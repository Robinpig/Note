## Introduction



入口函数在 cmd/kube-proxy/proxy.go

```c
func main() {
    command := app.NewProxyCommand()
    code := cli.Run(command)
    os.Exit(code)
}
```

执行 opts.Run()

```c
// NewProxyCommand creates a *cobra.Command object with default parameters
func NewProxyCommand() *cobra.Command {
    opts := NewOptions()

    cmd := &cobra.Command{
        Use: "kube-proxy",
        Long: `The Kubernetes network proxy runs on each node. This
reflects services as defined in the Kubernetes API on each node and can do simple
TCP, UDP, and SCTP stream forwarding or round robin TCP, UDP, and SCTP forwarding across a set of backends.
Service cluster IPs and ports are currently found through Docker-links-compatible
environment variables specifying ports opened by the service proxy. There is an optional
addon that provides cluster DNS for these cluster IPs. The user must create a service
with the apiserver API to configure the proxy.`,
        RunE: func(cmd *cobra.Command, args []string) error {
            verflag.PrintAndExitIfRequested()

            if err := initForOS(opts.config.Windows.RunAsService); err != nil {
                return fmt.Errorf("failed os init: %w", err)
            }

            if err := opts.Complete(cmd.Flags()); err != nil {
                return fmt.Errorf("failed complete: %w", err)
            }

            logs.InitLogs()
            if err := logsapi.ValidateAndApplyAsField(&opts.config.Logging, utilfeature.DefaultFeatureGate, field.NewPath("logging")); err != nil {
                return fmt.Errorf("initialize logging: %w", err)
            }

            cliflag.PrintFlags(cmd.Flags())

            if err := opts.Validate(); err != nil {
                return fmt.Errorf("failed validate: %w", err)
            }
            // add feature enablement metrics
            utilfeature.DefaultMutableFeatureGate.AddMetrics()
            if err := opts.Run(context.Background()); err != nil {
                opts.logger.Error(err, "Error running ProxyServer")
                return err
            }

            return nil
        },
        Args: func(cmd *cobra.Command, args []string) error {
            for _, arg := range args {
                if len(arg) > 0 {
                    return fmt.Errorf("%q does not take any arguments, got %q", cmd.CommandPath(), args)
                }
            }
            return nil
        },
    }

    fs := cmd.Flags()
    opts.AddFlags(fs)
    fs.AddGoFlagSet(goflag.CommandLine) // for --boot-id-file and --machine-id-file

    _ = cmd.MarkFlagFilename("config", "yaml", "yml", "json")

    return cmd
}
```

opts.Run() 是启动 kube-proxy 的入口，跟随 NewOptions() 构造函数，我们看到它返回的是 Options 结构体。
Options 实现了 Run 接口

```c
// Run runs the specified ProxyServer.
func (o *Options) Run(ctx context.Context) error {
    defer close(o.errCh)
    if len(o.WriteConfigTo) > 0 {
        return o.writeConfigFile()
    }

    err := platformCleanup(ctx, o.config.Mode, o.CleanupAndExit)
    if o.CleanupAndExit {
        return err
    }
    // We ignore err otherwise; the cleanup is best-effort, and the backends will have
    // logged messages if they failed in interesting ways.

    proxyServer, err := newProxyServer(ctx, o.config, o.master, o.InitAndExit)
    if err != nil {
        return err
    }
    if o.InitAndExit {
        return nil
    }

    o.proxyServer = proxyServer
    return o.runLoop(ctx)
}
```


```c
func (o *Options) runLoop(ctx context.Context) error {
    if o.watcher != nil {
        o.watcher.Run()
    }

    // run the proxy in goroutine
    go func() {
        err := o.proxyServer.Run(ctx)
        o.errCh <- err
    }()

    for {
        err := <-o.errCh
        if err != nil {
            return err
        }
    }
}
```

通过 client-go 从 apiserver 获取 services 和 endpoints/endpointSlice 配置

创建相应的 informer 并注册事件函数

