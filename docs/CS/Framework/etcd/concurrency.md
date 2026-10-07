## Introduction

`go.etcd.io/etcd/client/v3/concurrency` 是基于 etcd 的**分布式原语库**，把"锁 / 事务 / 选主"这类靠 Lease + MVCC 版本号 + Txn 才能实现的东西封装成可直接用的 API。所有原语都建立在 [client](/docs/CS/Framework/etcd/client.md) 之上，并依赖一个核心概念 **Session**（背后是 Lease + keepalive）。

etcd.md 的 `Transaction` 段末尾甩了个 STM 链接就完了（[etcd.md](/docs/CS/Framework/etcd/etcd.md) Features→Transaction），没展开这个库。本文补全 Mutex / STM / Election / Session 四个原语的接口、实现要点与坑。

> [!NOTE]
> **版本基线**：etcd **3.7.2**（`api/version/version.go`）。本文所有签名逐条对照 `client/v3/concurrency/` 核实。注意 v3.5 → v3.7 期间该包有一次**公开 API 破坏性变更**：选项类型从未导出的 `stmOption` / `sessionOption` 改为导出的 `STMOption` / `SessionOption`——照旧文档写 `so ...stmOption` 会编译不过。

> [!NOTE]
> concurrency 包**没有**队列（Queue）类型——只有 `Session`、`Mutex`（含 `NewLocker`）、`STM`、`Election`。早年示例里出现过 queue 用法，但当前包不含 `NewQueue`；需要分布式队列请基于 `Election` 或 `Mutex` + 前缀自行实现。

## Session (The Foundation of All Primitives)

```go
s, err := concurrency.NewSession(client, concurrency.WithTTL(10))  // 10s 租约
defer s.Close()
```

- `NewSession(client, opts...)`：创建一个绑定了 Lease 的会话。`WithTTL(ttl int)` 设租约秒数；`WithLease(leaseID)` 复用已有租约；`WithContext(ctx)` 用自定义 ctx 而非 `context.Background()`。
- **不传 `WithTTL` 时 TTL 取 `defaultSessionTTL = 60` 秒**（`session.go`）。传了 `ttl <= 0` 会打 Warn 并**沿用原值**，不会报错——想「永不过期」不能靠传 0。
- `s.Lease()` 返回 `v3.LeaseID`——所有原语把 key 的租约设成它。
- `s.Done()` 是 `<-chan struct{}`，**会话失效时关闭**（租约过期 / 连接断 / `Close()`）。基于 Session 的锁、选主都会随之自动释放，这是"崩溃不死锁"的关键。
- `s.Close()` 主动释放租约；`s.Orphan()` 让 Session 失效但不删租约（用于接管场景）。
- `s.Client()` / `s.Ctx()` 是 3.7 新增的取值方法（v3.5 没有）。

> [!WARNING]
> 务必 `defer s.Close()`。Session 背后是 Lease keepalive 流，不关会泄漏 goroutine 与租约。更要紧的是：锁/选主的生命周期跟随 Session——客户端崩溃 → 租约过期 → 原语自动释放；但若你手动 `Close()` 了 Session，对应锁立即释放，即使业务还没跑完。

## Mutex (Distributed Lock)

```go
m := concurrency.NewMutex(s, "/my-lock/")
if err := m.Lock(ctx); err != nil { /* ... */ }
defer m.Unlock(ctx)
// 临界区
```

- `NewMutex(s *Session, pfx string) *Mutex`：在 `pfx` 前缀下用 Session 的租约竞争。
- `Lock(ctx)` / `TryLock(ctx)`（后者在已被他人持有时返回 `ErrLocked`）/ `Unlock(ctx)`。
- 除 `ErrLocked` 外还有两个错误值要区分：`ErrSessionExpired`（Session 已失效，通常是租约没续上）与 `ErrLockReleased`（锁已不再归你持有，多为 Session 已被 `Close()`）。三者都在 `mutex.go` 里定义。
- `IsOwner() v3.Cmp`：返回一个 `Compare`，可在自己的 Txn 里判断"我是否仍持锁"，做 fencing。
- `NewLocker(s *Session, pfx string) sync.Locker`：把 Mutex 包成标准库 `sync.Locker`（`Lock()` / `Unlock()` 无 ctx），方便替换本地锁。
- `Key()` / `Header()` 返回该锁的 key 前缀与上次写请求的 header，可用于排查与 fencing。

