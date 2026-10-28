## Introduction

触发（trigger）是调度中心唯一对外发起的动作：把"某个 jobId 该跑一次"翻译成"向某台执行器发一个 HTTP 请求"，并在数据库里留下完整过程记录。本篇展开触发链路的三个组件——`JobTriggerPoolHelper`（快慢池与降级）、`JobTrigger`（分片展开与日志先行）、`JobTrigger.processTrigger`（六步执行）。

源码基线 tag `3.5.0`。调度时刻由谁决定见 [Scheduler](/docs/CS/Framework/Job/xxl-job/Scheduler.md)，地址怎么选见 [Route Strategy](/docs/CS/Framework/Job/xxl-job/Route_Strategy.md)，请求到达执行器后怎么处理见 [Executor](/docs/CS/Framework/Job/xxl-job/Executor.md)。

## Trigger Pool

### Fast and Slow

调度线程池拆成 fast / slow 两个，目的是**让慢任务不拖垮快任务**：

```java
fastTriggerPool = new ThreadPoolExecutor(
        10,
        XxlJobAdminBootstrap.getInstance().getTriggerPoolFastMax(),
        60L, TimeUnit.SECONDS,
        new LinkedBlockingQueue<Runnable>(2000), ...);

slowTriggerPool = new ThreadPoolExecutor(
        10,
        XxlJobAdminBootstrap.getInstance().getTriggerPoolSlowMax(),
        60L, TimeUnit.SECONDS,
        new LinkedBlockingQueue<Runnable>(5000), ...);
```

| 池 | 核心 | 最大（默认） | 队列 | 拒绝策略 |
| :--- | :--- | :--- | :--- | :--- |
| fast | 10 | 300（`< 200` 时兜底 200） | 2000 | 记 error 丢弃 |
| slow | 10 | 200（`< 100` 时兜底 100） | 5000 | 记 error 丢弃 |

慢池队列（5000）比快池（2000）更长、最大线程更小——慢任务本就耗时长，更耐排队；快池满意味着调度侧已经过载，应快速暴露而不是缓冲。两个池的拒绝策略都不是抛异常或阻塞调用方，而是**记日志丢弃**：一次触发丢了可以靠下次调度或 misfire 补，把扫库线程堵死才是灾难。

### Degradation

降级判定是滑动窗口，按 jobId 独立计数：

```java
public void trigger(final int jobId, final TriggerTypeEnum triggerType, final int failRetryCount,
                    final String executorShardingParam, final String executorParam, final String addressList) {

    // choose thread pool
    ThreadPoolExecutor triggerPool_ = fastTriggerPool;
    AtomicInteger jobTimeoutCount = jobTimeoutCountMap.get(jobId);
    if (jobTimeoutCount!=null && jobTimeoutCount.get() > 10) {      // job-timeout 10 times in 1 min
        triggerPool_ = slowTriggerPool;
    }

    triggerPool_.execute(new Runnable() {
        public void run() {
            long start = System.currentTimeMillis();
            try {
                XxlJobAdminBootstrap.getInstance().getJobTrigger()
                    .trigger(jobId, triggerType, failRetryCount, executorShardingParam, executorParam, addressList);
            } finally {
                // check timeout-count-map
                long minTim_now = System.currentTimeMillis()/60000;
                if (minTim != minTim_now) {
                    minTim = minTim_now;
                    jobTimeoutCountMap.clear();
                }
                // incr timeout-count-map
                long cost = System.currentTimeMillis()-start;
                if (cost > 500) {       // ob-timeout threshold 500ms
                    AtomicInteger timeoutCount = jobTimeoutCountMap.putIfAbsent(jobId, new AtomicInteger(1));
                    if (timeoutCount != null) { timeoutCount.incrementAndGet(); }
                }
            }
        }
    });
}
```

规则：单次触发耗时 > 500ms 记一次超时；1 分钟窗口内同一 jobId 超时 > 10 次，后续触发改走 slow 池；跨分钟自动清空计数。

两个实现细节值得注意：

