# Lease: TTL and Expiration

## Introduction

Lease 是 client 与 etcd server 之间的 TTL 契约：key 挂到某个 lease 上，只要 lease 在有效期内就不被删除；client 靠 `KeepAlive` 续期，server 由 leader 负责淘汰过期 lease 并删除其关联 key。生命周期的主角是 `server/lease` 的 `Lessor`、最小堆与 500ms 主循环。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下片段均取自该 tag。

四个从源码核验出来的反直觉点：

- **有两个同名 `Lessor` 接口**：`server/lease.Lessor` 是**进程内**能力（`Grant` / `Revoke` / `Attach` / `Renew` / `Promote` / `Demote` / `Lookup` 等）；`etcdserver.Lessor`（定义在 `v3_server.go`）才包含 `LeaseGrant` / `LeaseRevoke` / `LeaseRenew` / `LeaseTimeToLive` / `LeaseLeases` 这些 RPC 级方法。常见错误是拿客户端 API 去 `server/lease/lessor.go` 里找。
- **`Promote` 不在 leadership 回调里调**：它在 apply 到 leader 的 **noop entry** 时执行（`s.firstCommitInTerm.Notify()` 就在同一处），寓意是「apply 完上个 term 的所有 entry 后，新 leader 才真正接管 lease」。
- **TTL 会被静默钳制**：`MaxLeaseTTL` 是导出常量 `9000000000`；`minLeaseTTL` 不是常量而是 `lessor` 的字段，由 `ceil(1.5 × ElectionTicks × heartbeat)` 算出，申请 1 秒 TTL 实际拿到的可能更长且不报错。
- **注释描述的是计划不是现状**：`LeaseCheckpointPersist` 的注释写着「v3.6 起默认启用、v3.7 移除」，但 3.7.4 里它既没移除也不是默认启用——仍是 alpha + 默认 false。判断实际行为只能读 feature gate 的默认值代码。

## Two Lessor Interfaces

进程内接口管的是「lease 对象 + 它挂了哪些 item」：

```go
type Lessor interface {
	// SetRangeDeleter lets the lessor create TxnDeletes to the store.
	// Lessor deletes the items in the revoked or expired lease by creating
	// new TxnDeletes.
	SetRangeDeleter(rd RangeDeleter)

	SetCheckpointer(cp Checkpointer)

	// Grant grants a lease that expires at least after TTL seconds.
	Grant(id LeaseID, ttl int64) (*Lease, error)
	// Revoke revokes a lease with given ID. The item attached to the
	// given lease will be removed. If the ID does not exist, an error
	// will be returned.
	Revoke(id LeaseID) error

	// Checkpoint applies the remainingTTL of a lease. The remainingTTL is used in Promote to set
	// the expiry of leases to less than the full TTL when possible.
	Checkpoint(id LeaseID, remainingTTL int64) error

	// Attach attaches given leaseItem to the lease with given LeaseID.
	Attach(id LeaseID, items []LeaseItem) error
	// GetLease returns LeaseID for given item.
	GetLease(item LeaseItem) LeaseID
	// Detach detaches given leaseItem from the lease with given LeaseID.
	Detach(id LeaseID, items []LeaseItem) error

	// Promote promotes the lessor to be the primary lessor.
	Promote(extend time.Duration)
	// Demote demotes the lessor from being the primary lessor.
	Demote()

	// Renew renews a lease with given ID. It returns the renewed TTL.
	Renew(id LeaseID) (int64, error)
	// Lookup gives the lease at a given lease id, if any
	Lookup(id LeaseID) *Lease
	// Leases lists all leases.
	Leases() []*Lease
	// ExpiredLeasesC returns a chan that is used to receive expired leases.
	ExpiredLeasesC() <-chan []*Lease
	// Recover recovers the lessor state from the given backend and RangeDeleter.
	Recover(b backend.Backend, rd RangeDeleter)
	// Stop stops the lessor for managing leases.
	Stop()
}
```

RPC 级接口则是另一组方法；gRPC 接入层 `LeaseServer` 持有的是它，不是上面那个：

