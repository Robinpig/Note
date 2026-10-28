# Transactions and Locking

## Introduction

分布式向量库的写事务不是传统数据库的「行锁加隔离级别」套餐。在 Milvus v3.0.1 的流式架构里，事务被重新定义为 **WAL 上的消息分组**：一组 append 消息用 BeginTxn 与 CommitTxn 圈起来，提交前对任何读者完全不可见，提交后作为一条组装好的「事务消息」整组出现。整条机制只依赖 WAL 的顺序与 TimeTick，不需要额外的分布式事务协调器。

与之配套的锁也不是记录锁。append 路径上唯一的闸门是 lock interceptor：一把按 VChannel 键控的 key 级锁加一把 WAL 级读写锁，负责的是**消息序与生命周期**类竞争——排他消息不得穿过未决事务、CAS 提交不得与其他 append 交错，而不是主键级别的写写冲突。

本文聚焦事务生命周期、未提交可见性、锁与确认机制；WAL 通道与 TimeTick 基础见 [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)，端到端写链路见 [Write Path](/docs/CS/DB/Milvus/Write_Path.md)，查询侧一致性等待见 [Query Path](/docs/CS/DB/Milvus/Query_Path.md)，CDC 对未提交事务的处理见 [CDC and Replication](/docs/CS/DB/Milvus/CDC_and_Replication.md)。

## Transaction API and Lifecycle

v3.0.1 没有暴露给客户端的事务 RPC，事务由写路径内部发起，只有三个 WAL 消息类型参与：`MessageTypeBeginTxn`、`MessageTypeCommitTxn`、`MessageTypeRollbackTxn`。

客户端 producer（`internal/distributed/streaming/internal/producer/`）决定何时包事务：

- 单条消息、无 partial update CAS 标记、无既有 TxnContext 时，直接 append，不包事务；
- 同一 VChannel 的多条消息走 `produceTxn`：`beginTxn` 取回 TxnContext → `appendTxnBody` 并发追加所有 body → `commitTxn` 提交。单条消息一般直发，判据是 `!HasCAS ∨ TxnContext != nil ∨ ReplicateHeader != nil`——即带 partial update CAS 且既无既有事务上下文也无复制头时才会包一层事务；带复制头的 CAS 单条消息保持直发，因为复制必须保留源集群的事务边界。
- `AppendMessages` 先按 VChannel 分发：同一 VChannel 的消息按一个事务发送，跨 VChannel 各发各的，不保证跨 VChannel 的原子性。

`produceTxn` 对事务过期做自动重试（换新事务重放）；若消息带 partial update CAS，则改报可重试错误 `NewPartialUpdateRetryable`，因为 CAS 语义要求基于最新版本重做判定。

事务状态机定义在 `messagespb.TxnState`，session 内流转如下：

| TxnState | 进入点 | 含义 |
| --- | --- | --- |
| `TxnStateInFlight` | BeginTxn 建立 session | 唯一可继续追加 body 的状态 |
| `TxnStateOnCommit` | CommitTxn 进入 `RequestCommitAndWait` | 已冻结，不再接受新消息 |
| `TxnStateCommitted` | `CommitDone` | 提交完成，清理回调触发 |
| `TxnStateOnRollback` | RollbackTxn 进入 `RequestRollback` | 回滚进行中 |
| `TxnStateRollbacked` | `RollbackDone` / `RejectCommit` | 永久失效；**续租过期不经过此态**——`checkIfExpired` 只标记 `expired`，随后 `CleanupTxnUntil` 直接删除 session |

## Sessions and Expiration

一个事务对应一个 `TxnSession`，由 `TxnManager` 按 `TxnID` 管理。TxnID 在 BeginTxn append 时分配，session 绑定一个 VChannel；事务不跨 WAL——PChannel 转移到别的 StreamingNode 后，未决事务一律按过期回滚处理，客户端用新事务重试。

session 的寿命由 keepalive 决定：Begin 消息头携带 `KeepaliveMilliseconds`，为 0 时取 `streaming.txn.defaultKeepaliveTimeout`（默认 10s）；复制来源的事务 keepalive 为无限。续期发生在 body append 成功时——每成功追加一条消息就刷新 `lastTimetick`，`expiredTimeTick = lastTimetick + Keepalive`，一旦过期不可复活，后续任何消息都会被 `NewTransactionExpired` 拒绝。

清理有三个入口：

