## Introduction

kube-scheduler 是 Kubernetes 的默认调度器，职责窄到只有一件事：**给未绑定的 Pod 挑一个 nodeName**。它不看上层业务，也不管这个 Pod 起来之后能不能正常提供服务，那些是 controller-manager 和 kubelet 的事。

早期文档里说的"先 predicates 预选、再 priorities 优选"，指的是 1.15 之前的固定两阶段调度算法。从 1.15 起这套算法被改造成了 **Scheduling Framework**：预选/优选被拆成一个个可插拔的扩展点，两个阶段演变为 PreFilter / Filter / PostFilter / PreScore / Score 等多个有序插件阶段，任何阶段都可以替换或增删。今天再看调度器源码，应该从框架角度而不是 predicates/priorities 角度理解。

调度器的另一个特征是**每次只调度一个 Pod**。主循环严格单 goroutine 串行，是集群规模上升时的关键瓶颈点。

> [!NOTE]
> 本文基于 **Kubernetes v1.37.2** 源码实读（v1.36 → v1.37 的主要变化：`NextPod` 改为 `NextEntity` 以统一 Pod / PodGroup 出队；`DefaultPreemption.PostFilter` 委托给 `Evaluator.Preempt` 支持异步抢占；新增 `PreBindPreFlight` 扩展点）。

## Source Code Structure

v1.36 之后的目录布局稳定，核心文件位置：

| 模块 | 路径 |
|---|---|
| 主循环 | `pkg/scheduler/schedule_one.go` (`ScheduleOne` + `scheduleOnePod`) |
| 队列 | `pkg/scheduler/backend/queue/scheduling_queue.go` |
| 调度快照 | `pkg/scheduler/backend/cache/cache.go` |
| 框架接口 | `staging/src/k8s.io/kube-scheduler/framework/interface.go` |
| 框架 runtime 实现 | `pkg/scheduler/framework/runtime/framework.go` |
| 抢占插件 | `pkg/scheduler/framework/plugins/defaultpreemption/default_preemption.go` |
| 默认插件权重 | `pkg/scheduler/apis/config/v1/default_plugins.go` |

原 `scheduler.go` 现在只剩构造与装配逻辑，主循环已拆到 `schedule_one.go`。

## Main Loop ScheduleOne

`pkg/scheduler/schedule_one.go:67` 是整个调度器的入口。v1.37 统一了 Pod 与 PodGroup 的出队：

```go
func (sched *Scheduler) ScheduleOne(ctx context.Context) {
    entity, err := sched.NextEntity(logger)   // 替代旧的 NextPod
    if entity == nil { return }               // queue 已关闭
    switch specificEntity := entity.(type) {
    case *framework.QueuedPodGroupInfo: sched.scheduleOnePodGroup(ctx, specificEntity)
    case *framework.QueuedPodInfo:      sched.scheduleOnePod(ctx, specificEntity)
    }
}
```

`scheduleOnePod` 内部两步走，**调度周期同步，绑定周期异步**：

