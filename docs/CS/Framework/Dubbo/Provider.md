## Introduction

消费侧有 [Consumer](/docs/CS/Framework/Dubbo/Consumer.md) 专篇，而 Provider 侧长期被当成「Consumer 的镜像」一笔带过——这是错的。两侧的扩展点集合、配置项默认值、限流语义都不对称，几处最常见的错误恰恰来自「把消费侧的东西搬到服务端」：

1. **`actives` 不是服务端并发控制。** `ActiveLimitFilter` 的 `@Activate` 是 `group = CONSUMER`（`ActiveLimitFilter.java:45`），异常文案里明写 `"Waiting concurrent invoke timeout in client-side for service: "`（`:72`）。服务端对应的限制是 `executes`。
2. **服务端没有 `retries`。** 重试是消费侧 Cluster 的行为，`retries` 字段只存在于方法级配置。
3. **`ExporterListener` 没有任何内置实现注册。** 生产 resources 里连 SPI 文件都没有（只有测试资源下有一份），想监听服务暴露事件只能用 `ServiceListener`。

本文版本基线：Apache Dubbo **3.3.6**（源码 tag `dubbo-3.3.6`），所有默认值均标注文件与行号。

- 服务暴露的**完整时序**见 [Start](/docs/CS/Framework/Dubbo/Start.md)，配置对象模型见 [ServiceConfig](/docs/CS/Framework/Dubbo/ServiceConfig.md)。
- 服务端线程模型与 Dispatcher 五个派发模型见 [ThreadPool](/docs/CS/Framework/Dubbo/ThreadPool.md)。
- Filter 的 order 排序机制见 [Filter](/docs/CS/Framework/Dubbo/Filter.md)。

## Provider Call Chain

服务端的完整处理链路（自下而上）：

1. **Transport**：`NettyServer` 的 boss/worker 线程收包，`NettyCodecAdapter` 完成解码
2. **Codec**：`ExchangeCodec` / `DubboCodec` 解析 16 字节头 + body，构建 `Request` / `Response`（见 [Protocol](/docs/CS/Framework/Dubbo/Protocol.md)）
3. **Exchange**：`HeaderExchangeHandler` 按消息类型分派
4. **Dispatch**：按 `Dispatcher` 策略决定「在 IO 线程直接执行」还是「丢到业务线程池」（见 [ThreadPool](/docs/CS/Framework/Dubbo/ThreadPool.md)）
5. **Protocol**：`DubboProtocol` 的请求处理器按 serviceKey 找到对应 `Exporter` → `Invoker`
6. **Filter 链**：执行服务端的 Filter（鉴权、限流、访问日志、异常包装等）
7. **Proxy**：`JavassistProxyFactory` 生成的 Skeleton 把 `Invocation` 转成真实方法调用
8. **Service 实现类**执行并返回，结果沿原链路回溯

第 6 步是服务端扩展的主战场。Filter 链在 export 时由 Protocol 的包装器构建，排序仍由 `@Activate` 的 order 决定。

## Provider-Side Extension Points

### Protocol

`dubbo-rpc-api` 的 `org.apache.dubbo.rpc.Protocol` SPI 文件里注册了 5 项，**全是包装器**（`dubbo-rpc/dubbo-rpc-api/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.Protocol:1-5`）：

```
listener=org.apache.dubbo.rpc.protocol.ProtocolListenerWrapper
serializationwrapper=org.apache.dubbo.rpc.protocol.ProtocolSerializationWrapper
securitywrapper=org.apache.dubbo.rpc.protocol.ProtocolSecurityWrapper
invokercount=org.apache.dubbo.rpc.protocol.InvokerCountWrapper
mock=org.apache.dubbo.rpc.support.MockProtocol
```

真正的协议实现（dubbo / injvm / tri / registry）分别在 `dubbo-rpc-dubbo`、`dubbo-rpc-injvm`、`dubbo-rpc-triple`、`dubbo-registry-api` **各自的 SPI 文件**里。这解释了为什么「Protocol SPI 文件里找不到 dubbo 协议」——找错文件了。

