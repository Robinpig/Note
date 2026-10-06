## Introduction

Jetty 12.1 的资源保护不是单点开关，而是一张**分层清单**：请求从内核 accept 队列到业务 Handler 之间要穿过四个层次，每层有独立的开关，关掉某一层不等于其他层不存在。本文按层梳理 12.1.14 源码中的每一个保护类，全部结论带源码路径与行号。

| 阶段 | 工具 | 保护对象 | 所在模块 |
| :--- | :--- | :--- | :--- |
| accept 之前 | `AcceptRateLimit` | 新建连接的速率 | `jetty-server` |
| accept 之前 | `ConnectionLimit` / `NetworkConnectionLimit` | 并发连接总数 | `jetty-server` |
| 连接已建 | `LowResourceMonitor` | 空闲连接占用的 fd 与内存 | `jetty-server` |
| 请求已解析 | `SizeLimitHandler` / `MinimumDataRateHandler` | 请求/响应的体量与数据速率 | `jetty-server` |
| 处理中 | `DoSHandler` / `ThreadLimitHandler` / `QoSHandler` | 单客户端速率、并发线程、调度优先级 | `jetty-server` |
| 观测面 | `ConnectionStatistics` / `StatisticsHandler` | 连接层 / 请求层指标 | `jetty-io` / `jetty-server` |

accept 层的三个类共享同一个回调契约：`SelectorManager.AcceptListener`（io/SelectorManager.java:559-598 定义 `onAccepting` / `onAcceptFailed` / `onAccepted` / `onClosed` 四个回调），挂载方式是把实例 `addBean` 到 `Server`（作用于全部 Connector）或 `Connector` 上。

## Accept Layer Limits

三个 accept 层工具的触发时机都在连接被正式注册进 selector 之前——这是整条链路上**最早**能拒绝工作的地方，拒绝一个 TCP 连接的成本远低于解析一个 HTTP 请求。

### AcceptRateLimit

限制**新建连接的速率**（每单位时间 accept 多少个），实现为一个周期任务加监听器：

```java
// jetty-server-12.1.14/org/eclipse/jetty/server/AcceptRateLimit.java:59
public class AcceptRateLimit extends AbstractLifeCycle implements SelectorManager.AcceptListener, Runnable
```

构造时传入速率、周期与作用范围（jetty-server-12.1.14/org/eclipse/jetty/server/AcceptRateLimit.java:71-78）：

```java
public AcceptRateLimit(@Name("acceptRateLimit") int acceptRateLimit, @Name("period") long period,
                       @Name("units") TimeUnit units, @Name("server") Server server)
// ...
public AcceptRateLimit(@Name("limit") int limit, @Name("period") long period,
                       @Name("units") TimeUnit units, @Name("connectors") Connector... connectors)
```

每次 `onAccepting` 计算当前窗口内的 accept 速率（:201-208），超过阈值就停摆 accept（:186-187），窗口回落后再恢复（:195-196）：

```java
c.setAccepting(false);   // :186-187  limit(): 停止接受新连接
// ...
c.setAccepting(true);    // :195-196  unlimit(): 恢复接受
```

注意它限的是**瞬时新建速率**，不是总量——适合挡突发握手洪峰，不适合挡慢速占坑。

### ConnectionLimit

限制**并发连接总数**，同时实现 `Connection.Listener`（计数已建立的连接）与 `SelectorManager.AcceptListener`（计数 accept 中的连接）：

```java
// jetty-server-12.1.14/org/eclipse/jetty/server/ConnectionLimit.java:63
extends AbstractLifeCycle implements Listener, SelectorManager.AcceptListener
```

核心判定把「正在 accept 的」与「已建立的」加在一起与上限比较（jetty-server-12.1.14/org/eclipse/jetty/server/ConnectionLimit.java:193-202）：

```java
int total = _accepting + _connections;
if (total >= _maxConnections)
{
    // ...
    _limiting = true;
    LOG.info("Connection limit {} reached for {}", _maxConnections, _connectors);
    limit();
}
return total > _maxConnections;
```

字段 `_maxConnections` 定义在 :72，构造函数接受 `Server`（全局）或若干 `Connector`（:76-85）。`onAccepting`（:249）与 `onOpened`/`onClosed`（Connection.Listener 回调，:279/:292）都会触发 `check()`，返回 true 时新连接被直接关闭。到达上限时同样通过 `setAccepting(false)` 停止 accept，回落时 `unlimit()`（:208-210）。

### NetworkConnectionLimit

与 `ConnectionLimit` 的差别在**计数口径**：它只实现 `AcceptListener`，按物理网络连接（socket channel）计数，不随协议升级而抖动（jetty-server-12.1.14/org/eclipse/jetty/server/NetworkConnectionLimit.java:55，字段 `_maxNetworkConnections` :64）。javadoc 把行为讲得很完整（:32-42）：

