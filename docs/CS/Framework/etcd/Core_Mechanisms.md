## Introduction

etcd 的源码很容易读成“很多模块各自完成一段工作”，但真正决定它语义的，是几条跨模块的不变量：**谁有权提出写入、日志以什么顺序提交、状态机何时可见、客户端何时收到结果、崩溃后从哪里继续**。单独看 Raft、MVCC 或 boltdb，都不足以回答“一次 Put 到底什么时候成功”。

本文以 **etcd v3.7.2** 为固定源码基线，贯通 `Propose → Raft → Apply → MVCC → Watch / Read → Recovery`。它不是启动教程，也不重复 Raft 算法本身；重点是把 [raft](/docs/CS/Framework/etcd/raft.md)、[MVCC](/docs/CS/Framework/etcd/MVCC.md)、[boltdb](/docs/CS/Framework/etcd/boltdb.md)、[watch](/docs/CS/Framework/etcd/watch.md)、[read](/docs/CS/Framework/etcd/read.md) 之间的边界接起来。启动与恢复的完整调用树见 [boot](/docs/CS/Framework/etcd/boot.md)，请求入口与限流细节见 [request](/docs/CS/Framework/etcd/request.md)。

> [!NOTE]
> 版本基线：etcd **v3.7.2**，Raft 依赖 `go.etcd.io/raft/v3 v3.7.0`。本文行号均对应该 tag；3.5 资料中的 `server/etcdserver/raft.go:linearizableReadLoop`、`applyResult` 等路径或类型已经变化。

## Four Layers and Three Sequence Numbers

先把层次与序号分开。etcd 中至少有三套编号经常被混称为“版本”或“索引”，它们各自回答不同问题。

| 层 | 核心职责 | 关键状态 |
| :--- | :--- | :--- |
| API / server | 鉴权、参数检查、请求转发、注册结果等待者 | `InternalRaftRequest`、request ID |
| Raft | 对日志排序并复制到多数派 | term、log index、commit index |
| apply / state machine | 按日志顺序执行确定性的状态转换 | applied index、Auth / Quota / MVCC |
| MVCC / backend | 生成业务 revision，更新索引并物化历史 | `(main, sub)`、treeIndex、bbolt |
| watch / read | 从已物化状态提供事件流或快照 | watch ID、ReadIndex、snapshot revision |

| 序号 | 由谁生成 | 表示什么 | 不能代替什么 |
| :--- | :--- | :--- | :--- |
| Raft log index | Raft 日志 | 一条共识日志的位置 | 不是用户可见的业务 revision |
| MVCC revision | apply 阶段的 MVCC 写事务 | 一次原子键空间变更及其 sub 顺序 | 不是 WAL offset，也不是请求 ID |
| request ID | `EtcdServer.reqIDGen` | 把异步 apply 结果送回正确调用者 | 不参与共识排序，也不用于去重 |

一次事务可能只对应一个 Raft entry，却产生多个 `(main, sub)` revision；一个 Raft snapshot 又可以覆盖大量已经物化的 revision。**Raft index 相等不意味着 MVCC revision 相等，客户端请求到达顺序也不等于 Raft log 顺序。**

## End-to-End Invariants

理解 etcd 的最快方式，是先接受下面几条不变量，再看代码如何实现它们。

| 不变量 | 源码含义 | 常见误解 |
| :--- | :--- | :--- |
| 已提交不等于已 apply | commit index 可以领先 applied index | 收到 commit 就认为客户端已可读到 |
| 写响应等待 apply 结果 | 入口注册 waiter，apply 完成后按 request ID 唤醒 | `Propose` 返回就等于 Put 成功 |
| revision 在 apply 时分配 | `storeTxnWrite.beginRev = currentRev`，写入使用 `beginRev + 1` | 请求进入 server 时就生成 revision |
| 同一原子事务共享 main | 所有变更使用同一个 `beginRev + 1`，sub 为 `len(changes)` | 一个 Txn 每个 Put 都递增一次 revision |
| apply 必须按日志顺序 | FIFO 调度，且 `applyEntries` 检查 index 连续 | 不同写请求可以并发改 MVCC |
| 超时不等于未提交 | waiter 超时会被删除，已提交日志仍会 apply | 客户端超时后可以放心重试同一非幂等写 |
| 物化数据不要求每次 Put 立即 fsync | backend 有读缓冲与批量 bbolt 提交 | 每个 Put 返回前都单独提交一次 bbolt |
| 两类持久化服务不同目的 | WAL / snapshot 保存共识状态，backend 保存状态机结果 | 只有 WAL，或者只有 `snap/db` |

