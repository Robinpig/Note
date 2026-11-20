## Introduction

Consul 的 **KV 存储**是基于 Raft 的强一致键值，命令 `consul kv` / HTTP `/v1/kv/<key>`。它和 etcd 的 KV 看起来相似，但语义有明显差异：**Consul KV 不保留历史版本**（每次写直接覆盖），而 etcd 的 MVCC 保留多 revision（见 [etcd MVCC](/docs/CS/Framework/etcd/MVCC.md)）。Consul KV 的"协调"能力主要靠 **session**（类似 etcd 的 lease，生命周期与失效行为详见 [Session 与锁](/docs/CS/Framework/consul/Session.md)）。本文源码核自 **v2.1.0**。

> [!WARNING]
> 2.x 纠偏：server 端 RPC handler 是 `KVS.Apply` / `KVS.Get`（`agent/consul/kvs_endpoint.go`）——旧资料里的 `KVSPut`/`KVSDelete` 只是 HTTP 层函数名。"acquire 失败返回 HTTP 409"的说法与源码不符：state store 返回 `false`，HTTP 层返回 **200 + body `false`**。

## Basic Semantics

- **无历史版本**：写操作整体替换 value，不留存旧 revision；无法像 etcd 那样"从某 revision 读历史"。
- **层级键**：以 `/` 分隔的任意字符串键，`consul kv get -recurse` 可递归列举前缀。
- **单值上限 512KB**：大对象应外置到对象存储、KV 只存指针。超大的单条写会走 **Raft 分片提交**（`raftchunking.ChunkingApply`）。
- **CAS（Check-And-Set）**：写请求带 `cas=<ModifyIndex>`，`ModifyIndex` 每次写置为 Raft index（不是自增计数器）。
- **每个 entry 携带三个索引**：`CreateIndex`（首次创建的 Raft index）、`ModifyIndex`（最后修改）、`LockIndex`（累计被 acquire 的次数，仅锁语义使用）。

## Write Path

server 端写入口 `KVS.Apply`：先 `ForwardRPC` 转发到 leader，然后做 ACL + lock-delay 前置校验，最后 `raftApply`：

```go
// Apply is used to apply a KVS update request to the data store.
func (k *KVS) Apply(args *structs.KVSRequest, reply *bool) error {
	if done, err := k.srv.ForwardRPC("KVS.Apply", args, reply); done {
		return err
	}
	defer metrics.MeasureSince([]string{"kvs", "apply"}, time.Now())

	// Perform the pre-apply checks.
	authz, err := k.srv.ResolveTokenAndDefaultMeta(args.Token, &args.DirEnt.EnterpriseMeta, nil)
	if err != nil {
		return err
	}
	...
	ok, err := kvsPreApply(k.logger, k.srv, authz, args.Op, &args.DirEnt)
	if err != nil {
		return err
	}
	...
	// Apply the update.
	resp, err := k.srv.raftApply(structs.KVSRequestType, args)
	...
}
```

`agent/consul/kvs_endpoint.go`

FSM 侧落在 `agent/consul/state/kvs.go` 的 `kvsSetTxn`，索引维护规则一目了然：

```go
func kvsSetTxn(tx WriteTxn, idx uint64, entry *structs.DirEntry, updateSession bool) error {
	existingNode, err := tx.First(tableKVs, indexID, entry)
	...
	existing, _ := existingNode.(*structs.DirEntry)

	// Set the CreateIndex.
	if existing != nil {
		entry.CreateIndex = existing.CreateIndex
	} else {
		entry.CreateIndex = idx
	}

	// Preserve the existing session unless told otherwise. The "existing"
	// session for a new entry is "no session".
	if !updateSession {
		if existing != nil {
			entry.Session = existing.Session
		} else {
			entry.Session = ""
		}
	}

	// Set the ModifyIndex.
	if existing != nil && existing.Equal(entry) {
		// Skip further writing in the state store if the entry is not actually
		// changed. ...
		entry.ModifyIndex = existing.ModifyIndex
		return nil
	}
	entry.ModifyIndex = idx

	// Store the kv pair in the state store and update the index.
	if err := insertKVTxn(tx, entry, false, false); err != nil {
		return fmt.Errorf("failed inserting kvs entry: %s", err)
	}

	return nil
}
```

`agent/consul/state/kvs.go`

三个值得注意的语义：① `CreateIndex` 跨写保留；② **普通 put 不改 session 绑定**（想换绑/解绑必须走锁操作或 `updateSession` 路径）；③ 内容完全相同的重复写跳过落库，`ModifyIndex` 不变——重复 put 不会触发阻塞查询假唤醒。

## CAS

CAS 的 check-index 校验在同一文件的 `kvsSetCASTxn`：

```go
	// Check if the we should do the set. A ModifyIndex of 0 means that
	// we are doing a set-if-not-exists.
	if entry.ModifyIndex == 0 && existing != nil {
		return false, nil
	}
	if entry.ModifyIndex != 0 && existing == nil {
		return false, nil
	}
	e, ok := existing.(*structs.DirEntry)
	if ok && entry.ModifyIndex != 0 && entry.ModifyIndex != e.ModifyIndex {
		return false, nil
	}
```

`agent/consul/state/kvs.go`

`cas=0` 有特殊语义：**set-if-not-exists**（键不存在才写）。

