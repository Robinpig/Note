## Introduction

集群里有两个方向的身份问题，它们经常被混在一起谈：

1. **谁在调用 apiserver，凭什么相信他？**——控制面组件、kubelet、kube-proxy、工作负载，全都要先回答这个问题。
2. **工作负载怎么拿到"我是谁"的证明？**——Pod 里的进程需要一个凭据去访问 apiserver 或别的服务。

这两件事在 Kubernetes 里由**三套彼此独立的信任根**分别解决，而它们的签发者、载体、生命周期完全不同：

| 身份 | 签发者 | 载体 | 校验方用什么验 | 生命周期 |
|---|---|---|---|---|
| 控制面/节点组件 | 集群 CA（admin 手工签发） | x509 客户端证书 | apiserver `--client-ca-file` | 手工轮换，但 kubelet 可自动 |
| ServiceAccount | **apiserver 自己** | JWT（bearer） | apiserver `--service-account-key-file` | 1 小时～1 年，自动刷新 |
| Pod 证书（v1.37 GA） | 第三方 signer | x509（挂进 Pod 文件系统） | pod identity 扩展映射回 Pod | kubelet 托管 |

注意第二列和第四列：**ServiceAccount token 的签发与校验都在 apiserver 内部，用的密钥对与集群 CA 毫无关系**。这是最容易搞错的一点——`--client-ca-file` 和 `--service-account-key-file` 是两套完全不相干的密钥，谁都不会替谁背书。

而在第一行内部，还藏着一个结构性的"鸡生蛋"问题：**kubelet 要有一张证书才能连上 apiserver，但要拿到这张证书必须连上 apiserver**。这个环的解法（bootstrap token）是本篇最值得读的一段。

> [!NOTE]
> 本文全部结论基于 **Kubernetes v1.37.2** 源码实读，机制讲解直接贴真实片段。v1.37 有两处升级了 v1.36 的结论：`PodCertificateRequest` 与 `ClusterTrustBundle` 都已 **GA 且默认开启**。

## Segment 1: Static PKI — The Starting Point of Trust Is Who Holds the Private Key

集群搭建时，管理员手工（或 kubeadm 自动）生成一批证书。要紧的只有一件事：**私钥在谁手里**。

| 参数 | 谁用 | 私钥含义 |
|---|---|---|
| `--client-ca-file` | kube-apiserver | 用来验客户端证书的信任锚（只有公钥） |
| `--kubelet-client-certificate` / `-key` | kube-apiserver | apiserver **作为客户端**去连 kubelet 时的身份 |
| `--cluster-signing-cert-file` / `-key` | kube-controller-manager | **签发** CSR 用的 CA 私钥 |
| `--root-ca-file` | kube-controller-manager | 用来往各 namespace 发 `kube-root-ca.crt` |
| `--service-account-key-file` | kube-apiserver | 校验 SA token 的公钥（可传多个） |
| `--service-account-signing-key-file` | kube-apiserver | 签发 SA token 的私钥 |
| `--tls-cert-file` / `--tls-private-key-file` | kubelet | 服务端证书的**兜底**路径 |

有两点值得单独说：

**其一，`--cluster-signing-*` 是全集群唯一持有 CA 私钥的位置。** apiserver 只负责校验请求方有没有资格拿到证书（见 Segment 2 的 SAR），真正的签名动作发生在 kube-controller-manager 里的 `CertificateAuthority.Sign`（`pkg/controller/certificates/authority/authority.go`）。这是一个刻意的职责切分：**apiserver 不签发东西**。

**其二，`--root-ca-file` 缺省时会回退到 apiserver 自己的 CA。** `getKubeAPIServerCAFileContents` 在 `RootCAFile == ""` 时直接取 client config 的 `CAData`（`cmd/kube-controller-manager/app/certificates.go`）。所以在 kubeadm 集群里，`kube-root-ca.crt` 里的内容和 apiserver 的 client CA 是同一份——**但这是配置巧合，不是语义保证**。

`CertificateAuthority.Sign` 内部走 `PermissiveSigningPolicy.apply`：

```go
// pkg/controller/certificates/authority/policies.go
func (p PermissiveSigningPolicy) apply(tmpl *x509.Certificate, signerNotAfter time.Time) error {
	...
	usage, extUsages, err := keyUsagesFromStrings(p.Usages)
	if err != nil {
		return err
	}
	tmpl.KeyUsage = usage
	tmpl.ExtKeyUsage = extUsages

	tmpl.ExtraExtensions = nil
	tmpl.Extensions = nil
	tmpl.BasicConstraintsValid = true
	tmpl.IsCA = false

	tmpl.NotBefore = now.Add(-p.Backdate)

	if ttl < p.Short {
		// do not backdate the end time if we consider this to be a short lived certificate
		tmpl.NotAfter = now.Add(ttl)
	} else {
		tmpl.NotAfter = now.Add(ttl - p.Backdate)
	}

	if !tmpl.NotAfter.Before(signerNotAfter) {
		tmpl.NotAfter = signerNotAfter
	}
	...
}
```

