# Features

## Introduction

本篇讲 [etcd](/docs/CS/Framework/etcd/etcd.md) 的两个高层特性：基于 etcd 实现**服务发现**的原理与 APISIX 实战，以及 v3 迷你事务（Txn）的 API、ACID 实现与隔离级别。服务发现的 gRPC resolver 实现细节见 [naming](/docs/CS/Framework/etcd/naming.md)；分布式锁 / 选举 / STM 见 [concurrency](/docs/CS/Framework/etcd/concurrency.md)。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下片段均取自该 tag。

从源码核实的点：

- Txn 的客户端接口是 `If(cs...Cmp).Then(ops...Op).Else(ops...Op).Commit()`，`If` / `Then` / `Else` 内部用 `sync.Mutex` 防重复调用（如调两次 `If` 会 panic）。
- 隔离级别不是 etcd 自己实现的 SQL 等级，而是基于 [MVCC](/docs/CS/Framework/etcd/MVCC.md) revision + bbolt 事务能做到的几档，上层由 [STM](/docs/CS/Framework/etcd/concurrency.md) 封装。
- 服务发现最容易犯的错是不处理 Watch 返回的 `ErrCompacted`（revision 已被 [compact](/docs/CS/Framework/etcd/compact.md)），APISIX 从 v2 切到 v3 早期也踩过。

## Service Discovery

基于 etcd 的服务发现通用架构分四层：client 层、proxy 层（可选）、业务 server、etcd 存储层。引入 proxy 是为了让 client 更轻、逻辑更简单，无需直接访问存储层，同时可通过 proxy 支持各种协议。

- client 通过负载均衡访问 proxy；proxy 启动时用 `Range` RPC 读初始服务配置，随后用 Watch 持续监听后端扩缩容，实时改路由。
- proxy 收到请求后，按路由配置 + 负载均衡算法（如 Round-robin）转发到业务 server。
- 业务 server 启动用 `Txn`/`Put` 把地址、协议注册到 etcd；缩容/故障时 key 要能自动删除，因此 key 关联 Lease、设合理 TTL，定时 keepalive 续租。

Apache APISIX 就是这个架构里的 proxy，由控制面（Admin API 下发服务/路由/安全配置，默认存储是 etcd）和数据面（转发 + 限速、鉴权、安全、日志）组成。它在 etcd 下约定不同 key 前缀：

| 前缀 | 内容 |
| :--- | :--- |
| `/apisix/routes` | 路由配置（匹配规则、上游、插件） |
| `/apisix/services` | 服务配置（负载均衡算法、后端节点、协议） |
| `/apisix/ssl` | SSL 证书与密钥 |
| `/apisix/upstreams` | 上游节点定义 |
| `/apisix/consumers` | 消费者与认证信息 |

路由和服务配置的 value 是 JSON 对象，服务对象含 id、负载均衡算法、后端节点、协议等信息。APISIX 启动先 `Range` 拿全量配置/路由，随后用 Watch 拿增量变化。

> [!WARNING]
> 使用 Watch 最容易犯错的是**不处理返回的错误信息**，比如 `ErrCompacted`。一旦客户端持有 revision 超过压缩周期，Watch 会被服务端以 `mvcc: required revision has been compacted` 拒绝——必须捕获该错误、重新 LIST 拿最新 revision 再重建 Watch（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)）。

服务注册的 gRPC resolver 实现（如何把 watch 事件转换为 `resolver.UpdateState`）见 [naming](/docs/CS/Framework/etcd/naming.md)。

## Transaction

etcd v3 为解决多 key 原子操作提供迷你事务 API，基于 MVCC 版本号还能实现各种隔离级别。客户端接口定义在 `client/v3/txn.go`：