相关落点：`etcdserver/v3_server.go:1058-1133`、`etcdserver/server.go:1892-2003`、`etcdserver/apply/apply.go:27-53`、`storage/mvcc/kvstore_txn.go:174-220`、`storage/backend/batch_tx.go:308-340`。

## Write Path

### End-to-End Sequence

```sequence
Client->EtcdServer: Put / Txn
EtcdServer->EtcdServer: auth + apply-gap + MaxRequestBytes
EtcdServer->EtcdServer: Header.ID + waiter.Register
EtcdServer->Raft: Propose(InternalRaftRequest)
Raft->Raft: append + replicate + commit
Raft->EtcdServer: Ready(committed entries)
EtcdServer->ApplyQueue: unbuffered applyc
Raft->Transport: send messages / Save WAL
ApplyQueue->EtcdServer: applyAll in log order
EtcdServer->MVCC: Auth -> Quota -> Backend -> Txn
MVCC->MVCC: allocate (main, sub)
MVCC->treeIndex: update key generations
MVCC->Backend: UnsafeSeqPut + read buffer
MVCC->Watch: notify(rev, events)
MVCC->EtcdServer: txn End, currentRev++
EtcdServer->Client: trigger waiter by request ID
```

这张图强调逻辑依赖，不表示所有调用都在同一 goroutine 中严格串行。Raft 的副本发送、WAL 写入和 apply 调度之间存在流水线并行。

### Proposal Admission

`Put` 和写 `Txn` 最终都进入 `raftRequest → processInternalRaftRequestOnce`（`etcdserver/v3_server.go:295-308,325-380,1012-1133`）。入口按顺序完成：

1. 比较 `committedIndex` 与 `appliedIndex`，防止 apply 积压无限扩大；
2. 创建 `RequestHeader.ID`，写入认证用户名与 auth revision；
3. `proto.Marshal` 后检查 `MaxRequestBytes`；
4. 用 request ID 注册 waiter；
5. 创建带 `ReqTimeout()` 的 context，调用 `r.Propose`；
6. 等待 apply 结果、context 超时或 server 停止。

v3.7.2 的普通 apply-gap 阈值是 **5000**。`PriorityRequest` feature gate 默认关闭、Alpha；只有开启后，`LeaseRevoke` 才能把阈值放宽到 **10000**，其他请求不能享受这个例外（`etcdserver/v3_server.go:50-52`、`etcdserver/util.go:57-74`、`features/etcd_features.go:82-98`）。

> [!WARNING]
> 入口的 apply-gap 检查与 backend quota 不是同一个机制。前者限制“共识队列积压”，后者限制“状态机后端空间”。NOSPACE 甚至可能在 apply 阶段才被发现。

请求可以发给任意 member。若入口是 follower，Raft 节点会把 proposal 转发给 leader；etcd 的 peer 复制使用 `rafthttp` 的 HTTP/2 流，不是 gRPC。

### Timeout Semantics

`processInternalRaftRequestOnce` 的超时分支会调用 `s.w.Trigger(id, nil)` 清理 waiter，但这只是让本调用不再等待，**不会撤回已经进入 Raft 的日志**。

因此：

- 超时发生在 Propose 成功之前：请求可能根本没有形成 committed entry；
- 超时发生在 committed 之后、apply 完成之前：该写仍会执行；
- 超时发生在 apply 完成附近：数据可能已经可见，只是响应没有送达；
- 对 Put / DeleteRange 这类没有业务幂等键的操作，客户端重试可能产生重复效果。

判断“到底写没写”，应使用 revision、CreateRevision、ModRevision 或带 compare 的 Txn，而不是只看客户端错误。

### Orphaned Apply

apply 阶段会重新检查 request ID 是否仍有 waiter。若调用者已经超时：

- 有副作用的请求仍必须 apply，否则不同成员会出现状态分歧；
- 无人等待的无副作用请求可以跳过；
- 无人等待的写 Txn 可以跳过其内部 Range 的结果计算，但写操作不能跳过。

对应实现是 `needResult := w.IsRegistered(id)` 与 `SkipRangeExecution: !needResult && raftReq.Txn != nil`（`etcdserver/apply/apply.go:27-53`）。这说明 etcd 区分的是**执行语义**与**是否还需要生成客户端结果**。

## Raft Ready and Apply

### Ready Is a Pipeline Boundary

