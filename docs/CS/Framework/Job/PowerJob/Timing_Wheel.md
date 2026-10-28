## Introduction

PowerJob 的调度精度由自研时间轮保证。但"时间轮"这个词在流传中常被误写成"分层秒/分/时三级轮"——**源码里它是一颗单层哈希轮**。本文以 `powerjob-server/powerjob-server-common/.../common/timewheel/HashedWheelTimer.java` 与同目录 `holder/InstanceTimeWheelService.java`（4.3.9）为据，逐行拆解它的结构与降级策略，并标出 5.x 新增的第四个轮。

## Single-layer Hashed Wheel

`HashedWheelTimer` 的核心字段只有三个：`tickDuration`（每格毫秒数）、`wheel`（哈希桶数组）、`mask`（桶数 − 1）（`HashedWheelTimer.java:28-30`）。它**不是** Netty 那种多层分级时间轮，而是一颗「哈希轮」：

- **轮盘大小格式化为 2 的 N 次方**：`int ticksNum = CommonUtils.formatSize(ticksPerWheel)`，用 `mask = wheel.length - 1` 配合 `& mask` 代替取余（`:56-61`、`:300`）；
- **最小精度 1ms、误差 1ms**：javadoc 明写"Thread.sleep 本身不精确导致精度没法提高"（`:19-20`），与 Netty `HashedWheelTimer` 同源思想；
- **后台指针线程** `Indicator`（`:223`）：每个 tick 依次做四件事——`pushTaskToBucket()`（队列任务入桶）、`processCanceledTasks()`（清理取消任务）、`tickTack()`（按 `tickDuration` sleep 到下一刻度）、`expireTimerTasks(tick)`（执行到点的任务）；
- **取消**通过 `canceledTasks` 队列 + `bucket.remove` 完成（`:149-156`、`:271-282`），`status` 区分 WAITING / RUNNING / FINISHED / CANCELED。

> [!WARNING]
>
> 本笔记早期版本写"分层时间轮：第一层秒级 60 槽、第二层分钟级 60 槽、第三层小时级 24 槽，任务到期逐级降级"——**该描述与源码不符**。当前实现是单层哈希轮 + 精确/慢速双轮 + 长延迟降级（`InstanceTimeWheelService.java`）。三层 60/60/24 的说法无法在 PowerJob 任何版本源码里得到印证，以此为准会写错取消与降级的全部边界条件。

## Three Wheels

`InstanceTimeWheelService` 同时持有两颗轮（`InstanceTimeWheelService.java:25-38`）：

| 轮 | 构造参数 | 用途 |
| :--- | :--- | :--- |
| 精确轮 `TIMER` | `new HashedWheelTimer(1, 4096, CPU核数 × 4)` | 每 1ms 走一格、4096 槽、独立线程池（核数×4，`CallerRun` 拒绝策略） |
| 慢轮 `SLOW_TIMER` | `new HashedWheelTimer(10000, 12, 0)` | 每 10s 走一格、12 槽，无独立线程池 |
| （非精确轮 `INACCURATE_TIMER`） | `new HashedWheelTimer(5000, 16, 0)`（`HashedWheelTimerHolder`） | **5.x 新增**，4.3.9 源码中不存在，详见下方「5.x 待确认」 |

精确轮的线程池在 `HashedWheelTimer` 构造时按核数×4 建（`HashedWheelTimer.java:70-74`），队列上限 8192，拒绝策略 `RejectedExecutionHandlerFactory.newCallerRun("PowerJobTimeWheelPool")`——即线程池满时由调用线程（指针线程）直接执行，**保证到点任务不被丢弃**。

## Long-delay Degradation

长短延迟的分流在 `InstanceTimeWheelService.schedule`（`:46-58`）：

- 延迟 ≤ `LONG_DELAY_THRESHOLD_MS`（**60000**，即 60s）：直接进精确轮；
- 延迟 > 60s：先进慢轮，到期前 60s（`expectTriggerTime - now`）再转入精确轮——**避免为少量远未来任务占用 4096 槽的精确轮**；
- 取消表 `CARGO`：`MIN_INTERVAL_MS = 1000` 以下的任务不入表（太近来不及取消），`fetchTimerFuture(uniqueId)` 供停止任务时取消（`:34`、`:65-78`）。

也就是说，一个"2 小时后触发"的任务，前 119 分钟躺在慢轮里只占 1 个槽，最后 1 分钟才升入精确轮——精确轮的 4096 槽资源被优先留给近未来任务。

## 5.x 待确认

- **`INACCURATE_TIMER`**：笔记旧版与部分 5.x 资料提到 `HashedWheelTimerHolder` 持有第三颗"非精确轮"`new HashedWheelTimer(5000, 16, 0)`。本机源码是 4.3.9，**`InstanceTimeWheelService` 里只有 `TIMER` 与 `SLOW_TIMER` 两颗轮，没有 `INACCURATE_TIMER`**——这是 5.x 新增项，需回 v5.1.7 源码 (`holder/HashedWheelTimerHolder.java`) 确认其是否真的存在、以及它服务于哪个场景（推测用于容忍秒级误差的批量通知类任务）。
- 5.1.x 在时间轮这一层的核心变化是 **MU 协议下 worker 主动拉取到期任务**（见枢纽页 Architecture），时间轮本身的单哈希轮结构在 4.x→5.x 保持稳定。

## Links

- [PowerJob](/docs/CS/Framework/Job/PowerJob.md)
- [Scheduling](/docs/CS/Framework/Job/PowerJob/Scheduling.md)
- [Timing Strategies](/docs/CS/Framework/Job/PowerJob/Timing_Strategies.md)
- [Scheduled Task](/docs/CS/SE/Scheduled_Task.md)

## References

- [PowerJob GitHub](https://github.com/PowerJob/PowerJob)
- [Netty HashedWheelTimer（同源思想）](https://github.com/netty/netty)
