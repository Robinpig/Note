## Introduction

K8s 对"怎么跑应用"的回答不是命令，而是一组**工作负载对象**：你声明期望状态，控制器把实际状态逐步拉回期望。五个内建控制器（Deployment、StatefulSet、DaemonSet、Job、CronJob）共享同一套骨架——Informer 监听、workqueue 排队、reconcile 里按当前对象算下一步动作——但它们对"Pod 的身份、顺序、生命周期"的假设完全不同：

| 对象 | 直接管理的对象 | Pod 身份 | 核心语义 | 典型用途 |
|---|---|---|---|---|
| Deployment | ReplicaSet → Pod | 可丢弃、互相等价 | 滚动替换无状态副本 | Web 服务、API |
| StatefulSet | Pod（+ PVC） | 稳定序号与网络标识 | 有序创建/更新，数据随身份走 | 数据库、消息队列 |
| DaemonSet | Pod | 每节点一个 | 节点级常驻 | CNI、日志采集、设备插件 |
| Job | Pod | 跑完即止 | 至少成功 N 次 | 批处理、迁移 |
| CronJob | Job | 按时间产生 | 周期触发 Job | 定时任务、报表 |

> [!NOTE]
> 本文结论基于 **Kubernetes v1.36.4** 源码，文件路径与行号均对应 `kubernetes/kubernetes@v1.36.4`。默认值集中在 `pkg/apis/apps/v1/defaults.go` 与 `pkg/apis/batch/v1/defaults.go`，控制器逻辑分别在 `pkg/controller/{deployment,statefulset,daemon,job,cronjob}/`。

## Common Skeleton

五个控制器都不是"轮询 etcd"，而是标准控制器模式：

```
API Server watch ──► Informer 本地缓存 ──► workqueue（key，去重 + 限速）
                                                │
                                                ▼
                                     reconcile(key)，比较期望与实际
                                                │
                                     ┌──────────┴──────────┐
                                     ▼                     ▼
                              创建/删除/更新对象       更新 status → 触发下一轮
```

这带来两个容易误判的后果。**其一，控制器对"状态"没有记忆**：每次 reconcile 都从缓存重建判断，所以手工改掉副本数、删掉一个 Pod，下一轮就会被纠正；反过来，控制器重启不会"忘记进度"，因为进度写在对象的 `status` 里。**其二，事件只是提示，不是事实**：Informer 可能合并、乱序、丢失事件，控制器的正确性依赖 resync 与水平触发（level-triggered），这也是为什么调谐函数必须幂等。

所有工作负载对象还共享三个契约：

- **OwnerReference 决定级联**：Deployment 拥有 ReplicaSet，ReplicaSet 拥有 Pod，CronJob 拥有 Job。删除父对象时，GC 沿 owner 链处理，细节见 [删除与级联](/docs/CS/Container/k8s/Deletion.md)。
- **selector 是控制器的"所有权声明"**：控制器只管理匹配 selector 且 owner 指向自己的 Pod；修改 selector 的语义等于换一批 Pod。
- **每次 Pod 模板变更都产生新 revision**：Deployment 用新 ReplicaSet 承载，StatefulSet/DaemonSet 用 ControllerRevision 记录，回滚就是切回旧 revision。

## Deployment

Deployment 是最常用、也最容易被"会用但不懂"的对象。它本身不直接建 Pod，而是以 **ReplicaSet 为版本单位**：Pod 模板一变，Deployment 控制器计算模板哈希，创建（或复用）对应 hash 的 ReplicaSet，再把副本在新旧 ReplicaSet 之间迁移。

### Defaults

| 字段 | 默认值 | 源码 |
|---|---|---|
| `replicas` | 1 | `pkg/apis/apps/v1/defaults.go:40` |
| `strategy.type` | `RollingUpdate` | `defaults.go:46` |
| `strategy.rollingUpdate.maxSurge` | `25%` | `defaults.go:59` |
| `strategy.rollingUpdate.maxUnavailable` | `25%` | `defaults.go:54` |
| `revisionHistoryLimit` | 10 | `defaults.go:65` |
| `progressDeadlineSeconds` | 600 | `defaults.go:69` |
| `minReadySeconds` | 0 | 无默认化，零值即 0 |

`revisionHistoryLimit` 只限制**缩到 0 后保留的旧 ReplicaSet 数量**，不是"能回滚多少次"的硬上限；旧 RS 被清掉后，对应 revision 就不可回滚。设成 `math.MaxInt32` 表示全部保留（`pkg/controller/deployment/util/deployment_util.go:916-919`）。