```java
 * <p>This listener applies a limit to the number of network connections, which when
 * exceeded results in a call to {@link AbstractConnector#setAccepting(boolean)}
 * to prevent further network connections to be accepted.</p>
// ...
 * <p>When the number of network connections is exceeded, the idle timeout of existing
 * {@code EndPoint}s is changed to the value configured in this listener (typically
 * a shorter value).</p>
```

也就是说它是 `ConnectionLimit` 的加强版：超限除了停 accept，还会把现存 EndPoint 的 idle timeout 收缩到 `_endPointIdleTimeout`（:65，`setEndPointIdleTimeout` :104，小于等于 0 表示不改），回落后再恢复。WebSocket 这类升级场景里 `Connection` 对象会被替换，按 `Connection` 计数会抖动，按网络连接计数则不受影响——两者按需选一。

### Contrast With Tomcat maxConnections

Tomcat 把并发连接数做成连接器的单一属性 `maxConnections`，由 `LimitLatch` 实现，Acceptor 线程在达到上限时阻塞等待而不是停摆（机制对照见 [Tomcat Connector](/docs/CS/Framework/Tomcat/Connector.md)）。Jetty 12.1 把这件事拆成了三个可独立启用的类：`AcceptRateLimit`（速率）、`ConnectionLimit`（连接对象计数）、`NetworkConnectionLimit`（网络连接计数 + idle timeout 联动）。Tomcat 是「阻塞在闸门前」，Jetty 是「关闸 + 联动收缩」，语义差异在过载时的行为：Tomcat 的 accept 线程会被占住，Jetty 的 selector 线程不被阻塞。

## Idle Timeout Protection With LowResourceMonitor

`LowResourceMonitor` 是唯一一个**周期性体检**式的工具：它不设硬上限，而是在检测到「线程池低水位」等低资源状态时，主动收缩空闲连接的存活时间，快速释放 fd 与内存（jetty-server-12.1.14/org/eclipse/jetty/server/LowResourceMonitor.java:47）。

关键参数（均为默认值）：

- `_period = 1000`（:55）——每 1000ms 检测一轮；
- `_lowResourcesIdleTimeout = 1000`（:57）——进入低资源态后，EndPoint 的 idle timeout 被收缩到 1000ms；
- `_maxLowResourcesTime = 0`（:58）——0 表示允许无限期停留在低资源态；
- `_acceptingInLowResources = true`（:65）——默认低资源期间仍接受新连接。

生效路径是把收缩值写到每个 EndPoint 上（jetty-server-12.1.14/org/eclipse/jetty/server/LowResourceMonitor.java:366）：

```java
endPoint.setIdleTimeout(_lowResourcesIdleTimeout);
```

退出条件有两个：资源恢复检测通过，或 `_maxLowResourcesTime` 设了正值且低资源态持续超时。默认 `_maxLowResourcesTime = 0` 意味着「是否退出完全信任检测逻辑」——若线程池的 low resources 判定失灵（比如任务长期占满），超时收缩会一直生效。

与 accept 层工具的关系：`LowResourceMonitor` 管「让存量连接死得快一点」，`ConnectionLimit` 管「增量连接进不来」。过载时两者互补而非二选一。

## Request Level Handlers

连接进来了、请求解析了，接下来是对**请求本身**的保护。以下五个 Handler 全部位于 `jetty-server-12.1.14/org/eclipse/jetty/server/handler/`，已逐一核实存在。

### SizeLimitHandler

最直白的体量闸门：限制请求头、请求体与响应体大小，超出即以 413 拒绝（javadoc 明确提到 `PAYLOAD_TOO_LARGE_413`，handler/SizeLimitHandler.java:38；类声明 :40 `extends Handler.Wrapper`）。它不统计速率、不做客户端识别，纯粹按字节数，因此也最便宜，适合放在链路最外层。

### MinimumDataRateHandler

防 slowloris / slow-read 客户端：读或写的数据速率低于设定值时，让后续读写**立即失败**。类声明与构造（handler/MinimumDataRateHandler.java:33-43）：

```java
public class MinimumDataRateHandler extends StatisticsHandler
{
    private final long _minimumReadRate;
    private final long _minimumWriteRate;
    // ...
    public MinimumDataRateHandler(long minimumReadRate, long minimumWriteRate)
```

注意它继承自 `StatisticsHandler`——装上它顺带也获得了请求统计能力。读路径按「首次 demand 到当前累计字节数」计算速率，低于下限即失败（:103-105）：

```java
long rate = dataRatePerSecond(_firstDemandNanoTime, read);
if (rate < _minimumReadRate)
{
    // ... fail
```

写路径的处理更精细：不是每块立即判死，而是按「期望速率」给写操作设一个最长完成时限，超时才失败（:168-169）：