```go
type Lessor interface {
	// LeaseGrant sends LeaseGrant request to raft and toApply it after committed.
	LeaseGrant(ctx context.Context, r *pb.LeaseGrantRequest) (*pb.LeaseGrantResponse, error)
	// LeaseRevoke sends LeaseRevoke request to raft and toApply it after committed.
	LeaseRevoke(ctx context.Context, r *pb.LeaseRevokeRequest) (*pb.LeaseRevokeResponse, error)
	// LeaseRenew renews the lease with given ID. The renewed TTL is returned.
	LeaseRenew(ctx context.Context, id lease.LeaseID) (int64, error)
	// LeaseTimeToLive retrieves lease information.
	LeaseTimeToLive(ctx context.Context, r *pb.LeaseTimeToLiveRequest) (*pb.LeaseTimeToLiveResponse, error)
	// LeaseLeases lists all leases.
	LeaseLeases(ctx context.Context, r *pb.LeaseLeasesRequest) (*pb.LeaseLeasesResponse, error)
}

type LeaseServer struct {
	lg  *zap.Logger
	hdr header
	le  etcdserver.Lessor
	pb.UnsafeLeaseServer
}
```

`LeaseKeepAlive` 没有单独的 EtcdServer 方法：它是 gRPC 双向流，循环调用 `LeaseServer.leaseKeepAlive` → `s.le.LeaseRenew`。另外 `LeaseGrant` 在接入层也被 `quotaLeaseServer` 装饰，先过配额检查，见 [request](/docs/CS/Framework/etcd/request.md)。

## Grant, Attach and Renew

`Grant` 检查 ID 与 TTL 上限，把 TTL 钳到 `minLeaseTTL`，写入内存 map 与 bbolt 的 `lease` bucket，并在 primary lessor 上注册到过期堆：

```go
const NoLease = LeaseID(0)

// MaxLeaseTTL is the maximum lease TTL value
const MaxLeaseTTL = 9000000000

func (le *lessor) Grant(id LeaseID, ttl int64) (*Lease, error) {
	if id == NoLease {
		return nil, ErrLeaseNotFound
	}

	if ttl > MaxLeaseTTL {
		return nil, ErrLeaseTTLTooLarge
	}

	// TODO: when lessor is under high load, it should give out lease
	// with longer TTL to reduce renew load.
	l := NewLease(id, ttl)

	le.mu.Lock()
	defer le.mu.Unlock()

	if _, ok := le.leaseMap[id]; ok {
		return nil, ErrLeaseExists
	}

	if l.ttl < le.minLeaseTTL {
		l.ttl = le.minLeaseTTL
	}

	if le.isPrimary() {
		l.refresh(0)
	} else {
		l.forever()
	}

	le.leaseMap[id] = l
	l.persistTo(le.b)
	// ... 省略 metrics 与注册到过期堆 ...
	return l, nil
}
```

`minLeaseTTL` 来自 `ServerConfig` 的构造：

```go
	minTTL := time.Duration((3*cfg.ElectionTicks)/2) * heartbeat

	// always recover lessor before kv. When we recover the mvcc.KV it will reattach keys to its leases.
	// If we recover mvcc.KV first, it will attach the keys to the wrong lessor before it recovers.
	srv.lessor = lease.NewLessor(srv.Logger(), srv.be, srv.cluster, lease.LessorConfig{
		MinLeaseTTL:                int64(math.Ceil(minTTL.Seconds())),
		CheckpointInterval:         cfg.LeaseCheckpointInterval,
		CheckpointPersist:          cfg.ServerFeatureGate.Enabled(features.LeaseCheckpointPersist),
		ExpiredLeasesRetryInterval: srv.Cfg.ReqTimeout(),
	})
```

attach 发生在写事务里（`storeTxnWrite.put` 在 lease 变化时调 `Detach` / `Attach`），`lessor.Attach` 把 `LeaseItem` 同时记进 lease 自己的 `itemSet` 和全局 `itemMap`：

