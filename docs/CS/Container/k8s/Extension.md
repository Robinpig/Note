## Introduction

Kubernetes 之所以能成为"云原生的操作系统"，关键不在内建了多少对象，而在它把**扩展点**做成了协议：新增一种资源类型不用改 apiserver 源码，新增一种策略不用重启控制面组件，新增一种运行时不用重新编译 kubelet。

从 API 视角看，扩展分为三层，复杂度和能力依次上升：

| 层次 | 机制 | 新增的是 | 是否需要独立进程 | 典型例子 |
|---|---|---|---|---|
| 数据 | CustomResourceDefinition（CRD） | 新 GVK + 存储 | 否 | Prometheus 的 `ServiceMonitor`、Argo CD 的 `Application` |
| 行为 | Custom Controller / Operator | 调谐逻辑 | 是 | Prometheus Operator、cert-manager |
| 策略 | Admission Webhook / CEL Policy | 写入前的校验与变更 | Webhook 需要，CEL 不需要 | Istio sidecar 注入、Gatekeeper、VAP |
| API 语义 | Aggregated API Server（APIService） | 完整 REST API（含子资源、watch、protobuf） | 是 | metrics-server、K8s 云厂商扩展 |

> [!NOTE]
> 本文基于 **Kubernetes v1.36.4** 源码与官方 API 类型。CRD 类型见 `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go`，聚合层在 `staging/src/k8s.io/kube-aggregator/`，准入链在 `staging/src/k8s.io/apiserver/pkg/admission/`。

## CustomResourceDefinition

CRD 做的事情只有一件：**向 apiserver 注册一个新的 Group/Version/Kind**。注册成功后，`/apis/<group>/<version>/<plural>` 这条 REST 路径就活了，CR 的增删改查、watch、patch 都由 `apiextensions-apiserver` 通用逻辑处理，底层仍然存进 etcd。

### What a CRD Defines

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: widgets.example.com
spec:
  group: example.com
  scope: Namespaced
  names:
    plural: widgets
    singular: widget
    kind: Widget
    shortNames: [wdg]
    categories: [all]
  versions:
  - name: v1
    served: true
    storage: true
    subresources:
      status: {}
      scale:
        specReplicasPath: .spec.replicas
        statusReplicasPath: .status.replicas
    schema:
      openAPIV3Schema:
        type: object
        properties:
          spec:
            type: object
            required: [size]
            properties:
              size: {type: integer, minimum: 1, maximum: 10}
              replicas: {type: integer}
          status:
            type: object
            properties:
              readyReplicas: {type: integer}
```

几个字段值得单独说明：

- **`versions[].storage`**：多个版本时**有且只有一个**为 true（`staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go:178`）。storage 版本决定 etcd 里对象的实际编码，其它版本读写时都要转换。
- **`served`**：是否通过 REST 暴露该版本。可以先加版本、`served: false` 存着，迁移完成再打开。
- **`conversion.strategy`**：只有 `None` 和 `Webhook` 两种（同文件 `:26-37`）。`None` 要求版本间 schema 兼容（字段只增不减），否则必须上转换 webhook。
- **`subresources.status`**：开启后 `/status` 成为独立子资源，普通 update 不能改 status。没有它，控制器与用户会互相覆盖状态。
- **`subresources.scale`**：暴露 `/scale` 子资源，HPA、`kubectl scale` 才能按标准接口读写副本数。

### Structural Schema and Pruning

`apiextensions.k8s.io/v1` 要求每个版本提供 **structural schema**：根节点必须是 `type: object`，对象的每个属性都要能被 schema 完整描述，不能有"任意 JSON"的洞。这不是风格要求，而是以下功能的前提：

- **字段裁剪（pruning）**：schema 里没声明的字段，写入时直接丢弃。v1 里 `spec.preserveUnknownFields` 必须为 false（同文件 `:72`），想要保留任意字段只能在局部用 `x-kubernetes-preserve-unknown-fields: true`。
- **默认值**：`default` 只在 structural schema 上生效。
- **服务端校验**：类型、必填、枚举、范围都在 apiserver 侧完成，不依赖 webhook。
- **CEL 校验规则**：`x-kubernetes-validations` 依赖 schema 的类型信息做编译期检查。

裁剪是**静默**的：写错字段名不会报错，只会发现字段"消失"了。排查 CR 字段丢失时，第一件事就是对照 CRD 的 `openAPIV3Schema`，而不是怀疑控制器。

### Validation with CEL

CRD 支持在 schema 里写 CEL 规则，不需要额外 webhook：

```yaml
properties:
  spec:
    type: object
    x-kubernetes-validations:
    - rule: "self.replicas <= self.size * 2"
      message: "replicas must not exceed twice the size"
    properties:
      size: {type: integer}
      replicas: {type: integer}