- **清空计数由"下一次触发"驱动**（在 `finally` 里比对分钟数），任务停摆后旧计数最多残留一个分钟窗口，不会永久占用内存。
- **降级是单向的**：一旦降级只能等分钟窗口翻页后计数清零才回到 fast 池，没有"慢池里跑快了就升回去"的逻辑。

> [!NOTE]
>
> 此处的 500ms 是**调度中心侧一次触发动作的耗时**（含路由探测 + HTTP 往返），不是任务执行耗时。任务跑多久不影响这个计数——除非 `FAILOVER` / `BUSYOVER` 这类需要逐台探测的路由策略把 HTTP 往返拖长。

## Trigger Dispatch

### Sharding Expand

`JobTrigger.trigger()` 先决定"这次要发几个请求"：

```java
if (ExecutorRouteStrategyEnum.SHARDING_BROADCAST == ExecutorRouteStrategyEnum.match(jobInfo.getExecutorRouteStrategy(), null)
        && group.getRegistryList()!=null && !group.getRegistryList().isEmpty()
        && shardingParam==null) {
    for (int i = 0; i < group.getRegistryList().size(); i++) {
        processTrigger(group, jobInfo, finalFailRetryCount, triggerType, triggerTime, i, group.getRegistryList().size());
    }
} else {
    if (shardingParam == null) {
        shardingParam = new int[]{0, 1};
    }
    processTrigger(group, jobInfo, finalFailRetryCount, triggerType, triggerTime, shardingParam[0], shardingParam[1]);
}
```

- **分片广播**：按在线机器数展开成 N 次 `processTrigger`，每次一个分片下标，各自生成独立的 logId → N 条日志、N 次回调。
- **非分片**：固定 `0/1`。
- **重试场景**：`executorShardingParam` 非 null 时（形如 `"2/5"`）只重发那一个分片，不会重新广播——这保证失败重试只补失败的那一台。

`failRetryCount < 0` 表示"用任务配置里的值"，`>= 0` 表示用传入值（失败重试时传入 `剩余次数 - 1`，逐次递减）。

### Six Steps

`processTrigger` 是触发的全部逻辑，六步线性执行：

```java
// 1、save log-id
XxlJobLog jobLog = new XxlJobLog();
jobLog.setJobGroup(jobInfo.getJobGroup());
jobLog.setJobId(jobInfo.getId());
jobLog.setTriggerTime(triggerTime);
xxlJobLogMapper.save(jobLog);

// 2、init trigger-param
TriggerRequest triggerParam = new TriggerRequest();
triggerParam.setJobId(jobInfo.getId());
...
triggerParam.setLogId(jobLog.getId());
triggerParam.setBroadcastIndex(index);
triggerParam.setBroadcastTotal(total);

// 3、init address
String address = null;
if (group.getRegistryList()!=null && !group.getRegistryList().isEmpty()) {
    if (ExecutorRouteStrategyEnum.SHARDING_BROADCAST == executorRouteStrategyEnum) {
        address = (index < group.getRegistryList().size())
                ? group.getRegistryList().get(index)
                : group.getRegistryList().get(0);
    } else {
        routeAddressResult = executorRouteStrategyEnum.getRouter().route(triggerParam, group);
        if (routeAddressResult.isSuccess()) { address = routeAddressResult.getData(); }
    }
} else {
    routeAddressResult = Response.of(XxlJobContext.HANDLE_CODE_FAIL, I18nUtil.getString("jobconf_trigger_address_empty"));
}

// 4、trigger remote executor
Response<String> triggerResult = (address != null)
        ? doTrigger(triggerParam, address, group)
        : Response.of(XxlJobContext.HANDLE_CODE_FAIL, "Address Router Fail.");

// 5、collection trigger info  → 拼 triggerMsgSb

// 6、save log trigger-info
jobLog.setExecutorAddress(address);
jobLog.setTriggerCode(triggerResult.getCode());
jobLog.setTriggerMsg(triggerMsgSb.toString());
xxlJobLogMapper.updateTriggerInfo(jobLog);
```

