## Introduction

Kubernetes 里有两套互不相干的"垃圾回收"，名字都叫 GC，但工作在不同的层面：

| | 回收对象 | 执行者 | 触发方式 |
|---|---|---|---|
| **运行时 GC** | 容器、镜像、sandbox、日志目录 | kubelet | 节点本地定时任务 |
| **对象 GC**（garbage collector controller） | etcd 里的 API 对象（级联删除） | kube-controller-manager | watch 事件驱动 |

本文讲第一套——kubelet 怎么把节点上"用完就该扔"的东西收走。第二套（对象级联删除）属于 apiserver 写路径的延伸，完整链路见 [删除与级联完整链路](/docs/CS/Container/k8s/Deletion.md)。

> [!NOTE]
> 本文全部结论基于 **Kubernetes v1.37.2**（release-1.37，commit `91c32c2b`）源码实读，所有片段均为 verbatim。

## The Big Picture

kubelet 启动时拉起两个定时任务（`pkg/kubelet/kubelet.go`）：

```go
// pkg/kubelet/kubelet.go
// ContainerGCPeriod is the period for performing container garbage collection.
ContainerGCPeriod = time.Minute
// ImageGCPeriod is the period for performing image garbage collection.
ImageGCPeriod = 5 * time.Minute
```

```go
func (kl *Kubelet) StartGarbageCollection(ctx context.Context) {
	logger := klog.FromContext(ctx)
	loggedContainerGCFailure := false
	go wait.UntilWithContext(ctx, func(ctx context.Context) {
		if err := kl.containerGC.GarbageCollect(ctx); err != nil {
			logger.Error(err, "Container garbage collection failed")
			kl.recorder.WithLogger(logger).Eventf(kl.nodeRefWithUID(), v1.EventTypeWarning, events.ContainerGCFailed, "%s", err.Error())
			loggedContainerGCFailure = true
		} else {
			var vLevel klog.Level = 4
			if loggedContainerGCFailure {
				vLevel = 1
				loggedContainerGCFailure = false
			}

			logger.V(int(vLevel)).Info("Container garbage collection succeeded")
		}
	}, ContainerGCPeriod)

	// when the high threshold is set to 100, and the max age is 0 (or the max age feature is disabled)
	// stub the image GC manager
	if kl.kubeletConfiguration.ImageGCHighThresholdPercent == 100 && kl.kubeletConfiguration.ImageMaximumGCAge.Duration == 0 {
		logger.V(2).Info("ImageGCHighThresholdPercent is set 100 and ImageMaximumGCAge is 0, Disable image GC")
		return
	}

	prevImageGCFailed := false
	beganGC := time.Now()
	go wait.UntilWithContext(ctx, func(ctx context.Context) {
		if err := kl.imageManager.GarbageCollect(ctx, beganGC); err != nil {
			if prevImageGCFailed {
				logger.Error(err, "Image garbage collection failed multiple times in a row")
				// Only create an event for repeated failures
				kl.recorder.WithLogger(logger).Event(kl.nodeRefWithUID(), v1.EventTypeWarning, events.ImageGCFailed, err.Error())
			} else {
				logger.Error(err, "Image garbage collection failed once. Stats initialization may not have completed yet")
			}
			prevImageGCFailed = true
		} else {
			// ...
		}
	}, ImageGCPeriod)
}
```

几个细节值得注意：

- **Container GC 每 1 分钟、Image GC 每 5 分钟**。容器 GC 更频繁，因为死容器数量随 Pod churn 线性增长；镜像体积大但数量有限，且检测（`detectImages` 要遍历全部容器算引用）成本高。
- **镜像 GC 有一个"整体停用"开关**：`ImageGCHighThresholdPercent=100 && ImageMaximumGCAge=0` 时直接 return，不启动 image GC goroutine。语义是"磁盘满了也不动我的镜像"。
- **失败告警只报一次**：`prevImageGCFailed` 保证只有连续失败才发 Event，避免 GC 每轮失败刷屏。
- `beganGC := time.Now()` 记录 kubelet 启动时刻，后面 `freeOldImages` 要用它实现 `ImageMaximumGCAge` 的"冷却期"（见下文）。

## Container GC

### GarbageCollect: Three Eviction Steps

container GC 的入口（`pkg/kubelet/kuberuntime/kuberuntime_gc.go`）：

