## Introduction

Consul 的全部服务端状态收敛在一个**纯内存 memdb state store**（`agent/consul/state/state_store.go`，2.x 由旧版 `store.go` 更名）里：catalog（node/service/check）、KV、session、ACL、config entry 都是它的表。它由 Raft 日志经 FSM 逐条重建，阻塞查询与反熵对账也都挂在它上面。本篇讲清 state store 的内部结构、catalog 三要素、agent 本地注册与 server catalog 的**分离**，以及阻塞查询的统一实现。session 语义详见 [Session 与锁](/docs/CS/Framework/consul/Session.md)。本文源码核自 **v2.1.0**。

## State Store: In-Memory memdb over the Raft Log

```go
// Store is where we store all of Consul's state, including
// records of node registrations, services, checks, key/value
// pairs and more. The DB is entirely in-memory and is constructed
// from the Raft log through the FSM.
type Store struct {
	schema *memdb.DBSchema
	db     *changeTrackerDB

	// abandonCh is used to signal watchers that this state store has been
	// abandoned (usually during a restore). This is only ever closed.
	abandonCh chan struct{}

	// kvsGraveyard manages tombstones for the key value store.
	kvsGraveyard *Graveyard

	// lockDelay holds expiration times for locks associated with keys.
	lockDelay *Delay
}
```

`agent/consul/state/state_store.go`

三个要点：

- **内存 + Raft 重放**：没有落库引擎，重启靠 FSM `Restore` 快照重建（hashicorp/go-memdb，radix 索引 + 事务）。
- **single writer 由 Raft 保证**：`FSM.Apply` 只被 Raft 单 goroutine 调用，store 自身不设独立写锁；读事务天然并发。唯一的锁是 FSM 的 `stateLock`，用于保护 `Restore` 换库与外部 `State()` 读的竞态。
- **墓碑与锁延迟是 store 的内嵌组件**：KV 删除先写 tombstone（`kvsGraveyard`，供阻塞查询感知"刚删过"），leader 周期 `reapTombstones` 清理；lock-delay 的 `Delay` 对象也挂在 store 上（但只在 leader 内存里生效，见 [Session 与锁](/docs/CS/Framework/consul/Session.md)）。

有一个软限制值得知道——单个阻塞查询能挂的细粒度 watch 有上限，超限后自动升级为更粗的高层 watch：

```go
// watchLimit is used as a soft limit to cap how many watches we allow
// for a given blocking query. If this is exceeded, then we will use a
// higher-level watch that's less fine-grained. ...
	watchLimit = 8192
```

`agent/consul/state/state_store.go`

## FSM Snapshot and Restore

快照持久化时先写 header，再依次跑企业版/社区版 persister，最后 2.x 新增的 **resource storage**（raft storage backend，承载 2.x 的新资源服务）单独快照：

```go
// Persist saves the FSM snapshot out to the given sink.
func (s *snapshot) Persist(sink raft.SnapshotSink) error {
	defer metrics.MeasureSince([]string{"fsm", "persist"}, time.Now())

	// Write the header
	header := SnapshotHeader{
		LastIndex: s.state.LastIndex(),
	}
	encoder := codec.NewEncoder(sink, structs.MsgpackHandle)
	if err := encoder.Encode(&header); err != nil {
		sink.Cancel()
		return err
	}

	// Run all the persisters to write the FSM state.
	for _, fn := range []persister{
		// The enterprise version MUST be executed first, otherwise the snapshot will
		// not properly function during restore due to missing tenancy objects.
		entPersister,
		cePersister,
	} {
```

`agent/consul/fsm/snapshot.go`

Restore 是**整库替换**：构建全新 store、灌入快照、原子切换指针，然后 `Abandon()` 唤醒所有挂在旧库上的阻塞查询——这是阻塞查询正确性的关键：

```go
func (c *FSM) Restore(old io.ReadCloser) error {
	defer old.Close()

	stateNew := c.deps.NewStateStore()
	...
	// External code might be calling State(), so we need to synchronize
	// here to make sure we swap in the new state store atomically.
	c.stateLock.Lock()
	stateOld := c.state
	c.state = stateNew
	...
	c.stateLock.Unlock()

	// Signal that the old state store has been abandoned. This is required
	// because we don't operate on it any more, we just throw it away, so
	// blocking queries won't see any changes and need to be woken up.
	stateOld.Abandon()

	return nil
}
```

`agent/consul/fsm/fsm.go`

## Catalog: Node / Service / Check

catalog 是 server 维护的全局注册表，由三类对象构成，关系为 **node ⊃ service ⊃ check**：

