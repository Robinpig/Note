## Introduction

本篇与 [Container](/docs/CS/Framework/Tomcat/Container.md) 是一对：那篇讲容器持有什么、如何递归，这篇讲**每个容器那条 pipeline 是怎么被装配起来的**，以及 `catalina/valves/` 下那些内置 Valve 各自解决什么问题。请求进入 pipeline 之后的执行细节（`CoyoteAdapter.service` → 四层 Valve → `ApplicationFilterChain`）已在 [Connector](/docs/CS/Framework/Tomcat/Connector.md) 展开，此处不重复。

基线 Tomcat 11.0.26，行号相对 `org/apache/catalina/`。概念定义与类图见 [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)。

## Valve and Pipeline contract

`Valve.invoke(Request, Response)` 的 javadoc 是一份真正的契约，它把「允许做什么」写成有序清单，把「禁止做什么」写成绝对禁令（`Valve.java:51-93`）。禁令这一半在扩展 Valve 时最容易踩：

- 不得修改**已经用于决定流向**的请求属性——挂在 Host 或 Context 上的 Valve 改目标虚拟 host 就是这类；
- 不得既生成完整响应又把请求传给 `getNext()`；
- 除非自己负责生成响应或包装了请求，否则不得消费请求输入流；
- `getNext().invoke()` 返回之后，不得再改响应头、不得再对输出流做任何操作。

第 3、4 条合起来解释了为什么「包一层 `HttpServletRequestWrapper` 再往下传」是合法写法，而在 Valve 里事后补写 header 不生效（响应多半已提交）。`Valve` 还必须提供 `backgroundProcess()`（`Valve.java:47`），它由容器树的周期任务逐个调用，见 Container 篇。

`ValveBase` 是绝大多数实现的基类，四件事值得记住（`valves/ValveBase.java:35-128`）：

| 成员 | 语义 | 位置 |
| :--- | :--- | :--- |
| `asyncSupported` | 构造参数决定；**无参构造默认 false** | `:48-60`、`:104-106` |
| `container` / `containerLog` | 由 pipeline 通过 `Contained.setContainer()` 注入 | `:74-80`、`:98-100` |
| `next` | 链指针，`getNext()` / `setNext()` | `:86`、`:120-128` |
| `backgroundProcess()` | 默认 NO-OP | `:138-141` |

`initInternal()` 要求此时 `container` 已经注入，否则直接 `IllegalStateException`（`:145-152`）——这是「Valve 必须先被 addValve 再被 init」这条隐含顺序的来源。JMX ObjectName 形如 `type=Valve,<容器层级>,name=类简名`，同类型重复挂载时用 `seq=N` 区分（`:190-233`）。

## StandardPipeline assembly semantics

`StandardPipeline` 只有三个字段（`core/StandardPipeline.java:84-96`）：`basic`、`container`、`first`。链表里**不存** `basic`，它只是最后一个节点的 `next` 指向：

```java
        // Add this Valve to the set associated with this Pipeline
        if (first == null) {
            first = valve;
            valve.setNext(basic);
        } else {
            Valve current = first;
            while (current != null) {
                if (current.getNext() == basic) {
                    current.setNext(valve);
                    valve.setNext(basic);
                    break;
                }
                current = current.getNext();
            }
        }
```

由此得到三条结论，都不依赖配置文档：

1. `addValve()` **总是插到 basic 之前**，多个普通 Valve 按调用顺序（即 server.xml 中的书写顺序）串联（`:267-304`）。
2. 没有「插到最前面」的 API。11.0.26 里既不存在 `addValveFirst`，也没有任何包私有的前插入口；想排到前面只能靠配置顺序，或在 `setBasic()` 之后重新 addValve。
3. `getFirst()` 在没有任何普通 Valve 时返回 `basic`（`:402-408`），所以 `pipeline.getFirst().invoke(...)` 永远不需要判空——但也意味着空 pipeline 的请求会直接被 basic 处理掉。