```go
// GarbageCollect removes dead containers using the specified container gc policy.
// Note that gc policy is not applied to sandboxes. Sandboxes are only removed when they are
// not ready and containing no containers.
//
// GarbageCollect consists of the following steps:
// * gets evictable containers which are not active and created more than gcPolicy.MinAge ago.
// * removes oldest dead containers for each pod by enforcing gcPolicy.MaxPerPodContainer.
// * removes oldest dead containers by enforcing gcPolicy.MaxContainers.
// * gets evictable sandboxes which are not ready and contains no containers.
// * removes evictable sandboxes.
func (cgc *containerGC) GarbageCollect(ctx context.Context, gcPolicy kubecontainer.GCPolicy, allSourcesReady bool, evictNonDeletedPods bool) error {
```

三条淘汰规则按顺序执行：

1. **先清掉"Pod 已不存在"的容器**——`allSourcesReady` 时，凡是 kubelet 已确认源里没有这个 Pod 的，其容器全部删除。这一步是主清理路径。
2. **再按每容器保留数裁剪**——`MaxPerPodContainer` 限制同一个 container name 保留几个死实例。
3. **最后按全局总量裁剪**——`MaxContainers` 超限时先均摊（每个 evict unit 至少留 1 个），仍不够就把所有死容器按创建时间排序删最老的。

第二步与第三步的实现：

```go
// pkg/kubelet/kuberuntime/kuberuntime_gc.go
func (cgc *containerGC) evictContainers(ctx context.Context, gcPolicy kubecontainer.GCPolicy, allSourcesReady bool, evictNonDeletedPods bool) error {
	// Separate containers by evict units.
	evictUnits, err := cgc.evictableContainers(ctx, gcPolicy.MinAge)
	if err != nil {
		return err
	}

	// Remove deleted pod containers if all sources are ready.
	if allSourcesReady {
		for key, unit := range evictUnits {
			if cgc.podStateProvider.IsPodDeleted(key.uid) || (cgc.podStateProvider.IsPodTerminated(key.uid) && evictNonDeletedPods) {
				cgc.removeOldestN(unit, len(unit)) // Remove all.
				delete(evictUnits, key)
			}
		}
	}

	// Enforce max containers per evict unit.
	if gcPolicy.MaxPerPodContainer >= 0 {
		cgc.enforceMaxContainersPerEvictUnit(ctx, evictUnits, gcPolicy.MaxPerPodContainer)
	}

	// Enforce max total number of containers.
	if gcPolicy.MaxContainers >= 0 && evictUnits.NumContainers() > gcPolicy.MaxContainers {
		// Leave an equal number of containers per evict unit (min: 1).
		numContainersPerEvictUnit := gcPolicy.MaxContainers / evictUnits.NumEvictUnits()
		if numContainersPerEvictUnit < 1 {
			numContainersPerEvictUnit = 1
		}
		cgc.enforceMaxContainersPerEvictUnit(ctx, evictUnits, numContainersPerEvictUnit)

		// If we still need to evict, evict oldest first.
		numContainers := evictUnits.NumContainers()
		if numContainers > gcPolicy.MaxContainers {
			flattened := make([]containerGCInfo, 0, numContainers)
			for key := range evictUnits {
				flattened = append(flattened, evictUnits[key]...)
			}
			sort.Sort(byCreated(flattened))

			cgc.removeOldestN(flattened, numContainers-gcPolicy.MaxContainers)
		}
	}
	return nil
}
```

### evictableContainers: Who Is Eligible

候选集合的判定（同一文件）：

```go
func (cgc *containerGC) evictableContainers(ctx context.Context, minAge time.Duration) (containersByEvictUnit, error) {
	containers, err := cgc.manager.getContainers(ctx, listOptions{})
	if err != nil {
		return containersByEvictUnit{}, err
	}

	evictUnits := make(containersByEvictUnit)
	newestGCTime := time.Now().Add(-minAge)
	for _, container := range containers {
		// Prune out running containers.
		if container.State == runtimeapi.ContainerState_CONTAINER_RUNNING {
			continue
		}

		createdAt := time.Unix(0, container.CreatedAt)
		if newestGCTime.Before(createdAt) {
			continue
		}

		labeledInfo := getContainerInfoFromLabels(ctx, container.Labels)
		containerInfo := containerGCInfo{
			id:         container.Id,
			name:       container.Metadata.Name,
			createTime: createdAt,
			unknown:    container.State == runtimeapi.ContainerState_CONTAINER_UNKNOWN,
		}
		key := evictUnit{
			uid:  labeledInfo.PodUID,
			name: containerInfo.name,
		}
		evictUnits[key] = append(evictUnits[key], containerInfo)
	}

	return evictUnits, nil
}
```