### ProxyFactory

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/ProxyFactory.java:29
@SPI(value = "javassist", scope = FRAMEWORK)
public interface ProxyFactory { ... @Adaptive({PROXY_KEY}) ... }
```

SPI 文件注册 4 项：`stub`（`StubProxyFactoryWrapper`）、`jdk`（`JdkProxyFactory`）、`javassist`（`JavassistProxyFactory`）、`nativestub`（`StubProxyFactory`）。默认 `javassist`，全局常量 `CommonConstants.DEFAULT_PROXY = "javassist"`（`CommonConstants.java:99`）。

> [!WARNING]
> **3.3.6 没有 cglib。** 全仓库 `cglib` 只命中四处：BOM 版本声明（`dubbo-dependencies-bom/pom.xml:164,782-784`）、`dubbo-common` 的 **test scope** 依赖（`:104-105`）、测试类 `ProxyTest.java:51`、以及序列化黑名单 `serialize.blockedlist:96`。**没有任何 `CglibProxyFactory` 类或 SPI key**——网上「Dubbo 支持 cglib 代理」的说法来自 2.x。

### Filter

`dubbo-rpc/dubbo-rpc-api` 的 Filter SPI 文件共 18 条注册项，其中 **`@Activate` 的 group 含 PROVIDER 的有 13 个**（`dubbo-rpc/dubbo-rpc-api/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.Filter:1-18`）：

| key | Filter | `@Activate` 位置 | order | 激活条件 |
| :--- | :--- | :--- | :--- | :--- |
| `echo` | EchoFilter | `EchoFilter.java:33` | `-110000` | 无条件 |
| `generic` | GenericFilter | `GenericFilter.java:74` | `-20000` | 无条件 |
| `token` | TokenFilter | `TokenFilter.java:38` | — | `value = TOKEN_KEY`，需配 token |
| `accesslog` | AccessLogFilter | `AccessLogFilter.java:72` | — | 无条件，但 accesslog 为空/false 时内部直接透传 |
| `classloader` | ClassLoaderFilter | `ClassLoaderFilter.java:34` | `-30000` | 无条件 |
| `classloader-callback` | ClassLoaderCallbackFilter | `ClassLoaderCallbackFilter.java:33` | `Integer.MAX_VALUE` | 无条件 |
| `context` | ContextFilter | `ContextFilter.java:63` | `Integer.MIN_VALUE` | 无条件 |
| `profiler-server` | ProfilerServerFilter | `ProfilerServerFilter.java:45` | `Integer.MIN_VALUE` | 无条件 |
| `exception` | ExceptionFilter | `ExceptionFilter.java:49` | — | 无条件 |
| `timeout` | TimeoutFilter | `TimeoutFilter.java:38` | — | 无条件 |
| `executelimit` | ExecuteLimitFilter | `ExecuteLimitFilter.java:40` | — | `value = EXECUTES_KEY`，需配 executes |
| `tps` | TpsLimitFilter | `TpsLimitFilter.java:40` | — | `value = TPS_LIMIT_RATE_KEY`，需配 tps |
| — | CompatibleFilter | **无 `@Activate`** | — | **注册了也不会自动生效** |

对照组（Consumer 侧）：`genericimpl`（order 20000）、`deprecated`、`active-limit`、`rpc-exception`、`adaptiveLoadBalance`（order -200000）。

> [!NOTE]
> `CompatibleFilter` 只有 `@Deprecated` 注解（`CompatibleFilter.java:48`）而**没有 `@Activate`**，因此即便在 SPI 文件里注册了也不会进入任何调用链——这是「照着 SPI 文件数 Filter 数量」会数错的典型例子。
>
> 另外 `dubbo-cluster`、`dubbo-metrics-default`、`dubbo-tracing`、`dubbo-auth`、`dubbo-filter-cache`、`dubbo-filter-validation`、`dubbo-spring-security`、`dubbo-rpc-dubbo`、`dubbo-rpc-triple` **各自也有 Filter SPI 文件**，会叠加到全链上。所以「Provider 一共 13 个 Filter」只是 `dubbo-rpc-api` 一个文件的口径。

### Listener

- **`ExporterListener`**：接口存在（`dubbo-rpc/dubbo-rpc-api/.../rpc/ExporterListener.java:26`），但**生产 resources 里没有任何 SPI 文件**，3.3.6 无内置实现注册。
- **`InvokerListener`**：只有一条 `deprecated=org.apache.dubbo.rpc.listener.DeprecatedInvokerListener`（`.../META-INF/dubbo/internal/org.apache.dubbo.rpc.InvokerListener:1`）。
- 想监听服务暴露/取消暴露事件，用 **`ServiceListener`**——它由 `ServiceConfig.onExported()` / `onUnexported()` 直接遍历通知（`ServiceConfig.java:1026-1036`），见 [ServiceConfig](/docs/CS/Framework/Dubbo/ServiceConfig.md)。

## Provider Registration to Registry

消费侧启动时由 `RegistryProtocol` 把「订阅 URL」交给注册中心；Provider 侧则由**同一个** `RegistryProtocol.export()` 把「自己提供的服务」注册上去。这一步是「Provider 注册」的全部含义，它和本地协议导出（`doLocalExport`）是**两个不同动作**，但都在 `export()` 里串行完成。

`RegistryProtocol.export(Invoker<?> originInvoker)`（`dubbo-registry/dubbo-registry-api/.../registry/integration/RegistryProtocol.java:272`）的完整顺序：

```java
272  public <T> Exporter<T> export(final Invoker<T> originInvoker) throws RpcException {
273      URL registryUrl = getRegistryUrl(originInvoker);          // = originInvoker.getUrl()  (:489-491)
275      URL providerUrl = getProviderUrl(originInvoker);          // 取 invoker.url 的 "export" 属性 (:530-537)
288      providerUrl = overrideUrlWithConfig(providerUrl, overrideSubscribeListener); // 先合并 provider/service 配置
290      final ExporterChangeableWrapper<T> exporter = doLocalExport(originInvoker, providerUrl); // ① 先本地导出
293      final Registry registry = getRegistry(registryUrl);       // 取 Registry 实例
294      final URL registeredProviderUrl = customizeURL(providerUrl, registryUrl); // URL 变换(见下)
297      boolean register = providerUrl.getParameter(REGISTER_KEY, true)
298              && registryUrl.getParameter(REGISTER_KEY, true);
299      if (register) { register(registry, registeredProviderUrl); } // ② 再向注册中心注册
303      registerStatedUrl(registryUrl, registeredProviderUrl, register); // 存进 ProviderModel，非静态集合
305      exporter.setRegisterUrl(registeredProviderUrl);
306      exporter.setSubscribeUrl(overrideSubscribeUrl);
307      exporter.setNotifyListener(overrideSubscribeListener);
308      exporter.setRegistered(register);
317      registry.subscribe(overrideSubscribeUrl, overrideSubscribeListener); // 受开关保护(见下)
321      notifyExport(exporter);
323      return new DestroyableExporter<>(exporter);
324  }
```

几个容易记错的点：

- **`providerUrl` 不是从 `registryUrl` 过滤参数得到的**。`getProviderUrl`（`:530-537`）直接取 `originInvoker.getUrl().getAttribute(EXPORT_KEY)`——即挂在 `registry://` 这个 invoker URL 的 `export` 属性上的、真正的服务 URL（如 `dubbo://host:port/...`）。registry 自身参数之所以不污染注册 URL，靠的是「providerUrl 与 registryUrl 是 URL 上的两个不同属性」，而不是用 `filter` 剥离某个 key。
- **`doLocalExport` 先于 `registry.register`**。本地协议导出（真正起 Netty Server、`exporterMap` 落表）在前，注册在后；即使注册中心暂时不可用，本地服务也能先起来（只是 consumer 暂时看不到）。
- **注册的 URL 形态**：`customizeURL(providerUrl, registryUrl)`（`:507-516`）只做 `putAttribute(SIMPLIFIED_KEY, ...)`、`putAttribute(EXTRA_KEYS_KEY, ...)` 并应用 `ServiceURLCustomizer` 扩展，**不做 `appendParameters`、不 `addParameter(CATEGORY_KEY=providers)`**。也就是说 3.x 注册出去的其实就是「带着两个 attribute 的原生 provider URL」；`category=providers` / `dynamic` 是注册中心实现层（`AbstractRegistry` / `FailbackRegistry`）在落存储时拼的，`RegistryProtocol` 不负责。