`setBasic()` 不是简单赋值：它把新 Valve 接到旧 basic 的前驱上，从而**保持 basic 恒在链尾**（`:252-262`）。`removeValve()` 反过来处理头节点与 `first == basic` 的收敛（`:348-373`），并明确注释「移除 basic 只能靠 `setBasic()` 替换」。加不进或移除后的清理走 `cleanupValve()`：解绑 container、stop、destroy（`:379-398`）——`addValve` 时 Valve 自身 start 失败就会走这条路，表现为「配置写了但 pipeline 里没有，日志里一条 start 错误」。

装配过程**没有并发保护**，类注释直接警告不能在请求处理期间 addValve/removeValve（`:42-45`）。`ContainerBase.addValve()` 是 `synchronized` 的，但那只是给 Digester 用的便利方法（`core/ContainerBase.java:918-921`）；`getPipeline().addValve()` 本身无锁。

## Pipeline lifecycle

`StandardPipeline` 继承 `LifecycleBase`，但它的 `initInternal()` 是 NO-OP（`core/StandardPipeline.java:140-142`）——Valve 的初始化不在这里。`addValve()` 的三步顺序是 **先 `setContainer()`，再在 pipeline 已可用时 `start()`，最后才改链**（`:270-303`），而 `start()` 对处于 NEW 状态的对象会先补跑 `init()`（`util/LifecycleBase.java:159-161`）。因此 `ValveBase.initInternal()` 里那条 container 非空断言（`valves/ValveBase.java:145-152`）恰好成立——**顺序是设计出来的，不是巧合**，任何绕过 `addValve()` 自己拼链的嵌入用法都会踩空。

`startInternal()` 与 `stopInternal()` 都从 `first`（无则 `basic`）沿 `getNext()` 正向遍历（`core/StandardPipeline.java:146-161`、`:164-180`）。**停止不是反序的**，所以别指望「后装的 Valve 先释放资源」这种栈式语义，跨 Valve 的资源依赖必须在各自的 `stopInternal()` 里自己保证。`destroyInternal()` 则把 `getValves()` 的全表逐个 `removeValve()`（`:183-189`）。

## Four basic valves and auto-assembly

四类容器都在**构造函数**里装好 basic valve，不等配置（这是「删掉 server.xml 里所有 Valve 也能跑」的原因）：

| 容器 | basic valve | 位置 | 除委派外还做了什么 |
| :--- | :--- | :--- | :--- |
| Engine | `StandardEngineValve` | `core/StandardEngine.java:60` | Host 为 null 直接 404；把 asyncSupported 与下级 pipeline 求与（`core/StandardEngineValve.java:54-72`） |
| Host | `StandardHostValve` | `core/StandardHost.java:66` | bind/unbind TCCL、fireRequestInit/Destroy 监听器、错误页转发（`core/StandardHostValve.java:78-169`、`:340-394`） |
| Context | `StandardContextValve` | `core/StandardContext.java:157` | 拦 `/WEB-INF`、`/META-INF`，Wrapper 缺失或不可用 → 404，回 100-continue（`core/StandardContextValve.java:54-78`） |
| Wrapper | `StandardWrapperValve` | `core/StandardWrapper.java:85-87` | 可用性检查、`allocate()`、建 filter chain（`core/StandardWrapperValve.java:85-140`） |

四层都是 package-private 的 `final class`，且都以 `super(true)` 构造——它们不破坏 async。

在配置之外，还有三处运行期自动装配：