实现要点（来自 `mutex.go`）：锁的持有者是在 `pfx` 前缀下 **createRevision 最小**且带有效租约的那把 key。`Lock` 用 Txn 尝试创建带租约的 key（version=0 才创建成功），失败则 `WaitDelete` 等前驱释放。因为 key 绑了 Session 租约，持锁方崩溃 → 租约过期 → key 删除 → 后续者拿到锁。

> [!WARNING]
> 锁的"自动释放"依赖租约保活。若持锁方发生**长 GC / 网络分区**导致 keepalive 没及时续上、租约过期，锁会被释放、另一客户端可能拿到同一把锁——出现双持。需要严格 fencing 的业务应配合 `IsOwner()` 的 Txn 校验或版本号 fencing token，不要只靠锁本身。

## STM (Software Transactional Memory)

```go
_, err := concurrency.NewSTM(client, func(stm concurrency.STM) error {
    val := stm.Get("alice")          // 读
    stm.Put("alice", newVal)         // 写（事务内，未提交不可见）
    return nil
}, concurrency.WithIsolation(concurrency.SerializableSnapshot))
```

- `NewSTM(c *v3.Client, apply func(STM) error, so ...STMOption) (*v3.TxnResponse, error)`：**默认 SerializableSnapshot 隔离**。注意选项类型在 3.7 已导出为 `STMOption`（旧版是未导出的 `stmOption`）。
- `STM` 接口方法：`Get(keys ...string) string`、`Put(key, val string, opts ...)`、`Del(key)`、`Rev(key string) int64`——`Rev` 返回的是 **int64 的 revision 号**，不是字符串。
- 隔离级别（`Isolation` 常量）：
  - `SerializableSnapshot`（默认）：可串行化快照隔离，**提交时检查写冲突**。
  - `Serializable`：同一事务尝试内多次读返回首次读的 revision。
  - `RepeatableReads`：同一事务尝试内读永远返回相同数据。
  - `ReadCommitted`：从任意已提交 revision 读。
- 选项：`WithIsolation(lvl)`、`WithAbortContext(ctx)`（ctx 取消即中止）、`WithPrefetch(keys...)`（事务前预取，减少往返）。

实现要点（来自 `stm.go`）：乐观并发——事务内读写先攒在 readSet / writeSet，提交时把 readSet 各 key 的 revision 作为 `v3.Cmp` 放进一个 Txn；若任一 key 的 revision 已被别人改过，Txn 失败 → 重试 `apply`。这就是 etcd.md Transaction 段讲的"基于 MVCC 版本号实现隔离级别"的库级落地。

> [!NOTE]
> STM 把 etcd.md 里 `If(mod("Alice")=v1).Then(...)` 那种手写 Txn 封装成了 `Get`/`Put` + 自动冲突重试，应用层只写业务逻辑。它与 [MVCC](/docs/CS/Framework/etcd/MVCC.md) 的 revision 机制、[compact](/docs/CS/Framework/etcd/compact.md) 的历史压缩强相关：readSet 依赖的旧 revision 若被 compact 掉，事务会失败需重试。

## Election (Leader Election)

```go
e := concurrency.NewElection(s, "/my-leader/")
if err := e.Campaign(ctx, "my-value"); err != nil { /* ... */ }
// 成为 leader，执行业务
if resp, err := e.Leader(ctx); err == nil { /* 当前 leader 是 resp */ }
// 让贤
e.Resign(ctx)
```

- `NewElection(s *Session, pfx string) *Election`；`ResumeElection(s, pfx, leaderKey, leaderRev)` 从已知 leader 信息恢复。
- `Campaign(ctx, val)`：在 `pfx` 下创建带 Session 租约的 key，`createRevision` 最小者即为 leader；非最小者阻塞等待前驱。
- `Proclaim(ctx, val)`：leader 在不重新选举的情况下公告新值。
- `Resign(ctx)`：删掉自己的 leader key，触发新一轮选举。
- `Leader(ctx)` 查当前 leader；`Observe(ctx)` 返回一个可靠按序观察 leader 变更的 channel。
- `Key()` / `Rev()` / `Header()` 暴露 leader key、本地记录的 leader revision 与请求 header。