### Rolling Update Math

滚动更新的两个"闸门"不是独立生效的，它们要一起解：

- `maxSurge` 是**最多能超出期望副本数多少**，百分比**向上取整**；
- `maxUnavailable` 是**最多能少多少可用副本**，百分比**向下取整**。

`ResolveFenceposts`（`deployment_util.go:887`）先分别换算，再处理一个边角：若两者都算成 0（例如副本数很小 + 百分比很低），把 `maxUnavailable` 改成 1，否则更新会永久卡住。升级时新 ReplicaSet 的目标副本数由 `NewRSNewReplicas` 计算（`deployment_util.go:820`）：

```
maxTotalPods = replicas + maxSurge
若当前所有 RS 的 Pod 总数 >= maxTotalPods → 不再扩容
否则 newRS 最多扩到 replicas
```

缩旧 RS 侧则受 `allPodsCount - minAvailable - newRSUnavailable` 约束（`pkg/controller/deployment/rolling.go:111`），注释里给了一个 10 副本、2 unavailable、3 surge 的具体推演：**新 RS 的 Pod 不健康时，旧 RS 不能继续缩**，否则一次节点故障就可能把可用副本打穿。

> [!WARNING]
> `maxUnavailable: 0` 并不等于"绝对不中断"：它只保证**不主动**让旧 Pod 不可用。新 Pod 起不来、节点漂移、驱逐仍会造成不可用。真正的零中断需要 `maxSurge > 0` + readiness probe + PDB 配合，而 PDB 保护的是**自愿中断**（驱逐），不是滚动更新。

### Progress and Timeout

Deployment 的进度不是看"有没有新 Pod"，而是看 `Progressing` condition 的 `lastUpdateTime`：只要 `updatedReplicas`、`availableReplicas` 等指标有推进，条件就刷新；停滞超过 `progressDeadlineSeconds` 后写成：

```
type: Progressing
status: "False"
reason: ProgressDeadlineExceeded
```

（`pkg/controller/deployment/progress.go:86-95`）。控制器会按剩余时间把自己重新入队（`progress.go:160-199`），所以**不需要外部轮询**也能在到点时更新状态。注意超时**不会自动回滚**，它只是把失败暴露出来；`kubectl rollout undo` 仍需人工或流水线触发。

`kubectl rollout status` 读的正是这个 condition；它卡住时先看 `kubectl describe deploy` 里的 `Progressing` message，而不是只看 Pod 列表。

### Recreate and Pause

- `strategy.type: Recreate`：先杀掉全部旧 Pod，再创建新 Pod，必然中断，适合"新旧版本不能共存"的场景（如独占数据库 schema）。
- `spec.paused: true`：控制器只同步副本数，不推进模板变更；可以连续改多次模板后一次性恢复，避免产生一堆中间 revision。
- 纯扩缩容（只改 `replicas`）**不会**产生新 ReplicaSet，revision 不变。

### Ownership and Hash

新 ReplicaSet 的名字是 `<deployment-name>-<pod-template-hash>`，hash 由 Pod 模板计算（忽略 `pod-template-hash` 标签本身，`deployment_util.go:619`）。Deployment 通过 `deployment.kubernetes.io/revision` 注解记录版本序号，回滚时按 revision 找到对应 RS 并放大它。

一个常见故障是"Deployment 的 selector 与模板 labels 不匹配"：selector 在创建后不可变，模板 labels 必须覆盖 selector，否则 API 校验直接拒绝，或控制器永远认为 Pod 不属于自己。

## StatefulSet

StatefulSet 解决的是"Pod 不能随便换"的问题：每个 Pod 有**稳定序号、稳定 DNS 名、稳定存储绑定**。它不经过 ReplicaSet，直接管理 Pod 和 PVC。

### Identity

对一个名为 `web`、`serviceName: web-headless` 的 StatefulSet：

| 维度 | 形态 |
|---|---|
| Pod 名 | `web-0`、`web-1`…… |
| hostname | `web-0` |
| subdomain | `web-headless` |
| 集群内 DNS | `web-0.web-headless.<ns>.svc.cluster.local` |
| 存储 | `volumeClaimTemplates` 生成的 `<claim>-web-0` |