- **`StandardHost.startInternal()` 会自动补一个 `ErrorReportValve`**（`core/StandardHost.java:767-793`）：先按类名扫描现有 pipeline，没有才 `addValve()`。整棵树里只有 Host 这么干，所以 `errorReportValveClass` 换实现只需在 `<Host>` 上改属性。注意它被插在 `StandardHostValve` **之前**，靠 `getNext().invoke()` 返回后再检查响应状态来渲染默认错误页（`valves/ErrorReportValve.java:83-110`）；它**不参与**自定义错误页，自定义页是 `StandardHostValve.custom()` 用 forward 完成的。
- **Authenticator 是 Context pipeline 里的普通 Valve**：`AuthenticatorBase extends ValveBase`（`authenticator/AuthenticatorBase.java:147` 处以 `super(true)` 构造），`StandardContext.getAuthenticator()` 就是遍历 pipeline 找 `instanceof Authenticator`（`core/StandardContext.java:1262-1275`）。因此认证发生在 URL 映射之后、进入 Wrapper 之前，多个 Valve 的相对顺序由 server.xml / context.xml 的书写顺序唯一决定。
- **`RewriteValve` 会重跑整条链**：改写导致 URI 变化时，它 `mappingData.recycle()` → 重新调 `adapter.prepare(...)`（即重做 postParseRequest 与映射）→ 从 **Engine** pipeline 的 first 再进一次（`valves/rewrite/RewriteValve.java:628-646`）。它用 `ThreadLocal<Boolean> invoked` 做再入守卫，第二次进入时直接放行给 next（`:349-356`）；`[NS]` 类跳过语义靠手动 `next = next.getNext()` 实现（`:650-656`）。

## Built-in Valve taxonomy

`catalina/valves/` 与 `valves/rewrite/` 下的实现按用途分组。「层级」列给的是**有意义的最上挂载点**：越靠上覆盖的请求越多，但拿不到越靠下才确定的信息。

| 类别 | 类 | 解决什么 | 关键字段 默认值 | 层级 |
| :--- | :--- | :--- | :--- | :--- |
| 访问日志 | `AccessLogValve` | 文本访问日志与按日轮转 | `directory=logs`、`prefix=access_log`、`suffix=""`、`rotatable=true`、`buffered=true`、`fileDateFormat=.yyyy-MM-dd`、`maxDays=-1` | 任意 |
| 访问日志 | `ExtendedAccessLogValve` | W3C ELFF 字段语法 | 继承上表，字段名换成 `c-ip`、`cs-method`、`x-R(...)` 等 | 任意 |
| 访问日志 | `JsonAccessLogValve` | 同一套 pattern 直出 JSON | 令牌映射固定（`a→remoteAddr`、`s→statusCode` 等） | 任意 |
| 访问日志 | `JDBCAccessLogValve` | 日志入库 | `connectionURL`、`connectionName`、`driverName`、`tableName`、列名逐字段可配、独享 `resolveHosts` | 任意 |
| 会话治理 | `CrawlerSessionManagerValve` | 爬虫共用一个 session，避免内存被会话池打满 | `crawlerUserAgents`（bot 正则）、`crawlerIps`、`sessionInactiveInterval=60` | Context |
| 协议还原 | `RemoteIpValve` | 反代后还原 client IP / scheme / host | `remoteIpHeader=X-Forwarded-For`、`protocolHeader=X-Forwarded-Proto`、`proxiesHeader=X-Forwarded-By`、`internalProxiesCidr`（RFC1918 + `100.64.0.0/10` 等）、`trustedProxies=null`、`requestAttributesEnabled=true` | Engine / Host |
| 协议还原 | `SSLValve` | `mod_proxy_http` 下补回客户端证书信息 | `sslClientCertHeader=ssl_client_cert`、`sslClientEscapedCertHeader`、`sslSecureProtocolHeader` 等五个头名 | Engine（官方示例即挂在 Engine 下） |
| 并发保护 | `SemaphoreValve` | 限制并发进入某子树的请求数 | `concurrency=10`、`fairness=false`、`block=true`、`interruptible=false`、`highConcurrencyStatus=-1` | 任意，取决于隔离粒度 |
| 并发保护 | `ParameterLimitValve` | 按 URL 收紧解析预算 | `resourcePath=parameter_limit.config`；每行 `正则=maxParameterCount[,maxPartCount[,maxPartHeaderSize]]` | Host / Context |
| 并发保护 | `RequestFilterValve`（及 `RemoteAddrValve` / `RemoteHostValve` / `RemoteCIDRValve`） | 按地址属性 allow/deny | `allow`、`deny`、`denyStatus=403`、`addConnectorPort=false`、`usePeerAddress=false`、`invalidAuthenticationWhenDeny=false` | 任意 |
| 诊断 | `StuckThreadDetectionValve` | 发现并可选中断卡死的请求线程 | `threshold=600`（秒）、`interruptThreadThreshold=-1` | 任意 |
| 诊断 | `FilterValve` | 把任意 `jakarta.servlet.Filter` 当 Valve 用 | `className`；禁止包装 request/response | 任意 |
| 摘流 | `LoadBalancerDrainingValve` | 节点被 LB 置 DIS 后把无有效会话的请求踢回 LB | `redirectStatusCode=307`、`ignoreCookieName`、`ignoreCookieValue` | Host / Context |
| 健康检查 | `HealthCheckValve` | 给 LB / 探针一个 `/health` | `path=/health`、`checkContainersAvailable=true`（递归判断整棵子树） | 任意 |
| 错误呈现 | `ErrorReportValve` / `JsonErrorReportValve` / `ProxyErrorReportValve` | 默认错误页 / JSON 错误体 / 代理到静态错误页 | `showReport=true`、`showServerInfo=true` | Host（自动装配） |
| 会话持久 | `PersistentValve` | 非粘滞 LB + `PersistentManager` 的按请求加载/保存 | `filter`、`semaphoreFairness=true`、`semaphoreBlockOnAcquire=true`、`semaphoreAcquireUninterruptibly=true` | Context 语义，允许挂 Host / Engine |