3.7.2 中，`raftNode` 消费外置 Raft 的 `Ready`，主路径位于 `etcdserver/raft.go:175-341`。真实顺序不能概括为“先落盘，再发消息，最后 apply”：

1. 先处理 `SoftState` 与 `ReadStates`；
2. 把 committed entries 和 snapshot 封装为 `toApply`；
3. 通过**无缓冲** `applyc` 投递，raft goroutine 会等到 apply 侧接走这个任务；
4. leader 发起副本消息发送，然后执行本地 snapshot / WAL `Save`；
5. follower 先完成本地 `Save`，再处理待发送消息；
6. 普通 follower 通过 `notifyc` 表示持久化阶段已完成；
7. 若包含 ConfChange，follower 还要再次阻塞，直到配置变更已 apply；
8. 调用 `Advance()`；ConfChange 额外发送 `raftAdvancedC`。

leader 的源码注释明确说明，本地磁盘写入可以与向 follower 复制并行（`raft.go:237-243`）。无缓冲 `applyc` 提供的是**任务交接的背压**，不是“apply 完成后才返回 Ready”。

### applyAll Order

`EtcdServer.applyAll` 的真实顺序尤其重要（`etcdserver/server.go:972-993`）：

```go
s.applySnapshot(ep, apply)
s.applyEntries(ep, apply)
backend.VerifyBackendConsistency(...)
s.applyWait.Trigger(ep.appliedi)

<-apply.notifyc
s.snapshotIfNeededAndCompactRaftLog(ep)
```

这意味着：

- 非空 snapshot 路径会先等待 `notifyc`，确认快照与 WAL snapshot record 已持久化，再切换 backend；随后才执行 entries；
- 普通 entry 路径不等待本地 WAL，`applyEntries` 按 entry 顺序执行；
- 每批 apply 后校验 backend 的 write view 与 read view；
- applied index 先推进，线性读才可能被唤醒；
- 普通 entry 路径中，本地 WAL 的 `notifyc` 是在 apply 与 applyWait 之后才等待；非空 snapshot 路径已在 `applySnapshot` 内先消费该屏障；
- 等待持久化的主要目的，是保证创建 snapshot / 压缩 Raft log 时，applied index 不会超过 Raft storage 中已有的日志。

`applyEntries` 不允许日志跳跃：若首条待 apply entry 的 index **大于** `applied + 1` 就直接 panic；若小于等于 `applied + 1`，则切掉已经应用的重复前缀，只执行剩余 entries（`etcdserver/server.go:1185-1209`）。

### Backend Consistency Check

`VerifyBackendConsistency` 比较 backend 的 BatchTx 与 ReadTx 视图，不一致会触发 verify panic。它跳过被标记为 safe-range 的 bucket，因此传入 `AllBuckets` 并不等于逐项扫描所有大桶（`storage/backend/verify.go:73-95`，跳过判断在 `:85-89`；`etcdserver/server.go:972-975`）。

这是一道内部损坏防线，不是 MVCC 语义校验：它不会验证“某个 revision 是否合理”，也不会自动修复数据。

## State Machine Apply

3.7 的 apply 代码已经拆到独立 `etcdserver/apply` 包。一条普通 entry 的执行链为：

```text
apply.Apply
  -> UberApplier
     -> CorruptApplier
     -> CappedApplier
     -> AuthApplier
     -> QuotaApplier
     -> BackendApplier
        -> Put / DeleteRange / Txn / Compact / Lease / Auth ...
```

`apply.Apply` 先解析 `InternalRaftRequest`，再决定是否需要结果、是否需要执行；`UberApplier` 负责把请求分派给具体状态机操作（`etcdserver/apply/apply.go:27-53`、`etcdserver/apply/uber_applier.go:82-211`）。

`applyEntryNormal` 在 apply 返回后按 request ID 触发 waiter。空 data 是 leader 在当前 term 确认时生成的 noop entry，用于推进 first-commit-in-term 与 lessor promotion，不修改用户键空间（`etcdserver/server.go:1945-2003`）。

### Quota Can Return an Error After Applying

`quotaApplierV3.Put` 的顺序是：

```go
ok := a.q.Available(p)
resp, trace, err := a.applierV3.Put(p)
if err == nil && !ok {
    err = errors.ErrNoSpace
}
```

