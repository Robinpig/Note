# etcd Security: TLS, Authentication and RBAC

## Introduction

etcd 的"安全"不是一块开关，而是**四层彼此独立的机制**，混为一谈是排障时最常见的起点：

| 层 | 回答的问题 | etcd 的实现 | 默认状态 |
| :--- | :--- | :--- | :--- |
| 传输安全 | 数据在网上传输时会不会被窃听 / 篡改 | TLS / mTLS | **关闭** |
| 认证（authn） | 你是谁 | 密码 + Token，或客户端证书 CN | **关闭** |
| 授权（authz） | 你能碰哪些 key | RBAC（用户 / 角色 / 区间权限） | 随认证一起开启 |
| 静态加密 | 磁盘上的数据有没有加密 | **etcd 不提供** | — |

四层要分开看的原因很实际：`auth enable` 之后 `etcdctl get` 需要 `--user`，但 `curl http://127.0.0.1:2379/metrics` 依然畅通——`/metrics` 与 `/health` 走独立的 HTTP handler，**不受 v3 RBAC 保护**。反过来，打开 TLS 也不代表有认证（`--auto-tls` 只加密不验身份）。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下片段均取自该 tag。3.7 没有引入新的认证机制，但授权路径有 `rangePermCache`（见下文），且 feature gate 里留下一条"注释说要删却没删"的活化石。

> [!WARNING]
> etcd 的 TLS 只保护**传输中的**数据，**不加密磁盘上的 key/value**。静态加密要靠客户端自己加解密，或用底层存储的加密能力（如 dm-crypt / LUKS）。以为"用了 TLS 就安全了"是选型时最常见的边界误判。

还有一个反直觉点：**鉴权（auth）本身是走 Raft 共识的写操作**。用户、角色、权限必须全集群一致，否则同一请求在不同节点会得到不同裁决。因此 `user add` / `role grant-permission` 都是提案，要等多数派确认；鉴权配置本身依赖 quorum，集群失去多数派时连改权限都做不到。

## Control Plane and Data Plane

鉴权体系由**控制面**和**数据面**组成。

**控制面**负责鉴权元数据的一致性：AuthServer 收到请求后，通过 [Raft](/docs/CS/Framework/etcd/raft.md) 同步，日志条目被半数以上节点确认后，apply 模块经 AuthStore 把规则写入 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 的 `auth` / `authUsers` / `authRoles` bucket。

**数据面**由认证（authn）与授权（authz）组成：认证检查 client 身份是否合法、防止匿名访问；授权检查该身份是否有权操作请求的数据路径。

## Authentication

认证检查 client 身份、防止匿名用户访问。etcd 实现了两种机制：**密码认证**和**证书认证**。认证通过后为提升密码认证性能会分配一个 Token（类似门票），client 后续请求携带它，server 无需每次跑一遍 bcrypt。

### Password Storage: bcrypt + salt + cost

密码认证有两大难点——**保障密码安全性**与**提升认证性能**天然冲突（安全性靠慢哈希，性能要求快）。etcd 的做法是融合三者：底层用 **bcrypt**（基于 Blowfish 的慢哈希，刻意耗 CPU）、每个用户独立的随机 **salt**、可配置的迭代 **cost**，连同算法版本拼成一个字符串存储。`UserAdd` 与 `UserPasswd` 共用同一段哈希逻辑：

```go
// server/etcdserver/v3_server.go
		hashedPassword, err := bcrypt.GenerateFromPassword([]byte(r.Password), s.authStore.BcryptCost())
```

cost 由 `--bcrypt-cost` 指定，默认 `bcrypt.DefaultCost`，有效范围受 `bcrypt.MinCost` / `bcrypt.MaxCost` 约束。调高它会线性拉长每次 `user add` / `user passwd` 与登录校验的耗时——这是用算力换抗爆破能力。

开启鉴权前必须先创建 `root` 账号（拥有最高读写权限，`root` 角色可授予任意用户）：

```shell
$ etcdctl user add root:root
User root created
$ etcdctl --user root:root auth enable
Authentication Enabled
```

> [!WARNING]
> `auth enable` **不接受任何参数**——身份必须用 `--user` 这个**全局 flag** 传，写成 `etcdctl auth enable --user root:root` 会被 cobra 当成位置参数而报错。`--user` 接受 `user:password`、只给 `user`（交互式提示）、配合独立 `--password` 三种形态，另有隐藏的 `--auth-jwt-token` 直接携带 JWT。