它做的事很有限：设 KeyUsage/ExtKeyUsage、强制 `IsCA=false`、**清空所有扩展**、把 NotAfter 夹在 CA 的 NotAfter 之内。

> [!IMPORTANT]
> `PermissiveSigningPolicy` **不会覆写 Subject**——签出来的证书 CN/O 就是 CSR 里的值。所以"CA 会强制把 Subject 改成固定值"这个印象是错的。约束 Subject 的是**审批环节**（recognizer 的匹配条件），不是签发环节。

## Segment 2: The Chicken-and-egg of Node Identity, and Its Solution

### 2.1 Where the Loop Is

kubelet 首次启动时，磁盘上没有任何证书。它需要：

- 一张**客户端证书**去认证 apiserver（CN `system:node:<name>`，O `system:nodes`）
- 一张**服务端证书**让 apiserver/其他组件能反过来连它

而申请证书的唯一途径是调 apiserver 的 CSR API——又要求先认证。这就是 TLS bootstrap 问题。

解法不是"给 kubelet 一个长期凭据"，而是**给它一个短期、权限极窄的一次性凭据，用它换完证书就作废**。这个凭据就是 bootstrap token。

### 2.2 The Shape of the Bootstrap Token

| 项 | 值 |
|---|---|
| 格式 | `<token-id>.<token-secret>`（`staging/src/k8s.io/cluster-bootstrap/token/api/types.go`） |
| ID | 6 字符，`[a-z0-9]` |
| Secret | 16 字符，`[a-z0-9]` |
| 存储 | Secret `bootstrap-token-<id>`，type `bootstrap.kubernetes.io/token` |
| 所在 namespace | `kube-system` |

Secret 里的 key 决定这个 token 能干什么：

| key | 作用 |
|---|---|
| `token-id` / `token-secret` | 凭据本体 |
| `expiration` | RFC3339 绝对时间；**缺省即永不过期** |
| `usage-bootstrap-authentication` | 必须为 `"true"` 才能用来做 bearer 认证 |
| `usage-bootstrap-signing` | 必须为 `"true"` 才能用来签 `cluster-info` |
| `auth-extra-groups` | 额外附加的组，必须匹配 `system:bootstrappers:[a-z0-9:-]{0,255}[a-z0-9]` |
| `description` | 人读描述 |

认证入口是 `plugin/pkg/auth/authenticator/token/bootstrap/bootstrap.go`，它按顺序做四件事：

```go
// plugin/pkg/auth/authenticator/token/bootstrap/bootstrap.go（AuthenticateToken 内，节选）
if string(secret.Type) != string(bootstrapapi.SecretTypeBootstrapToken) || secret.Data == nil {
    tokenErrorf(secret, "has invalid type, expected %s.", bootstrapapi.SecretTypeBootstrapToken)
    return nil, false, nil
}

ts := bootstrapsecretutil.GetData(secret, bootstrapapi.BootstrapTokenSecretKey)
if subtle.ConstantTimeCompare([]byte(ts), []byte(tokenSecret)) != 1 {
    tokenErrorf(secret, "has invalid value for key %s.", bootstrapapi.BootstrapTokenSecretKey)
    return nil, false, nil
}
...
if bootstrapsecretutil.HasExpired(secret, time.Now()) {
    // logging done in isSecretExpired method.
    return nil, false, nil
}

if bootstrapsecretutil.GetData(secret, bootstrapapi.BootstrapTokenUsageAuthentication) != "true" {
    tokenErrorf(secret, "not marked %s=true.", bootstrapapi.BootstrapTokenUsageAuthentication)
    return nil, false, nil
}

groups, err := bootstrapsecretutil.GetGroups(secret)
...
return &authenticator.Response{
    User: &user.DefaultInfo{
        Name:   bootstrapapi.BootstrapUserPrefix + string(id),
        Groups: groups,
    },
}, true, nil
```

即：类型校验 → `subtle.ConstantTimeCompare` 比 secret → 过期检查 → usage 检查，最后返回用户名 `system:bootstrap:<id>` 和组列表 `system:bootstrappers` + `auth-extra-groups`。

