## Introduction

kubelet 运行在每个节点上，接收 apiserver 下发的 Pod 期望状态，把节点上的实际状态收敛过去，并持续把节点与 Pod 状态回写。它是控制面到数据面的"最后一跳"：**调度器决定 Pod 去哪，kubelet 决定 Pod 怎么真的跑起来**。

职责可以拆成四条彼此独立的循环：

| 循环 | 做什么 | 不做什么 |
|---|---|---|
| 配置同步 | 从 apiserver / 静态文件 / HTTP 接收 Pod 期望状态 | 不决定 Pod 调度到哪个节点 |
| 运行时同步 | 调 CRI 创建/删除 sandbox 与容器 | 不直接操作容器进程 |
| 状态回写 | 聚合运行时状态，写 Pod status / Node status | 不做业务级健康判断 |
| 本地自治 | 镜像 GC、驱逐、容器 GC | 不经过 apiserver 删除 Pod 对象 |

kubelet 自己不实现 CRI / CNI / CSI，只定义契约交给外部实现。三者在本仓库中的位置差别很大：

| 接口 | v1.37.2 现状 |
|---|---|
| **CRI** | 唯一运行路径。客户端代码已搬到独立 staging 模块 `k8s.io/cri-client`，流式接口在 `k8s.io/cri-streaming`；dockershim 早已不存在 |
| **CNI** | 已完全移出 kubelet 代码树。kubelet 不再调用任何 CNI 插件，只能通过 CRI 回报的 `NetworkReady` condition 感知网络就绪 |
| **CSI** | kubelet 不实现驱动，但握有衔接链：pluginwatcher 监听插件 socket → 注册 handler → volumeManager reconciler 挂载 |

> [!NOTE]
> CNI 出树的直接影响：**排查网络问题时，kubelet 日志里已经找不到任何 CNI 调用记录**，要看 containerd / CRI-O 侧与 CRI 的 `RuntimeStatus`。

## Startup and Run

`kubelet` 使用 Cobra 作为命令行框架，`main` 只做四件事：解析 flags → 构造 `KubeletServer` → 组装依赖 → `app.Run`。

真正的启动在 `pkg/kubelet/kubelet.go:1883` 的 `Run`。v1.37.2 的启动顺序值得逐个记住，因为它决定了"什么时候能开始调度 Pod"：

```go
func (kl *Kubelet) Run(ctx context.Context, updates <-chan kubetypes.PodUpdate) {
	if err := kl.initializeModules(ctx); err != nil {
		os.Exit(1)                       // 初始化失败直接退出，交给 babysitter 重启
	}
	if err := kl.cgroupVersionCheck(); err != nil { ... }   // 仅告警

	if kl.allocationManager != nil { kl.allocationManager.Run(ctx) }
	go kl.volumeManager.Run(ctx, kl.sourcesReady)

	if kl.kubeClient != nil {
		go func() {
			kl.updateRuntimeUp(ctx)      // 先探测运行时，避免首个周期误报 NotReady
			wait.JitterUntil(func() { kl.syncNodeStatus(ctx) }, kl.nodeStatusUpdateFrequency, 0.04, true, wait.NeverStop)
		}()
		go kl.fastStatusUpdateOnce(context.WithoutCancel(ctx))
		go kl.nodeLeaseController.Run(context.Background())
		go kl.fastStaticPodsRegistration(ctx)
	}
	go wait.UntilWithContext(ctx, kl.updateRuntimeUp, 5*time.Second)

	if kl.makeIPTablesUtilChains { kl.initNetworkUtil(logger) }

	kl.statusManager.Start(ctx)
	if kl.runtimeClassManager != nil { kl.runtimeClassManager.Start(wait.NeverStop) }
	kl.pleg.Start(ctx)                                  // 先起 PLEG
	if kl.eventedPlegWatcher != nil { kl.eventedPlegWatcher.Start(ctx) }
	kl.syncLoop(ctx, updates, kl)                       // 最后进主循环，永不返回
}
```

### 模块初始化被拆成两段

这是 v1.37 一个容易被旧资料误导的结构变化：**不依赖运行时的模块与依赖运行时的模块分两次启动**。

`initializeModules`（`:1771`）只做**不需要容器运行时在线**的事：

```
metrics.Register + RegisterCollectors   → setupDataDirs（创建目录）
ContainerLogsDir                        → imageManager.Start（镜像 GC）
serverCertificateManager.Start          → clientCAManager.Run
oomWatcher.Start                        → resourceAnalyzer.Start
```

**containerManager、evictionManager、containerLogManager 不在这里**。它们被搬到 `initializeRuntimeDependentModules`（`:1829`）：

```go
func (kl *Kubelet) initializeRuntimeDependentModules(ctx context.Context) {
	if err := kl.cadvisor.Start(); err != nil { os.Exit(1) }
	_, _, _ = kl.StatsProvider.GetCgroupStats(ctx, "/", true)   // 先采一次，让 ephemeral storage 有值
	node, err := kl.getNodeAnyWay(ctx)
	// containerManager 必须在 cAdvisor 之后，因为它需要文件系统容量信息
	kl.containerManager.Start(ctx, node, ...)
	// evictionManager 必须在 cadvisor 之后，因为它要判断 runtime 是否独享 imagefs
	kl.evictionManager.Start(ctx, kl.StatsProvider, kl.getAllocatedPods, ...)
	kl.containerLogManager.Start(ctx)
	kl.pluginManager.AddHandler(pluginwatcherapi.CSIPlugin, ...)
}
```