```java
long maxWriteDuration = length * 1_000_000_000L / _minimumWriteRate;
Scheduler.Task task = getRequest().getComponents().getScheduler().schedule(() -> fail(original), maxWriteDuration, TimeUnit.NANOSECONDS);
```

失败动作是往请求上挂错误内容并让 callback 失败（:181-182）：

```java
getRequest()._errorContent = Content.Chunk.from(cause);
callback.failed(cause);
```

它的历史背景：旧的等价配置是 `HttpConfiguration.setMinRequestDataRate`，12.1.11 起废弃、指向本 Handler（jetty-server-12.1.14/org/eclipse/jetty/server/HttpConfiguration.java:641-655）：

```java
 * @deprecated use {@link org.eclipse.jetty.server.handler.MinimumDataRateHandler} instead
// ...
@Deprecated(since = "12.1.11", forRemoval = true)
public void setMinRequestDataRate(long bytesPerSecond)
```

迁移时的一个巧合别名：`StatisticsHandler` 内部还留有一个同名嵌套类 `StatisticsHandler.MinimumDataRateHandler`，同样 `@Deprecated(since = "12.1.11", forRemoval = true)`，只是继承到新类上的过渡壳（handler/StatisticsHandler.java:313-314）。

### DoSHandler

按客户端维度的**请求速率**保护，12.1.14 中确实存在于 handler/DoSHandler.java:51-52：

```java
@ManagedObject("DoS Prevention Handler")
public class DoSHandler extends ConditionalHandler.ElseNext
```

它的两态语义由 `ConditionalHandler.ElseNext` 的结构天然表达：条件命中（该客户端当前被判定超速）时走本 Handler 的拒绝分支，请求不再进入下游；未命中则 `else next` 放行到下一个 Handler。也就是说超速客户端在时间窗内的后续请求得到的是统一的快速拒绝，而不是继续占用解析与处理资源；客户端识别与阈值经构造参数注入。挂在 [EE Layer](/docs/CS/Framework/Jetty/EeLayer.md) 之外还是之内是部署时的关键决策（见 Common Pitfalls）。

### ThreadLimitHandler

按远端 IP 限制**并发线程数**，javadoc 开宗明义（handler/ThreadLimitHandler.java:49）：

```java
 * <p>Handler to limit the number of concurrent threads per remote IP address, for DOS protection.</p>
```

实现为每客户端一张记录表加默认 10 的并发上限（:66 类声明 `extends ConditionalHandler.Abstract`，:72-74）：

```java
private final ConcurrentHashMap<String, Remote> _remotes = new ConcurrentHashMap<>();
// ...
private int _threadLimit = 10;
```

与 `DoSHandler` 的分工：DoS 限**速率**（单位时间多少个请求），ThreadLimit 限**并发**（同时压在线程池上多少个）。低速但并发的慢请求（每个都慢、但总数不多）恰好落在 DoS 的盲区、ThreadLimit 的打击面上。

### QoSHandler

前四个工具都是「拒绝」，`QoSHandler` 是唯一「排队」的：线程池枯竭时，低优先级请求被挂起（suspend），不转发给子 Handler，存入按优先级组织的队列；一个正在处理的请求完成时，恢复当前最高优先级的挂起请求（javadoc :52-64，类声明 handler/QoSHandler.java:79 `extends ConditionalHandler.Abstract`）：

```java
 * If more requests are received, they are suspended (that is, not
 * forwarded to the child {@code Handler}) and stored in a priority
// ...
 * <p>When a request that is being processed completes, the suspended
 * request that current has the highest priority is resumed.</p>
```

两个必须显式考虑的参数：`maxSuspendedRequests` 默认 1024（:95），达到上限后新请求直接失败而不是无限排队；`maxSuspend` 默认 `Duration.ZERO` 即**永久挂起**（:96、:173），生产上几乎一定要设一个有限值——过期请求会被重新处理并以 reject 状态完成（:316-317）。优先级由子类覆写 `getPriority(Request)` 决定，0 为最低（:382-389）。

## Statistics Surface

保护机制生效的前提是看得见过载，Jetty 把观测面也拆成两层：

- **连接层**：`ConnectionStatistics` 挂在 `Connection.Listener` 上统计连接的开闭、时长与吞吐（jetty-io-12.1.14/org/eclipse/jetty/io/ConnectionStatistics.java:45-46）：

  ```java
  @ManagedObject("Tracks statistics on connections")
  public class ConnectionStatistics extends AbstractLifeCycle implements Connection.Listener, Dumpable
  ```

- **请求层**：`StatisticsHandler` 统计请求全生命周期的活跃数与延迟分位（handler/StatisticsHandler.java:33 `extends EventsHandler`）。

