## Introduction

四种执行模式是 PowerJob 区别于纯调度器的核心能力。但"执行"这件事在 PowerJob 里是**两级派发**：Server 只把一个 instance 派给被选中的 Master Worker，真正的子任务分发由该 Worker 侧的 `TaskTracker` 协调到集群里其他 Worker。本文以 `powerjob-server/.../core/DispatchService.java` 与 `powerjob-worker/.../actors/TaskTrackerActor.java`、`core/tracker/task/{light,heavy}`（4.3.9）为据，拆解这条链路。

## ExecuteType

执行模式由 `ExecuteType` 枚举定义（`powerjob-common/.../enums/ExecuteType.java:18-27`）：

| 枚举 | 值 | 中文 |
| :--- | :--- | :--- |
| `STANDALONE` | 1 | 单机执行 |
| `BROADCAST` | 2 | 广播执行（集群内每个 worker 各跑一遍） |
| `MAP_REDUCE` | 3 | Map 后汇总 |
| `MAP` | 4 | 仅 Map 分发 |

## Two-level Dispatch

### Server side: pick the Master Worker

`DispatchService.dispatch(...)`（`DispatchService.java:101-184`）不直接决定"任务落到哪台机器执行每个分片"，而是决定"这次 instance 交给哪台 Worker 当 Master"：

1. `workerClusterQueryService.geAvailableWorkers(jobInfo)` 取可用 worker 列表（`:151`）；
2. `filterOverloadWorker(...)` 剔除超载节点（`:161`）；
3. `taskTrackerSelectorService.select(jobInfo, instanceInfo, suitableWorkers)` 按 `jobInfo.getDispatchStrategy()` 选出一个 `TaskTracker` 地址（`:173`）；
4. `transportService.tell(workerUrl, req)` 把整个 `ServerScheduleJobReq` 发给这台 Master Worker（`:176-177`）。

`TaskTrackerSelectorService.select`（`powerjob-server-remote/.../selector/TaskTrackerSelectorService.java:29-32`）用 `Map<Integer, TaskTrackerSelector>` 按 `DispatchStrategy` 取实现，三种策略见 `powerjob-common/.../enums/DispatchStrategy.java`：**`HEALTH_FIRST(1)`（默认）、`RANDOM(2)`、`SPECIFY(11)`**。`SPECIFY` 即用户在任务里写死目标 worker 地址。

### Worker side: Light vs Heavy

被选中的 Master Worker 收到请求后，由 `TaskTrackerActor.onReceiveServerScheduleJobReq` 决定用哪种 `TaskTracker`（`TaskTrackerActor.java:122-157`）——关键判定 `isLightweightTask(req)`（`:212-221`）：

```java
private boolean isLightweightTask(ServerScheduleJobReq req) {
    final ExecuteType executeType = ExecuteType.valueOf(req.getExecuteType());
    if (executeType != ExecuteType.STANDALONE) return false;   // 非单机 → 必为 Heavy
    TimeExpressionType t = TimeExpressionType.valueOf(req.getTimeExpressionType());
    return t != FIXED_DELAY && t != FIXED_RATE;                 // 单机+FIXED_* → 也是 Heavy
}
```

由此得到精确映射：

| 条件 | TaskTracker | 含义 |
| :--- | :--- | :--- |
| `STANDALONE` 且非 `FIXED_RATE/FIXED_DELAY` | `LightTaskTracker` | 单机 / 广播模式的一次性执行 |
| `BROADCAST` / `MAP` / `MAP_REDUCE` | `HeavyTaskTracker` | 需要拆分子任务 |
| `STANDALONE` + `FIXED_RATE` / `FIXED_DELAY` | `HeavyTaskTracker` | 秒级循环任务也走 Heavy（需循环执行机制） |

两个 `TaskTracker` 都有过载保护：Light 受 `MaxLightweightTaskNum`、Heavy 受 `MaxHeavyweightTaskNum` 约束，超限直接忽略本次请求（`TaskTrackerActor.java:133-156`）。

## HeavyTaskTracker and ProcessorTracker

`HeavyTaskTracker`（`core/tracker/task/heavy/HeavyTaskTracker.java`）负责 Map/MapReduce：把任务拆成若干 sub-task，通过 `TaskTrackerActor` 的 `WTT_HANDLER_MAP_TASK` 路径（`TaskTrackerActor.java:108`）分发到其他 Worker；每台接收方 Worker 起一个 `ProcessorTracker`（`core/tracker/processor/ProcessorTracker.java`，注释"负责管理 Processor 的执行"）真正跑处理器，子任务执行用 `HeavyProcessorRunnable`。Reduce 阶段由 `HeavyTaskTracker` 汇总各 `ProcessorTracker` 的结果。

开发者只需实现 `MapReduceProcessor` 寥寥数行即可获得分布式计算能力——这正是 PowerJob 把"调度"与"轻量分布式计算"合一的落点。`#1102` 还支持 Worker 自定义运行时核心数。

## 5.x 待确认

- 以上 Server→Master Worker→ProcessorTracker 两级链路在 4.3.9 已完整验证。
- 5.1.7 修复了"Worker 锁中断"等问题（见枢纽页 Processors 版本事实），属 Worker 侧健壮性修复，不改变两级派发骨架。
- MU 协议下（5.1.x）worker 可主动访问 server，是**通讯方向**的变化，不影响本文描述的派发层级。

## Links

- [PowerJob](/docs/CS/Framework/Job/PowerJob.md)
- [Scheduling](/docs/CS/Framework/Job/PowerJob/Scheduling.md)
- [Workflow](/docs/CS/Framework/Job/PowerJob/Workflow.md)
- [Job](/docs/CS/Framework/Job/Job.md)

## References

- [PowerJob GitHub](https://github.com/PowerJob/PowerJob)
- [PowerJob 官方文档](https://www.yuque.com/powerjob/guidence/intro)