两个判定标准：**非 running**（Exited 与 UNKNOWN 状态都算候选）+ **年龄超过 `MinAge`**。注意 `CONTAINER_UNKNOWN` 也会被收走——这是给"runtime 崩溃后状态不明"的容器留的兜底。

evict unit 的 key 是 `PodUID + containerName`，而不是 container ID——同一 Pod 里同名容器的前 N 代实例构成一个保留队列。

### GC Policy Defaults

策略来自 kubelet 启动参数（`pkg/kubelet/kubelet.go` 装配）：

```go
containerGCPolicy := kubecontainer.GCPolicy{
    MinAge:             minimumGCAge.Duration,
    MaxPerPodContainer: int(maxPerPodContainerCount),
    MaxContainers:      int(maxContainerCount),
}
```

flags 默认值（`cmd/kubelet/app/options/options.go`）：

| 参数 | 默认 | 含义 |
|---|---|---|
| `--minimum-gc-age` | `0` | 死容器最小年龄，0 表示随时可收 |
| `--max-per-pod-container-count` | `1` | 每个容器名保留 1 个死实例 |
| `--max-container-count` | `-1` | **负数 = 不设全局上限** |

注意 `MaxContainers >= 0` 才会启用全局裁剪，所以默认配置下**全局总量没有上限**，只受"每容器保留 1 个死实例"约束。

### evictSandboxes and evictPodLogsDirectories

`GarbageCollect` 还有两步收尾：

- **evictSandboxes**——sandbox 不受上面策略约束，规则独立：只有"not ready 且不含任何容器"的 sandbox 才删。因为 sandbox 是 Pod 网络命名空间的宿主，只要 Pod 里还有容器在跑，sandbox 就不能动。
- **evictPodLogsDirectories**——`allSourcesReady` 时删除已消失 Pod 的日志目录；被 runtime 标记过期的容器日志目录也一并清理。

## Image GC

### Two Independent Reasons to Collect

v1.37 的 image GC 有**两条互相独立的回收理由**，这也是它相对旧版最大的结构变化（旧版只有一个 `freeSpace`）：

| 理由 | 触发条件 | 指标 reason |
|---|---|---|
| **space** | 磁盘使用率超过 `HighThresholdPercent` | `ImageGarbageCollectedTotalReasonSpace` |
| **age** | 镜像 lastUsed 超过 `ImageMaximumGCAge` | `ImageGarbageCollectedTotalReasonAge` |

```go
// pkg/kubelet/images/image_gc_manager.go
// ImageGarbageCollectedTotalReason* specify the reason why an image was garbage collected
ImageGarbageCollectedTotalReasonAge   = "age"
ImageGarbageCollectedTotalReasonSpace = "space"
```

`ImageMaximumGCAge` 是磁盘压力之外的第二条路径：即使磁盘很空，镜像只要"太久没用"也会被收走。它在 1.29 引入、1.30 Beta、**1.35 GA 且 LockToDefault**（`pkg/features/kube_features.go`），配置校验要求 `imageMaximumGCAge > imageMinimumGCAge`。

### GarbageCollect: The Main Loop

```go
// pkg/kubelet/images/image_gc_manager.go
func (im *realImageGCManager) GarbageCollect(ctx context.Context, beganGC time.Time) error {
	ctx, otelSpan := im.tracer.Start(ctx, "Images/GarbageCollect")
	logger := klog.FromContext(ctx)
	defer otelSpan.End()

	freeTime := time.Now()
	images, err := im.imagesInEvictionOrder(ctx, freeTime)
	if err != nil {
		return err
	}

	images, err = im.freeOldImages(ctx, images, freeTime, beganGC)
	if err != nil {
		return err
	}

	// Get disk usage on disk holding images.
	fsStats, _, err := im.statsProvider.ImageFsStats(ctx)
	if err != nil {
		return err
	}

	// ... capacity/available normalization ...

	// If over the max threshold, free enough to place us at the lower threshold.
	usagePercent := 100 - int(available*100/capacity)
	if usagePercent >= im.policy.HighThresholdPercent {
		amountToFree := capacity*int64(100-im.policy.LowThresholdPercent)/100 - available
		logger.Info("Disk usage on image filesystem is over the high threshold, trying to free bytes down to the low threshold", "usage", usagePercent, "highThreshold", im.policy.HighThresholdPercent, "amountToFree", amountToFree, "lowThreshold", im.policy.LowThresholdPercent)
		remainingImages, freed, err := im.freeSpace(ctx, amountToFree, freeTime, images)
		if err != nil {
			// Failed to delete images, eg due to a read-only filesystem.
			return err
		}

		im.runPostGCHooks(ctx, remainingImages, freeTime)

		if freed < amountToFree {
			// This usually means the disk is full for reasons other than container
			// images, such as logs, volumes, or other files. ...
```