上表只覆盖 `catalina/valves/` 包。集群模块（catalina-ha）另有两颗同样走 Valve 契约的实现：`ReplicationValve`（复制触发器）与 `JvmRouteBinderValve`（failover 后改写 session id 的 jvmRoute 后缀），它们的挂载位置与复制时序见 [Cluster](/docs/CS/Framework/Tomcat/Cluster.md)。错误呈现一族的输出细节（`showServerInfo` 的信息泄露面、`ERROR_*` attributes 的设置点、哪些状态码会断 keep-alive）单独成篇，见 [ErrorPage](/docs/CS/Framework/Tomcat/ErrorPage.md)。

几处需要额外解释的判断：

**访问日志不是「链上打点」。** 这四个实现都走 `AbstractAccessLogValve`，其 `invoke()` 只做两件事：需要 TLS 属性时提前取一次（防 NIO2 断连后丢失）、把 pattern 元素 `cache(request)`，然后交给 next（`valves/AbstractAccessLogValve.java:768-781`）。真正写日志的 `log(request, response, time)` 由 `CoyoteAdapter` 收尾时通过 `Container.logAccess()` 触发（`connector/CoyoteAdapter.java:392-414`），`ContainerBase.logAccess()` 再沿父级回溯（`core/ContainerBase.java:862-876`）。所以：

- 挂在 Engine 的 `AccessLogValve` 连「映射不到 Context」的请求都会记，因为 `StandardEngine` 兜底会去找默认 Host 与 ROOT 的 accessLog（`core/StandardEngine.java:212-264`）；
- `ContainerBase.getAccessLog()` 会把本容器 pipeline 里所有 `AccessLog` 实例合并进一个 `AccessLogAdapter`（`core/ContainerBase.java:879-901`），一条请求可以被两个不同格式的日志同时记；
- **一次扫描后不再重扫**（`accessLogScanComplete`，`:881-883`）：启动后才 `addValve` 一个 AccessLogValve，它对访问日志是透明的。

