# Registry Center

## Introduction

ElasticJob 的全部去中心化协调都落在注册中心上。3.0.5 仅内置 **ZooKeeper** 一种实现（接口 `CoordinatorRegistryCenter` 定义在 `registry-center` 模块，ZK 实现在 `kernel` 内），作业节点通过它完成注册、选主、分片协商与失效转移。理解节点树结构是读懂分片与失效转移的前提——本文所有路径均以 `3.0.5` 源码 `kernel/internal/storage/JobNodePath.java` 及各 `*Node` 常量类为准。

## CoordinatorRegistryCenter

注册中心对外暴露统一接口 `CoordinatorRegistryCenter`（`registry-center` 模块），屏蔽 ZK 细节；`kernel` 内的作业逻辑只依赖该接口，因此理论上可替换实现。接入时业务侧构造 `ZookeeperConfiguration`（命名空间 + 注册中心地址），再交给 `JobBootstrap` 使用。

ZK 上的作业根路径由 `JobNodePath` 拼装，形式为 `/{namespace}/{jobName}/...`：

```java
// kernel/internal/storage/JobNodePath.java (3.0.5)
private static final String LEADER_HOST_NODE = "leader/election/instance";
private static final String CONFIG_NODE       = "config";
private static final String SERVERS_NODE      = "servers";
private static final String INSTANCES_NODE    = "instances";
private static final String SHARDING_NODE     = "sharding";
public String getFullPath(final String node) {
    return String.format("/%s/%s", jobName, node);
}
```

## Node Tree

以 `/{namespace}/{jobName}/` 为前缀，源码中确认的真实节点如下（括号内为定义该常量的类）：

| ZK 路径 | 类型 | 用途 |
| :--- | :--- | :--- |
| `config` | 持久 | 作业配置（cron、分片数、分片参数等），变更经监听实时下发 |
| `instances/{instanceId}` | 临时 | 实例注册（实例下线自动删除）；`InstanceNode.INSTANCES` |
| `servers/{ip}` | 持久 | 受控服务器列表，可置 `ENABLED` / `DISABLED`；`ServerNode.SERVERS` |
| `sharding/{item}/instance` | 临时/持久 | 分片项 `item` 当前归属哪个实例；`ShardingNode.INSTANCE` |
| `sharding/{item}/running` | 临时 | 分片项是否正在执行；`ShardingNode.RUNNING` |
| `sharding/{item}/misfire` | 持久 | 分片项是否积压了错过执行的触发；`ShardingNode.MISFIRE` |
| `sharding/{item}/disabled` | 持久 | 分片项级禁用；`ShardingNode.DISABLED` |
| `sharding/{item}/failover` | 持久 | 该分片项待失效转移；`FailoverNode.EXECUTION_FAILOVER` |
| `sharding/{item}/failovering` | 临时 | 该分片项正在被接管的转移中状态；`FailoverNode.EXECUTING_FAILOVER` |
| `leader/election/instance` | 临时 | 当前主节点实例 ID；`LeaderNode.INSTANCE` |
| `leader/election/latch` | 临时 | 选主屏障（分布式锁语义）；`LeaderNode.LATCH` |
| `leader/sharding/necessary` | 持久 | 标记需要重新分片；`ShardingNode.NECESSARY` |
| `leader/sharding/processing` | 临时 | leader 正在分配分片（分配屏障）；`ShardingNode.PROCESSING` |
| `leader/failover/items/{item}` | 持久 | 待失效转移的分片项队列；`FailoverNode.ITEMS` |

> [!WARNING]
>
> 旧资料常把失效转移节点写成 `leader/items`、`leader/latch`。源码实测：**latch 是 `leader/election/latch`**（选主用），而失效转移项队列的真实路径是 **`leader/failover/items/{item}`**（见 `FailoverNode`：`LEADER_ROOT = leader/failover`，`ITEMS = leader/failover/items/%s`）。不要把两者混为一谈。

## Leader Election

主节点由 `LeaderService`（`kernel/internal/election`）经 ZK 临时节点选举产生，核心方法：

- `electLeader()`：尝试在 `leader/election/instance` 创建临时节点，创建成功者即主节点；
- `isLeader()`：判断当前实例是否为主；
- `isLeaderUntilBlock()`：阻塞直到确认自身为主或主节点已存在——分片 / 失效转移等"只有主能做"的操作都先过这一关；
- `hasLeader()` / `removeLeader()`：主节点存在性判断与摘除。

`LeaderNode` 定义选主相关路径：`ROOT = "leader"`、`ELECTION_ROOT = "leader/election"`、`INSTANCE = "leader/election/instance"`、`LATCH = "leader/election/latch"`。**leader 崩溃 → 临时节点消失 → 其余存活实例监听到变化后自动重选**，这是"无中心架构得以成立"的关键。但注意：leader 只是协调者，不是调度中心——它不参与具体作业执行，只负责分片分配与失效转移的协调。

## Instance and Server

- **实例（instance）**：每个运行中的作业进程注册为 `instances/{instanceId}`（临时节点，`JobInstance` 由 IP + PID 等构成），下线即消失，是分片分配的基本单元。
- **服务器（server）**：`servers/{ip}` 以 IP 为粒度记录受控服务器，状态由 `ServerStatus` 维护（`ENABLED` / `DISABLED`）。服务器 `DISABLED` 时，其上的实例不参与分片。

二者区别在于粒度：server 是机器级开关，instance 是进程级在线心跳。分片分配看的是**可用实例集合**（`instanceService.getAvailableJobInstances()`）。

## Static Sharding

`JobConfiguration` 提供 `staticSharding` 开关（默认 `false`）。开启后，分片项与实例的绑定关系在首次分片后固定下来，不再随实例上下线动态重平衡——适用于实例与数据分片强绑定的场景（如分片即物理分区）。动态分片（默认）则在每次实例/服务器变化后触发重新分片。

## Links

- [ElasticJob](/docs/CS/Framework/Job/ElasticJob.md) — 枢纽：架构 / 演进 / 对比
- [Sharding](/docs/CS/Framework/Job/ElasticJob/Sharding.md) — 分片如何利用 `leader/sharding/necessary` 与 `processing` 屏障
- [Failover](/docs/CS/Framework/Job/ElasticJob/Failover.md) — 失效转移如何利用 `leader/failover/items`
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md) — ElasticJob 的隐性中心

## References

- [ElasticJob 源码 `kernel/internal/storage/JobNodePath.java` (3.0.5)](https://github.com/apache/shardingsphere-elasticjob/blob/3.0.5/kernel/src/main/java/org/apache/shardingsphere/elasticjob/kernel/internal/storage/JobNodePath.java)
- [ElasticJob 注册中心模块](https://github.com/apache/shardingsphere-elasticjob/tree/3.0.5/registry-center)