鉴权模块用 bcrypt 基于明文密码、随机 salt、cost 迭代算出 hash，把**算法版本 + salt + cost + hash** 拼成字符串，以用户名为 key 存入 boltdb 的 `authUsers` bucket。访问时先调 `Authenticate` 接口：按用户名取出加密密码，hash 里含算法版本 / salt / cost，据此用请求明文算出最终 hash，一致则通过。

### Token Lifecycle

每个 Token 都有 TTL，过期后 client 需再次验证身份——这缩小了数据泄露的时间窗口。server 定时检查过期 token 并从内存 map 删除，清理由 `simpleTokenTTLKeeper` 负责，**扫描精度 1 秒**：

```go
// server/auth/simple_token.go
	simpleTokenTTLResolution = 1 * time.Second
	// ...
	tokenTicker := time.NewTicker(simpleTokenTTLResolution)
```

所以实际过期时刻可能比 TTL 晚至多 1 秒。

Token 生成由 `TokenProvider` 负责，`--auth-token` 选择实现（默认 `simple`）：

| 维度 | Simple Token | JWT |
| :--- | :--- | :--- |
| 是否有状态 | **有**（内存 map 存 token → 用户） | **无**（自包含签名） |
| 默认 TTL | 300 秒（`--auth-token-ttl`） | 5 分钟（options 的 `DefaultTTL`） |
| 可描述性 | 差，client 读不出任何信息 | 含 `username` / `revision` / `exp` claim |
| 抗伪造 | 弱（启动即 warn "not cryptographically signed"） | 强（非对称签名） |
| 失效方式 | `disable()` 遍历 map 全部作废 | 只能等 TTL 自然过期 |
| 官方定位 | 开发 / 测试环境 | 对安全要求高的环境 |

> [!TIP]
> Simple Token 字符串本身**未含任何有价值信息**——没有签发时间、过期时间、用户名。client 无法提前得知 Token 何时失效，只能被动等请求返回 `Unauthenticated` 后重新认证。这是它只被建议在开发测试环境使用的核心原因。

JWT 签出的 token 携带三个 claim，其中 `revision` 是**兜底的重放防护**：

```go
// server/auth/jwt.go
			"username": username,
			"revision": revision,
			"exp":      ...,
```

`isOpPermitted` 会拒绝 `authInfo.Revision` 小于本节点 auth revision 的请求（返回 `ErrAuthOldRevision`）。这个字段对 simple token 同样存在，只是 JWT 里由服务端签入、simple token 里由内存 map 记录。

`--auth-token-ttl` 只作用于 simple token；JWT 走自己的 `ttl` 选项：

```shell
--auth-token="jwt,priv-key=/path/to/key.pem,sign-method=RS256,ttl=10m"
```

可识别的选项只有四个：`sign-method`、`pub-key`、`priv-key`、`ttl`：

```go
// server/auth/options.go
	optSignMethod = "sign-method"
	optPublicKey  = "pub-key"
	optPrivateKey = "priv-key"
	optTTL        = "ttl"
```

> [!WARNING]
> 写错的键**不会报错**，只会打一条 `unknown JWT options` 的 warn 然后被忽略——配置拼错了却静默生效，是这条路径上最容易踩的坑。键名必须是 `priv-key`，不是 `private-key`。

### Certificate Identity (CN Authentication)

除密码外，还有一条**不依赖密码**的认证路径：从客户端证书的 Common Name 取用户名。

```go
// server/auth/store.go
func (as *authStore) AuthInfoFromTLS(ctx context.Context) (ai *AuthInfo) {
	peer, ok := peer.FromContext(ctx)
	if !ok || peer == nil || peer.AuthInfo == nil {
		return nil
	}

	tlsInfo := peer.AuthInfo.(credentials.TLSInfo)
	for _, chains := range tlsInfo.State.VerifiedChains {
		if len(chains) < 1 {
			continue
		}
		ai = &AuthInfo{
			Username: chains[0].Subject.CommonName,
			Revision: as.Revision(),
		}
		// ... 省略 gateway 识别与日志
	}
	return ai
}
```

