## Introduction

Consul 的安全体系由三层组成：**ACL**（授权，零信任默认收口）、**传输 TLS**（RPC / gossip / 网格 mTLS）、**Connect CA**（服务网格证书，见 [Mesh](/docs/CS/Framework/consul/mesh.md)）。与 etcd 的 RBAC + mTLS（见 [etcd security](/docs/CS/Framework/etcd/security.md)）相比，Consul 的 ACL 体系最贴近"零信任网络"的默认收口，但**默认并不启用**——需要显式打开并按最小权限配置。本文源码核自 **v2.1.0**。

> [!WARNING]
> 关键事实：Consul 的 `acl.default_policy` **出厂默认是 `allow`**，且 ACL **默认不启用**（`acl.enabled=false`）。生产环境务必设 `enabled=true` + `default_policy="deny"`，且 `primary_datacenter` 必须指定。

> [!NOTE]
> 2.x 纠偏：1.x 的 `ACL.TokenResolve` RPC **已不存在**。token 解析统一走 `ACLResolver`（`agent/consul/acl.go`）→ 缓存/singleflight → `ACL.TokenRead` RPC。

## ACL: Resolver Pipeline

token 解析是三层瀑布：**本地解析 → agent 缓存 → RPC 到权威 DC**，RPC 失败按 `down_policy` 处理：

```go
func (r *ACLResolver) resolveIdentityFromToken(token string) (structs.ACLIdentity, error) {
	// Attempt to resolve locally first (local results are not cached)
	if done, identity, err := r.backend.ResolveIdentityFromToken(token); done {
		return identity, err
	}

	// Check the cache before making any RPC requests
	cacheEntry := r.cache.GetIdentityWithSecretToken(token)
	if cacheEntry != nil && cacheEntry.Age() <= r.config.ACLTokenTTL {
		metrics.IncrCounter([]string{"acl", "token", "cache_hit"}, 1)
		return cacheEntry.Identity, nil
	}

	metrics.IncrCounter([]string{"acl", "token", "cache_miss"}, 1)

	// Background a RPC request and wait on it if we must
	waitChan := r.identityGroup.DoChan(token, func() (interface{}, error) {
		identity, err := r.fetchAndCacheIdentityFromToken(token, cacheEntry)
		return identity, err
	})
	...
```

`agent/consul/acl.go`

RPC 失败时的降级（`extend-cache` 默认）：

```go
	req := structs.ACLTokenGetRequest{
		Datacenter:  r.backend.ACLDatacenter(),
		TokenID:     token,
		TokenIDType: structs.ACLTokenSecret,
		QueryOptions: structs.QueryOptions{
			Token:      token,
			AllowStale: true,
		},
	}

	var resp structs.ACLTokenResponse
	err := r.backend.RPC(context.Background(), "ACL.TokenRead", &req, &resp)
	...
	if cached != nil && (r.config.ACLDownPolicy == "extend-cache" || r.config.ACLDownPolicy == "async-cache") {
		// extend the cache
		r.cache.PutIdentityWithSecretToken(token, cached.Identity)
		return cached.Identity, nil
	}
```

`agent/consul/acl.go`

分层实现：client agent 无本地解析（`acl_client.go` 的 `ResolveIdentityFromToken` 直接返回 false，全部走 RPC）；server 在权威 DC 直接读 FSM state，非权威 DC 靠 **ACL 复制**（`acl_replication.go` 的 `replicateACLTokens/Policies/Roles`，需 `acl.token_replication=true`）把 token 拉到本地：

```go
func (s *Server) ResolveIdentityFromToken(token string) (bool, structs.ACLIdentity, error) {
	// only allow remote RPC resolution when token replication is off and
	// when not in the ACL datacenter
	if !s.InPrimaryDatacenter() && !s.config.ACLTokenReplication {
		return false, nil, nil
	}
	index, aclToken, err := s.fsm.State().ACLTokenGetBySecret(nil, token, nil)
```

`agent/consul/acl_server.go`

## Policy Evaluation: Default Deny Semantics

policy 求值在 `acl/policy_authorizer.go`：**显式 deny 一票否决；无匹配规则时看 `Default`，而 Default 是否放行由 `default_policy` 决定**：

```go
func defaultIsAllow(decision EnforcementDecision) EnforcementDecision {
	switch decision {
	case Allow, Default:
		return Allow
	default:
		return Deny
	}
}
```

```go
	case AccessDeny:
		// explicit denial - do not recurse
		return Deny
```

`acl/policy_authorizer.go`

（`default_policy="deny"` 时用相反的判定——`Default` 落 Deny。）授权对象是 policy / role / token / auth-method 四件套；`ACL.Login` 端点用 AuthMethod validator 校验 bearer token（K8s/JWT 等）后签发短期 token：

```go
	authMethod, validator, err := a.srv.loadAuthMethod(args.Auth.AuthMethod, &args.Auth.EnterpriseMeta)
	if err != nil {
		return err
	}

	verifiedIdentity, err := validator.ValidateLogin(context.Background(), args.Auth.BearerToken)
	...
	token, err := a.srv.aclLogin().TokenForVerifiedIdentity(verifiedIdentity, authMethod, name, description)
```

`agent/consul/acl_endpoint.go`