`spec.serviceName` 必须指向一个 **headless Service**（`clusterIP: None`），否则 DNS 不会为每个 Pod 生成独立 A 记录。StatefulSet 的控制器只保证"名字与序号稳定"，**不保证 IP 稳定**；把 IP 写进配置仍然会坏。

### Ordering

`podManagementPolicy` 默认 `OrderedReady`（`pkg/apis/apps/v1/defaults.go:101`）：

- 扩容：从 0 开始，前一个 Pod **Running 且 Ready** 后才创建下一个；
- 缩容：从最大序号开始倒序删除，前一个消失后才删下一个；
- 更新：从最大序号往下，逐个删除重建，**等新 Pod Ready 再动下一个**。

`Parallel` 则允许同时创建/删除，只保留"最终数量正确"的约束。源码里用 `allowsBurst(set)` 表达这件事：只有 `Parallel` 返回 true（`pkg/controller/statefulset/stateful_set_utils.go:496`），主循环的 `monotonic` 标志随之取反（`stateful_set_control.go:649`）。

### Update Strategies

- `RollingUpdate`（默认）：从最高序号向低推进，遇到 `partition` 停下。`partition: N` 表示**序号 >= N 的 Pod 才更新**，序号 < N 的保持旧 revision（`stateful_set_control.go:711`）。这常被用来做"金丝雀"：先只更新最高序号的少数 Pod。
- `OnDelete`：控制器不主动删 Pod，模板更新后必须手工删除某个 Pod，重建时才套用新模板（`stateful_set_control.go:692-693`）。

`MaxUnavailableStatefulSet` 在 v1.36 仍是 **Beta 且默认关闭**（`pkg/features/kube_features.go:1672`），开启后才允许一次更新多个 Pod；默认行为仍是严格的"一个一个来"。

### Storage Retention

`volumeClaimTemplates` 创建的 PVC 默认**不会**随 Pod 或 StatefulSet 删除而回收，这是数据库场景的默认安全选择。`persistentVolumeClaimRetentionPolicy` 有两个维度（`defaults.go:127-135`）：

| 配置 | 缩容时 | 删除 StatefulSet 时 |
|---|---|---|
| `whenScaled: Retain` + `whenDeleted: Retain`（默认） | 保留 PVC | 保留 PVC |
| `whenScaled: Delete` | 删掉被缩容 Pod 的 PVC | 按 `whenDeleted` |
| `whenDeleted: Delete` | 按 `whenScaled` | 删掉所有关联 PVC |

实现方式是给 PVC 挂不同组合的 ownerReference（`stateful_set_utils.go:240-245`）：删 Pod 时能级联到 PVC，或删 StatefulSet 时能级联，取决于策略。**默认的 Retain 意味着缩容后重新扩容会复用旧数据**——这既是有意设计，也是"为什么缩容后数据还在"的答案。

### Revisions

StatefulSet 用 ControllerRevision 保存每次模板变更，Pod 上打 `controller-revision-hash` 标签（`staging/src/k8s.io/api/apps/v1/types.go:27`），`status.currentRevision` / `status.updateRevision` 分别指向"大多数 Pod 在跑的版本"和"最新模板版本"。回滚通过 `kubectl rollout undo statefulset/<name>` 选旧 revision 完成，本质仍是改模板 + 重新滚动。

## DaemonSet

DaemonSet 的语义是"**每个符合条件的节点一个 Pod**"，典型用于 CNI、kube-proxy、日志/监控 agent、设备插件。

### Bypassing the Scheduler

DaemonSet 控制器创建 Pod 时直接写入 `spec.nodeName`（`pkg/controller/daemon/daemon_controller.go:1416-1423`），**不经过 kube-scheduler**。因此：

- 节点上没有"调度失败"事件，Pod 会直接绑定到该节点；
- 资源不足、污点不容忍等问题在 kubelet 侧表现为 `FailedScheduling` 之外的报错（如 `OutOfcpu`），排查入口不同；
- 节点是否"应该跑"由控制器自己的谓词判断（`NodeShouldRunDaemonPod`，`daemon_controller.go:1378`）：nodeName、nodeAffinity、taints 三项。

### Default Tolerations

控制器会给每个 DaemonSet Pod 注入一组 toleration（`pkg/controller/daemon/util/daemonset_util.go:47-100`）：

