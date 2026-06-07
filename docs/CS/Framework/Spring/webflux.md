## Introduction

响应式栈 Web 框架 [Spring WebFlux](https://docs.spring.io/spring-framework/docs/current/reference/html/web-reactive.html) 已在 Spring 5.0 中加入。
它是完全非阻塞的，支持[响应式流](http://www.reactive-streams.org/)背压，并可在 Netty、Undertow 和 Servlet 3.1+ 容器等服务器上运行。

### Concurrency Model

[Spring MVC](/docs/CS/Framework/Spring/MVC.md) 和 Spring WebFlux 都支持注解控制器，但在并发模型以及阻塞和线程的默认假设方面存在关键差异。
- 在 Spring MVC（以及一般的 Servlet 应用）中，假设应用可以阻塞当前线程（例如，用于远程调用）。
  因此，Servlet 容器使用大型线程池来吸收请求处理期间的潜在阻塞。
- 在 Spring WebFlux（以及一般的非阻塞服务器）中，假设应用不会阻塞。
  因此，非阻塞服务器使用小的固定大小线程池（事件循环工作者）来处理请求。

## Start Server

[AbstractApplicationContext#refresh()](/docs/CS/Framework/Spring/IoC.md?id=abstractapplicationcontextrefresh)-> finishRefresh -> LifecycleProcessor#onRefresh() -> DefaultLifecycleProcessor#startBeans() -> DefaultLifecycleProcessor#doStart()
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

reactor.netty.tcp.TcpServerBind#bind() invoke [io.netty.bootstrap.ServerBootstrap#bind()](/docs/CS/Framework/Netty/Bootstrap.md?id=serverbootstrapbind-)
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

处理 Web 请求的契约。
使用 *HttpWebHandlerAdapter* 将 *WebHandler* 适配为 *HttpHandler*。*WebHttpHandlerBuilder* 提供了一种方便的方式，同时还可以选择配置一个或多个过滤器和/或异常处理程序。

```java
public interface WebHandler {

   //Handle the web server exchange.
   Mono<Void> handle(ServerWebExchange exchange);

}
```

### DispatcherHandler

HTTP 请求处理器/控制器的中央分发器。将请求分派到注册的处理程序进行处理，提供方便映射功能。

DispatcherHandler 从 Spring 配置中发现所需的委托组件。它在应用上下文中检测以下内容：

- HandlerMapping -- 将请求映射到处理器对象
  - RoutePredicateHandlerMapping
    - [Spring Cloud Gateway](/docs/CS/Framework/Spring_Cloud/gateway.md)
- HandlerAdapter -- 用于使用任何处理器接口
- HandlerResultHandler -- 处理处理程序返回值

DispatcherHandler 本身也被设计为一个 Spring bean，并实现了 ApplicationContextAware 以访问其运行的上下文。
如果 DispatcherHandler 被声明为名为 "webHandler" 的 bean，它将被 WebHttpHandlerBuilder.applicationContext(ApplicationContext) 发现，该方法将处理链与 WebFilter、WebExceptionHandler 等其他组件组合在一起。

`@EnableWebFlux` 配置中包含一个 DispatcherHandler bean 声明。

```java
public class DispatcherHandler implements WebHandler, PreFlightRequestHandler, ApplicationContextAware {

    @Nullable
    private List<HandlerMapping> handlerMappings;

    @Nullable
    private List<HandlerAdapter> handlerAdapters;

    @Nullable
    private List<HandlerResultHandler> resultHandlers;


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

    @Override
    public Mono<Object> getHandler(ServerWebExchange exchange) {
        return getHandlerInternal(exchange).map(handler -> {
            ServerHttpRequest request = exchange.getRequest();
            if (hasCorsConfigurationSource(handler) || CorsUtils.isPreFlightRequest(request)) {
                CorsConfiguration config = (this.corsConfigurationSource != null ? this.corsConfigurationSource.getCorsConfiguration(exchange) : null);
                CorsConfiguration handlerConfig = getCorsConfiguration(handler, exchange);
                config = (config != null ? config.combine(handlerConfig) : handlerConfig);
                if (!this.corsProcessor.process(config, exchange) || CorsUtils.isPreFlightRequest(request)) {
                    return REQUEST_HANDLED_HANDLER;
                }
            }
            return handler;
        });
    }
}
```

#### initStrategies
```java
public class DispatcherHandler implements WebHandler, PreFlightRequestHandler, ApplicationContextAware {
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
}
```

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Netty](/docs/CS/Framework/Netty/Netty.md)
