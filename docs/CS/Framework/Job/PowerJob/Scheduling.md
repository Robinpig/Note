## Introduction

PowerJob 的调度主流程集中在 Server 端的 `PowerScheduleService`。它的设计目标只有一个：**以最低的数据库压力，保证"未来 30 秒内该触发的任务"都被捞出来、先落库、再精准投递到时间轮**。本文所有断言以本机源码 `powerjob-server/powerjob-server-core/.../core/scheduler/PowerScheduleService.java`（4.3.9）为据，路径:行号随文给出；5.x 新增项见枢纽页「版本与核实口径」。

## Schedule Loop

调度不是一个长事务，而是**每 15 秒跑一次的扫描循环**。`PowerScheduleService` 暴露三个入口，分别由三个独立定时器按同一周期驱动：

| 入口方法 | 负责的表达式类型 | 源码行 |
| :--- | :--- | :--- |
| `scheduleNormalJob(TimeExpressionType)` | `CRON`、`DAILY_TIME_INTERVAL` | `PowerScheduleService.java:71` |
| `scheduleCronWorkflow()` | 工作流的 `CRON` 触发 | `PowerScheduleService.java:91` |
| `scheduleFrequentJob()` | `FIXED_RATE`、`FIXED_DELAY` | `PowerScheduleService.java:112` |

三个方法共享同一个常量 `SCHEDULE_RATE = 15000`（`PowerScheduleService.java:68`）——即 15 秒。`scheduleNormalJob0` / `scheduleWorkflowCore` / `scheduleFrequentJobCore` 各自跑完后会检查耗时，一旦 `cost > SCHEDULE_RATE` 就打 `warn`："数据库查询耗时过高，请检查数据库负载"（`:86-88`、`:106-108`、`:127-129`）。这条 warn 是判断"调度瓶颈在数据库"的直接信号。

## App-sharded Scan

与 XXL-JOB「全局扫表 + DB 锁」不同，PowerJob Server 是**多活但分片**的：每个 app 固定由绑定的 server 调度，集群共同分担而无需锁竞争。取本机负责哪些 app 的代码是：

```java
final List<Long> allAppIds = appInfoRepository.listAppIdByCurrentServer(
        transportService.defaultProtocol().getAddress());
```

（`PowerScheduleService.java:75`，`scheduleCronWorkflow` / `scheduleFrequentJob` 同形）。`defaultProtocol().getAddress()` 即当前 server 的地址——**app 与 server 的绑定关系靠 server 地址做分片键**，所以同一 app 的调度永远落在同一台 server 上，天然避免了多 server 重复调度。

拿到 app 列表后按 `MAX_APP_NUM = 10`（`PowerScheduleService.java:47`）分批并发：

```java
long timeThreshold = nowTime + 2 * SCHEDULE_RATE;   // 预读未来 30s
Lists.partition(appIds, MAX_APP_NUM).forEach(partAppIds -> { ... });
```

（`PowerScheduleService.java:153-154`）。`timeThreshold` 是把"下次触发时间 ≤ now + 30s"的到期任务一次性捞出来，给时间轮留足投递缓冲。

## Database-first Dispatch

调度最核心的一条纪律是**先落库、再调度**——调度记录必须先于调度动作写入，防止"时间轮到期了但实例记录丢失"。`scheduleNormalJob0` 的顺序是：

1. **批量建实例**：对每个到期 `JobInfoDO` 调 `instanceService.create(...)` 生成 Instance 记录（`:170`）；
2. **flush**：`instanceInfoRepository.flush()`（`:173`）——这一步把实例记录强制落库；
3. **推入时间轮**：`InstanceTimeWheelService.schedule(instanceId, delay, () -> dispatchService.dispatch(...))`（`:188`）；
4. **刷新下次触发时间**：`refreshJob(...)` 计算并写回 `nextTriggerTime`（`:194`）。

注意第 2 步在推轮之前。`dispatchService.dispatch` 内部还会二次校验实例状态（见 [Execution Modes](/docs/CS/Framework/Job/PowerJob/Execution_Modes.md)），已派发或已取消的直接跳过，因此即便时间轮到期与扫描重叠也不会重复执行。

## Design Reversal

源码注释里留着一次设计反复的痕迹，值得原样保留（`PowerScheduleService.java:32-34`）：

> 原：FIX_RATE 和 FIX_DELAY 任务不需要被调度，创建后直接被派发到 Worker 执行，只需要失败重试机制（在 `InstanceStatusCheckService` 中完成）。
> 先：那样写不太优雅，东一坨代码西一坨代码的，还是牺牲点性能统一调度算了（优雅，永不过时～ BY：青钢影）

所以当前**所有表达式类型都统一经时间轮驱动**。`scheduleFrequentJobCore`（`:243-287`）的做法也印证了这点：它只负责"挑出当前没在跑的秒级任务并触发"，真正的执行仍走 `jobService.runJob` → 时间轮。

## Workflow Cron

工作流的 CRON 触发走 `scheduleCronWorkflow` → `scheduleWorkflowCore`（`:208-241`），与任务调度同构：先 `workflowInstanceManager.create(wfInfo, null, nextTriggerTime, null)` 生成 workflow 实例记录（`:222`），再 `InstanceTimeWheelService.schedule(wfInstanceId, delay, () -> workflowInstanceManager.start(...))` 推轮（`:230`），最后 `refreshWorkflow` 写回下次触发时间（`:234`）。即工作流实例与任务实例共用同一套时间轮与实例体系。

## Links

- [PowerJob](/docs/CS/Framework/Job/PowerJob.md)
- [Timing Wheel](/docs/CS/Framework/Job/PowerJob/Timing_Wheel.md)
- [Execution Modes](/docs/CS/Framework/Job/PowerJob/Execution_Modes.md)
- [Job](/docs/CS/Framework/Job/Job.md)

## References

- [PowerJob GitHub](https://github.com/PowerJob/PowerJob)
- [PowerJob 官方文档](https://www.yuque.com/powerjob/guidence/intro)