也就是说，**导致后端超过配额的那次 Put 可能已经写入，但调用者收到 `ErrNoSpace`**。正常路径会在 goroutine 中先执行 Alarm 的 `raftRequest`，再 `Trigger` 原 waiter；已有 NOSPACE Alarm 等分支则直接 Trigger。因此 Trigger 不代表 Alarm 已提交，Alarm 仍需经 Raft apply，成员才进入 capped 状态并拒绝后续写入，“发现超配额”与“整个集群开始拒绝”之间存在窗口（`etcdserver/apply/quota.go:36-60`、`etcdserver/server.go:1981-2002`、`etcdserver/apply/uber_applier.go:70-88`）。

这与“超时后写入不确定”一样，都是 etcd 错误语义中必须显式处理的边界。

## MVCC Commit Boundary

### Revision Allocation

MVCC 写事务在 apply 阶段创建：

```go
tw := &storeTxnWrite{
    beginRev: s.currentRev,
    changes:  make([]*mvccpb.KeyValue, 0, 4),
}
```

每次变更使用：

```go
rev := tw.beginRev + 1
idxRev := Revision{Main: rev, Sub: int64(len(tw.changes))}
```

因此 revision 不是 API 层生成的，也不是 Raft index 的别名。一个事务中的所有变更共享 main，用 sub 保持确定性顺序（`storage/mvcc/kvstore_txn.go:166-184,223-261`）。

[treeIndex](/docs/CS/Framework/etcd/treeIndex.md) 保存的是用户 key 对应的 revision 代际信息，不是“指向磁盘 value 的指针”。真正 value 以序列化 `mvccpb.KeyValue` 存在 backend 的 `key` bucket 中，backend key 是 revision 编码。

### Memory Index, Buffer and bbolt

一次 put 依次完成：

1. 查询旧 key，保留 `CreateRevision`，递增 `Version`，处理 lease attach / detach；
2. 将 revision key 与 `KeyValue` value 写入 `UnsafeSeqPut`；
3. 更新 treeIndex；
4. 把变更追加到 `changes`；
5. 事务 `End` 时，若存在变更则递增 `currentRev`，随后解锁 backend batch transaction。

`UnsafeSeqPut` 同时更新 backend 写缓冲。BatchTx 解锁时，先把缓冲写回 ReadTx 的读缓冲；只有 pending 达到 batch limit 或存在 delete 时才立即 commit bbolt（`storage/backend/batch_tx.go:308-340`）。

这就是为什么“Put 成功”不要求每次调用都产生一次独立的 bbolt fsync：读路径会同时查看 bbolt 与读缓冲，逻辑可见性由 MVCC 锁与 revision 保证，磁盘持久化则按批次推进。

> [!IMPORTANT]
> delete 没有等价的缓冲读取语义，所以只要存在待提交删除，就必须立即 commit；否则下一条请求可能从 bbolt 读到旧数据，破坏 linearizability。源码在 `batch_tx.go:318-331` 明确解释了这一点。

### Watch Notify Before Txn End

watchable store 的 `End` 顺序是：

```go
tw.s.mu.Lock()
tw.s.notify(rev, evs)
tw.TxnWrite.End()
tw.s.mu.Unlock()
```

`notify` 先于底层事务结束，但整个过程持有 watchable store 锁，确保异步事件发送检查 `currentRev` 时不会观察到“半完成”的 revision（`storage/mvcc/watchable_store_txn.go:22-47`）。这不是事件先于数据可见的漏洞，而是一组经过锁约束的发布动作。

## Transaction Atomicity

写 Txn 在 apply 状态机中执行，入口是 `etcdserver/txn/txn.go:32-101`：

1. 创建 read view；
2. 在 read view 上计算 compare path，并检查所选分支的请求；
3. 写事务结束 read view，创建 `kv.Write`；
4. 在同一 write transaction 中执行 Success 或 Failure 分支；
5. 所有变更共享 `beginRev + 1`，结束后统一 `currentRev++`。

写 apply 是串行的，因此 compare 与写入之间不会插入另一个已提交写事务。事务中的 Range 也能看到本事务此前的写入，因为 `storeTxnWrite.Range` 会在已有 changes 时使用 `beginRev + 1`（`storage/mvcc/kvstore_txn.go:189-195`）。

若写事务执行中发生错误，etcd 选择 panic，而不是返回“部分成功”：

- 部分写入可能已经进入 backend buffer；
- 静默忽略会破坏事务原子性；
- 不同成员若不对称 apply，会产生持久分歧。

这就是 `txn.go:84-94` 的 `lg.Panic("unexpected error during txn with writes")`。对 etcd 而言，**确定性状态机的崩溃比带着未知部分结果继续服务更安全**。

## Read Path

### Serializable vs Linearizable

