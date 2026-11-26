## Introduction

Consul 的"客户端"有两个完全不同的层次：**接入层**（业务怎么用：go-client / HTTP / DNS / CLI，无需私有 SDK）与**agent 内部的 RPC 转发层**（client agent 怎么把请求送到 server：conn pool + yamux + router）。本篇两层都讲清——后者是理解"client 挂了会不会丢注册、RPC 失败怎么换 server"的基础。本文源码核自 **v2.1.0**。

## go-client (Official SDK)

官方 `github.com/hashicorp/consul/api` 包按子系统拆分 client：

| 子 client | 用途 |
| :--- | :--- |
| `api.KV()` | KV 读写、CAS（`cas` 参数）、`acquire`/`release` 锁 |
| `api.Health()` | 带健康过滤的服务发现（`health.Service("web", &QueryOptions{PassingOnly:true})`） |
| `api.Catalog()` | 全量目录（不过滤健康） |
| `api.Agent()` | 本节点服务 / 检查注册、本 agent 视角 |
| `api.Session()` | 创建 / 销毁 session（锁、leader 选举） |
| `api.PreparedQuery()` | 命名查询 |

`api.DefaultConfig()` 默认连本机 `127.0.0.1:8500`（HTTP）。`QueryOptions{AllowStale:true}` 走 agent 缓存（见 [Discovery](/docs/CS/Framework/consul/discovery.md)），`WaitIndex`+`WaitTime` 实现阻塞查询，`RequireConsistent` 强制 leader 读。

## Agent RPC: Client to Server

### Router and Server Selection

client 把 RPC 发给哪个 server，由 `agent/router/router.go` 决定。2.x 纠偏：**不存在** 1.x 资料里的 `FindRegionServer`——跨区域抽象统一为 area，client 本地选路走 `FindLANRoute`：

```go
// FindLANRoute returns a healthy server within the local datacenter. In some
// cases this may return a best-effort unhealthy server that can be used for a
// connection attempt. ...
func (r *Router) FindLANRoute() (*Manager, *metadata.Server) {
	mgr := r.GetLANManager()

	if mgr == nil {
		return nil, nil
	}

	return mgr, mgr.FindServer()
}
```

`agent/router/router.go`

server 列表来源是 serf LAN 成员事件（`lanNodeJoin` → `router.AddServer`），失败反馈是 `manager.NotifyFailedServer(server)`——连接失败会换下一台，并随 gossip 传播的成员变化自动增删候选。

### Client RPC Loop

`Client.RPC` 的完整逻辑：选 server → 限流 → 发请求 → 失败换 server 重试：

```go
// RPC is used to forward an RPC call to a consul server, or fail if no servers
func (c *Client) RPC(ctx context.Context, method string, args interface{}, reply interface{}) error {
	...
	metrics.IncrCounter([]string{"client", "rpc"}, 1)
TRY:
	retryCount++
	manager, server := c.router.FindLANRoute()
	if server == nil {
		metrics.IncrCounter([]string{"client", "rpc", "failed"}, 1)
		return structs.ErrNoServers
	}

	// Enforce the RPC limit.
	if !c.rpcLimiter.Load().(*rate.Limiter).Allow() {
		metrics.IncrCounter([]string{"client", "rpc", "exceeded"}, 1)
		return structs.ErrRPCRateExceeded
	}

	// Make the request.
	rpcErr := c.connPool.RPC(c.config.Datacenter, server.ShortName, server.Addr, method, args, reply)
	if rpcErr == nil {
		return nil
	}

	// Move off to another server, and see if we can retry.
	manager.NotifyFailedServer(server)
```

`agent/consul/client.go`

注意两个保护：① client 侧有本机 RPC 限流器（`ErrRPCRateExceeded`），打爆自己 agent 的业务会直接拿到错误；② 跨 DC 时走 `FindRoute(dc)`（非 LAN）。

### Conn Pool: yamux Multiplexing

`agent/pool/pool.go` 的连接是 **yamux 多路复用**的：拨号时先写一个 Consul 私有的多路复用握手字节（`RPCMultiplexV2`），再建 yamux session，一条 TCP 承载所有并发 RPC：

```go
	// Get a new, raw connection and write the Consul multiplex byte to set the mode
	conn, _, err := p.DialTimeout(dc, nodeName, addr, RPCMultiplexV2)
	if err != nil {
		return nil, err
	}

	conf := yamux.DefaultConfig()
	// override the default because LogOutput conflicts with Logger.
	conf.LogOutput = nil
	conf.Logger = p.Logger

	// Create a multiplexed session
	session, err := yamux.Client(conn, conf)
```

