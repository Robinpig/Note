## Introduction

Kubernetes 的资源模型解决两件事：**调度时给 Pod 保证多少资源**（`requests`），和**运行时最多允许用多少**（`limits`）。两者都写在容器级 `resources` 字段，kubelet 再换算成 [Cgroup](/docs/CS/OS/Linux/cgroup.md) 限制落到内核。

```yaml
resources:
  requests:
    cpu: 100m        # 调度依据 + 保证下限
    memory: 128Mi
  limits:
    cpu: 500m        # 硬上限（超了被限流）
    memory: 256Mi    # 硬上限（超了被 OOMKill）
```

- **requests**：调度器按"节点已分配 requests 之和 + 本 Pod requests"判断是否放得下；也是 kubelet 给 cgroup 设的**保证下限**（被压缩时最后才被抢）。
- **limits**：运行时上限。CPU 超限只被 CFS 限流（throttle），**不会被杀**；内存超限被 OOMKill（退出码 137），因为内存不可压缩。

> [!TIP]
> CPU 用"可压缩资源"、内存用"不可压缩资源"——这是后面所有调度、QoS、驱逐行为的根。CPU 超了只是慢，内存超了直接死。

## CPU vs Memory Semantics

| 资源 | requests 的作用 | limits 超限后果 | 底层机制 |
| :--- | :--- | :--- | :--- |
| CPU | 调度依据；cgroup `cpu.shares` 权重下限 | CFS quota 限流（throttle，不杀） | CFS bandwidth control |
| 内存 | 调度依据；cgroup `memory.min` 保护 | OOMKill（137） | cgroup memory limit + OOM killer |

CPU 单位：`1` = 1 核，`100m` = 0.1 核（100 millicpu）；也可写 `"0.5"`。`limits.cpu` 在容器里表现为 CFS quota，突发会被平滑限制而非终止。

## QoS Classes

QoS（服务质量）是 kubelet 给 Pod 打的**单档标签**，决定节点内存压力下谁先死，也决定 `oom_score_adj`。完整三档与 OOM 被杀排序见 [Pod](/docs/CS/Container/k8s/Pod.md?id=resources-and-qos)；这里只列结论：

| QoS | 判定 | 节点内存压力下被杀优先级 |
| :--- | :--- | :--- |
| Guaranteed | 每个容器 `requests == limits`（CPU、内存都设且相等） | 最低 |
| Burstable | 至少一个容器设了 request 但不满足 Guaranteed | 中间 |
| BestEffort | 什么都没设 | 最高（最先被杀） |

> [!WARNING]
> 两件容易混的事：**内核 OOM killer 按 QoS（`oom_score_adj`）挑 victim**，但 **kubelet 节点压力驱逐不按 QoS**——它按"是否超自身 request → priority → 绝对用量"排序。两者是两套独立的"内存不足时杀谁"机制，详见 [Eviction](/docs/CS/Container/k8s/Eviction.md)。

## LimitRange

`LimitRange` 是 **namespace 级**的护栏：给该 ns 内新建的 Pod/容器**补默认值**、并**设上下限**，防止有人不写 requests/limits 或写得太离谱。

```yaml
apiVersion: v1
kind: LimitRange
metadata: { name: mem-limit, namespace: prod }
spec:
  limits:
    - type: Container
      default:            # 不写 limits 时补的 limit
        memory: 512Mi
        cpu: 500m
      defaultRequest:     # 不写 requests 时补的 request
        memory: 256Mi
        cpu: 100m
      max:                 # 单容器上限
        memory: 1Gi
        cpu: "1"
      min:
        memory: 64Mi
        cpu: 50m
      maxLimitRequestRatio:   # limit/request 比值上限（防超卖）
        memory: 4
        cpu: 4
```

`type` 支持 `Container` / `Pod` / `PersistentVolumeClaim`。注意：**LimitRange 只作用于新建对象**；已存在的 Pod 不受影响。它为 ResourceQuota 提供了"没有 request 时从哪补"的依据。

## ResourceQuota

`ResourceQuota` 也是 **namespace 级**，但管的是**总量**：限制一个 ns 内能用掉多少计算资源、能建多少对象。

```yaml
apiVersion: v1
kind: ResourceQuota
metadata: { name: compute-quota, namespace: prod }
spec:
  hard:
    requests.cpu: "10"
    requests.memory: 20Gi
    limits.cpu: "20"
    limits.memory: 40Gi
    pods: "20"
    services: "10"
    count/deployments.apps: "5"
```

要点：

- 配额按 `requests.cpu` / `limits.memory` 等**资源名**分别计；一个 ns 的累计 requests 不能超 `requests.*`，累计 limits 不能超 `limits.*`。
- 一旦 ns 设了 `requests.cpu` 这类配额，该 ns 内**每个 Pod 都必须显式写对应 requests/limits**，否则 admission 直接拒绝创建——此时靠 `LimitRange` 的 `defaultRequest`/`default` 自动补上最省心。
- 可按 `scopeSelector` / `scopes` 只对特定范围的对象生效（如 `Terminating`、`BestEffort`），实现"BestEffort Pod 总数上限"。

## Quota, LimitRange and Scheduler

三者的协作链路：

```
Pod 创建
 ├─ LimitRange 补默认 requests/limits（若没写）
 ├─ ResourceQuota admission 校验累计是否超限 → 超了拒绝
 └─ scheduler 按 requests 选节点（节点 Allocatable 视角）
       节点 Allocatable = Capacity - kube-reserved - system-reserved - eviction-threshold
```

- 调度看的是节点 **Allocatable** 而非 Capacity，reserved 与驱逐阈值被先扣掉，避免节点被打满到无法运维。
- `NodeResourcesFit` 默认 `LeastAllocated` 策略：把 Pod 往"剩余比例高"的节点放，倾向分散；想"装箱"省节点可切 `MostAllocated`（配合 Cluster Autoscaler 缩容）。
- 没有 request 的 BestEffort Pod 不占调度账本，但 OOM 时最先死——生产应尽量避免。

## Observability

- `kubectl top pod/node` 来自 `metrics.k8s.io`（由 metrics-server 提供，需单独装），看的是**实际用量**而非 requests/limits。
- 用量经 [client-go](/docs/CS/Container/k8s/client-go.md) 的 metrics 接口喂给 [HPA](/docs/CS/Container/k8s/Scaling.md) 做弹性。
- 配额占用可 `kubectl describe quota -n <ns>` 看 `Used/Limited`。

## Links

- [Pod 与 QoS](/docs/CS/Container/k8s/Pod.md)
- [调度器](/docs/CS/Container/k8s/scheduler.md)
- [节点压力驱逐](/docs/CS/Container/k8s/Eviction.md)
- [弹性扩缩容 HPA](/docs/CS/Container/k8s/Scaling.md)
- [持久化存储](/docs/CS/Container/k8s/Storage.md)
- [Cgroup 内核机制](/docs/CS/OS/Linux/cgroup.md)
- [GPU 设备插件](/docs/CS/Container/k8s/DevicePlugin.md)

## References

1. [Resource Management for Pods](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
2. [LimitRange](https://kubernetes.io/docs/concepts/policy/limit-range/)
3. [Resource Quotas](https://kubernetes.io/docs/concepts/policy/resource-quotas/)
4. [Configure Quality of Service](https://kubernetes.io/docs/tasks/configure-pod-container/quality-service-pod/)