`Range` 在 v3.7.2 的入口是 `etcdserver/v3_server.go:106-155`：

- `Serializable=false`：先调用 `s.read.LinearizableReadNotify(ctx)`，再读本地 MVCC；
- `Serializable=true`：跳过 ReadIndex，直接读本地 MVCC；
- 只读 Txn 使用同样规则（`v3_server.go:325-372`）。

线性读不是“从 leader 读 value”，而是先确认一个 committed index，再等本地 applied index 追上，最后读本地状态机。串行读可能落后，但不会返回未提交数据。

### ReadIndex Batching

3.7 的线性读实现已迁入 `etcdserver/read/read.go`：

- `LinearizableReadNotify` 保存当前 notifier，并尽可能向 `waitC` 发信号；
- `LinearizableReadLoop` 替换 notifier，让一批并发读共享同一次 ReadIndex；
- `requestCurrentIndex` 发送带 8 字节 request ID 的 ReadIndex；
- 收到 `ReadState` 后忽略过期 request ID；
- 若 applied index 不足，等待 `ApplyWait(confirmedIndex)`；
- 最后一次性唤醒本轮 notifier 中的所有读。

对应源码：`read/read.go:74-146,148-248`。

3.7 还包含两个重试来源：**first commit in current term** 会重发 ReadIndex；`readIndexRetryTime` 到点也会重发。`requestIDs` 用 map 保存本轮所有已发送 ID，避免把旧响应当作当前结果。leader 变更或最终超时会通过 notifier 返回错误，不只是简单“交给客户端重试”。

### RangeStream

v3.7.2 新增 `RangeStream`。默认仍是线性读，但流式响应有一个关键约束：若客户端没有显式指定 revision，第一批响应得到 `headerRev` 后，后续 chunk 会固定在该 revision（`etcdserver/v3_server.go:157-292`）。

因此，流开始后提交的新写不会出现在后续 chunk 中。首批 chunk limit 为 10，之后根据前一批响应大小动态调整。它解决的是“大 Range 分批发送时快照漂移”，不是把 Range 变成 Watch。

## Watch Path

Watch 复用同一条 MVCC apply 链，不额外提出一条 Raft 写日志。写事务结束时，变更被转换为事件，`notify` 将事件投递给匹配的 synced watcher。

watch 的可靠性来自三类状态：

| 状态 | 含义 | 处理方式 |
| :--- | :--- | :--- |
| synced | 已追上当前 revision，等待新事件 | apply 时直接投递 |
| unsynced | 落后于当前 revision，需要历史回放 | 后台按 revision 范围扫描 backend |
| victim | 投递 channel 阻塞，事件暂时积压 | 保留批次并异步重试，不直接丢弃 |

历史回放由 `syncWatchersLoop` 驱动，默认每 100ms 检查一次；victim 重试由 `syncVictimsLoop` 驱动（`storage/mvcc/watchable_store.go:223-254,257-282`）。历史事件按 backend revision key 的范围扫描，再按 watcher 的 key / range 过滤；这一步依赖 revision 的有序物理布局，而不是用户前缀查询。

若 watcher 的起始 revision 已被 compaction 删除，watch 会被取消。正常事件响应通过 `CompactRevision` 指出可用的压缩水位；创建时直接给出负 `StartRevision` 的请求则在 `CancelReason` 中返回 `ErrCompacted`（`etcdserver/api/v3rpc/watch.go:270-277,459-465`）。客户端必须重新 List / Range 获取新快照，再从新 revision 开始 Watch，不能继续从旧游标盲重试。详见 [watch](/docs/CS/Framework/etcd/watch.md)。

## Lease Expiration Is Also a Write

lease 到期不是本地定时器直接从 backend 删除 key，而是一条需要共识的写路径：

1. lessor 每 500ms 扫描过期 lease，仅 primary 把待撤销批次发送到 `expiredC`；
2. server 再次确认 leadership，以容量 16 的 channel 限制并发撤销；
3. 每个 `LeaseRevoke` 封装为 `InternalRaftRequest`，走 waiter + Propose + apply；
4. apply 分派到 `Lessor.Revoke`，在一个 MVCC 写事务中排序 key 并逐项 `DeleteRange`；
5. 删除 lease 元数据并结束事务，生成 DELETE watch 事件。

源码落点：`lease/lessor.go:620-662`、`etcdserver/server.go:836-901`、`etcdserver/apply/backend.go:94-96`、`lease/lessor.go:326-364`。v3.7.2 的 `LeaseCheckpoint` 与 `LeaseCheckpointPersist` 默认均为 false；启用 `LeaseCheckpoint` 后，checkpoint 同样通过 Raft 传播 remaining TTL，但 checkpoint 本身不删除 key，也不增加 MVCC revision。

