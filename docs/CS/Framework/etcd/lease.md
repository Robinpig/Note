# Lease: TTL and Expiration

## Introduction

Lease 是 client 与 etcd server 之间的 TTL 契约：key 挂到某个 lease 上，只要 lease 在有效期内就不被删除；client 靠 `KeepAlive` 续期，server 由 leader 负责淘汰过期 lease 并删除其关联 key。生命周期的主角是 `server/lease` 的 `Lessor`、最小堆与 500ms 主循环。

etcd 创建 Lessor 时会启动一个常驻 `runLoop` goroutine。它每 500ms 依次执行 `revokeExpiredLeases()` 与 `checkpointScheduledLeases()`：前者检查并投递过期 Lease，后者按 checkpoint 队列更新剩余 TTL。两者不是两个独立 goroutine。
> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下片段均取自该 tag。

四个从源码核验出来的反直觉点：

- **有两个同名 `Lessor` 接口**：`server/lease.Lessor` 是**进程内**能力（`Grant` / `Revoke` / `Attach` / `Renew` / `Promote` / `Demote` / `Lookup` 等）；`etcdserver.Lessor`（定义在 `v3_server.go`）才包含 `LeaseGrant` / `LeaseRevoke` / `LeaseRenew` / `LeaseTimeToLive` / `LeaseLeases` 这些 RPC 级方法。常见错误是拿客户端 API 去 `server/lease/lessor.go` 里找。
- **`Promote` 不在 leadership 回调里调**：它在 apply 到 leader 的 **noop entry** 时执行（`s.firstCommitInTerm.Notify()` 就在同一处），寓意是「apply 完上个 term 的所有 entry 后，新 leader 才真正接管 lease」。
- **TTL 会被静默钳制**：`MaxLeaseTTL` 是导出常量 `9000000000`；`minLeaseTTL` 不是常量而是 `lessor` 的字段，由 `ceil(1.5 × ElectionTicks × heartbeat)` 算出，申请 1 秒 TTL 实际拿到的可能更长且不报错。
- **注释描述的是计划不是现状**：`LeaseCheckpointPersist` 的注释写着「v3.6 起默认启用、v3.7 移除」，但 3.7.4 里它既没移除也不是默认启用——仍是 alpha + 默认 false。判断实际行为只能读 feature gate 的默认值代码。

> [!WARNING]
> **归类更正**：客户端 API、`EtcdServer` 方法与 `Lessor` 接口是三层，不能混着读。`Lessor` 接口（`server/lease/lessor.go`）包含 `Grant` / `Revoke` / `Renew` / `Lookup` / `Attach` / `Detach` / `Checkpoint` / `Promote` / `Demote` 等**进程内**操作；gRPC 接入层 `LeaseServer`（`server/etcdserver/api/v3rpc/lease.go`）暴露 `LeaseGrant` / `LeaseRevoke` / `LeaseTimeToLive` / `LeaseLeases` / `LeaseKeepAlive`，其中 `LeaseKeepAlive` 是流方法。单次续期在流处理中调用 `EtcdServer.LeaseRenew`，其余非流请求由 `EtcdServer` 的同名方法处理（`server/etcdserver/v3_server.go`）。

## Version Baseline

| 项 | 值 |
| :--- | :--- |
| 源码基线 | **3.7.2** |
| `MaxLeaseTTL`（最大 TTL） | `9000000000` 秒（`server/lease/lessor.go`，**导出常量**） |
| `minLeaseTTL`（最小 TTL） | **不是常量**，是 `lessor` 结构体字段；运行时按 `ceil(1.5 × ElectionTicks × heartbeat)` 计算 |
| checkpoint 默认间隔 | `defaultLeaseCheckpointInterval = 5 * time.Minute` |
| 淘汰主循环周期 | 500ms |
| 3.7 新增 gate | `FastLeaseKeepAlive`（beta，**默认开启**）、`PriorityRequest`（alpha，默认关） |

> [!NOTE]
> `LeaseCheckpoint` 与 `LeaseCheckpointPersist` 在 3.7.2 **都是 alpha 且默认 false**（`server/features/etcd_features.go`）。网上「3.5 起 checkpoint 默认开启」的说法对应的是 3.5 时代的 `--experimental-enable-lease-checkpoint`，3.6 起已改为 feature gate、3.7.2 里并未默认打开——判断「当前实际行为」要看 gate 的默认值代码，不是看功能是否存在。

