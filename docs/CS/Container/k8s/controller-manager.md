## Introduction


Kubernetes 控制器管理器是一个守护进程，内嵌随 Kubernetes 一起发布的核心控制回路。 在机器人和自动化的应用中，控制回路是一个永不休止的循环，用于调节系统状态。 在 Kubernetes 中，每个控制器是一个控制回路，通过 API 服务器监视集群的共享状态， 并尝试进行更改以将当前状态转为期望状态。 目前，Kubernetes 自带的控制器例子包括副本控制器、节点控制器、命名空间控制器和服务账号控制器等


kube-controller-manager中运行了多个控制器 控制器通过Informer机制监听资源对象的Add、Update、Delete事件 并且通过Reconcile调谐机制更新资源对象的状态


```go
func Run(ctx context.Context, c *config.CompletedConfig) error {

logger := klog.FromContext(ctx)

stopCh := ctx.Done()

// Start events processing pipeline.

c.EventBroadcaster.StartStructuredLogging(0)

c.EventBroadcaster.StartRecordingToSink(&v1core.EventSinkImpl{Interface: c.Client.CoreV1().Events("")})

defer c.EventBroadcaster.Shutdown()

if cfgz, err := configz.New(ConfigzName); err == nil {

cfgz.Set(c.ComponentConfig)

} else {

logger.Error(err, "Unable to register configz")

}

// Setup any healthz checks we will want to use.

var checks []healthz.HealthChecker

var electionChecker *leaderelection.HealthzAdaptor

if c.ComponentConfig.Generic.LeaderElection.LeaderElect {

electionChecker = leaderelection.NewLeaderHealthzAdaptor(time.Second * 20)

checks = append(checks, electionChecker)

}

healthzHandler := controllerhealthz.NewMutableHealthzHandler(checks...)

  

// Start the controller manager HTTP server

// unsecuredMux is the handler for these controller *after* authn/authz filters have been applied

var unsecuredMux *mux.PathRecorderMux

if c.SecureServing != nil {

unsecuredMux = genericcontrollermanager.NewBaseHandler(&c.ComponentConfig.Generic.Debugging, healthzHandler)

slis.SLIMetricsWithReset{}.Install(unsecuredMux)

  

handler := genericcontrollermanager.BuildHandlerChain(unsecuredMux, &c.Authorization, &c.Authentication)

// TODO: handle stoppedCh and listenerStoppedCh returned by c.SecureServing.Serve

if _, _, err := c.SecureServing.Serve(handler, 0, stopCh); err != nil {

return err

}

}

  

clientBuilder, rootClientBuilder := createClientBuilders(c)

  

saTokenControllerDescriptor := newServiceAccountTokenControllerDescriptor(rootClientBuilder)

  

run := func(ctx context.Context, controllerDescriptors map[string]*ControllerDescriptor) {

controllerContext, err := CreateControllerContext(ctx, c, rootClientBuilder, clientBuilder)

if err != nil {

logger.Error(err, "Error building controller context")

klog.FlushAndExit(klog.ExitFlushTimeout, 1)

}

  

if err := StartControllers(ctx, controllerContext, controllerDescriptors, unsecuredMux, healthzHandler); err != nil {

logger.Error(err, "Error starting controllers")

klog.FlushAndExit(klog.ExitFlushTimeout, 1)

}

  

controllerContext.InformerFactory.Start(stopCh)

controllerContext.ObjectOrMetadataInformerFactory.Start(stopCh)

close(controllerContext.InformersStarted)

  

<-ctx.Done()

}

  

// No leader election, run directly

if !c.ComponentConfig.Generic.LeaderElection.LeaderElect {

controllerDescriptors := NewControllerDescriptors()

controllerDescriptors[names.ServiceAccountTokenController] = saTokenControllerDescriptor

run(ctx, controllerDescriptors)

return nil

}

  

id, err := os.Hostname()

if err != nil {

return err

}

  

// add a uniquifier so that two processes on the same host don't accidentally both become active

id = id + "_" + string(uuid.NewUUID())

  

// leaderMigrator will be non-nil if and only if Leader Migration is enabled.

var leaderMigrator *leadermigration.LeaderMigrator = nil

  

// If leader migration is enabled, create the LeaderMigrator and prepare for migration

if leadermigration.Enabled(&c.ComponentConfig.Generic) {

logger.Info("starting leader migration")

  

leaderMigrator = leadermigration.NewLeaderMigrator(&c.ComponentConfig.Generic.LeaderMigration,

"kube-controller-manager")

  

// startSATokenControllerInit is the original InitFunc.

startSATokenControllerInit := saTokenControllerDescriptor.GetInitFunc()

  

// Wrap saTokenControllerDescriptor to signal readiness for migration after starting

// the controller.

saTokenControllerDescriptor.initFunc = func(ctx context.Context, controllerContext ControllerContext, controllerName string) (controller.Interface, bool, error) {

defer close(leaderMigrator.MigrationReady)

return startSATokenControllerInit(ctx, controllerContext, controllerName)

}

}

  

if utilfeature.DefaultFeatureGate.Enabled(kubefeatures.CoordinatedLeaderElection) {

binaryVersion, err := semver.ParseTolerant(featuregate.DefaultComponentGlobalsRegistry.EffectiveVersionFor(featuregate.DefaultKubeComponent).BinaryVersion().String())

if err != nil {

return err

}

emulationVersion, err := semver.ParseTolerant(featuregate.DefaultComponentGlobalsRegistry.EffectiveVersionFor(featuregate.DefaultKubeComponent).EmulationVersion().String())

if err != nil {

return err

}

  

// Start lease candidate controller for coordinated leader election

leaseCandidate, waitForSync, err := leaderelection.NewCandidate(

c.Client,

"kube-system",

id,

"kube-controller-manager",

binaryVersion.FinalizeVersion(),

emulationVersion.FinalizeVersion(),

coordinationv1.OldestEmulationVersion,

)

if err != nil {

return err

}

healthzHandler.AddHealthChecker(healthz.NewInformerSyncHealthz(waitForSync))

  

go leaseCandidate.Run(ctx)

}

  

// Start the main lock

go leaderElectAndRun(ctx, c, id, electionChecker,

c.ComponentConfig.Generic.LeaderElection.ResourceLock,

c.ComponentConfig.Generic.LeaderElection.ResourceName,

leaderelection.LeaderCallbacks{

OnStartedLeading: func(ctx context.Context) {

controllerDescriptors := NewControllerDescriptors()

if leaderMigrator != nil {

// If leader migration is enabled, we should start only non-migrated controllers

// for the main lock.

controllerDescriptors = filteredControllerDescriptors(controllerDescriptors, leaderMigrator.FilterFunc, leadermigration.ControllerNonMigrated)

logger.Info("leader migration: starting main controllers.")

}

controllerDescriptors[names.ServiceAccountTokenController] = saTokenControllerDescriptor

run(ctx, controllerDescriptors)

},

OnStoppedLeading: func() {

logger.Error(nil, "leaderelection lost")

klog.FlushAndExit(klog.ExitFlushTimeout, 1)

},

})

  

// If Leader Migration is enabled, proceed to attempt the migration lock.

if leaderMigrator != nil {

// Wait for Service Account Token Controller to start before acquiring the migration lock.

// At this point, the main lock must have already been acquired, or the KCM process already exited.

// We wait for the main lock before acquiring the migration lock to prevent the situation

// where KCM instance A holds the main lock while KCM instance B holds the migration lock.

<-leaderMigrator.MigrationReady

  

// Start the migration lock.

go leaderElectAndRun(ctx, c, id, electionChecker,

c.ComponentConfig.Generic.LeaderMigration.ResourceLock,

c.ComponentConfig.Generic.LeaderMigration.LeaderName,

leaderelection.LeaderCallbacks{

OnStartedLeading: func(ctx context.Context) {

logger.Info("leader migration: starting migrated controllers.")

controllerDescriptors := NewControllerDescriptors()

controllerDescriptors = filteredControllerDescriptors(controllerDescriptors, leaderMigrator.FilterFunc, leadermigration.ControllerMigrated)

// DO NOT start saTokenController under migration lock

delete(controllerDescriptors, names.ServiceAccountTokenController)

run(ctx, controllerDescriptors)

},

OnStoppedLeading: func() {

logger.Error(nil, "migration leaderelection lost")

klog.FlushAndExit(klog.ExitFlushTimeout, 1)

},

})

}

  

<-stopCh

return nil

}
```