- TimeTick 消息到达时 `CleanupTxnUntil(msg.TimeTick())` 清扫过期或已完成的 session，同时触发 `RegisterCleanup` 注册的回调（shard 层借此释放 segment 上的事务计数）；
- 排他消息释放锁时 `FailTxnAtVChannel` 强制失败该 VChannel 的全部未决事务；
- 优雅关闭 `GracefulClose` 等待 session 清零，failover 场景用 `RollbackAllInFlightTransactions` 兜底。

恢复路径：WAL 重开时用扫描出的未提交消息重建 session（`NewTxnManager(channel, TxnBuffer.GetUncommittedMessageBuilder())`），`RecoverDone` 通道在未决事务全部落定前不关闭，恢复扫描据此与原始顺序对齐。

## WAL Representation and Commit Ordering

Begin、body、Commit 都是真实写入 WAL 的消息，按 append 顺序落在同一 PChannel；body 消息携带 TxnContext 属性（客户端 `WithTxnContext` 标记）。值得注意的是，处理事务的并不是独立 interceptor——append 链顺序为 redo → lock → replicate → timetick → shard → partialupdate，Begin/Commit/Rollback 分支实现在 timetick interceptor 里，`txn` 包只放 manager 与 session。

提交点的确定顺序：

1. CommitTxn 先由 timetick 层分配自己的 TimeTick；
2. 进入 `handleCommit` → `RequestCommitAndWait(ctx, msg.TimeTick())`，等到 session 的 inFlightCount 归零——即所有 body append 都已返回；
3. 此后任何新消息试图加入都会被 `NewInvalidTransactionState` 拒绝。

因此 CommitTxn 的 TimeTick 严格大于其所有 body 的 TimeTick，这个 tick 就是整组事务的可见性位点。提交结果被二值化：WAL append 之前被准入拒绝（partial update CAS 校验失败，经 `MarkCommitAdmissionRejected` 标记）→ `RejectCommit`，确定未提交；一旦进入 append 阶段，无论 append 成功与否都记 `CommitDone`——append 失败不能证明 CommitTxn 未持久化。

RollbackTxn 在 timetick interceptor 里有完整的 `handleRollback` 与 `RollbackDone` 路径，但 v3.0.1 生产代码中未见发送方（消息构建器只被测试与 Proxy 的 DumpMessages 过滤引用）——显式回滚在当前版本不是客户端可见的 API，未提交事务主要靠 keepalive 过期回收。

## Uncommitted Visibility

消费侧的可见性由 Scanner 统一把关：每个 scanner 都持有 `ReOrderByTimeTickBuffer` 与 `TxnBuffer`。重排缓冲先按 TimeTick 归序，`TxnBuffer.HandleImmutableMessages` 再做事务分组：

- 无 TxnContext 的普通消息立即通过；
- BeginTxn 开启一个 builder，body 消息不断加入 builder；
- CommitTxn 触发 `builder.Build(commitMsg)`，组装出一条 `ImmutableTxnMessage`——它的 MessageID、TimeTick、LastConfirmedMessageID 全部取自 CommitTxn，begin 与 body 被 `cloneForTxnBody` 重写成同一组值。提交前缓冲区里的消息对上层不存在，提交瞬间整组以提交点为戳出现。

丢弃路径同样明确：RollbackTxn、过期（`builder.ExpiredTimeTick() <= 已消费的 TimeTick`）直接删除 builder；commit 落在未知 txn 上按重复提交忽略；body 落在未知 txn 上忽略；复制造成的重复 BeginTxn 会重置缓冲。强制提升场景（`AlterReplicateConfig` 带 ForcePromote）触发 `rollbackAllUncommittedTxn`，把旧拓扑遗留的未决事务全部丢弃，细节见 [CDC and Replication](/docs/CS/DB/Milvus/CDC_and_Replication.md)。

所有消费方共享这套语义：StreamingNode flusher（3.0 唯一落盘路径）、QueryNode（经 dispatcher）、CDC 复制输入、恢复扫描——未提交数据不落盘、不可查、不可复制，这就是最核心的「可见性边界」。

## Lock Interceptor

append 链上的 lock interceptor 由两把锁组成：一把 WAL 级的 `glock sync.RWMutex`，一把按 VChannel 字符串键控的 `lock.KeyLock[string]`。普通消息取 glock 读锁加 VChannel 读锁，同一 VChannel 的并发 append 互不阻塞。