```
NextEntity(activeQ.pop)         阻塞取当前最优 entity（Pod 或 PodGroup）
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

主循环本体在 `pkg/scheduler/scheduler.go:546`，只有两个动作值得记住：

```go
go wait.UntilWithContext(ctx, sched.ScheduleOne, 0)   // :560
```

- 周期是 0，意味着 `ScheduleOne` 返回后立刻再调用——串行性由 `NextPod` 阻塞在队列上保证，而不是靠定时器；
- 必须放进**独立 goroutine**。源码注释解释了原因：`ScheduleOne` 会挂在取 Pod 上，若放在 `Run` 自身所在的 goroutine，关闭时 `SchedulingQueue.Close()` 就永远等不到它返回，直接死锁。

另外调度器给 Pod 装的是 **in-place informer**（`NewInformerFactory` → `newPodInformer`，`scheduler.go:578`）：informer 直接复用 apiserver 返回的对象指针而不额外拷贝，因为调度器只读不写。

## Snapshot: Only the Changed Nodes Are Copied

每个调度周期开头都要 `UpdateSnapshot`，但如果每轮都把几千个 NodeInfo 深拷贝一遍，开销不可接受。v1.36 的做法是**按 generation 增量更新**（`backend/cache/cache.go:190`）：

```go
for node := cache.headNode; node != nil; node = node.next {
	if node.info.Generation <= snapshotGeneration {
		// all the nodes are updated before the existing snapshot. We are done.
		break
	}
	...
	clone := node.info.SnapshotConcrete()
	*existing = *clone
}
if cache.headNode != nil {
	nodeSnapshot.generation = cache.headNode.info.Generation
}
```

三个实现要点：

1. cache 里的 NodeInfo 是一条**按修改时间排序的双向链表**，headNode 最新。一旦遇到 generation 不大于快照世代的节点，后面都不必再看——这就是为什么遍历能提前 break；
2. 只有变化过的节点才 `SnapshotConcrete()` 深拷贝，其余保持原指针；
3. 派生列表（全部节点列表、有亲和性 Pod 的节点列表、有 required anti-affinity 的列表、usedPVCSet）各自有独立的 dirty flag，按需重建而不是每轮重建。

每次进入还会先 `forgetAllAssumedPods`（`:217`）——这就是上文说的 assumed pod 兜底点。

结尾有一次一致性自检：`nodeInfoList` 长度与 `nodeTree.numNodes` 不相等时，记录 `snapshot state is not consistent ... trying to recover` 并返回 error，本轮调度失败。**看到这条日志说明 cache 与快照已经跑偏**，属于需要上报的实现问题，不是可忽略的告警。

## findNodesThatFitPod: The Complete Scheduling Pipeline

`schedulePod`（`schedule_one.go:572`）是调度周期的算法核心，它把 `findNodesThatFitPod`（过滤）和 `prioritizeNodes`（打分）串起来：

```
schedulePod
├─ findNodesThatFitPod(ctx, fwk, state, podInfo)   ← 本节展开
│   ├─ ListNodesInPlacement()                      — 从快照取所有节点
│   ├─ RunPreFilterPlugins                          — 可能返回 NodeNames 限定候选集
│   ├─ evaluateNominatedNode                       — NominatedNodeName 快路
│   ├─ findNodesThatPassFilters (并行 Filter)
│   └─ findNodesThatPassExtenders                   — Extender 远程过滤
├─ len(feasible) == 1 → 直接返回（跳过打分）
├─ prioritizeNodes(ctx, extenders, fwk, state, pod, feasibleNodes)
│   ├─ RunPreScorePlugins
│   ├─ RunScorePlugins  → 加权求和
│   └─ extenders.Prioritize  → 与框架分数相加
└─ SortedScoredNodes.Pop() → SuggestedHost
```

### findNodesThatFitPod 五步

源码（`schedule_one.go:630`）的完整流程：

```go
allNodes, _ := sched.nodeInfoSnapshot.ListNodesInPlacement()

// ① PreFilter：可能返回 NodeNames 限定后续 Filter 范围
preRes, s, unscheduledPlugins := schedFramework.RunPreFilterPlugins(ctx, state, pod)
if !s.IsSuccess() {
    diagnosis.NodeToStatus.SetAbsentNodesStatus(s)   // 所有节点都被标记为该状态
    return nil, diagnosis, "", nil
}

// ② NominatedNodeName 快路：上一轮抢占指定的节点，先试它一个
if len(pod.Status.NominatedNodeName) > 0 || len(nodeHint) > 0 {
    feasibleNodes, _ := sched.evaluateNominatedNode(ctx, pod, fwk, state, nodeHint, diagnosis)
    if len(feasibleNodes) != 0 {
        return feasibleNodes, diagnosis, nodeHint, nil   // 命中就直接返回，不遍历全集群
    }
}