**`RemoteIpValve` 的改写是「作用域」而非「永久」。** 它在 `getNext().invoke()` 的 `finally` 里把 remoteAddr、remoteHost、secure、scheme、serverName、serverPort 以及两个转发头**全部还原成代理带来的原始值**（`valves/RemoteIpValve.java:733-758`）。下游链路（含应用）看到的是真实 client，但 pipeline 返回之后、也就是访问日志落笔时，`request.getRemoteAddr()` 又是代理地址。真实 client 之所以还能进日志，全靠还原前写入的六个属性：`AccessLog.REMOTE_ADDR_ATTRIBUTE` 等，前提是 `requestAttributesEnabled=true` 且日志侧也开启属性读取（`:726-731`）。这条链给出了一个硬性的顺序要求：**`RemoteIpValve` 必须排在 `AccessLogValve` 之前**。

**`HealthCheckValve` 的 path 语义随层级漂移。** 挂在 Context 上比较 `requestPathMB`（已剥掉 contextPath），挂在 Engine/Host 上比较完整 URI（`valves/HealthCheckValve.java:103-112`、可用性判定在 `:125-132`）。同一份配置换个层级，探测路径就得跟着改。它的可用性判断是递归的：整棵子树任一容器 not available 就返回 DOWN + 503。

**`SemaphoreValve` 的三个坑集中在这一个类里。** `semaphore` 在 `startInternal()` 里创建（`valves/SemaphoreValve.java:199-202`），改 `concurrency` 必须重启；`highConcurrencyStatus` 默认 -1，配合 `block="false"` 时超阈请求会**静默返回空响应**（`permitDenied()` 只在 `>0` 时 `sendError`，`:289-293`）；它虽 `super(true)` 声明支持 async，但 javadoc 自己提示「一个 async 请求在内部可能是多个串行请求」，permit 的持有范围与直觉不符（`:33-36`）。

**`ParameterLimitValve` 依赖「参数尚未被解析」。** 它按正则命中后调 `request.setMaxParameterCount()` / `setMaxPartCount()` / `setMaxPartHeaderSize()`（`valves/ParameterLimitValve.java:275-296`），而这些值是解析期才读的。`ParameterLimitValve` 与任何会触发参数解析的东西（读 cookie、会话、另一条 Valve 里的 `getParameter`）的相对顺序因此是功能性的，不只是风格问题。它同时支持 `context` 标志切换用 `requestPathMB` 还是完整 URI 匹配（`:282`）。

**`LoadBalancerDrainingValve` 判的是属性而不是集群状态。** 条件是 `"DIS".equals(request.getAttribute("JK_LB_ACTIVATION"))` 且会话 id 无效（`valves/LoadBalancerDrainingValve.java:157-159`），属性由连接器侧写入；命中后清会话 cookie、剥掉 `;jsessionid`、以 307 重定向回 LB（`:196-232`）。它必须排在认证 Valve 之前，否则受保护资源会被先保存再重定向（类注释 `:52-54`）。

**容器文件的解析路径只有一种算法。** `RewriteValve` 与 `ParameterLimitValve` 都用 `Container.getConfigPath(getContainer(), resourcePath)` 定位配置（`valves/rewrite/RewriteValve.java:186`、`valves/ParameterLimitValve.java:156`），实现在 `Container.java:272-295`：沿 `getParent()` 找到 Host 与 Engine，若 Host 配了 `xmlBase` 就用它，否则拼 `conf/<engine>/<host>/`。想给某个虚拟 host 单独一份 `rewrite.config`，改的是 Host 的名字而不是文件位置。