它由 `updateRuntimeUp`（`:3362` 处调用）在运行时首次就绪后触发一次。所以**容器运行时没起来时，kubelet 仍能上报 Node 状态、跑镜像 GC，但不会创建任何 Pod**——这是"运行时故障时节点表现为 NotReady 而不是崩溃"的源码依据。

另外 `Run` 里先起 `updateRuntimeUp` 再起 `syncNodeStatus`，是为了避免 kubelet 重启后的第一个上报周期就误报 NotReady（`syncNodeStatus` 需要运行时就绪信息）。

## The Sync Loop

`syncLoop`（`:2671`）是 kubelet 的事件总线。所有来源的变更都被收敛到"对某个 Pod 做一次 sync"，没有变更时也按固定周期兜底同步。

```go
func (kl *Kubelet) syncLoop(ctx context.Context, updates <-chan kubetypes.PodUpdate, handler SyncHandler) {
	syncTicker := time.NewTicker(time.Second)                    // 每秒检查哪些 Pod 需要 sync
	housekeepingTicker := time.NewTicker(housekeepingPeriod)     // 定期清理
	plegCh := kl.pleg.Watch()
	duration := 100 * time.Millisecond
	for {
		if err := kl.runtimeState.runtimeErrors(); err != nil {
			time.Sleep(duration)                                  // 运行时异常 → 指数退避，暂停同步
			duration = time.Duration(math.Min(float64(max), factor*float64(duration)))
			continue
		}
		duration = 100 * time.Millisecond                         // 一次成功即重置退避
		if !kl.syncLoopIteration(ctx, updates, handler, syncTicker.C, housekeepingTicker.C, plegCh) {
			break
		}
	}
}
```

关键点：**运行时错误不是让 kubelet 退出，而是让主循环整体退避**（100ms 起，翻倍到 5s 上限）。退避期间仍然在跑 Node 状态上报、镜像 GC、驱逐等独立 goroutine，只有"Pod 同步"被暂停。

### 八路 select

`syncLoopIteration`（`:2746`）是一个八分支 select，且**分支顺序不代表优先级**——Go 的 select 在多个 channel 同时就绪时随机选：

| 分支 | 触发源 | 动作 |
|---|---|---|
| `configCh` | apiserver / 静态文件 / HTTP | 按 `u.Op` 分发：ADD→`HandlePodAdditions`，UPDATE/DELETE→`HandlePodUpdates`，REMOVE→`HandlePodRemoves`，RECONCILE→`HandlePodReconcile` |
| `plegCh` | PLEG 事件 | 事件"值得同步"就 `HandlePodSyncs`；`ContainerDied` 额外触发 `cleanUpContainersInPod` |
| `syncCh` | 每秒 ticker | `getPodsToSync()` 后批量 `HandlePodSyncs` |
| `livenessManager.Updates()` | 存活探针失败 | `handleProbeSync`，同步该 Pod |
| `readinessManager.Updates()` | 就绪探针结果 | 先 `SetContainerReadiness`，再同步 |
| `startupManager.Updates()` | 启动探针结果 | 先 `SetContainerStartup`，再同步 |
| `containerManager.Updates()` | 设备/资源分配变更（DRA） | 取出受影响 Pod，`HandlePodSyncs` |
| `housekeepingCh` | 定期 | `sourcesReady.AllReady()` 后才 `HandlePodCleanups`，防止误删未就绪来源的 Pod |

`housekeeping` 有一道重要闸门：**只要还有配置来源没 ready，就跳过清理**，否则可能把"还没从某个来源收到的 Pod"当成残留删掉。同一分支还会记录耗时，超过 `housekeepingWarningDuration` 打 error 日志。

probe 三路的意义在于：**探针结果不需要等 PLEG 或定时同步**，失败即刻触发一次 sync，这是容器重启延迟能压到秒级的原因。

## Probe Manager

v1.37 的 probe manager（`pkg/kubelet/prober/prober_manager.go`）不再是一个共享轮询循环，而是**每个容器的每种 probe 各一条 worker goroutine**：AddPod 时遍历每个 container 的 StartupProbe / ReadinessProbe / LivenessProbe，分别 `newWorker` + `go w.run(ctx)`。键是 `{podUID, containerName, probeType}`，三种 probe 彼此独立互不干扰。

### Worker 循环与状态闸门

`worker.run`（`pkg/kubelet/prober/worker.go:158`）的骨架：

```go
// 防 kubelet 重启时所有 probe 同时开始——加一次随机抖动
if probeTickerPeriod > time.Since(w.probeManager.start) {
    time.Sleep(time.Duration(rand.Float64() * float64(probeTickerPeriod)))
}
probeTicker := time.NewTicker(probeTickerPeriod)

probeLoop:
for w.doProbe(ctx) {
    select {
    case <-w.stopCh:           break probeLoop
    case <-probeTicker.C:       // 定时触发
    case <-w.manualTriggerCh:   // 手动触发，ticker 重置
        probeTicker.Reset(probeTickerPeriod)
    }
}
```

`doProbe`（`:215`）里的**五道闸门**决定了 probe 什么时候真的执行：

1. **容器 ID 变了？** → 旧 containerID 的结果从 resultsManager 里删掉，新 containerID 写入 `initialValue`，`onHold = false`。
2. **Pod 终态？** → worker 退出。
3. **容器没 Running？** → 直接写 `Failure`，然后看 `RestartPolicy`（含 restartable init container 的 sidecar 语义）——不需要真正执行 probe。
4. **Graceful shutdown？** → `Pod.DeletionTimestamp != nil` 且 probe 是 liveness/startup 时，直接写 `Success` 然后 `return false` 停止探测——不让"正在被杀"的容器被判 unhealthy 干扰排障。
5. **InitialDelaySeconds 没过？** → 跳过。
6. **Started 闸门？** → `c.Started == true` 时 liveness/readiness 才开始探测；`c.Started == false` 时 startup 才探测，startup 过了之后自己就停了。

