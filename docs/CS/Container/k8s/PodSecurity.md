## Introduction

Pod Security Standards (PSS) 是 K8s 原生的**工作负载安全基线**，定义三档安全等级，并通过内置的 **Pod Security Admission (PSA)** 在命名空间级强制执行。它替代了已被移除的 PodSecurityPolicy (PSP)。

PSP 历史：`PodSecurityPolicy` 是集群级 admission，复杂易错；v1.21 弃用、**v1.25 移除**；PSA 在 v1.23 beta、v1.25 随 PSP 移除一同 GA。当前（v1.36）PSA 默认开启但默认 `mode: "privileged"`（即不强制），需显式给 ns 打标签才生效。

## Three Levels

| 档 | 定位 | 关键约束 |
| :--- | :--- | :--- |
| **Privileged** | 完全放开 | 给系统组件 / CNI / CSI 等基础设施用；无限制 |
| **Baseline** | 禁止已知危险能力 | 禁 host namespace、特权容器、`hostPath`、危险 volume、`hostPort`、危险能力，普通应用够用 |
| **Restricted** | 最严、加固 | 在 Baseline 基础上：必须 `runAsNonRoot`、`seccompProfile: RuntimeDefault`、drop ALL capabilities、`allowPrivilegeEscalation: false`、非 root 用户、仅允许特定 volume 类型；适合高安全 |

## Enforcement via Namespace Labels

PSA 用命名空间标签声明，三种 mode 可分别设不同档：

```yaml
pod-security.kubernetes.io/enforce: restricted   # 违反直接拒绝创建
pod-security.kubernetes.io/audit:   baseline      # 违反记审计事件
pod-security.kubernetes.io/warn:    restricted    # 违反给 kubectl 警告
```

mode：`enforce`（拒绝）/ `audit`（记事件）/ `warn`（警告）。level：`privileged` / `baseline` / `restricted`，可加版本如 `restricted:latest` 或 `restricted:v1.30`。

> [!TIP]
> 常用做法：先 `warn`+`audit=baseline` 评估存量 workload 违规，再逐步把 `enforce` 升到 `restricted`。系统 ns（kube-system）通常豁免（`exempt`）。

## PSS vs securityContext

PSS 是**准入基线检查**，它校验的是 Pod/container 的 `securityContext` 字段是否满足档位要求；`securityContext` 才是真正落到容器的能力声明：

| securityContext 字段 | Restricted 要求 |
| :--- | :--- |
| `runAsNonRoot` | `true` |
| `runAsUser` | 非 0 |
| `allowPrivilegeEscalation` | `false` |
| `capabilities.drop` | 含 `ALL` |
| `seccompProfile.type` | `RuntimeDefault` 或 `localhostProfile` |
| `privileged` | 禁止 |

两者互补：securityContext 写"要什么"，PSS 保证"不许超标"。

## How It Differs From acl / NetworkPolicy

| 机制 | 管的什么 | 层次 |
| :--- | :--- | :--- |
| [acl](/docs/CS/Container/k8s/acl.md) | 谁能调哪些 API（身份/授权） | 集群 API 准入前 |
| PSS（本页） | Pod 能有什么能力（特权/用户/能力） | 工作负载 admission |
| [NetworkPolicy](/docs/CS/Container/k8s/NetworkPolicy.md) | Pod 间流量 | 网络层 |

三者是正交的三道防线：身份（谁能操作）→ 工作负载能力（Pod 多危险）→ 网络（Pod 间通不通）。

## Beyond PSS: Policy Engines

PSS 覆盖的是"基线三档"。需要更细的策略（如禁止某镜像仓库、限制 label、自定义 mutate）用[准入 Webhook](/docs/CS/Container/k8s/Extension.md)：Kyverno、OPA Gatekeeper。PSP 的复杂场景多数迁移到这两个。

## Links

- [集群访问控制 acl](/docs/CS/Container/k8s/acl.md)
- [NetworkPolicy](/docs/CS/Container/k8s/NetworkPolicy.md)
- [Pod 与 securityContext](/docs/CS/Container/k8s/Pod.md)
- [扩展机制与准入 Webhook](/docs/CS/Container/k8s/Extension.md)
- [Docker 安全](/docs/CS/Container/Docker/security.md)

## References

1. [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
2. [Pod Security Admission](https://kubernetes.io/docs/concepts/security/pod-security-admission/)
3. [Migrate from PodSecurityPolicy](https://kubernetes.io/docs/tasks/administer-cluster/migrate-from-podsecuritypolicy/)
