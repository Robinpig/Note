## Introduction

K8s 集群是一个具有严格访问控制机制的安全系统。无论是 K8s 内部组件、集群用户，亦或者是用户部署的 Pod 应用，都必须遵循以下基本安全原则：

- 所有请求都要经过认证（Authentication），确认"你是谁"；
- 认证通过后要经过授权（Authorization），确认"你能做什么"；
- 部分请求还要经过准入控制（Admission Control），对对象进行校验与修改；
- 默认拒绝：任何一条链路失败，请求都会被拒绝。

三道关卡由 [apiserver](/docs/CS/Container/k8s/apiserver.md) 统一执行，处理顺序为：

```
请求 → Authentication → Authorization → Admission Control → 写入 etcd
```

## Authentication

K8s 集群采用了基于数字证书的认证机制。认证方式是"或"的关系，任一方式通过即可，主要分为两类：

- **人类用户**：通常是 X.509 客户端证书（kubeadm 集群中 `/etc/kubernetes/pki/ca.crt` 签发的证书，CN 即用户名、O 即用户组）；也可对接 OIDC（对接企业 SSO）、Bootstrap Token 等。
- **Service Account**：Pod 内进程的身份。Token 由 apiserver 签发（v1.24+ 改为 TokenRequest API 签发有时限的 JWT），以 Volume 挂载进 Pod。

两类身份的关键区别：用户不对应任何 API 对象（kube-apiserver 只读不存），而 ServiceAccount 是 namespace 内的真实资源对象，可以被 RBAC 引用。

这里有三点值得展开，细节见 [身份与证书](/docs/CS/Container/k8s/Identity.md)：

- **Bootstrap Token 是节点自己给自己换第一份证书的凭据**，格式 `<6位id>.<16位secret>`，存在 `kube-system/bootstrap-token-<id>` 这个 Secret 里，认证后身份是 `system:bootstrap:<id>`。它权限极窄——默认只有"提交 CSR"这一条路。
- **x509 客户端证书的信任根与 SA token 的信任根互不相干**：前者由 `--client-ca-file` 校验，后者由 `--service-account-key-file` 校验，是两套密钥。
- **自动创建永不过期的 SA Secret 已经移除，但边角还在**：手工创建的 `kubernetes.io/service-account-token` Secret 仍会被填入 token 并被认证；而 Pod 里挂载的早已是限时 token（admission 注入 `expirationSeconds: 3607`，配合默认开启的 extend-expiration 逻辑实际延长到 1 年）。

## Authorization

认证回答"你是谁"，授权回答"你能对哪个资源的哪个动作"。内置的授权模式：

| 模式 | 原理 | 适用场景 |
|------|------|---------|
| RBAC | 基于 Role/ClusterRole 与 RoleBinding/ClusterRoleBinding 的四对象模型 | 生产默认选择 |
| ABAC | 基于 JSON 策略文件 | 已过时，改策略需重启 apiserver |
| Node | kubelet 专用，只允许读自身关联的 Pod/Secret 等 | 内部组件 |
| Webhook | 委托外部服务决策 | 对接企业权限系统 |

RBAC 的四个对象中，**Role/RoleBinding 受 namespace 限制，ClusterRole/ClusterRoleBinding 是集群级**；ClusterRole 也可以通过 RoleBinding 在某个 namespace 内"降级"复用。授权判定是并集关系：命中任一规则即放行。

典型最小权限示例：

```yaml
kind: Role
apiVersion: rbac.authorization.k8s.io/v1
metadata:
  namespace: dev
  name: pod-reader
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
---
kind: RoleBinding
apiVersion: rbac.authorization.k8s.io/v1
metadata:
  namespace: dev
  name: read-pods
subjects:
- kind: ServiceAccount
  name: ci-bot
  namespace: dev
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

## Admission Control

准入控制作用于"对象写入 etcd 之前"，可以**修改**请求（Mutating）或**拒绝**请求（Validating）：

- 内置插件：`NamespaceLifecycle`（向不存在的 namespace 创建对象会被拒）、`ResourceQuota`（配额检查）、`LimitRanger`（注入默认资源限制）、`ServiceAccount`（自动挂载 SA token）等。
- 动态扩展：**Admission Webhook**（MutatingWebhookConfiguration / ValidatingWebhookConfiguration），是 Istio sidecar 自动注入、OPA Gatekeeper 策略引擎的实现基础。

在请求里的位置：认证与授权都在 filter chain 里完成，而准入发生在 **REST handler 内部**——对象解码之后、写 etcd 之前，且 mutating 与 validating 被拆在两处。完整链路见 [apiserver 写路径](/docs/CS/Container/k8s/apiserver.md?id=write-path)。

### Execution Order Is a Table, Not Registration Order

准入插件的执行顺序由一张**硬编码顺序表**决定（`pkg/kubeapiserver/options/plugins.go:74`）：

```go
// AllOrderedPlugins is the list of all the plugins in order.
var AllOrderedPlugins = []string{
	admit.PluginName,                        // AlwaysAdmit
	lifecycle.PluginName,                    // NamespaceLifecycle
	...
	// new admission plugins should generally be inserted above here
	// webhook, resourcequota, and deny plugins must go at the end
	mutatingadmissionpolicy.PluginName,   // MutatingAdmissionPolicy
	mutatingwebhook.PluginName,           // MutatingAdmissionWebhook
	validatingadmissionpolicy.PluginName, // ValidatingAdmissionPolicy
	validatingwebhook.PluginName,         // ValidatingAdmissionWebhook
	resourcequota.PluginName,             // ResourceQuota
	deny.PluginName,                      // AlwaysDeny
}