// ③ 如果 PreFilter 给了 NodeNames，过滤候选集
nodes := allNodes
if !preRes.AllNodes() {
    nodes = [...]   // 只保留 preRes.NodeNames 里的节点
}

// ④ 并行 Filter：每个节点串行跑所有 Filter 插件
feasibleNodes, err := sched.findNodesThatPassFilters(ctx, fwk, state, pod, &diagnosis, nodes)

// ⑤ Extender 远程过滤（如果配置了 Extender）
feasibleNodesAfterExtender, _ := findNodesThatPassExtenders(ctx, sched.Extenders, pod, feasibleNodes, diagnosis.NodeToStatus)
```

两个容易忽略的设计点：

1. **NominatedNodeName 快路是"先试一个"**——如果上一轮抢占给 Pod 标了 `nominatedNodeName`，这一轮先只对那个节点跑 Filter。命中就直接返回，不遍历全集群；不命中才降级到全量遍历。这避免了"抢占后还得重新扫一遍所有节点"的浪费。
2. **Extender 过滤失败会把 `fwk.ExtenderName` 塞进 UnschedulablePlugins**——因为 Extender 不支持 EnqueueExtensions，所以任何集群事件都会触发这个 Pod 从 unschedulableQ 重入队，无论事件是否相关。这是 Extender 机制的固有缺陷，也是为什么新写插件不要用 Extender。

### prioritizeNodes 与打分

当 feasibleNodes > 1 时进入打分（`schedule_one.go:608`）：

```go
priorityList, _ := prioritizeNodes(ctx, sched.Extenders, fwk, state, pod, feasibleNodes)
sortedPrioritizedNodes := framework.NewSortedScoredNodes(priorityList)
node := sortedPrioritizedNodes.Pop().Name   // 取分数最高的
```

`prioritizeNodes` 内部先跑框架打分（`RunPreScorePlugins` + `RunScorePlugins`），再跑 Extender 打分，然后把两者**相加**（不是加权平均）。这意味着 Extender 的分数量纲如果和框架不一致，会直接压过框架分——写 Extender 时必须注意归一化到 `[0, MaxNodeScore]`。

### 单节点短路

`schedulePod` 里有个很重要的优化（`:596`）：如果 Filter 后只剩 **1 个可行节点**，**直接返回，不跑打分**。这避免了对唯一可行节点做无意义的 Score 计算，在节点资源紧张、大量 Pod 只能落到个别节点时很有用。

## Binding Cycle: From Assume to PostBind

绑定周期是异步的（`go runBindingCycle`），它和调度周期解耦——调度周期选出节点后就返回去调度下一个 Pod，绑定在后台 goroutine 里完成。完整链路在 `schedule_one.go`：

```
schedulingCycle (同步)
├─ UpdateSnapshot
├─ schedulingAlgorithm → schedulePod → SuggestedHost
└─ prepareForBindingCycle
   ├─ assumeAndReserve                     — ① assume 进 cache + RunReservePlugins
   └─ RunPermitPlugins
      ├─ Success  → 继续（去 bindingCycle）
      ├─ Wait     → AddWaitingPod，挂起
      └─ Reject   → unreserveAndForget，返回 Unschedulable

runBindingCycle (异步 goroutine)
└─ bindingCycle
   ├─ RunPreBindPreFlights (可选)          — ② 预检 + 写 NominatedNodeName
   ├─ WaitOnPermit                         — ③ 等待挂起的 Pod 被唤醒
   ├─ SchedulingQueue.Done(uid)            — ④ 释放队列里的事件缓冲
   ├─ RunPreBindPlugins                    — ⑤ PreBind（如 VolumeBinding）
   ├─ bind (RunBindPlugins)                — ⑥ 实际调 apiserver POST binding
   └─ RunPostBindPlugins                   — ⑦ PostBind（如清理 assumed 状态）
