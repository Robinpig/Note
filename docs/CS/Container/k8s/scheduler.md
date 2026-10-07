## Introduction

kube-scheduler 是 Kubernetes 的默认调度器，职责窄到只有一件事：**给未绑定的 Pod 挑一个 nodeName**。它不看上层业务，也不管这个 Pod 起来之后能不能正常提供服务，那些是 controller-manager 和 kubelet 的事。

早期文档里说的"先 predicates 预选、再 priorities 优选"，指的是 1.15 之前的固定两阶段调度算法。从 1.15 起这套算法被改造成了 **Scheduling Framework**：预选/优选被拆成一个个可插拔的扩展点，两个阶段演变为 PreFilter / Filter / PostFilter / PreScore / Score 等多个有序插件阶段，任何阶段都可以替换或增删。今天再看调度器源码，应该从框架角度而不是 predicates/priorities 角度理解。

调度器的另一个特征是**每次只调度一个 Pod**。主循环严格单 goroutine 串行，是集群规模上升时的关键瓶颈点。

> [!NOTE]
> 本文基于 **Kubernetes v1.36.4** 源码实读。v1.36 有一批结构性变更，与多数既有资料的认知差异较大，集中列在文末。

## Source Code Structure

v1.36 的调度器目录发生过一次重命名，**老路径已经全部失效**：

| 常见认知（≤1.34） | v1.36.4 实际 |
|---|---|
| `pkg/scheduler/internal/queue/scheduling_queue.go` | `pkg/scheduler/backend/queue/scheduling_queue.go` |
| `pkg/scheduler/internal/cache/cache.go` | `pkg/scheduler/backend/cache/cache.go` |
| `pkg/scheduler/scheduler.go` 里的 `scheduleOne` | 已拆到 `pkg/scheduler/schedule_one.go`，且方法名改为大写 `ScheduleOne` |

`pkg/scheduler/backend/` 下新增了 `api_cache`、`api_dispatcher`、`heap` 三个子层，用于支撑异步 API 调用（默认关闭）。原来的 `scheduler.go` 现在只剩构造与装配逻辑，主循环不在这里。

## Main Loop ScheduleOne

`pkg/scheduler/schedule_one.go:67` 是整个调度器的入口：

```go
func (sched *Scheduler) ScheduleOne(ctx context.Context) {
	podInfo, err := sched.NextPod(logger)
	...
	if sched.genericWorkloadEnabled && podInfo.Pod.Spec.SchedulingGroup != nil {
		sched.scheduleOnePodGroup(ctx, podInfo.PodGroupInfo)   // 1.36 新增的 gang 分支
	} else {
		sched.scheduleOnePod(ctx, podInfo)
	}
}
```

`scheduleOnePod` 内部两步走，**调度周期同步，绑定周期异步**：

```
NextPod(activeQ.pop)            阻塞取当前最优 Pod
 frameworkForPod               按 pod.Spec.SchedulerName 选 profile
 skipPodSchedule               已在删除 / 已被 assume 则跳过
 UpdateSnapshot                固定本轮调度视图，此后到 Permit 结束前不变
 findNodesThatFitPod           PreFilter → Filter（并行）→ Extender filter
 RunPostFilterPlugins          仅当无可行节点时才走抢占
 assumeAndReserve              Cache.AssumePod → RunReservePlugins
 RunPermitPlugins              返回 Wait 则挂起，超时或 Reject 则判定失败
 go runBindingCycle            ★ 绑定放进独立 goroutine
```

### Why AssumePod Must Come First

`assume` 的源码注释写得很直白：乐观地假定绑定会成功，然后把 Pod 写进 cache 并异步发起绑定；万一绑定失败，立即释放已分配给它的资源。

真正的原因藏在下一步：**绑定是一个需要走 apiserver 的 API 往返**。如果同步等待它返回，主循环就会被这个往返串行阻塞。先 assume 让下一个调度周期立刻能看到这份资源占用，吞吐量才上得去。

配套地，v1.36 **移除了旧的 30s TTL 定时清理 assumed pod 的机制**（全文检索 TTL 已零命中），改为：

