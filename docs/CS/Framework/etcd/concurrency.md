# Concurrency Primitives

## Introduction

`go.etcd.io/etcd/client/v3/concurrency` 是基于 etcd 的**分布式原语库**，把"锁 / 选主 / 事务内存"这类靠 Lease + MVCC 版本号 + Txn 才能实现的机制封装成可直接用的 API。所有原语都建立在 [client](/docs/CS/Framework/etcd/client.md) 之上，并依赖一个核心概念 **Session**（背后是 Lease + keepalive）。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下片段均取自该 tag（`client/v3/concurrency/`）。

从源码核实的几个反直觉点：

- **选项类型已导出**：3.7 里是 `STMOption` / `SessionOption`（大写），旧教程里的未导出 `stmOption` / `sessionOption` 会编译不过。
- **包里没有 Queue**：只有 `Session`、`Mutex`（含 `NewLocker`）、`STM`、`Election`，没有 `NewQueue`。
- **Session 默认 TTL 是 60 秒**：`const defaultSessionTTL = 60`，传 `<=0` 只会被 Warn 并沿用原值，想"永不过期"不能靠传 0。

## Session

Session 是所有原语的地基——一个绑定了 Lease 的会话，靠 keepalive 保活。`NewSession` 默认把 TTL 设为 `defaultSessionTTL`：

```go
const defaultSessionTTL = 60

// Session represents a lease kept alive for the lifetime of a client.
// Fault-tolerant applications may use sessions to reason about liveness.
type Session struct {
	client *v3.Client
	opts   *sessionOptions
	id     v3.LeaseID

	ctx    context.Context
	cancel context.CancelFunc
	donec  <-chan struct{}
}

// NewSession gets the leased session for a client.
func NewSession(client *v3.Client, opts ...SessionOption) (*Session, error) {
	lg := client.GetLogger()
	ops := &sessionOptions{ttl: defaultSessionTTL, ctx: client.Ctx()}
	for _, opt := range opts {
		opt(ops, lg)
	}
	// ... 省略：Grant lease 并启动 keepalive
}
```

要点：

- `WithTTL(ttl)` 设租约秒数；`WithLease(leaseID)` 复用已有租约；`WithContext(ctx)` 用自定义 ctx。
- `s.Lease()` 返回 `v3.LeaseID`，所有原语把 key 的租约设成它。
- `s.Done()` 在会话失效时关闭（租约过期 / 断连 / `Close()`）——基于 Session 的锁、选主随之自动释放，这是"崩溃不死锁"的关键。
- `s.Close()` 主动释放租约；`s.Orphan()` 让 Session 失效但不删租约（接管场景）。

> [!WARNING]
> 务必 `defer s.Close()`：Session 背后是 keepalive 流，不关会泄漏 goroutine 与租约。更要紧的是锁/选主的生命周期跟随 Session——若你手动 `Close()` 了 Session，对应锁立即释放，即使业务还没跑完。

## Mutex

`Mutex` 用 Txn 在前缀下创建带租约的 key，`createRevision` 最小且持有效租约者持锁。三个错误值必须区分：

```go
var (
	ErrLocked         = errors.New("mutex: Locked by another session")
	ErrSessionExpired = errors.New("mutex: session is expired")
	ErrLockReleased   = errors.New("mutex: lock has already been released")
)

type Mutex struct {
	s *Session

	pfx   string
	myKey string
	myRev int64
	hdr   *pb.ResponseHeader
}
```

`Lock` 尝试获取锁，失败则 `waitDeletes` 等前驱（revision 小于自己）的 key 被删；拿到后再 `Get` 一次确认 session key 仍在——不在就返回 `ErrSessionExpired`：

```go
func (m *Mutex) Lock(ctx context.Context) error {
	resp, err := m.tryAcquire(ctx)
	if err != nil {
		return err
	}
	// if no key on prefix / the minimum rev is key, already hold the lock
	ownerKey := resp.Responses[1].GetResponseRange().Kvs
	if len(ownerKey) == 0 || ownerKey[0].CreateRevision == m.myRev {
		m.hdr = resp.Header
		return nil
	}
	client := m.s.Client()
	// wait for deletion revisions prior to myKey
	werr := waitDeletes(ctx, client, m.pfx, m.myRev-1)
	if werr != nil {
		m.Unlock(client.Ctx())
		return werr
	}
	// make sure the session is not expired, and the owner key still exists.
	gresp, werr := client.Get(ctx, m.myKey)
	if werr != nil {
		m.Unlock(client.Ctx())
		return werr
	}
	if len(gresp.Kvs) == 0 { // is the session key lost?
		return ErrSessionExpired
	}
	m.hdr = gresp.Header
	return nil
}
```

`TryLock` 在已被他人持有时立即返回 `ErrLocked`（先删掉自己刚创建的 key）。`IsOwner() v3.Cmp` 返回一个 `Compare`，可在自己的 Txn 里判断"是否仍持锁"做 fencing；`NewLocker` 把 Mutex 包成标准库 `sync.Locker`。

> [!WARNING]
> 锁的自动释放依赖租约保活。若持锁方长 GC / 网络分区导致 keepalive 没续上、租约过期，锁会被释放、另一客户端可能同时拿到——出现双持。严格 fencing 的业务应叠加 `IsOwner()` 的 Txn 校验或版本号 token。

## STM

STM（软件事务内存）把 etcd.md 里手写的 `If(mod("Alice")=v1).Then(...)` 封装成 `Get`/`Put` + 自动冲突重试。四种隔离级别是枚举常量，默认 `SerializableSnapshot`：