前提是服务端开了 `--client-cert-auth` 且客户端**同时**不提供用户名密码——两者都提供时密码认证优先。`VerifiedChains` 是 `crypto/tls` 在**验证通过后**才填的，所以没有可信 CA 签发就不会有身份，这也是 CN 认证天然依附于 mTLS 的原因。

> [!WARNING]
> CN 认证**无法配合 gRPC-proxy 与 gRPC-gateway 使用**。proxy 在客户端侧终结 TLS，所有下游客户端共用 proxy 那张证书，服务端看到的 CN 永远是 proxy 的。etcd 有专门防护：请求头带 `grpcgateway-accept` 时，CN 直接被丢弃并打 warn——源码里就是上面片段省略的那段 `md["grpcgateway-accept"]` 检查；grpc-proxy 则在证书 CN 非空时直接报错退出。

## Authorization

开启鉴权后，put 请求应用到状态机前还会对发出请求的用户做权限检查。etcd 实现的是 **RBAC**：为每个用户分配角色，为每个角色授予最小化权限。

```shell
$ etcdctl role add app
$ etcdctl role grant-permission app read /foo/          # 前缀读
$ etcdctl role grant-permission app --prefix=true readwrite /pub/
$ etcdctl role grant-permission app readwrite key1 key5  # 区间 [key1, key5)
$ etcdctl user grant-role alice app
```

### Interval Tree

一个用户可能有成百上千条权限。etcd 为提升检查性能引入**区间树**：把角色所有 key 权限合并成两棵区间树（读一棵、写一棵），检查时只需判断请求的 key 落在哪个已授权区间内。`getMergedPerms` 遍历用户的每个角色、每条 `KeyPermission`，按 `PermType` 插入对应的树：

```go
// server/auth/range_perm_cache.go
func getMergedPerms(tx UnsafeAuthReader, userName string) *unifiedRangePermissions {
	user := tx.UnsafeGetUser(userName)
	if user == nil {
		return nil
	}

	readPerms := adt.NewIntervalTree()
	writePerms := adt.NewIntervalTree()

	for _, roleName := range user.Roles {
		role := tx.UnsafeGetRole(roleName)
		if role == nil {
			continue
		}

		for _, perm := range role.KeyPermission {
			// ... 省略区间构造，按 PermType 插入 readPerms / writePerms
		}
	}

	return &unifiedRangePermissions{readPerms: readPerms, writePerms: writePerms}
}
```

查询侧按请求形态分两路：`rangeEnd` 为空走 `checkKeyPoint`（点查询，`Intersects`），否则走 `checkKeyInterval`（区间查询，`Contains`）。两者都是 O(logN)——**这就是引入区间树的全部理由**。

权限区间的边界有一套不变量约束（源码注释里的 rule a1~b3），最反直觉的一条是：**开区间用 `rangeEnd = []byte{0x00}` 表示**，而不是留空。

```go
// server/auth/range_perm_cache.go
func isOpenEnded(rangeEnd []byte) bool { // check rule b3
	return len(rangeEnd) == 1 && rangeEnd[0] == 0
}
```

因为 `BytesAffineComparable` 用 `[]byte{}`（空串）当最大元素，`(X, []byte{})` 在语义上是"非法区间"而非"到顶区间"，所以必须用 `0x00` 表达"一直到最大 key"。`--prefix=true` 生成的就是这种开区间权限。

### rangePermCache: per-user Interval Tree Cache

仅有区间树还不够。`isOpPermitted` 是**每个请求**都走的热路径，要先拿用户对象、遍历角色列表、再查树——源码里留着 TODO 承认它很贵。3.7 的答案是 `rangePermCache`：**在鉴权配置变更时，为每个用户预先合并好区间树**（读 + 写各一棵），查询时只查缓存、不遍历角色。

```go
// server/auth/range_perm_cache.go
func (as *authStore) isRangeOpPermitted(userName string, key, rangeEnd []byte, permtyp authpb.Permission_Type) bool {
	// assumption: tx is Lock()ed
	as.rangePermCacheMu.RLock()
	defer as.rangePermCacheMu.RUnlock()

	rangePerm, ok := as.rangePermCache[userName]
	if !ok {
		as.lg.Error("user doesn't exist", zap.String("user-name", userName))
		return false
	}
	if len(rangeEnd) == 0 {
		return checkKeyPoint(as.lg, rangePerm, key, permtyp)
	}
	return checkKeyInterval(as.lg, rangePerm, key, rangeEnd, permtyp)
}
```