```

### assumeAndReserve: 内存侧提交

`assumeAndReserve`（`:315`）做两件事：

1. **`sched.assume(logger, state, assumedPodInfo, host)`**——把 Pod 的 `NodeName` 设为 SuggestedHost，然后调 `Cache.AssumePod`。这一步**只改 scheduler 进程内的 cache**，不碰 apiserver。后续调度的 Filter/Score 看到的 NodeInfo 就已经包含了这个 Pod 的资源占用。
2. **`RunReservePlugins`**——通知 Reserve 插件（如 VolumeBinding 声明 "这个卷我占了"）。如果 Reserve 失败，调 `unreserveAndForget` 回滚。

> [!IMPORTANT]
> assume 是**乐观锁语义**：scheduler 假设绑定一定会成功，所以先在内存里占资源。如果实际绑定失败（apiserver 拒绝），会调 `ForgetPod` 回滚 cache。这期间如果有别的 Pod 调度到了同一节点，它看到的 NodeInfo 包含这个"还没真正绑定"的 Pod——这是 scheduler 吞吐的关键（不用等 apiserver 来回）。

### Permit: 同步+异步两段

Permit 分两步走：

1. **调度周期内的 `RunPermitPlugins`**（`prepareForBindingCycle:211`）——同步跑所有 Permit 插件。如果所有插件都 Success，直接进入绑定周期；如果有 Wait，调 `AddWaitingPod` 挂起，然后**仍然返回 Success**（因为绑定周期会等）；如果 Reject，调 `unreserveAndForget` 回滚，Pod 回到 unschedulableQ。
2. **绑定周期内的 `WaitOnPermit`**（`bindingCycle:433`）——阻塞等待 Pod 被唤醒。其它插件（如 Coscheduling）可以通过 `frameworkHandle.IterateOverWaitingPods` 找到等待中的 Pod 并调 `waitingPod.Allow()` 唤醒它。超时（15min）则失败。

### PreBind → Bind → PostBind

`bindingCycle` 的后半段（`:455` 之后）：

```go
// Permit 通过后，释放队列里的事件缓冲
sched.SchedulingQueue.Done(assumedPod.UID)

// PreBind：如 VolumeBinding 把 PV 绑定到 PVC
if status := schedFramework.RunPreBindPlugins(ctx, state, assumedPod, host); !status.IsSuccess() {
    return status   // 失败 → handleBindingCycleError → ForgetPod 回滚
}

// Bind：实际调 apiserver POST /api/v1/namespaces/<ns>/pods/<name>/binding
if status := sched.bind(ctx, schedFramework, assumedPod, host, state); !status.IsSuccess() {
    return status
}

// PostBind：成功后的清理（如清 assumed 状态、记录指标）
schedFramework.RunPostBindPlugins(ctx, state, assumedPod, host)
```

> [!TIP]
> **Permit 是最后一个能把 Pod 标记为 Unschedulable 的扩展点**。PreBind 或 Bind 失败不会让 Pod 进 unschedulableQ，而是进 backoffQ 重试（因为这通常是临时错误，不是真正的"不可调度"）。源码注释（`:449`）明确写了："We define the Pod as 'unschedulable' only when Pods are rejected at specific extension points, and Permit is the last one."

### 失败回滚

`handleBindingCycleError`（`:507`）在绑定周期任何阶段失败时触发：

```go
// 1. 调 Unreserve 插件回滚资源占用
schedFramework.RunReservePluginsUnreserve(ctx, state, assumedPod, host)

// 2. 从 cache 移除 assumed Pod
sched.Cache.ForgetPod(assumedPod)

// 3. 写失败指标
metrics.PodScheduleErrors.Inc()

