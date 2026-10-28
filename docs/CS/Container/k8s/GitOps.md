## Introduction

GitOps 把 **Git 仓库作为集群期望状态的唯一来源**，由集群内的控制器持续把实际状态拉回期望状态。它解决的不是"怎么把 YAML 发到集群"——`kubectl apply` 和 CI 推送早就能做——而是三个更难的问题：

1. **谁改了什么**：所有变更都经过 Git 的 review、审计与回滚；
2. **集群是否漂移**：控制器持续对账，手工改动会被发现并纠正；
3. **灾难恢复**：新集群只要能访问 Git，就能重建出同样的状态。

OpenGitOps 给出的四条原则是：

1. **Declarative**：系统状态以声明方式描述；
2. **Versioned and Immutable**：期望状态存在版本化、不可变的存储中（通常是 Git）；
3. **Pulled Automatically**：软件代理自动拉取期望状态；
4. **Continuously Reconciled**：代理持续观察实际状态并向期望状态收敛。

> [!NOTE]
> 本文的 Argo CD 事实基于 **v3.5.6**（2026-10-20 发布），Flux 基于 **v2.9.6**，Kustomize 基于 **v5.8.3**。三者都是当前主线版本；CRD 字段以源码为准，示例只保留最小可用字段。

## Push, Pull, and the Source of Truth

传统 CI 推送模型：

```
开发提交 → CI 构建镜像 → CI 执行 kubectl apply/helm upgrade → 集群
```

GitOps 拉取模型：

```
开发提交 → CI 构建镜像并把新版本写回 Git（或只改 tag）
                              │
                              ▼
                     Git 仓库（期望状态）
                              │  watch/poll
                              ▼
               集群内控制器（Argo CD / Flux）→ 集群
```

差别不只是方向：

| 维度 | CI Push | GitOps Pull |
|---|---|---|
| 集群凭证 | CI 持有高权限 kubeconfig | 凭证留在集群内，CI 不碰集群 |
| 漂移检测 | 无（下一次 apply 才知道） | 持续对账 |
| 回滚 | 重跑流水线或 `kubectl rollout undo` | `git revert` |
| 审计 | CI 日志 | Git 历史 |
| 网络要求 | CI 能访问集群 API | 集群能访问 Git（或通过代理） |

> [!WARNING]
> "CI 里跑 `kubectl apply`"不是 GitOps，只是把命令换了地方执行。真正的 GitOps 要求**集群内的 agent 拉取**，并且**没有第二个写入者**。如果 CI 和控制器同时写集群，漂移检测会变成互相打架。

## Kustomize: The Rendering Layer

GitOps 仓库里通常不放"渲染后的最终 YAML"，而是放 **base + overlay**，由 Kustomize 在同步时渲染。这样环境差异只写在 overlay 里，base 保持单一事实来源。

```
apps/payment/
├── base/
│   ├── kustomization.yaml
│   ├── deployment.yaml
│   └── service.yaml
└── overlays/
    ├── staging/
    │   ├── kustomization.yaml
    │   └── replicas-patch.yaml
    └── prod/
        ├── kustomization.yaml
        └── resources-patch.yaml
```

```yaml
# overlays/prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
- ../../base
images:
- name: registry.example.com/payment
  newTag: v2.3.1
replicas:
- name: payment
  count: 6
patches:
- path: resources-patch.yaml
```

本地渲染与直接应用：

```bash
kubectl kustomize apps/payment/overlays/prod   # 只渲染
kubectl apply -k apps/payment/overlays/prod    # 渲染并 apply
```

`kubectl apply -k` 内置了 Kustomize（K8s 1.36 内置 Kustomize v5 系列），不需要单独安装 `kustomize` 二进制；但**版本可能与独立二进制不同**，CI 与集群侧渲染结果要以同一版本为准，否则会出现"本地 diff 干净、同步后字段不同"的假象。

Kustomize 与 Helm 的分工：

| | Kustomize | Helm |
|---|---|---|
| 模板能力 | patch/overlay，无逻辑分支 | Go template，可条件/循环 |
| 版本化发布单元 | 无（直接 apply 资源） | Release + revision |
| 适合 | 环境差异小、平台团队统一基线 | 需要参数化、作为产品分发 |
| GitOps 中 | 控制器直接渲染 | 控制器调 Helm SDK 渲染成资源 |

二者可以组合：Helm 负责打包第三方应用，Kustomize 负责给渲染结果打环境补丁。

## Argo CD

Argo CD 是"以 Application 为中心"的 GitOps 控制器：一个 `Application` 描述"哪份 Git 内容 → 哪个集群/namespace"，控制器对比 Git 渲染结果与集群实际状态，计算同步计划。