```

`x-kubernetes-validations` 在 v1.25 GA；**CRD validation ratcheting**（对未修改字段放宽校验，避免升级 CRD 时存量对象全部非法）在 v1.33 GA 并锁定（`staging/src/k8s.io/apiextensions-apiserver/pkg/features/kube_features.go:70-74`）。

CEL 的边界要清楚：它适合**对象内部字段之间**的约束，做不了跨对象查询（比如"这个 namespace 的配额还剩多少"）。后者要么用 admission webhook，要么用带 `paramKind` 的 ValidatingAdmissionPolicy。

### Version Conversion

多版本 CRD 的读写路径：

```
客户端请求 v1beta1
   → apiserver 找到 storage 版本 v1
   → 若请求版本 != storage 版本，调用 conversion
   → 以 v1 编码写入 etcd；读回时再转成请求版本
```

`conversion.strategy: Webhook` 时，apiserver 向 `spec.conversion.webhook.clientConfig` 指定的服务发 `ConversionReview` 请求。几个运维要点：

- 转换 webhook **必须高可用**：它挂了，非 storage 版本的读写都会失败，storage 版本通常还能工作。
- webhook 必须返回**完整对象**，并保留 `metadata`（尤其是 `name`、`namespace`、`uid`）。
- 转换必须**可逆且幂等**：`v1 → v1beta1 → v1` 不能丢信息，否则每次读写循环都会漂移。
- 部署转换 webhook 本身又需要 CRD 已存在，注意启动顺序（常见做法是先 `strategy: None` 上线，再切 Webhook）。

### Deletion Semantics

删除 CRD 会**级联删除该 CRD 下的所有自定义资源**，因为存储路径随 CRD 一起消失。这是不可逆操作，`kubectl delete crd` 前必须确认：

```bash
kubectl get crd widgets.example.com -o jsonpath='{.status.acceptedNames.kind}'
kubectl get widgets.example.com --all-namespaces
```

CRD 自身也支持 finalizer。某些 Operator 会在 CRD 上挂 finalizer，先清理外部资源（云负载均衡、DNS 记录）再允许 CRD 消失；如果 finalizer 逻辑有 bug，就会看到 CRD 长期 `Terminating`，排查思路与 [删除与级联](/docs/CS/Container/k8s/Deletion.md) 中一致。

## Controller and Operator

CRD 只提供"存什么"，不提供"做什么"。一个 `Widget` 被创建后，除非有控制器监听它，否则不会有任何 Pod 被创建。**Operator = CRD + 自定义控制器 + 运维知识**，它把"人类运维手册"编码成调谐循环。

### Reconcile Loop

```go
func (r *WidgetReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
    var w examplev1.Widget
    if err := r.Get(ctx, req.NamespacedName, &w); err != nil {
        return ctrl.Result{}, client.IgnoreNotFound(err)
    }
    if !w.DeletionTimestamp.IsZero() {
        return r.finalize(ctx, &w)
    }
    desired := buildDeployment(&w)
    if err := r.createOrUpdate(ctx, &w, desired); err != nil {
        return ctrl.Result{}, err
    }
    return r.updateStatus(ctx, &w)
}
```

这段代码体现了四个不变量：

1. **读不到对象就返回成功**：对象已被删除不是错误，`IgnoreNotFound` 防止无限重试。
2. **先处理删除再看期望状态**：有 `deletionTimestamp` 时只做清理，不再创建新资源。
3. **期望状态由当前对象重新计算**：不依赖"上一次 reconcile 做到哪"，所以控制器重启、事件丢失都不影响正确性。
4. **status 单独更新**：避免与 spec 更新互相覆盖；`observedGeneration` 用来告诉用户"控制器已经看到第几代 spec"。

### Finalizers

Finalizer 是控制器参与删除的唯一正式入口：

```
用户 DELETE
  → apiserver 设置 deletionTimestamp，对象仍存在
  → 控制器看到 deletionTimestamp，清理外部资源
  → 控制器从 metadata.finalizers 移除自己的条目
  → finalizers 为空，apiserver 真正删除对象