`doLocalExport`（`:349-360`）把 `providerUrl` 包成 `InvokerDelegate`，再 `exporterFactory.createExporter(providerUrlKey, () -> protocol.export(invokerDelegate))`（`:354-355`）。这里的 `protocol` 是完整协议包装链，末端的 `ProtocolFilterWrapper.export` 会顺手构建好**服务端 Filter 链**（见 Provider-Side Invocation Handling），最终 `DubboProtocol.export` 把「已包 Filter 链的 invoker」存进 `exporterMap`（见 Exporter Management）。导出关系挂在 `bounds` 字段（`:185-186`，`ConcurrentHashMap<String, ConcurrentHashMap<String, ExporterChangeableWrapper<?>>>`）：外层 key = `providerUrl.removeParameters(DYNAMIC_KEY, ENABLED_KEY).toFullString()`（`:545-548`），内层 key = `registryUrl` 同法处理后的串（`:550-553`）。

### Override / 动态配置在 3.x 的归属

`OverrideListener`（内部类，`:815-925`，实现 `NotifyListener`）确实存在，订阅的是 `getSubscribedOverrideUrl(providerUrl)`（其 `category=configurators`，`:518-522`），收到变更后过滤 `category=configurators` 的 URL、转成 `Configurator`，必要时 `reExport`。**但 `export()` 里的 `registry.subscribe(...)`（`:317`）是带开关的**：仅当 `ENABLE_26X_CONFIGURATION_LISTEN` 开启且 `!registry.isServiceDiscovery()` 时才走注册中心订阅。

