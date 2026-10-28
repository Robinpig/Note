## Introduction

阻塞处理策略回答一个问题：**调度请求来得比执行器处理得快时怎么办**。XXL-JOB 的答案是"每个 jobId 一条专属线程 + 一个无界队列"，把并发问题转成队列问题，再用三种策略约定队列的行为。

这一篇也是理解执行器并发模型的入口：`JobThread` 是 XXL-JOB 里唯一的任务执行载体，阻塞策略、超时控制、触发去重、优雅停机全部挂在它身上。请求怎么进来见 [Executor](/docs/CS/Framework/Job/xxl-job/Executor.md)，调度侧怎么发起见 [Trigger](/docs/CS/Framework/Job/xxl-job/Trigger.md)。

源码基线 tag `3.5.0`，核心类 `com.xxl.job.core.thread.JobThread`、`com.xxl.job.core.constant.ExecutorBlockStrategyEnum`。

## Job Thread Model

```java
public class JobThread extends Thread{
    private final int jobId;
    private final IJobHandler handler;
    private final LinkedBlockingQueue<TriggerRequest> triggerQueue;
    private final Set<Long> triggerLogIdSet;        // avoid repeat trigger for the same TRIGGER_LOG_ID

    private volatile boolean toStop = false;
    private String stopReason;
    private boolean running = false;                // if running job
    private int idleTimes = 0;                      // idle times

    public JobThread(int jobId, IJobHandler handler) {
        this.jobId = jobId;
        this.handler = handler;
        this.triggerQueue = new LinkedBlockingQueue<>();
        this.triggerLogIdSet = ConcurrentHashMap.newKeySet();
        this.setName("xxl-job, JobThread-"+jobId+"-"+System.currentTimeMillis());
    }
}
```

仓库里两张 Map 维护全部运行态（`XxlJobExecutor` 字段）：

| 仓库 | 键 | 值 | 说明 |
| :--- | :--- | :--- | :--- |
| `jobHandlerRepository` | handler 名 | `IJobHandler` | 启动时扫描注册，全进程共享 |
| `jobThreadRepository` | jobId | `JobThread` | 按需创建，每个 jobId 至多一条 |

**"一 job 一线程"是这个模型的核心**：同一 jobId 的触发请求永远进同一条线程的同一队列，天然串行；不同 jobId 之间互不影响，各自一条线程。所以 XXL-JOB 不需要业务方自己做单机串行控制——默认就是串行的。

代价也直接：job 数量 × 每条线程 = 常驻线程数。这也是下面"空闲销毁"必须存在的原因。

## Trigger Dedup

```java
public Response<String> pushTriggerQueue(TriggerRequest triggerParam) {
    // avoid repeat
    if (!triggerLogIdSet.add(triggerParam.getLogId())) {
        return Response.of(XxlJobContext.HANDLE_CODE_FAIL, "repeat trigger job, logId:" + triggerParam.getLogId());
    }

    // push trigger queue
    triggerQueue.add(triggerParam);
    return Response.ofSuccess();
}
```

`triggerLogIdSet` 做**触发请求去重**：调度中心重试、网络重发、人工重复点击导致的同 logId 重复触发会被拒绝。注意去重窗口是"从入队到被取出执行"——取出时就 `remove` 掉了：

```java
triggerParam = triggerQueue.poll(3L, TimeUnit.SECONDS);
if (triggerParam != null) {
    triggerLogIdSet.remove(triggerParam.getLogId());
    ...
}
```

所以去重只防"同一时刻重复投递"，不防"上次跑完后又来一次同 logId"（那本来也不该发生，logId 是自增主键）。

入队即返回成功，**执行是异步的**：调度中心拿到 200 只代表"执行器收下了"，不代表"任务跑完了"。真正的执行结果靠回调（见 [Log And Alarm](/docs/CS/Framework/Job/xxl-job/Log_And_Alarm.md)）。

## Block Strategy

判定发生在 `ExecutorBizImpl.trigger()` 里，**入队之前**：

```java
// executor block strategy
if (jobThread != null) {
    ExecutorBlockStrategyEnum blockStrategy = ExecutorBlockStrategyEnum.match(triggerRequest.getExecutorBlockStrategy(), null);
    if (ExecutorBlockStrategyEnum.DISCARD_LATER == blockStrategy) {
        // discard when running
        if (jobThread.isRunningOrHasQueue()) {
            return Response.of(XxlJobContext.HANDLE_CODE_FAIL, "block strategy effect："+ExecutorBlockStrategyEnum.DISCARD_LATER.getTitle());
        }
    } else if (ExecutorBlockStrategyEnum.COVER_EARLY == blockStrategy) {
        // kill running jobThread
        if (jobThread.isRunningOrHasQueue()) {
            removeOldReason = "block strategy effect：" + ExecutorBlockStrategyEnum.COVER_EARLY.getTitle();
            jobThread = null;
        }
    } else {
        // just queue trigger
    }
}

// replace thread (new or exists invalid)
if (jobThread == null) {
    jobThread = XxlJobExecutor.getInstance().registJobThread(triggerRequest.getJobId(), jobHandler, removeOldReason);
}

// push data to queue
return jobThread.pushTriggerQueue(triggerRequest);
```