// 4. 把 Pod 重新入队（backoffQ 或 unschedulableQ）
sched.SchedulingQueue.AddUnschedulableIfNotPresent(...)
```

回滚顺序和 Reserve 相反（LIFO），保证资源占用被正确释放。

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

## Framework Runtime: Plugin Invocation Semantics

扩展点的"顺序"在接口文档里只是声明，真正的执行语义在 `pkg/scheduler/framework/runtime/framework.go`。理解各阶段是**串行还是并行**、**返回什么状态会停止后续插件**，是写自定义插件的前提。

### Filter: Serial within Node, Parallel across Nodes

`RunFilterPlugins`（`framework.go:1105`）对**单个节点**是串行遍历 `f.filterPlugins`：

```go
for _, pl := range f.filterPlugins {
    if state.GetSkipFilterPlugins().Has(pl.Name()) { continue }  // PreFilter 标记跳过
    if status := f.runFilterPlugin(ctx, pl, state, pod, nodeInfo); !status.IsSuccess() {
        status.SetPlugin(pl.Name())
        return status   // 第一个失败的 Filter 直接终止该节点的过滤
    }
}
return nil
```

但调用 `RunFilterPlugins` 的外层（在 `schedule_one.go` 的 `findNodesThatFitPod` 里）是**按节点并行**的——`Parallelizer().Until(ctx, len(allNodes), func(index int) { ... RunFilterPlugins(...) })`。所以整体结构是：

```
外层: 按节点并行（默认 16 goroutine）
  内层: 单节点内按插件串行（第一个 Unschedulable 即终止该节点）
```

`SkipFilterPlugins` 是一个重要的优化点：PreFilter 阶段如果某个插件确认"本 Pod 不需要跑某个 Filter"，就可以把那个插件名加进 skip 集合，避免无效调用。

### Score: Three-Stage Parallel

`RunScorePlugins`（`framework.go:1405`）是三段并行，比 Filter 复杂：

```
阶段 1: RunScorePlugins → 按节点并行（Parallelizer）
         每个节点内串行跑所有 Score 插件，收集 RawScores
         ↓ errCh，任一分支失败 cancel 全部

阶段 2: normalizeScores → 按插件并行（Parallelizer）
         对实现了 ScoreExtensions() 的插件调 NormalizeScore
         ↓ 把 RawScores 转成归一化后的 Scores

阶段 3: 加权求和 → 按节点并行
         TotalScore = Σ (Score × weight)
```

关键代码片段（`framework.go:1436`）：

```go
// 阶段 1: 按节点并行收集每个插件的原始分
f.Parallelizer().Until(ctx, len(nodes), func(index int) {
    rawScores, status := f.runRawScorePlugins(nodeCtx, state, pod, nodeInfo, plugins)
    for _, rawScore := range rawScores {
        pluginToNodeScores[rawScore.Name][index] = fwk.NodeScore{Name: nodeName, Score: rawScore.Score}
    }
})

