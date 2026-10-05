# Jetty Connector 与 accept 路径

## Introduction

Jetty 12 里一个 `Connector` 不是「一个线程」, 而是**两组职责完全不同的任务**: 一组 **acceptor** 只负责把 TCP 连接从监听队列里取出来, 一组 **selector** 负责把新连接注册进多路复用器并驱动后续的读、写、超时。两组任务都**不自建线程**, 全部提交到 `Executor`(通常是 `QueuedThreadPool`)执行, 因此连接器的容量最终被线程池预算(`ThreadPoolBudget`)约束, 而不是被构造参数里的魔法数字约束。

这条链路的源码骨架很短:

```
ServerSocketChannel.accept()            AbstractConnector.Acceptor.run() 循环
   -> ServerConnector.accepted()        非阻塞 + socket 选项 + _manager.accept()
      -> SelectorManager.accept()       挑一个 ManagedSelector, OP_REGISTER
         -> newEndPoint()               SocketChannelEndPoint
            -> ConnectionFactory.newConnection()   HttpConfiguration 决定 HTTP/1.1 还是 h2c
```

与 Tomcat 的最大差异是一句话: Tomcat 的 `NioEndpoint` 把 acceptor、poller、processor 三级线程固化在自己的 `ThreadPoolExecutor` 里, 数量随 CPU 推导; Jetty 的 acceptor 默认**恒为 1** 且只是线程池里的一个任务, 唯一还按 CPU 推导的是 selector 数量。详见 [Tomcat Connector](/docs/CS/Framework/Tomcat/Connector.md)。

所有行号相对 `/tmp/src/tree/`, 基于官方 `-sources.jar` 解压的 Jetty 12.1.14。

## AbstractConnector fields and defaults

| 字段 | 默认值 | 位置 | 说明 |
| :-- | :-- | :-- | :-- |
| `_acceptors` | `Thread[1]` | `AbstractConnector.java:199-204` | 长度即 acceptor 任务数, 数组内容由任务自己回填 |
| `_acceptorPriorityDelta` | `-2` | `AbstractConnector.java:162`, `ServerConnector.java:215` | acceptor 线程相对降低 2 级优先级 |
| `_accepting` | `true` | `AbstractConnector.java:163` | `setAccepting(false)` 是**摘流开关**, 不关监听 socket |
| `_idleTimeout` | `30000` ms | `AbstractConnector.java:156` | 连接级空闲超时下限, 被 `HttpConfiguration` 与 `LowResourceMonitor` 覆盖 |
| `_shutdownIdleTimeout` | `1000` ms | `AbstractConnector.java:157` | 优雅停机时把连接空闲超时压到 1s |
| `_factories` | `LinkedHashMap` | `AbstractConnector.java:147` | **顺序重要**, 决定协议协商链 |
| `_lease` | - | `AbstractConnector.java:321` | `ThreadPoolBudget.Lease`, 向线程池租借 acceptor+selector 线程额度 |
| `_endpoints` | `ConcurrentHashMap` 支撑的 Set | `AbstractConnector.java:153` | 该连接器上所有存活 EndPoint, 停机时逐个关闭 |

构造签名里 `acceptors` 与 `selectors` 都是 `int`, 约定 `-1` 表示「用默认值」, `0` 表示「我不用这套机制」——`0` 的语义在 `ServerConnector` 上有一个重要后果, 见后文。

## History of the acceptor count

12.1.14 的实际推导只有三行:

```java
// jetty-server-12.1.14/org/eclipse/jetty/server/AbstractConnector.java:199-204
int cores = ProcessorUtils.availableProcessors();
if (acceptors < 0)
    acceptors = 1;
if (acceptors > cores)
    LOG.warn("Acceptors should be <= availableProcessors: {} ", this);
_acceptors = new Thread[acceptors];
```

注意 `cores` 在这里**只用于打一条警告日志**, 不参与数量决策。也就是说: `acceptors = -1` 或 `0` 之外的任何负数都得到 1; 8 核机器不会自动变成 8 个 acceptor。

