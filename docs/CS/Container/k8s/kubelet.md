## Introduction





`pkg/kubelet/kubelet.go`

```go
func (kl *Kubelet) Run(updates <-chan kubetypes.PodUpdate) {
	if kl.logServer == nil {
		kl.logServer = http.StripPrefix("/logs/", http.FileServer(http.Dir("/var/log/")))
	}
	if kl.kubeClient == nil {
		glog.Warning("No api server defined - no node status update will be sent.")
	}

	if err := kl.initializeModules(); err != nil {
		kl.recorder.Eventf(kl.nodeRef, v1.EventTypeWarning, events.KubeletSetupFailed, err.Error())
		glog.Fatal(err)
	}

	// Start volume manager
	go kl.volumeManager.Run(kl.sourcesReady, wait.NeverStop)

	if kl.kubeClient != nil {
		// Start syncing node status immediately, this may set up things the runtime needs to run.
		go wait.Until(kl.syncNodeStatus, kl.nodeStatusUpdateFrequency, wait.NeverStop)
	}
	go wait.Until(kl.syncNetworkStatus, 30*time.Second, wait.NeverStop)
	go wait.Until(kl.updateRuntimeUp, 5*time.Second, wait.NeverStop)

	// Start loop to sync iptables util rules
	if kl.makeIPTablesUtilChains {
		go wait.Until(kl.syncNetworkUtil, 1*time.Minute, wait.NeverStop)
	}

	// Start a goroutine responsible for killing pods (that are not properly
	// handled by pod workers).
	go wait.Until(kl.podKiller, 1*time.Second, wait.NeverStop)

	// Start gorouting responsible for checking limits in resolv.conf
	if kl.dnsConfigurer.ResolverConfig != "" {
		go wait.Until(func() { kl.dnsConfigurer.CheckLimitsForResolvConf() }, 30*time.Second, wait.NeverStop)
	}

	// Start component sync loops.
	kl.statusManager.Start()
	kl.probeManager.Start()

	// Start the pod lifecycle event generator.
	kl.pleg.Start()
	kl.syncLoop(updates, kl)
}
```





initializeModules will initialize internal modules that do not require the container runtime to be up.
Note that the modules here must not depend on modules that are not initialized here.

initializeModules方法主要做了以下几件事：

1. 创建创建文件目录、Container的log目录；
2. 启动 imageManager，这个管理器实际上是realImageGCManager，我们待会看；
3. 启动 certificate manager ，证书相关；
4. 启动 oomWatcher监视器；
5. 启动 resource analyzer,定时刷新volume stats到缓存中

```go
func (kl *Kubelet) initializeModules() error {
	// Prometheus metrics.
	metrics.Register(kl.runtimeCache, collectors.NewVolumeStatsCollector(kl))

	// Setup filesystem directories.
	if err := kl.setupDataDirs(); err != nil {
		return err
	}

	// If the container logs directory does not exist, create it.
	if _, err := os.Stat(ContainerLogsDir); err != nil {
		if err := kl.os.MkdirAll(ContainerLogsDir, 0755); err != nil {
			glog.Errorf("Failed to create directory %q: %v", ContainerLogsDir, err)
		}
	}

	// Start the image manager.
	kl.imageManager.Start()

	// Start the certificate manager.
	if utilfeature.DefaultFeatureGate.Enabled(features.RotateKubeletServerCertificate) {
		kl.serverCertificateManager.Start()
	}

	// Start container manager.
	node, err := kl.getNodeAnyWay()
	if err != nil {
		return fmt.Errorf("Kubelet failed to get node info: %v", err)
	}

	if err := kl.containerManager.Start(node, kl.GetActivePods, kl.sourcesReady, kl.statusManager, kl.runtimeService); err != nil {
		return fmt.Errorf("Failed to start ContainerManager %v", err)
	}

	// Start out of memory watcher.
	if err := kl.oomWatcher.Start(kl.nodeRef); err != nil {
		return fmt.Errorf("Failed to start OOM watcher %v", err)
	}

	// Initialize GPUs
	if err := kl.gpuManager.Start(); err != nil {
		glog.Errorf("Failed to start gpuManager %v", err)
	}

	// Start resource analyzer
	kl.resourceAnalyzer.Start()

	return nil
}
```



`pkg/kubelet/images/image_gc_manager.go`

realImageGCManager的start方法会启动两个协程，然后分别定时调用detectImages方法与imageCache的set方法。detectImages方法里面主要就是调用ImageService和RuntimeService的方法找出所有正在使用的image，然后删除不再使用的image。

这里ListImages和detectImages里面用到的GetPods方法都是调用了CRI的方法

```go

func (im *realImageGCManager) Start() {
	go wait.Until(func() {
		// Initial detection make detected time "unknown" in the past.
		var ts time.Time
		if im.initialized {
			ts = time.Now()
		}
		err := im.detectImages(ts)
		if err != nil {
			glog.Warningf("[imageGCManager] Failed to monitor images: %v", err)
		} else {
			im.initialized = true
		}
	}, 5*time.Minute, wait.NeverStop)

	// Start a goroutine periodically updates image cache.
	// TODO(random-liu): Merge this with the previous loop.
	go wait.Until(func() {
		images, err := im.runtime.ListImages()
		if err != nil {
			glog.Warningf("[imageGCManager] Failed to update image list: %v", err)
		} else {
			im.imageCache.set(images)
		}
	}, 30*time.Second, wait.NeverStop)

}
```







## syncLoop

syncLoop is the main loop for processing changes. It watches for changes from three channels (file, apiserver, and http) and creates a union of them. 
For any new change seen, will run a sync against desired state and running state. 
If no changes are seen to the configuration, will synchronize the last known desired state every sync-frequency seconds. Never returns.

```go
func (kl *Kubelet) syncLoop(updates <-chan kubetypes.PodUpdate, handler SyncHandler) {
	glog.Info("Starting kubelet main sync loop.")
	// The resyncTicker wakes up kubelet to checks if there are any pod workers
	// that need to be sync'd. A one-second period is sufficient because the
	// sync interval is defaulted to 10s.
	syncTicker := time.NewTicker(time.Second)
	defer syncTicker.Stop()
	housekeepingTicker := time.NewTicker(housekeepingPeriod)
	defer housekeepingTicker.Stop()
	plegCh := kl.pleg.Watch()
	const (
		base   = 100 * time.Millisecond
		max    = 5 * time.Second
		factor = 2
	)
	duration := base
	for {
		if rs := kl.runtimeState.runtimeErrors(); len(rs) != 0 {
			glog.Infof("skipping pod synchronization - %v", rs)
			// exponential backoff
			time.Sleep(duration)
			duration = time.Duration(math.Min(float64(max), factor*float64(duration)))
			continue
		}
		// reset backoff if we have a success
		duration = base

		kl.syncLoopMonitor.Store(kl.clock.Now())
		if !kl.syncLoopIteration(updates, handler, syncTicker.C, housekeepingTicker.C, plegCh) {
			break
		}
		kl.syncLoopMonitor.Store(kl.clock.Now())
	}
}
```






## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)





## References

1. [11.深入k8s：kubelet工作原理及其初始化源码分析 ](https://www.cnblogs.com/luozhiyun/p/13699435.html)