这解释了一个看似矛盾的现象：TTL 已过后才提交的 Put 仍可能成功，但随后被撤销；同一 key 上，普通 Put 与 LeaseRevoke 的最终顺序由 Raft log 顺序决定，而不是客户端调用时间。

## Persistence and Recovery

### WAL and Backend Are Different Stores

| 存储 | 保存内容 | 恢复时回答的问题 |
| :--- | :--- | : |
| WAL | metadata、Raft entries、HardState、snapshot record | 集群身份、term、commit、日志从哪里续接 |
| Raft snapshot | ConfState、applied index / term、状态机快照载荷 | 从哪里截断旧日志并恢复状态机 |
| backend `snap/db` | 已物化 KV、lease、auth、member、meta 等 | 本地状态机实际恢复到哪里 |
| consistent index | backend meta bucket 中已提交事务对应的 Raft index | 哪些 WAL entry 不需要再次 apply |

WAL `Save` 并不是每次调用都无条件 fsync：只有 `raft.MustSync` 或 segment cut 等路径触发同步；`UnsafeNoFsync` 还会跳过 fdatasync（`storage/wal/wal.go:995-1060`）。因此“调用 Save 返回”与“这一段数据已经克服所有断电窗口”不能简单画等号。

### Snapshot Barrier

本地落盘 snapshot（`toDisk`）的持久化顺序有严格约束（`etcdserver/server.go:2086-2135`）：

1. 先 `KV().Commit()`，把 consistent index 等元数据提交到 backend；
2. 创建 Raft snapshot；
3. `SaveSnap` 通过 `WriteAndSyncFile` 写入并 fsync 快照文件；该路径本身不 fsync snap 目录。目录 fsync 属于接收 leader DB snapshot 的 `SaveDBFrom` 路径；
4. 将 snapshot record 写入 WAL；
5. 释放 WAL 中可删除的旧日志。

`toDisk=false` 的内存 snapshot 只创建 Raft snapshot，不执行上述 backend Commit、SaveSnap、WAL record 与 Release。落盘路径保证 backend 的 `consistent_index >= snapshot.index`。接收 leader 的 DB snapshot 时，还必须先把临时文件 fsync、rename 并 fsync 目录，再处理对应 Raft 消息；这与本地 `.snap` 文件的保存路径不同（`etcdserver/api/snap/snapshotter.go:79-108`、`etcdserver/api/snap/db.go:33-83`）。

### Consistent Index

apply 前，server 设置 `ConsistentApplyingIndex`。backend 真正 commit 前，hook 调用 `UnsafeSave`，把 consistent index 与 term 写入 meta bucket（`etcdserver/server.go:1900-1913`、`storage/hooks.go:45-53`、`storage/schema/cindex.go:87-94`）。

这里必须区分：

- 内存 consistent index 已前进；
- 该 index 已随 bbolt 事务持久化。

只有后者能在重启时用于跳过已物化的 WAL entry。未提交的 bbolt 事务丢失 consistent index 后，相关 WAL entry 会重新 apply。

### Bootstrap Choice

启动顺序不能简化成“先读 WAL，再选 backend”（`etcdserver/bootstrap.go:77-90,231-280,413-465`）：

1. `bootstrapBackend` 先打开现有 backend，恢复其 consistent index；
2. `recoverSnapshot` 读取 WAL 中的 snapshot records，并构造供 Raft 使用的 snapshot 元数据；
3. `RecoverSnapshotBackend` 比较 snapshot index 与 backend consistent index：前者小于等于后者时保留现有 backend，更大时关闭旧 backend并打开 `.snap.db`；
4. backend 选择完成后，`bootstrapWALFromSnapshot` 才打开 WAL 并 `ReadAll`；
5. apply 时仅对 index 大于 consistent index 的 entry 执行 v3 状态机，避免重复物化。

`ForceNewCluster` 是例外：它会把 HardState.Commit 提升到 `max(WAL Commit, consistentIndex)`，丢弃未提交尾部，并强制提交配置变更 entries（`etcdserver/bootstrap.go:588-606`）。

MVCC restore 则从 backend 重建 treeIndex、恢复 lease 关联，并用 finished / scheduled compact revision 修正 `currentRev`，防止最新 revision 是 tombstone 且已被压缩时出现 revision 回退（`storage/mvcc/kvstore.go:292-413`）。