1. 绑定失败时显式 `Cache.ForgetPod` 回收；
2. 每次 `UpdateSnapshot` 时调用 `forgetAllAssumedPods` 做兜底。

## Scheduling Queue

`PriorityQueue` 由三个部分组成（`backend/queue/scheduling_queue.go:172`）：

| 队列 | 作用 | 出队条件 |
|---|---|---|
| `activeQ` | 主队列，堆结构 | 每次 Pop 直接取（幂次最高 + 最早入队） |
| `backoffQ` | 退避队列 | 退避到期后由后台 goroutine 移回 activeQ |
| `unschedulablePods` | 不可调度集合 | 集群状态变化时按事件过滤后移回 |

三个 backoff / flush 相关的默认周期：

| 参数 | 默认值 | 位置 |
|---|---|---|
| `DefaultPodInitialBackoffDuration` | 1s | `scheduling_queue.go:79` |
| `DefaultPodMaxBackoffDuration` | 10s | `scheduling_queue.go:83` |
| `DefaultPodMaxInUnschedulablePodsDuration` | 5min | `scheduling_queue.go:66` |
| flushUnschedulable 周期 | 30s | `scheduling_queue.go:444` |

退避计算是标准的指数退避 `initial << (n-1)`，上限 10s，即 1s → 2s → 4s → 8s → 10s 封顶。

> [!NOTE]
> v1.36 把 `backoffQ` 内部拆成了**两个堆**：`podBackoffQ`（插件判定为 Unschedulable 的 Pod）与 `podErrorBackoffQ`（因内部错误失败的 Pod）。此前只有一个。

事件驱动的重新入队依赖 Queueing Hints：**gated pod 只对自己 gating 插件注册过的事件或 wildcard 事件响应**，这是防止无效重算的关键优化。

## Scheduling Framework Extension Points

扩展点的权威定义已经不在 `pkg/scheduler/framework/interface.go`，而在 staging 仓库 `staging/src/k8s.io/kube-scheduler/framework/interface.go`。按实际调用顺序：

**调度周期（同步）**

```
PreEnqueue  (入队时)  →  PreFilter  →  Filter  →  PostFilter(抢占)
                                   →  Reserve  →  Permit
```

**绑定周期（异步 goroutine）**

```
PreBindPreFlight  →  WaitOnPermit  →  PreBind  →  Bind  →  PostBind
```

> [!TIP]
> **Permit 是最后一个能把 Pod 判定为 unschedulable 的扩展点**。过了 Permit，进入 PreBind/Bind 之后失败就只能回退避队列重试，不再重新选节点。

v1.36 新增了两个扩展点：`PreBindPreFlight`（并行 PreBind 预检）与 `SignPlugin`；另有服务于 pod group 的 `PlacementGeneratePlugin` / `PlacementScorePlugin`。注意 `PreFilterExtensions` **没有被统一化**，仍然作为 `PreFilterPlugin` 的可选返回值独立存在。

### Local Optimum in the Filter Phase

调度器在集群规模大时只遍历部分节点，这就是 sched 文档里"局部最优解"的来源。`numFeasibleNodesToFind` 的公式（`schedule_one.go:864`）：

| 常量 | 值 |
|---|---|
| `minFeasibleNodesToFind` | 100 |
| `minFeasibleNodesPercentageToFind` | 5 |
| `DefaultPercentageOfNodesToScore` | 0（自适应 `50 - N/125`，下限 5%） |
| `DefaultParallelism`（并发度） | 16 |

即少于 100 个节点时全量遍历；5000 节点时按 `50 - 40 = 10%` 取 500 个节点，找到足够数量即 `cancel` 掉剩余的并行检查任务。

## Default Plugins and Weights

默认启用的打分插件（`apis/config/v1/default_plugins.go`）：

| 插件 | 权重 |
|---|---|
| TaintToleration | 3 |
| NodeAffinity | 2 |
| InterPodAffinity | 2 |
| PodTopologySpread | 2 |
| NodeResourcesFit | 1 |
| NodeResourcesBalancedAllocation | 1 |
| ImageLocality | 1 |