注意锁的粒度：查询路径只拿 **RLock**，且**连 boltdb 事务都不开**——对比 `isOpPermitted` 里的 `tx := as.be.ReadTx(); tx.RLock()`，缓存把整条 boltdb 读取链路从热路径上摘掉了。这才是它真正的收益。

代价写在源码注释里，非常直白：

```go
// server/auth/range_perm_cache.go
func (as *authStore) refreshRangePermCache(tx UnsafeAuthReader) {
	// Note that every authentication configuration update calls this method and it invalidates the entire
	// rangePermCache and reconstruct it based on information of users and roles stored in the backend.
	// This can be a costly operation.
	as.rangePermCacheMu.Lock()
	defer as.rangePermCacheMu.Unlock()
	// ... 全量重建
}
```

**全量失效 + 全量重建**，没有增量更新。因此读多写少的场景几乎白嫖性能收益；频繁变更角色权限的管理面操作，每次变更都触发 O(用户数 × 权限数) 重建，期间写锁阻塞所有授权查询。`AuthEnable` / `UserAdd` / `UserDelete` / `RoleAdd` / `RoleDelete` / `RoleGrantPermission` 等**所有**改动鉴权配置的入口都会触发它——包括 `user passwd` 这种看似无关的操作。

> [!NOTE]
> 排查"权限改了但不生效"或"改了权限后 etcd 卡住"时，第一反应应当是 `rangePermCache` 的重建，而不是怀疑 Raft 同步。开启 debug 日志后能看到 `Refreshing rangePermCache` 这条日志的出现频率。

缓存之外的短路只有一条：**`root` 角色直接放行**，不查任何树。反过来，缓存里查不到用户时打 `user doesn't exist` 并返回 `false`——**fail-closed**，鉴权出问题时 etcd 选择拒绝而不是放行。

### Auth-Related Flags and Revision

| flag | 默认值 | 说明 |
| :--- | :--- | :--- |
| `--auth-token` | `simple` | `simple` 或 `jwt`，JWT 可带逗号分隔选项 |
| `--auth-token-ttl` | `300`（秒） | **仅作用于 simple token** |
| `--bcrypt-cost` | `bcrypt.DefaultCost` | 密码哈希迭代成本 |

鉴权配置带一个独立的 **auth revision**，与 MVCC 数据 revision 不是一回事。它在请求校验时充当**新旧裁决的判据**：请求携带的 `authInfo.Revision` 是签发 Token 那一刻的 auth revision；若之后有人改了权限，各节点 apply 完新配置后 auth revision 前进，旧 Token 带着老 revision 就会被拒（`ErrAuthOldRevision`，对外是 `InvalidArgument`）。

```go
// server/auth/store.go
	rev := as.Revision()
	if revision < rev {
		as.lg.Warn("request auth revision is less than current node auth revision",
			zap.Uint64("current node auth revision", rev),
			zap.Uint64("request auth revision", revision),
			zap.ByteString("request key", key),
			zap.Error(ErrAuthOldRevision))
		return ErrAuthOldRevision
	}
```

> [!NOTE]
> 这解释了一个常见困惑：**改了角色权限后，客户端报 `revision of auth store is old` 而不是 `permission denied`**。这不是 bug，是设计——权限变更让所有未重新认证的旧 Token 立刻失效，属于 fail-closed。客户端应重新 `Authenticate` 拿新 Token，而不是重试。该 revision 也作为不稳定指标 `etcd_debugging_auth_revision` 暴露。

## 3.7 Impact of Feature Gate on Related Behavior

3.7 引入了统一的 feature gate 机制（`server/features/etcd_features.go`），其中两项与租约 / 存储行为相关：

| gate | 阶段 | 默认 | 影响 |
| :--- | :--- | :--- | :--- |
| `LeaseCheckpoint` | alpha | false | leader 定期向其他成员发 checkpoint，防止 leader 切换时 TTL 被重置 |
| `LeaseCheckpointPersist` | alpha | false | 持久化 remainingTTL，防止长租约被无限续租 |

