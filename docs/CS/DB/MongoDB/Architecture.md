## Introduction

MongoDB 的进程模型比单体关系库多一层：单机形态只有一个 `mongod`，分布式形态则拆成 **shard / mongos / config server** 三类角色。理解这张部署图，才能解释后面的复制、分片、事务各自的边界——例如"为什么事务在 mongos 上提交""为什么分片集群的命令不能直连 shard"。

本文基线 **MongoDB 8.0**（Major Release，2024-10 发布），9.0（2026-09）的差异单独标注。

## Process and Components

| 组件 | 职责 | 是否有本地数据 |
| :--- | :--- | :--- |
| `mongod` | 存储引擎、查询执行、复制、事务 | 有（dbPath） |
| `mongos` | 查询路由、结果归并、路由表缓存 | 无；8.0 起可搭配 config shard 复用 |
| config server | 存集群元数据（shard、chunk、collection 位置、集群参数） | 有（config 库） |
| driver | 服务发现（SDAM）、连接池、重试、读偏好路由 | 无 |

**副本集**是最小生产单元：一个 primary 加两个及以上 secondary，config server 自身也必须是一个副本集（CSRS）。

**分片集群**由多个 shard 副本集、一到多个 `mongos`、一个 config server 副本集组成。客户端只连 `mongos`，不直连 shard。8.0 起 config server 可以兼作 shard（config shard），用 `transitionFromDedicatedConfigServer` / `transitionToDedicatedConfigServer` 在两种形态间切换。

> [!WARNING]
>
> 8.0 起直连 shard 节点只能执行白名单内的命令；8.3 起 DDL 与 `applyOps` 只允许在 `mongos` 上执行。运维脚本里"连到某台 shard 上改集合"的老做法会直接报错，需要 `directShardOperations` 角色（仅限维护窗口）。

## Storage and Execution Layers

`mongod` 自上而下分三层：

1. **查询层**：解析 MQL / 聚合管道，鉴权，选计划，执行。7.0 起默认使用 **SBE（Slot-Based Execution Engine）**，不支持的查询形状回退 classic 引擎。
2. **复制与事务层**：写操作生成 oplog 条目；多文档事务在 WT 时间戳上取快照、提交时统一可见。
3. **存储层**：WiredTiger 负责 B-tree、缓存、checkpoint、journal。MMAPv1 在 4.2 已移除，如今 WiredTiger 是唯一的生产存储引擎（企业版另有 in-memory / encrypted 引擎）。

锁的层次是"粗粒度意向锁 + 细粒度文档并发"：MongoDB 层在 global / database / collection 上持 IS/IX 意向锁，DDL 取排他锁；真正的行级（文档级）并发由 WiredTiger 用 MVCC 与 hazard pointer 实现，读不阻塞写。

## Request Lifecycle

一次读请求的典型路径：

```text
driver → (mongos 路由) → mongod
  → 解析 BSON 命令
  → 鉴权 / 校验
  → 查 plan cache（命中则复用，否则 multi-planner 试跑）
  → SBE / classic 执行
  → WiredTiger：先查 cache，未命中再从磁盘页解压
  → 返回首批结果（find 默认 101 个文档或 16MB，取先到者）
  → 客户端 getMore 继续拉取
```

写请求多两步：在 WT 里生成新版本并写 journal（默认每 100ms 刷一次），若在副本集上还要写 oplog；`w:majority` 的确认点在多数派**写入** oplog 之后（8.0 的语义变化，见 [Replication](/docs/CS/DB/MongoDB/Replication.md)）。

## Memory Model

WiredTiger 内部缓存默认取 **50% × (RAM − 1GB)** 与 **256MB** 中的较大值，剩余内存留给操作系统的文件系统缓存（压缩后的数据页仍在 page cache 里）。容器里如果拿不到宿主机全部内存，必须显式设置 `--wiredTigerCacheSizeGB`。

8.0 把内存分配器换成使用 **per-CPU cache** 的 TCMalloc，降低高并发下的碎片与争抢。这部分与 [Storage Engine](/docs/CS/DB/MongoDB/StorageEngine.md) 的淘汰机制直接相关：缓存放不下工作集时，WT 先淘汰脏页，应用线程在高压下也会参与淘汰，表现为延迟抖动而非直接报错。

## Deployment Forms

| 形态 | 适用 | 说明 |
| :--- | :--- | :--- |
| standalone | 本地开发、一次性分析 | 无复制、无事务跨文档能力 |
| replica set | 绝大多数生产 | 至少 3 个投票成员，自动故障转移 |
| sharded cluster | 数据量或写入超出单机 | 复杂度显著上升，shard key 一旦选错代价高 |

## Links

- [MongoDB](/docs/CS/DB/MongoDB.md)
- [Storage Engine](/docs/CS/DB/MongoDB/StorageEngine.md)
- [Replication](/docs/CS/DB/MongoDB/Replication.md)
- [Sharding](/docs/CS/DB/MongoDB/Sharding.md)
- [WAL](/docs/CS/DB/WAL.md)

## References

- [Sharded Cluster Components](https://www.mongodb.com/docs/manual/core/sharded-cluster-components/)
- [Sharded Cluster Query Router](https://www.mongodb.com/docs/manual/core/sharded-cluster-query-router/)
- [WiredTiger Storage Engine](https://www.mongodb.com/docs/manual/core/wiredtiger/)
- [MongoDB Versioning](https://www.mongodb.com/docs/manual/reference/versioning/)