## Compaction and Recovery

Compaction 请求本身经 Raft 提交，apply 调用 `store.Compact`。它分为逻辑水位与物理回收两个阶段。

### Logical Waterline

`updateCompactRev` 在 `revMu` 下：

1. 拒绝小于等于 `compactMainRev` 的请求；
2. 拒绝大于 `currentRev` 的 future revision；
3. 更新内存 `compactMainRev`；
4. 将 scheduled compact revision 写入 backend；
5. `ForceCommit`，确保“准备压缩到哪”先持久化。

从这一刻起，低于水位的读会得到 `ErrCompacted`，但物理删除可能仍在后台进行（`storage/mvcc/kvstore.go:197-222`）。

### Physical Reclamation

FIFO 中的 compaction job 先压缩 treeIndex 的 keyIndex，再分批扫描 backend revision key，删除不在 keep set 中的历史。每批结束按需 `ForceCommit` 并让出调度；最后写入 finished compact revision（`storage/mvcc/kvstore_compaction.go:28-99`）。

scheduled 与 finished 是一对恢复锚点，但**存在性也必须一致**：

- 两个值都存在且 `scheduled == finished`：上次 compaction 已完成；
- 两个值都存在且 `scheduled > finished`：上次 compaction 未完成，重启后继续；
- 只有一个值存在：同样视为未完成；
- 扫描不到更高 revision 时，用 finished / scheduled 水位防止 `currentRev` 回退。

`checkPrevCompactionCompleted` 同时比较值和 `found` 标志；restore 则在 `scheduledCompact > compactMainRev` 时重新调度压缩（`storage/mvcc/kvstore.go:224-232,389-423`）。

v3.7.2 的 `CompactionRequest.Physical` 还允许调用者等待物理阶段完成；完成后 server 会 `ForceCommit`，避免 finished compaction 在崩溃后回退并重复执行（`etcdserver/v3_server.go:382-431`）。

Compaction 删除的是历史版本，不等于 defrag 立即缩小数据库文件。完整操作对比见 [compact](/docs/CS/Framework/etcd/compact.md)。

## Failure Matrix

| 故障 / 观察 | 实际语义 | 判断与处置 |
| :--- | :--- | :--- |
| 客户端 Put 超时 | 可能未提交，也可能已提交但响应丢失 | 用 revision / compare Txn 读回确认，避免盲目非幂等重试 |
| commit 领先 apply | 日志已共识，状态机尚未物化 | 看 apply lag、慢盘与昂贵 apply；积压超过 5000 会拒绝新提案 |
| leader 变更 | proposal 可能被丢弃，ReadIndex 会重发或报错 | 区分“提案前失败”与“提交后未知” |
| Put 返回 NOSPACE | 触发配额的写可能已经 apply；NOSPACE Alarm 本身也要经 Raft | 检查实际键值，确认各 member 已 apply alarm，disarm 后再恢复写入 |
| 本地 WAL 慢 | apply 与副本发送形成背压 | `notifyc` 是 snapshot 前置屏障，不是每次 apply 的前置条件 |
| watch channel 满 | watcher 转 victim，事件保留重试 | 不要假设 server 丢事件；检查客户端消费与 compaction |
| watch 收到 compacted | 起始 revision 已不可回放 | 重新 Range / List，再从新 revision Watch |
| WAL 已提交、backend 未提交 | consistent index 不会越过未持久化事务 | 重启后重放相应 WAL entry |
| compaction 中崩溃 | scheduled / finished 描述中断位置 | 重启后继续压缩，并用 scheduled 防止 revision 回退 |
| backend 索引查不到 revision | 内存索引与物化数据不一致 | server Fatal；这是损坏，不是普通 miss |
| apply 写 Txn 出错 | 可能已有部分变更进入执行 | panic，避免成员间非对称状态 |

更完整的指标、告警与处置见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md) 与 [monitoring](/docs/CS/Framework/etcd/monitoring.md)。

## v3.7.2 Counterintuitive Points