值得注意的设计点：

- **水位控制而非定量清理**——超过高水位（默认 **85%**）后，不是"删一点"，而是**一次清到低水位（默认 **80%**）以下**：`amountToFree = capacity × (100 - Low%) / 100 - available`。默认值来自 `pkg/kubelet/apis/config/v1beta1/defaults.go`（注释原话：default is below docker's default dm.min_free_space of 90%）。
- **回收分两阶段**：先 `imagesInEvictionOrder`（找出候选 + 排序），再 `freeOldImages`（按 age 理由清），最后磁盘超水位才 `freeSpace`（按 space 理由清）。

### imagesInEvictionOrder: Candidates and Ordering

```go
func (im *realImageGCManager) imagesInEvictionOrder(ctx context.Context, freeTime time.Time) ([]evictionInfo, error) {
	isRuntimeClassInImageCriAPIEnabled := utilfeature.DefaultFeatureGate.Enabled(features.RuntimeClassInImageCriAPI)
	imagesInUse, err := im.detectImages(ctx, freeTime)
	if err != nil {
		return nil, err
	}

	im.imageRecordsLock.Lock()
	defer im.imageRecordsLock.Unlock()
	logger := klog.FromContext(ctx)

	// Get all images in eviction order.
	images := make([]evictionInfo, 0, len(im.imageRecords))
	for image, record := range im.imageRecords {
		if isImageUsed(image, imagesInUse) {
			logger.V(5).Info("Image ID is being used", "imageID", image)
			continue
		}
		// Check if image is pinned, prevent garbage collection
		if record.pinned {
			logger.V(5).Info("Image is pinned, skipping garbage collection", "imageID", image)
			continue

		}
		// ...
	}
	sort.Sort(byLastUsedAndDetected(images))
	return images, nil
}
```

三类镜像被排除出候选：

1. **正在被容器使用**——`detectImages` 遍历所有容器算出 in-use 集合，在用的镜像 `lastUsed` 被刷新为当前时刻。
2. **被 runtime 标记 pinned**——`record.pinned` 来自 CRI 返回的 `image.Pinned` 字段，runtime 可以声明"这个镜像别动"（例如节点关键镜像）。
3. 剩下的按 `byLastUsedAndDetected` 排序——**最近使用的排最后，从最久没用的开始删**（LRU）。

### freeOldImages: Age-Based Collection

```go
func (im *realImageGCManager) freeOldImages(ctx context.Context, images []evictionInfo, freeTime, beganGC time.Time) ([]evictionInfo, error) {
	if im.policy.MaxAge == 0 {
		return images, nil
	}

	// Wait until the MaxAge has passed since the Kubelet has started,
	// or else we risk prematurely garbage collecting images.
	if freeTime.Sub(beganGC) <= im.policy.MaxAge {
		return images, nil
	}
	var deletionErrors []error
	logger := klog.FromContext(ctx)
	remainingImages := make([]evictionInfo, 0)
	for _, image := range images {
		logger.V(5).Info("Evaluating image ID for possible garbage collection based on image age", "imageID", image.id)
		// Evaluate whether image is older than MaxAge.
		if freeTime.Sub(image.lastUsed) > im.policy.MaxAge {
			if err := im.freeImage(ctx, image, ImageGarbageCollectedTotalReasonAge); err != nil {
				deletionErrors = append(deletionErrors, err)
				remainingImages = append(remainingImages, image)
				continue
			}
			continue
		}
		remainingImages = append(remainingImages, image)
	}
	// ...
}
```