```go
type Isolation int

const (
	// SerializableSnapshot provides serializable isolation and also checks
	// for write conflicts.
	SerializableSnapshot Isolation = iota
	// Serializable reads within the same transaction attempt return data
	// from the revision of the first read.
	Serializable
	// RepeatableReads reads within the same transaction attempt always
	// return the same data.
	RepeatableReads
	// ReadCommitted reads keys from any committed revision.
	ReadCommitted
)

// STMOption configures STM.
type STMOption func(*stmOptions)

// NewSTM initiates a new STM instance, using serializable snapshot isolation by default.
func NewSTM(c *v3.Client, apply func(STM) error, so ...STMOption) (*v3.TxnResponse, error) {
	// ... 省略：应用 WithIsolation / WithPrefetch，runSTM 执行
}
```

- `STM` 接口方法：`Get(keys ...string) string`、`Put(key, val string, opts...)`、`Del(key)`、`Rev(key string) int64`（返回的是 MVCC 全局 revision，**int64 不是 string**）。
- 选项：`WithIsolation(lvl)`、`WithAbortContext(ctx)`、`WithPrefetch(keys...)`。
- 实现是乐观并发：读写攒在 readSet / writeSet，提交时把 readSet 各 key 的 revision 作为 `v3.Cmp` 放进 Txn；任一 key 被改过则失败重试 `apply`。

> [!NOTE]
> readSet 依赖的旧 revision 若被 [compact](/docs/CS/Framework/etcd/compact.md) 掉，事务会失败需重试——这是 STM 与历史压缩强相关的点。

## Election

`Election` 与 Mutex 同源：leader 是 `pfx` 下 `createRevision` 最小的带租约 key。`Campaign` 创建带 Session 租约的 key，非最小者阻塞等前驱：

```go
func NewElection(s *Session, pfx string) *Election { /* ... */ }

// Campaign puts a value as eligible for the election on the prefix.
// It blocks until elected; it fails with an ErrSessionExpired if the session expired.
func (e *Election) Campaign(ctx context.Context, val string) error { /* ... */ }
```

- `ResumeElection(s, pfx, leaderKey, leaderRev)` 从已知 leader 信息恢复。
- `Proclaim(ctx, val)`：leader 不重新选举就公告新值。
- `Resign(ctx)`：删掉自己的 leader key，触发新一轮选举。
- `Leader(ctx)` 查当前 leader；`Observe(ctx)` 返回按序观察 leader 变更的 channel。
- `Key()` / `Rev()` / `Header()` 暴露 leader key、revision 与 header。

leader 崩溃 → 租约过期 → key 删 → 其余候选者中 createRevision 最小者上位。`Campaign` 内部用 `v3.Compare(v3.CreateRevision(leaderKey), "=", leaderRev)` 保证只有自己能 `Proclaim`/`Resign`。

## Cooperation with Client Retry Semantics

[client](/docs/CS/Framework/etcd/client.md) 里讲明：写操作是 **at-most-once**，仅在"连接都没建起来"时才重试。`Lock`/`Campaign`/`STM` 提交底层都是 Txn/Put，因此：

- 拿到 `Unavailable` 等错误**不要盲目重放** `Lock`/`Campaign`——客户端无法区分"请求没到"和"已提交但响应丢了"。
- 正确做法是依赖 Session 租约自动释放 + 业务幂等，而非在调用点无脑重试。

## Pitfall List

> [!WARNING]
> 以下几条都是"照旧文档抄下来就跑不对"的点，均对照 3.7.4 源码核实。

1. **`so ...stmOption` 编译不过** —— 3.7 已导出为 `STMOption`，`sessionOption` 同样改为 `SessionOption`。
2. **`Rev()` 返回 `int64` 不是 `string`** —— 拿它和字符串比大小会静默出错。
3. **Session 默认 TTL 60 秒** —— `WithTTL(0)` 只会被 Warn 并沿用 60s；想真不失效要传极大值并容忍 `MaxLeaseTTL` 上限。
4. **别只判断 `ErrLocked`** —— `ErrSessionExpired`（Session 失效）与 `ErrLockReleased`（锁已易主）走不同分支，笼统 retry 会做错误的事务补偿。
5. **defer 顺序有语义差别** —— `defer s.Close()` 与 `defer m.Unlock(ctx)` 的顺序决定谁先执行；先 `Close` 后 `Unlock` 会拿到 `ErrLockReleased`。
6. **自动释放 ≠ 绝对互斥** —— 长 GC / 分区导致租约过期时锁会消失，严格 fencing 要叠加 `IsOwner()` 或版本号 token。
7. **别在 `Lock`/`Campaign` 失败点无脑重试** —— 写操作 at-most-once（见上节）。
8. **三个旧构造函数已 Deprecated** —— `NewSTMRepeatable` / `NewSTMSerializable` / `NewSTMReadCommitted` 仍能编译，新代码用 `NewSTM` + `WithIsolation`。
9. **包里没有 Queue** —— 需要队列就基于 `Election` 或 `Mutex` + 前缀自建。

## Links

- [client](/docs/CS/Framework/etcd/client.md)
- [lease](/docs/CS/Framework/etcd/lease.md)
- [MVCC](/docs/CS/Framework/etcd/MVCC.md)
- [compact](/docs/CS/Framework/etcd/compact.md)
- [etcd](/docs/CS/Framework/etcd/etcd.md)

## References

1. [etcd v3.7.4 源码（client/v3/concurrency/session.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/client/v3/concurrency/session.go)
2. [etcd v3.7.4 源码（client/v3/concurrency/mutex.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/client/v3/concurrency/mutex.go)
3. [etcd v3.7.4 源码（client/v3/concurrency/stm.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/client/v3/concurrency/stm.go)
4. [etcd v3.7.4 源码（client/v3/concurrency/election.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/client/v3/concurrency/election.go)