```go
func (le *lessor) Attach(id LeaseID, items []LeaseItem) error {
	le.mu.Lock()
	defer le.mu.Unlock()

	l := le.leaseMap[id]
	if l == nil {
		return ErrLeaseNotFound
	}

	l.mu.Lock()
	for _, it := range items {
		l.itemSet[it] = struct{}{}
		le.itemMap[it] = id
	}
	l.mu.Unlock()
	return nil
}
```

3.7 的 `FastLeaseKeepAlive`（beta，默认开启）让续期跳过等待 applied index——只有当 lease 在内存里查不到时才等，避免「正在创建中的 lease」被误判为不存在：

```go
		// This change aims to make lease renewal faster under high server load
		// while preserving correctness. If a lease is not found, it might still be in
		// the process of being created. We must wait for the applied index to advance
		// to verify whether the lease truly does not exist.
		if s.FeatureEnabled(features.FastLeaseKeepAlive) {
			le := s.lessor.Lookup(id)
			if le == nil {
				if err := s.waitAppliedIndex(); err != nil {
					return 0, err
				}
			}
		} else {
			if err := s.waitAppliedIndex(); err != nil {
				return 0, err
			}
		}

		if err := s.checkLeaseRenew(ctx, id); err != nil {
			return 0, err
		}

		ttl, err := s.lessor.Renew(id)
```

## Expiration: Min-Heap and Run Loop

早期实现是 O(N) 遍历全部 lease；现在用最小堆：`LeaseQueue` 按过期时间排序，`LeaseExpiredNotifier` 用 map + heap 保证一个 lease 只有一个条目，`RegisterOrUpdate` 时 `heap.Fix` 更新：

```go
type LeaseWithTime struct {
	id    LeaseID
	time  time.Time
	index int
}

type LeaseQueue []*LeaseWithTime

func (pq LeaseQueue) Len() int { return len(pq) }

func (pq LeaseQueue) Less(i, j int) bool {
	return pq[i].time.Before(pq[j].time)
}

// LeaseExpiredNotifier is a queue used to notify lessor to revoke expired lease.
// Only save one item for a lease, `Register` will update time of the corresponding lease.
type LeaseExpiredNotifier struct {
	m     map[LeaseID]*LeaseWithTime
	queue LeaseQueue
}

func (mq *LeaseExpiredNotifier) RegisterOrUpdate(item *LeaseWithTime) {
	if old, ok := mq.m[item.id]; ok {
		old.time = item.time
		heap.Fix(&mq.queue, old.index)
	} else {
		heap.Push(&mq.queue, item)
		mq.m[item.id] = item
	}
}
```

主循环每 500ms 依次做淘汰检查与 checkpoint 检查；淘汰只在 primary lessor 上进行，并做了速率限制（每轮最多 `leaseRevokeRate / 2`）：

```go
func (le *lessor) runLoop() {
	defer close(le.doneC)

	delayTicker := time.NewTicker(500 * time.Millisecond)
	defer delayTicker.Stop()

	for {
		le.revokeExpiredLeases()
		le.checkpointScheduledLeases()

		select {
		case <-delayTicker.C:
		case <-le.stopC:
			return
		}
	}
}

func (le *lessor) revokeExpiredLeases() {
	var ls []*Lease

	// rate limit
	revokeLimit := le.leaseRevokeRate / 2

	le.mu.RLock()
	if le.isPrimary() {
		ls = le.findExpiredLeases(revokeLimit)
	}
	le.mu.RUnlock()

	if len(ls) != 0 {
		select {
		case <-le.stopC:
			return
		case le.expiredC <- ls:
		default:
			// the receiver of expiredC is probably busy handling
			// other stuff
			// let's try this next time after 500ms
		}
	}
}
```

`expireExists` 是 O(1) 查堆顶：堆顶未过期就结束本轮；过期则把条目时间推到 `expiredLeaseRetryInterval`（3s）之后重新入堆，等 `EtcdServer.run()` 从 `ExpiredLeasesC()` 收到列表后走 `Revoke`（其中 key 会**排序后再删**，保证各成员 backend hash 一致）。

## Leader Transition: Promote and Demote