```

常见错误是"清理逻辑失败但先把 finalizer 摘了"，结果外部资源泄漏；正确做法是清理失败就返回 error 让队列重试。反过来，finalizer 逻辑永远成功但没摘除，会看到对象永久 `Terminating`。

### Status and Conditions

Operator 的可观测性主要靠 `.status`：

- `observedGeneration`：控制器已处理的 `metadata.generation`，落后说明控制器没跟上；
- `conditions[]`：`type/status/reason/message/lastTransitionTime`，用 `metav1.Condition`；
- 领域字段：如 `readyReplicas`、`currentVersion`，供 `kubectl get` 的 printer columns 展示。

不要在 status 里写"控制器内部进度百分比"这类易失信息；status 是给用户和自动化判断的契约，不是日志。

### Leader Election and RBAC

高可用部署时，同一个 Operator 的多个副本必须开启 leader election（controller-runtime 默认支持），否则多个副本会同时创建同名资源、重复调谐。RBAC 则遵循最小权限：只授予它真正 watch/update 的 CRD 与内建资源，避免 Operator 被攻破后等于集群管理员。

### Operator vs Helm

两者经常被混为一谈：

| | Helm | Operator |
|---|---|---|
| 执行模型 | 一次性渲染并 apply | 持续调谐 |
| 状态 | Release 记录在 Secret/ConfigMap | 期望状态在 CR，实际状态在 status |
| 升级 | `helm upgrade` 触发 | 改 CR 或换 Operator 版本，控制器自己推进 |
| 适合 | 静态应用打包 | 有状态服务、需要 Day-2 运维（备份、扩缩、故障转移） |

现实中二者常组合：Helm 安装 Operator 本身，Operator 再管理 CR。

## Aggregated API Server

CRD 的 REST 语义是"通用"的：资源形状由 schema 描述，行为由 controller 补。若需要**真正的自定义 API 语义**（自定义子资源、自定义存储、protobuf、甚至非 etcd 后端），就要用聚合层。

### APIService and kube-aggregator

聚合层把外部 apiserver "挂"进主 apiserver 的 API 空间：

```yaml
apiVersion: apiregistration.k8s.io/v1
kind: APIService
metadata:
  name: v1beta1.metrics.k8s.io
spec:
  group: metrics.k8s.io
  version: v1beta1
  groupPriorityMinimum: 100
  versionPriority: 100
  service:
    name: metrics-server
    namespace: kube-system
    port: 443
  caBundle: <base64 CA>
```

请求路径仍然由主 apiserver 接收：

```
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes
  → kube-apiserver 发现该 group 由 APIService 代理
  → kube-aggregator 通过 Service 转发到 metrics-server
  → metrics-server 用自己的证书响应，aggregator 用 caBundle 校验