`LeaseCheckpointPersist` 是一条**计划与现实脱节的实证**：它的注释明确写着"Always enabled in v3.6"，还留着 `TODO: Delete in v3.7`，但 3.7.4 源码里**它仍然存在**，默认仍是 `false`：

```go
// server/features/etcd_features.go
	// LeaseCheckpointPersist enables persisting remainingTTL to prevent indefinite auto-renewal of long lived leases. Always enabled in v3.6. Should be used to ensure smooth upgrade from v3.5 clusters with this feature enabled.
	// Requires EnableLeaseCheckpoint featuragate to be enabled.
	// TODO: Delete in v3.7
	LeaseCheckpointPersist featuregate.Feature = "LeaseCheckpointPersist"
	// ...
	LeaseCheckpointPersist:       {Default: false, PreRelease: featuregate.Alpha},
```

这类"注释说该删但没删"的情况，正是必须以源码而不是以注释为准的典型例子。

## Pitfall List

> [!WARNING]
> 这套体系里有几处最容易配错的点：

1. **`auth enable` 不接受参数** —— 身份必须用全局 flag `--user` 传，写成 `etcdctl auth enable --user root:root` 会被 cobra 判为位置参数而报错退出。
2. **开了 auth 不等于 `/metrics` 也被保护** —— `/metrics`、`/health` 走独立 HTTP handler，不受 v3 RBAC 管辖。要保护它们得用 mTLS，或绑到 `--listen-metrics-urls` 指定的内部地址。
3. **JWT 配置项拼错不报错** —— 键名必须是 `priv-key`（不是 `private-key`），未知键只打一条 warn 就被忽略，token 仍正常签发，于是你以为配了密钥、其实用的是无签名路径。
4. **JWT 无法即时吊销** —— 改密码、改角色都不会让已签发的 JWT 失效，只能等 `exp` 到期。需要立即吊销时，Simple Token 的 `disable()` 反而更直接。
5. **`--auth-token-ttl` 对 JWT 无效** —— 它只改 simple token 的 TTL，JWT 走 `--auth-token` 里的 `ttl` 选项。
6. **频繁改权限会触发全量缓存重建** —— `rangePermCache` 是全量失效设计（源码注释自认 "can be a costly operation"），所有鉴权变更入口都会触发，包括看起来无关的 `user passwd`。
7. **CN 认证在 gRPC-proxy / gRPC-gateway 下失效** —— proxy 终结 TLS 后所有客户端共用一张证书；gateway 请求带 `grpcgateway-accept` 头时 CN 被显式丢弃。
8. **空密码用户不能登录** —— `etcdctl user add anonymous:''` 看似能建号，但这类账号无法通过用户名密码认证，请求报 `user name is empty`。要免密访问请用 `--no-password` 配合证书 CN。
9. **etcd 不做静态加密** —— TLS 只保护传输过程，磁盘上的 key/value 是明文，这是 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 文件被拷走后可直接读取的原因。
10. **etcd 不校验密码强度** —— API 与 `etcdctl` 都不强制长度或复杂度，这是管理员的责任。
11. **改权限后旧 Token 报的是 `revision of auth store is old`，不是 `permission denied`** —— 这是 auth revision 机制的正常行为，客户端应重新认证而非重试。

## Links

- [client（客户端认证配置与 token 注入）](/docs/CS/Framework/etcd/client.md)
- [boltdb（鉴权 bucket 的落盘结构）](/docs/CS/Framework/etcd/boltdb.md)
- [raft（鉴权元数据为何要走共识）](/docs/CS/Framework/etcd/raft.md)
- [gateway（proxy / gateway 与 CN 认证的冲突）](/docs/CS/Framework/etcd/gateway.md)
- [tuning（bcrypt cost 与性能权衡）](/docs/CS/Framework/etcd/tuning.md)

## References

1. [etcd Documentation - Authentication](https://etcd.io/docs/v3.7/op-guide/authentication/)
2. [etcd Documentation - Role-based access control](https://etcd.io/docs/v3.7/op-guide/authentication/rbac/)
3. [etcd Documentation - Transport security model](https://etcd.io/docs/v3.7/op-guide/security/)
4. [etcd v3.7.4 源码（server/auth/range_perm_cache.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/auth/range_perm_cache.go)
5. [etcd v3.7.4 源码（server/auth/store.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/auth/store.go)