`AbstractConnector` 的类注释给出了理由:

```java
// jetty-server-12.1.14/org/eclipse/jetty/server/AbstractConnector.java:136-138
 * The default number of acceptor tasks is 1. Having more acceptors may reduce the latency for servers that see
 * a high rate of new connections (for example HTTP/1.0 without {@code Connection: keep-alive}).
 * Typically, the default is sufficient for modern protocols (HTTP/1.1, HTTP/2 etc.), that all use persistent connections.
```

> [!IMPORTANT]
> 这是本篇最重要的纠偏点。社区资料里「Jetty acceptor = CPU 推导」的说法来自 9/10/11 时代的实现与文档, 那些版本的具体公式**本篇未逐个核实, 不要照抄**; 在 12.1.14 里能确定的事实是: **acceptor 恒为 1, CPU 数量只剩警告作用**。把 `acceptors` 调到几十不仅无益, 还会挤占同一个 `QueuedThreadPool` 里处理请求的线程。

只有两种场景值得手工调: 高新建连接率且无 keep-alive(短连接压测、老 HTTP/1.0 客户端), 或者接受线程本身成为瓶颈(此时 `accept()` 的阻塞时间被客户端 TLS 握手、`accept` 队列满等因素拉长)。

## Acceptor is an Executor task

启动时 acceptor 并非 `new Thread().start()`, 而是**提交给 Executor**:

```java
// jetty-server-12.1.14/org/eclipse/jetty/server/AbstractConnector.java:321-330
_lease = ThreadPoolBudget.leaseFrom(getExecutor(), this, _acceptors.length);

super.doStart();

for (int i = 0; i < _acceptors.length; i++)
{
    Acceptor a = new Acceptor(i);
    addBean(a);
    getExecutor().execute(a);
}
```

`Acceptor.run()` 在**被池分配到的线程上**改写线程名, 并把这个 `Thread` 存回数组, 以便停机时能 `interrupt`:

```java
// jetty-server-12.1.14/org/eclipse/jetty/server/AbstractConnector.java:678-691
public void run()
{
    final Thread thread = Thread.currentThread();
    String name = thread.getName();
    _name = String.format("%s-acceptor-%d@%x-%s", name, _id, hashCode(), AbstractConnector.this.toString());
    thread.setName(_name);

    int priority = thread.getPriority();
    if (_acceptorPriorityDelta != 0)
        thread.setPriority(Math.max(Thread.MIN_PRIORITY, Math.min(Thread.MAX_PRIORITY, priority + _acceptorPriorityDelta)));

    try (AutoLock l = _lock.lock())
    {
        _acceptors[_id] = thread;
    }
```

于是 jstack 里看到的 `qtp12345678-acceptor-0@1a2b3c4d-ServerConnector@...` 就是**一个池线程临时充当 acceptor**, 这也是 `_acceptorPriorityDelta = -2` 的副作用来源: 优先级调整发生在池线程身上, 线程退出 run() 时 Jetty 会把名字与优先级还原(`:723-726` 的 `finally`)。

`ThreadPoolBudget.leaseFrom` 的作用是向 `SizedThreadPool` 声明「我要长期占用 N 个线程名额」:

```java
// jetty-util-12.1.14/org/eclipse/jetty/util/thread/ThreadPoolBudget.java:170-179
public static Lease leaseFrom(Executor executor, Object leasee, int threads)
{
    if (executor instanceof ThreadPool.SizedThreadPool)
    {
        ThreadPoolBudget budget = ((ThreadPool.SizedThreadPool)executor).getThreadPoolBudget();
        if (budget != null)
            return budget.leaseTo(leasee, threads);
    }
    return NOOP_LEASE;
}
```