agent 端 token/policy 缓存 TTL 默认 **30s**；server 端缓存容量（`acl_server.go`）：identities 10240、parsed policies 512、authorizers 1024。2.x 还给 Envoy 的 escape-hatch 通道加了独立的 `mesh:write` 权限校验（`agent/acl.go`）。

## Transport TLS

传输层 TLS 集中在 `tlsutil/config.go` 的 `Configurator`，按三类协议分别加载配置：内部 RPC、HTTPS、gRPC。TLS 版本映射里 `auto` = TLS1.2（低于 1.2 需显式配置）：

```go
// goTLSVersions maps types.TLSVersion to the Go internal value
var goTLSVersions = map[types.TLSVersion]uint16{
	types.TLSVersionAuto: tls.VersionTLS12,
	types.TLSv1_0:        tls.VersionTLS10,
	types.TLSv1_1:        tls.VersionTLS11,
	types.TLSv1_2:        tls.VersionTLS12,
	types.TLSv1_3:        tls.VersionTLS13,
}
```

`tlsutil/config.go`

三个域各有开关：`verify_incoming`（server 校验客户端证书）、`verify_outgoing`（RPC 出站校验）、`verify_server_hostname`（校验 server 名字防 spoof）。开启 `verify_outgoing + verify_server_hostname` 即实现 RPC 全链路双向认证。

## Auto-Encrypt

`auto_encrypt.allow_tls` 开启后，client 无需手工分发证书：生成 CSR → 向 gossip 已知的 server 发 `AutoEncrypt.Sign` RPC → 拿回 leaf 证书 + CA 根 + `VerifyServerHostname`，之后自动轮转。服务端实现复用了 ConnectCA 端点：

```go
	// This is the ConnectCA endpoint which is reused here because it is
	// exactly what is needed.
	c := ConnectCA{srv: a.srv}

	rootsArgs := structs.DCSpecificRequest{Datacenter: args.Datacenter}
	roots := structs.IndexedCARoots{}
	err := c.Roots(&rootsArgs, &roots)
	if err != nil {
		return err
	}

	cert := structs.IssuedCert{}
	err = c.Sign(args, &cert)
	...
	reply.IssuedCert = cert
	reply.ConnectCARoots = roots
	reply.ManualCARoots = a.srv.tlsConfigurator.ManualCAPems()
	reply.VerifyServerHostname = a.srv.tlsConfigurator.VerifyServerHostname()
```

`agent/consul/auto_encrypt_endpoint.go`

client 侧流程（`agent/auto-config/auto_encrypt.go`，2.x 目录名是 `auto-config` 而非旧资料的 `auto_encrypt`）：

```go
func (ac *AutoConfig) autoEncryptInitialCerts(ctx context.Context) (*structs.SignedResponse, error) {
	// generate a CSR
	csr, key, err := ac.generateCSR()
	...
			ac.logger.Debug("making AutoEncrypt.Sign RPC", "addr", addr.String())
			err = ac.acConfig.DirectRPC.RPC(ac.config.Datacenter, ac.config.NodeName, &addr, "AutoEncrypt.Sign", &request, &resp)
```

`agent/auto-config/auto_encrypt.go`

## Gossip Encryption

gossip 走 memberlist 对称 keyring（与 TLS 独立），LAN/WAN 各一份密钥文件（`serf/local.keyring` / `serf/remote.keyring`），支持在线轮换多钥。建立与轮换细节见 [Serf](/docs/CS/Framework/consul/serf.md)。生产推荐的完整组合：`encrypt`（gossip keyring）+ `verify_outgoing`+`verify_server_hostname`（RPC TLS）+ `auto_encrypt`（client 证书自动分发）+ ACL deny 默认。

## Comparison with etcd / ZooKeeper

| 维度 | Consul | etcd | ZooKeeper |
| :--- | :--- | :--- | :--- |
| 授权模型 | policy/role/token + 默认策略可切 | RBAC（user/role） | SASL + ACL（digest/ip） |
| 默认状态 | 不启用，default=allow | 认证可选 | 认证可选 |
| Token 生命周期 | TTL + auth-method 短期 token | 静态 | 静态 |
| 传输加密 | TLS 三域 + gossip keyring | TLS | TLS |
| 证书自动分发 | auto-encrypt + Connect CA | 无 | 无 |
| 服务身份 | SPIFFE（网格） | 无 | 无 |

## Links

- [Consul（枢纽与架构）](/docs/CS/Framework/consul/Consul.md)
- [Mesh（服务网格与 Connect CA）](/docs/CS/Framework/consul/mesh.md)
- [Serf（gossip keyring）](/docs/CS/Framework/consul/serf.md)
- [配置参考（acl 段参数）](/docs/CS/Framework/consul/config.md)
- [etcd security](/docs/CS/Framework/etcd/security.md)

## References

1. [Consul ACL System](https://developer.hashicorp.com/consul/docs/security/acl/acl-system)
2. [Consul Encryption](https://developer.hashicorp.com/consul/docs/security/encryption)
3. [hashicorp/consul v2.1.0 acl.go](https://github.com/hashicorp/consul/blob/v2.1.0/agent/consul/acl.go)
4. [Auto-encrypt TLS](https://developer.hashicorp.com/consul/docs/secure/auto_encrypt_tls)
