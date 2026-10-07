## Introduction

etcd 的"安全"不是一块开关，而是**四层彼此独立的机制**，混为一谈是排障时最常见的起点：

| 层 | 回答的问题 | etcd 的实现 | 默认状态 |
| :--- | :--- | :--- | :--- |
| 传输安全 | 数据在网上传输时会不会被窃听/篡改 | TLS / mTLS | **关闭** |
| 认证（authn） | 你是谁 | 密码 + Token，或客户端证书 CN | **关闭** |
| 授权（authz） | 你能碰哪些 key | RBAC（用户 / 角色 / 区间权限） | 随认证一起开启 |
| 静态加密 | 磁盘上的数据有没有加密 | **etcd 不提供** | — |

四层要分开看的原因很实际：`auth enable` 之后 `etcdctl get` 需要 `--user`，但 `curl http://127.0.0.1:2379/metrics` 依然畅通无阻——`/metrics` 与 `/health` 走独立的 HTTP handler，**不受 v3 RBAC 保护**。反过来，打开了 TLS 也不代表有认证（`--auto-tls` 只加密不验身份）。

> [!WARNING]
> etcd 的 TLS 只保护**传输中的**数据，**不加密磁盘上的 key/value**。静态加密要靠客户端自己加解密，或用底层存储的加密能力（如 dm-crypt / LUKS）。这是选型时经常被误以为"etc 用了 TLS 就安全了"的边界。

还有一个反直觉点：**鉴权（auth）本身是走 Raft 共识的写操作**。这不是实现偷懒，而是必然结果——用户、角色、权限必须全集群一致，否则同一个请求在不同节点上会得到不同裁决。因此 `user add` / `role grant-permission` 都是提案，要等多数派确认；也因此，**鉴权配置本身依赖 quorum**，集群失去多数派时连改权限都做不到。

> [!NOTE]
> **版本基线**：etcd **3.7.2**（`api/version/version.go` → `Version = "3.7.2"`）。本文所有 flag、文件路径、默认值与源码行号均以 `server/auth/`、`server/embed/config.go` 在 3.7.2 下的实际内容为准。3.7.2 **没有引入新的认证机制**，但给授权路径加了一层性能机制（见下文 `rangePermCache`）——这是旧版本资料里没有的。

## Control Plane and Data Plane

鉴权体系架构由**控制面**和**数据面**组成。

**控制面**负责鉴权元数据的一致性。AuthServer 收到请求后，为确保各节点间鉴权元数据一致，会通过 [Raft](/docs/CS/Framework/etcd/raft.md) 模块进行数据同步。当对应的 Raft 日志条目被集群半数以上节点确认后，Apply 模块通过鉴权存储（AuthStore）执行日志条目内容，将规则存储到 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 的一系列鉴权 bucket 中（`auth` / `authUsers` / `authRoles`）。

**数据面**由认证（authn）和授权（authz）流程组成：认证检查 client 身份是否合法、防止匿名访问；授权检查该身份是否有权限操作请求的数据路径。

## Authentication

认证的目的是检查 client 的身份是否合法、防止匿名用户访问。etcd 目前实现了两种认证机制：**密码认证**和**证书认证**。

认证通过后，为了提高密码认证性能，会分配一个 Token（类似门票、通信证）给 client，client 后续其他请求携带此 Token，server 就可快速完成身份校验，不必每次都跑一遍 bcrypt。

### Password Storage: bcrypt + salt + cost

用户密码认证是最基础的鉴权方式。密码认证有两大难点：**如何保障密码安全性**和**如何提升认证性能**——这两者天然冲突（安全性靠慢哈希实现，性能要求快）。

etcd 的做法是把三者融合：底层用 **bcrypt**（基于 Blowfish 的慢哈希，刻意设计得耗 CPU）、每个用户独立的随机 **salt**、可配置的迭代次数 **cost**。三者与算法版本一起拼成一个字符串存储，因此每次校验都能读回当时的参数。