因为 acceptor 与 selector 都是**长期阻塞**的任务, 如果不预留额度, `maxThreads=200` 的池会被这些不处理请求的线程蚕食, 极端情况下新连接的读事件永远排不上队。租赁关系是 `acceptors.length` 加上 selector 自身的 lease, 具体的 `QueuedThreadPool` 与虚拟线程形态下的差异见 [Jetty Threading](/docs/CS/Framework/Jetty/Threading.md)。

## accept loop and setAccepting drain

`Acceptor.run()` 的循环体就是 Jetty 收连的全部逻辑:

```java
// jetty-server-12.1.14/org/eclipse/jetty/server/AbstractConnector.java:696-720
while (isRunning() && !_shutdown.isShutdown())
{
    try (AutoLock l = _lock.lock())
    {
        if (!_accepting && isRunning())
        {
            _setAccepting.await();
            continue;
        }
    }
    catch (InterruptedException e)
    {
        continue;
    }

    try
    {
        accept(_id);
    }
    catch (Throwable x)
    {
        if (!handleAcceptFailure(x))
            break;
    }
}
```

三个值得注意的设计:

1. **`_accepting == false` 时线程 `await()`, 不忙等**。`setAccepting(false)` 只是让 acceptor 停在条件变量上, **监听 socket 仍然开着**, 内核 accept 队列继续堆积; 恢复时 `_setAccepting.signalAll()`(`:423-428`)。这正是滚动发布时「摘流但不丢监听」的原语, 也解释了为什么单纯 `setAccepting(false)` 并不能把已建立的空闲连接赶走。
2. **`accept(_id)` 是抽象方法**(`AbstractConnector.java:410`), 阻塞语义由子类实现, `ServerConnector` 用阻塞模式的 `ServerSocketChannel.accept()`。
3. **异常不 fatal**: `handleAcceptFailure`(`:625`) 默认对 `InterruptedException`、`AsynchronousCloseException`、`ClosedChannelException` 之类返回「继续」, 只有真正无法恢复时才让循环 break, 避免一次 EMFILE / 客户端提前 RST 就把 acceptor 干掉。

## Selector-based accept mode when acceptors is 0

`acceptors = 0` 是合法配置, 含义是「不要用阻塞线程收连」。`ServerConnector.doStart()` 于是把监听 channel 自己交给 selector:

```java
// jetty-server-12.1.14/org/eclipse/jetty/server/ServerConnector.java:233-236
if (getAcceptors() == 0)
{
    _acceptChannel.configureBlocking(false);
    _acceptor.set(_manager.acceptor(_acceptChannel));
}
```

`SelectorManager.acceptor(SelectableChannel)` 把活儿派给某个 `ManagedSelector` 的内部 `Acceptor`(`io/SelectorManager.java:243-256`), 它不再是线程, 而是一个 `SelectorUpdate + Selectable`:

```java
// jetty-io-12.1.14/org/eclipse/jetty/io/ManagedSelector.java:831-849
public Runnable onSelected()
{
    SelectableChannel channel = null;
    try
    {
        while (true)
        {
            channel = _selectorManager.doAccept(_channel);
            if (channel == null)
                break;
            _selectorManager.accepted(channel);
        }
    }
    catch (Throwable x)
    {
        LOG.warn("Accept failed for channel {}", channel, x);
        IO.close(channel);
    }
    return null;
}
```

注册 OP_ACCEPT 在 `update()`(`:818`), 挂起/恢复靠 `cancelAccept()`(`:860-864`) 取消 `SelectionKey`, 配合 `ServerConnector.setAccepting()` 里 `getAcceptors() > 0` 提前 return、否则重建或关闭 acceptor 的分支(`ServerConnector.java:561-583`)。注意 `onSelected()` 里的 `while(true)` 收干 accept 队列后才返回, 且返回 `null` 表示不需要额外任务——**收连动作发生在 selector 线程里**。

两种模式的取舍:

| 维度 | `acceptors >= 1`(默认) | `acceptors == 0` |
| :-- | :-- | :-- |
| 阻塞点 | 独立的池线程阻塞在 `accept()` | selector 线程 `select()` 被 OP_ACCEPT 唤醒 |
| 线程占用 | 每 acceptor 长期占 1 个名额 | 不额外占名额 |
| 慢客户端 SYN 后不发数据 | 不影响(握手已完成) | accept 后立刻在 selector 线程做 socket 选项, 极端并发下可能拉长 select 周期 |
| 适用 | 通用, 需要 `accept()` 里做重活(TLS 前置协商、`configure`) | 虚拟线程/极小线程池/容器化 CPU 受限, 想省掉常驻阻塞线程 |
| 与 epoll `SO_REUSEPORT` | 无对应机制 | 无对应机制 |

> [!NOTE]
> `MemoryConnector` 与 `DatagramServerConnector` 走的正是「没有阻塞 accept」这条路: 前者的 `accept(int)` 什么都不做, 后者在 open 时直接把 `DatagramChannel` 交给 `selectorManager.accept(...)`。见 `DatagramServerConnector.java:74`、`:145`。

## selectors is the only CPU-derived formula

```java
// jetty-io-12.1.14/org/eclipse/jetty/io/SelectorManager.java:70-79
private static int defaultSelectors(Executor executor)
{
    if (executor instanceof ThreadPool.SizedThreadPool)
    {
        int threads = ((ThreadPool.SizedThreadPool)executor).getMaxThreads();
        int cpus = ProcessorUtils.availableProcessors();
        return Math.max(1, Math.min(cpus / 2, threads / 16));
    }
    return Math.max(1, ProcessorUtils.availableProcessors() / 2);
}
```

触发条件在构造器 `:94-95`(`selectors <= 0`)。代入默认 `QueuedThreadPool(maxThreads = 200)`: `threads / 16 = 12`, 在 16 核机器上 `cpus / 2 = 8`, 于是 **8 个 selector**; 在 4 核机器上是 2 个; 如果线程池小于 16 线程, 会得到下限 1。虚拟线程或普通 `Executor` 不是 `SizedThreadPool`, 走第二条分支, 只有 CPU 一半。

派活是纯轮询, 没有任何负载均衡判断:

```java
// jetty-io-12.1.14/org/eclipse/jetty/io/SelectorManager.java:99
_selectorIndexUpdate = index -> (index + 1) % _selectors.length;
```

这解释了一个常见困惑: **selector 数决定的是同一时刻能被多少条 `select()` 并行唤醒**, 与请求处理并发度无关(后者是 `Executor` 的事)。已经建立连接被固定分配到某一个 `ManagedSelector`, 不会迁移, 因此某个 selector 上聚了一批活跃连接时, 那个 selector 的唤醒延迟会体现在所有成员身上——这也是 `cpus/2` 而不是 `cpus` 的原因: 太多 selector 会让每个连接的事件分发更分散, 而 `select()` 本身不是瓶颈。

## ServerConnector connection setup and socket options

```java
// jetty-server-12.1.14/org/eclipse/jetty/server/ServerConnector.java:383-400
@Override
public void accept(int acceptorID) throws IOException
{
    ServerSocketChannel serverChannel = _acceptChannel;
    if (serverChannel != null && serverChannel.isOpen())
    {
        SocketChannel channel = serverChannel.accept();
        accepted(channel);
    }
}

private void accepted(SocketChannel channel) throws IOException
{
    channel.configureBlocking(false);
    Socket socket = channel.socket();
    configure(socket);
    _manager.accept(channel);
}
```

```java
// jetty-server-12.1.14/org/eclipse/jetty/server/ServerConnector.java:402-417
protected void configure(Socket socket)
{
    try
    {
        socket.setTcpNoDelay(_acceptedTcpNoDelay);
        if (_acceptedReceiveBufferSize > -1)
            socket.setReceiveBufferSize(_acceptedReceiveBufferSize);
        if (_acceptedSendBufferSize > -1)
            socket.setSendBufferSize(_acceptedSendBufferSize);
    }
    catch (SocketException e)
    { ... }
}
```