> [!TIP]
> **token 只允许 `[a-z0-9]`，所以认证天然大小写敏感**（types.go 的正则没有 `i` 标志）。历史上这里出过问题，现在写法上已无法绕过。
>
> **token 过期不会让 Secret 消失。** authenticator 只是拒绝，删除动作归 `tokencleaner` 管，而它**默认是关闭的**（见 Segment 5 末尾）。

### 2.3 Signature of `cluster-info`: Why the Token Carries Trust

新节点除了 token，还必须知道"apiserver 是谁、要不要信他的证书"。这份信息的载体是 `kube-public/cluster-info` ConfigMap 的 `kubeconfig` key。但**怎么证明这份 kubeconfig 没被人篡改**？——用 bootstrap token 自己签。

`bootstrapsigner` 做的事（`pkg/controller/bootstrap/bootstrapsigner.go`）：

1. 从 `kube-public/cluster-info` 取出 `kubeconfig` 内容
2. 遍历现有 `jws-kubeconfig-*` key，把它们从内存副本里**摘出来**暂存
3. 对当前每个有效 signing token，用 token secret 作 **HS256 对称密钥**重算 detached JWS，写回 `jws-kubeconfig-<token-id>`
4. 只有当"某个签名变了"或"有多余签名要删"时才真正写回 ConfigMap

这套设计的隐含结论很干净：**撤销一个 bootstrap token，就等于撤销指向它的那份签名**——因为第 3 步只为当前有效的 token 生成签名。

### 2.4 First Handshake and CSR

kubelet 侧入口是 `bootstrap.LoadClientCert`，最终落到 `requestNodeCertificate`（`pkg/kubelet/certificate/bootstrap/bootstrap.go`）：

| 项 | 值 |
|---|---|
| CSR Subject | `O=system:nodes`，`CN=system:node:<nodeName>` |
| signerName | `kubernetes.io/kube-apiserver-client-kubelet` |
| usages | `digitalSignature` + `clientAuth`（RSA 再加 `keyEncipherment`） |
| 等待超时 | 3600 秒 |
| 取回方式 | `csr.WaitForCertificate` 轮询 CSR 状态 |

> [!WARNING]
> **第一份 CSR 的 Subject 是"节点身份"，不是 bootstrap 用户身份。** CN 是 `system:node:<nodeName>`，而**不是** `system:bootstrap:<id>`。很多人以为 bootstrap token 的 username 会出现在证书里——不会。token 只用于"我有资格申请"，申请的东西是节点证书。

### 2.5 CSR Approval: Uses Authorization Query, Not Hardcoding

审批控制器只有**两个** recognizer（`pkg/controller/certificates/approver/sarapprove.go`）：

```go
// pkg/controller/certificates/approver/sarapprove.go
func recognizers() []csrRecognizer {
	recognizers := []csrRecognizer{
		{
			recognize:      isSelfNodeClientCert,
			permission:     authorization.ResourceAttributes{Group: "certificates.k8s.io", Resource: "certificatesigningrequests", Verb: "create", Subresource: "selfnodeclient", Version: "*"},
			successMessage: "Auto approving self kubelet client certificate after SubjectAccessReview.",
		},
		{
			recognize:      isNodeClientCert,
			permission:     authorization.ResourceAttributes{Group: "certificates.k8s.io", Resource: "certificatesigningrequests", Verb: "create", Subresource: "nodeclient", Version: "*"},
			successMessage: "Auto approving kubelet client certificate after SubjectAccessReview.",
		},
	}
	return recognizers
}
```

`isNodeClientCert` 的匹配条件：signerName = `kubernetes.io/kube-apiserver-client-kubelet`，且 O = `["system:nodes"]`、CN 前缀 `system:node:`、usages 匹配、无额外 SAN；`isSelfNodeClientCert` 在此基础上还要求 `csr.Spec.Username == CSR 的 CN`。

匹配上之后，它**不是直接批准**，而是以 CSR 请求者的身份发一个 `SubjectAccessReview`；SAR 通过才追加 Approved 条件：

```go
// pkg/controller/certificates/approver/sarapprove.go
func (a *sarApprover) authorize(ctx context.Context, csr *capi.CertificateSigningRequest, rattrs authorization.ResourceAttributes) (bool, error) {
	...
	sar := &authorization.SubjectAccessReview{
		Spec: authorization.SubjectAccessReviewSpec{
			User:               csr.Spec.Username,
			UID:                csr.Spec.UID,
			Groups:             csr.Groups,
			Extra:              extra,
			ResourceAttributes: &rattrs,
		},
	}
	sar, err := a.client.AuthorizationV1().SubjectAccessReviews().Create(ctx, sar, metav1.CreateOptions{})
	if err != nil {
		return false, err
	}
	return sar.Status.Allowed, nil
}
```