### Application and AppProject

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: payment-prod
  namespace: argocd
spec:
  project: payment
  source:
    repoURL: https://github.com/example/platform.git
    targetRevision: main
    path: apps/payment/overlays/prod
  destination:
    server: https://kubernetes.default.svc
    namespace: payment
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
```

关键字段（`pkg/apis/application/v1/types.go`）：

- `source.path` 指向**渲染入口**（Kustomize 目录或 Helm chart 目录），不是单个 YAML；
- `syncPolicy.automated.prune`：删除 Git 中已移除、集群中仍存在的资源；
- `syncPolicy.automated.selfHeal`：集群内手工改动偏离 Git 时自动改回；
- **`prune` 与 `selfHeal` 默认都是 false**（`pkg/apis/application/v1/types.go:1421`、`:1611-1614`），必须显式开启。这是安全默认，也是"为什么手工改了没被纠正"的答案；
- `revisionHistoryLimit` 默认 10（同文件 `:91-96`）。

`AppProject` 是权限边界：限制允许的 `sourceRepos`、`destinations`，以及可创建的集群级资源白名单（`pkg/apis/application/v1/types.go:2834-2847`）。多团队共享一个 Argo CD 时，**没有 AppProject 隔离等于所有人共用 cluster-admin**。

### Sync, Health, and Drift

Argo CD 把"状态"拆成两个正交维度：

| 维度 | 含义 | 典型值 |
|---|---|---|
| Sync Status | Git 期望 vs 集群实际是否一致 | Synced / OutOfSync / Unknown |
| Health Status | 资源本身是否健康 | Healthy / Progressing / Degraded / Missing |

`OutOfSync` 不等于故障：可能只是有人手工改了副本数，或 Git 刚提交还没同步。反过来，`Synced` 也不等于健康：应用可能已经 `CrashLoopBackOff`，但清单与 Git 完全一致。排障时要两个维度一起看。

同步的粒度是**资源**，不是"整个 Application 原子提交"。Argo CD 支持 sync waves（`argocd.argoproj.io/sync-wave` 注解）控制资源顺序，支持 `Hook` 在同步前后执行 Job；但一个资源失败不会自动回滚已经成功的资源，除非配置了 `FailOnSharedResource` 或使用 Rollback 手动回退。

### ApplicationSet

当"每个环境/每个团队/每个集群一个 Application"时，手写 Application 会爆炸。ApplicationSet 用 generator（Git 目录、集群列表、PR、矩阵）批量生成 Application，是平台团队做"多集群分发"的标准做法。

## Flux

Flux 是"以控制器拆分职责"的 GitOps 实现。v2 由一组独立控制器组成（`flux2` 仓库 `manifests/bases/`）：

| 控制器 | 职责 |
|---|---|
| source-controller | 拉取 Git/OCI/Helm/Bucket，产出 artifact |
| kustomize-controller | 渲染 Kustomization 并 apply |
| helm-controller | 管理 HelmRelease |
| notification-controller | 发送事件/告警，接收 webhook |
| image-reflector-controller | 扫描镜像仓库 tag |
| image-automation-controller | 把新 tag 写回 Git |
| source-watcher | 监听源变更（v2.9 新增） |

一条典型的 Flux 链路：

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: platform
  namespace: flux-system
spec:
  url: https://github.com/example/platform.git
  interval: 1m
  ref:
    branch: main
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: payment-prod
  namespace: flux-system
spec:
  interval: 10m
  path: ./apps/payment/overlays/prod
  prune: true
  sourceRef:
    kind: GitRepository
    name: platform
  targetNamespace: payment
```

`Kustomization` 的关键字段（`fluxcd/kustomize-controller/api/v1/kustomization_types.go:68-173`）：

- `interval`：对账周期；
- `path`：仓库内渲染目录；
- `prune`：删除 Git 中已移除的资源（默认 false）；
- `force`：不可变字段变更时重建资源（可能造成中断，慎用）；
- `sourceRef`：指向 `GitRepository`/`OCIRepository` 等源对象。

Helm 由 `HelmRelease` 管理（`fluxcd/helm-controller/api/v2/helmrelease_types.go:49-173`）：`chart`/`chartRef` 指定 chart 源，`interval` 控制调谐，`valuesFrom` 引用 ConfigMap/Secret 提供 values，`driftDetection` 检测集群内 Helm release 的漂移，`upgrade`/`rollback` 控制失败策略。Flux 的 Helm 实现调用 Helm SDK，**不依赖 Helm CLI，也不使用 `helm install` 的 release secret 作为唯一状态**。