`agent/pool/pool.go`

阻塞查询有专门的超时处理：带 blocking 参数的请求会把 client 超时拉长为 `blockingTimeout + RPCHoldTimeout`（hold 余量用于 leader 切换期间的重试），避免长轮询被误杀：

```go
	var deadline time.Time
	timeout := p.RPCClientTimeout()
	if bq, ok := args.(BlockableQuery); ok {
		blockingTimeout := bq.BlockingTimeout(p.MaxQueryTime, p.DefaultQueryTime)
		if blockingTimeout > 0 {
			// Override the default client timeout but add RPCHoldTimeout
			// as a buffer for retries during leadership changes.
			timeout = blockingTimeout + p.RPCHoldTimeout
		}
	}
```

`agent/pool/pool.go`

server 端跨 DC 转发也复用同一个 conn pool：`forwardDC` 用 `router.FindRoute(dc)` 选目标 DC 的 server（`agent/consul/rpc.go`）。

## Local Registration State

client agent 的注册/检查落在 `agent/local/state.go` 的内存状态（`Deleted` / `InSync` 双标记），经反熵同步到 server——完整同步机制见 [数据模型](/docs/CS/Framework/consul/data_model.md)。这里只强调与"客户端容灾"相关的两点：

- **agent 挂 ≠ 服务下线**：catalog 里的注册仍保留（直到 serf 判死节点 → leader `reconcileReaped` 注销）。client 重启后反熵 `SyncFull` 重新对账，不需要业务重注册。
- **配置驱动注册**：`agent/service_manager.go` 的 `ServiceManager` 不是注册同步器——它是**中央服务配置 watcher**（`cache.Notify` 监听 `ResolvedServiceConfigName`），中央 config 变更时合并配置重新注册：

```go
// ServiceManager watches changes to central service config for all services
// registered with it. When a central config changes, the local service will
// be updated with the correct values from the central config.
type ServiceManager struct {
	agent *Agent

	// servicesLock guards the services map, but not the watches contained
	// therein
	servicesLock sync.Mutex

	// services tracks all active watches for registered services
	services map[structs.ServiceID]*serviceConfigWatch
```

`agent/service_manager.go`

## Access Without SDK

```bash
# HTTP：注册一个服务 + TTL 检查
curl -X PUT http://127.0.0.1:8500/v1/agent/service/register -d '{
  "name": "web", "port": 8080,
  "check": { "id": "web-ttl", "ttl": "30s" }
}'
curl -X PUT http://127.0.0.1:8500/v1/agent/check/pass/web-ttl

# 发现（带健康过滤 + 阻塞查询）
curl -s 'http://127.0.0.1:8500/v1/health/service/web?passing&index=<idx>&wait=5m'

# DNS：标准 dig 即可
dig @127.0.0.1 -p 8600 web.service.consul SRV

# CLI
consul members            # serf LAN 成员
consul catalog services   # 全部服务名
```

## Comparison with etcd / ZooKeeper

| 维度 | Consul | etcd | ZooKeeper |
| :--- | :--- | :--- | :--- |
| 接入方式 | HTTP/DNS/gRPC，无需 SDK | gRPC（Java/Go client） | 私有协议 |
| 本地缓存 | agent cache + stale 默认 | 无（客户端自己做） | 无 |
| 连接复用 | yamux 多路复用 TCP | HTTP/2 gRPC | 单 TCP NIO |
| RPC 失败处理 | router 自动换 server + NotifyFailedServer | 客户端 endpoint 切换 | 客户端重连 |
| 注册容灾 | 反熵对账，agent 重启无需重注册 | lease 失效即删 | session 失效即删 |

## Links

- [Consul（枢纽与架构）](/docs/CS/Framework/consul/Consul.md)
- [数据模型（反熵与注册容灾）](/docs/CS/Framework/consul/data_model.md)
- [Discovery（服务发现与缓存）](/docs/CS/Framework/consul/discovery.md)
- [KV（存储）](/docs/CS/Framework/consul/kv.md)
- [Session 与锁](/docs/CS/Framework/consul/Session.md)
- [etcd client](/docs/CS/Framework/etcd/client.md)

## References

1. [Consul Agent HTTP API](https://developer.hashicorp.com/consul/api-docs/agent)
2. [hashicorp/consul api package](https://github.com/hashicorp/consul/tree/v2.1.0/api)
3. [hashicorp/consul v2.1.0 pool/pool.go](https://github.com/hashicorp/consul/blob/v2.1.0/agent/pool/pool.go)
