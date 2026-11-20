## Introduction

Consul 的**网关**与**多数据中心联邦**是它"跨机房原生"能力的落地。etcd 是单一 Raft 组、跨 DC 需外部复制；ZooKeeper 无跨 DC 概念；Consul 则把 mesh gateway / WAN federation / cluster peering 做成一等能力。本篇覆盖四类网关与跨 DC 的三种形态。本文源码核自 **v2.1.0**。

> [!WARNING]
> 2.x 纠偏：`agent/consul/gateways/` 目录是 **api-gateway 的 reconcile controller**（订阅 APIGateway/HTTPRoute/BoundAPIGateway 事件流），**不是 mesh gateway**——mesh gateway 的服务端发现靠 `gateway_locator.go` 与 proxycfg 数据源。另外 transparent proxy 的重定向已迁 nftables（见 [Mesh](/docs/CS/Framework/consul/mesh.md)）。

## Mesh Gateway (Service Mesh Cross-DC)

mesh gateway 部署在 DC 边界，作为进出本 DC 的网格流量汇聚点，让跨 DC 网格流量走 WAN 而**不必把每个 sidecar 暴露到公网**：

- **local 模式**：本 DC sidecar → 本地 gateway → 远端 gateway → 目标 sidecar；
- **remote 模式**：sidecar 直连远端 gateway；
- WAN federation 走 mesh gateway 时，server 只需暴露本地 gateway 的地址，WAN Serf（8302）与 Server RPC（8300）流量经 gateway 隧道转发。

server 自身经 gateway 隧道 RPC/gossip 时的网关挑选由 **GatewayLocator** 负责——它只认带 `wanfed:1` meta 的 gateway 实例：

```go
// GatewayLocator assists in selecting an appropriate mesh gateway when wan
// federation via mesh gateways is enabled.
//
// This is exclusively used by the consul server itself when it needs to tunnel
// RPC or gossip through a mesh gateway to reach its ultimate destination.
type GatewayLocator struct {
	...
	// these ONLY contain ones that have the wanfed:1 meta
	gatewaysLock      sync.Mutex
	primaryGateways   []string // WAN addrs
	localGateways     []string // LAN addrs
	populatedGateways bool
```

`agent/consul/gateway_locator.go`

接线在 `server.go`：开启 `ConnectMeshGatewayWANFederationEnabled` 时，把 `PickGateway` 注入 conn pool 与 gRPC conn pool：

```go
	if s.config.ConnectMeshGatewayWANFederationEnabled {
		s.gatewayLocator = NewGatewayLocator(
			s.logger,
			s,
			s.config.Datacenter,
			s.config.PrimaryDatacenter,
		)
		s.connPool.GatewayResolver = s.gatewayLocator.PickGateway
		s.grpcConnPool.SetGatewayResolver(s.gatewayLocator.PickGateway)
	}
```

`agent/consul/server.go`

locator 判断 primary gateway 可达性的方式很务实——**借用 federation state 复制循环的成功/失败作为探针**，而不是再发 ping：

```go
// SetLastFederationStateReplicationError is used to indicate if the federation
// state replication loop has succeeded (nil) or failed during the last
// execution.
//
// Rather than introduce a completely new mechanism to periodically probe that
// our chosen mesh-gateway configuration can reach the primary's servers (like
// a ping or status RPC) we cheat and use the federation state replicator
// goroutine's success or failure as a proxy.
```

`agent/consul/gateway_locator.go`

primary mesh gateway 地址可由 **federation state 复制**回填（无回填时用 `primary_gateways` 静态 fallback 配置）。

## Ingress Gateway (North-South Inbound)

ingress gateway 把外部流量引入网格：在 `ingress-gateway` config entry 里声明 listener（端口 + 协议 tcp/http/http2/grpc）与背后的服务，Envoy 据此生成监听器。2.x 中 ingress/terminating 的 config entry **合并进了单文件** `config_entry_gateways.go`：

```go
// IngressGatewayConfigEntry manages the configuration for an ingress service
// with the given name.
type IngressGatewayConfigEntry struct {
	// Kind of the config entry. This will be set to structs.IngressGateway.
	Kind string

	// Name is used to match the config entry with its associated ingress gateway
	// service. This should match the name provided in the service definition.
	Name string

	// TLS holds the TLS configuration for this gateway.
	TLS GatewayTLSConfig

	// Listeners declares what ports the ingress gateway should listen on, and
	// what services to associated to those ports.
	Listeners []IngressListener

	// Defaults contains default configuration for all upstream service instances
	Defaults *IngressServiceConfig `json:",omitempty"`
	...
}
```

```go
type IngressListener struct {
	// Port declares the port on which the ingress gateway should listen for traffic.
	Port int

	// Protocol declares what type of traffic this listener is expected to
	// receive. ...
	Protocol string

	// TLS config for this listener.
	TLS *GatewayTLSConfig `json:",omitempty"`

	// Services declares the set of services to which the listener forwards traffic.
	//
	// For "tcp" protocol listeners, only a single service is allowed.
	// For "http" listeners, multiple services can be declared.
	Services []IngressService
}
```

`agent/structs/config_entry_gateways.go`

## Terminating Gateway (Bridge to Non-Mesh Services)

terminating gateway 让网格内的服务访问**不在网格里的外部服务**（遗留服务、托管数据库）：gateway 代表目标服务做 TLS 发起（`SNI`）、证书注入，网格侧则把它当作普通上游。2.x 新增本地凭据注入（UDS handler）：