> [!WARNING]
> **3.x 与 2.x 在「Provider 注册」上最容易被照抄错的一点：3.3.6 已没有「把 provider URL 注册成 configurator / override」的逻辑。** `registry.register(...)`（`:258`）注册的就是 provider 自身；override 动态配置改由 `ProviderConfigurationListener` / `ServiceConfigurationListener` 走配置中心（`GovernanceRuleRepository`）推送，注册中心订阅只是 2.6 兼容开关下的可选项。任何「provider 注册时会往注册中心写一份 override 规则」的说法都是 2.x 记忆。

反注册对称：`DestroyableExporter.unexport()` → `ExporterChangeableWrapper.unexport()`（`:1161-1171`）先清 `bounds`、再 `unregister()`（`:1087-1158`，用 `registered.compareAndSet(true,false)` 保证只执行一次）调 `registry.unregister(registerUrl)`（`:1106`）、最后 `doUnExport()`。

## Provider-Side Invocation Handling

Provider Call Chain 把服务端链路拆成 8 步，这里把它落到真实代码：一条入站请求从 Netty 线程一路调到实现类，中间经过哪些类、Filter 链在哪构建、谁创建了 `AsyncRpcResult`。

1. **分派入口**：`HeaderExchangeHandler.received(Channel, Object)`（`dubbo-remoting/.../exchange/support/header/HeaderExchangeHandler.java:196`）按消息类型分派；双向 `Request` 走 `handleRequest(exchangeChannel, request)`（`:206`）。
2. **构造 Response**：`handleRequest`（`:88`）取出 `req.getData()`，调用 `handler.reply(channel, msg)`（`:110`）——注意 `reply` 返回 `CompletionStage<Object>`，在 `whenComplete` 里填充 `Response` 并 `channel.send(res)`（`:120`），即**响应是异步回写的**。
3. **reply 实现（Dubbo 协议）**：`DubboProtocol` 内部 `requestHandler`（字段 `:111`，继承 `ExchangeHandlerAdapter`）的 `reply(ExchangeChannel, Object)`（`:117`）：

   ```java
   117  public CompletableFuture<Object> reply(ExchangeChannel channel, Object message) throws RemotingException {
   119      if (!(message instanceof Invocation)) { throw new RemotingException(...); }
   130      Invocation inv = (Invocation) message;
   131      Invoker<?> invoker = inv.getInvoker() == null ? getInvoker(channel, inv) : inv.getInvoker();
   166      RpcContext.getServiceContext().setRemoteAddress(channel.getRemoteAddress());
   167      Result result = invoker.invoke(inv);          // 进入 Filter 链 + Proxy
   168      return result.thenApply(Function.identity()); // Result -> CompletableFuture
   169  }
   ```

   `getInvoker(Channel, Invocation)`（`:287`）用 `port/path/version/group`（从 invocation attachment 取，`:308-309`）拼出 `serviceKey`，从 `exporterMap` 取 `DubboExporter`（`:310`）；取不到直接抛 `"Not found exported service: " + serviceKey`——和 Exporter Management 是同一个 map，`version`/`group` 不匹配在此阶段就挂。