`_acceptedTcpNoDelay` 默认 `true`(`:83`), 两个 buffer size 默认 `-1`(`:84-85`), 即**完全不设 socket 缓冲, 交给内核与 autotuning**。这是很多人以为 Jetty「性能差」实则配置差异的地方: 显式设 `ReceiveBufferSize` 会关掉内核自动调优。

`_manager` 由 `newSelectorManager(getExecutor(), getScheduler(), selectors)` 创建(`ServerConnector.java:213`), 扩展点就是覆盖这个受保护方法(`:218-221`)。默认的 `ServerConnectorManager`(`:585-601`) 覆写三处: `accepted()` 回调 `AcceptListener`、`newEndPoint()` 造 `SocketChannelEndPoint`、`newConnection()` 走工厂链。**换 EndPoint 类型(比如加 `SSLConnectionFactory` 之外的自定义 transport)不要碰 acceptor, 从这里入手。**

## Chained protocol negotiation in ConnectionFactory

`AbstractConnector` 用 `LinkedHashMap` 保存工厂, 注释明确 `// Order is important on server side, so we use a LinkedHashMap`(`:147`)。协商不是「按 ALPN 结果查表」这么简单, 而是**沿着有序的协议列表找下一个**:

```java
// jetty-server-12.1.14/org/eclipse/jetty/server/AbstractConnectionFactory.java:35-48
private final String _protocol;
private final List<String> _protocols;
private int _inputBufferSize = IO.DEFAULT_BUFFER_SIZE;

protected AbstractConnectionFactory(String protocol)
{
    _protocol = protocol;
    _protocols = List.of(protocol);
}

protected AbstractConnectionFactory(String... protocols)
{
    _protocol = protocols[0];
    _protocols = List.of(protocols);
}
```

```java
// jetty-server-12.1.14/org/eclipse/jetty/server/AbstractConnectionFactory.java:77-83
protected String findNextProtocol(Connector connector)
{
    return findNextProtocol(connector, getProtocol());
}

protected static String findNextProtocol(Connector connector, String currentProtocol)
{
    String nextProtocol = null;
    for (Iterator<String> it = connector.getProtocols().iterator(); it.hasNext(); )
    { ... }
```

直观后果: **TLS 工厂必须排在明文工厂之前**, 因为 `SslConnectionFactory` 的 `newConnection` 完成后会取 `getNextProtocol()`(通常是 `http/1.1` 或 `h2`)再向列表查下一个工厂; `HttpConfiguration` 的 `setProtocols` 链必须首尾闭合。`AbstractConnector.doStart()` 里还有一段启动期校验: 若存在 `SslConnectionFactory`, 它的 `nextProtocol` 必须在连接器协议表里找得到工厂, 否则 `IllegalStateException`(`AbstractConnector.java:315-319`)。

工厂接口本身只有一个关键方法: `ConnectionFactory.newConnection(Connector, EndPoint)`。HTTP/2 的工厂链(`HTTP2C` 前置码识别、`h2` ALPN 升级)见 [Jetty Http2](/docs/CS/Framework/Jetty/Http2.md)。

## Idle timeout and persistent connection decision

三个层级, 后一层覆盖前一层:

| 层级 | 字段 | 默认 | 位置 |
| :-- | :-- | :-- | :-- |
| Connector | `_idleTimeout` | `30000` ms | `AbstractConnector.java:156` |
| HttpConfiguration | `_idleTimeout` | `-1`(表示回落到 connector) | `HttpConfiguration.java:71` |
| HttpConfiguration | `_persistentConnectionsEnabled` | `true` | `HttpConfiguration.java:77` |
| LowResourceMonitor | `_lowResourcesIdleTimeout` | `1000` ms | `LowResourceMonitor.java:57` |