**`FilterValve` 是「用 Valve 模拟链式语义」的反面教材。** 它自己实现 `FilterConfig` 并把 `this` 传给 `filter.init(this)`（`valves/FilterValve.java:172`、`:198-203`），于是 `getFilterName()` 恒为 null（`:135-138`）；挂在 Engine/Host 上时 `getServletContext()` 返回一个只回答「取工具线程池」这一个问题的动态代理，其余方法一律 `UnsupportedOperationException`（`:186-198`）。真正有意思的是续链判定：它用一个内部 `FilterChain` 记录器捕获 `doFilter` 的调用与参数，只有**过滤器确实调用了 `doFilter`** 才 `getNext().invoke()`（`:221-241`）；如果传回的 request/response 被换成了包装对象，直接 `IllegalStateException`（`:232-238`）。一个过滤器 `return` 而不 `chain.doFilter` 在 Valve 位置上的后果是整条 pipeline 就地终止，且不产生任何异常。

**`PersistentValve` 的层级自由度来自一处小设计。** `setContainer()` 只记录 `clBindRequired = container instanceof Engine || container instanceof Host`（`valves/PersistentValve.java:106-109`），挂在这两层时它经私有 `bind()` / `unbind()` 助手在 Session 存取前后切换 TCCL（`:347-359`，调用点 `:263`、`:297`）；它靠**每个 session 一把 `UsageCountingSemaphore`** 串行化同一会话的请求（`:88-94`），拿不到许可时默认 `sendError(429)`，该行为可被覆写 `onSemaphoreNotAcquired()`（`:321-323`）。`filter` 是一个正则（`:86`），命中的 URI 完全绕过会话的加载与保存（`isRequestWithoutSession()`，`:368`）——静态资源必须走这条路，否则每个图片请求都会打一次 Store。类注释同时限定它只能配 `PersistentManager`。

**`StuckThreadDetectionValve` 的检测完全不在 `invoke()` 里。** `threshold <= 0` 时 `invoke()` 直接放行（`valves/StuckThreadDetectionValve.java:169-174`）；正常情况下它只把当前线程与 URI 记进 `activeThreads`，`finally` 里摘除并把「结束时已被判定为 stuck」的线程入队（`:190-203`）。真正的判定在 `backgroundProcess()`（`:207-235`）：遍历在飞线程，活跃时长超过 `threshold` 秒则告警，超过 `interruptThreadThreshold` 秒且该值 > 0 才中断。这给了一个普适结论——**Valve 的观测能力受它所属容器的后台递归覆盖范围约束**（递归规则见 [Container](/docs/CS/Framework/Tomcat/Container.md)）。

**日志的开关与条件是两层。** `enabled` 决定这条 Valve 是否参与（`valves/AbstractAccessLogValve.java:215`），`condition` / `conditionIf` 决定单条请求是否落笔（`:525-531`）——后者读的是 request attribute，因此与上一条 pitfall 同源：**写属性的 Valve 必须排在日志 Valve 之前**。别名 `common` / `combined` 在 `setPattern()` 里就地展开成字面 pattern（`:666-679`），所以运行期看到的 pattern 永远是展开后的串。

## Ordering quick reference

`ContainerBase` 对四层一视同仁，任何一层都能 `addValve()`；Wrapper 级实际很少用，因为那时映射与实例分配已经完成。把上面的机制压成一张表：

| 目的 | 挂载层 | 顺序要求 | 依据 |
| :--- | :--- | :--- | :--- |
| 真实 client IP 进访问日志 | Engine / Host | `RemoteIpValve` 早于 `AccessLogValve` | 属性在改写后写入、原始值在 `finally` 还原 |
| 应用能读到客户端证书 | Engine | `SSLValve` 早于任何读 `CERTIFICATES_ATTR` 的环节 | 先 `setAttribute` 再传链（`valves/SSLValve.java:260-283`） |
| 收紧表单/上传预算 | Host / Context | `ParameterLimitValve` 早于任何触发参数或 multipart 解析的环节 | 限制值在解析时才被读 |
| 会话先被踢回 LB 再认证 | Host / Context | `LoadBalancerDrainingValve` 早于 Authenticator | 类注释明示 |
| 默认错误页 | Host | 无需手工排序 | `StandardHost.startInternal()` 把它 addValve 到 basic 之前 |
| 覆盖「映射不到 Host」的请求 | Engine | 只有 Engine 级做得到 | `StandardEngine.logAccess()` 的兜底链 |
| 健康检查覆盖整棵子树 | Engine / Host | 无顺序要求 | `isAvailable()` 递归 |