`Promote(extend)` 刷新所有 lease 的到期时间、重新注册进过期堆并按需调度 checkpoint；如果 lease 数量多到可能在 1 秒内堆积，还会按 `leaseRevokeRate` 把到期时间错开。`Demote()` 则把所有 lease 设为 `forever()`，清空 checkpoint / 过期堆：

```go
func (le *lessor) Promote(extend time.Duration) {
	le.mu.Lock()
	defer le.mu.Unlock()

	le.demotec = make(chan struct{})

	// refresh the expiries of all leases.
	for _, l := range le.leaseMap {
		l.refresh(extend)
		item := &LeaseWithTime{id: l.ID, time: l.expiry}
		le.leaseExpiredNotifier.RegisterOrUpdate(item)
		le.scheduleCheckpointIfNeeded(l)
	}
	// ... 省略 lease 堆积时的到期时间错峰逻辑 ...
}

func (le *lessor) Demote() {
	le.mu.Lock()
	defer le.mu.Unlock()

	// set the expiries of all leases to forever
	for _, l := range le.leaseMap {
		l.forever()
	}

	le.clearScheduledLeasesCheckpoints()
	le.clearLeaseExpiredNotifier()

	if le.demotec != nil {
		close(le.demotec)
		le.demotec = nil
	}
}
```

调用点不在 `raftReadyHandler.updateLeadership`（那里只调 `Demote` / `compactor.Pause` / `Resume`），而是 apply 空 entry 时：

```go
	// raft state machine may generate noop entry when leader confirmation.
	// skip it in advance to avoid some potential bug in the future
	if len(e.Data) == 0 {
		s.firstCommitInTerm.Notify()

		// promote lessor when the local member is leader and finished
		// applying all entries from the last term.
		if s.isLeader() {
			s.lessor.Promote(s.Cfg.ElectionTimeout())
		}
		return
	}
```

这个 noop 同时触发 [read](/docs/CS/Framework/etcd/read.md) 的 `FirstCommitInTermNotify`——新 leader 在本 term 首次提交前既不能答线性读，也不能真正接管 lease。

## Checkpoint and Feature Gates

checkpoint 的作用是：leader 定期把 lease 剩余 TTL 经 Raft 同步给 follower，避免 leader 切换时「所有 lease 自动续期」导致长 TTL lease 永不过期、key 堆积。3.7.4 的 gate 默认值如下：

| gate | 默认 | 级别 | 作用 |
| :--- | :--- | :--- | :--- |
| `LeaseCheckpoint` | false | alpha | leader 定期把剩余 TTL checkpoint 给 follower |
| `LeaseCheckpointPersist` | false | alpha | 把 checkpoint 持久化到 v3 存储；单独开启会在 `Validate()` 报错 |
| `FastLeaseKeepAlive` | **true** | beta | 续期跳过等待 applied index（仅 lease 不在内存时才等） |
| `PriorityRequest` | false | alpha | `LeaseRevoke` 在过载时获得更高 apply 优先级（见 [request](/docs/CS/Framework/etcd/request.md) 的 `maxPriorityGap`） |

`checkpointScheduledLeases` 由主循环调用，受 `leaseCheckpointRate / 2` 与 `maxLeaseCheckpointBatchSize` 双重限制：

```go
func (le *lessor) checkpointScheduledLeases() {
	// rate limit
	for i := 0; i < leaseCheckpointRate/2; i++ {
		var cps []*pb.LeaseCheckpoint

		le.mu.Lock()
		if le.isPrimary() {
			cps = le.findDueScheduledCheckpoints(maxLeaseCheckpointBatchSize)
		}
		le.mu.Unlock()

		if len(cps) != 0 {
			if err := le.cp(context.Background(), &pb.LeaseCheckpointRequest{Checkpoints: cps}); err != nil {
				return
			}
		}
		if len(cps) < maxLeaseCheckpointBatchSize {
			return
		}
	}
}
```

> [!WARNING]
> checkpoint 开关是 `--feature-gates=LeaseCheckpoint=true` 这样的 **feature gate**，不是 embed 配置项；`LeaseCheckpointPersist` 依赖 `LeaseCheckpoint`，单独开会被启动校验拒绝。默认间隔 `defaultLeaseCheckpointInterval = 5 * time.Minute`。