4. **服务端 Filter 链是在 export 时构建好的，不是每次请求重建**。`ProtocolFilterWrapper.export`（注意它在 **`dubbo-cluster`** 模块，`org.apache.dubbo.rpc.cluster.filter.ProtocolFilterWrapper:53-58`）：

   ```java
   53   public <T> Exporter<T> export(Invoker<T> invoker) throws RpcException {
   54       if (UrlUtils.isRegistry(invoker.getUrl())) { return protocol.export(invoker); }
   57       FilterChainBuilder builder = getFilterChainBuilder(invoker.getUrl());
   58       return protocol.export(builder.buildInvokerChain(invoker, SERVICE_FILTER_KEY, CommonConstants.PROVIDER));
   59   }
   ```

   group 参数是 `CommonConstants.PROVIDER`（值 `"provider"`），key 是 `"service.filter"`。`buildInvokerChain` 实际实现在 `DefaultFilterChainBuilder.buildInvokerChain`（`:45-77`）：先 `last = originalInvoker`，再**逆序**遍历 filters（`:68`）使 order 最小的成为链头，每个包成 `CopyOfFilterChainNode`，最外层返回 `CallbackRegistrationInvoker`（`:73`）。所以 `reply` 第 167 行 `invoker.invoke(inv)` 调到的，正是 export 时存进 `exporterMap` 的「已包 Filter 链的 invoker」。
5. **Filter 执行顺序（provider 侧，从外到内）**：`CallbackRegistrationInvoker`（先注册 Listener）→ `ContextFilter`（`@Activate(group=PROVIDER, order=Integer.MIN_VALUE)`，最先执行，`:138`）→ 其余 `@Activate(group=PROVIDER)` Filter 按 order 升序 → `AbstractProxyInvoker`（链尾 `originalInvoker`）→ `Wrapper.invokeMethod` → 真实实现类。
6. **服务端 RpcContext 装配**：`ContextFilter.invoke`（`:138`）从 `invocation.getObjectAttachments()` 取出消费端传来的 attachment，注入 `RpcContext.getServerAttachment()`（`:178-180`），设置 service context；调用前 `clearAfterEachInvoke(false)`、调用后 `finally` 里 `clearAfterEachInvoke(true)`（`:190-193`）清理。这就是 [Invocation](/docs/CS/Framework/Dubbo/Invocation.md) 里「Consumer → Provider attachment 透传」的服务端落点。
7. **最底层 Proxy → 实现类**：`AbstractProxyInvoker.invoke`（`dubbo-rpc/.../rpc/proxy/AbstractProxyInvoker.java:87`）调用抽象 `doInvoke(proxy, methodName, paramTypes, args)`（`:100`）；`JavassistProxyFactory.getInvoker`（`:80`）返回的 `AbstractProxyInvoker` 其 `doInvoke` 调 `wrapper.invokeMethod(proxy, methodName, parameterTypes, arguments)`（`:89`）。`Wrapper` 在 `dubbo-common/.../bytecode/Wrapper.java`，由 `getWrapper(Class)` → `makeWrapper` 动态生成 `invokeMethod` 字节码，按方法名反射/Javassist 分派到真实业务方法。**这是服务端 Invoker 的最底层，再往下就是调到你的实现。**

> [!WARNING]
> 三个会被旧笔记带偏的硬事实：
> - **`ProtocolFilterWrapper` 在 3.3.6 已迁到 `dubbo-cluster`（`org.apache.dubbo.rpc.cluster.filter`），不再位于 `dubbo-rpc-api`**；`buildInvokerChain` 也拆到了 `DefaultFilterChainBuilder`。
> - **`AsyncRpcResult` 不在 `reply` 里创建**——`reply` 只把已有的 `Result` 转成 `CompletableFuture`（`:168`）。它真正诞生在 `AbstractProxyInvoker.invoke` 的 `return new AsyncRpcResult(appResponseFuture, invocation)`（`:117`）。
> - **没有 `makeInvoker` 方法、也没有 `JavassistWrapper` 类**（2.x 记忆）。服务端代理走的是 `JavassistProxyFactory.getInvoker` → `AbstractProxyInvoker` → `Wrapper.invokeMethod`。