分工与 [Connector](/docs/CS/Framework/Jetty/Connector.md) 一文中线程池/连接器指标的讨论互补：连接层指标回答「谁把 fd 和内存占满了」，请求层指标回答「线程池为什么忙」。给 `ConnectionLimit` 调阈值之前先看 `ConnectionStatistics` 的连接时长分布，给 `QoSHandler` 定优先级之前先看请求层分位延迟。

## Recommended Combination

嵌入式部署（`Server` + Handler 链）从外到内的推荐顺序：

1. **`LowResourceMonitor`** 挂到 `Server`：始终启用，作为「资源水位 → 快速回收」的自愈层，`maxLowResourcesTime` 设有限值防检测失灵。
2. **`ConnectionLimit`（或 `NetworkConnectionLimit`）**：并发连接硬上限，选哪个取决于是否存在连接升级场景。
3. **`SizeLimitHandler`**：链路最外层的体量闸门，无状态、最便宜。
4. **`MinimumDataRateHandler`**：体量之后立刻限数据速率，slowloris 在此出局。
5. **`DoSHandler`**：按客户端速率拉黑，放在识别维度可用的最早位置。
6. **`ThreadLimitHandler`**：按 IP 限并发，挡住速率不高但并发放大的客户端。
7. **Security（EE 层）**：认证授权（见 [EE Layer](/docs/CS/Framework/Jetty/EeLayer.md)）。
8. **`QoSHandler`** 包住昂贵业务 Handler：只让通过全部廉价检查的请求进入排队，优先级队列本身也有容量上限。

排序理由：越靠外越便宜且越全局（无状态 → 有状态），昂贵的认证与业务只在通过全部前置闸门后才被执行。`QoSHandler` 放在 Security 之后还有个好处：`getPriority` 可以读到认证结果，按用户身份分级。

## Common Pitfalls

- **`LowResourceMonitor` 的周期与 idle timeout 相互作用**：`_period = 1000` 决定进入低资源态的检测滞后（最坏 1s）；一旦收缩生效，idle 间隔小于 `_lowResourcesIdleTimeout` 的 keep-alive 连接会被**误杀**——若把它设得比正常客户端的请求间隔还小，低资源期间正常用户也会被断连。反过来 `_maxLowResourcesTime = 0` 的默认值在检测逻辑失灵时会让收缩无限期生效，务必设上限。
- **`ConnectionLimit` 与 `maxConnections` 的命名混淆**：从 Tomcat 迁移过来最容易写错——Tomcat 的 `maxConnections` 是连接器属性（见 [Tomcat Connector](/docs/CS/Framework/Tomcat/Connector.md)），Jetty 里对应的是独立的 `ConnectionLimit` 类；且 Jetty 还有第二个同名近亲 `NetworkConnectionLimit`，两者计数口径不同（`Connection` 对象 vs 网络连接），连接升级场景下数字会分叉。另外不要把它和 `LowResourceMonitor` 混为一谈：前者是硬上限，后者是软性收缩。
- **限流 Handler 的顺序敏感**：`ConditionalHandler` 系列只看请求进入自己那一刻的状态。`DoSHandler`/`ThreadLimitHandler` 放在 Security 之前，识别维度只能用地址类信息，无法按认证身份限流；`SizeLimitHandler` 放在 gzip/缓冲类 Handler 之内会改变它测量的字节数；`QoSHandler` 放最外层则连静态资源的快速请求都占挂起槽位。调整顺序后挂起队列、拉黑表、计数器的口径都会变，不是可随意重排的中间件。这一点与 Tomcat 的 Valve 管线同理（管线与顺序的机制见 [Tomcat Valve](/docs/CS/Framework/Tomcat/Valve.md)）。
- **速率类工具限的是不同对象**：`AcceptRateLimit` 限新建连接速率、`DoSHandler` 限请求速率、`MinimumDataRateHandler` 限字节速率——三者阈值单位不同（个/秒、请求/秒、字节/秒），排障时先确认看的是哪个计数器。

## Links

- [Jetty](/docs/CS/Framework/Jetty/Jetty.md)
- [Connector](/docs/CS/Framework/Jetty/Connector.md)
- [Threading](/docs/CS/Framework/Jetty/Threading.md)
- [RequestFlow](/docs/CS/Framework/Jetty/RequestFlow.md)
- [Http2](/docs/CS/Framework/Jetty/Http2.md)

## References

- [Jetty Documentation](https://jetty.org/docs.html)
- [Jetty 12.1.14 javadoc: org.eclipse.jetty.server](https://javadoc.io/doc/org.eclipse.jetty/jetty-server/12.1.14)
- [Jetty source tree (tag jetty-12.1.14)](https://github.com/jetty/jetty.project/tree/jetty-12.1.14/jetty-core/jetty-server/src/main/java/org/eclipse/jetty/server)