`QueueSort` 插件（决定谁先出队）默认是 `PrioritySort`，规则极简：**priority 降序，同优先级 timestamp 升序**，没有任何额外权重：

```go
func (pl *PrioritySort) Less(pInfo1, pInfo2 fwk.QueuedPodInfo) bool {
	p1 := corev1helpers.PodPriority(pInfo1.GetPodInfo().GetPod())
	p2 := corev1helpers.PodPriority(pInfo2.GetPodInfo().GetPod())
	return (p1 > p2) || (p1 == p2 && pInfo1.GetTimestamp().Before(pInfo2.GetTimestamp()))
}
```

NodeResourcesFit 的默认策略是 `LeastAllocated`，资源权重为 `cpu:1, memory:1`。

## Preemption

只有 PostFilter 阶段才会触发抢占。流程是六步：`PodEligibleToPreemptOthers` 过滤 → `findCandidates` → `callExtenders` → `SelectCandidate` → 执行驱逐 → 返回被提名节点。

候选节点数量由两个参数决定，默认 `MinCandidateNodesPercentage=10`、`MinCandidateNodesAbsolute=100`。

> [!WARNING]
> 网上常说的 `VictimsElectorPolicy`（LeastVictims / NewerVictims）在 v1.36.4 中**不存在**。全仓检索零命中，`DefaultPreemptionArgs` 只有上述两个 MinCandidate 字段。victim 选择仍走 `SelectVictimsOnNode`，按"优先级降序、同优先级运行时长降序"排序，并配合 PDB 做分组豁免。

抢占并不会真的驱逐 Pod，它只是给被抢占者标记 `nominatedNodeName` 并通过 apiserver 删除 victim；真正的驱逐由 apiserver + kubelet 完成。

## Where Bind Lands

绑定优先级是：**先 HTTP extender，后框架插件**。

```go
// pkg/scheduler/framework/plugins/defaultbinder/default_binder.go:70
err := b.handle.ClientSet().CoreV1().Pods(binding.Namespace).Bind(ctx, binding, metav1.CreateOptions{})
```

注意这里提交的是 legacy **`binding` 子资源**，不是 Update pods。只有开启 `SchedulerAsyncAPICalls`（默认 false）时才会改走异步的 `APICacher().BindPod`。

## v1.36 Key Default Values

| 参数 | 默认值 | 位置 |
|---|---|---|
| parallelism | 16 | `framework/parallelize/parallelism.go:28` |
| Permit 超时上限 | **15min** | `framework/runtime/framework.go:53` |
| podInitialBackoff / podMaxBackoff | 1s / 10s | `backend/queue/scheduling_queue.go:79,83` |
| HardPodAffinityWeight | 1 | `apis/config/v1/defaults.go:190` |
| VolumeBinding BindTimeoutSeconds | 600 | `apis/config/v1/defaults.go:196` |
| MaxScore / MaxNodeScore | 100 | `staging/.../interface.go:329,321` |

Permit 上限 15min 常被误记成 30s 或 5min，这是校验卡住时的常见排查点。

`VolumeBinding` 那 600s 是**调度器与 PV controller 之间的握手超时**：`WaitForFirstConsumer` 场景下，调度器写完 `volume.kubernetes.io/selected-node` 后会一直等 PV controller 完成绑定，超时才放弃本次调度。这条握手有两端——调度器侧的预绑与 `checkBindings` 重试、controller 侧的供给与失败回退（删掉 selected-node 让调度器重试），完整时序见 [持久化存储](/docs/CS/Container/k8s/Storage.md)。

## Links

- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [client-go](/docs/CS/Container/k8s/client-go.md)
- [Pod](/docs/CS/Container/k8s/Pod.md)
- [controller-manager](/docs/CS/Container/k8s/controller-manager.md)
- [扩缩容与 HPA](/docs/CS/Container/k8s/Scaling.md)

## References

1. [Kubernetes Scheduling Framework](https://kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/)
2. [Scheduler Configuration](https://kubernetes.io/docs/reference/scheduling/config/)
3. [Pod Preemption](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/)
4. [kube-scheduler v1.36.4 source](https://github.com/kubernetes/kubernetes/tree/v1.36.4/pkg/scheduler)