所以"谁能自动拿到节点证书"完全由 RBAC 决定。默认绑定由 kubeadm 建立：

- `system:certificates.k8s.io:certificatesigningrequests:nodeclient`（`plugin/pkg/auth/authorizer/rbac/bootstrappolicy/policy.go`）→ 绑给 `system:bootstrappers:kubeadm:default-node-token`
- `system:certificates.k8s.io:certificatesigningrequests:selfnodeclient` → 绑给 `system:nodes`

前者是"新节点首次换证"，后者是"老节点自己轮换"——**这是两条权限不同的路**，不要混。另外 `system:node-bootstrapper` 只给 `create/get/list/watch certificatesigningrequests`，作用是"能提交 CSR"，不含批准。

### 2.6 Issuance and Revocation

kube-controller-manager 里注册了**四个** signing controller（`pkg/controller/certificates/signer/signer.go`）：

| 构造函数 | signerName |
|---|---|
| `NewKubeletServingCSRSigningController` | `kubernetes.io/kubelet-serving` |
| `NewKubeletClientCSRSigningController` | `kubernetes.io/kube-apiserver-client-kubelet` |
| `NewKubeAPIServerClientCSRSigningController` | `kubernetes.io/kube-apiserver-client` |
| `NewLegacyUnknownCSRSigningController` | `kubernetes.io/legacy-unknown` |

每个 controller 用各自的 CA 文件，或统一回退到 `--cluster-signing-{cert,key}-file`（`cmd/kube-controller-manager/app/certificates.go`）。签发前会做一次 **usages 与 signerName 的匹配校验**（`isRequestForSignerFn`）——不匹配就写 `CertificateFailed` 条件并**拒绝签发**。比如 `kubernetes.io/kube-apiserver-client` 强制要求含 `client auth`。

默认签发有效期 `--cluster-signing-duration` = **365 天**（`pkg/controller/certificates/signer/config/v1alpha1/defaults.go`）；CSR 可以用 `spec.expirationSeconds` 要更短的（最短 10 分钟）。

签完名写回 `csr.Status.Certificate`，kubelet 端轮询读到后落盘。

## Segment 3: Certificate Persistence and Rotation

### 3.1 Disk Layout

`NewFileStore(prefix, ...)` 生成的文件名规则是 `<prefix>-<qualifier>.pem`（`staging/src/k8s.io/client-go/util/certificate/certificate_store.go`）。kubelet 用两个前缀：

| 用途 | 文件 |
|---|---|
| 客户端证书 | `kubelet-client-current.pem`（symlink） |
| 服务端证书 | `kubelet-server-current.pem`（symlink） |

每次轮换写一个新文件 `kubelet-client-2006-01-02-15-04-05.pem`，再原子替换 `-current` symlink。目录权限 `0755`，文件权限 `0600`。旧版本路径 `kubelet-client.crt` / `.key` 仍作为回退被读取。

### 3.2 Threshold: 70% to 90%

```go
// staging/src/k8s.io/client-go/util/certificate/certificate_manager.go
var jitteryDuration = func(totalDuration float64) time.Duration {
	return wait.Jitter(time.Duration(totalDuration), 0.2) - time.Duration(totalDuration*0.3)
}
```

`wait.Jitter(d, 0.2)` 等于 `d + [0, 0.2d]`，所以结果落在 **[0.7d, 0.9d]**。

> [!WARNING]
> **同一个文件里的两处注释互相矛盾。** 函数注释写的是 "80%+/-10%"，而变量注释写的是 "approximately 70-90%"。**代码与后者一致。** 这个 70%~90% 的 jitter 是为了让同一时间创建的节点不要在后续生命期里同时轮换。

没有 `certRenewalPercent` 之类的可配置项；轮换阈值不可调。

### 3.3 Failure and Retry

| 情形 | 行为 |
|---|---|
| 单轮等待批准 | 最长 15 分钟（`certificate_manager.go` 的 `maxWaitDuration`） |
| 申请失败 | 退避 2/4/8/16/32 秒，之后每 32 秒无限重试 |
| **失败上限** | **没有**。kubelet 不因轮换失败而崩溃 |
| 重启时 | store 里有未过期证书就直接复用，**不换证** |

### 3.4 Server Certificate Rotation Must Pass Two Gates