| 污点 | effect | 目的 |
|---|---|---|
| `node.kubernetes.io/not-ready` | NoExecute | 节点失联时不被 taint eviction 赶走 |
| `node.kubernetes.io/unreachable` | NoExecute | 同上 |
| `node.kubernetes.io/disk-pressure` | NoSchedule | 压力节点仍可跑 agent |
| `node.kubernetes.io/memory-pressure` | NoSchedule | 同上 |
| `node.kubernetes.io/pid-pressure` | NoSchedule | 同上 |
| `node.kubernetes.io/unschedulable` | NoSchedule | 新节点 cordon 期间也能部署 |
| `node.kubernetes.io/network-unavailable` | NoSchedule | 仅在 `hostNetwork: true` 时注入 |

这解释了为什么"节点刚加入、还没 Ready，DaemonSet Pod 就已经在了"：它不是调度器放上去的，也不受这些污点阻挡。

### Rolling Update

`updateStrategy` 默认 `RollingUpdate`，`maxUnavailable` 默认 **1**，`maxSurge` 默认 **0**（`defaults.go:85-92`）。默认路径是"删一个旧 Pod → 建一个新 Pod"，按节点推进；`maxSurge > 0` 则先建新再删旧，以额外资源换更平滑的切换（`pkg/controller/daemon/update.go:44-266`）。`revisionHistoryLimit` 默认 10（`defaults.go:94`）。

> [!TIP]
> DaemonSet 的 `status.numberReady` / `numberAvailable` / `updatedNumberScheduled` 才是判断滚动是否完成的依据；`kubectl rollout status ds/<name>` 内部也是看这些字段。

## Job

Job 管理"跑完就结束"的 Pod，核心状态是 `succeeded` / `failed` 计数与完成条件。

### Defaults

| 字段 | 默认值 | 源码 |
|---|---|---|
| `completions` / `parallelism`（都未设时） | 1 / 1 | `pkg/apis/batch/v1/defaults.go:37` |
| `parallelism`（单独未设） | 1 | `defaults.go:41` |
| `backoffLimit` | 6 | `defaults.go:44-49` |
| `completionMode` | `NonIndexed` | `defaults.go:55` |
| `suspend` | false | `defaults.go:59` |
| `podReplacementPolicy` | `TerminatingOrFailed`；配了 `podFailurePolicy` 时 `Failed` | `defaults.go:62-70` |
| `manualSelector` | false | `defaults.go:71` |

设置了 `backoffLimitPerIndex` 时，`backoffLimit` 的默认值变成 `math.MaxInt32`（`defaults.go:45-47`），因为失败预算改由每个 index 单独计算。

### Completion Semantics

- `completions` 未设：**任意一个 Pod 成功即视为整体成功**，但控制器会等剩余 active Pod 结束（`job_controller.go:1150-1157`）。
- `completions: N`：成功数达到 N 且没有 active Pod 才完成。
- `completionMode: Indexed`：每个 Pod 带 `batch.kubernetes.io/job-completion-index`，成功集合按 index 计；配合 `backoffLimitPerIndex`、`maxFailedIndexes`、`successPolicy` 可以做"部分成功即完成"的批任务。

### Failure Paths

控制器按固定顺序判定（`job_controller.go:1060-1120`）：

1. 已有 `SuccessCriteriaMet` / `FailureTarget` 条件 → 直接沿用；
2. `podFailurePolicy` 命中 `FailJob` → 失败；
3. `failed > backoffLimit`，或 `restartPolicy: OnFailure` 下容器重启总数超限 → `BackoffLimitExceeded`；
4. `activeDeadlineSeconds` 到期 → `DeadlineExceeded`；
5. Indexed Job 的 `maxFailedIndexes` 超限或出现失败 index → 失败。

Pod 失败后的重试不是立刻发生：默认 10s 起步、指数退避、上限 10 分钟（`DefaultJobPodFailureBackoff` / `MaxJobPodFailureBackoff`，`job_controller.go:76-80`；计算在 `backoff_utils.go:258-282`）。所以 `kubectl get pods` 看到"失败后隔一会儿才出现新 Pod"是正常行为。

### Tracking and TTL

Job 控制器会给它创建的 Pod 加 `batch.kubernetes.io/job-tracking` finalizer，确保"Pod 已结束"和"计数已落库"不会断档；这也是某些 Pod 删除后短暂残留 finalizer 的原因（`job_controller.go:902`）。

`ttlSecondsAfterFinished` 不由 Job 控制器执行，而由独立的 TTL-after-finished 控制器处理：它每秒扫一次，到期后**删除 Job 对象**，Pod 再沿 owner 链被 GC（`pkg/controller/ttlafterfinished/ttlafterfinished_controller.go:206-263`、`:256`）。因此 TTL 到期删的是 Job，不是单独删 Pod；想保留 Job 历史就别设 TTL。