## Concurrency and Rate Limiting

服务端只有**两个**内置的流量限制 Filter，第三个（actives）是消费侧的：

| Filter | 文件 | 侧 | value key | 默认值 | 默认值出处 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `TpsLimitFilter` | `TpsLimitFilter.java:40` | **PROVIDER** | `tps` | interval = `60000`；**rate 默认 `-1`** | `rpc/Constants.java:45,47,49`；`DefaultTPSLimiter.java:47` |
| `ExecuteLimitFilter` | `ExecuteLimitFilter.java:40` | **PROVIDER** | `executes` | **`0`**（0 = 不限制） | `ExecuteLimitFilter.java:49` |
| `ActiveLimitFilter` | `ActiveLimitFilter.java:45` | **CONSUMER** | `actives` | **`0`** | `ActiveLimitFilter.java:54` |

TPS 相关常量的**字面量**必须记准——它不叫 `tps.limit`，也不叫 `tps.limit.rate`：

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/Constants.java
String TPS_LIMIT_RATE_KEY     = "tps";           // :45
String TPS_LIMIT_INTERVAL_KEY = "tps.interval";  // :47
long   DEFAULT_TPS_LIMIT_INTERVAL = 60 * 1000;   // :49
```

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/filter/tps/DefaultTPSLimiter.java
int  rate     = url.getMethodParameter(..., TPS_LIMIT_RATE_KEY, -1);                  // :47
long interval = url.getMethodParameter(..., TPS_LIMIT_INTERVAL_KEY, DEFAULT_TPS_LIMIT_INTERVAL); // :48-49
```

> [!WARNING]
> rate 的默认值 `-1` 是**硬编码在 `DefaultTPSLimiter.java:47`** 的，**不存在 `DEFAULT_TPS_LIMIT_RATE` 常量**。同理 `executes` 的 `0` 写在 `ExecuteLimitFilter.java:49`，也没有 `DEFAULT_EXECUTES` 常量。因此「Dubbo 服务端默认限流 N 次/秒」这类说法全部是编的——**不配就是不限制**。

## Thread and Connection Defaults

| 参数 | 默认值 | 源码出处 |
| :--- | :--- | :--- |
| `threads` | `200` | `CommonConstants.java:111`（`DEFAULT_THREADS`） |
| `queues` | `0` | `CommonConstants.java:141`（`DEFAULT_QUEUES`） |
| `iothreads` | `min(availableProcessors + 1, 32)` | `dubbo-remoting/.../remoting/Constants.java:118` |
| `accepts` | `0`（不限制） | `dubbo-remoting/.../remoting/Constants.java:43`；读取处 `AbstractServer.java:62` |
| `threadname` | `Dubbo` | `CommonConstants.java:107` |
| `alive` | `60 * 1000` | `CommonConstants.java:143` |
| `connections` | 运行时默认 `0`（**无 `DEFAULT_CONNECTIONS` 常量**） | `DubboProtocol.java:453` |

> [!WARNING]
> **关于 `threadpool` 的默认值有两个答案，别写错那个。** 常量 `CommonConstants.DEFAULT_THREADPOOL` 的字面量是 **`"limited"`**（`CommonConstants.java:133`），但**生产代码从不引用它**（只在 `PerformanceServerTest.java:78` 里被用到），真正生效的默认是 SPI 注解：
>
> ```java
> // dubbo-common/src/main/java/org/apache/dubbo/common/threadpool/ThreadPool.java:29
> @SPI(value = "fixed", scope = ExtensionScope.FRAMEWORK)
> ```
>
> 即：**运行默认确实是 `fixed`**，但写成「`DEFAULT_THREADPOOL = fixed`」就错了。另外注意 `accepts` / `iothreads` 在 `dubbo-remoting` 的 `Constants`，不在 `CommonConstants`。

四种线程池实现（`fixed` / `cached` / `limited` / `eager`）的行为差异、`queues` 的三态语义、Consumer 侧默认走 `cached` 的原因见 [ThreadPool](/docs/CS/Framework/Dubbo/ThreadPool.md)。

## Access Log