### leaderElectAndRun

```go
// leaderElectAndRun runs the leader election, and runs the callbacks once the leader lease is acquired.

// TODO: extract this function into staging/controller-manager

func leaderElectAndRun(ctx context.Context, c *config.CompletedConfig, lockIdentity string, electionChecker *leaderelection.HealthzAdaptor, resourceLock string, leaseName string, callbacks leaderelection.LeaderCallbacks) {

logger := klog.FromContext(ctx)

rl, err := resourcelock.NewFromKubeconfig(resourceLock,

c.ComponentConfig.Generic.LeaderElection.ResourceNamespace,

leaseName,

resourcelock.ResourceLockConfig{

Identity: lockIdentity,

EventRecorder: c.EventRecorder,

},

c.Kubeconfig,

c.ComponentConfig.Generic.LeaderElection.RenewDeadline.Duration)

if err != nil {

logger.Error(err, "Error creating lock")

klog.FlushAndExit(klog.ExitFlushTimeout, 1)

}

  

leaderelection.RunOrDie(ctx, leaderelection.LeaderElectionConfig{

Lock: rl,

LeaseDuration: c.ComponentConfig.Generic.LeaderElection.LeaseDuration.Duration,

RenewDeadline: c.ComponentConfig.Generic.LeaderElection.RenewDeadline.Duration,

RetryPeriod: c.ComponentConfig.Generic.LeaderElection.RetryPeriod.Duration,

Callbacks: callbacks,

WatchDog: electionChecker,

Name: leaseName,

Coordinated: utilfeature.DefaultFeatureGate.Enabled(kubefeatures.CoordinatedLeaderElection),

})

  

panic("unreachable")

}
```

## 

Controller Manager 在 cmd/kube-controller-manager/app/controllermanager.go 的 NewControllerInitializers 函数中初始化了所有的 Controller

## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)