```c
func (s *ProxyServer) Run(ctx context.Context) error {
    logger := klog.FromContext(ctx)
    // To help debugging, immediately log version
    logger.Info("Version info", "version", version.Get())

    logger.Info("Golang settings", "GOGC", os.Getenv("GOGC"), "GOMAXPROCS", os.Getenv("GOMAXPROCS"), "GOTRACEBACK", os.Getenv("GOTRACEBACK"))

    proxymetrics.RegisterMetrics(s.Config.Mode)

    // TODO(vmarmol): Use container config for this.
    var oomAdjuster *oom.OOMAdjuster
    if s.Config.Linux.OOMScoreAdj != nil {
        oomAdjuster = oom.NewOOMAdjuster()
        if err := oomAdjuster.ApplyOOMScoreAdj(0, int(*s.Config.Linux.OOMScoreAdj)); err != nil {
            logger.V(2).Info("Failed to apply OOMScore", "err", err)
        }
    }

    if s.Broadcaster != nil {
        stopCh := make(chan struct{})
        s.Broadcaster.StartRecordingToSink(stopCh)
    }

    // TODO(thockin): make it possible for healthz and metrics to be on the same port.

    var healthzErrCh, metricsErrCh chan error
    if s.Config.BindAddressHardFail {
        healthzErrCh = make(chan error)
        metricsErrCh = make(chan error)
    }

    // Start up a healthz server if requested
    serveHealthz(ctx, s.HealthzServer, healthzErrCh)

    // Start up a metrics server if requested
    serveMetrics(s.Config.MetricsBindAddress, s.Config.Mode, s.Config.EnableProfiling, metricsErrCh)

    noProxyName, err := labels.NewRequirement(apis.LabelServiceProxyName, selection.DoesNotExist, nil)
    if err != nil {
        return err
    }

    noHeadlessEndpoints, err := labels.NewRequirement(v1.IsHeadlessService, selection.DoesNotExist, nil)
    if err != nil {
        return err
    }

    labelSelector := labels.NewSelector()
    labelSelector = labelSelector.Add(*noProxyName, *noHeadlessEndpoints)

    // Make informers that filter out objects that want a non-default service proxy.
    informerFactory := informers.NewSharedInformerFactoryWithOptions(s.Client, s.Config.ConfigSyncPeriod.Duration,
        informers.WithTweakListOptions(func(options *metav1.ListOptions) {
            options.LabelSelector = labelSelector.String()
        }))

    // Create configs (i.e. Watches for Services, EndpointSlices and ServiceCIDRs)
    // Note: RegisterHandler() calls need to happen before creation of Sources because sources
    // only notify on changes, and the initial update (on process start) may be lost if no handlers
    // are registered yet.
    serviceConfig := config.NewServiceConfig(ctx, informerFactory.Core().V1().Services(), s.Config.ConfigSyncPeriod.Duration)
    serviceConfig.RegisterEventHandler(s.Proxier)
    go serviceConfig.Run(ctx.Done())

    endpointSliceConfig := config.NewEndpointSliceConfig(ctx, informerFactory.Discovery().V1().EndpointSlices(), s.Config.ConfigSyncPeriod.Duration)
    endpointSliceConfig.RegisterEventHandler(s.Proxier)
    go endpointSliceConfig.Run(ctx.Done())

    if utilfeature.DefaultFeatureGate.Enabled(features.MultiCIDRServiceAllocator) {
        serviceCIDRConfig := config.NewServiceCIDRConfig(ctx, informerFactory.Networking().V1beta1().ServiceCIDRs(), s.Config.ConfigSyncPeriod.Duration)
        serviceCIDRConfig.RegisterEventHandler(s.Proxier)
        go serviceCIDRConfig.Run(wait.NeverStop)
    }
    // This has to start after the calls to NewServiceConfig because that
    // function must configure its shared informer event handlers first.
    informerFactory.Start(wait.NeverStop)

    // Make an informer that selects for our nodename.
    currentNodeInformerFactory := informers.NewSharedInformerFactoryWithOptions(s.Client, s.Config.ConfigSyncPeriod.Duration,
        informers.WithTweakListOptions(func(options *metav1.ListOptions) {
            options.FieldSelector = fields.OneTermEqualSelector("metadata.name", s.NodeRef.Name).String()
        }))
    nodeConfig := config.NewNodeConfig(ctx, currentNodeInformerFactory.Core().V1().Nodes(), s.Config.ConfigSyncPeriod.Duration)
    // https://issues.k8s.io/111321
    if s.Config.DetectLocalMode == kubeproxyconfig.LocalModeNodeCIDR {
        nodeConfig.RegisterEventHandler(proxy.NewNodePodCIDRHandler(ctx, s.podCIDRs))
    }
    if utilfeature.DefaultFeatureGate.Enabled(features.KubeProxyDrainingTerminatingNodes) {
        nodeConfig.RegisterEventHandler(&proxy.NodeEligibleHandler{
            HealthServer: s.HealthzServer,
        })
    }
    nodeConfig.RegisterEventHandler(s.Proxier)

    go nodeConfig.Run(wait.NeverStop)

    // This has to start after the calls to NewNodeConfig because that must
    // configure the shared informer event handler first.
    currentNodeInformerFactory.Start(wait.NeverStop)

    // Birth Cry after the birth is successful
    s.birthCry()

    go s.Proxier.SyncLoop()

    select {
    case err = <-healthzErrCh:
        s.Recorder.Eventf(s.NodeRef, nil, api.EventTypeWarning, "FailedToStartProxierHealthcheck", "StartKubeProxy", err.Error())
    case err = <-metricsErrCh:
        s.Recorder.Eventf(s.NodeRef, nil, api.EventTypeWarning, "FailedToStartMetricServer", "StartKubeProxy", err.Error())
    }
    return err
}
```


```c
// SyncLoop runs periodic work.  This is expected to run as a
// goroutine or as the main loop of the app.  It does not return.
func (proxier *metaProxier) SyncLoop() {
    go proxier.ipv6Proxier.SyncLoop() // Use go-routine here!
    proxier.ipv4Proxier.SyncLoop()    // never returns
}
```


## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)