```go
// 位置：server/etcdserver/v3_server.go:892（UserAdd 与 UserPasswd 共用）
hashedPassword, err := bcrypt.GenerateFromPassword([]byte(r.Password), s.authStore.BcryptCost())
```

cost 由 `--bcrypt-cost` 指定，默认取 `bcrypt.DefaultCost`（`server/embed/config.go:552`），有效范围受 `bcrypt.MinCost` / `bcrypt.MaxCost` 约束。**注意成本含义**：调高它会线性拉长每次 `user add` / `user passwd` 的耗时，也拉长登录校验耗时——这是用算力换抗爆破能力。

开启鉴权前必须先创建 `root` 账号，它拥有集群的最高读写权限（`root` 角色可以被授予任意用户，不限于 `root` 用户）：

```shell
$ etcdctl user add root:root
User root created
$ etcdctl --user root:root auth enable
Authentication Enabled
```

> [!WARNING]
> `auth enable` **不接受任何参数**（源码 `etcdctl/ctlv3/command/auth_command.go:77` 显式判 `len(args) != 0` 即报错退出）。身份必须用 `--user` 这个**全局 flag** 传，写成 `etcdctl auth enable --user root:root` 会被 cobra 当成位置参数而报错。

`--user` 接受三种形态（`etcdctl/ctlv3/ctl.go:74`）：`user:password`、只给 `user`（交互式提示输密码）、配合独立的 `--password`。另有一个隐藏的 `--auth-jwt-token` 用来直接携带 JWT。

拿到 root 后就可以创建普通账号了：

```shell
$ etcdctl user add alice:alice --user root:root
User alice created
```

鉴权模块收到此命令后，用 bcrypt 库的 blowfish 算法，基于明文密码、随机分配的 salt、自定义的 cost 迭代多次计算得到 hash 值，并将**算法版本、salt 值、cost、hash 值**组成一个字符串作为加密后的密码。然后以用户名为 key、加密后的密码为 value，存入 boltdb 的 `authUsers` bucket，账号创建完成。

当你用 alice 账号访问 etcd 时，需要先调用鉴权模块的 `Authenticate` 接口（`server/auth/store.go:333`）验证身份合法性：模块先按请求的用户名从 boltdb 取出加密后的密码，由于 hash 里包含了算法版本、salt、cost 等信息，可以据此用请求中的明文密码计算出最终 hash，结果一致则校验通过。

### Token Lifecycle

etcd 生成的每个 Token 都有一个过期时间 TTL 属性。Token 过期后 client 需再次验证身份——这显著缩小了数据泄露的时间窗口，在性能与安全性之间取得平衡。

etcd server 会定时检查 Token 是否过期，过期则从内存 map 中删除。清理由 `simpleTokenTTLKeeper` 负责，**扫描精度是 1 秒**（`server/auth/simple_token.go:43` 的 `simpleTokenTTLResolution`），所以实际过期时刻可能比 TTL 晚至多 1 秒。

> [!TIP]
> Simple Token 字符串本身**未含任何有价值信息**——没有签发时间、没有过期时间、没有用户名。client 因此**无法提前得知 Token 何时失效**，只能被动等请求返回 `Unauthenticated` 后重新认证。这是 Simple Token 可描述性弱的直接后果，也是它只被建议在开发测试环境使用的核心原因。

Token 的生成由 `TokenProvider` 负责，etcd 提供两种实现，由 `--auth-token` 选择（默认 `simple`，见 `server/embed/config.go:75`）：