```go
// pkg/kubelet/kubelet.go
if kubeCfg.ServerTLSBootstrap && utilfeature.DefaultFeatureGate.Enabled(features.RotateKubeletServerCertificate) {
```

也就是说 `--rotate-server-certificates` 与 feature gate `RotateKubeletServerCertificate`（1.12 起 Beta 默认 true，未 LockToDefault）**都**要满足。**而且服务端 CSR 同样需要被批准**——这道批准没有默认的自动 recognizer，得管理员手工批或配 RBAC。

另一个容易踩的点：服务端 CSR 模板**至少需要一个 IP SAN**，否则 `newGetTemplateFn` 返回 nil，kubelet 干脆不申请。

### 3.5 Dynamic Loading on the Transport Side

`transport.go` 把证书读取挂成 `GetClientCertificate` 回调，直接返回 `clientCertificateManager.Current()`。另有一个每 10 秒的检查：若发现 `Current()` 变了，就 `CloseAll()` 把所有连接踢掉强制重握手——**不是重建 transport，而是断连接**。

`ServerHealthy()` 与 `/healthz` 不是一回事：manager 的 `ServerHealthy()` 由 CSR 的响应推断，而 server dynamic-file manager 恒返回 true。

可观测的指标（Subsystem 均为 `kubelet`）：

- `kubelet_certificate_manager_server_rotation_seconds`（历史轮换周期直方图）
- `kubelet_certificate_manager_server_ttl_seconds`（当前服务端证书剩余 TTL）
- `kubelet_server_expiration_renew_errors` / `kubelet_client_expiration_renew_errors`

## Segment 4: ServiceAccount Token

### 4.1 Two Kinds of Tokens Coexist

| | legacy | bound |
|---|---|---|
| 载体 | Secret（`kubernetes.io/service-account-token`） | projected volume 中的文件 |
| 生成方式 | controller 填进 Secret | `TokenRequest` API |
| 过期 | **无 `exp`，永不过期** | 有 `exp` |
| audience | 通常为空 | 显式指定 |
| 对象绑定 | 无 | Pod / Secret / Node |

**自动创建 legacy Secret 的机制已经彻底移除。** 三个相关 gate（`LegacyServiceAccountTokenNoAutoGeneration` / `Tracking` / `CleanUp`）在 v1.36+ 源码里**全库零命中**。

> [!CAUTION]
> 移除的只是"**自动创建**"。legacy authenticator 仍在 apiserver 启动时注册，所以**手工创建的 Secret 依然会被填入 token，也依然能被认证**（`pkg/serviceaccount/legacy.go`）。这不是漏洞，是设计上的兼容出口。

### 4.2 Default Validity Period 3607 Seconds

```go
// pkg/serviceaccount/claims.go
WarnOnlyBoundTokenExpirationSeconds = 60*60 + 7
```

**为什么不是整 3600？** 因为 `+7` 是一个哨兵值：admission 自动注入投射卷时用它，`TokenRequest` 处理里据此判断"这是自动注入的 token"，从而可以走 extend-expiration 的迁移逻辑（`pkg/registry/core/serviceaccount/storage/token.go`）。

`--service-account-extend-token-expiration` **默认 true**（`pkg/kubeapiserver/options/authentication.go`：`o.ServiceAccounts.ExtendExpiration = true`），所以自动注入的 token 实际会被延长到 **1 年**，而不是 1 小时。手写 `kubectl create token` 得到的才是 1 小时的版本。

`--service-account-max-token-expiration` 默认 **0（无上限）**，只有配成非 0 时才会裁剪超长请求。

### 4.3 Claims and Verification Timing

JWT 的 `kubernetes.io` 段包含命名空间、ServiceAccount 的 name/uid，以及可选的 pod / node / secret 的 name/uid。注意 **JWT 只存 name + uid，不存 kind / apiVersion**。

对象绑定的校验发生在**认证阶段**（`pkg/serviceaccount/jwt.go` 调 `validator.Validate`）：Pod 被删除或 UID 变化 → token 立即失效。所以"绑到 Pod 的 token 在 Pod 重建后失效"是认证层强制的，不是靠客户端自觉。

### 4.4 kubelet token manager

| 项 | 值 |
|---|---|
| cache key | name / namespace / audiences / expirationSeconds / boundObjectRef / uid（`pkg/kubelet/token/token_manager.go`） |
| 刷新条件 | 超过 TTL 的 **80%**，或已存活超过 **24 小时** |
| jitter | ≤ 10 秒 |
| 刷新失败 | 旧 token 若仍有效则**继续返回旧 token**；没有退避重试 |
| 请求方式 | `ServiceAccounts(ns).CreateToken`（TokenRequest 子资源） |
| 落盘介质 | projected volume 底层是 `EmptyDir{Medium: Memory}`，即 tmpfs（`pkg/volume/projected/projected.go`） |