## Continuous Reconciliation and Drift

两种实现的对账语义高度一致，但默认行为不同：

| 行为 | Argo CD | Flux |
|---|---|---|
| 自动同步 | 需显式 `automated: {}`，默认手动 | 控制器默认持续对账 |
| 漂移纠正 | `selfHeal: true` 才改回 | 默认按期望状态 apply，漂移会被覆盖 |
| 删除 Git 中移除的资源 | `prune: true` | `prune: true` |
| 不可变字段冲突 | 同步失败，需人工处理 | `force: true` 可重建 |
| 状态展示 | UI/CRD status 双维度 | 事件 + condition |

漂移检测的边界要清楚：控制器只比较**它管理的资源**。由 HPA 改写的 `replicas`、由 VPA 改写的 requests、由 Operator 写入的 status，都是"合法漂移"，必须通过 `ignoreDifferences`（Argo CD）或 `spec.ignoreDifferences`（Flux Kustomization）排除，否则控制器会与 HPA 无限互相覆盖。

## Progressive Delivery

GitOps 解决"最终状态从哪来"，不解决"怎么安全地到达"。渐进式发布把一次全量替换拆成可观测、可中止的步骤：

- **Argo Rollouts**：用 `Rollout` 替代 Deployment，支持 canary（按步长放量、暂停、分析）、blue-green（先切流量再删旧版本），AnalysisTemplate 可接 Prometheus 指标自动判定成功/失败；
- **Flagger**：以 Deployment 为源，自动创建 canary Deployment 与 Service，按指标逐步放量，支持 Istio、Linkerd、NGINX、Gateway API 等流量提供方。

它们与 GitOps 的分工是：Git 提交触发 Argo CD/Flux 同步 → 同步创建/更新 Rollout/Deployment → 渐进式控制器接管后续放量。**不要用 GitOps 控制器直接控制流量比例**，那会把发布状态写回 Git，破坏"Git 是期望状态"的单一来源。

七层流量的按权重/按 header 切分见 [Ingress](/docs/CS/Container/k8s/Ingress.md)。

## Secrets in Git

GitOps 的前提是"Git 里什么都有"，但 Secret 不能明文入库。三种主流做法：

| 方案 | 原理 | 密钥在哪 |
|---|---|---|
| Sealed Secrets | 用集群公钥加密，控制器用私钥解密 | 私钥在集群内 |
| SOPS | 文件级加密，Git 里存密文 | KMS/age/PGP |
| External Secrets Operator | Git 只存引用，运行时从外部拉取 | 外部 Secret Manager |

选择标准：**密钥轮换是否需要改 Git**。External Secrets 轮换时 Git 不变；Sealed Secrets/SOPS 需要重新加密并提交。多集群场景下，Sealed Secrets 的密钥按集群隔离，不能跨集群复用。

## Anti-Patterns

- **把 Git 当备份，实际仍由 CI 推送**：审计与漂移检测都失效。
- **两个写入者**：Argo CD/Flux 与 CI/人工同时 apply，`OutOfSync` 永远消不掉。
- **`prune: true` + 渲染结果不稳定**：模板随机值、时间戳、动态名字会导致每次同步都删了再建。
- **在 Git 里存 `kubectl` 生成的完整清单**：包含 `status`、`resourceVersion`、集群分配的字段，越同步越乱；只存期望字段。
- **环境靠手工改**：staging/prod 的差异必须收敛到 overlay 或 values，否则下一个环境无法重建。
- **忽略 CRD 的升级顺序**：CRD 与 Operator 必须"先 CRD 后控制器"，Argo CD 可用 sync wave 表达，Flux 可用依赖 `dependsOn` 表达。
- **把密钥明文放进 Git**：即使仓库私有，历史也会永久保留。

## Links

- [Helm](/docs/CS/Container/k8s/Helm.md)
- [kubectl](/docs/CS/Container/k8s/kubectl.md)
- [Ingress](/docs/CS/Container/k8s/Ingress.md)
- [Workloads](/docs/CS/Container/k8s/Workloads.md)
- [Extension](/docs/CS/Container/k8s/Extension.md)
- [Kubernetes](/docs/CS/Container/k8s/K8s.md)

## References

1. [OpenGitOps Principles](https://opengitops.dev/)
2. [Argo CD Documentation](https://argo-cd.readthedocs.io/)
3. [Flux Documentation](https://fluxcd.io/flux/)
4. [Kustomize Documentation](https://kustomize.io/)
5. [Argo Rollouts](https://argoproj.github.io/rollouts/)
6. [Flagger](https://flagger.app/)