// 阶段 2: 按插件并行归一化
f.Parallelizer().Until(ctx, len(plugins), func(index int) {
    pl := plugins[index]
    ext := pl.ScoreExtensions()
    if ext == nil { return }   // 没实现归一化的插件跳过
    ext.NormalizeScore(ctx, state, pod, pluginToNodeScores[pl.Name()])
})
```

> [!TIP]
> **归一化是插件自己的责任，框架不代劳。** 框架只保证 `Score` 返回值落在 `[0, MaxNodeScore]`，但原始分的量纲（0~1 还是 0~100）完全由插件自己 `NormalizeScore` 拉平。忘了实现 `ScoreExtensions` 的插件，原始分会被直接乘权重，很容易压过所有内置插件。

### PreFilter: Serial with Stateful Side Effects

`RunPreFilterPlugins`（`framework.go:934`）是**串行**的，因为 PreFilter 的职责是"为后续 Filter/Score 准备数据"——通常是往 `CycleState` 里写计算结果（比如 Pod 反亲和的目标 Pod 集合）。串行保证插件间没有 race，但也意味着 PreFilter 是调度周期里不能并行化的瓶颈段。

PreFilter 还有一个特殊返回值 `PreFilterResult`，里面的 `NodeNames` 字段可以**直接限定后续 Filter 只跑哪些节点**——这是大规模集群下"先粗筛再细筛"的常见优化（比如 NodeAffinity 在 PreFilter 里直接算出候选节点集合，避免对全集群跑 Filter）。

### Permit: Wait Aggregation

`RunPermitPlugins`（`framework.go:2097`）的语义和其它阶段都不同——它**收集所有插件的 Wait 状态，而不是遇到第一个失败就停**：

```go
for _, pl := range f.permitPlugins {
    status, timeout := f.runPermitPlugin(ctx, pl, state, pod, nodeName)
    switch {
    case status.IsRejected():  return nil, status            // 立即拒绝
    case status.IsWait():      pluginsWaitTime[pl.Name()] = timeout; waitStatus = status
    case !status.IsSuccess():  return nil, status            // 错误
    }
}
if waitStatus.IsWait() {
    return pluginsWaitTime, waitStatus   // 至少一个插件说"等一下"
}
return nil, nil  // 全部 Success
```

逻辑是：**只要有一个插件 Reject，整个 Permit 失败；只要有一个插件 Wait 且没人 Reject，Pod 进入等待**。等待时间取 `pluginsWaitTime` 里的最大值，但不超过 `maxTimeout`（15min）。等待中的 Pod 由 `waitingPodsMap` 管理，其它插件可以通过 `frameworkHandle.IterateOverWaitingPods` 唤醒它。

> [!TIP]
> Permit 是 PodGroup（gang scheduling）的核心扩展点——Coscheduling 插件就是在 Permit 阶段检查"同组 Pod 是否都能调度"，不够就 Wait，凑齐了一起通过。

### Reserve: Two-Phase Rollback

`RunReservePluginsReserve`（`framework.go:2014`）在 assume 后调用，`RunReservePluginsUnreserve`（`:2058`）在绑定失败或 Permit 拒绝时调用。这是一个**两阶段提交**的雏形：Reserve 占资源，Unreserve 释放。框架保证只要调用过 Reserve 的插件，后续一定会调用对应的 Unreserve——顺序逆序（LIFO），和数据库的 undo log 一样。

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

权重在装配期就做合法性校验（`framework/runtime/framework.go:574`）：weight 为 0 会被当作 1，且所有插件的 `weight * MaxScore` 之和不得超过 `MaxTotalScore`，否则构造失败——这条保证 TotalScore 始终在 int64 范围内且不溢出。

## Scoring Pipeline

打分不是一个函数，是**三段并行**（`framework/runtime/framework.go:1339` `RunScorePlugins`）：

| 阶段 | 并行维度 | 做什么 |
|---|---|---|
| Score | 按**节点**并行 | 对每个节点跑所有 Score 插件 |
| NormalizeScore | 按**插件**并行 | 仅对实现了 `ScoreExtensions()` 的插件执行 |
| 加权求和 | 按**节点**并行 | `weightedScore := score * weight`，累加成 `TotalScore` |

```go
// framework/runtime/framework.go:1390
f.Parallelizer().Until(ctx, len(plugins), func(index int) {
	pl := plugins[index]
	if pl.ScoreExtensions() == nil {
		return          // 没实现归一化的插件直接跳过
	}
	...
})
```

> [!TIP]
> **归一化是插件自己的责任，框架不代劳。** 这是理解各插件分值量纲的关键：框架只保证 `Score` 的返回值落在 `[0, MaxNodeScore]`，至于插件内部打的是 0~1 还是 0~100，一概由插件自己 `NormalizeScore` 拉平。所以自定义插件忘了实现 `ScoreExtensions`，它的原始分会被直接乘以权重，很容易在总分里压过所有内置插件。

最终选节点用了一个堆（`schedule_one.go:1086` `nodeScoreHeap`）：

```go
func (h nodeScoreHeap) Less(i, j int) bool {
	return (h[i].TotalScore > h[j].TotalScore ||
		(h[i].TotalScore == h[j].TotalScore && h[i].Randomizer > h[j].Randomizer))
}
```

并列时用 `Randomizer` 而非节点名字典序打破——**同分节点是随机选的，不是稳定的**。

两条短路值得记：

1. 过滤后只剩一个可行节点时**完全不打分**，直接返回（`schedule_one.go:596` 注释 *When only one node after predicate, just use it*）；
2. 一个 Score 插件都没配、也没有 extender 时，所有节点统一 `TotalScore: 1`（`schedule_one.go:959`），退化成"随便挑一个"。

HTTP extender 的分数要换算到同一量纲（`schedule_one.go:1021`）：

```go
finalscore := score * weight * (fwk.MaxNodeScore / extenderv1.MaxExtenderPriority)
```

之所以要乘这个比例，是因为 extender 的量纲（MaxExtenderPriority）与调度框架的 `MaxNodeScore`（100）可以完全不同。extender 打分失败不致命——只记日志跳过，让内置插件继续决定。

## Preemption

只有 PostFilter 阶段才会触发抢占。流程是六步：`PodEligibleToPreemptOthers` 过滤 → `findCandidates` → `callExtenders` → `SelectCandidate` → 执行驱逐 → 返回被提名节点。

候选节点数量由两个参数决定，默认 `MinCandidateNodesPercentage=10`、`MinCandidateNodesAbsolute=100`。

> [!WARNING]
> 网上常说的 `VictimsElectorPolicy`（LeastVictims / NewerVictims）在 v1.36.4 中**不存在**。全仓检索零命中，`DefaultPreemptionArgs` 只有上述两个 MinCandidate 字段。victim 选择仍走 `SelectVictimsOnNode`，按"优先级降序、同优先级运行时长降序"排序，并配合 PDB 做分组豁免。

抢占并不会真的驱逐 Pod，它只是给被抢占者标记 `nominatedNodeName` 并通过 apiserver 删除 victim；真正的驱逐由 apiserver + kubelet 完成。

### SelectVictimsOnNode: The Remove-All-Then-Reprieve Algorithm

`SelectVictimsOnNode`（`defaultpreemption/default_preemption.go:286`）是抢占的核心算法。它在一个候选节点上决定"该驱逐哪些 Pod 才能让 preemptor 落下来"。直觉上是"找出要驱逐的最小集合"，但源码用了一个巧妙的反向策略：

```
① 先把该节点上所有可被抢占的 Pod 全部从 NodeInfo 里移除
   removeVictim() —— 同时调 RunPreFilterExtensionRemovePod 更新 CycleState