> [!WARNING]
> **Jetty 12 里已经没有 `selectKeepAlive` 方法**。它在 9/10/11 时代是 `HttpConnection` 上一个可读写的判断钩子, 12.1.14 全模块 grep 零命中。等价判断被内联进响应生成器 `jetty-http/HttpGenerator.java:630-793`(综合 `Connection` 头、协议版本、`persistent` 标志、请求体是否完整消费)与 `HttpConnection.java:1392-1411`。想自定义 keep-alive 策略, 现在只能改 `HttpConfiguration`(`setPersistentConnectionsEnabled`、`setRelativeRedirectAllowed` 之类)或换响应生成器, 不要再去找那个旧扩展点。

## Rate limiting and low resources

Jetty 的连接级保护全部**挂在 SelectorManager 的 AcceptListener 上**, 而不是在 handler 链里。回调契约四个方法(`io/SelectorManager.java:559-598`): `onAccepting`(已 accept、尚未分配 EndPoint)、`onAcceptFailed`、`onAccepted`(EndPoint + Connection 建好且 onOpen 已通知)、`onClosed`。注释还提醒「called from either the selector or acceptor thread and implementations must be non blocking and fast」——这决定了限流器只能记账, 不能在里面做阻塞 IO。

| 组件 | 位置 | 机制 |
| :-- | :-- | :-- |
| `ConnectionLimit` | `ConnectionLimit.java:63`, `_maxConnections` `:72`, 判定 `:194-202` | 跨多个 connector 统计存活连接数, 超限时在 `onAccepting` 立即关闭新 channel |
| `NetworkConnectionLimit` | `NetworkConnectionLimit.java:55` | 按远端 IP / 子网限制并发连接, 抗单源打满 |
| `AcceptRateLimit` | `AcceptRateLimit.java:59` | 令牌桶限制**新建连接速率**, 慢启动时保护后端 |
| `LowResourceMonitor` | `LowResourceMonitor.java:47` | 周期探测低资源, 低资源期把已有连接空闲超时压到 1s |

`LowResourceMonitor` 的默认值组合容易踩:

```java
// jetty-server-12.1.14/org/eclipse/jetty/server/LowResourceMonitor.java:55-65
private int _period = 1000;
private int _lowResourcesIdleTimeout = 1000;
private int _maxLowResourcesTime = 0;
private boolean _acceptingInLowResources = true;
```

`:366` 处 `endPoint.setIdleTimeout(_lowResourcesIdleTimeout)`——一旦低资源(线程池接近耗尽、内存压力、GC 时间过长), 每个连接只剩 **1 秒**空闲时间, 空闲即断, 快速回收线程与 fd; `_maxLowResourcesTime = 0` 表示低资源状态没有最长持续限制, 会一直持续到资源恢复。`_acceptingInLowResources = true` 意味着低资源期间**仍然继续 accept**, 只靠 1s 空闲超时兜底, 想真正拒绝新连接要显式设为 `false`。

## Where statistics went in 12

> [!IMPORTANT]
> **`Server` 在 Jetty 12 里没有任何统计字段**——`grep -c Statistic Server.java` 在 12.1.14 得到 **0**, 旧的 `AbstractConnector._statistics` 同样不存在。凡是照旧版写 `server.getStatistics()`、`connector.getStatistic()` 的代码在 12 上都编译不过。

统计被拆成两层:

- **请求级**: `jetty-server/handler/StatisticsHandler.java:33`, 要显式包在 handler 链最外层, 提供 requests / responses / 时长直方图, JMX 与 `StatisticsHandler.Statistics` 都从这里取。
- **连接级**: `jetty-io/ConnectionStatistics.java:46`, 通过 `SelectorManager` 的 listener 聚合, `:108-114` 读 `connection.getBytesIn()` / `getMessagesIn()`——注意它统计的是**连接对象自己上报的字节数**, 不是内核层的收发。

想知道「当前有多少活跃连接」这类瞬时值, 仍然用 `Connector.getEndpoints()`(`AbstractConnector.java` 的 `_immutableEndPoints`), 它是对存活 `EndPoint` 的只读视图, 比统计器更实时也更便宜。连接生命周期与派发见 [Jetty RequestFlow](/docs/CS/Framework/Jetty/RequestFlow.md)。