- **Node（节点）**：一个被 Consul 认知的主机，含 `NodeID`、地址、元数据；由 agent 注册产生。
- **Service（服务）**：挂在 node 下的实例，含服务名、端口、tag、weights。同一服务名可在多 node 有多实例。
- **Check（健康检查）**：挂在 node 或 service 下，类型覆盖 `script` / `http` / `tcp` / `grpc` / `ttl`。节点级 check（如 `serfHealth`）作用于该 node 上所有服务。

catalog 与"本地 agent 注册"**分离**：服务由 agent 上报后 server 确认进 catalog；**单个 agent 挂了不影响 catalog 中已确认的服务**——存活语义由 serf 派生的 `serfHealth` check 表达，健康语义由健康检查表达。这与 etcd"进程退出 key 即删"的 lease 模型截然不同（etcd 对比见 [etcd read](/docs/CS/Framework/etcd/read.md)）。

节点级与服务级 check 在查询时合并，逻辑在 `agent/consul/state/catalog.go` 的 `parseCheckServiceNodes`：

```go
		// First add the node-level checks. These always apply to any
		// service on the node.
		var checks structs.HealthChecks
		q := NodeServiceQuery{
			Node:           sn.Node,
			Service:        "", // node checks have no service
			EnterpriseMeta: *sn.WithWildcardNamespace(),
			PeerName:       sn.PeerName,
		}
		iter, err := tx.Get(tableChecks, indexNodeService, q)
		...
		for check := iter.Next(); check != nil; check = iter.Next() {
			checks = append(checks, check.(*structs.HealthCheck))
		}

		// Now add the service-specific checks.
		...
```

`agent/consul/state/catalog.go`

> [!WARNING]
> 2.x 纠偏：旧资料里常见的 `passingCount` 在 v2.1.0 中并不存在。passing 过滤由三档枚举 **`HealthFilterType`**（`IncludeAll` / `ExcludeCritical` / `IncludeOnlyPassing`）+ `ExcludeBasedOnChecks` 实现，`Health.ServiceNodes` 在返回侧执行 `Filter`；`Catalog.ServiceNodes` 则**不做任何健康过滤**（catalog 本就不带健康语义）。

```go
func (csn *CheckServiceNode) ExcludeBasedOnChecks(opts CheckServiceNodeFilterOptions) bool {
	for _, check := range csn.Checks {
		if slices.Contains(opts.IgnoreCheckIDs, check.CheckID) {
			// Skip this _check_ but keep looking at other checks for this node.
			continue
		}
		if opts.FilterType.ExcludeBasedOnStatus(check.Status) {
			return true
		}
	}
	return false
}
```

`agent/structs/structs.go`

## Agent Local State vs Server Catalog

```dot
digraph catalog_sync {
  rankdir=LR;
  node [shape=box, style="rounded,filled", fontname="Helvetica"];
  edge [color="#555", fontsize=10];

  local [label="Agent 本地注册表\nagent/local/state.go\nDeleted / InSync 双标记", fillcolor="#eef3fb"];
  ae [label="Anti-Entropy 状态机\nagent/ae/ae.go\nSyncFull → SyncChanges", fillcolor="#fdeccb"];
  cat [label="Server Catalog\n(Raft + memdb)", fillcolor="#d6ead0"];

  local -> ae [label="TriggerSyncChanges"];
  ae -> cat [label="Catalog.Register / Deregister"];
  cat -> ae [label="SyncFull diff"];
}
```

同步机制的三个环节：

- **标脏**：本地注册/检查变更置 `InSync=false`（检查状态变更还有 output 节流——状态没变只更新 output 时延迟半周期回写），经注入的 `TriggerSyncChanges` 回调异步触发同步。
- **增量**（`SyncChanges`）：把脏数据直接 push——服务与它的检查**合并进同一条 `Catalog.Register`**，保证原子注册：

```go
	// If the service has associated checks that are out of sync,
	// piggyback them on the service sync so they are part of the
	// same transaction and are registered atomically. ...
	var checks structs.HealthChecks
	...
	req := structs.RegisterRequest{
		Datacenter:      l.config.Datacenter,
		ID:              l.config.NodeID,
		Node:            l.config.NodeName,
		Address:         l.config.AdvertiseAddr,
		TaggedAddresses: l.config.TaggedAddresses,
		NodeMeta:        l.metadata,
		Service:         l.services[key].Service,
		EnterpriseMeta:  key.EnterpriseMeta,
		WriteRequest:    structs.WriteRequest{Token: st},
		SkipNodeUpdate:  l.nodeInfoInSync,
	}
```