② 对该节点重跑一遍 Filter（RunFilterPluginsWithNominatedPods）
   如果 preemptor 还是放不进去 → 这个节点不适合抢占，直接返回

③ 把 potentialVictims 按"重要性"降序排序（优先级高 + 运行时长长的更重要）

④ 逐个尝试"加回"（reprieve）每个 victim：
   addVictim(victim) → 重跑 Filter
   ├── preemptor 还能放 → 这个 victim 可以不驱逐，保留
   └── preemptor 放不下 → 这个 victim 必须驱逐，从 potentialVictims 移除
   优先尝试加回 PDB-violating 的 victim（保护 PodDisruptionBudget）
```

源码结构（简化）：

```go
// 第一步: 全部移除
for _, victim := range potentialVictims {
    removeVictim(victim)   // RemovePod + RunPreFilterExtensionRemovePod
}

// 第二步: 验证 preemptor 是否能放
if status := RunFilterPluginsWithNominatedPods(...); !status.IsSuccess() {
    return nil, 0, status   // 这个节点不适合抢占
}

// 第三步: 按重要性排序，优先 reprieve 重要的
sort.Slice(potentialVictims, func(i, j int) bool {
    return MoreImportantVictim(potentialVictims[i], potentialVictims[j])
})

// 第四步: 逐个加回，放不下的就作为最终 victim
for _, victim := range potentialVictims {
    addVictim(victim)
    if status := RunFilterPluginsWithNominatedPods(...); !status.IsSuccess() {
        removeVictim(victim)   // 放不回去，这个必须驱逐
    }
}
```

这个算法的精妙之处：**不是枚举"驱逐哪些"的组合（指数级），而是从"全驱逐"出发贪心加回（线性）**。最终驱逐的是"加回去会导致 preemptor 放不下"的那些 Pod，保证了"驱逐数量最少"在贪心意义下成立。

### PostFilter Delegation and Async Preemption

v1.37 的 `DefaultPreemption.PostFilter`（`default_preemption.go:152`）本身很薄：

```go
func (pl *DefaultPreemption) PostFilter(ctx, state, pod, m) (*PostFilterResult, *Status) {
    result, status := pl.Evaluator.Preempt(ctx, state, pod, m)
    return result, status
}
```

它把真正的抢占逻辑委托给 `Evaluator`。当 `EnableAsyncPreemption` feature gate 开启时，PreEnqueue 会检查当前 Pod（或其 PodGroup）是否已经有正在运行的抢占——如果有，返回 `UnschedulableAndUnresolvable` 让 Pod 留在 unschedulablePods，等抢占完成后由事件驱动重入队。这避免了同一个 Pod 在等待抢占结果时被反复调度。

## Nominated Node and Nominator

抢占留下的 `status.nominatedNodeName` 不只是给人看的字段，它在下一轮调度里被**当作优先路径**（`schedule_one.go:663`）：

```go
// "NominatedNodeName" can potentially be set in a previous scheduling cycle as a result of preemption.
// This node is likely the only candidate that will fit the pod, and hence we try it first before iterating over all nodes.
if len(pod.Status.NominatedNodeName) > 0 || len(nodeHint) > 0 {
	feasibleNodes, err := sched.evaluateNominatedNode(ctx, pod, schedFramework, state, nodeHint, diagnosis)
	...
	if len(feasibleNodes) != 0 {
		return feasibleNodes, diagnosis, nodeHint, nil   // 提名节点过关，跳过全量遍历
	}
}
```

`evaluateNominatedNode`（`:720`）只对这个单一节点跑 filter 与 extender。命中就直接返回，**省掉整轮全集群过滤**——抢占后大量 Pod 重试时，这条捷径的价值非常明显。

几个 v1.36 的位置变化需要留意：

| 项 | v1.36.4 实际 |
|---|---|
| nominator 归属 | 挂在 **SchedulingQueue** 上（`SchedulingQueue.AddNominatedPod`，`:388` `:1280`），不在 scheduler cache |
| NNN 的写入时机 | 分两处：抢占后（`:1280`）与绑定周期里可选的"预期写入"（`:410`） |
| 预期写入的用途 | 注释写明是给 **cluster autoscaler 之类的外部组件**看的：告诉它们这个 Pod 即将落到哪个节点 |
| 写入条件 | `NominatingInfo.Mode() == fwk.ModeOverride` 且值与当前不同时才写（`:1330`） |

`clearNominatedNode`（`:172`）是一个 `ModeOverride + 空名` 的组合，调度失败时用它把 NNN 显式清空——注意 Mode 必须是 Override，`ModeNoop` 表示"不要动这个字段"。

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
| 主循环周期 | 0（`wait.UntilWithContext` 立即循环） | `pkg/scheduler/scheduler.go:560` |

另有三条结构性变化，与旧资料冲突较多：

| 常见认知 | v1.36.4 实际 |
|---|---|
| nominator 在 scheduler cache 里 | 已移到 `SchedulingQueue.AddNominatedPod`，cache 中零命中 |
| 框架统一归一化插件分值 | 不代劳，只调插件自己的 `ScoreExtensions().NormalizeScore` |
| `UpdateSnapshot` 每轮全量拷贝 | 按 NodeInfo generation 增量拷贝，链表遍历可提前 break |

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
4. [kube-scheduler v1.37.2 source (本地仓库)](https://github.com/kubernetes/kubernetes/tree/v1.37.2/pkg/scheduler)
5. [scheduler framework runtime](https://github.com/kubernetes/kubernetes/tree/v1.37.2/pkg/scheduler/framework/runtime)