| 维度 | Simple Token | JWT |
| :--- | :--- | :--- |
| 是否有状态 | **有**（内存 map 存 token → 用户） | **无**（自包含签名） |
| 默认 TTL | 300 秒（`--auth-token-ttl`，`config.go:553`） | 5 分钟（`server/auth/options.go:44`） |
| 可描述性 | 差，client 读不出任何信息 | 含 `username` / `revision` / `exp` claim |
| 抗伪造 | 弱（源码启动即 warn "not cryptographically signed"） | 强（非对称签名） |
| 失效方式 | `disable()` 遍历 map 全部作废 | 只能等 TTL 自然过期 |
| 官方定位 | 开发 / 测试环境 | 对安全要求高的环境 |

Simple Token 的核心原理是：用户身份验证通过后生成一个**随机字符串** Token 返回给 client，并在内存中用 map 存储用户与 Token 的映射关系。收到后续请求时，etcd 从请求中取出 Token，转换成对应的用户名信息传给下层模块。随机串默认长度 16（`simple_token.go:36`）。

JWT 路径签出的 token 携带三个 claim（`server/auth/jwt.go:101-105`）：`username`、`revision`、`exp`。其中 `revision` 是**兜底的重放防护**——`isOpPermitted` 会拒绝 `authInfo.Revision` 小于本节点 auth revision 的请求（`server/auth/store.go:870`，返回 `ErrAuthOldRevision`）。这个字段对 simple token 同样存在，只是 JWT 里由服务端签入、simple token 里由内存 map 记录。

`--auth-token-ttl` 只作用于 simple token（`config.go:361` 的字段注释写明 "in seconds of the simple token"）。JWT 的 TTL 走自己的 `ttl` 选项：

```shell
--auth-token="jwt,priv-key=/path/to/key.pem,sign-method=RS256,ttl=10m"
```

可识别的选项只有四个：`sign-method`、`pub-key`、`priv-key`、`ttl`（`server/auth/options.go:36-41`）。写错的键**不会报错**，只会打一条 `unknown JWT options` 的 warn 然后被忽略——配置拼错了却静默生效，是这条路径上最容易踩的坑。

### Certificate Identity (CN Authentication)

除了密码，etcd 还有一条**不依赖密码**的认证路径：从客户端证书的 Common Name 里取用户名。

```go
// 位置：server/auth/store.go:1013-1027
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
```

前提是服务端开了 `--client-cert-auth`，且客户端**同时**不提供用户名密码——两者都提供时**密码认证优先**。

`VerifiedChains` 是 `crypto/tls` 在**验证通过后**才填的，所以没有可信 CA 签发就不会有身份，这也是 CN 认证天然依附于 mTLS 的原因。

> [!WARNING]
> CN 认证**无法配合 gRPC-proxy 与 gRPC-gateway 使用**。proxy 在客户端侧终结 TLS，所有下游客户端共用 proxy 那一张证书，服务端看到的 CN 永远是 proxy 的。etcd 对此有专门防护：请求头里带 `grpcgateway-accept` 时，CN 直接被丢弃并打 warn（`server/auth/store.go:1036-1044`）；grpc-proxy 则在证书 CN 非空时直接报错退出。

对安全要求更高时，应使用 HTTPS 加密通信，防止中间人攻击与数据篡改。HTTPS 用非对称加密实现身份认证与密钥协商，因此需要用 CA 证书给 client 签发证书才能接入（详见官方 Transport security model 一节的 `keyUsage` / `extendedKeyUsage` 要求）。

## Authorization

开启鉴权后，put 请求在应用到状态机前，etcd 还会对发出请求的用户做权限检查。常用的权限模型有 ACL（Access Control List）、ABAC（Attribute-based access control）、RBAC（Role-based access control），etcd 实现的是 **RBAC**：为每个用户分配角色，为每个角色授予最小化的权限。

授权的基本操作：

```shell
$ etcdctl role add app
$ etcdctl role grant-permission app read /foo/          # 前缀读
$ etcdctl role grant-permission app --prefix=true readwrite /pub/
$ etcdctl role grant-permission app readwrite key1 key5  # 区间 [key1, key5)
$ etcdctl user grant-role alice app
```