**文件会自己更新**：kubelet 在 80% TTL 时用 atomic writer 重写 token 文件，容器里长期运行的进程只要重新读文件就能拿到新 token。但**把 token 读进环境变量的做法不会更新**。

### 4.5 Verification Side

apiserver 用 `JWTTokenAuthenticator`，默认 RS256（也支持 ES256/384/512）。`--service-account-key-file` 接受**多个**文件，校验时逐个尝试所有公钥——这是 SA 签名密钥轮换的机制。OIDC discovery 与 JWKS 端点注册在 `pkg/routes/openidmetadata.go`（`/openid/v1/jwks`）。

`jti` 会被写进 token（gate `ServiceAccountTokenJTI` 已 GA 且 LockToDefault），但**它只用于审计追踪，没有重放黑名单**。同理 `ServiceAccountTokenPodNodeInfo`（GA）会把 `kubernetes.io/node{name,uid}` 写进 token。

这四个 gate 的依赖关系也值得记一笔：gate 表里 `ServiceAccountTokenNodeBinding` 声明了对 `ServiceAccountTokenNodeBindingValidation` 的依赖，即**启用前者必须以同时启用后者为前提**。四个 gate 在 1.32 之后都已 `GA + LockToDefault`，所以现状是不能再关。

## Segment 5: Pod Certificates and Cluster Trust Bundles（v1.37 GA）

### 5.1 PodCertificateRequest — Workload Requests x509 Directly

`PodCertificateRequest`（`certificates.k8s.io/v1beta1`）的 gate 状态在 v1.37.2 里是：

```go
// pkg/features/kube_features.go
PodCertificateRequest: {
    {Version: version.MustParse("1.34"), Default: false, PreRelease: featuregate.Alpha},
    {Version: version.MustParse("1.35"), Default: false, PreRelease: featuregate.Beta},
    {Version: version.MustParse("1.37"), Default: true, PreRelease: featuregate.GA}, // LockToDefault in 1.38
},
```

**v1.37 GA 且默认开启**（v1.34 Alpha 引入、v1.35 转 Beta 时默认关闭——如果你读过旧资料说它"默认关"，那是 v1.36 以前的状态）。

它的设计意图和 CSR 完全不同：**请求内容只有一句话——"Pod X 向 signer Y 要证书"**。私钥由 **kubelet** 生成，kubelet 负责建 PCR、等签发、把 key 与证书链挂进 Pod 文件系统；**node 限制的强制在 apiserver 侧**。Kubernetes 自带**零个**应用 signer，签发交给第三方。

配套的清理控制器在 KCM 侧接线：

```go
// cmd/kube-controller-manager/app/certificates.go
func newPodCertificateRequestCleanerControllerDescriptor() *ControllerDescriptor {
	return &ControllerDescriptor{
		name:        names.PodCertificateRequestCleanerController,
		constructor: newPodCertificateRequestCleanerController,
		requiredFeatureGates: []featuregate.Feature{
			features.PodCertificateRequest,
		},
	}
}
```

`NewPCRCleanerController` 用 15 分钟（期望流程完成上限）与 5 分钟（轮询间隔）两个参数。

### 5.2 ClusterTrustBundle — Replaces `kube-root-ca.crt`

`rootcacertpublisher` 现在的行为是往**每一个** namespace 发布同名 ConfigMap `kube-root-ca.crt`，数据 key 为 `ca.crt`（`pkg/controller/certificates/rootcacertpublisher/publisher.go`）；Namespace informer 的 Add 与 Update 都入队。

> [!NOTE]
> **`kube-root-ca.crt` 不只在 `kube-public`。** 每个 namespace 一份。`kube-public/cluster-info` 是 bootstrap signer 用的另一回事，别混。

这套"每个 namespace 一份 ConfigMap"的做法正是 KEP-3257 想淘汰的对象。替代品 `ClusterTrustBundle` 在 v1.37.2 的 gate 状态：

```go
// pkg/features/kube_features.go
ClusterTrustBundle: {
    {Version: version.MustParse("1.27"), Default: false, PreRelease: featuregate.Alpha},
    {Version: version.MustParse("1.33"), Default: false, PreRelease: featuregate.Beta},
    {Version: version.MustParse("1.37"), Default: true, PreRelease: featuregate.GA}, // LockToDefault in 1.38
},
```