最后一道闸门非常关键（`:335-346`）：**startup probe 是 liveness/readiness 的前置开关**，只有它判 success 之后其它 probe 才开始。反之，startup 判 success 之后自己就退出循环了——避免用不必要的探测把容器压垮。

### Threshold 状态机：连续 N 次才算数

probe 执行完不会立刻写 resultsManager，而是在 worker 里维护 `lastResult` + `resultRun` 计数器（`:366-377`）：

```go
if w.lastResult == result { w.resultRun++ } else { w.lastResult = result; w.resultRun = 1 }

// 连续 FailureThreshold 次 Failure 才算 Failure；连续 SuccessThreshold 次 Success 才算 Success
if (result == results.Failure && w.resultRun < int(w.spec.FailureThreshold)) ||
    (result == results.Success && w.resultRun < int(w.spec.SuccessThreshold)) {
    return true   // 状态不变，继续探测
}
w.resultsManager.Set(w.containerID, result, w.pod)
```

三种 probe 的初始值不同（`newWorker:112-125`）：

| probe | initialValue | 设计意图 |
|---|---|---|
| readiness | **Failure** | "没就绪之前一律 NotReady"——防止 kubelet 刚起就把 Pod 标 Ready |
| liveness | **Success** | "还没挂就先算活着"——防止 kubelet 刚起、liveness 还没跑就把容器重启自杀 |
| startup | **Unknown** | "startup 过没过要等 probe 自己说"——Unknown 是中性值，让 `isContainerStarted` 明确区分 |

### onHold：失败后暂停探测

liveness 判 Failure 或 startup 判 Failure 达到阈值后（worker.go:381-390），worker 置 `w.onHold = true` 且 `w.resultRun = 0`，下一次循环的 `doProbe` 在闸门 1 就返回 `true`——**直到 runtime 返回一个新的 containerID（容器被重启了）才解除 onHold**。注释里的原因是跑 `docker exec` 时容器可能正处于 stop 过程中会产生不可预测行为（旧 issue #21751）。

### 探针的四种实现与重试

`prober.runProbe`（`pkg/kubelet/prober/prober.go:152`）按 spec 分派，四种实现共享一个重试包装 `runProbeWithRetries`（最多 3 次）：

| 类型 | 实际执行 | 超时 |
|---|---|---|
| Exec | `kubecontainer.CommandRunner.RunInContainer` → CRI ExecSync | `TimeoutSeconds` 秒 |
| HTTP GET | `httpprobe.Probe(req, timeout)`，可选 H2C（`HTTPProtocolHTTP2` + `H2CContainerProbe` 门） | 同上 |
| TCP Socket | `tcpprobe.Probe(host, port, timeout)` 单纯 Dial | 同上 |
| GRPC | `grpcprobe.Probe(host, service, port, timeout, options)`，可选 TLS 模式 | 同上 |

三条容易被忽略的细节：

- **Exec probe 拿不到 Pod env / downward API**——注释明确说了（`:348`），因为 exec 命令是直接在容器里跑，kubelet 不会帮它注入。
- **HTTP probe 不跟随非本地重定向**（`followNonLocalRedirects = false`，`:61`）——防止攻击者让 probe 打内网。
- **results.Manager 只有一个 Updates channel**（`results_manager.go:38` 的 NOTE），所以 sync loop 三路 select 各自读同一个 channel、互不阻塞（channel 容量 20）。

### restartable init container 的 probe

v1.37 里 probe manager 已支持 restartable init container（sidecar 模式）：`AddPod` 时把 `pod.Spec.Containers` 和 `getRestartableInitContainers` 拼起来（`prober_manager.go:203`），worker 创建与普通容器完全一样。UpdatePodStatus 里也有对应的 initContainer 分支（`:389-431`）。普通 init container 不参与 probe。

### Manual Trigger：UpdatePodStatus 里的即时探测

`UpdatePodStatus`（`:344`）是**状态回写前的"最终校准"**：如果 readinessManager 还没有这个 containerID 的结果（probe 还没跑过第一次），它会向 worker 的 `manualTriggerCh` 非阻塞写一次，**强制让 probe 在这次 status 写回之前先跑一轮**。这样首次 Ready 状态不会被错误地写成 false。这就是 sync loop 里 readiness 分支先 `SetContainerReadiness` 再 `handleProbeSync` 的原因——handleProbeSync 里的 HandlePodSyncs 会再进一次 UpdatePodStatus，第二次就拿到真实 probe 结果了。

## Pod Admission and Dispatch

`HandlePodAdditions`（`:2883`）是"新 Pod 进入节点"的唯一入口，v1.37 的顺序与旧版本差异明显：