`AccessLogFilter` 存在且默认激活（`@Activate(group = PROVIDER)`，`AccessLogFilter.java:72`），但它的**默认行为是不落文件的**——这是 3.x 做的安全加固，与 2.x 的笔记容易冲突：

```java
// AccessLogFilter.java:107-121
String accessLogKey = invoker.getUrl().getParameter(Constants.ACCESS_LOG_KEY);
boolean isFixedPath = invoker.getUrl().getParameter(ACCESS_LOG_FIXED_PATH_KEY, true);  // 默认 true
if (StringUtils.isEmpty(accessLogKey) || "false".equalsIgnoreCase(accessLogKey)) {
    return invoker.invoke(inv);   // 取消定时任务，直接透传
}
```

输出方式判定（`:178-206`）：

- `accesslog` 未配 → **Filter 完全不做事**
- `accesslog="true"` / `"default"` → 走 logger，logger 名为 `dubbo.accesslog.<ServiceName>`（`:241`）
- `accesslog="<path>"` 且 **`accesslog.fixed.path=false`** → 才真正写文件；`fixed.path` 默认 `true`，此时会打 `VULNERABILITY_WARNING` 并**退回 logger**（`:184-192`）

刷新周期为 5000ms（`LOG_OUTPUT_INTERVAL:81`），缓冲区上限 5000 条（`LOG_MAX_BUFFER:79`）。相关常量：`ACCESS_LOG_KEY = "accesslog"`（`rpc/Constants.java:63`）、`ACCESS_LOG_FIXED_PATH_KEY = "accesslog.fixed.path"`（`:65`）。

## Echo and Generic

- **`$echo` 不是「暴露一个 EchoService 服务」**，而是 `EchoFilter` 在链首拦截方法名为 `$echo` 的调用并直接回参（`EchoFilter.java:36-42`）：

  ```java
  public Result invoke(Invoker<?> invoker, Invocation inv) throws RpcException {
      if (inv.getMethodName().equals($ECHO) && inv.getArguments() != null && inv.getArguments().length == 1) {
          return AsyncRpcResult.newDefaultAsyncResult(inv.getArguments()[0], inv);
      }
      return invoker.invoke(inv);
  }
  ```

  常量 `$ECHO = "$echo"` 在 `rpc/Constants.java:28`，配套 `$ECHO_PARAMETER_DESC = "Ljava/lang/Object;"`（`:29`）。order `-110000` 保证它在极靠前的位置。

- **泛化调用的服务端实现是 `GenericFilter`**（`Filter:2`，`@Activate(group = PROVIDER, order = -20000)`）；消费侧对应的是 `GenericImplFilter`（`Filter:3`，`@Activate(group = CONSUMER, value = GENERIC_KEY, order = 20000)`）。泛化调用的 API 与序列化细节见 [Invocation](/docs/CS/Framework/Dubbo/Invocation.md)。

## Default Value Summary Table

| 项 | 默认值 | 出处 |
| :--- | :--- | :--- |
| ProxyFactory | `javassist` | `ProxyFactory.java:29` |
| threadpool | 运行默认 `fixed`（`DEFAULT_THREADPOOL` 常量字面量是 `limited`，死常量） | `ThreadPool.java:29` / `CommonConstants.java:133` |
| threads | `200` | `CommonConstants.java:111` |
| queues | `0` | `CommonConstants.java:141` |
| iothreads | `min(cpus + 1, 32)` | `remoting/Constants.java:118` |
| accepts | `0` | `remoting/Constants.java:43` |
| executes | `0`（不限制） | `ExecuteLimitFilter.java:49` |
| tps（rate） | `-1`（不限制） | `DefaultTPSLimiter.java:47` |
| tps.interval | `60000` | `rpc/Constants.java:49` |
| warmup | `10 * 60 * 1000` | `rpc/cluster/Constants.java:99` |
| weight | `100` | `rpc/cluster/Constants.java:29` |
| delay | `null`（不延迟） | `ServiceConfigBase.java:138-146` |
| accesslog | 未配（Filter 不做事） | `AccessLogFilter.java:110-121` |

## Exporter Management

Provider 暴露出的每个 `Invoker` 都会被包成一个 `Exporter`，并由协议层集中管理。容器是 `AbstractProtocol` 持有的一个 `ConcurrentHashMap`：