注意 `beganGC` 的作用：kubelet 启动后 `MaxAge` 时间窗内**不做 age 回收**——因为启动初期 `detectImages` 的 lastUsed 数据还没建立起来，贸然按时间删会误伤刚拉取还没跑的镜像。

### freeSpace: Space-Based Collection

```go
func (im *realImageGCManager) freeSpace(ctx context.Context, bytesToFree int64, freeTime time.Time, images []evictionInfo) ([]string, int64, error) {
	// Delete unused images until we've freed up enough space.
	var deletionErrors []error
	logger := klog.FromContext(ctx)
	spaceFreed := int64(0)
	var imagesLeft []string
	for _, image := range images {
		logger.V(5).Info("Evaluating image ID for possible garbage collection based on disk usage", "imageID", image.id, "runtimeHandlerUsedToPullImage", image.runtimeHandlerUsedToPullImage)
		// Images that are currently in used were given a newer lastUsed.
		if image.lastUsed.Equal(freeTime) || image.lastUsed.After(freeTime) {
			imagesLeft = append(imagesLeft, image.id)
			logger.V(5).Info("Image ID was used too recently, not eligible for garbage collection", "imageID", image.id, "lastUsed", image.lastUsed, "freeTime", freeTime)
			continue
		}

		// Avoid garbage collect the image if the image is not old enough.
		// In such a case, the image may have just been pulled down, and will be used by a container right away.
		if freeTime.Sub(image.firstDetected) < im.policy.MinAge {
			imagesLeft = append(imagesLeft, image.id)
			logger.V(5).Info("Image ID's age is less than the policy's minAge, not eligible for garbage collection", "imageID", image.id, "age", freeTime.Sub(image.firstDetected), "minAge", im.policy.MinAge)
			continue
		}

		if err := im.freeImage(ctx, image, ImageGarbageCollectedTotalReasonSpace); err != nil {
			deletionErrors = append(deletionErrors, err)
			imagesLeft = append(imagesLeft, image.id)
			continue
		}
		spaceFreed += image.size

		if spaceFreed >= bytesToFree {
			break
		}
	}
	// ...
}
```

`MinAge`（默认 **2 分钟**，`ImageMinimumGCAge`）在这里生效：镜像从"第一次被检测到"算起不满 2 分钟不删。源码注释写明了动机——镜像可能刚拉下来马上就要被容器用，不能拉完就收。

### Thresholds vs Absolutes: Why Percentages

image GC 用**百分比水位**而不是绝对字节数做触发条件，这是刻意的：

1. **节点磁盘大小差异极大**——8GB 的边缘节点和 2TB 的 GPU 节点不可能共用一个绝对阈值，百分比天然归一化。
2. **水位语义对用户直观**——"磁盘用到 85% 才开始清、清到 80% 停"比"保留 10GB 空闲"更容易推理，且与 `dm.min_free_space`（90%）等下层工具的语义兼容（默认高水位 85% < 90%，保证 image GC 先于容器存储驱动报错动手）。
3. **清到低水位而非刚好回到高水位之下**——一次多清一些，避免"清 1GB 又超了再清 1GB"的抖动，每次 GC 都要付 `detectImages` 遍历全部容器的成本。

另一个值得注意的取舍：**GC 失败不影响 Pod 运行**。`freed < amountToFree` 时只发 `FreeDiskSpaceFailed` Event 返回错误——真正会因为磁盘满而杀 Pod 的是 [驱逐](/docs/CS/Container/k8s/Eviction.md)（imagefs 水位触发 node-pressure eviction）。image GC 是"预防"，驱逐是"抢救"，两者看同一个 `ImageFsStats` 但职责不同。

## Links

- [Kubernetes](/docs/CS/Container/k8s/K8s.md)
- [删除与级联完整链路](/docs/CS/Container/k8s/Deletion.md)
- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [controller-manager](/docs/CS/Container/k8s/controller-manager.md)
- [驱逐](/docs/CS/Container/k8s/Eviction.md)

## References

1. [Kubernetes v1.37.2 source](https://github.com/kubernetes/kubernetes/tree/v1.37.2)
2. [Garbage Collection](https://kubernetes.io/docs/concepts/architecture/garbage-collection/)
3. [Resource Management for Pods and Containers](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
4. [KEP-4210: ImageMaximumGCAge in Kubelet](https://github.com/kubernetes/enhancements/tree/master/keps/sig-node/4210-max-image-gc-age)