判据是 `isRunningOrHasQueue()`：`running || !triggerQueue.isEmpty()`——**正在跑或队列里还有活**，都算"忙"。

| 策略 | `jobThread == null`（首次触发） | 忙时行为 | 不忙时行为 |
| :--- | :--- | :--- | :--- |
| `SERIAL_EXECUTION` | 建线程 | 直接入队排队 | 入队 |
| `DISCARD_LATER` | 建线程 | **返回失败**，不入队 | 入队 |
| `COVER_EARLY` | 建线程 | 置 `jobThread = null` → 重建线程（旧线程被 kill） | 入队 |

`COVER_EARLY` 的实现方式是"重建线程"而非"中断当前任务"：`registJobThread` 会把旧线程 `toStop + interrupt`，新请求进的是全新线程。被中断的旧线程在 `run()` 的 `finally` 里回调一条 `HANDLE_CODE_FAIL` + `stopReason + " [job running, killed]"`。

`CONCURRENT_EXECUTION`（并行执行）在枚举中已被注释，3.5.0 不可用。这意味着**无论选哪种策略，同一 jobId 都不会并行**——想并行只能靠分片广播把任务拆到多台机器上。

### Handler Hot Swap

阻塞判定之前还有一段"handler 是否变了"的校验，它同样会导致线程重建：

- **BEAN 模式**：比较 `jobThread.getHandler() != newJobHandler`（实例引用），变了就重建；
- **GLUE / 脚本模式**：比较 handler 类型与 `glueUpdatetime`，源码更新了就重建。

三条 `removeOldReason` 文案分别对应 "change jobhandler or glue type" / "change job source or glue type" / "change script or glue type"。这是 GLUE 在线改代码能即时生效的机制，详见 [GLUE](/docs/CS/Framework/Job/xxl-job/GLUE.md)。

## Run Loop

```java
public void run() {
    // invoke init-method, only once
    try { handler.init(); } catch (Throwable e) { logger.error(e.getMessage(), e); }

    while(!toStop){
        running = false;
        idleTimes++;

        TriggerRequest triggerParam = null;
        try {
            // to check toStop signal, we need cycle, so we cannot use queue.take(), instead of poll(timeout)
            triggerParam = triggerQueue.poll(3L, TimeUnit.SECONDS);
            if (triggerParam != null) {
                running = true;
                idleTimes = 0;
                triggerLogIdSet.remove(triggerParam.getLogId());
                ...
            } else {
                if (idleTimes > 30) {
                    if (triggerQueue.isEmpty()) {   // avoid concurrent trigger causes jobId-lost
                        XxlJobExecutor.getInstance().removeJobThread(jobId, "excutor idle times over limit.");
                    }
                }
            }
        } catch (Throwable e) { ... }
        finally { ...callback... }
    }
    ...
}
```

三个关键设计：

1. **用 `poll(3s)` 而非 `take()`**：必须周期性醒来检查 `toStop` 标志。`Thread.interrupt()` 只能打断阻塞态，打断不了正在跑的业务代码，所以停线程靠的是共享变量 + 定时轮询。
2. **空闲 30 次 × 3s = 90s 自我销毁**：`removeJobThread` 把自己从 `jobThreadRepository` 摘掉。这是防止 job 数量多时常驻线程无限增长的关键。销毁前再判一次 `triggerQueue.isEmpty()` 防并发竞态（刚摘掉就有新触发进来，会导致该触发找不到线程——但下一次触发会重建，最多丢一次）。
3. **`handler.init()` / `handler.destroy()` 各调一次**，对应 `@XxlJob(init/destroy)` 指定的方法。

### Timeout Control

```java
if (triggerParam.getExecutorTimeout() > 0) {
    Thread futureThread = null;
    try {
        FutureTask<Boolean> futureTask = new FutureTask<Boolean>(new Callable<Boolean>() {
            public Boolean call() throws Exception {
                XxlJobContext.setXxlJobContext(xxlJobContext);   // 新线程要重新绑定 ThreadLocal
                handler.execute();
                return true;
            }
        });
        futureThread = new Thread(futureTask);
        futureThread.setName("xxl-job, JobThread-future-"+jobId+"-"+System.currentTimeMillis());
        futureThread.start();

        Boolean tempResult = futureTask.get(triggerParam.getExecutorTimeout(), TimeUnit.SECONDS);
    } catch (TimeoutException e) {
        XxlJobHelper.log("<br>----------- xxl-job job execute timeout");
        XxlJobHelper.handleTimeout("job execute timeout ");
    } finally {
        futureThread.interrupt();
    }
} else {
    // just execute
    handler.execute();
}
```