// :128
// The order of registration is irrelevant, see AllOrderedPlugins for execution order.
```

三个结论：

1. **注册顺序与执行顺序无关**，各插件包里 `Register` 的先后不影响任何事；
2. **webhook、resourcequota、deny 必须排在最后**——表末尾的注释是给插件作者看的约束，因为配额检查必须看到对象被所有 mutating 改完后的最终形态；
3. 新增插件原则上插到"webhook 之前"那一档，不能插到末尾。

### Default On / Off

默认开启集合同样是硬编码（`:170`），共 24 个，**其余全部默认关闭**。值得留意的两点：

- `NodeRestriction` **不在默认开启集合里**。它是 kubelet 权限收敛的关键插件，实践中由发行版或 kubeadm 显式加上；如果自己拼 apiserver 启动参数而照抄"默认"，会漏掉它。
- 一批插件即便进了默认开启集合，仍受 feature gate 二次控制，例如 `ValidatingAdmissionPolicy`、`MutatingAdmissionPolicy`、`PodResizeValidator`（`InPlacePodVerticalScaling`）、`JobValidation`（`WorkloadWithJob`）、`PodTopologyLabels`（`PodTopologyLabelsAdmission`）。**列在默认开启里不等于一定生效**，还要看 gate。

v1.36 新增的准入插件：`PodGroupProtection`、`PodGroupWorkloadExists`、`NodeDeclaredFeatureValidator`、`JobValidation`、`PodResizeValidator`。

## Authorization Chain Details

多个 authorizer 组合成 union：任一返回 Allow 即放行，全部 NoOpinion 才算拒绝——**是并集不是交集**。所以加一个宽松的 webhook 会直接把已有的 RBAC 约束架空，这是配置多模式时最常见的翻车方式。

被聚合的（delegated）apiserver 走 `DelegatingAuthorizationOptions`，其中几条默认值值得知道（`staging/src/k8s.io/apiserver/pkg/server/options/authorization.go:78`）：

| 项 | 默认值 | 说明 |
|---|---|---|
| `AlwaysAllowPaths` | `/healthz`、`/readyz`、`/livez` | 探活接口免鉴权，否则 kubelet 探活自己会先被鉴权卡住 |
| `AlwaysAllowGroups` | `system:masters` | 源码注释说明这是硬编码 authorizer，避免管理员把自己锁在门外 |
| `AllowCacheTTL` / `DenyCacheTTL` | 10s / 10s | webhook 鉴权结果的缓存时长 |
| `ClientTimeout` | 10s | 向 `SubjectAccessReview` 发起请求的超时 |

## Pod Access Control

Pod 内应用访问 apiserver 时默认携带挂载的 ServiceAccount token，权限由对应 RBAC 决定。生产实践中通常通过 automountServiceAccountToken: false 关闭默认挂载，仅给确实需要访问 apiserver 的 Pod（如 operator）配置最小权限。

## Links

- [apiserver](/docs/CS/Container/k8s/apiserver.md)
- [身份与证书](/docs/CS/Container/k8s/Identity.md)
- [Pod Security Standards](/docs/CS/Container/k8s/PodSecurity.md)
- [ResourceQuota 与配额计量](/docs/CS/Container/k8s/Resource.md)
- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [Istio](/docs/CS/Framework/Istio/Istio.md)

## References

1. [Controlling Access to the Kubernetes API](https://kubernetes.io/docs/concepts/security/controlling-access/)
2. [Using Admission Controllers](https://kubernetes.io/docs/reference/access-authn-authz/admission-controllers/)
3. [Dynamic Admission Control](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/)
4. [Using RBAC Authorization](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
5. [Using Node Authorization](https://kubernetes.io/docs/reference/access-authn-authz/node/)