排他消息（`IsExclusiveRequired`）包括 CreateCollection、DropCollection、TruncateCollection、CreatePartition、DropPartition、CommitImport、RollbackImport、ManualFlush、FlushAll、AlterCollection、SchemaChange、AlterReplicateConfig、AlterWAL。PChannel 级或 vchannel 为空时取 glock 写锁独占整个 WAL，否则取 VChannel 写锁。

排他锁释放时会调用 `FailTxnAtVChannel`，把该 VChannel 上的未决事务全部失败。动机在源码注释里写得很直白：ManualFlush 会封掉正在使用的 growing segment，若事务在 flush 之后才提交，insert 消息就会出现在 flush 消息之后，破坏 WAL 的消息序——正确性不是靠隔离级别，而是靠不让这类交错发生；排他消息本身低频，整批失败并让客户端换新事务重试是可接受的代价。

第三类规则：带 partial update CAS 标记的 CommitTxn（非复制来源）走 VChannel 写锁——CAS 的准入校验需要对同 VChannel 的其他 append 串行，否则校验与生效之间存在竞争窗口。

因此这里的锁防的不是主键冲突（那是 partial update 层的版本校验职责），而是两类生命周期竞争：排他消息与未决事务、CAS 提交与并发 append。

## Acknowledgement and MVCC

timetick interceptor 给每条非 TimeTick 消息分配 `Acker`：从 TSO 取时间戳，并携带当下生效的 `lastConfirmedMessageID`，消息带着这对值追加进 WAL；append 完成后 `Ack` 才让确认机制收敛。

`AckManager` 用两个结构收敛水位：

- 按时间戳排序的最小堆等待 ack，连续 ack 完成后推进 `lastConfirmedTimeTick`；
- 把每条消息（连同其 TxnSession、MessageID、EndTimestamp）压入按 MessageID 排序的堆，`updateLastConfirmedMessageID` 只有在「EndTimestamp 落后于已同步的 tick」且「session 为空或已 done/expired」时才把水位推过这条消息。

也就是说，**未提交事务的 Begin 消息是可见性水位上的钉子**：只要它未决，`lastConfirmedMessageID` 就不能推过它，防止「从 LastConfirmedMessageID 之后读」的消费者漏掉将来才会出现的 CommitTxn。承诺语义（源码注释）：从某消息的 LastConfirmedMessageID 起读，保证不会漏掉 TimeTick 更大的消息，事务消息同样适用；恢复时 `determineLastConfirmedMessageID` 取全部未决 txn builder 的最小 LastConfirmedMessageID 来守住这个承诺。

多路消费者各自扫描、各自持有 TxnBuffer 与重排缓冲，但可见性边界一致：以 CommitTxn 的 TimeTick 为界。查询侧如何等待这条边界见 [Query Path](/docs/CS/DB/Milvus/Query_Path.md)。

## Transaction State Across Subsystems

事务不止被 WAL 一层感知，shard 与恢复路径都参与了它的生命周期：

- shard 层在事务消息分配行时把清理回调注册到 segment（`TxnSession.RegisterCleanup`），segment 的 txnSem 在行分配时加一、session 清理时减一；segment 存在未决事务时自动 flush 判定直接推迟——未提交事务钉住 segment 的封口与刷写。
- 恢复期 shard 的 flush worker 等待 `TxnManager.RecoverDone()`，未决事务落定前不推进封口，保证重放顺序与原始写入顺序一致。
- 错误面：准入拒绝是确定性未提交，过期与 CAS 重试是两类可重试信号，语义归属见 [Error Model](/docs/CS/DB/Milvus/Error_Model.md)。

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)
- [WAL](/docs/CS/DB/Concept/WAL.md)
- [Distributed Systems](/docs/CS/Distributed/Distributed.md)

## References

- [Milvus v3.0.1 txn manager source](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/streamingnode/server/wal/interceptors/txn/txn_manager.go)
- [Milvus v3.0.1 lock interceptor source](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/streamingnode/server/wal/interceptors/lock/lock_interceptor.go)
- [Milvus v3.0.1 TxnBuffer source](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/streamingnode/server/wal/utility/txn_buffer.go)
- [Milvus v3.0.1 last confirmed message manager source](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/streamingnode/server/wal/interceptors/timetick/ack/last_confirmed.go)
- [Milvus v3.0.1 streaming producer task source](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/distributed/streaming/internal/producer/producer_task.go)
