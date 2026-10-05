## Introduction

The reactive-stack web framework, [Spring WebFlux](https://docs.spring.io/spring-framework/reference/web/webflux.html), has been added Spring 5.0. 
It is fully non-blocking, supports [reactive streams](http://www.reactive-streams.org/) back pressure, and runs on such servers as Netty, Undertow, and Servlet 3.1+ containers.

> [!NOTE]
> 部署环境在 7.x 一代有两处变化：Spring Boot 4 **不再支持 Undertow**（尚未兼容 Jakarta Servlet 6.1），响应式应用默认用 Reactor Netty 或 Jetty；`WebClient` 也从 WebFlux starter 中独立出来，改由 `spring-boot-starter-webclient` 引入。


### Concurrency Model

Both [Spring MVC](/docs/CS/Framework/Spring/MVC.md) and Spring WebFlux support annotated controllers, but there is a key difference in the concurrency model and the default assumptions for blocking and threads.
- In Spring MVC (and servlet applications in general), it is assumed that applications can block the current thread, (for example, for remote calls). 
  For this reason, servlet containers use a large thread pool to absorb potential blocking during request handling.
- In Spring WebFlux (and non-blocking servers in general), it is assumed that applications do not block. 
  Therefore, non-blocking servers use a small, fixed-size thread pool (event loop workers) to handle requests.



## Start Server

[AbstractApplicationContext#refresh()](/docs/CS/Framework/Spring/IoC.md?id=refresh)-> finishRefresh -> LifecycleProcessor#onRefresh() -> DefaultLifecycleProcessor#startBeans() -> DefaultLifecycleProcessor#doStart()
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

reactor.netty.tcp.TcpServerBind#bind() invoke [io.netty.bootstrap.ServerBootstrap#bind()](/docs/CS/Framework/Netty/Bootstrap.md?id=bind)
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

- HandlerMapping -- map requests to handler objects
  - RoutePredicateHandlerMapping
    - [Spring Cloud Gateway](/docs/CS/Framework/Spring_Cloud/gateway.md)
- HandlerAdapter -- for using any handler interface
- HandlerResultHandler -- process handler return values

DispatcherHandler is also designed to be a Spring bean itself and implements ApplicationContextAware for access to the context it runs in. If DispatcherHandler is declared as a bean with the name "webHandler", it is discovered by WebHttpHandlerBuilder.applicationContext(ApplicationContext) which puts together a processing chain together with WebFilter, WebExceptionHandler and others.

A DispatcherHandler bean declaration is included in `@EnableWebFlux` configuration.



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



## 两种编程模型

`DispatcherHandler` 之所以能同时支持注解式控制器和函数式端点，是因为它把"请求 → 处理器"这一步完全委托给 `HandlerMapping` 链，而容器里可以同时存在多种实现，按 `@Order` 依次匹配：

| HandlerMapping | 负责 | 对应模型 |
| :-- | :-- | :-- |
| `RequestMappingHandlerMapping` | `@RequestMapping` / `@GetMapping` 等 | 注解式控制器 |
| `RouterFunctionMapping` | `RouterFunction<ServerResponse>` Bean | 函数式端点 |
| `SimpleUrlHandlerMapping` | 静态资源等 | 资源处理 |

两者可以在同一个应用里混用，最终都被适配成 `HandlerAdapter` 能调用的形态。

| 维度 | 注解式控制器 | 函数式端点 |
| :-- | :-- | :-- |
| 定义方式 | 类 + 注解 | 路由表 Bean + 处理函数 |
| 路由可见性 | 分散在各控制器 | **集中在一处，一眼看全** |
| 与 MVC 迁移成本 | 低，写法几乎一致 | 高 |
| 条件分支路由 | 靠注解属性表达，能力有限 | 任意谓词组合 |
| 复杂前置处理 | 靠拦截器 / AOP | 直接用 `before` / `filter` 组合子 |
| 适用场景 | 常规 REST API、团队熟悉 MVC | 小型服务、路由规则复杂、API 网关类场景 |

## RouterFunction 函数式端点

路由用一个返回 `RouterFunction<ServerResponse>` 的 Bean 声明，谓词与处理器写在一起：

```java
@Configuration
class PersonRoutes {

    @Bean
    RouterFunction<ServerResponse> personRoutes(PersonHandler handler) {
        return RouterFunctions.route()
                .GET("/person/{id}", accept(MediaType.APPLICATION_JSON), handler::getOne)
                .GET("/person", handler::list)
                .POST("/person", accept(MediaType.APPLICATION_JSON), handler::create)
                .PUT("/person/{id}", handler::update)
                .DELETE("/person/{id}", handler::delete)
                .build();
    }
}
```

`RequestPredicates` 提供的谓词可以任意组合（`and` / `or` / `negate`），这是函数式最直接的收益：

```java
import static org.springframework.web.reactive.function.server.RequestPredicates.*;

route()
  .nest(path("/api/v1"), builder -> builder          // 公共前缀
        .GET("/orders", accept(APPLICATION_JSON), h::listOrders)
        .GET("/orders/{id}", h::getOrder))
  .GET("/internal/**", headers(h -> h.containsHeader("X-Internal")), h::internal)
  .add(otherRoutes)
  .build();
```

### HandlerFunction

处理函数的签名固定为 `Mono<ServerResponse> handle(ServerRequest)`：

```java
@Component
class PersonHandler {

    private final PersonRepository repository;

    Mono<ServerResponse> getOne(ServerRequest request) {
        String id = request.pathVariable("id");
        return repository.findById(id)
                .flatMap(person -> ServerResponse.ok()
                        .contentType(MediaType.APPLICATION_JSON)
                        .bodyValue(person))
                .switchIfEmpty(ServerResponse.notFound().build());
    }

    Mono<ServerResponse> create(ServerRequest request) {
        Mono<Person> person = request.bodyToMono(Person.class);
        return ServerResponse.status(HttpStatus.CREATED)
                .body(repository.saveAll(person), Person.class);
    }
}
```

`ServerRequest` 侧的取值 API：`pathVariable` / `queryParam` / `headers()` / `bodyToMono` / `bodyToFlux` / `formData()` / `multipartData()` / `attribute()`。注意 `body` 只能被消费一次——这是响应式流的基本性质，多次订阅会报错。

### 组合子：before / after / filter

函数式的"拦截器"是组合子，直接写在路由上：

```java
route()
  .before(request -> {                     // 改请求
      log.info("{} {}", request.method(), request.path());
      return ServerRequest.from(request).header("X-Trace-Id", traceId()).build();
  })
  .filter((request, next) -> next.handle(request)   // 包住整条链，可做鉴权/限流
          .onErrorResume(AuthenticationException.class,
                  ex -> ServerResponse.status(UNAUTHORIZED).build()))
  .after((request, response) -> response)  // 改响应
  .GET("/person/{id}", handler::getOne)
  .build();
```

`before` 只改请求、`after` 只改响应、`filter` 能短路并替换整条处理链——权限校验这类需要拒绝请求的逻辑应放在 `filter`。

## WebClient

`WebClient` 是响应式 HTTP 客户端，用来调用下游服务。7.x 一代它已从 WebFlux starter 中独立出去，需单独引入 `spring-boot-starter-webclient`；同步场景则改用 [RestClient](/docs/CS/Framework/Spring/RestClient.md)（原 `RestTemplate` 在 7.1 弃用、8.0 移除）。

```java
WebClient client = WebClient.builder()
        .baseUrl("https://api.example.com")
        .defaultHeader(HttpHeaders.ACCEPT, MediaType.APPLICATION_JSON_VALUE)
        .build();

Mono<Person> person = client.get()
        .uri("/person/{id}", id)
        .retrieve()
        .bodyToMono(Person.class);
```

### retrieve 与 exchange

| 方法 | 语义 | 状态 |
| :-- | :-- | :-- |
| `retrieve()` | 直接声明"我要 body"，4xx/5xx 默认抛 `WebClientResponseException` | 首选 |
| `exchangeToMono` / `exchangeToFlux` | 拿到完整响应再自行决定如何映射，包括按状态码分派 | 需要精细控制时用 |
| `exchange()` | 早期 API，会把响应体留在内存中且需手动释放 | 已弃用，不要再用 |

按状态码分派的典型写法：

```java
client.get().uri("/orders/{id}", id)
      .exchangeToMono(response -> {
          if (response.statusCode().is2xxSuccessful()) {
              return response.bodyToMono(Order.class);
          }
          if (response.statusCode() == HttpStatus.NOT_FOUND) {
              return Mono.empty();
          }
          return response.createException().flatMap(Mono::error);
      });
```

### 错误处理、超时与重试

```java
client.get().uri("/orders/{id}", id)
      .retrieve()
      .onStatus(HttpStatus::is4xxClientError,
              resp -> resp.bodyToMono(ProblemDetail.class).flatMap(Mono::error))   // 与服务端 ProblemDetail 对齐
      .onStatus(HttpStatus::is5xxServerError,
              resp -> Mono.error(new DownstreamException()))
      .bodyToMono(Order.class)
      .timeout(Duration.ofSeconds(2))                       // 单个请求超时
      .retryWhen(Retry.backoff(3, Duration.ofMillis(200))   // 退避重试
                      .filter(ex -> ex instanceof WebClientRequestException));
```

`timeout` 只切断当前订阅，不会取消下游已发出的连接，写操作要慎用重试（非幂等接口重试可能造成重复）。

### 连接层配置

超时、连接池、SSL 等属于 `HttpClient`（Reactor Netty）而非 `WebClient` 本身：

```java
HttpClient httpClient = HttpClient.create()
        .responseTimeout(Duration.ofSeconds(2))
        .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, 1000);

WebClient client = WebClient.builder()
        .clientConnector(new ReactorClientHttpConnector(httpClient))
        .build();
```

Boot 提供了预配置的 `WebClient.Builder` Bean，注入它即可继承编解码器、指标与观测配置。

## 响应式异常处理

注解式控制器沿用 `@ExceptionHandler` / `@RestControllerAdvice`，只是返回值可以是 `Mono`：

```java
@RestControllerAdvice
class GlobalExceptionHandler {

    @ExceptionHandler(NotFoundException.class)
    Mono<ResponseEntity<ProblemDetail>> handle(NotFoundException ex, ServerWebExchange exchange) {
        ProblemDetail pd = ProblemDetail.forStatusAndDetail(HttpStatus.NOT_FOUND, ex.getMessage());
        return Mono.just(ResponseEntity.status(HttpStatus.NOT_FOUND).body(pd));
    }
}
```

标准错误响应体 `ProblemDetail` 的约定见 [统一异常处理](/docs/CS/Framework/Spring/Exception.md)。函数式端点则走路由上的 `onError`：

```java
route()
  .GET("/person/{id}", handler::getOne)
  .onError(NotFoundException.class,
           (ex, request) -> ServerResponse.status(NOT_FOUND).build())
  .onError(Throwable.class,
           (ex, request) -> ServerResponse.status(INTERNAL_SERVER_ERROR).build())
  .build();
```

校验失败在 WebFlux 里抛的是 `WebExchangeBindException`（对应 MVC 的 `MethodArgumentNotValidException`），若开启 `spring.webflux.problemdetails.enabled`，Boot 会把它统一转成 RFC 9457 问题详情。

未被任何 handler 处理的异常最终落到 `ErrorWebExceptionHandler`（默认实现 `DefaultErrorWebExceptionHandler`）——自定义全局兜底要实现这个接口，而不是 MVC 那套 `ErrorController`。

## 上下文传播

响应式链上没有线程局部变量可用：请求中途会切换线程，`ThreadLocal` 里的 `SecurityContext`、MDC、观测上下文都会丢。替代机制是 Reactor 的 `Context`：

```java
Mono<Order> order = Mono.deferContextual(ctx -> {
        String tenant = ctx.get("tenant");
        return repository.findById(id, tenant);
    })
    .contextWrite(ctx -> ctx.put("tenant", tenantId));
```

WebFlux 已把 `ServerRequest`、`ExchangeContext`（承载 `SecurityContext`）等写入 Reactor Context，业务代码用 `deferContextual` / `transformDeferredContextual` 读取即可。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [Reactive](/docs/CS/Framework/Spring/Reactive.md)
- [Spring MVC](/docs/CS/Framework/Spring/MVC.md)
- [统一异常处理](/docs/CS/Framework/Spring/Exception.md)

## References

- [Spring WebFlux - Functional Endpoints](https://docs.spring.io/spring-framework/reference/web/webflux-functional.html)
- [Spring WebFlux - WebClient](https://docs.spring.io/spring-framework/reference/web/webflux-webclient.html)
- [Spring Boot - WebClient Auto-configuration](https://docs.spring.io/spring-boot/reference/io/webclient.html)