`agent/local/state.go`

- **全量**（`SyncFull`）：反熵状态机的初始态——先 `Catalog.NodeServiceList`（`AllowStale` 且 `MaxStaleDuration=2s`）拉远端做 diff，再走 `SyncChanges`。因此 agent 短暂失联后，catalog 保留最后已知状态，直到 serf 判死触发 `reconcileReaped` 注销（leader 扫描"serf 已不认识但 catalog 还有 serfHealth check"的节点）。

> [!TIP]
> 反熵与 gossip 解耦：成员存活由 Serf 管，服务/检查状态由反熵 + 健康检查管。调试"服务从 catalog 消失"时，先分清是哪条路径删的——serf reap（节点级）还是 agent 反注册（服务级，且强制用 agent token，`node:write` 即可，避免 service token 失效卡死）。

## Blocking Query

阻塞查询在 2.x 被抽成独立包 `agent/blockingquery`（1.x 内嵌在各 endpoint）。`Server.blockingQuery` 只是兼容 passthrough。核心循环：

```go
	maxQueryTimeout, err := requestOpts.GetMaxQueryTime()
	...
	timeout := fsmServer.RPCQueryTimeout(maxQueryTimeout)
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	...
	store := fsmServer.GetState()

	ws := memdb.NewWatchSet()
	// This channel will be closed if a snapshot is restored and the
	// whole state store is abandoned.
	ws.Add(store.AbandonCh())

	err := query(ws, store)
	fsmServer.SetQueryMeta(responseMeta, requestOpts.GetToken())
	...
	if responseMeta.GetIndex() > minQueryIndex {
		return nil
	}

	// block until something changes, or the timeout
	if err := ws.WatchCtx(ctx); err != nil {
		// exit if we've reached the timeout, or other cancellation
		return nil
	}
```

`agent/blockingquery/blockingquery.go`

设计要点：① 查询函数拿到 `memdb.WatchSet`，读事务把自己关心的索引 watch 注册进去；② `AbandonCh` 让 Restore 换库能整体唤醒；③ consistent 模式的 `VerifyLeader` 也统一在这一层入口处做；④ 2.x 新增哨兵错误 `ErrNotChanged`（配合 `errNotFound`），用于"响应未变"时抑制假唤醒、保住阻塞连接——`Health.ServiceNodes` 的 merge-hash 去重就依赖它。

agent 侧还有一层 **agent cache**（`agent/cache`），`RegisterOptions{Refresh, SupportsBlocking, LastGetTTL}` 声明各类型的缓存行为，后台 refresh 失败走指数退避。服务发现类查询走 cache 时长阻塞由 cache 承接，client 与 server 之间是短请求——详见 [Discovery](/docs/CS/Framework/consul/discovery.md)。

## KV vs Catalog Boundary

| 维度 | KV | Catalog |
| :--- | :--- | :--- |
| 模型 | 扁平 key-value，单值 ≤ 512KB | 结构化 node/service/check 关系表 |
| 版本历史 | 无（仅 `ModifyIndex` 当前版本） | 无 |
| 典型用途 | 配置、锁、信号量、feature flag | 服务注册与发现、健康状态 |
| 绑定 session | 支持（锁/临时键） | 不直接支持 |
| 读一致性 | 默认走 leader | 默认本地缓存 stale，可 `?consistent` |

二者都跑在 Raft 之上、强一致，但 catalog 是为"服务拓扑"量身的结构化视图，KV 是通用键值；不要把"服务注册"塞进 KV——catalog 自带健康过滤与 DNS 映射，KV 没有。

## Links

- [Consul（枢纽）](/docs/CS/Framework/consul/Consul.md)
- [KV（存储）](/docs/CS/Framework/consul/kv.md)
- [Session 与锁](/docs/CS/Framework/consul/Session.md)
- [Discovery（服务发现）](/docs/CS/Framework/consul/discovery.md)
- [Serf（成员发现）](/docs/CS/Framework/consul/serf.md)
- [Raft（共识）](/docs/CS/Framework/consul/raft.md)
- [etcd read（线性/串行读）](/docs/CS/Framework/etcd/read.md)

## References

1. [Consul Catalog](https://developer.hashicorp.com/consul/docs/architecture/consul-architecture-catalog)
2. [hashicorp/consul v2.1.0 blockingquery](https://github.com/hashicorp/consul/tree/v2.1.0/agent/blockingquery)
3. [Consul Anti-entropy](https://developer.hashicorp.com/consul/docs/architecture/anti-entropy)
4. [hashicorp/go-memdb](https://github.com/hashicorp/go-memdb)