## New connector shapes in 12.1

| 连接器 | 位置 | 用途与关键点 |
| :-- | :-- | :-- |
| `ServerConnector` | `ServerConnector.java` | 标准 TCP/IP, 本篇主线 |
| `DatagramServerConnector` | `DatagramServerConnector.java:33` | QUIC 等基于 UDP 的协议; `accept(int)` 是空实现(`:145`), open 时直接 `selectorManager.accept(datagramChannel)`(`:74`) |
| `LocalConnector` | `LocalConnector.java:45` | 本机 Unix domain socket / 本地传输, 测试与 sidecar 场景 |
| `MemoryConnector` | `MemoryConnector.java:62` | 完全在内存里造 EndPoint, 集成测试不经过真实网络栈 |
| `NetworkTrafficServerConnector` | `NetworkTrafficServerConnector.java` | 在 `ServerConnector` 之上注入带宽/延迟模拟, 用于弱网测试 |

它们的共同点是**复用同一套 `SelectorManager` + `ConnectionFactory` 机制**, 只替换 transport 与 EndPoint 类型。这正是 Jetty 连接器抽象比「一个 Acceptor 线程池」更耐用的地方: 加一种传输不需要动 accept 逻辑, 只需要提供 `newSelectorManager()` 与 `newEndPoint()`。

## Pitfalls

1. **照旧版调 `acceptors`**。12 默认恒为 1, 调大不提速反而吃线程池额度; 判断瓶颈要看 `-acceptor-0` 线程是否长期 RUNNABLE 在 `accept` 之外。
2. **`selectors` 设成 1 却抱怨高并发下延迟抖动**。所有连接挤在一个 `select()` 上, 任何一个连接的读写任务都可能推迟其他人的事件处理; 容器里 CPU limit 小会让 `cpus/2` 得到 1, 此时显式给 `selectors` 更稳。
3. **`maxThreads` 小于 `16 * selectors`**, `threads/16` 把 selector 数压到 1, 与直觉相反。两者要么都显式设, 要么别设。
4. **显式设 `AcceptedReceiveBufferSize` / `SendBufferSize`** 关掉内核 autotuning, 高带宽长肥管道上吞吐反而下降。
5. **把 `setAccepting(false)` 当「优雅下线」的全部**。它只停 accept, 存量连接不受影响; 完整流程还要 `Server.stop()` 或主动 `EndPoint.close()`, 配合 `_shutdownIdleTimeout = 1000`。
6. **`ConnectionFactory` 顺序写错**, HTTP/2 或 TLS 场景表现为「连上就没响应」或 `No protocol factory for SSL next protocol`, 启动期那条 `IllegalStateException` 要当真。
7. **在 `AcceptListener` 里做阻塞操作**, selector 线程被拖住, 表现是整个连接器的新连接都卡。
8. **`LowResourceMonitor` 上线后发现大量 `Connection reset`**。它没坏, 是 1s 空闲超时在低资源期主动掐持久连接; 客户端连接池要能容忍断连重试。
9. **找 `server.getStatistics()`**。12 里请改用 `StatisticsHandler` + `ConnectionStatistics`。

## Links

- [Jetty](/docs/CS/Framework/Jetty/Jetty.md)
- [Jetty Threading](/docs/CS/Framework/Jetty/Threading.md)
- [Jetty RequestFlow](/docs/CS/Framework/Jetty/RequestFlow.md)
- [Jetty HTTP/2](/docs/CS/Framework/Jetty/Http2.md)
- [Tomcat Connector](/docs/CS/Framework/Tomcat/Connector.md)
- [Netty](/docs/CS/Framework/Netty/Netty.md)

## References

- [Jetty 12 Programming Guide - Connectors](https://jetty.org/docs/jetty/12/programming-guide/server/connectors.html)
- [Jetty 12 Documentation](https://jetty.org/docs/)