1. **revision 在 apply 才分配。** API 层只负责构造请求，Raft 只负责对 entry 排序。
2. **committed 与 applied 是两个水位。** 线性读等待 applied，不是等待 commit。
3. **`applyAll` 先 apply、先 trigger applyWait，再等待 WAL `notifyc`。** 该等待主要用于 snapshot 与 Raft log compaction 安全。
4. **`Ready` 不是“全部处理完”的批。** 它包含可并行推进的消息、持久化与 apply 工作。
5. **请求超时不会取消已提交写入。** waiter 消失只意味着结果不再需要返回。
6. **NOSPACE 的那一次 Put 可能已写入。** quota applier 先 apply，再根据入口预算结果返回错误；Alarm 经共识 apply 后才开始拒绝后续写入。
7. **一个 Txn 只递增一次 main revision。** 多 key 变化靠 sub 排序。
8. **Put 不必每次立即提交 bbolt。** 读缓冲保证可见性；delete 则必须立即提交。
9. **watch notify 早于底层 Txn End。** watchable store 锁约束了发布顺序。
10. **lease 到期删除也是 Raft 写。** TTL 与 Put 的最终顺序由日志决定。
11. **Compaction 的逻辑水位先于物理删除。** scheduled revision 还要先持久化。
12. **WAL Save 不等于无条件 fsync。** `MustSync`、segment cut 与 `UnsafeNoFsync` 决定真实持久边界。
13. **RangeStream 的后续 chunk 不漂移。** 未指定 revision 时，首批响应会固定整个流的快照。
14. **PriorityRequest 默认关闭。** 只有显式开启后，LeaseRevoke 才获得 10000 的 apply-gap 宽限。
15. **Raft peer 不是 gRPC。** 客户端 API 使用 gRPC，成员复制使用 rafthttp / HTTP/2。

## Source Map

| 主题 | v3.7.2 源码 |
| :--- | :--- |
| Put / Txn / Range / RangeStream / 提案入口 | `server/etcdserver/v3_server.go` |
| Ready 消费与角色差异 | `server/etcdserver/raft.go` |
| applyAll / applyEntries / waiter 触发 | `server/etcdserver/server.go` |
| apply 分派与 waiter 裁剪 | `server/etcdserver/apply/apply.go`、`uber_applier.go`、`quota.go` |
| Txn compare / 分支 / 原子 revision | `server/etcdserver/txn/txn.go`、`put.go` |
| MVCC read / write / revision | `server/storage/mvcc/kvstore_txn.go` |
| watch 发布与历史同步 | `server/storage/mvcc/watchable_store_txn.go`、`watchable_store.go` |
| backend 批量提交与 delete 边界 | `server/storage/backend/batch_tx.go` |
| ReadIndex 批量与重试 | `server/etcdserver/read/read.go` |
| lease 扫描与撤销 | `server/lease/lessor.go`、`server/etcdserver/server.go` |
| WAL / snapshot / consistent index | `server/storage/wal/wal.go`、`server/etcdserver/bootstrap.go`、`server/storage/schema/cindex.go` |
| compaction / restore | `server/storage/mvcc/kvstore.go`、`kvstore_compaction.go` |

## Links

- [cluster（成员变更、快照与备份恢复）](/docs/CS/Framework/etcd/cluster.md)
- [concurrency（锁、选举与 STM 的 revision 依赖）](/docs/CS/Framework/etcd/concurrency.md)
- [net（gRPC API 与 rafthttp peer 传输）](/docs/CS/Framework/etcd/net.md)
- [client（重试与请求结果语义）](/docs/CS/Framework/etcd/client.md)

## References

- [etcd v3.7.2 - EtcdServer API and proposal path](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/v3_server.go)
- [etcd v3.7.2 - raftNode Ready processing](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/raft.go)
- [etcd v3.7.2 - EtcdServer apply pipeline](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/server.go)
- [etcd v3.7.2 - apply dispatcher](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/apply/apply.go)
- [etcd v3.7.2 - quota applier](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/apply/quota.go)
- [etcd v3.7.2 - transaction execution](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/txn/txn.go)
- [etcd v3.7.2 - MVCC transaction implementation](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/kvstore_txn.go)
- [etcd v3.7.2 - watch transaction publication](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/watchable_store_txn.go)
- [etcd v3.7.2 - watch synchronization](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/watchable_store.go)
- [etcd v3.7.2 - backend batch transaction](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/backend/batch_tx.go)
- [etcd v3.7.2 - linearizable read loop](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/read/read.go)
- [etcd v3.7.2 - lessor](https://github.com/etcd-io/etcd/blob/v3.7.2/server/lease/lessor.go)
- [etcd v3.7.2 - WAL implementation](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/wal/wal.go)
- [etcd v3.7.2 - bootstrap recovery](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/bootstrap.go)
- [etcd v3.7.2 - MVCC compaction and restore](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/kvstore.go)
- [etcd v3.7.2 - physical compaction](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/kvstore_compaction.go)