实现要点（来自 `election.go`）：与 Mutex 同源——leader 是 `pfx` 下 createRevision 最小的带租约 key。`Campaign` 内部用 `v3.Compare(v3.CreateRevision(leaderKey), "=", leaderRev)` 保证只有自己能 `Proclaim`/`Resign`。leader 崩溃 → 租约过期 → key 删 → 其余候选者中 createRevision 最小者上位。

## Cooperation with Client Retry Semantics

[client](/docs/CS/Framework/etcd/client.md) 里讲明：写操作是 **at-most-once**，仅在"连接都没建起来"时才重试。concurrency 的 `Lock`/`Campaign`/`Put` 底层都是 Txn/Put，因此：
- 拿到 `Unavailable` 等错误**不要盲目重放** `Lock`/`Campaign`——客户端无法区分"请求没到"和"已提交但响应丢了"。
- 正确做法是依赖 Session 租约自动释放 + 业务层幂等，而非在调用点无脑重试。

## Pitfall List

> [!WARNING]
> 下面几条都是「照旧文档/旧示例抄下来就跑不对」的点，逐条对照 3.7.2 源码核实过。

1. **`so ...stmOption` 编译不过** —— 3.7 里选项类型已导出为 `STMOption`（`stm.go`），`sessionOption` 同样改为 `SessionOption`。旧教程与 StackOverflow 片段里的未导出名字是 v3.5 及以前的。
2. **`Rev()` 返回 `int64` 不是 `string`** —— 拿它去和字符串比大小会静默出错。它就是 MVCC 的全局 revision，配合 [MVCC.md](/docs/CS/Framework/etcd/MVCC.md) 理解。
3. **Session 默认 TTL 是 60 秒，不是「无限」** —— 忘写 `WithTTL` 就用默认值；写 `WithTTL(0)` 想关掉保活只会被 Warn 并仍用 60s。想真的不失效得自己传一个极大值并容忍 `MaxLeaseTTL` 上限。
4. **只有一个错误值 `ErrLocked` 是不够的** —— `ErrSessionExpired`（Session 失效）与 `ErrLockReleased`（锁已易主）走的是不同分支。笼统地 `if err != nil { retry }` 会把「我已不再持锁」当成「竞争失败」，做出错误的事务补偿。
5. **`Close()` 会立即释放锁** —— `defer s.Close()` 与 `defer m.Unlock(ctx)` 的**顺序**有语义差别：后者先执行才是先解锁。反过来写（先 `Close` 后 `Unlock`）会拿到 `ErrLockReleased`。
6. **锁的自动释放依赖 keepalive，不等于互斥绝对成立** —— 长 GC / 网络分区导致租约过期时锁会消失、另一客户端可同时拿到。需要严格 fencing 就叠加 `IsOwner()` 或版本号 token。
7. **不要在 `Lock`/`Campaign` 失败点无脑重试** —— 见上节「与客户端重试语义的配合」，写操作是 at-most-once。
8. **`NewSTMRepeatable` / `NewSTMSerializable` / `NewSTMReadCommitted` 已 Deprecated** —— 仍能编译，但新代码用 `NewSTM` + `WithIsolation`。
9. **concurrency 包没有 Queue** —— 别去找 `NewQueue`。需要队列就基于 `Election` 或 `Mutex` + 前缀自建。

## Links

- [etcd（Transaction 段提到的 STM）](/docs/CS/Framework/etcd/etcd.md)
- [client（重试语义 / Session 依赖的 gRPC 连接）](/docs/CS/Framework/etcd/client.md)
- [lease（Session 背后的租约与 keepalive）](/docs/CS/Framework/etcd/lease.md)
- [MVCC（revision 与 STM 冲突检测）](/docs/CS/Framework/etcd/MVCC.md)
- [compact（历史压缩影响 STM readSet）](/docs/CS/Framework/etcd/compact.md)

## References

1. [etcd source - client/v3/concurrency/mutex.go](https://github.com/etcd-io/etcd/blob/v3.7.2/client/v3/concurrency/mutex.go)
2. [etcd source - client/v3/concurrency/stm.go](https://github.com/etcd-io/etcd/blob/v3.7.2/client/v3/concurrency/stm.go)
3. [etcd source - client/v3/concurrency/election.go](https://github.com/etcd-io/etcd/blob/v3.7.2/client/v3/concurrency/election.go)
4. [etcd source - client/v3/concurrency/session.go](https://github.com/etcd-io/etcd/blob/v3.7.2/client/v3/concurrency/session.go)