```go
func (kl *Kubelet) HandlePodAdditions(ctx context.Context, pods []*v1.Pod) {
	sort.Sort(sliceutils.PodsByCreationTime(pods))         // 按创建时间排序，保证确定性
	for _, pod := range pods {
		kl.podManager.AddPod(pod)                           // desired state 的唯一真相来源
		kl.podCertificateManager.TrackPod(ctx, pod)         // Pod 证书（PodCertificate 特性）

		pod, mirrorPod, wasMirror := kl.podManager.GetPodAndMirrorPod(pod)
		if wasMirror {
			if pod == nil { continue }                      // 找不到源 Pod 的 mirror pod 直接跳过
			kl.podWorkers.UpdatePod(ctx, UpdatePodOptions{
				Pod: pod, MirrorPod: mirrorPod, UpdateType: kubetypes.SyncPodUpdate, StartTime: start,
			})
			continue
		}

		if !kl.podWorkers.IsPodTerminationRequested(pod.UID) && !podutil.IsPodPhaseTerminal(pod.Status.Phase) {
			if ok, reason, message := kl.allocationManager.AddPod(ctx, kl.GetActivePods(), pod); !ok {
				kl.rejectPod(ctx, pod, reason, message)     // 准入失败：写失败状态 + 事件
				continue
			}
		}
		kl.podWorkers.UpdatePod(ctx, UpdatePodOptions{
			Pod: pod, MirrorPod: mirrorPod, UpdateType: kubetypes.SyncPodCreate, StartTime: start,
		})
	}
}
```

三个必须记住的点：

1. **准入在 `allocationManager.AddPod`，不是 `canAdmitPod`**。设备、CPU 亲和、拓扑、Pod 级资源都在这里一次性分配并判定。旧资料里的 `kubecontainer.DoPodAdmission` 已移除。
2. **`podManager.AddPod` 无条件先执行**。即使后面准入失败、Pod 被 reject，desired state 里也必须有它——否则清理逻辑会把它当"apiserver 已删除"的对象处理。
3. **mirror pod（静态 Pod 的镜像）不再进入准入流程**，直接转成对源 Pod 的 `SyncPodUpdate`。

`dispatchWork` 的实质只有一句：`kl.podWorkers.UpdatePod(...)`。**真正的同步不在调用方 goroutine 里跑**，而是交给该 Pod 专属的 pod worker。

## Pod Worker State Machine

每个 Pod 有一个独立 worker 与一条**容量为 1** 的通知通道。状态机是三态（`pkg/kubelet/pod_workers.go:112`）：

```go
SyncPod         PodWorkerState = iota   // 创建与稳态同步
TerminatingPod                          // 停止容器、收集退出状态
TerminatedPod                           // 清理资源、写最终状态
```

`podWorkerLoop`（`:1245`）按状态分派：

```go
switch {
case update.WorkType == TerminatedPod:
	err = p.podSyncer.SyncTerminatedPod(ctx, update.Options.Pod, status)
case update.WorkType == TerminatingPod:
	err = p.podSyncer.SyncTerminatingPod(ctx, update.Options.Pod, status, gracePeriod, podStatusFn)
default:
	err = p.podSyncer.SyncPod(ctx, update.Options.Pod, status)
}
```

`UpdatePod`（`:761`）的并发控制是这套设计的核心：

```go
if !p.isWorking[pod.UID] {
	p.isWorking[pod.UID] = true
	podUpdates <- *options              // 通道容量 1，写入即触发
} else {
	// worker 忙时只保留"最后一次未送达的更新"，旧值被覆盖
	update, found := p.lastUndeliveredWorkUpdate[pod.UID]
	if !found || update.UpdateType != kubetypes.SyncPodKill {
		p.lastUndeliveredWorkUpdate[pod.UID] = *options
	}
}
```

也就是说：**并发更新会被合并成"最新一次配置 + 一次通知"，且 Kill 请求优先级最高、不会被覆盖**。这是 kubelet 在配置高频抖动下仍能保持稳定的关键——永远只有"当前正在跑的一次 + 一个待送达的最新状态"。

> [!IMPORTANT]
> 优雅删除的 grace period **只能缩短、不能延长**。这是明确的设计约束，避免驱逐与滚动更新叠加时无限推迟删除。

终止的语义边界也很清楚：`SyncTerminatingPod` 成功 = 所有容器已停止；`SyncTerminatedPod` 成功 = 资源清理完毕、可以写最终状态。`IsPodKnownTerminated` / `ShouldPodBeFinished` 分别对应这两个里程碑。

## SyncPod: The Transaction Script

`kl.SyncPod`（`:2053`）是"把单个 Pod 收敛到期望状态"的事务脚本，可重入，每次失败后下一轮从当前实际状态继续推进。v1.37.2 的执行顺序（源码逐步读出的顺序）：

```
① 记录 PodWorkerStartDuration（updateType == SyncPodCreate）
② InPlacePodVerticalScaling：检查 resize 是否进行中，维护 PodResizeInProgress condition
③ generateAPIPodStatus → statusManager.SetPodStatus
④ 若 Phase 已是 Succeeded / Failed → isTerminal = true，直接返回
⑤ 运行时网络未就绪且非 hostNetwork → 报 NetworkNotReady，返回错误
⑥ secretManager / configMapManager RegisterPod（让引用对象进入缓存）
⑦ Pod 级 cgroup：不存在且非首次同步 → 先 killPod 再重建（QoS 层级迁移）
⑧ tryReconcileMirrorPods（静态 Pod 的 mirror pod 增删）
⑨ makePodDataDirs（创建 Pod 数据目录）
⑩ volumeManager.WaitForAttachAndMount（阻塞等卷挂载）
⑪ containerRuntime.InitializeActuatedPod
⑫ getPullSecretsForPod → probeManager.AddPod
⑬ containerRuntime.SyncPod（用 context.WithoutCancel）
⑭ reasonCache.Update，RestartAllContainers 场景按需再入队
```

几个与旧版本差别最大的地方：

