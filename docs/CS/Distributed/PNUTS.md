# PNUTS

PNUTS（Yahoo!，VLDB 2008）是面向全球化 Web 应用的**跨地域复制数据服务平台（geo-replicated data serving platform）**。它要解决的核心矛盾是：用户分布在世界各地、都希望就近低延迟读写，而数据又必须在多个 region 之间保持一致——纯 AP（如 [Dynamo](/docs/CS/Distributed/Dynamo.md)）会读到乱序因果，纯 CP（如 [Spanner](/docs/CS/Distributed/Spanner.md)）则要付出跨 region 强一致的延迟代价。PNUTS 提出了一条中间路线：**per-record master + 时间线一致性（timeline consistency）**。

PNUTS 与 [Wormhole](/docs/CS/Distributed/Wormhole.md) / [Databus](/docs/CS/Distributed/Databus.md) 同属"地理复制"主题，但 PNUTS 是**有状态的数据服务层**（可查询的 KV/表），而非消息/变更流层。

## Per-record Master and Timeline Consistency

- **每条记录有一个主 region（master region）**：对某条记录的写请求被路由到它的 master，由 master **串行化**该记录的所有更新。这样同一记录不会有两个不同的 region 同时接受冲突写，从根本上规避了 Dynamo 式"写写冲突需后期 reconcile"的复杂度。
- **时间线一致性（Timeline Consistency）**：由于 master 串行化了单记录的更新，所有 region 看到的该记录变更顺序，都和 master 上发生的顺序一致——保证因果不乱序（不会出现"旧更新覆盖新更新"的视觉）。这是介于"最终一致"和"强一致"之间的一种**可预期一致性**级别。
- **异步复制 + 向量时钟**：记录更新经 **Yahoo Message Broker（YMB）** 异步复制到其它 region；复制元数据中用**向量时钟**追踪因果，帮助副本判断"我看到的版本是否最新、是否缺中间版本"。

## Consistency Trade-offs: Yield vs Consistency

PNUTS 论文提出用 **yield（产出率）** 来刻画 CAP 之外的工程取舍：

- **yield** 指的是"在部分 region 故障 / 网络分区时，系统仍能成功处理请求的比例"。PNUTS 允许读写即使某 region 不可用也继续（高 yield），代价是可能短暂读到非 master 的最新值（一致性被放宽）。
- 这与 CAP 的"二选一"表述不同：PNUTS 强调在**保证时间线一致**的前提下，通过 per-record master 与可调一致性级别，把"可用性损失"与"一致性损失"解耦，让应用按需选择读 master（最新）还是读本地副本（低延迟、可能滞后）。

## Reads and Replication

- **读取一致性级别可调**：应用可读 master 拿最新值，也可读本地副本拿低延迟但可能滞后的快照——把"一致性 vs 延迟"的选择权交给调用方，而非系统一刀切。
- **与 Dynamo 对照**：Dynamo 无 master、各副本平等接受写、最终一致、靠 vector clock + 协调解决冲突，偏向"永远可写"；PNUTS 用 per-record master 换"时间线有序"，偏向"读到的单记录变更顺序可预期"，代价是 master 故障时的写需要 failover。两者都是 AP 谱系，但对"一致性的可预期程度"取舍不同。
- **与 Spanner 对照**：Spanner 用 TrueTime 做跨 region 强一致（commit wait），读可线性一致；PNUTS 不追求跨 region 线性一致，只保证单记录时间线一致，因此延迟与可用性更友好，代价是跨记录无全局顺序。

## Links

- [Dynamo](/docs/CS/Distributed/Dynamo.md)
- [Spanner](/docs/CS/Distributed/Spanner.md)
- [Wormhole](/docs/CS/Distributed/Wormhole.md)
- [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md)

## References

- PNUTS: Yahoo!'s Hosted Data Serving Platform (Cooper et al., VLDB 2008)
- Paper: https://people.mpi-sws.org/~druschel/courses/ds/papers/cooper-pnuts.pdf