### Interval Tree

因为一个用户可能拥有成百上千条权限，etcd 为提升权限检查性能引入了**区间树**：把角色的所有 key 权限合并成两棵区间树（读一棵、写一棵），检查时只需判断请求的 key 落在哪个已授权区间内。

```go
// 位置：server/auth/range_perm_cache.go:24-31, 67-71
func getMergedPerms(tx UnsafeAuthReader, userName string) *unifiedRangePermissions {
	user := tx.UnsafeGetUser(userName)
	if user == nil {
		return nil
	}
	readPerms := adt.NewIntervalTree()
	writePerms := adt.NewIntervalTree()
	for _, roleName := range user.Roles {
		// ... 遍历角色的每条 KeyPermission，按 PermType 插入对应的树
	}
	return &unifiedRangePermissions{readPerms: readPerms, writePerms: writePerms}
}
```

查询侧按请求形态分两路：`rangeEnd` 为空走 `checkKeyPoint`（点查询，`Intersects`），否则走 `checkKeyInterval`（区间查询，`Contains`）。两者都是 O(logN)——**这就是引入区间树的全部理由**。

权限区间的边界有一套不变量约束（源码注释里的 rule a1~b3），最反直觉的一条是：**开区间用 `rangeEnd = []byte{0x00}` 表示**，而不是留空。

```go
// 位置：server/auth/range_perm_cache.go:185-187
func isOpenEnded(rangeEnd []byte) bool { // check rule b3
	return len(rangeEnd) == 1 && rangeEnd[0] == 0
}
```

因为 `BytesAffineComparable` 用 `[]byte{}`（空串）当最大元素，`(X, []byte{})` 在语义上是"非法区间"而非"到顶区间"，所以必须用 `0x00` 来表达"一直到最大 key"。`--prefix=true` 生成的就是这种开区间权限。

### rangePermCache: per-user Interval Tree Cache

仅有区间树还不够。`isOpPermitted` 是**每个请求**都会走的热路径，而它需要先拿到用户对象、遍历用户的角色列表、再查树——源码里甚至留着一条 TODO 承认这件事很贵：

```go
// 位置：server/auth/store.go:859-860
func (as *authStore) isOpPermitted(userName string, revision uint64, key, rangeEnd []byte, permTyp authpb.Permission_Type) error {
	// TODO(mitake): this function would be costly so we need a caching mechanism
```

etcd 3.7 的答案是 `rangePermCache`：**在鉴权配置发生变更时，为每个用户预先合并好一棵区间树**（读 + 写各一棵），查询时只查缓存、不再遍历角色。