## Lock and Unlock

`LockIndex` 不在普通写里维护，而在独立的 `kvsLockTxn`（acquire）/`kvsUnlockTxn`（release）：

```go
	// Set up the entry, using the existing entry if present.
	if existing != nil {
		e := existing.(*structs.DirEntry)
		if e.Session == entry.Session {
			// We already hold this lock, good to go.
			entry.CreateIndex = e.CreateIndex
			entry.LockIndex = e.LockIndex
		} else if e.Session != "" {
			// Bail out, someone else holds this lock.
			return false, nil
		} else {
			// Set up a new lock with this session.
			entry.CreateIndex = e.CreateIndex
			entry.LockIndex = e.LockIndex + 1
		}
	} else {
		entry.CreateIndex = idx
		entry.LockIndex = 1
	}
	entry.ModifyIndex = idx
```

`agent/consul/state/kvs.go`

三态清晰：同一 session 重入直接放行；被别的 session 持有返回 `false`；无主则 `LockIndex+1` 上锁。`LockIndex` 让等待方知道"锁换过几手"，配合 `ModifyIndex` 可区分"重入"与"易主"。

## Blocking Query

KV 读端点 `KVS.Get` 用 `ent.ModifyIndex` 作为阻塞索引：

```go
	return k.srv.blockingQuery(
		&args.QueryOptions,
		&reply.QueryMeta,
		func(ws memdb.WatchSet, state *state.Store) error {
			index, ent, err := state.KVSGet(ws, args.Key, &args.EnterpriseMeta)
			...
			reply.Index = ent.ModifyIndex
			reply.Entries = structs.DirEntries{ent}
			return nil
		})
```

`agent/consul/kvs_endpoint.go`

超时截断与抖动在 `Server.RPCQueryTimeout`：默认等待 `DefaultQueryTime = 300s`，硬上限 `MaxQueryTime = 600s`，再叠加 `timeout/JitterFraction` 的随机抖动（`agent/consul/config.go`、`rpc.go`）。阻塞实现细节（memdb `WatchSet`、`agent/blockingquery` 包）见 [数据模型](/docs/CS/Framework/consul/data_model.md)。

## Command Cheatsheet

```bash
# 基础读写
consul kv put app/config '{"timeout":30}'   # 写
consul kv get -raw app/config               # 读（-raw 输出明文，默认是 Base64）
consul kv get -recurse app/                 # 递归读前缀
consul kv get -detailed app/config          # 带元数据（ModifyIndex / LockIndex / Session）
consul kv delete app/config                 # 删

# CAS：无锁乐观并发
consul kv get -detailed app/config          # 取当前 ModifyIndex
consul kv put -cas=<ModifyIndex> app/config 'new'

# session：锁与临时键的载体（详见 Session.md）
consul session create -ttl=30s -behavior=delete
consul kv put -acquire=<sid> lock/leader 'me'   # 取锁
consul kv put -release=<sid> lock/leader 'me'   # 放锁

# HTTP：阻塞查询（长轮询）——index 用上次响应的 X-Consul-Index
curl -s 'http://127.0.0.1:8500/v1/kv/app/config?index=<idx>&wait=5m'
```

> [!TIP]
> `consul kv get` 默认输出 **Base64 编码**的值，脚本里记得加 `-raw`。阻塞查询返回的 `X-Consul-Index` 是"下一次轮询要带的下标"，务必回传，否则等于退化成轮询。

## Comparison with etcd

| 维度 | Consul KV | etcd KV |
| :--- | :--- | :--- |
| 历史版本 | 无（仅 ModifyIndex 单值） | MVCC 多 revision |
| 临时键/锁 | session（LockDelay 15s） | lease（TTL） |
| CAS | `cas=<ModifyIndex>`（0 = set-if-not-exists） | `prevIndex` / 事务 |
| 大值 | 512KB + Raft 分片 | 默认 1.5MB（可配） |
| 监听变更 | 阻塞查询（无历史回溯） | watch（按 revision，可回溯） |
| 事务 | 不支持 STM | concurrency.STM |

Consul KV 的定位是"配合服务发现与配置的小型强一致存储"，不是 etcd 那种面向海量协调事件的 MVCC 引擎。若需要历史回溯、事务或大规模监听，etcd 更合适；若只是存配置、做 leader 选举、加分布式锁，Consul KV + session 足够且 API 友好。

## Links

- [Consul（枢纽与架构）](/docs/CS/Framework/consul/Consul.md)
- [Session 与锁](/docs/CS/Framework/consul/Session.md)
- [Raft（共识）](/docs/CS/Framework/consul/raft.md)
- [数据模型](/docs/CS/Framework/consul/data_model.md)
- [Discovery（服务发现）](/docs/CS/Framework/consul/discovery.md)
- [etcd MVCC](/docs/CS/Framework/etcd/MVCC.md)
- [etcd lease](/docs/CS/Framework/etcd/lease.md)

## References

1. [Consul KV Store](https://developer.hashicorp.com/consul/docs/concepts/key-value-store)
2. [KV HTTP API](https://developer.hashicorp.com/consul/api-docs/kv)
3. [hashicorp/consul v2.1.0 state/kvs.go](https://github.com/hashicorp/consul/blob/v2.1.0/agent/consul/state/kvs.go)