- **"不该运行的 Pod 就地 kill"那段代码没有了**。终止不再由 SyncPod 内部完成，而是 pod worker 切到 `TerminatingPod` 状态调 `SyncTerminatingPod`。SyncPod 只在发现 Pod 已是终态时置 `isTerminal`。
- **Pod 状态在准入之后、启动之前就写回**（第 ③ 步）。因此 `kubectl describe` 看到的 pending 原因来自 status manager 的中间态，而不是等容器建完。
- **`WaitForAttachAndMount` 是 `ContainerCreating` 卡住的主要来源**：它阻塞该 Pod 的 sync goroutine，等的是「kubelet 上报 VolumesInUse → controller attach 并写 VolumesAttached → kubelet 读到」这一整圈经 etcd 的异步往返，而不是本地操作。卷挂载上限超限时走 `rejectPod`。完整链路见 [持久化存储](/docs/CS/Container/k8s/Storage.md)。

## kuberuntime SyncPod: computePodActions

`kubeGenericRuntimeManager.SyncPod`（`pkg/kubelet/kuberuntime/kuberuntime_manager.go:1583`）负责真正的 CRI 调用。它的第一步不是"创建容器"，而是**算出一份差异清单**：

```go
podContainerChanges := m.computePodActions(ctx, pod, podStatus, restartAllContainers)
```

`computePodActions`（`:1279`）的核心判定：

```go
createPodSandbox, attempt, sandboxID, _ := runtimeutil.PodSandboxChanged(pod, podStatus)
changes := podActions{
	KillPod:           createPodSandbox,     // sandbox 变了 → 整个 Pod 重建
	CreateSandbox:     createPodSandbox,
	SandboxID:         sandboxID,
	Attempt:           attempt,
	ContainersToStart: []int{},
	ContainersToKill:  make(map[kubecontainer.ContainerID]containerToKillInfo),
}
```

后续几个关键分支：

| 条件 | 结果 |
|---|---|
| `PodSandboxChanged`（sandbox 缺失/状态异常/ID 变化） | `KillPod = true` + `CreateSandbox = true`，init 容器需要 purge |
| 不需要重启（`!shouldRestartOnFailure` 且 `attempt != 0` 且已有容器状态） | `CreateSandbox = false`，直接返回，避免给已结束的 Pod 再建 sandbox |
| `RestartAllContainersOnContainerExits` 开启且被标记 | 只填 `ContainersToReset`，按**逆序**杀容器（触发源容器最后移除） |
| 计算启动集 | 遍历 `pod.Spec.Containers`，`OnFailure` 策略且已成功的不再启动；`ContainerRestartRules` 支持容器级 restartPolicy |

SyncPod 的主干（`:1583` 起）：

```
Step 1  computePodActions
Step 2  KillPod == true → killPodWithSyncResult（sandbox 变更时额外 purgeInitContainers）
Step 3  否则逐个 kill ContainersToKill；RestartAllContainers 时对 ContainersToReset 先 kill 再 remove
        pruneInitContainersBeforeStart（主动修剪已退出的 init 容器，不等 GC）
Step 4  CreateSandbox → generatePodSandboxConfig → RunPodSandbox（生成 sandbox 配置、建日志目录、拿 podIPs）
后续    按 changes.InitContainersToStart / ContainersToStart 依次创建 init 容器与业务容器
```

> [!TIP]
> "先算差异、再执行动作"是 kubelet 可重入的根本。SyncPod 不假设上一轮走到哪一步，全部依据 `podStatus` 的当前观测重新计算。这也解释了为什么 kubelet 重启后能自然接管已有容器：它看到的 podStatus 就是真实状态。

## PLEG

PLEG（Pod Lifecycle Event Generator）是 kubelet 感知运行时状态的唯一来源。它把"运行时里实际有什么"与"上一轮记的有什么"做 diff，产生 `ContainerStarted` / `ContainerDied` / `ContainerRemoved` / `PodSync` 等事件。

`GenericPLEG.Start`（`pkg/kubelet/pleg/generic.go:158`）刻意把首个 timer 设为 0，**启动即立刻 relist 一次**，之后才按 `RelistPeriod` 周期跑。

`workerLoopIteration`（`:192`）用非阻塞 select 实现**三级优先级**：

```go
// 1. 最高优先：stopCh
select { case <-g.stopCh: return false; default: }

// 2. 次高优先：全局 relist（避免被单 Pod 请求饿死）
select {
case <-g.globalRelistTimer.C():
	g.Relist(ctx); g.globalRelistTimer.Reset(g.relistDuration.RelistPeriod); return true
default:
}

// 3. 兜底阻塞：stopCh / 全局 relist / 单 Pod relist 队列
select {
case <-g.stopCh: return false
case <-g.globalRelistTimer.C(): g.Relist(ctx); ...
case req := <-g.relistRequests:
	if req.timestamp.After(g.getRelistTime()) { g.relistPod(ctx, req.podUID) }
}
```

单 Pod relist 还带一个**时间戳去重**：如果请求时间早于最近一次全局 relist，说明这个请求已经被那轮全局 relist 覆盖，直接丢弃。这也是 SyncPod 结束后能"按需立刻刷新状态"而不放大 QPS 的原因。

`Relist`（`:289`）的主体只有五步：

```go
podList, err := g.runtime.GetPods(ctx, true)     // ① 一次性列出所有 Pod 与容器（含 sandbox）
g.updateRelistTime(timestamp)                    // ② 更新活跃时间（Healthy 依据）
g.podRecords.setCurrent(pods)                    // ③ 当前记录入位
for pid := range g.podRecords { g.reconcilePodRecord(ctx, pid) }   // ④ 逐 Pod diff
g.cache.UpdateTime(timestamp)                    // ⑤ 所有 Pod 处理完才推进 cache 时间
```