## Client Read-Only APIs

客户端 `client/v3/lease.go` 的 `Lease` 接口提供一组只读查询，它们不改状态、不改 TTL：

```go
type Lease interface {
	// Grant creates a new lease.
	Grant(ctx context.Context, ttl int64) (*LeaseGrantResponse, error)
	// Revoke revokes the given lease.
	Revoke(ctx context.Context, id LeaseID) (*LeaseRevokeResponse, error)
	// TimeToLive retrieves the lease information of the given lease ID.
	TimeToLive(ctx context.Context, id LeaseID, opts ...LeaseOption) (*LeaseTimeToLiveResponse, error)
	// Leases retrieves all leases.
	Leases(ctx context.Context) (*LeaseLeasesResponse, error)
	// KeepAlive attempts to keep the given lease alive forever.
	KeepAlive(ctx context.Context, id LeaseID) (<-chan *LeaseKeepAliveResponse, error)
	// KeepAliveOnce renews the lease once.
	KeepAliveOnce(ctx context.Context, id LeaseID) (*LeaseKeepAliveResponse, error)
}
```

- `TimeToLive` 返回剩余 TTL、初始 TTL，带 `WithAttachedKeys()` 才填充 `Keys`（etcdctl 的 `--keys`）；**返回 -1 表示已过期**，不要拿去做算术。
- `Leases` 列出集群所有 lease ID，对应 `etcdctl lease list`。
- `KeepAliveOnce` 只续期一次，即使 `KeepAlive` 流因 `ErrKeepAliveHalted` 中断也能正常工作。
- 在 [naming](/docs/CS/Framework/etcd/naming.md) 里 endpoint 通过 `WithLease(leaseID)` 绑定租约：实例挂了不再续期，endpoint 自动消失，消费方 Watch 到 Delete 摘掉实例——lease 同时充当健康检查。

## Common Pitfalls

- `LeaseTimeToLive` / `LeaseKeepAlive` 不在 `server/lease.Lessor` 接口里；它们在 `etcdserver.Lessor` 与 gRPC 接入层，按层找接口才不会扑空。
- `EnableLeaseCheckpoint` 这个配置项在 3.7.4 不存在；`LeaseCheckpointPersist` 不能单独开。
- 别把 `minLeaseTTL` 当常量：它是结构体字段，由 `ElectionTicks` / `heartbeat` 动态算出，调小选举超时会同步降低最小 TTL。
- 只有导出常量 `MaxLeaseTTL`，没有小写 `maxLeaseTTL`；TTL 超限在 `Grant` 报 `ErrLeaseTTLTooLarge`，过短则静默钳制。
- lease 活着 ≠ key 活着：lease 只保证「不删你的 key」，不保证 key 存在，`Put` 失败或 `Delete` 都不会被 lease 拦截。
- `FastLeaseKeepAlive` 默认开启会改变续期延迟基线，跨版本对比 keepalive 性能时要留意。

## Links

- [etcd（总览与架构）](/docs/CS/Framework/etcd/etcd.md)
- [MVCC（Put 时的 Attach / Detach）](/docs/CS/Framework/etcd/MVCC.md)
- [compare（与 ZooKeeper 临时节点的对应）](/docs/CS/Framework/etcd/compare.md)
- [concurrency（分布式锁依赖 Session 租约）](/docs/CS/Framework/etcd/concurrency.md)
- [features（feature gate 机制）](/docs/CS/Framework/etcd/features.md)

## References

1. [etcd v3.7.4 源码（server/lease/lessor.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/lease/lessor.go)
2. [etcd v3.7.4 源码（server/lease/lease_queue.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/lease/lease_queue.go)
3. [etcd v3.7.4 源码（server/features/etcd_features.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/features/etcd_features.go)
4. [etcd v3.7.4 源码（server/etcdserver/v3_server.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/v3_server.go)
5. [etcd v3.7.4 源码（server/etcdserver/api/v3rpc/lease.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/api/v3rpc/lease.go)
6. [etcd v3.7.4 源码（client/v3/lease.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/client/v3/lease.go)
