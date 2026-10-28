# Failover

## Introduction

ElasticJob 把"作业治理"归纳为三件套：**失效转移（failover）、错过作业重新执行（misfire）、自诊断修复（reconcile）**。三者都建立在 [Registry Center](/docs/CS/Framework/Job/ElasticJob/RegistryCenter.md) 的节点树之上，由 `kernel/internal/failover`、`kernel/internal/sharding`（`ShardingNode.MISFIRE`/`RUNNING`）与 `reconcile` 包协作完成。本文基于 `3.0.5` 源码展开，节点路径以 `FailoverNode` / `ShardingNode` 常量为准。

## Failover Mechanism

某实例崩溃时，其 `instances/{instanceId}` 临时节点随会话消失，`FailoverListenerManager` 监听到实例下线，对该实例"当时正在运行"的分片项（`sharding/{item}/running` 存在且归属该实例）调用 `FailoverService.setCrashedFailoverFlag(item)`，把待转移项写入 `leader/failover/items/{item}`。`FailoverService`（`kernel/internal/failover`）的关键方法（已核实）：

| 方法 | 作用 |
| :--- | :--- |
| `setCrashedFailoverFlag(int item)` | 标记分片项待失效转移，写 `leader/failover/items/{item}` |
| `failoverIfNecessary()` | 存在待转移项且本实例可用时触发转移执行 |
| `needFailover()` | 判断是否确有未分配的待转移项 |
| `isFailoverAssigned(Integer item)` | 该项是否已被某实例领走（防重复接管） |
| `getFailoverItems(jobInstanceId)` | 本实例领到的待转移项 |
| `getLocalFailoverItems()` | 本实例本地待转移项 |
| `updateFailoverComplete(Collection<Integer>)` | 转移完成后清理对应的 `leader/failover/items` 与 `sharding/{item}/failover` |
| `clearFailoveringItem(int)` / `removeFailoverInfo()` | 清理转移中状态与全部失效转移信息 |

存活实例通过 `sharding/{item}/failover`（持久，标记该项待转移）与 `sharding/{item}/failovering`（临时，标记正在被接管）协同，抢到转移项的实例以 `ExecutionSource.FAILOVER` 来源重新执行该分片。

```dot
digraph failover {
  rankdir=LR;
  node [shape=box, style="rounded,filled", fillcolor="#eef3fb", fontname="Helvetica"];
  crash [label="实例崩溃\ninstances/{id} 消失", fillcolor="#fdeccb"];
  flag [label="FailoverListenerManager\nsetCrashedFailoverFlag", fillcolor="#e4eef7"];
  queue [label="leader/failover/items/{item}", fillcolor="#efefef"];
  take [label="存活实例领走\nsharding/{item}/failovering", fillcolor="#e7f4e4"];
  run [label="以 FAILOVER 来源\n重跑该分片", fillcolor="#e7f4e4"];
  crash -> flag -> queue -> take -> run;
}
```

> [!NOTE]
>
> 失效转移只重跑"崩溃时正在执行"的分片项（由 `ShardingService.getCrashedShardingItems` 判定），**未触发的不补**。这是与"错过执行重跑（misfire）"的区别：failover 管的是运行中断，misfire 管的是触发时刻错过。

## Misfire

`misfire`（`JobConfiguration`，默认 `true`）处理"触发时刻作业没来得及跑"的情况：当某分片项的上一次执行仍未结束、或节点在触发窗口不可用，会在 `sharding/{item}/misfire` 置位；下一调度周期 `ElasticJobExecutor` 以 `ExecutionSource.MISFIRE` 来源对积压项补执行。misfire 能否被探测，依赖 `monitorExecution` 是否开启（见下）。

## Monitor Execution

`monitorExecution`（`JobConfiguration`，默认 `true`）决定每个分片项执行时是否在 `sharding/{item}/running` 写入运行态。开启后：

- 支持 misfire 探测（运行未结束时新触发被识别为错过）；
- 产生 `JobExecutionEvent`（开始 / 完成 / 失败），可供事件追踪与 `JobErrorHandler` 消费；
- 代价是每次执行多写一次 ZK 临时节点，高并发短作业下会增加 ZK 压力。

关闭 `monitorExecution` 可显著降低 ZK 写入，但会**同时失去 misfire 保护与执行监控**，需按作业特征权衡。

## Reconcile (Self-Diagnosis)

`reconcileIntervalMinutes`（`JobConfiguration`，默认 `10`）驱动一个自诊断线程，周期性比对运行态与真实执行情况，修正因实例崩溃残留的不一致状态（例如悬挂的 `sharding/{item}/running`、未及时清理的失效转移项）。它是"去中心化下没有全局锁也能自愈"的兜底机制——实例崩溃后不依赖人工介入即可逐步回到一致。

## What ElasticJob Does Not Do

官方功能列表里，**作业间依赖（DAG 工作流）至今仍是 TODO 状态**。ElasticJob 只解决单作业的弹性分片与高可用，不编排多作业间的上下游依赖。需要 DAG、任务编排、跨作业数据传递的场景，应直接看 [PowerJob](/docs/CS/Framework/Job/PowerJob.md)（原生 DAG + MapReduce）或 [DolphinScheduler](/docs/CS/Framework/Job/DolphinScheduler.md)。

## Links

- [ElasticJob](/docs/CS/Framework/Job/ElasticJob.md) — 枢纽：作业治理在三件套中的位置
- [Registry Center](/docs/CS/Framework/Job/ElasticJob/RegistryCenter.md) — `leader/failover/items` 与 `running` 节点定义
- [Sharding](/docs/CS/Framework/Job/ElasticJob/Sharding.md) — 崩溃分片项如何被 `getCrashedShardingItems` 识别
- [Job Types](/docs/CS/Framework/Job/ElasticJob/Job_Types.md) — `JobConfiguration` 中 failover / misfire / monitorExecution 开关

## References

- [ElasticJob 源码 `FailoverService.java` (3.0.5)](https://github.com/apache/shardingsphere-elasticjob/blob/3.0.5/kernel/src/main/java/org/apache/shardingsphere/elasticjob/kernel/internal/failover/FailoverService.java)
- [ElasticJob 源码 `FailoverNode.java` (3.0.5)](https://github.com/apache/shardingsphere-elasticjob/blob/3.0.5/kernel/src/main/java/org/apache/shardingsphere/elasticjob/kernel/internal/failover/FailoverNode.java)