### External Controller

`spec.managedBy` 允许把某个 Job 交给外部控制器管理（`JobManagedBy` 在 v1.35 GA，`pkg/features/kube_features.go:1558`）。一旦设置，内建 Job 控制器不再驱动该 Job，只保留状态读取；这是 Kueue、Volcano 等批调度器接管 Job 的官方接口。

## CronJob

CronJob 是"按 cron 表达式创建 Job"的薄控制器，复杂度几乎都在**错过调度**与**并发策略**上。

### Defaults

| 字段 | 默认值 | 源码 |
|---|---|---|
| `concurrencyPolicy` | `Allow` | `pkg/apis/batch/v1/defaults.go:77` |
| `suspend` | false | `defaults.go:80` |
| `successfulJobsHistoryLimit` | 3 | `defaults.go:83` |
| `failedJobsHistoryLimit` | 1 | `defaults.go:86` |

生成的 Job 名为 `<cronjob-name>-<scheduled-time 的 Unix 分钟数>`（`cronjob_controllerv2.go:677`），因此同一分钟不会重复创建。

### Missed Schedules

每次调谐，控制器从 `max(creationTimestamp, lastScheduleTime)` 起算下一次应触发时间：

- 设了 `startingDeadlineSeconds` 且已超过窗口 → 记 `MissSchedule` 事件，本次不建 Job（`cronjob_controllerv2.go:552-565`）；
- 错过的次数**超过 100** → 记 `TooManyMissedTimes`，并**停止补跑**（`pkg/controller/cronjob/utils.go:170`、`:218`）。这是防止控制器长时间停机后瞬间创建成百上千 Job 的保险丝。

> [!WARNING]
> `startingDeadlineSeconds` 不是"Job 最长运行时间"，而是"**到点后多久内还允许启动**"。它只影响是否创建 Job，不影响已创建 Job 的运行时长；后者要用 Job 的 `activeDeadlineSeconds`。

### Concurrency

| 策略 | 行为 |
|---|---|
| `Allow`（默认） | 允许同一 CronJob 的多个 Job 并行 |
| `Forbid` | 上一个还没结束就跳过本次（记 `JobAlreadyActive` 事件） |
| `Replace` | 删掉正在跑的旧 Job，再创建新 Job |

`Forbid` 的检查读的是 `status.active`，存在极短的竞态窗口；源码注释明确承认"理论上仍可能并发"（`cronjob_controllerv2.go:573-584`）。需要强互斥时，应该在 Job 内部用分布式锁，而不是只依赖这个字段。

### Time Zone

`spec.timeZone` 接受 IANA 时区名（如 `Asia/Shanghai`），空值表示使用 controller-manager 所在机器的本地时区。**依赖节点本地时区是运维陷阱**：控制器迁移到 UTC 机器后，所有 CronJob 的触发时间都会平移。生产环境应显式设置 `timeZone`。

## Choosing a Controller

| 需求 | 选择 | 不要用 |
|---|---|---|
| 无状态副本 + 滚动发布 | Deployment | 裸 Pod / 手工 ReplicaSet |
| 每副本独立存储、稳定网络标识 | StatefulSet | Deployment + 共享 PVC |
| 每节点一个 agent | DaemonSet | 按节点数写死 replicas 的 Deployment |
| 一次性批处理 | Job | 带 restartPolicy: Never 的 Deployment |
| 定时批处理 | CronJob | 外部 crontab 调 kubectl |
| 需要自定义发布编排（金丝雀/蓝绿） | Deployment + Ingress/Gateway 权重，或 Argo Rollouts | 直接改 ReplicaSet |

## Links

- [Pod](/docs/CS/Container/k8s/Pod.md)
- [ReplicaSet Controller](/docs/CS/Container/k8s/ReplicaSetController.md)
- [Job Controller](/docs/CS/Container/k8s/jobController.md)
- [删除与级联](/docs/CS/Container/k8s/Deletion.md)
- [驱逐](/docs/CS/Container/k8s/Eviction.md)
- [Kubernetes](/docs/CS/Container/k8s/K8s.md)

## References

1. [Deployments](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
2. [StatefulSets](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
3. [DaemonSet](https://kubernetes.io/docs/concepts/workloads/controllers/daemonset/)
4. [Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/)
5. [CronJob](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/)
