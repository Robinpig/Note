## Introduction

The reactive-stack web framework, **Spring WebFlux**, has been added Spring 5.0. It is fully non-blocking, supports [reactive streams](http://www.reactive-streams.org/) back pressure, and runs on such servers as Netty, Undertow, and Servlet 3.1+ containers.



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



## handle

Contract to handle a web request.
Use *HttpWebHandlerAdapter* to adapt a *WebHandler* to an *HttpHandler*. The *WebHttpHandlerBuilder* provides a convenient way to do that while also optionally configuring one or more filters and/or exception handlers.

```java
public interface WebHandler {

   //Handle the web server exchange.
   Mono<Void> handle(ServerWebExchange exchange);

}
```



### DispatcherHandler

Central dispatcher for HTTP request handlers/controllers. Dispatches to registered handlers for processing a request, providing convenient mapping facilities.
DispatcherHandler discovers the delegate components it needs from Spring configuration. It detects the following in the application context:
HandlerMapping -- map requests to handler objects
HandlerAdapter -- for using any handler interface
HandlerResultHandler -- process handler return values
DispatcherHandler is also designed to be a Spring bean itself and implements ApplicationContextAware for access to the context it runs in. If DispatcherHandler is declared as a bean with the name "webHandler", it is discovered by WebHttpHandlerBuilder.applicationContext(ApplicationContext) which puts together a processing chain together with WebFilter, WebExceptionHandler and others.
A DispatcherHandler bean declaration is included in @EnableWebFlux configuration.



```java
public class DispatcherHandler implements WebHandler, PreFlightRequestHandler, ApplicationContextAware {

   @Nullable
   private List<HandlerMapping> handlerMappings;

   @Nullable
   private List<HandlerAdapter> handlerAdapters;

   @Nullable
   private List<HandlerResultHandler> resultHandlers;
  
  ...
}
```



```java
// DispatcherHandler
@Override
public Mono<Void> handle(ServerWebExchange exchange) {
   if (this.handlerMappings == null) {
      return createNotFoundError();
   }
   if (CorsUtils.isPreFlightRequest(exchange.getRequest())) {
      return handlePreFlight(exchange);
   }
   return Flux.fromIterable(this.handlerMappings)
         .concatMap(mapping -> mapping.getHandler(exchange))
         .next()
         .switchIfEmpty(createNotFoundError())
         .flatMap(handler -> invokeHandler(exchange, handler))
         .flatMap(result -> handleResult(exchange, result));
}
```



```java
// DispatcherHandler
@Override
public void setApplicationContext(ApplicationContext applicationContext) {
   initStrategies(applicationContext);
}


protected void initStrategies(ApplicationContext context) {
   Map<String, HandlerMapping> mappingBeans = BeanFactoryUtils.beansOfTypeIncludingAncestors(
         context, HandlerMapping.class, true, false);

   ArrayList<HandlerMapping> mappings = new ArrayList<>(mappingBeans.values());
   AnnotationAwareOrderComparator.sort(mappings);
   this.handlerMappings = Collections.unmodifiableList(mappings);

   Map<String, HandlerAdapter> adapterBeans = BeanFactoryUtils.beansOfTypeIncludingAncestors(
         context, HandlerAdapter.class, true, false);

   this.handlerAdapters = new ArrayList<>(adapterBeans.values());
   AnnotationAwareOrderComparator.sort(this.handlerAdapters);

   Map<String, HandlerResultHandler> beans = BeanFactoryUtils.beansOfTypeIncludingAncestors(
         context, HandlerResultHandler.class, true, false);

   this.resultHandlers = new ArrayList<>(beans.values());
   AnnotationAwareOrderComparator.sort(this.resultHandlers);
}
```
