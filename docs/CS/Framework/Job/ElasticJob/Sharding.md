# Sharding

## Introduction

分片是 ElasticJob 弹性调度的核心机制：作业按配置切成 N 个分片项（`shardingTotalCount`），每个分片项携带参数（如 `0=北京,1=上海`），由不同实例各执其一。加节点即触发重新分片，执行能力随资源线性增长。本文基于 `3.0.5` 源码 `kernel/internal/sharding/ShardingService.java` 与 `JobShardingStrategy` SPI 展开。

## Sharding Model

分片项（`item`）是调度的最小单位，取值范围 `[0, shardingTotalCount)`。每个分片项通过 `shardingItemParameters` 配置获得一个字符串参数，在执行时由 `ShardingContext.getShardingParameter()` 暴露给作业代码。典型用法是按参数把数据路由到同一分片：相同任务经分片参数聚合至相同执行器处理。

`ShardingItemParameters`（`kernel/internal/sharding`）负责把 `0=北京,1=上海` 形式的配置解析为 `item -> parameter` 映射；解析失败会抛出 `JobConfigurationException`。

`ShardingContext`（`api/spi/executor/item/param`，3.0.5 确认字段）携带单次执行所需的全部上下文：

| 字段 | 含义 |
| :--- | :--- |
| `jobName` | 作业名 |
| `taskId` | 本次执行任务 ID（含分片项与执行来源，用于事件追踪） |
| `shardingTotalCount` | 总分片数 |
| `jobParameter` | 作业级参数（所有分片共享） |
| `shardingItem` | 当前分片项 |
| `shardingItem` 对应 `shardingParameter` | 当前分片项参数 |

## Resharding Flow

重新分片由 `ShardingService` 驱动，关键在 **leader 屏障**：只有当实例是主节点（`LeaderService.isLeaderUntilBlock()`）时才执行分配，非主节点会阻塞等待分配完成。源码 `shardingIfNecessary()` 的逻辑骨架（已核实）：

```java
public void shardingIfNecessary() {
    List<JobInstance> availableJobInstances = instanceService.getAvailableJobInstances();
    if (!isNeedSharding() || availableJobInstances.isEmpty()) {
        return;
    }
    if (!leaderService.isLeaderUntilBlock()) {     // 非主节点：等主分配完
        blockUntilShardingCompleted();
        return;
    }
    waitingOtherShardingItemCompleted();
    JobConfiguration jobConfig = configService.load(false);
    int shardingTotalCount = jobConfig.getShardingTotalCount();
    jobNodeStorage.fillEphemeralJobNode(ShardingNode.PROCESSING, "");  // 占 processing 屏障
    resetShardingInfo(shardingTotalCount);
    JobShardingStrategy jobShardingStrategy =
        TypedSPILoader.getService(JobShardingStrategy.class, jobConfig.getJobShardingStrategyType());
    jobNodeStorage.executeInTransaction(
        getShardingResultTransactionOperations(jobShardingStrategy.sharding(availableJobInstances, jobName, shardingTotalCount)));
}
```

节点变化（实例上下线、服务器开关）会触发 `setReshardingFlag()`，在 `leader/sharding/necessary` 置位；主节点随后在下次调度周期执行 `shardingIfNecessary()`，`blockUntilShardingCompleted()` 通过轮询 `leader/sharding/necessary` 与 `leader/sharding/processing` 两个节点的存在性来判定分配是否结束。`PROCESSING` 是主节点持有的临时节点，分配期间存在，分配完成后删除——它是一道保证"同一时刻只有一个主在做分配"的屏障。

## Sharding Strategies

分片分配算法被抽象为 `JobShardingStrategy` SPI（`extends TypedSPI`），签名：

```java
Map<JobInstance, List<Integer>> sharding(List<JobInstance> jobInstances, String jobName, int shardingTotalCount);
```

`3.0.5` 的 `META-INF/services` 注册了 **4 种**策略（`kernel/internal/sharding/strategy/type/`）：

| 类型字符串 | 类名 | 分配语义 |
| :--- | :--- | :--- |
| `AVG` / `AverageAllocationJobShardingStrategy` | `AverageAllocationJobShardingStrategy` | **默认**。平均分片，余数挨个顺延（如 9 片 2 实例 → `[0,1,2,3,4],[5,6,7,8]`） |
| `OdevitySortByNameJobShardingStrategy` | `OdevitySortByNameJobShardingStrategy` | 作业名哈希奇偶数决定实例排序后再平均分，使不同作业的分片倾向错开 |
| `RoundRobinByNameJobShardingStrategy` | `RoundRobinByNameJobShardingStrategy` | 按作业名轮询分配，进一步打散热点 |
| `SingleShardingBalanceJobShardingStrategy` | `SingleShardingBalanceJobShardingStrategy` | 单分片优先均衡（每个实例先分一片，余下再补） |

策略由 `JobConfiguration.getJobShardingStrategyType()` 选定，经 `TypedSPILoader` 按类型字符串加载；不指定时走默认的平均分片。

## Local and Crashed Sharding Items

`ShardingService` 提供多项查询，供执行与失效转移使用：

- `getLocalShardingItems()`：返回当前实例分到的分片项（读 `sharding/{item}/instance == 本实例`）；
- `getShardingItems(jobInstanceId)`：返回指定实例的分片项；
- `getCrashedShardingItems(jobInstanceId)`：返回崩溃实例"当时正在运行"的分片项（`sharding/{item}/running` 存在且该分片归属该实例），失效转移只接管这些项。

## Links

- [ElasticJob](/docs/CS/Framework/Job/ElasticJob.md) — 枢纽：执行链路中分片如何被消费
- [Registry Center](/docs/CS/Framework/Job/ElasticJob/RegistryCenter.md) — `leader/sharding/necessary` 与 `processing` 屏障的节点定义
- [Failover](/docs/CS/Framework/Job/ElasticJob/Failover.md) — 崩溃分片项的接管
- [Job Types](/docs/CS/Framework/Job/ElasticJob/Job_Types.md) — `ShardingContext` 如何在作业代码中被使用

## References

- [ElasticJob 源码 `ShardingService.java` (3.0.5)](https://github.com/apache/shardingsphere-elasticjob/blob/3.0.5/kernel/src/main/java/org/apache/shardingsphere/elasticjob/kernel/internal/sharding/ShardingService.java)
- [ElasticJob 分片策略 SPI 注册](https://github.com/apache/shardingsphere-elasticjob/blob/3.0.5/kernel/src/main/resources/META-INF/services/org.apache.shardingsphere.elasticjob.kernel.internal.sharding.strategy.JobShardingStrategy)
