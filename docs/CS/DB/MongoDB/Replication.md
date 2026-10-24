## Introduction

MongoDB 的高可用单位是**副本集（Replica Set）**：一主多从，写只进 primary，从节点异步重放 oplog，主节点失联后由多数派选举出新主。分片集群里的每个 shard 与 config server 本身也都是副本集，因此复制机制是整个分布式形态的地基。

## Topology and Roles

| 角色 | 数据 | 投票 | 可被读 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| primary | 有 | 有 | 是 | 唯一接受写入 |
| secondary | 有 | 有 | 是（取决于 read preference） | 重放 oplog |
| arbiter | 无 | 有 | 否 | 只参与投票，不存数据 |
| hidden | 有 | 有 | 否（客户端不可见） | 用于备份/离线分析 |
| delayed | 有 | 有 | 否（客户端不可见） | 延迟 `secondaryDelaySecs` 重放，防误删 |

生产推荐 **P-S-S** 三个数据节点。P-S-A 能省存储，但少一份数据且故障切换后可能退化为单节点，不推荐用于核心业务。

## Oplog

oplog 是 `local.oplog.rs` 这个 **capped collection**，按时间顺序记录所有写操作：

- 条目是**幂等**的：更新会被改写成 `$set`/`$unset` 等可重复执行的形式，因此 secondary 重复应用不会产生不同结果。
- 默认大小为**空闲磁盘的 5%**，最小 990MB，最大 50GB；可用 `replSetResizeOplog` 在线调整。
- oplog 会滚出旧条目，**oplog 窗口**决定了 secondary 最长能断线多久、Change Streams 能续读多远。
- 8.0 起 secondary 的"写 oplog"与"应用 oplog"由两个缓冲并行处理，复制吞吐提升。

```javascript
rs.printReplicationInfo()          // 主节点：oplog 大小与时间窗口
rs.printSecondaryReplicationInfo() // 各从节点延迟
```

## Replication Flow

```text
client write
  → primary: 写 WT + 写本地 oplog
  → w:majority 等待多数派把该条目写入各自 oplog（8.0 语义）
  → secondary: 拉取 oplog 批次 → 写本地 oplog → 异步 apply
  → 主节点推进 majority commit point
```

8.0 的一个重要语义变化：`w: "majority"` 的确认从"多数派**应用**完成"改为"多数派**写入 oplog**"。因此客户端收到确认后立刻从 secondary 读，仍可能读不到这次写入——除非使用因果一致会话。

流控（flow control）默认开启：当多数派持久化的滞后超过阈值时，primary 会放慢写入，避免 secondary 越落越远。

## Elections and Failover

副本集使用 **PV1 协议**（3.2+），Raft-like：

- 成员每 **2 秒**心跳一次，**10 秒**无响应视为不可达；
- 候选者任期（term）加一，向多数派拉票；
- 只有 oplog 足够新的候选者才能当选（保证不丢已提交数据）；
- `priority` 高的节点优先发起选举；`priority: 0` 永不成为 primary；
- primary 发现自己只能看到少数派时主动 stepdown，避免双主。

故障转移时间通常在数秒到十几秒，取决于 `electionTimeoutMillis`（默认 10 秒）。应用侧靠驱动自动重连与可重试写入（retryable writes，3.6+）屏蔽大部分抖动。

## Rollback

如果旧 primary 在分区期间接受了未被多数派确认的写入，重新加入时会发现自己的 oplog 与新 primary 分叉，需要**回滚**：

- 回滚到两个分支的最后一个共同点；
- 被回滚的文档写入 `dbPath/rollback/` 下的 BSON 文件；
- 这些写入对客户端表现为"曾经成功、后来消失"。

避免方式：写操作用 `w: "majority"`，读重要数据用 `readConcern: "majority"`。延迟从节点（delayed）是误删/误更新后的最后一道人工恢复手段。

## Read Preference

| 模式 | 行为 | 典型场景 |
| :--- | :--- | :--- |
| `primary` | 只读主 | 强一致读、事务 |
| `primaryPreferred` | 主可用读主，否则读从 | 故障期间保可用 |
| `secondary` | 只读从 | 报表、离线分析 |
| `secondaryPreferred` | 从可用读从，否则读主 | 读扩展 |
| `nearest` | 选网络延迟最低的成员 | 多地域低延迟 |

read preference 只决定"发给谁"，不保证数据新旧。从节点可能落后，甚至拥有会被回滚的数据。

## Read Concern

| 级别 | 语义 | 代价 |
| :--- | :--- | :--- |
| `local` | 读本节点最新数据，可能未进多数派 | 最低 |
| `available` | 同 local，分片场景语义更弱 | 最低 |
| `majority` | 只读多数派已确认的数据，不会回滚 | 需等 majority commit point |
| `linearizable` | 读能反映读开始前所有已确认写 | 最高，仅 primary |
| `snapshot` | 事务内一致性快照 | 事务专用 |

## Write Concern

```javascript
{ w: 1 }                       // 主节点内存确认，最快，可能丢
{ w: "majority" }              // 多数派 oplog 确认，默认（常见 P-S-S）
{ w: "majority", j: true }     // 多数派且落 journal
{ w: 2, wtimeout: 5000 }       // 指定节点数 + 超时
```

副本集的**隐式默认写关注**按公式计算：当数据节点数大于投票多数时取 `majority`，否则 `w: 1`。三节点 P-S-S 的默认就是 `majority`。

`j: true` 与 `w: "majority"` 的关系由 `writeConcernMajorityJournalDefault` 决定：开启 journal 时，`majority` 通常隐含持久化要求。

## Causal Consistency

会话（session）可以开启因果一致性，保证同一会话内：

- 读到自己之前的写（read your writes）；
- 单调读（不会读到更旧的状态）；
- 单调写（写按顺序生效）。

实现方式是把上一次操作的 `operationTime` 作为 `afterClusterTime` 传给后续读，服务端等待副本集追上该时间点。跨客户端共享因果链时，需要传递 session 的 cluster time。

## Change Streams

`watch()` 订阅集合/库/集群的变更，底层读 oplog，输出带 resume token 的事件流。6.0 起支持 pre-image / post-image，能看到更新前后的完整文档。

限制同样来自 oplog：断线时间超过 oplog 窗口，resume token 失效，只能重新全量同步。分片集群的 Change Streams 由 `mongos` 合并各 shard 的事件，并按 cluster time 排序。

## Links

- [MongoDB](/docs/CS/DB/MongoDB.md)
- [Architecture](/docs/CS/DB/MongoDB/Architecture.md)
- [Transaction](/docs/CS/DB/MongoDB/Transaction.md)
- [Sharding](/docs/CS/DB/MongoDB/Sharding.md)
- [Redis Sentinel](/docs/CS/DB/Redis/sentinel.md)

## References

- [Replication](https://www.mongodb.com/docs/manual/replication/)
- [Replica Set Elections](https://www.mongodb.com/docs/manual/core/replica-set-elections/)
- [Replica Set Oplog](https://www.mongodb.com/docs/manual/core/replica-set-oplog/)
- [Read Preference](https://www.mongodb.com/docs/manual/core/read-preference/)