```go
// Txn is the interface that wraps mini-transactions.
//
//	Txn(context.TODO()).If(
//	 Compare(Value(k1), ">", v1),
//	 Compare(Version(k1), "=", 2)
//	).Then(
//	 OpPut(k2,v2), OpPut(k3,v3)
//	).Else(
//	 OpPut(k4,v4), OpPut(k5,v5)
//	).Commit()
type Txn interface {
	// If takes a list of comparison. If all comparisons passed in succeed,
	// the operations passed into Then() will be executed. Or the operations
	// passed into Else() will be executed.
	If(cs ...Cmp) Txn
	// Then takes a list of operations. The Ops list will be executed, if the
	// comparisons passed in If() succeed.
	Then(ops ...Op) Txn
	// Else takes a list of operations. The Ops list will be executed, if the
	// comparisons passed in If() fail.
	Else(ops ...Op) Txn
	// Commit tries to commit the transaction.
	Commit() (*TxnResponse, error)
}
```

`If` 的实现用 `sync.Mutex` 保证调用顺序，重复或乱序调用直接 panic（`cannot call If twice!` / `cannot call If after Then!`）：

```go
func (txn *txn) If(cs ...Cmp) Txn {
	txn.mu.Lock()
	defer txn.mu.Unlock()

	if txn.cif { panic("cannot call If twice!") }
	if txn.cthen { panic("cannot call If after Then!") }
	if txn.celse { panic("cannot call If after Else!") }

	txn.cif = true
	for i := range cs {
		cmp := cs[i].Clone()
		txn.cmps = append(txn.cmps, cmp.GetCompare())
	}
	return txn
}
```

### Comparison Items

`If` 支持四类检查项，都由 `client/v3/compare.go` 的构造函数生成 `Cmp`：

| 检查项 | 构造 | 用途 |
| :--- | :--- | :--- |
| `mod_revision` | `ModRevision(key)` | key 最近一次修改版本；`mod("Alice")="v1"` 保障转账时余额未被挪用 |
| `create_revision` | `CreateRevision(key)` | 创建版本；`create("lock")="0"` 判断 key 不存在（分布式锁创建） |
| `version` | `Version(key)` | 修改次数；`version("key")<"3"` 按修改次数控制 |
| `value` | `Value(key)` | key 的 value；`value("Alice")="200"` 按内容判断 |

配合等于/大于/小于/不等于等运算符，实现灵活的条件判断。

### ACID

- **原子性**：一个事务要么全成功要么全失败，基于 WAL 日志、consistent index、bbolt 事务能力支持。
- **一致性**：转账前后数据库与应用期望的恒等状态不变，由数据库与业务应用协作完成。
- **持久性**：事务提交后数据不丢（WAL + bbolt 落盘）。
- **隔离性**：etcd 不存在脏读，基于 MVCC + bbolt 事务可实现可重复读、串行化快照隔离，保障并发事务的数据安全。

### Isolation Levels

etcd 基于 MVCC + bbolt 事务可实现的隔离级别：

| 隔离级别 | 实现机制 | 可见性保证 |
| :--- | :--- | :--- |
| 读已提交（Read Committed） | bbolt 单事务 | 仅见已提交数据 |
| 可重复读（Repeatable Read） | MVCC 多版本 + 固定 revision 快照 | 事务内多次读看到同一快照 |
| 串行化快照隔离（SSI） | MVCC revision + 冲突检测 | 并发事务串行化，无脏读 / 幻读 |

社区 `STM`（`client/v3/concurrency/stm.go`）已封装上述隔离级别，把 `If(mod("Alice")=v1).Then(...)` 的手写 Txn 简化成 `Get`/`Put` + 自动冲突重试，简化应用编程（见 [concurrency](/docs/CS/Framework/etcd/concurrency.md)）。

## Links

- [MVCC](/docs/CS/Framework/etcd/MVCC.md)
- [naming](/docs/CS/Framework/etcd/naming.md)
- [concurrency](/docs/CS/Framework/etcd/concurrency.md)
- [compare](/docs/CS/Framework/etcd/compare.md)
- [watch](/docs/CS/Framework/etcd/watch.md)

## References

1. [etcd v3.7.4 源码（client/v3/txn.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/client/v3/txn.go)
2. [etcd v3.7.4 源码（client/v3/compare.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/client/v3/compare.go)
3. [Apache APISIX - Service Discovery](https://apisix.apache.org/docs/apisix/discovery/)