超时开启时（任务配置 `executor_timeout > 0`）会**额外起一条线程**跑业务，主线程 `futureTask.get(timeout)` 等待；超时则记录 `HANDLE_CODE_TIMEOUT`（502）并 interrupt 子线程。

这里有两个容易踩的坑：

- `XxlJobContext` 是 **ThreadLocal**，所以子线程里必须重新 `setXxlJobContext`。业务代码里用 `XxlJobHelper.log()` 走的就是这个上下文，漏了绑定日志会写错文件。
- `futureThread.interrupt()` **只是发中断信号**，如果业务代码不响应中断（不看 `Thread.interrupted()`、不响应 `InterruptedException`），子线程会继续跑到自己结束。XXL-JOB 的超时是"我不等了"而不是"我杀掉你"。

### Result Normalization

```java
if (XxlJobContext.getXxlJobContext().getHandleCode() <= 0) {
    XxlJobHelper.handleFail("job handle result lost.");
} else {
    String tempHandleMsg = XxlJobContext.getXxlJobContext().getHandleMsg();
    tempHandleMsg = (tempHandleMsg!=null && tempHandleMsg.length()>50000)
            ? tempHandleMsg.substring(0, 50000).concat("...")
            : tempHandleMsg;
    XxlJobContext.getXxlJobContext().setHandleMsg(tempHandleMsg);
}
```

**业务代码不显式调用 `handleSuccess()` 会被判为失败**（"job handle result lost."）。这是新手最常见的"任务明明跑完了却显示失败"的原因。`handleMsg` 截断阈值 50000 字符。

### Callback and Kill

```java
finally {
    if (triggerParam != null) {
        if (!toStop) {
            // common
            pushCallBack(new CallbackData(logId, logDateTime, handleCode, handleMsg));
        } else {
            // is killed
            pushCallBack(new CallbackData(logId, logDateTime, HANDLE_CODE_FAIL,
                    stopReason + " [job running, killed]"));
        }
    }
}
```

主线程 `while` 结束（收到 `toStop`）后，还有一段收尾：

```java
// callback trigger request in queue
while (triggerQueue != null && !triggerQueue.isEmpty()){
    TriggerRequest triggerParam = triggerQueue.poll();
    if (triggerParam != null) {
        pushCallBack(new CallbackData(triggerParam.getLogId(), triggerParam.getLogDateTime(),
                XxlJobContext.HANDLE_CODE_FAIL,
                stopReason + " [job not executed, in the job queue, killed.]"));
    }
}
// invoke destroy-method, only once
try { handler.destroy(); } catch (Throwable e) { ... }
```

**队列里未执行的触发不会被静默丢弃**，而是逐条回调失败并附原因 `[job not executed, in the job queue, killed.]`。这让调度中心能区分"跑过但失败"与"压根没跑"，对 `kill` 操作和 `COVER_EARLY` 的排障很关键。

## Selection Guide

| 场景 | 推荐 | 理由 |
| :--- | :--- | :--- |
| 定时报表、批处理，允许排队 | `SERIAL_EXECUTION` | 不丢任务，靠队列吸收抖动；注意队列无界，长期积压会内存增长 |
| 高频采集，只关心最新一次 | `COVER_EARLY` | 丢弃旧的执行，用新数据；代价是被中断的那次记为失败 |
| 幂等统计，重复跑无意义 | `DISCARD_LATER` | 忙时直接拒，调度中心记为触发失败，可配告警 |
| 任务耗时长于调度间隔且必须每次都跑 | 无解，需改设计 | 三种策略都不支持并行；应改用分片广播 + 多台机器，或拉长间隔 |

> [!WARNING]
>
> `triggerQueue` 是**无界** `LinkedBlockingQueue`。`SERIAL_EXECUTION` 下如果持续入队速度大于出队速度，队列会一直增长直到 OOM，且没有任何阈值告警。这是选型 `SERIAL_EXECUTION` 时必须评估的风险——要么保证执行耗时稳定小于调度间隔，要么用 `DISCARD_LATER` / `COVER_EARLY` 主动丢弃。

## Links

- [xxl-job](/docs/CS/Framework/Job/xxl-job.md)
- [Scheduler](/docs/CS/Framework/Job/xxl-job/Scheduler.md)
- [Route Strategy](/docs/CS/Framework/Job/xxl-job/Route_Strategy.md)
- [Registry And Discovery](/docs/CS/Framework/Job/xxl-job/Registry_And_Discovery.md)
- [Data Model](/docs/CS/Framework/Job/xxl-job/Data_Model.md)
- [Job](/docs/CS/Framework/Job/Job.md)

## References

- [XXL-JOB 官方文档](http://www.xuxueli.com/xxl-job/)
- [XXL-JOB GitHub](https://github.com/xuxueli/xxl-job)