同样 **v1.37 GA 默认开启**。发布的对象由 `clustertrustbundlepublisher` 完成，对象名由 signerName 派生：`/` 换成 `:`，再接 `:` + sha256(CA bundle) 的前 12 位（`pkg/controller/certificates/clustertrustbundlepublisher/publisher.go`）。接线时优先 v1beta1，discovery 不到就回退 v1alpha1。

### 5.3 ReloadKubeletClientCAFile

```go
// pkg/features/kube_features.go
ReloadKubeletClientCAFile: {
    {Version: version.MustParse("1.36"), Default: true, PreRelease: featuregate.Beta},
},
```

**v1.36 全新引入，Beta 即默认开启**：kubelet 可以在不重启的情况下重载客户端 CA 文件。

### 5.4 Cleanup Cadence

`csrcleaner` 是唯一会删 CSR 的组件，常量写在 `pkg/controller/certificates/cleaner/cleaner.go`：

| 条件 | 阈值 |
|---|---|
| 轮询间隔 | 1 小时 |
| 已签发、被拒、失败 | 1 小时 |
| Pending | 24 小时 |
| 证书已过期 | 立即 |
| 已批准但未签发 | 24 小时 |

注意**"已批准"条件一旦写入不会被改回**——cleaner 删的是对象，不是反转状态。

## Whole-chain Comparison Table

| 阶段 | 触发者 | 凭据 | 校验方 | 结果 |
|---|---|---|---|---|
| 集群搭建 | 管理员 / kubeadm | 手工 CA | apiserver `--client-ca-file` | 静态 PKI 就位 |
| 节点首次加入 | kubelet | bootstrap token（最长 24h） | bootstrap authenticator | 身份 `system:bootstrap:<id>` |
| 取 `cluster-info` | kubelet | token 作为 HS256 密钥验签 | 本地 | 拿到 apiserver 地址与 CA |
| 申请节点证书 | kubelet | bootstrap token | apiserver 认证 | CSR 提交成功 |
| CSR 审批 | csrapprover | — | **SAR**（`nodeclient` 子资源） | Approved 条件 |
| CSR 签发 | csrsigner（4 个） | `--cluster-signing-*` 私钥 | usages ↔ signerName 匹配 | `status.certificate` |
| 证书落盘 | kubelet | — | — | `kubelet-client-current.pem` |
| 日常轮换 | kubelet（70~90% TTL） | 自身客户端证书 | `selfnodeclient` SAR | 新证书，换 symlink |
| Pod 拿 SA token | kubelet token manager | `TokenRequest` | apiserver 认证 + 对象存在性 | JWT 写入 tmpfs |
| token 过期刷新 | kubelet（80% TTL / 24h） | 同左 | — | 文件原地更新 |
| Pod 拿 x509（v1.37 GA） | kubelet | `PodCertificateRequest` | 第三方 signer | key + 证书链挂进 Pod |

## v1.36-v1.37 Counterintuitive List

1. **ServiceAccount token 与集群 CA 是两套完全独立的信任根。** `--client-ca-file` 不认 SA token，`--service-account-key-file` 也不认客户端证书。
2. **`PermissiveSigningPolicy` 不覆写 Subject**，只清扩展、强制 `IsCA=false`、夹紧 NotAfter。约束 Subject 的是审批，不是签发。
3. **轮换阈值是 70%~90%，不是 90%。** 而且 `certificate_manager.go` 里函数注释写的 "80%+/-10%" 与变量注释写的 "70-90%" **自相矛盾**，以代码为准。
4. **kubelet 重启不会换证。** store 里有未过期证书就直接复用，只有无证书或证书将过期才 `forceRotation`。
5. **CSR 被拒后无限重试，没有失败上限。** 退避到 32 秒后无限轮询，kubelet 不会因此崩。
6. **bootstrap token 的 username（`system:bootstrap:<id>`）不会出现在换来的证书里。** 第一份 CSR 的 CN 是 `system:node:<nodeName>`。
7. **审批走 SAR，不是硬编码放行。** `recognizers()` 只有两个，且都必须通过 SubjectAccessReview。
8. **`nodeclient` 与 `selfnodeclient` 是两条权限不同的路**：前者给新节点（绑 `system:bootstrappers:...`），后者给老节点自轮换（绑 `system:nodes`）。
9. **服务端证书轮换要双条件**：`--rotate-server-certificates` **且** gate `RotateKubeletServerCertificate`（仍 Beta 默认 true，未 GA），且 CSR 仍需被批准。
10. **服务端 CSR 至少需要一个 IP SAN**，否则根本不申请。
11. **自动创建 legacy SA Secret 的 gate 已从源码中彻底消失**，但 legacy authenticator 仍在——手工 Secret 依然能被填 token 并被认证。
12. **bound token 默认 3607 秒不是随手取的**，`+7` 是识别人工/自动注入的哨兵值；配合默认开启的 extend-expiration，实际有效期是 **1 年**。
13. **`kube-root-ca.crt` 在每个 namespace 都有一份**，不是只在 `kube-public`。
14. **`jti` 已 GA 但不做重放检测**，仅作审计追踪。
15. **`PodCertificateRequest` 与 `ClusterTrustBundle` 在 v1.37 已 GA 且默认开启**——v1.34-v1.36 期间它们是"Beta 但默认关闭"，旧资料的说法在 v1.37 已失效。两者都不会自动产生任何对象，发布/签发仍需配套 signer / publisher。
16. **`csrcleaner` 的"已批准"判定不会反转**，它只是删对象；被批准过的 CSR 不会回到 Pending。
17. **`ReloadKubeletClientCAFile` 是 v1.36 全新引入的 gate，Beta 即默认 true**。
18. **`bootstrapsigner` 与 `tokencleaner` 默认都是关闭的**（`cmd/kube-controller-manager/app/bootstrap.go` 的 descriptor 里标了 `isDisabledByDefault: true`）。kubeadm 靠 `--controllers=*,bootstrapsigner,tokencleaner` 显式打开——**自建控制面时如果漏掉这个参数，token 清理与 `cluster-info` 签名都不会发生**，过期的 token Secret 会一直留在集群里。