```go
// TerminatingGatewayConfigEntry manages the configuration for a terminating service
// with the given name.
type TerminatingGatewayConfigEntry struct {
	Kind                string
	Name                string
	Services            []LinkedService
	CredentialInjection *GatewayCredentialInjection `json:",omitempty" alias:"credential_injection"`
	...
}
```

```go
// A LinkedService is a service represented by a terminating gateway
type LinkedService struct {
	// Name is the name of the service, as defined in Consul's catalog
	Name string `json:",omitempty"`
	...
	// SNI is the optional name to specify during the TLS handshake with a linked service
	SNI string `json:",omitempty"`

	//DisableAutoHostRewrite disables terminating gateways auto host rewrite feature when set to true.
	DisableAutoHostRewrite bool `json:",omitempty"`
	...
}
```

`agent/structs/config_entry_gateways.go`

## API Gateway Controller

api-gateway（1.16+ 引入，基于 Gateway API 语义）在 server 端有一个**事件驱动的 reconcile controller**（`agent/consul/gateways/`）——订阅 APIGateway / HTTPRoute / TCPRoute / BoundAPIGateway 的变更流，把用户声明绑定成 `BoundAPIGatewayConfigEntry`：

```go
func (r *apiGatewayReconciler) Reconcile(ctx context.Context, req controller.Request) error {
	switch req.Kind {
	case structs.APIGateway:
		return reconcileEntry(r.fsm.State(), r.logger, ctx, req, r.reconcileGateway, r.cleanupGateway)
	case structs.BoundAPIGateway:
		return reconcileEntry(r.fsm.State(), r.logger, ctx, req, r.reconcileBoundGateway, r.cleanupBoundGateway)
	case structs.HTTPRoute:
		return reconcileEntry(r.fsm.State(), r.logger, ctx, req, r.reconcileHTTPRoute, r.cleanupRoute)
	case structs.TCPRoute:
		return reconcileEntry(r.fsm.State(), r.logger, ctx, req, r.reconcileTCPRoute, r.cleanupRoute)
	...
}
```

`agent/consul/gateways/controller_gateways.go`

## WAN Federation vs Cluster Peering

跨 DC 有两种形态，语义不同：

| 维度 | WAN Federation | Cluster Peering |
| :--- | :--- | :--- |
| 关系 | 同一"逻辑集群"的多 DC 联邦 | 两个独立 cluster 的对等连接 |
| 发现机制 | WAN serf 池（成员 gossip） | peering token + gRPC 流复制 |
| 状态共享 | catalog 各自复制/转发查询 | catalog/health/CA **订阅流**单向同步 |
| 用途 | 传统多机房联邦 | 隔离集群互访（多租户/混合云） |

**WAN federation** 的成员底座是 WAN serf（见 [Serf](/docs/CS/Framework/consul/serf.md)），`JoinWAN` 加入跨 WAN gossip 环：

```go
// JoinWAN is used to have Consul join the cross-WAN Consul ring
// The target address should be another node listening on the
// Serf WAN address
func (s *Server) JoinWAN(addrs []string) (int, error) {
	if s.serfWAN == nil {
		return 0, ErrWANFederationDisabled
	}

	if err := s.enterpriseValidateJoinWAN(); err != nil {
		return 0, err
	}

	return s.serfWAN.Join(addrs, true)
}
```

`agent/consul/server.go`

**Cluster peering**（2.x 增强）的握手是"establishment secret 交换"：发起端 `GenerateToken` 生成 peering token → 对端 `Establish` 解码校验 → `exchangeSecret` 用 TLS dial + 地址环重试完成交换，之后由订阅流（`peerstream` gRPC 服务）复制 catalog/health/CA。地址环优先 mesh gateway：

```go
	if gatewayRing != nil {
		// The ordering is important here. We always want to start with the mesh gateway
		// addresses and fallback to the remote addresses, so we append the server addresses
		// in newRing to gatewayRing.
		compositeRing := ring.New(gatewayRing.Len() + newRing.Len())
```

`agent/consul/peering_backend.go`

TLS 材料由 connect CA 体系提供（SAN 为 `connect.PeeringServerSAN(...)`）。服务端流有心跳保活（15s 心跳 / 2m 超时）：

```go
const (
	defaultOutgoingHeartbeatInterval = 15 * time.Second
	defaultIncomingHeartbeatTimeout  = 2 * time.Minute
)
```

`agent/grpc-external/services/peerstream/server.go`

## Links

- [Consul（枢纽与架构）](/docs/CS/Framework/consul/Consul.md)
- [Mesh（服务网格）](/docs/CS/Framework/consul/mesh.md)
- [Serf（WAN 池与 flooder）](/docs/CS/Framework/consul/serf.md)
- [Cluster（集群运维）](/docs/CS/Framework/consul/cluster.md)
- [Security（TLS 与 ACL）](/docs/CS/Framework/consul/security.md)

## References

1. [Consul Gateways](https://developer.hashicorp.com/consul/docs/connect/gateways)
2. [Cluster Peering](https://developer.hashicorp.com/consul/docs/connect/cluster-peering)
3. [WAN Federation via Mesh Gateways](https://developer.hashicorp.com/consul/docs/connect/gateways/mesh-gateway#wan-federation-via-mesh-gateways)
4. [hashicorp/consul v2.1.0 gateway_locator.go](https://github.com/hashicorp/consul/blob/v2.1.0/agent/consul/gateway_locator.go)