## Custom Valve

最小正确写法只有一条硬要求：调用 `getNext().invoke()` 或明确生成响应，二选一，不能都不做。

```java
public class MyValve extends ValveBase {

    public MyValve() {
        super(true);
    }

    @Override
    public void invoke(Request request, Response response) throws IOException, ServletException {
        // 1. 读/改请求，此时下游还没跑
        getNext().invoke(request, response);
        // 2. 只能读响应状态，不能再改 header 或输出流
    }
}
```

踩坑清单，每条都对应上文源码：

1. **忘了 `getNext()`**：请求直接返回，状态 200、响应体空，日志里没有任何异常。basic valve 恒在链尾意味着漏掉的正是下游所有工作。
2. **用无参 `super()`**：`asyncSupported=false` 会沿 `StandardPipeline.isAsyncSupported()` 传染整条链（`core/StandardPipeline.java:102-110`），`CoyoteAdapter` 在进 pipeline 前就把它写进 request（`connector/CoyoteAdapter.java:344`），最终 `startAsync()` 抛 `IllegalStateException`。定位很友好：`Request.getNonAsyncClassNames()` 会从 Wrapper 逐级向上调 `findNonAsyncValves()`，把 Valve 类名打进 warn 日志（`connector/Request.java:1586-1606`）。
3. **异常处理**：Wrapper/Context 层的异常由 `StandardHostValve` 兜住并转成错误页（`core/StandardHostValve.java:113-126`）；Engine/Host 层的 Valve 抛出去就穿透 `CoyoteAdapter.service`（只 catch `IOException`，`:380`），由连接器兜底：置 500、`CLOSE_CLEAN` 关连接、并额外记一次 access log（`http11/Http11Processor.java:432-437`）。想「出错也放行」必须在 Valve 内部自己 catch。
4. **属性时机**：`Globals.DISPATCHER_TYPE_ATTR`、`DISPATCHER_REQUEST_PATH_ATTR` 到 `StandardWrapperValve` 才写入（`core/StandardWrapperValve.java:137-138`）；`request.getWrapper()` 在 `postParseRequest` 之后即已就绪（映射结果，`connector/Request.java:785-787`）；会话在 `parseSessionCookiesId` 后才可用。写 Valve 前先确认要读的东西在哪一层被填上。
5. **热改配置**：运行期 `addValve` / `removeValve` 无锁（`core/StandardPipeline.java:42-45`），且 AccessLog 类 Valve 还受一次性扫描影响（`core/ContainerBase.java:881-883`）。真要动态开关，优先用 `AccessLogValve` 的 `condition` / `enabled`，而不是重排 pipeline。

## Links

- [Container](/docs/CS/Framework/Tomcat/Container.md)
- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)
- [Connector](/docs/CS/Framework/Tomcat/Connector.md)
- [Start](/docs/CS/Framework/Tomcat/Start.md)
- [ClassLoader](/docs/CS/Framework/Tomcat/ClassLoader.md)

## References

1. [Tomcat 11.0 Configuration Reference: Valve](https://tomcat.apache.org/tomcat-11.0-doc/config/valve.html)
2. [Tomcat 11.0 Rewrite Valve (Apache httpd 兼容语法)](https://tomcat.apache.org/tomcat-11.0-doc/rewrite.html)
3. [Tomcat 11.0 Configuration Reference](https://tomcat.apache.org/tomcat-11.0-doc/config/)
4. [Tomcat 11.0 Monitoring (JMX)](https://tomcat.apache.org/tomcat-11.0-doc/monitoring.html)
