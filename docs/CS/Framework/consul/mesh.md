## Introduction

**Consul service mesh**（早期叫 Connect）是 Consul 相对 etcd / ZooKeeper / Nacos 的差异化王牌：把"服务间 mTLS + 授权"做成开箱能力，业务代码零改造。开启网格后，每个服务旁部署一个 **Envoy sidecar**，由 Consul 通过 gRPC xDS 下发配置；服务间流量强制双向 TLS + 意图校验。本文源码核自 **v2.1.0**。

> [!WARNING]
> 2.x 关键变化：① xDS 的 **state-of-the-world ADS 已废弃**——`StreamAggregatedResources` 硬性返回 `not implemented`，只剩 **delta xDS**（`DeltaAggregatedResources`）。② Connect CA 的协调从 1.x 单体 `reconcileCA` 循环重构为 **`CAManager` 显式状态机** + 后台 routine。③ transparent proxy 的流量重定向从 iptables 迁移到 **nftables**。

## Sidecar and delta xDS

xDS server 注册在 agent 的 external gRPC server（8502；server 模式另有 8503 TLS）：

```go
	a.xdsServer = xds.NewServer(
		a.config.NodeName,
		a.logger.Named(logging.Envoy),
		proxyWatcher,
		func(id string) (acl.Authorizer, error) {
			return a.delegate.ResolveTokenAndDefaultMeta(id, nil, nil)
		},
		a,
	)
	a.xdsServer.Register(a.externalGRPCServer)
```

`agent/agent.go`

```go
// StreamAggregatedResources implements
// envoy_discovery_v3.AggregatedDiscoveryServiceServer. This is the ADS endpoint which is
// the only xDS API we directly support for now.
//
// Deprecated: use DeltaAggregatedResources instead
func (s *Server) StreamAggregatedResources(stream ADSStream) error {
	return errors.New("not implemented")
}

// Register the XDS server handlers to the given gRPC server.
func (s *Server) Register(srv *grpc.Server) {
	envoy_discovery_v3.RegisterAggregatedDiscoveryServiceServer(srv, s)
}
```

`agent/xds/server.go`

push 触发来自 **proxycfg watch**：agent 维护每个 sidecar 的 `ConfigSnapshot`，快照变化即经 `stateCh` 触发 delta xDS 重新生成资源。五种资源类型各自处理"允许空"的语义（listener/route/cluster 可空，endpoint/secret 不可）：

```go
	handlers := map[string]*xDSDeltaType{
		xdscommon.ListenerType: newDeltaType(logger, stream, xdscommon.ListenerType, func() bool {
			return snapshot.AllowEmptyListeners()
		}),
		xdscommon.RouteType: newDeltaType(logger, stream, xdscommon.RouteType, func() bool {
			return snapshot.AllowEmptyRoutes()
		}),
		xdscommon.ClusterType: newDeltaType(logger, stream, xdscommon.ClusterType, func() bool {
			return snapshot.AllowEmptyClusters()
		}),
		xdscommon.EndpointType: newDeltaType(logger, stream, xdscommon.EndpointType, nil),
		xdscommon.SecretType:   newDeltaType(logger, stream, xdscommon.SecretType, nil),
	}
```

`agent/xds/delta.go`

`envoyextensions/` 是独立 Go module（Envoy 扩展框架 `extensioncommon` + 资源索引 `xdscommon`），xDS 包导入它做 `IndexResources` 与 `DetermineSupportedProxyFeatures`。2.1.0 还新增了 api-gateway 冷启动 **bootstrap gate**（默认 30s，`CONSUL_XDS_APIGATEWAY_BOOTSTRAP_GATE_TIMEOUT` 可覆盖）与 failover guard（`CONSUL_XDS_DISABLE_APIGATEWAY_FAILOVER_GUARD`）。

业务无需改代码：透明代理模式下出站流量由 nftables 规则重定向到 sidecar（见下文）；sidecar 证书从 Connect CA 自动获取并轮转，服务身份是 SPIFFE 风格 `spiffe://<trust-domain>/ns/<ns>/svc/<svc>`。

## mTLS and Connect CA

证书体系：RootCA（默认 TTL ~10 年）→ IntermediateCA（~1 年，secondary DC 向 primary 请求签发）→ leaf 证书（默认 **72h**，agent 自动轮转）。默认值：

```go
const (
	DefaultLeafCertTTL         = "72h"
	DefaultIntermediateCertTTL = "8760h"  // ~ 1 year = 365 * 24h
	DefaultRootCertTTL         = "87600h" // ~ 10 years = 365 * 24h * 10
)
```

`agent/structs/connect_ca.go`

2.x 的 CA 协调是 `CAManager` 显式状态机：

```go
const (
	caStateUninitialized     caState = "UNINITIALIZED"
	caStateInitializing      caState = "INITIALIZING"
	caStateInitialized       caState = "INITIALIZED"
	caStateRenewIntermediate caState = "RENEWING"
	caStateReconfig          caState = "RECONFIGURING"
)
```

`agent/consul/leader_connect_ca.go`

```go
func (c *CAManager) Start(ctx context.Context) {
	// Attempt to initialize the Connect CA now. This will
	// happen during leader establishment and it would be great
	// if the CA was ready to go once that process was finished.
	if err := c.Initialize(); err != nil {
		c.logger.Error("Failed to initialize Connect CA", "error", err)
		c.leaderRoutineManager.Start(ctx, backgroundCAInitializationRoutineName, c.backgroundCAInitialization)
	} else {
		c.startPostInitializeRoutines(ctx)
	}
}
```

`agent/consul/leader_connect_ca.go`

