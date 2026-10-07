## Introduction

Lease 顾名思义，client 和 etcd server 之间存在一个约定，内容是 etcd server 保证在约定的有效期内（TTL），不会删除你关联到此 Lease 上的 key-value。

etcd 在启动的时候，创建 Lessor 模块的时候，它会启动两个常驻 goroutine，一个是 RevokeExpiredLease 任务，定时检查是否有过期 Lease，发起撤销过期的 Lease 操作。一个是 CheckpointScheduledLease，定时触发更新 Lease 的剩余到期时间的操作。

客户端能感知的四个 API 作用如下：

- Grant 表示创建一个 TTL 为你指定秒数的 Lease，Lessor 会将 Lease 信息持久化存储在 boltdb 中；
- Revoke 表示撤销 Lease 并删除其关联的数据；
- LeaseTimeToLive 表示获取一个 Lease 的有效期、剩余时间；
- LeaseKeepAlive 表示为 Lease 续期。

> [!WARNING]
> **归类更正**：上面后两个 API **不在 `Lessor` 接口里**。`Lessor` 接口（`server/lease/lessor.go`）只暴露 `Lookup`（查内存里的 `*Lease`）与 `Renew`（返回剩余 TTL）这类**进程内**操作；`LeaseTimeToLive` / `LeaseLeases` / `LeaseKeepAlive` / `LeaseGrant` / `LeaseRevoke` 都是 **`EtcdServer` 层**的方法（`server/etcdserver/v3_server.go`），gRPC 接入层在 `server/etcdserver/api/v3rpc/lease.go`。把「客户端 API」当成「Lessor 接口方法」去读源码会找不到。

## Version Baseline

| 项 | 值 |
| :--- | :--- |
| 最新稳定版 | **3.7.2** |
| 维护分支 | 3.6.15 / 3.5.34 |
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
当 Lease server 收到 client 的创建一个有效期 600 秒的 Lease 请求后，会通过 Raft 模块完成日志同步，随后 Apply 模块通过 Lessor 模块的 Grant 接口执行日志条目内容。
首先 Lessor 的 Grant 接口会把 Lease 保存到内存的 ItemMap 数据结构中，然后它需要持久化 Lease，将 Lease 数据保存到 boltdb 的 Lease bucket 中，返回一个唯一的 LeaseID 给 client。
通过这样一个流程，就基本完成了 Lease 的创建

KV 模块的 API 接口提供了一个"--lease"参数，你可以通过如下命令，将 key node 关联到对应的 LeaseID 上。然后你查询的时候增加 -w 参数输出格式为 json，就可查看到 key 关联的 LeaseID
通过 put 等命令新增一个指定了 "--lease" 的 key 时，MVCC 模块它会通过 Lessor 模块的 Attach 方法，将 key 关联到 Lease 的 key 内存集合 ItemSet 中。

### renew