```go
// 位置：server/auth/range_perm_cache.go:110-129
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

注意锁的粒度：查询路径只拿 **RLock**（读锁），且**连 boltdb 事务都不开了**——对比 `isOpPermitted` 里的 `tx := as.be.ReadTx(); tx.RLock()`，缓存把整条 boltdb 读取链路从热路径上摘掉了。这才是这个缓存真正的收益所在。

代价写在源码注释里，非常直白：

```go
// 位置：server/auth/range_perm_cache.go:131-140
func (as *authStore) refreshRangePermCache(tx UnsafeAuthReader) {
	// Note that every authentication configuration update calls this method and it invalidates the entire
	// rangePermCache and reconstruct it based on information of users and roles stored in the backend.
	// This can be a costly operation.
	as.rangePermCacheMu.Lock()
	defer as.rangePermCacheMu.Unlock()
	as.lg.Debug("Refreshing rangePermCache")
	as.rangePermCache = make(map[string]*unifiedRangePermissions)
```

**全量失效 + 全量重建**，没有增量更新。因此：

- 读多写少的场景（典型业务）几乎白嫖性能收益；
- 频繁变更角色权限的管理面操作，会让每次变更都触发一次 O(用户数 × 权限数) 的重建，期间**写锁阻塞所有授权查询**；
- `server/auth/store.go` 里有 11 处 `refreshRangePermCache` 调用点，覆盖 `AuthEnable` / `UserAdd` / `UserDelete` / `RoleAdd` / `RoleDelete` / `RoleGrantPermission` 等**所有**会改动鉴权配置的入口——包括 `user passwd` 这种看似与权限无关的操作。

> [!NOTE]
> 排查"权限改了但不生效"或"改了权限后 etcd 卡住"时，第一反应应当是 `rangePermCache` 的重建，而不是怀疑 Raft 同步。开启 debug 日志后可以看到 `Refreshing rangePermCache` 这条 debug 日志的出现频率。

缓存之外的短路只有一条：**`root` 角色直接放行**，不查任何树（`server/auth/store.go:889-892`）。反过来，缓存里查不到用户时会打 `user doesn't exist` 并返回 `false`——**fail-closed**，鉴权出问题时 etcd 选择拒绝而不是放行。

### Auth-Related Flags

| flag | 默认值 | 位置 | 说明 |
| :--- | :--- | :--- | :--- |
| `--auth-token` | `simple` | `config.go:746` | `simple` 或 `jwt`，JWT 可带逗号分隔选项 |
| `--auth-token-ttl` | `300`（秒） | `config.go:748`，默认值在 `:553` | **仅作用于 simple token** |
| `--bcrypt-cost` | `bcrypt.DefaultCost` | `config.go:747`，默认值在 `:552` | 密码哈希迭代成本 |

`--auth-token-ttl` 的默认值 300 秒自 v3.4.9 以来**从未变过**——这个事实本身没变，变的只是它当年被写进文档时的版本锚点。

鉴权配置本身带一个独立的 **auth revision**（`server/auth/store.go:967`），与 MVCC 的数据 revision 不是一回事。它在请求校验时充当**新旧裁决的判据**：

```go
// 位置：server/auth/store.go:869-877
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

请求携带的 `authInfo.Revision` 是**签发 Token 那一刻**的 auth revision。如果之后有人改了权限，各节点 apply 完新配置后 auth revision 前进，而旧 Token 还带着老 revision——此时请求会被拒（`ErrAuthOldRevision`，对外是 `InvalidArgument`）。Simple Token 与 JWT 都带这个字段，因此这个"权限变更后旧 Token 立即失效"的语义两种 token 一致。

> [!NOTE]
> 这解释了一个常见困惑：**改了角色权限后，客户端开始报 `revision of auth store is old` 而不是 `permission denied`**。这不是 bug，是设计——权限变更会让所有未重新认证的旧 Token 立刻失效，属于 fail-closed。客户端的应对是重新 `Authenticate` 拿新 Token，而不是重试。

该 revision 也作为指标暴露：`etcd_debugging_auth_revision`（`server/auth/metrics.go:24`）。注意它带 `etcd_debugging_` 前缀，属官方标注的**不稳定指标**，跨版本可能变。

## 3.7 Impact of Feature Gate on Related Behavior

3.7 引入了统一的 feature gate 机制（`server/features/etcd_features.go`），其中两项与安全/存储行为相关：

| gate | 阶段 | 默认 | 影响 |
| :--- | :--- | :--- | :--- |
| `LeaseCheckpoint` | alpha | false | leader 定期向其他成员发 checkpoint，防止 leader 切换时 TTL 被重置 |
| `LeaseCheckpointPersist` | alpha | false | 持久化 remainingTTL，防止长租约被无限续租 |

`LeaseCheckpointPersist` 是一条**计划与现实脱节的实证**：它的注释明确写着"v3.6 起默认启用，**将在 v3.7 移除**"（`:69` 的 `Deprecated` 标注、`:65` 的 `TODO: Delete in v3.7`），但 3.7.2 源码里**它仍然存在**，且默认仍是 `false`（`:95`）。这类"注释说该删但没删"的情况，正是必须以源码而不是以注释为准的典型例子。

## Pitfall List

> [!WARNING]
> 这套体系里有几处最容易配错的点：

1. **`auth enable` 不接受参数** —— 身份必须用全局 flag `--user` 传。写成 `etcdctl auth enable --user root:root` 会被 cobra 判为位置参数而报错退出（`auth_command.go:77`）。
2. **开了 auth 不等于 `/metrics` 也被保护** —— `/metrics`、`/health` 走独立 HTTP handler，不受 v3 RBAC 管辖。要保护它们得用 mTLS，或把它们绑到 `--listen-metrics-urls` 指定的内部地址上。
3. **JWT 配置项拼错不报错** —— `--auth-token="jwt,private-key=..."` 里的键名必须是 `priv-key`（不是 `private-key`）。未知键只打一条 warn 就被忽略，token 仍会正常签发，于是你以为配了密钥、其实用的是无签名路径。
4. **JWT 无法即时吊销** —— 改密码、改角色都不会让已签发的 JWT 失效，只能等 `exp` 到期。需要立即吊销能力时，Simple Token 的 `disable()` 反而更直接。
5. **`--auth-token-ttl` 对 JWT 无效** —— 它只改 simple token 的 TTL。JWT 的 TTL 走 `--auth-token` 里的 `ttl` 选项。
6. **频繁改权限会触发全量缓存重建** —— `rangePermCache` 是全量失效设计（`range_perm_cache.go:132-134` 注释自认 "can be a costly operation"），11 个鉴权变更入口都会触发它，包括看起来无关的 `user passwd`。
7. **CN 认证在 gRPC-proxy / gRPC-gateway 下失效** —— proxy 终结 TLS 后所有客户端共用一张证书；gateway 请求会被显式识别并丢弃 CN（`store.go:1036`）。
8. **空密码用户不能登录** —— `etcdctl user add anonymous:''` 看起来能建号，但这类账号无法通过用户名密码认证，请求会报 `user name is empty`。要免密访问请用 `--no-password` 配合证书 CN。
9. **etcd 不做静态加密** —— TLS 只保护传输过程。磁盘上的 key/value 是明文，这是 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 文件被拷走后可直接读取的原因。
10. **etcd 不校验密码强度** —— API 与 `etcdctl` 都不强制长度或复杂度要求，这是管理员的责任，不能指望 etcd 兜底。
11. **改权限后旧 Token 报的是 `revision of auth store is old`，不是 `permission denied`** —— 这是 auth revision 机制的正常行为（见上文），客户端应重新认证而非重试。

## Links

- [etcd（总览与架构）](/docs/CS/Framework/etcd/etcd.md)
- [client（客户端认证配置）](/docs/CS/Framework/etcd/client.md)
- [boltdb（鉴权 bucket 的落盘结构）](/docs/CS/Framework/etcd/boltdb.md)
- [raft（鉴权元数据为何要走共识）](/docs/CS/Framework/etcd/raft.md)
- [gateway（proxy / gateway 与 CN 认证的冲突）](/docs/CS/Framework/etcd/gateway.md)
- [troubleshooting（权限相关报错排查）](/docs/CS/Framework/etcd/troubleshooting.md)

## References

1. [etcd Documentation - Authentication](https://etcd.io/docs/v3.7/op-guide/authentication/)
2. [etcd Documentation - Role-based access control](https://etcd.io/docs/v3.7/op-guide/authentication/rbac/)
3. [etcd Documentation - Transport security model](https://etcd.io/docs/v3.7/op-guide/security/)
4. [etcd server/auth/ 源码目录（v3.7.2）](https://github.com/etcd-io/etcd/tree/v3.7.2/server/auth)
5. [etcd server/auth/range_perm_cache.go — 区间树与 rangePermCache](https://github.com/etcd-io/etcd/blob/v3.7.2/server/auth/range_perm_cache.go)