初始化失败不再阻塞 leader（转入后台重试 routine）；secondary DC 的 routine 有两个：`secondaryCARootWatch`（跟随 primary 根）与 `runRenewIntermediate`（中间证书续期）。secondary 请求签名走跨 DC RPC `ConnectCA.SignIntermediate`，携带本地 provider 生成的 CSR：

```go
	csr, opaque, err := provider.GenerateIntermediateCSR()
	...
	if err := c.delegate.forwardDC("ConnectCA.SignIntermediate", c.serverConf.PrimaryDatacenter, c.delegate.generateCASignRequest(csr), &intermediatePEM); err != nil {
```

`agent/consul/leader_connect_ca.go`

CA 状态（`CARoot` 的 `RootCert` + `IntermediateCerts []string` 字段）存在 state store 的 `connect-ca-*` 表里，约束"**恰好一个 active CA**"。CA provider 默认 consul 内置，可换 Vault。

## Intentions

服务间授权以 **`service-intentions` config entry** 存储（2.x 文件名 `config_entry_intentions.go`；legacy `Intention` 结构保留 SourceNS/SourceName/DestinationNS/DestinationName + Action）。

**默认 deny** 的判定不是一个写死的常量，而是"继承 ACL 默认策略、可被 agent 的 `default_intentionPolicy` 覆盖"：

```go
func DefaultIntentionAllow(authz acl.Authorizer, defaultIntentionPolicy string) bool {
	// The default intention policy inherits from ACLs but
	// is overridden by the agent's DefaultIntentionPolicy.
	//nolint:staticcheck
	defaultAllow := authz.IntentionDefaultAllow(nil) == acl.Allow
	if defaultIntentionPolicy != "" {
		defaultAllow = defaultIntentionPolicy == structs.IntentionDefaultPolicyAllow
	}
	return defaultAllow
}
```

`agent/consul/util.go`

决策计算走 state store 的 `IntentionDecision`（匹配 source/destination + 通配符 + 权限）。数据面上 deny 的表现是**不生成 cluster/listener**（隐式黑洞）而非显式 REJECT——排查"连不通"时要先查 intention 是否缺配。

## Transparent Proxy: iptables → nftables

2.x 的透明代理重定向已从 iptables 迁移到 **nftables**（`consul connect redirect-traffic`），用 inet family 一套规则同时覆盖 IPv4/IPv6，不再需要 ip6tables 二次配置：

```go
	// ProxyInboundRedirectChain is the chain to redirect inbound traffic to the proxy.
	ProxyInboundRedirectChain = "CONSUL_PROXY_IN_REDIRECT"

	// ProxyOutputRedirectChain is the chain to redirect outbound traffic to the proxy
	ProxyOutputRedirectChain = "CONSUL_PROXY_REDIRECT"

	// DNSChain is the chain to redirect outbound DNS traffic to Consul DNS.
	DNSChain = "CONSUL_DNS_REDIRECT"
```

`sdk/nftables/nftables.go`

```go
// Setup will set up nftables interception and redirection rules
// based on the configuration provided in cfg.
// The inet address family is used so that a single rule set covers both
// IPv4 and IPv6 traffic — no separate ip6tables pass is required.
func Setup(cfg Config, dualStack bool) error {
```

`sdk/nftables/nftables.go`

出站重定向端口默认 15001（`DefaultTProxyOutboundPort`）。2.x 的 mesh config entry 还新增了 cluster 级 TPROXY 选项（`TransparentProxyMeshConfig`）。

## Config Entries

网格的行为全部由 config entry 声明：`service-defaults`（协议）、`service-resolver`（子集/failover）、`service-router`（L7 路由）、`service-splitter`（流量切分）、`proxy-defaults`（Envoy 全局配置）、`mesh`、`ingress-gateway` / `terminating-gateway`（2.x 已合并进单文件 `config_entry_gateways.go`，terminating gateway 新增凭据注入 `CredentialInjection`）。这些 entry 存在 state store、经 Raft 复制，agent 侧由 `config_entry_backend` 订阅增量并喂给 proxycfg。

## Comparison with Other Meshes

| 维度 | Consul Mesh | Istio | Nacos |
| :--- | :--- | :--- | :--- |
| 发现底座 | 自带 catalog（同源） | 依赖外部（K8s/Istiod） | 无 mesh |
| CA | Connect CA（内置/Vault） | istiod 自签 | 无 |
| 授权 | intentions（L4/L7） | AuthorizationPolicy | 无 |
| xDS | delta ADS（SOTW 已废弃） | SOTW + delta | 无 |
| 控制面依赖 | 无（agent 即控制面） | istiod 独立部署 | 无 |

Consul mesh 的独特优势是**控制面与注册中心同源**——不需要额外的发现组件；代价是仅 Consul 目录内的服务可入网格，跨系统服务要用 terminating gateway 桥接。

## Links

- [Consul（枢纽与架构）](/docs/CS/Framework/consul/Consul.md)
- [Security（ACL 与传输 TLS）](/docs/CS/Framework/consul/security.md)
- [Gateway（网关与联邦）](/docs/CS/Framework/consul/gateway.md)
- [Discovery（服务发现）](/docs/CS/Framework/consul/discovery.md)
- [Raft（共识）](/docs/CS/Framework/consul/raft.md)
- [Istio](/docs/CS/Framework/Istio/Istio.md)

## References

1. [Consul Service Mesh](https://developer.hashicorp.com/consul/docs/connect)
2. [Envoy xDS delta protocol](https://www.envoyproxy.io/docs/envoy/latest/api-docs/xds_protocol)
3. [hashicorp/consul v2.1.0 xds/delta.go](https://github.com/hashicorp/consul/blob/v2.1.0/agent/xds/delta.go)
4. [Intentions](https://developer.hashicorp.com/consul/docs/connect/intentions)