`reconcilePodRecord`（`:332`）对每个容器调 `computeEvents` 做状态迁移比对；**只有产生了事件（或被标记 reinspect）才 `updateCache`**。而且注释明确写了失败策略：

```go
// updateCache 失败时不更新 podRecord，让下一轮 relist 还能检测到这次变化
```

即 **PLEG 用"不推进旧状态"来实现重试**，不需要额外重试队列。`cache.UpdateTime` 必须放在所有 Pod 处理完之后，否则 cache 会短暂报告一个"已更新但内容还是旧的"时间戳。

`Healthy`（`:235`）判断 `now - lastRelistTime > RelistThreshold`，并把这个值暴露成 `pleg_last_seen_seconds` 指标——**PLEG 卡住时节点会变 NotReady，这是最常见的节点 NotReady 原因之一**。

默认（未开 Evented）的 relist 参数：

| 参数 | 值 | 位置 |
|---|---|---|
| relist 周期 | 1s | `pkg/kubelet/kubelet.go:215` |
| relist 健康阈值 | 3min | `pkg/kubelet/kubelet.go:216` |
| 事件通道容量 | 200（relistRequests）/ 1000（CRI 事件流） | `generic.go:146` / `evented.go:32` |

## PLEG and EventedPLEG: The Dual Channel

v1.37 的 EventedPLEG 与早期设计**完全不是一种东西**，旧资料里"EventedPLEG 自己产生生命周期事件"的描述已经作废。现在的架构（`pkg/kubelet/pleg/evented.go:40-42` 的注释写得很直白）：

> EventedPLEG watches CRI container events and requests low-latency pod relists. **GenericPLEG remains responsible for observing runtime state, updating the cache, and producing pod lifecycle events.**

也就是说双通道的分工是：

| 通道 | 角色 | 是否触碰缓存/事件 |
|---|---|---|
| GenericPLEG（轮询，1s） | 唯一的状态观测者、diff 者、事件生产者 | 是，唯一写者 |
| EventedPLEG（CRI 事件流） | 低延迟**提示**：只触发单 Pod relist | 否，纯粹是"加速器" |

### Why Events Became Just Hints

旧设计里 EventedPLEG 自己把 CRI 事件翻译成 `ContainerDied` 等生命周期事件直接发出去，但事件流与轮询之间天然存在乱序与丢失（事件可能是旧的、可能重复、流可能断），两条事件来源让下游 syncLoop 处理竞态非常困难。v1.37 的解法是**把事件降级为 relist 提示**：EventedPLEG 收到事件后只调 `RequestRelist(podUID)`，真正的状态比对仍由 GenericPLEG 单点完成。竞态消失了，因为写缓存的永远只有一个组件。

事件过滤极其苛刻（`evented.go:118-130`）：

```go
if event.PodSandboxStatus == nil || event.PodSandboxStatus.Metadata == nil {
	continue    // sandbox 已被删的竞态，丢弃（注释：最坏情况 relist 兜底）
}
if event.ContainerEventType != runtimeapi.ContainerEventType_CONTAINER_STOPPED_EVENT {
	continue    // 只有容器停止才走快速通道
}
e.podRelister.RequestRelist(logger, podID)
```

**只有 CONTAINER_STOPPED 会触发即时 relist**。原因：容器死亡是对延迟最敏感的事件——它决定 kubelet 多快重启容器、多快上报 Failed；而容器启动本来就由 kubelet 自己发起，它不需要被"通知"。sandbox 为 nil 的事件直接丢弃，最坏情况有周期性 relist 兜底。

### The On-Demand Relist Path

快速通道落地的三段都在 GenericPLEG 里：

1. **入队**（`generic.go:551` 的 `RequestRelist`）：容量 200 的 channel，**非阻塞写入，满了直接丢**并打 error——快速通道宁可丢请求也不阻塞 CRI 事件流。
2. **去重执行**（`workerLoopIteration:219`）：`req.timestamp.After(g.getRelistTime())` 才执行——如果上一次全局 relist 已经覆盖了这个时刻，请求作废。
3. **单 Pod 刷新**（`relistPod:413`）：用 `runtime.GetPod`（单 Pod 查询，比全局 `GetPods` 便宜）更新该 Pod 的 record 并走同一条 `reconcilePodRecord` diff；**不推进全局 relist 时间戳**，只 `cache.SetObservedTime`——否则快速通道会"假装"全局 relist 发生过，干扰 Healthy 判定。

效果：**容器死亡的检测延迟从最坏 ~2s（两轮 1s 轮询）压到亚秒级**，而轮询 QPS 不变。

### Stream Resilience and Gates

CRI 事件流的重连逻辑（`evented.go:74-99`）是有限重试：`eventedPlegMaxStreamRetries = 5`（`kubelet.go:219`），断流/出错重连 5 次后**彻底放弃快速通道**，打 error 日志退回纯轮询——不会无限重试把 runtime 打爆。`GetContainerEvents` 是 CRI 的流式 RPC，连接指标为 `kubelet_evented_pleg_connections` / `_errors_total` / `_latency`。

v1.37.2 的门控状态（`pkg/features/kube_features.go`）：

| 特性门 | 状态 | 说明 |
|---|---|---|
| `PLEGOnDemandRelist` | **v1.37 GA、锁定为 true**（`:1930`，v1.40 移除该门） | 单 Pod 按需 relist 已永久化 |
| `EventedPLEG` | **仍是 Alpha、默认关闭**（`:1595`，自 v1.26 起未推进） | 依赖 `PLEGOnDemandRelist`（`:2639`），开启时必须同时满足 |

