# webflux



## Start Server

[AbstractApplicationContext#refresh()](/docs/CS/Java/Spring/IoC.md?id=abstractapplicationcontextrefresh)-> finishRefresh -> LifecycleProcessor#onRefresh() -> DefaultLifecycleProcessor#startBeans() -> DefaultLifecycleProcessor#doStart()
-> WebServerStartStopLifecycle#start() -> NettyWebServer#start()

```java
// NettyWebServer#start()
@Override
public void start() throws WebServerException {
    if (this.disposableServer == null) {
        try {
            this.disposableServer = startHttpServer();
        }
        catch (Exception ex) {
            PortInUseException.ifCausedBy(ex, ChannelBindException.class, (bindException) -> {
                if (!isPermissionDenied(bindException.getCause())) {
                    throw new PortInUseException(bindException.localPort(), ex);
                }
            });
            throw new WebServerException("Unable to start Netty", ex);
        }
        logger.info("Netty started on port(s): " + getPort());
        startDaemonAwaitThread(this.disposableServer);
    }
}

// NettyWebServer#startDaemonAwaitThread()
private void startDaemonAwaitThread(DisposableServer disposableServer) {
        Thread awaitThread = new Thread("server") {
            @Override
            public void run() { disposableServer.onDispose().block(); }
        };
        awaitThread.setContextClassLoader(getClass().getClassLoader());
        awaitThread.setDaemon(false);
        awaitThread.start();
}
```

reactor.netty.tcp.TcpServerBind#bind() invoke [io.netty.bootstrap.ServerBootstrap#bind()](/docs/CS/Java/Netty/Bootstrap.md?id=serverbootstrapbind-)
```java
// reactor.netty.tcp.TcpServerBind#bind()
public Mono<? extends DisposableServer> bind(ServerBootstrap b) {
        SslProvider ssl = SslProvider.findSslSupport(b);
        if (ssl != null && ssl.getDefaultConfigurationType() == null) {
            ssl = SslProvider.updateDefaultConfiguration(ssl, DefaultConfigurationType.TCP);
            SslProvider.setBootstrap(b, ssl);
        }

        if (b.config().group() == null) {
            TcpServerRunOn.configure(b, LoopResources.DEFAULT_NATIVE, TcpResources.get());
        }

        return Mono.create((sink) -> {
            ServerBootstrap bootstrap = b.clone();
            ConnectionObserver obs = BootstrapHandlers.connectionObserver(bootstrap);
            ConnectionObserver childObs = BootstrapHandlers.childConnectionObserver(bootstrap);
            OnSetup ops = BootstrapHandlers.channelOperationFactory(bootstrap);
            convertLazyLocalAddress(bootstrap);
            BootstrapHandlers.finalizeHandler(bootstrap, ops, new TcpServerBind.ChildObserver(childObs));
            ChannelFuture f = bootstrap.bind();
            TcpServerBind.DisposableBind disposableServer = new TcpServerBind.DisposableBind(sink, f, obs, bootstrap);
            f.addListener(disposableServer);
            sink.onCancel(disposableServer);
        });
}
```