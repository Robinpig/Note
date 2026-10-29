## Introduction

PodDisruptionBudget (PDB) 保护**自愿中断（voluntary disruption）**期间应用的可用性：在节点维护、驱逐（eviction）、集群缩容（Cluster Autoscaler）、滚动升级期间，保证"同一时刻最多有多少副本不可用"。

**自愿中断 vs 非自愿中断**：

- **自愿**：drain、驱逐、节点升级、CA 缩容——apiserver 会先查 PDB。
- **非自愿**：节点崩、内核 panic、kubelet 失联、硬件故障、OOM——PDB **管不了**。这类靠多副本 + 反亲和 + 跨 AZ 调度来扛。

> [!TIP]
> PDB 只约束"主动动节点"的操作，不保证"绝不丢流量"。要平滑还要配合 readinessProbe + 滚动更新 + preStop，见 [Pod 优雅终止](/docs/CS/Container/k8s/Pod.md)。

## How It Works

apiserver 的 eviction 子系统在真正删除 Pod 前，会计算"若删除后，该 PDB 选中的 Pod 集合是否还满足预算"：

- 满足 → 允许删除；
- 不满足 → 返回 `429 Too Many Requests`，操作稍后重试。

因此 `kubectl drain` 一个节点时，如果 PDB 不允许再少一个副本，drain 会卡住等待（直到有副本在别处起来，或强制 `--force --grace-period=0`——后者会**无视 PDB**，危险）。

## Two Forms

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata: { name: app-pdb }
spec:
  minAvailable: 2          # 至少 2 个副本必须可用（绝对值或百分比）
  selector:
    matchLabels: { app: app }
```

或

```yaml
spec:
  maxUnavailable: 1        # 最多允许 1 个不可用（百分比或绝对值）
  selector:
    matchLabels: { app: app }
```

- `minAvailable`：保证可用下限（所有 Pod 对象类型都能用）。
- `maxUnavailable`：允许的中断上限，`policy/v1` GA；早期只有 Deployment/ReplicaSet/StatefulSet 等"带副本集"的控制器支持。
- 二者**二选一**，不能同时写。

## Pitfalls

- **PDB 过严会卡死运维**：`minAvailable: 100%` 或 `maxUnavailable: 0` 等于禁止任何自愿中断，drain 节点或 CA 缩容会永久挂起。
- **与 CA 缩容死锁**：节点空闲但该节点上 Pod 受 PDB 保护、且全集群没有其它地方能放下，CA 无法缩容，节点空转烧钱。
- **多个 PDB 选同一 Pod 冲突**：一个 Pod 只能被一个 PDB 选中，多个 PDB selector 重叠会校验失败。
- **PDB 不影响节点故障**：节点直接宕机，Pod 立刻没了，PDB 无法阻止，只能靠副本分布（topologySpread / 反亲和）。
- **滚动更新与 PDB 交互**：滚动更新由控制器自己管副本数，不走 eviction；但滚动更新同时节点维护时，两者叠加可能短暂低于预算。

## Links

- [节点压力驱逐](/docs/CS/Container/k8s/Eviction.md)
- [弹性扩缩容 HPA/CA](/docs/CS/Container/k8s/Scaling.md)
- [Pod 优雅终止](/docs/CS/Container/k8s/Pod.md)
- [工作负载控制器](/docs/CS/Container/k8s/Workloads.md)

## References

1. [Pod Disruption Budgets](https://kubernetes.io/docs/tasks/run-application/configure-pdb/)
2. [Safely Drain a Node](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)