> [!WARNING]
> 两个常见误解：其一，EventedPLEG 并没有 GA，v1.37 里默认仍关；其二，开启它**不再放宽轮询周期**——v1.37 里 `genericPlegRelistPeriod` 恒为 1s（`kubelet.go:891`），旧的"evented 模式轮询放宽到 5 分钟"常量已被删除。EventedPLEG 只是叠加在 1s 轮询之上的快速通道，开不开都不影响兜底延迟上界。

## Status Reporting

状态回写是另一条独立链路，它和 SyncPod 的耦合点只有 `statusManager.SetPodStatus`：

```
SyncPod: generateAPIPodStatus(pod, podStatus)     ← 合并 desired spec 与运行时观测
        → statusManager.SetPodStatus
        → statusManager 内部按 version 比较、限流、批量 PATCH Pod status
```

要点：**status manager 不做业务判断，只负责"把 kubelet 认为的状态可靠地送到 apiserver"**。它维护每个 Pod 的版本号，避免回退覆盖；并在 Pod 终止后等待 `SyncTerminatedPod` 完成才发最终状态（`pod_workers.go` 注释中的 `status manager is waiting for SyncTerminatedPod`）。

## Local Autonomy

kubelet 有两条完全绕开 apiserver 的自主链路，理解它们才能解释很多"对象还在但容器没了"的现象：

- **镜像 GC**：`imageManager.Start` 起两个 goroutine——5 分钟一次 `detectImages`（找出未使用镜像并删除），30 秒一次刷新 imageCache。全部通过 CRI 的 `ListImages` / `GetPods` 实现。
- **节点压力驱逐**：每 10s 轮询水位，越线就本地杀 Pod，并把压力写成 Node condition 上报，**不经过 apiserver 删除 Pod 对象**。默认阈值（Linux）：`memory.available=100Mi`、`nodefs.available=10%`、`imagefs.available=15%`。完整链路见 [驱逐](/docs/CS/Container/k8s/Eviction.md)。

kubelet 自己的身份也是一条自主链路：生成密钥 → 构造 CSR → 等审批 → 落 `kubelet-client-current.pem` → 生命周期 70%~90% 处自动轮换；服务端证书还需 `--rotate-server-certificates` 与 gate `RotateKubeletServerCertificate` 双条件。详见 [身份与证书](/docs/CS/Container/k8s/Identity.md)。

## Volume Manager: DSW → ASW Reconciler

SyncPod 的 ⑩ `WaitForAttachAndMount` 卡在**等待 volume manager 的异步状态收敛**。`volumeManager.Run`（`pkg/kubelet/volumemanager/volume_manager.go:319`）起三个独立 goroutine：

| goroutine | 周期 | 职责 |
|---|---|---|
| `desiredStateOfWorldPopulator.Run` | 100ms loop | 遍历 podManager 里的 Pod，把 spec 里的 volume 转成 DSW（Desired State of World）条目 |
| `reconciler.Run` | **100ms loopSleepDuration**（`:63`） | **纯调度器**：比较 DSW 与 ASW，发起 Attach / Mount / Unmount / Detach |
| `volumeHealthManager.Run` | 可选 | 只有 `CSIVolumeHealth` 特性门开时启动，上报 volume 健康状态 |

核心循环是 reconciler 的 `reconcile`（`reconciler.go:33`）：

```go
func (rc *reconciler) reconcile(ctx context.Context) {
    readyToUnmount := rc.readyToUnmount()
    if readyToUnmount {
        rc.unmountVolumes(logger)               // 先 unmount，给被删 Pod 腾位置
    }
    rc.mountOrAttachVolumes(logger)              // 推进挂载/附着
    if readyToUnmount {
        rc.unmountDetachDevices(logger)           // 再 detach 设备
        rc.cleanOrphanVolumes(logger)            // 清理无法重建的孤儿 volume
    }
}
```

### mountOrAttachVolumes: 四分支分派

`mountOrAttachVolumes`（`reconciler_common.go:169`）对 DSW 里每个 `volumeToMount` 走四分支：

```go
for _, volumeToMount := range rc.desiredStateOfWorld.GetVolumesToMount() {
    if rc.operationExecutor.IsOperationPending(volumeToMount.VolumeName, EmptyUniquePodName, EmptyNodeName) {
        continue   // 上一轮 reconcile 起的异步 goroutine 还没结，跳过
    }
    volMounted, devicePath, err := rc.actualStateOfWorld.PodExistsInVolume(...)
    switch {
    case cache.IsVolumeNotAttachedError(err):
        rc.waitForVolumeAttach(logger, volumeToMount)     // ← 可能要等 controller
    case !volMounted || cache.IsRemountRequiredError(err):
        rc.mountAttachedVolumes(logger, volumeToMount)    // ← 真正 MountVolume
    case cache.IsFSResizeRequiredError(err):
        rc.expandVolume(logger, volumeToMount)
    }
}
```

`IsOperationPending` 是这个模型的关键：**同一个 volumeName + podName + nodeName 的同一类型操作，pendingOperations 里只允许一个**。reconciler 不阻塞、不等待，只做"差距扫描 + 未初始化差距起操作"，100ms 一轮 O(N)。

### Attach 有两条路径

`waitForVolumeAttach`（`reconciler_common.go:232`）分叉在 `controllerAttachDetachEnabled`（由 Kubelet flag `--enable-controller-attach-detach` 决定）：