**第 1 步的"日志先行"是整个可靠性设计的支点**：

1. logId 在任何网络动作之前生成并落库，随 `TriggerRequest` 下发到执行器；
2. 执行器回调时带 logId 回来，调度中心能精确对号入座（见 [Log And Alarm](/docs/CS/Framework/Job/xxl-job/Log_And_Alarm.md)）；
3. 执行器侧用 logId 做触发去重（见 [Block Strategy](/docs/CS/Framework/Job/xxl-job/Block_Strategy.md)）；
4. 即使执行器整个不可达，调度中心仍留下一条 `trigger_code = 500` 的记录，可观测、可告警。

分片广播的取址逻辑有个细节：`index >= registryList.size()` 时退回第 0 台。这处理"扫描时 5 台、路由时缩到 3 台"的竞态——宁可让第 0 台多跑一个分片，也不让分片丢掉。

### Remote Invocation

```java
private Response<String> doTrigger(TriggerRequest triggerParam, String address, XxlJobGroup jobGroup){
    try {
        // build client
        ExecutorBiz executorBiz = XxlJobAdminBootstrap.getExecutorBiz(address, jobGroup);
        // invoke
        Response<String> runResult = executorBiz.trigger(triggerParam);
        ...
    } catch (Exception e) {
        logger.error(">>>>>>>>>>> xxl-job trigger error, please check if the executor[{}] is running.", address, e);
        return Response.of(XxlJobContext.HANDLE_CODE_FAIL, ThrowableTool.toString(e));
    }
}
```

客户端由 `XxlJobAdminBootstrap.getExecutorBiz(address, jobGroup)` 按 `address|accessToken|appname` 三元组缓存（上限 1000，超限整体清空），连接/读超时取 `xxl.job.timeout`（默认 3s）。鉴权与协议细节见 [OpenAPI](/docs/CS/Framework/Job/xxl-job/OpenAPI.md)。

### Trigger Log Content

第 5 步拼的 `trigger_msg` 是排障时最有价值的一段文本，它把**决策过程**而非只有结果写进日志：调度类型、调度中心 IP、执行器地址类型（自动注册 / 手动录入）、在线机器地址列表、路由策略、分片参数、阻塞策略、超时时间、失败重试次数、实际选中的地址、JobHandler 名、任务参数、执行器返回的 code 与 msg。

路由失败时的文案区分了两种情况：注册表为空（"地址为空"）与 router 返回失败（把 router 的失败原因一并带上，比如 `BUSYOVER` 会列出逐台 `idleBeat` 的结果）。

## Trigger Types

| 类型 | 触发来源 | 备注 |
| :--- | :--- | :--- |
| `CRON` | 时间轮 / 扫库到期 | 常规周期调度 |
| `MANUAL` | 管理后台手动触发 | |
| `RETRY` | 失败重试 | `JobFailAlarmMonitorHelper` 发起，带剩余重试次数 |
| `PARENT` | 父任务触发子任务 | `JobCompleter` 在父任务成功后发起 |
| `API` | OpenAPI `triggerJob` | 3.5.0 新增 |
| `MISFIRE` | 过期补偿 | `MisfireFireOnceNow` 发起 |

六种类型共用同一条链路，区别只在写入日志的 `trigger_type` 文案——**没有独立的执行路径**，这也是 XXL-JOB 触发模型保持简单的原因。

## Links

- [xxl-job](/docs/CS/Framework/Job/xxl-job.md)
- [Registry And Discovery](/docs/CS/Framework/Job/xxl-job/Registry_And_Discovery.md)
- [Data Model](/docs/CS/Framework/Job/xxl-job/Data_Model.md)
- [GLUE](/docs/CS/Framework/Job/xxl-job/GLUE.md)
- [Job](/docs/CS/Framework/Job/Job.md)
- [Scheduled Task](/docs/CS/SE/Scheduled_Task.md)

## References

- [XXL-JOB 官方文档](http://www.xuxueli.com/xxl-job/)
- [XXL-JOB GitHub](https://github.com/xuxueli/xxl-job)