## Troubleshooting Quick Reference

| 症状 | 先查什么 | 常见原因 |
|---|---|---|
| 节点 `kubectl get csr` 一直 Pending | `kubectl auth can-i create certificatesigningrequests/nodeclient --as=system:bootstrap:<id>` | RBAC 绑定缺失；token 的 group 与预设不符 |
| 证书签了但 kubelet 没拿到 | `kubectl get csr -o yaml` 看 `status.certificate` | signer usages 不匹配，写了 `CertificateFailed` |
| 服务端证书永远不轮换 | kubelet 启动参数与 gate | `--rotate-server-certificates` 未开；CSR 无人批准；**无 IP SAN 导致根本不申请** |
| 证书到期集群大面积 401 | `openssl x509 -in kubelet-client-current.pem -noout -dates` | 轮换从未成功；对比 `kubelet_client_expiration_renew_errors` |
| `kubeadm join` 报 `Unauthorized` | Secret `bootstrap-token-<id>` 是否存在、`usage-bootstrap-authentication` 是否 `"true"`、`expiration` 是否已过 | token 过期**不会**自动删除 Secret，容易被误判为有效 |
| `cluster-info` 验签失败 | `kubectl get cm cluster-info -n kube-public -o yaml` 的 `jws-kubeconfig-*` | `bootstrapsigner` 默认关闭 |
| Pod 里 token 突然失效 | `kubectl get pod <p> -o jsonpath='{.metadata.uid}'` | 绑定的 Pod 被重建导致 UID 变化，认证层直接判无效 |
| Pod 里 token 是 1 年期而不是 1 小时 | 是否由 admission 自动注入 | 是则 `+7` 哨兵 + extend-expiration 生效；手写 `spec.expirationSeconds` 才会拿到短期的 |

## Links

- [认证、授权与准入](/docs/CS/Container/k8s/acl.md)
- [kubelet](/docs/CS/Container/k8s/kubelet.md)
- [controller-manager](/docs/CS/Container/k8s/controller-manager.md)
- [apiserver](/docs/CS/Container/k8s/apiserver.md)
- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [常见问题排查](/docs/CS/Container/k8s/Issues.md)

## References

1. [Kubernetes v1.37.2 source](https://github.com/kubernetes/kubernetes/tree/v1.37.2)
2. [KEP-43: Kubelet TLS Bootstrap](https://github.com/kubernetes/enhancements/issues/43)
3. [KEP-1205: Bound Service Account Tokens](https://github.com/kubernetes/enhancements/tree/master/keps/sig-auth/1205-bound-service-account-tokens)
4. [KEP-4193: Bound Service Account Token Improvements](https://github.com/kubernetes/enhancements/tree/master/keps/sig-auth/4193-bound-service-account-token-improvements)
5. [KEP-3257: Cluster Trust Bundles](https://github.com/kubernetes/enhancements/tree/master/keps/sig-auth/3257-cluster-trust-bundles)
6. [KEP-4317: Pod Certificates](https://github.com/kubernetes/enhancements/issues/4317)