```shell

# 创建一个TTL为600秒的lease，etcd server返回LeaseID 
$ etcdctl lease grant 600
 # 查看lease的TTL、剩余时间 
$ etcdctl lease timetolive 326975935f48f814

```
当 Lease server 收到 client 创建一个有效期 600 秒的 Lease 请求后，请求经 Raft 同步，再由 Apply 模块调用 `Lessor.Grant`。`Grant` 创建 `Lease`、按需把 TTL 钳制到 `minLeaseTTL`，将其插入 `leaseMap` 并持久化到 boltdb 的 Lease bucket，最后返回 LeaseID 给 client。

KV 模块的 API 接口提供了一个"--lease"参数，你可以通过如下命令，将 key node 关联到对应的 LeaseID 上。然后你查询的时候增加 -w 参数输出格式为 json，就可查看到 key 关联的 LeaseID
通过 put 等命令新增一个指定了 "--lease" 的 key 时，MVCC 模块它会通过 Lessor 模块的 Attach 方法，将 key 关联到 Lease 的 key 内存集合 ItemSet 中。

### renew

为了防止 Lease 被淘汰，你需要定期发送 LeaseKeepAlive 请求给 etcd server 续期 Lease，本质是更新 Lease 的到期时间。客户端侧对应 [lease.go](https://pkg.go.dev/go.etcd.io/etcd/client/v3) 里的 `KeepAlive`（常驻流）与 `KeepAliveOnce`（单次）。

## expire

过期 Lease 的发现由 Lessor 的 `runLoop` 负责：它从最小堆检查过期项，把批次发送到 `expiredC`；server 侧再通过 Raft 发起撤销，而不是由 `runLoop` 直接删除 backend 中的 key。

目前etcd是基于最小堆来管理Lease，实现快速淘汰过期的Lease。
etcd早期的时候，淘汰Lease非常暴力。etcd会直接遍历所有Lease，逐个检查Lease是否过期，过期则从Lease关联的key集合中，取出key列表，删除它们，时间复杂度是O(N)。
然而这种方案随着Lease数增大，毫无疑问它的性能会变得越来越差。我们能否按过期时间排序呢？这样每次只需轮询、检查排在前面的Lease过期时间，一旦轮询到未过期的Lease， 则可结束本轮检查。
刚刚说的就是etcd Lease高效淘汰方案最小堆的实现方法。每次新增Lease、续期的时候，它会插入、更新一个对象到最小堆中，对象含有LeaseID和其到期时间unixnano，对象之间按到期时间升序排序。
etcd Lessor 主循环每隔 500ms 执行一次撤销 Lease 检查（`revokeExpiredLeases`），每次轮询堆顶的元素，若已过期则加入到待淘汰列表，直到堆顶的 Lease 过期时间大于当前，则结束本轮轮询。
相比早期 O(N) 的遍历时间复杂度，使用堆后，插入、更新、删除，它的时间复杂度是 O(Log N)，查询堆顶对象是否过期时间复杂度仅为 O(1)，性能大大提升，可支撑大规模场景下 Lease 的高效淘汰

上面这套描述对应 3.7.2 的 `runLoop`：`delayTicker := time.NewTicker(500 * time.Millisecond)`，每轮依次调 `revokeExpiredLeases()` 与 `checkpointScheduledLeases()`。最小堆由 `LeaseQueue` 实现（`server/lease/lease_queue.go`）。

检查 Lease 是否过期、维护最小堆、针对过期的 Lease 发起 revoke 操作，都是 Leader 节点负责的，它类似于 Lease 的仲裁者，通过以上清晰的权责划分，降低了 Lease 特性的实现复杂度。
那么当 Leader 因重启、crash、磁盘 IO 等异常不可用时，Follower 节点就会发起 Leader 选举，新 Leader 要完成以上职责，必须重建 Lease 过期最小堆等管理数据结构

当你的集群发生 Leader 切换后，新的 Leader 基于 Lease map 信息，按 Lease 过期时间构建一个最小堆时，etcd 早期版本为了优化性能，并未持久化存储 Lease 剩余 TTL 信息，因此重建的时候就会自动给所有 Lease 自动续期了。
然而若较频繁出现 Leader 切换，切换时间小于 Lease 的 TTL，这会导致 Lease 永远无法删除，大量 key 堆积，db 大小超过配额等异常
为了解决这个问题，etcd 引入了检查点机制，也就是 CheckPointScheduledLeases 任务
一方面，etcd 启动的时候，Leader 节点后台会运行此异步任务，定期批量地将 Lease 剩余的 TTL 基于 Raft Log 同步给 Follower 节点，Follower 节点收到 CheckPoint 请求后，更新内存数据结构 LeaseMap 的剩余 TTL 信息。
另一方面，当 Leader 节点收到 KeepAlive 请求的时候，它也会通过 checkpoint 机制把此 Lease 的剩余 TTL 重置，并同步给 Follower 节点，尽量确保续期后集群各个节点的 Lease 剩余 TTL 一致性

> [!NOTE]
> 3.7.2 把这套「leader 切换时怎么处置 lease」的历史逻辑显式化成了 `Lessor` 接口的两个方法：`Promote(extend time.Duration)`（成为 leader 时调用，`Promote` 会 refresh 所有 lease 到期并按需调度 checkpoint）与 `Demote()`（失去 leader 时调用）。调用点在 `server/etcdserver/server.go`——成为 leader 时 `Promote(s.Cfg.ElectionTimeout())`，失去 leader 时 `Demote()`。读 3.7 源码时不用再从 `runLoop` 里猜这段逻辑藏在哪。

## Lease Read-Only Query and Management

前面讲的是服务端生命周期（Grant / Revoke / KeepAlive / Checkpoint）。客户端还有一组**只读**查询 API——它们不修改任何状态、不改 TTL，只是读取 lease 的当前视图，统称 read-only lease 操作。这些方法定义在 `client/v3/lease.go` 的 `Lease` 接口上。

### TimeToLive and Associated Keys

`Lease.TimeToLive(ctx, id, opts...)` 返回一个 lease 的剩余 TTL、初始 TTL，以及（可选）挂在该 lease 下的所有 key：

```go
resp, _ := cli.TimeToLive(ctx, leaseID, clientv3.WithAttachedKeys())
// resp.TTL        剩余秒数（已过期返回 -1）
// resp.GrantedTTL Grant 时确定的 TTL（Renew 不修改它）
// resp.Keys       [][]byte，带上 WithAttachedKeys 才填充
```

`WithAttachedKeys()` 对应 `LeaseTimeToLiveRequest.keys` 字段——etcdctl 里就是 `etcdctl lease timetolive <id> --keys`。这正是排查“哪个 lease 还挂着 key”的最快手段，[troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md) 的 NOSPACE 排查常需要定位大 key 归属的 lease。
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

两个 gate 有**互斥依赖**：`LeaseCheckpointPersist` 单独开启时 `Validate()` 直接返回错误 `enabling feature gate LeaseCheckpointPersist requires enabling feature gate LeaseCheckpoint`；反过来只开 `LeaseCheckpoint` 不开 Persist 只会打一条 Warn（`server/embed/config.go`）。

`LeaseCheckpointPersist` 的价值在于：持久化后 leader 切换能从 checkpoint 恢复剩余 TTL，避免上文「切换即全续期」导致长 TTL 的 lease 永不过期、key 堆积的问题。

checkpoint 间隔由 `LeaseCheckpointInterval` 配置，默认 `defaultLeaseCheckpointInterval = 5 * time.Minute`。

> [!NOTE]
> 一条容易踩的版本陷阱：`LeaseCheckpointPersist` 的源码注释写着「v3.6 起默认启用，将在 v3.7 移除」，但 3.7.2 里它**既没被移除、也没默认启用**，仍是 alpha + 默认 false。注释描述的是计划不是现状，判断实际行为只能读默认值代码。

### 3.7 Renewal Path Changes

3.7 新增的两个 feature gate 直接改写了 `LeaseRenew` 的行为：

| gate | 默认 | 级别 | 作用 |
| :--- | :--- | :--- | :--- |
| `FastLeaseKeepAlive` | **true** | beta | 续期**跳过等待 applied index**（仅当 lease 在内存中不存在时才等），高负载下更快 |
| `PriorityRequest` | false | alpha | 让 `LeaseRevoke` 等请求在过载时获得更高 apply 优先级 |

`FastLeaseKeepAlive` 默认开启意味着 3.7 的续期延迟比 3.5/3.6 更低——做 lease 相关压测时这条差异会影响观测结果。

### Cooperation with naming

[naming（服务发现）](/docs/CS/Framework/etcd/naming.md) 里 endpoint 注册可以 `clientv3.WithLease(leaseID)`——把业务实例地址挂到一个 lease 上。实例进程挂了、lease 不再续期，endpoint 自动从 etcd 消失，消费方 Watch 到 Delete 摘掉实例。这里 lease 同时充当了「服务健康检查」：lease 活着 = 实例活着。

## Pitfall List

> [!WARNING]
> checkpoint 开关是 `--feature-gates=LeaseCheckpoint=true` 这样的 **feature gate**，不是 embed 配置项；`LeaseCheckpointPersist` 依赖 `LeaseCheckpoint`，单独开会被启动校验拒绝。默认间隔 `defaultLeaseCheckpointInterval = 5 * time.Minute`。

1. **`LeaseKeepAlive` 不是 `EtcdServer` 方法，也不是 `Lessor` 接口方法** —— 它是 gRPC `LeaseServer` 的流方法；流内单次续期调用 `EtcdServer.LeaseRenew`，最终落到 `Lessor.Renew`。`LeaseTimeToLive` / `LeaseLeases` / `LeaseGrant` / `LeaseRevoke` 才由 `EtcdServer` 提供非流入口。
2. **`EnableLeaseCheckpoint` 这个配置项在 3.7.2 里不存在** —— 3.6 起改成 feature gate `LeaseCheckpoint`，且**默认 false**。「3.5 起默认开启」不适用于 3.7。
3. **`LeaseCheckpointPersist` 不能单独开** —— 只开它不加 `LeaseCheckpoint`，`Validate()` 会直接返回错误拒绝启动。
4. **「gate 存在」不等于「gate 生效」** —— 判断当前集群实际行为要看默认值代码。`LeaseCheckpointPersist` 的注释说「v3.6 起默认启用、v3.7 移除」，而 3.7.2 里它**没被移除也未默认启用**。
5. **别把 `minLeaseTTL` 当常量** —— 它是 `lessor` 结构体字段，值由 `minTTL := time.Duration((3*ElectionTicks)/2) * heartbeat` 动态计算后注入。所以**调小 `--election-timeout` 或 `--heartbeat-interval` 会同步降低最小 TTL**，短 TTL 需求不是调这个能解决的。
6. **小写 `maxLeaseTTL` 不存在** —— 只有导出常量 `MaxLeaseTTL = 9000000000`。超过它在 `Grant` 时报 `ErrLeaseTTLTooLarge`。
7. **TTL 会被静默钳制** —— `Grant` 里 `if l.ttl < le.minLeaseTTL { l.ttl = le.minLeaseTTL }`。申请 1 秒 TTL 实际拿到的是最小 TTL，接口不报错。
8. **`TimeToLive` 返回的 TTL 为 -1 表示已过期** —— 不是「还剩负数秒」，别拿去做算术。
9. **lease 活着 ≠ key 活着** —— lease 只保证「不删你的 key」，不保证 key 存在。`Put` 失败、`Delete` 都不会因为有 lease 而被拦截。
10. **`FastLeaseKeepAlive` 默认开启会改变压测基线** —— 3.7 的续期延迟天然低于 3.5/3.6，跨版本对比 keepalive 性能时要留意。

## Links

- [Core_Mechanisms（lease revoke 与 checkpoint 的 Raft 路径）](/docs/CS/Framework/etcd/Core_Mechanisms.md)
- [etcd](/docs/CS/Framework/etcd/etcd.md)
- [compare（与 ZooKeeper 临时节点的对应）](/docs/CS/Framework/etcd/compare.md)
- [concurrency（分布式锁 / 选主依赖 Session 租约）](/docs/CS/Framework/etcd/concurrency.md)

## References

1. [etcd source - server/lease/lessor.go（Lessor 接口、主循环、TTL 常量）](https://github.com/etcd-io/etcd/blob/v3.7.2/server/lease/lessor.go)
2. [etcd source - server/features/etcd_features.go（LeaseCheckpoint / FastLeaseKeepAlive 等 gate 默认值）](https://github.com/etcd-io/etcd/blob/v3.7.2/server/features/etcd_features.go)
3. [etcd source - server/etcdserver/v3_server.go（Lease* 的 gRPC 入口实现）](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/v3_server.go)
4. [etcd API](https://etcd.io/docs/v3.7/learning/api/)
5. [etcd source - client/v3/lease.go（客户端 Lease 接口）](https://github.com/etcd-io/etcd/blob/v3.7.2/client/v3/lease.go)
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