| 模式 | 谁负责 Attach | reconciler 动作 | 典型场景 |
|---|---|---|---|
| `controllerAttachDetachEnabled = true`（默认） | **CSI Attacher controller**（cloud-controller-manager / external-attacher） | `VerifyControllerAttachedVolume`——轮询检查 `node.status.volumesAttached`，没标记就继续等 | 大多数云盘 |
| `controllerAttachDetachEnabled = false` | **kubelet 自己** | `operationExecutor.AttachVolume`——起 goroutine 调 volume plugin 的 Attacher.Attach 实现 | 旧式 in-tree 插件 / 本地盘 |

前者是**跨进程异步**（apiserver 写 Node status，controller watch 到后调 CSI ControllerPublishVolume，再写回 volumesAttached），后者是**进程内 goroutine**。这正是 `WaitForAttachAndMount` 超时设成 2min3s 的原因——controller attach 涉及经 etcd 的全链往返，不能太快判失败。

### operationExecutor: Goroutine Spawner

`operationExecutor.AttachVolume` / `MountVolume`（`operation_executor.go:772/:834`）的实现都是：

```go
func (oe *operationExecutor) AttachVolume(...) error {
    generatedOperations := oe.operationGenerator.GenerateAttachVolumeFunc(...)
    return oe.pendingOperations.Run(volumeToAttach.VolumeName, podName, nodeName, generatedOperations)
}
```

`pendingOperations.Run` 起 goroutine 执行 operation assembler，**reconciler 拿到 nil 立即返回**，下一轮就 `IsOperationPending` 跳过。goroutine 完成后**直接修改 ASW**（MarkVolumeAsAttached / MarkVolumeMounted / MarkVolumeAsUnmounted），reconciler 下一轮才"看见"。

### WaitForAttachAndMount: SyncPod 的阻塞点

回到 SyncPod ⑩（`volume_manager.go:422`）：

```go
// 强制让 populator 重解析这个 Pod 的 spec（可能有变化）
vm.desiredStateOfWorldPopulator.ReprocessPod(uniquePodName)

err := wait.PollUntilContextTimeout(
    ctx,
    podAttachAndMountRetryInterval,  // 300ms
    podAttachAndMountTimeout,         // 2min + 3s
    true,
    vm.verifyVolumesMountedFunc(uniquePodName, expectedVolumes))
```

这不是调 reconciler，reconciler 一直在 100ms 跑着。WaitForAttachAndMount 是**观察者**：每 300ms 看一眼 ASW 里"这个 Pod 所有期望的 volume 是否都 mounted 了"，2 分 3 秒还没齐就报错。错误信息里会告诉你 unmounted 哪些、unattached 哪些、哪些还没进 DSW。

四个关键超时/周期：

| 常量 | 值 | 位置 | 说明 |
|---|---|---|---|
| `reconcilerLoopSleepPeriod` | **100ms** | `volume_manager.go:63` | reconcile 循环周期 |
| `waitForAttachTimeout` | **10min** | `volume_manager.go:90` | 单次 Attach / Mount goroutine 的 ctx 超时 |
| `podAttachAndMountRetryInterval` | **300ms** | `volume_manager.go:82` | WaitForAttachAndMount 的轮询间隔 |
| `podAttachAndMountTimeout` | **2min3s** | `volume_manager.go:78` | WaitForAttachAndMount 总超时 |

### 为什么 reconciler 先 unmount 再 mount

`reconciler.go:36-40` 注释写得直白：volume 是有限资源，**如果一个 Pod 被删了、另一个 Pod 引用同一块 volume，必须先让旧 Pod unmount，再给新 Pod mount**，不然新 Pod 会因为 volume 还被旧 Pod 挂着而失败。unmount 先于 mount 就是这个原因。

### readyToUnmount 闸门

`readyToUnmount`（`reconstruct.go:30`）在 reconciler 里出现两次（unmountVolumes 和 unmountDetachDevices 都 gated 它），核心目的是：**DSW 和 ASW 都"收齐"了才开始 unmount**——避免 populator 还在跑、新 Pod 的 volume 还没进 DSW，reconciler 就把一个 volume unmount 掉，结果新 Pod 也要用它，等于白费一次 IO。

## v1.37 Structural Notes

| 变更 | 说明 |
|---|---|
| `pkg/kubelet/cri/` → `k8s.io/cri-client` | 拆成独立 staging 模块，流式接口另立 `k8s.io/cri-streaming` |
| `kuberuntime_pod.go` → `kuberuntime_sandbox.go` | 文件改名 |
| `pkg/kubelet/network/cni` 出树 | 该目录下只剩 `dns/` |
| 模块初始化两段化 | `initializeModules` 不再启动 containerManager / evictionManager / containerLogManager，改由 `initializeRuntimeDependentModules` 在运行时就绪后启动 |
| 准入迁移 | `kubecontainer.DoPodAdmission` 移除，改到 `HandlePodAdditions → allocationManager.AddPod` |
| 主循环上下文化 | `syncLoop` / `syncLoopIteration` 全面改用 ctx，新增 readiness / startup / containerManager 三路事件 |

## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)
- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [Pod](/docs/CS/Container/k8s/Pod.md)
- [containerd 运行时](/docs/CS/Container/k8s/containerd.md)
- [驱逐](/docs/CS/Container/k8s/Eviction.md)
- [client-go](/docs/CS/Container/k8s/client-go.md)

## References

1. [kubelet source (v1.37.2)](https://github.com/kubernetes/kubernetes/tree/v1.37.2/pkg/kubelet)
2. [Kubelet: The Kubernetes Node Agent](https://kubernetes.io/docs/reference/command-line-tools-reference/kubelet/)
3. [CRI: Container Runtime Interface](https://github.com/kubernetes/cri-api)
4. [Pod Lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/)