为了防止 Lease 被淘汰，你需要定期发送 LeaseKeepAlive 请求给 etcd server 续期 Lease，本质是更新 Lease 的到期时间。客户端侧对应 [lease.go](https://pkg.go.dev/go.etcd.io/etcd/client/v3) 里的 `KeepAlive`（常驻流）与 `KeepAliveOnce`（单次）。

## expire

淘汰过期Lease的工作由Lessor模块的一个异步goroutine负责 它会定时从最小堆中取出已过期的Lease，执行删除Lease和其关联的key列表数据的RevokeExpiredLease任务

目前etcd是基于最小堆来管理Lease，实现快速淘汰过期的Lease。
etcd早期的时候，淘汰Lease非常暴力。etcd会直接遍历所有Lease，逐个检查Lease是否过期，过期则从Lease关联的key集合中，取出key列表，删除它们，时间复杂度是O(N)。
然而这种方案随着Lease数增大，毫无疑问它的性能会变得越来越差。我们能否按过期时间排序呢？这样每次只需轮询、检查排在前面的Lease过期时间，一旦轮询到未过期的Lease， 则可结束本轮检查。
刚刚说的就是etcd Lease高效淘汰方案最小堆的实现方法。每次新增Lease、续期的时候，它会插入、更新一个对象到最小堆中，对象含有LeaseID和其到期时间unixnano，对象之间按到期时间升序排序。
etcd Lessor 主循环每隔 500ms 执行一次撤销 Lease 检查（RevokeExpiredLease），每次轮询堆顶的元素，若已过期则加入到待淘汰列表，直到堆顶的 Lease 过期时间大于当前，则结束本轮轮询。
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
// resp.GrantedTTL 创建/续期时的初始 TTL
// resp.Keys       [][]byte，带上 WithAttachedKeys 才填充
```

`WithAttachedKeys()` 对应 `LeaseTimeToLiveRequest.keys` 字段——etcdctl 里就是 `etcdctl lease timetolive <id> --keys`。这正是排查「哪个 lease 还挂着 key」的最快手段，[troubleshooting.md](/docs/CS/Framework/etcd/troubleshooting.md) 的 NOSPACE 排查常需要定位大 key 归属的 lease。

### List All Leases

`Lease.Leases(ctx)` 返回集群里所有 lease 的 ID（不含 key 明细），用于巡检「有多少租约还活着」「哪个快到期」。etcdctl 对应 `etcdctl lease list`。

### KeepAliveOnce

`Lease.KeepAliveOnce(ctx, id)` 只续期一次（不像 `KeepAlive` 起常驻流）。适用于「临时延长一下、但不想维护 keepalive 流」的场景；官方注释特意说明：即使 `KeepAlive` 的流因意外中断（`ErrKeepAliveHalted`），`KeepAliveOnce` 仍能正常工作。

### Checkpoint Configuration (Control Plane)

> [!WARNING]
> checkpoint 的开关**不是** embed 启动配置，而是 3.6 起引入的 **feature gate**，通过 `--feature-gates` 传入。3.7.2 里两个 gate **都是 alpha 且默认 false**：

| gate | 默认 | 级别 | 作用 |
| :--- | :--- | :--- | :--- |
| `LeaseCheckpoint` | **false** | alpha | 是否开启 leader 定期把 lease 剩余 TTL checkpoint 给 follower |
| `LeaseCheckpointPersist` | **false** | alpha | 是否把 checkpoint 持久化到 v3 存储 |

开启方式（注意是 gate 名，不是 flag 名）：

```shell
# 开启 checkpoint（不含持久化）
$ etcd --feature-gates=LeaseCheckpoint=true

# 开启并持久化（Persist 依赖 Checkpoint，单独开会在启动时报错）
$ etcd --feature-gates=LeaseCheckpoint=true,LeaseCheckpointPersist=true
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

[naming.md](/docs/CS/Framework/etcd/naming.md) 里 endpoint 注册可以 `clientv3.WithLease(leaseID)`——把业务实例地址挂到一个 lease 上。实例进程挂了、lease 不再续期，endpoint 自动从 etcd 消失，消费方 Watch 到 Delete 摘掉实例。这里 lease 同时充当了「服务健康检查」：lease 活着 = 实例活着。

## Pitfall List

> [!WARNING]
> 逐条对照 3.7.2 源码核实，都是「照旧文档写会出错」的点：

1. **`LeaseTimeToLive` / `LeaseKeepAlive` 不在 `Lessor` 接口里** —— 它们是 `EtcdServer` 的方法（`server/etcdserver/v3_server.go`），gRPC 接入层在 `server/etcdserver/api/v3rpc/lease.go`。`Lessor` 只有 `Lookup` / `Renew` 这类进程内方法。
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

- [etcd](/docs/CS/Framework/etcd/etcd.md)
- [compare（与 ZooKeeper 临时节点的对应）](/docs/CS/Framework/etcd/compare.md)
- [concurrency（分布式锁 / 选主依赖 Session 租约）](/docs/CS/Framework/etcd/concurrency.md)
- [naming（endpoint 绑定 lease 自动下线）](/docs/CS/Framework/etcd/naming.md)

## References

1. [etcd source - server/lease/lessor.go（Lessor 接口、主循环、TTL 常量）](https://github.com/etcd-io/etcd/blob/v3.7.2/server/lease/lessor.go)
2. [etcd source - server/features/etcd_features.go（LeaseCheckpoint / FastLeaseKeepAlive 等 gate 默认值）](https://github.com/etcd-io/etcd/blob/v3.7.2/server/features/etcd_features.go)
3. [etcd source - server/etcdserver/v3_server.go（Lease* 的 gRPC 入口实现）](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/v3_server.go)
4. [etcd Documentation - Lease (TTL) API](https://etcd.io/docs/v3.7/api/lease/)
5. [etcd source - client/v3/lease.go（客户端 Lease 接口）](https://github.com/etcd-io/etcd/blob/v3.7.2/client/v3/lease.go)