```java
// dubbo-rpc/dubbo-rpc-api/.../rpc/protocol/AbstractProtocol.java:60
protected final Map<String, Exporter<?>> exporterMap = new ConcurrentHashMap<>();
```

`DubboProtocol.export()`（`DubboProtocol.java:336-365`）以 `serviceKey(url)` 为 key 构造 `DubboExporter`，并在其构造器里 `put` 进 `exporterMap`（`DubboExporter.java:38`）：

```java
// DubboProtocol.java:341-342
String key = serviceKey(url);
DubboExporter<T> exporter = new DubboExporter<>(invoker, key, exporterMap);
```

请求到来时，服务端处理器用同样的 `serviceKey` 反查 `Exporter` → `Invoker`（`DubboProtocol.java:310-315`）：

```java
DubboExporter<?> exporter = (DubboExporter<?>) exporterMap.get(serviceKey);
if (exporter == null) {
    throw new RemotingException(... "Not found exported service: " + serviceKey
            + " in " + exporterMap.keySet() + ", may be version or group mismatch ...");
}
```

也就是说：**`version` / `group` 不匹配的调用在查 `exporterMap` 阶段就直接失败**，根本进不了 Filter 链。该 map 同时支撑优雅停机与状态查询——`AbstractProtocol.unexport()` 遍历它逐个 `exporter.unexport()` 后 `clear()`（`:120-132`），`getExporters()` 返回其不可修改视图（`:144-148`）。

> [!NOTE]
> `exporterMap` 是 `protected final`，由 `AbstractProtocol` 统一管理，所有具体协议（`dubbo` / `tri` / `injvm`）共享同一套生命周期语义；`DubboExporter` 只在构造 / 销毁时读写它（`DubboExporter.java:34-43`），自身不持有并发逻辑。

## Pitfall List

- **把 `actives` 当服务端并发控制**——它是 Consumer 侧，服务端用 `executes`。
- **以为 Provider 有 `retries`**——没有。
- **按 SPI 文件数 Filter 数量**——`CompatibleFilter` 无 `@Activate` 不生效，且其它模块还有各自的 Filter SPI 文件。
- **以为 `ExporterListener` 有内置实现**——生产 resources 里没有 SPI 文件，用 `ServiceListener`。
- **写 `DEFAULT_THREADPOOL = fixed`**——字面量是 `limited` 但那是死常量，运行默认来自 `@SPI("fixed")`。
- **配了 `accesslog` 却发现没文件**——`accesslog.fixed.path` 默认 `true`，必须显式设为 `false` 才写文件。
- **写 `tps.limit` 作为 TPS 配置键**——正确键名就是 `tps`。
- **以为 `accepts` / `iothreads` 在 `CommonConstants`**——它们在 `dubbo-remoting` 的 `Constants`。
- **以为 `ProtocolFilterWrapper` 还在 `dubbo-rpc-api`**——3.3.6 已迁 `dubbo-cluster`（`org.apache.dubbo.rpc.cluster.filter`），`buildInvokerChain` 拆到 `DefaultFilterChainBuilder`。
- **以为 `AsyncRpcResult` 在 `reply` 里创建**——它在 `AbstractProxyInvoker.invoke`（`:117`）创建，`reply` 只把它转成 `CompletableFuture`。
- **以为 Provider 注册会把自身写成 override/configurator**——3.x 只注册自身（`category=providers` 由注册中心实现层拼），override 动态配置改走配置中心（`GovernanceRuleRepository`）。
- **以为有 `makeInvoker` / `JavassistWrapper`**——不存在，服务端代理走 `JavassistProxyFactory.getInvoker` → `AbstractProxyInvoker` → `Wrapper.invokeMethod`。

## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [Consumer](/docs/CS/Framework/Dubbo/Consumer.md)
- [Start](/docs/CS/Framework/Dubbo/Start.md)
- [ThreadPool](/docs/CS/Framework/Dubbo/ThreadPool.md)
- [Filter](/docs/CS/Framework/Dubbo/Filter.md)
- [ServiceConfig](/docs/CS/Framework/Dubbo/ServiceConfig.md)

## References

- <https://github.com/apache/dubbo/tree/dubbo-3.3.6>
- <https://cn.dubbo.apache.org/zh-cn/overview/mannual/java-sdk/reference-manual/filter/>
