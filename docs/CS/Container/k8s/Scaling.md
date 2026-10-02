## Introduction

Deployment 的核心任务是保证"当前 Pod 数量 = 期望 Pod 数量"，但那个**期望数字**从哪来？不是凭感觉拍的，而是根据流量和资源消耗动态调整出来的——这个过程就是扩缩容（Scaling）。

先区分两个方向：

| 方向 | 做法 | 代价 |
|------|------|------|
| **水平扩缩容**（Horizontal） | 增减 Pod 副本数 | 需要 Service 配合分发，副本间必须无状态 |
| **垂直扩缩容**（Vertical） | 给单个 Pod 更多 CPU/内存 | 需要重启 Pod，单机上限受限，K8s 支持但能力有限 |

水平扩缩容是云原生弹性的主力，本文以它为主。

## 手动扩缩容

```shell
# 大促前预估流量涨 10 倍，先扩容到 5 个
kubectl scale deployment my-app --replicas=5

# 大促结束，缩容回 2 个（留一个冗余）
kubectl scale deployment my-app --replicas=2
```

扩缩容最终都落到 Deployment → ReplicaSet → Pod 的副本数调和上（见 [ReplicaSetController](/docs/CS/Container/k8s/ReplicaSetController.md)），缩掉的 Pod 会被优雅终止（见 [Pod 优雅终止](/docs/CS/Container/k8s/Pod.md?id=优雅终止)）。

手动方式适合"可预知的大促"，但它有三个绕不过的问题：

1. **要有人盯着**——凌晨三点流量暴涨时没人敲命令；
2. **没有客观依据**——设 5 还是 10 全凭直觉，少了扛不住、多了浪费钱；
3. **缩容时机难判断**——流量降了没人知道，多余副本白烧一周资源。

## HPA：自动扩缩容

HPA（Horizontal Pod Autoscaler）是一个"自动店长"：它周期性（默认每 15s）检查负载指标，自动调整 Deployment/StatefulSet 的 replicas，你只需告诉它两个数——**有几个人**（min/max）和**多忙算忙**（目标利用率）。

```shell
kubectl autoscale deployment my-app \
  --cpu-percent=70 \
  --min=2 \
  --max=10
```

等价于声明式写法：

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

### 工作流程

1. **监控**：通过 Metrics Server 采集每个 Pod 的 CPU/内存实际用量；
2. **计算**：求当前所有 Pod 的平均利用率，与目标值比较；
3. **决策**：按公式算出目标副本数；
4. **执行**：更新 Deployment 的 `replicas`，后续由 ReplicaSet 创建/删除 Pod。

核心公式：

```
期望副本数 = ceil( 当前副本数 × (当前平均利用率 / 目标利用率) )
```

例：2 个 Pod 各用 80% CPU，目标 70% → `ceil(2 × 80/70) = ceil(2.29) = 3`。

### 冷却与抖动

- **扩容有 3 分钟容忍窗口**、**缩容默认有 5 分钟冷却期**（`--horizontal-pod-autoscaler-downscale-stabilization`）：不会因为 CPU 抖动一下就把 Pod 全杀了。
- HPA 还会取过去一段时间内的**推荐值最大值**来抑制指标毛刺，避免副本数来回震荡（flapping）。

### 指标不止 CPU

autoscaling/v2 支持三类指标，按需组合：

| 指标类型 | 来源 | 例子 |
|---------|------|------|
| Resource | Metrics Server | CPU、内存 |
| Pods | 自定义指标适配器 | QPS per pod、队列长度 |
| Object / External | Prometheus Adapter 等 | Ingress 请求数、MQ 堆积量 |

生产实践中，CPU 只是"替代指标"，对 IO 密集或异步消费型服务，用队列积压量（Kafka lag）等业务指标做 HPA 往往更准确。

## HPA / VPA / Cluster Autoscaler 的关系

三者解决的是不同层次的"不够用"：

```
流量上涨 → HPA 加 Pod → Node 资源不够 → Cluster Autoscaler 加 Node → 新 Pod 调度成功
```

- **HPA**：改 Pod 数量（横向）；
- **VPA**：改 Pod 的 requests/limits（纵向），需要重建 Pod，且与 HPA 同时作用于 CPU 时会打架，同一维度二选一；
- **Cluster Autoscaler**：Node 池层面加/减机器，是 HPA 能持续生效的兜底。

## 实战心法

1. **别迷信 3**：先设 `min=2, max=10`，让 HPA 跑，再看 Prometheus 曲线反推合适的 min/max 和 requests。
2. **缩容留缓冲**：min 不要设 1（单副本既无高可用，也扛不住突增流量），手动缩容同样留 1~2 个冗余 Pod。
3. **关注启动时间**：从决定扩容到新 Pod 通过就绪探针，轻量 Go 服务约 10s，Java Spring Boot 可能 60s 以上。秒杀类瞬时高峰必须提前预热扩容，否则扩容速度追不上流量上涨速度。
4. **看住 requests**：HPA 的利用率分母是 `requests` 而非 `limits`。requests 设小了会导致利用率虚高、Pod 频繁被限流；设大了则 HPA 迟迟不触发。
5. **HPA 只管 Pod**：Node 满了新 Pod 会 Pending，必须配 Cluster Autoscaler。

## 常见翻车案例

| 案例 | 现象 | 教训 |
|------|------|------|
| 缩容过激 | min=1 + 冷却期改 30s，凌晨缩到 1 个，早高峰瞬间打爆，恢复期用户吃到 502 | min 别设 1，冷却期别乱改 |
| 忘记回落 | 大促期间 min=20，活动结束无人调整，20 个 Pod 空转两周 | 峰值过后记得调 min，HPA 只负责弹性不负责省钱 |
| Node 不足 | HPA 要扩到 15 个，3 个 Node × 4 Pod 上限，剩余 Pod 全部 Pending | HPA 必须配合 Cluster Autoscaler |

扩缩容本质是个经济学问题：**你愿意花多少冗余资源换取多少稳定性**。最省钱的配置扛不住任何波动，最稳的配置让账单失控——平衡点在数据里，不在直觉里。

## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)
- [Pod](/docs/CS/Container/k8s/Pod.md)
- [scheduler](/docs/CS/Container/k8s/scheduler.md)
- [Service](/docs/CS/Container/k8s/Service.md)
- [常见问题排查](/docs/CS/Container/k8s/Issues.md)

## References

1. [图解K8s · 扩缩容就像开分店](https://mp.weixin.qq.com/s/Ouoaa2wHMemVZ7pYCxzUMA)