```

`local` 类型（`spec.service` 为空）表示由主 apiserver 进程内实现，例如 `v1.`、`apps/v1` 这些内建 API 都注册为 local。

### Availability Is Probed, Not Assumed

APIService 的 `Available` condition 由 aggregator 自己探测（`staging/src/k8s.io/kube-aggregator/pkg/controllers/status/remote/remote_available_controller.go`）：

1. Service 必须存在且暴露对应端口；
2. 该 Service 的 EndpointSlice 必须有匹配端口的就绪地址（`:257`）；
3. 真正请求一次 discovery 路径 `/apis/<group>/<version>`，**并发 5 次尝试，单次 HTTP 超时 5s，任一成功即视为可用**（`:283-355`）。

这解释了三个常见现象：

- `kubectl get apiservices` 里 `Available=False`，但 Pod 明明在跑 → 先看 Service 的 EndpointSlice 是否有地址，而不是先看 Pod 日志；
- metrics-server 刚启动时 HPA 报 `unable to fetch metrics` → 聚合层还在探测，等 `Available=True`；
- 外部 apiserver 证书 SAN 不包含 `service.namespace.svc` → 探测失败，`Available=False`，错误信息在 APIService condition 里。

### CRD or Aggregation

| 维度 | CRD | Aggregated API |
|---|---|---|
| 开发成本 | 低（YAML + controller） | 高（实现 apiserver 库、存储、版本转换） |
| API 语义 | 通用 CRUD + 可选 status/scale | 完全自定义 |
| 存储 | 固定 etcd | 可自定义 |
| 性能 | 通用路径，足够大多数场景 | 可针对性优化（如 metrics 聚合） |
| 升级风险 | 低，apiserver 内建处理 | 需自己处理多版本、证书、可用性 |
| 适用 | 99% 的 Operator | 指标、云厂商、特殊协议 API |

> [!TIP]
> 判断标准不是"哪个更强大"，而是"是否需要 CRD 表达不了的 REST 语义"。大多数团队从 CRD 起步，只有当通用 registry 成为瓶颈或语义不匹配时才考虑聚合层。

## Admission Webhooks

准入链位于"认证 + 授权通过之后、对象写入 etcd 之前"，是唯一能**修改**请求内容的扩展点。顺序固定：

```
Authentication → Authorization → Mutating admission → Validating admission → etcd
```

- Mutating webhook 可以改对象（注入 sidecar、补默认值、改镜像）；
- Validating webhook 只能放行或拒绝；
- 多个 webhook 按名称排序串行执行；Mutating 阶段支持 `reinvocationPolicy: IfNeeded`，让被后续变更影响的对象再跑一遍。

### Defaults That Bite

`pkg/apis/admissionregistration/v1/defaults.go` 给出两个关键默认值：

| 字段 | 默认 | 后果 |
|---|---|---|
| `failurePolicy` | `Fail` | webhook 不可达时，**匹配的写请求全部失败** |
| `timeoutSeconds` | 10 | 每个 webhook 最多阻塞 10s，多个串行会累加 |

`failurePolicy: Fail` 是安全默认，但也是事故来源：一个只处理 `pods` 的 webhook，如果 `rules` 写宽了（`*/*`），webhook 服务一挂，整个集群的写入都会失败，连删 Pod 都做不到。生产 webhook 必须：

- 把 `rules`、`namespaceSelector`、`objectSelector` 收窄到真正需要的范围；
- 至少 2 副本 + PDB，且不要与它拦截的工作负载放在同一节点池；
- 用 `matchConditions`（CEL）做前置过滤，减少无效调用；
- 明确设置 `sideEffects: None` 或 `NoneOnDryRun`，否则 dry-run 会被拒绝；
- 排除自己的 namespace，避免"webhook 创建 Pod 又被自己拦截"的递归。

一个最小 ValidatingWebhookConfiguration：

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: widget-validator.example.com
webhooks:
- name: widgets.example.com
  admissionReviewVersions: [v1]
  sideEffects: None
  failurePolicy: Fail
  timeoutSeconds: 5
  clientConfig:
    service:
      name: widget-webhook
      namespace: policy
      path: /validate
    caBundle: <base64 CA>
  rules:
  - apiGroups: [example.com]
    apiVersions: [v1]
    operations: [CREATE, UPDATE]
    resources: [widgets]
    scope: Namespaced
  matchConditions:
  - name: skip-system
    expression: "request.namespace != 'kube-system'"
```

### Webhook vs CEL Policy

从 v1.30 起，ValidatingAdmissionPolicy（VAP）GA；v1.36 源码里它的 feature gate 已被移除，属于无条件可用。VAP 把校验表达式交给 apiserver **进程内**的 CEL 引擎执行，没有网络往返：

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: widget-size.example.com
spec:
  matchConstraints:
    resourceRules:
    - apiGroups: [example.com]
      apiVersions: [v1]
      operations: [CREATE, UPDATE]
      resources: [widgets]
  validations:
  - expression: "object.spec.size <= 10"
    message: "size must be <= 10"
  validationActions: [Deny]
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: widget-size-binding
spec:
  policyName: widget-size.example.com
  validationActions: [Deny, Warn]
```

`validationActions` 可以组合 `Deny`、`Warn`、`Audit`（`staging/src/k8s.io/api/admissionregistration/v1/types.go:693-710`）：同一份策略可以先以 `Warn` 上线观察，再切 `Deny`。`paramKind` + `paramRef` 允许把阈值放到独立的自定义资源里，策略与参数解耦。

MutatingAdmissionPolicy 走得更远：它用 CEL 直接产出变更。v1.36 中 `MutatingAdmissionPolicy` 已是 **GA 且默认开启**（`staging/src/k8s.io/apiserver/pkg/features/kube_features.go:443-447`），变更方式支持 `ApplyConfiguration` 与 `JSONPatch`（`staging/src/k8s.io/api/admissionregistration/v1/types.go:1224-1250`）。它的价值是把"补默认值/加标签"这类简单 mutation 从 webhook 服务里搬回 apiserver，消除一个故障点。

| 维度 | Admission Webhook | Validating/MutatingAdmissionPolicy |
|---|---|---|
| 执行位置 | 外部 HTTPS 服务 | apiserver 进程内 CEL |
| 延迟 | 网络 RTT × 串行数量 | 本地求值 |
| 可用性风险 | webhook 挂 → 写请求失败 | 无外部依赖 |
| 能力 | 任意逻辑（可查外部系统） | 只能看请求/对象/参数，不能发起外部调用 |
| 适用 | sidecar 注入、复杂策略、外部授权 | 字段约束、标签强制、简单默认值 |

迁移建议：**能用 CEL 表达的规则先迁到 VAP/MAP，webhook 只保留必须访问外部系统的部分**。这样即使 webhook 故障，大部分写操作仍然可用。

## Extension Points Beyond the API

云原生的扩展不止 API 层。以下扩展点经常与 Operator 配合，但机制完全不同：

| 扩展点 | 接口/对象 | 谁调用 | 典型实现 |
|---|---|---|---|
| 容器运行时 | CRI（gRPC） | kubelet | containerd、CRI-O |
| 网络 | CNI（可执行插件） | 容器运行时 | Cilium、Calico、Flannel |
| 存储 | CSI（gRPC） | kubelet + external-attacher | 云盘、Ceph、NFS |
| 设备 | Device Plugin（gRPC） | kubelet | GPU、FPGA、RDMA |
| 调度 | Scheduler Framework 插件 | kube-scheduler | 拓扑感知、批调度 |
| 动态资源 | DRA（ResourceClaim） | kubelet + scheduler | GPU 共享、结构化参数 |

这些扩展点的共同特征是**有明确的版本化协议**，升级时要同时考虑两端兼容性；不要把它们与 CRD 混为一谈——CRD 扩展的是 API 数据面，CRI/CNI/CSI 扩展的是节点执行面。

## Links

- [Kubernetes](/docs/CS/Container/k8s/K8s.md)
- [apiserver](/docs/CS/Container/k8s/apiserver.md)
- [访问控制](/docs/CS/Container/k8s/acl.md)
- [client-go](/docs/CS/Container/k8s/client-go.md)
- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [工作负载控制器](/docs/CS/Container/k8s/Workloads.md)

## References

1. [Extend the Kubernetes API with CustomResourceDefinitions](https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/)
2. [Custom Resources](https://kubernetes.io/docs/concepts/extend-kubernetes/api-extension/custom-resources/)
3. [Operator pattern](https://kubernetes.io/docs/concepts/extend-kubernetes/operator/)
4. [Extending the Kubernetes API with the aggregation layer](https://kubernetes.io/docs/concepts/extend-kubernetes/api-extension/apiserver-aggregation/)
5. [Extensible Admission Controllers](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/)
6. [ValidatingAdmissionPolicy](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/)
