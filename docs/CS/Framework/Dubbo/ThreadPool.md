## Introduction

Dubbo 的线程模型分两层：**Dispatcher** 决定「哪些通道事件交给业务线程池」，**ThreadPool** 决定「这个业务线程池长什么样」。两层的默认值都不在配置文件里，而在 SPI 注解与常量类里，因此极容易被记反。

流传最广的三个说法，本文逐条从源码推翻：

- **「Dubbo 默认线程池是 `limited`」**——不成立。`CommonConstants.DEFAULT_THREADPOOL = "limited"` 这个常量确实存在，但它在主源码里从未被任何生产代码读取，唯一引用者是一个性能测试。真实默认由 `ThreadPool` 的 `@SPI` 决定：Provider 侧是 `fixed`，Consumer 侧是 `cached`。
- **「`threads=0` 或负值表示自动」**——不成立。`threads` 只有「读多少就是多少」的语义，`0` 就是 0；在全部线程池参数里，**只有 `iothreads` 会在非正值时回落默认值，只有 `queues` 有三态语义**。
- **「消费端也用 `fixed`，和 Provider 一样」**——不成立。消费端线程池默认 `cached`，而且是**全应用共享的一个池**；更反直觉的是，**同步调用根本不占这个池**，业务代码实际跑在发起调用的线程上。

版本基线：Apache Dubbo **3.3.6**，源码 tag `dubbo-3.3.6`。本文所有 SPI 名、默认值、行号均取自该 tag 的官方源码文件。`Dispatcher` / `ChannelHandler` / `Transporter` 的接口结构已在 [remoting.md](/docs/CS/Framework/Dubbo/remoting.md) 展开，本文不重复，只聚焦线程模型选型、线程池参数默认值与消费端线程模型。

## Dispatcher：五种派发模型

### 默认值与兼容 key

`Dispatcher` 的 SPI 默认扩展名是 `all`：

```java
// dubbo-remoting/dubbo-remoting-api/src/main/java/org/apache/dubbo/remoting/Dispatcher.java:28-40
@SPI(value = AllDispatcher.NAME, scope = ExtensionScope.FRAMEWORK)
public interface Dispatcher {

    /**
     * dispatch the message to threadpool.
     */
    @Adaptive({Constants.DISPATCHER_KEY, "dispather", "channel.handler"})
    // The last two parameters are reserved for compatibility with the old configuration
    ChannelHandler dispatch(ChannelHandler handler, URL url);
}
```

> [!NOTE]
> `@Adaptive` 的 key 列表里除了正式的 `dispatcher`，还挂了拼错的 `dispather` 与 `channel.handler` 两个兼容 key，源码注释写明是历史遗留。配置里写 `dispather=direct` 在 3.3.6 上仍然生效，但不要在新配置里使用。

### 五个扩展名与事件分流

SPI 注册文件共注册 5 个扩展名：

```properties
# dubbo-remoting/dubbo-remoting-api/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.remoting.Dispatcher
all=org.apache.dubbo.remoting.transport.dispatcher.all.AllDispatcher
direct=org.apache.dubbo.remoting.transport.dispatcher.direct.DirectDispatcher
message=org.apache.dubbo.remoting.transport.dispatcher.message.MessageOnlyDispatcher
execution=org.apache.dubbo.remoting.transport.dispatcher.execution.ExecutionDispatcher
connection=org.apache.dubbo.remoting.transport.dispatcher.connection.ConnectionOrderedDispatcher
```

各 Dispatcher 把**哪些事件**丢进业务线程池，差异如下：

| 扩展名 | 实现类 | 进入业务线程池的事件 |
| :--- | :--- | :--- |
| `all`（默认） | `AllChannelHandler` | connected、disconnected、received、caught 全部入池 |
| `direct` | `DirectChannelHandler` | 仅 received，且**仅当 executor 是 `ThreadlessExecutor` 才入池，否则在 IO 线程同步直调** |
| `message` | `MessageOnlyChannelHandler` | 仅 received |
| `execution` | `ExecutionChannelHandler` | 仅 received，且仅 `message instanceof Request` 时入池 |
| `connection` | `ConnectionOrderedChannelHandler` | connected/disconnected 入**独立且有序的 connectionExecutor**，received/caught 入主线程池 |

`all` 是「什么都丢给业务线程池」：IO 线程只负责读写，不碰业务逻辑。`connection` 的关键在于 connected/disconnected 被路由到一个**单线程、按序执行**的连接事件池，保证同一连接的建连/断连事件不被乱序处理，避免连接状态机错乱——这是它在长连接频繁重建场景下的价值。

### 什么时候会绕过线程池

`direct` 与 `execution` 都会在特定条件下**不使用业务线程池**，直接在 IO 线程上调用下游 handler：

```java
// dubbo-remoting/dubbo-remoting-api/.../transport/dispatcher/direct/DirectChannelHandler.java:38-48
@Override
public void received(Channel channel, Object message) throws RemotingException {
    ExecutorService executor = getPreferredExecutorService(message);
    if (executor instanceof ThreadlessExecutor) {
        try {
            executor.execute(new ChannelEventRunnable(channel, handler, ChannelState.RECEIVED, message));
        } catch (Throwable t) {
            throw new ExecutionException(message, channel, getClass() + " error when process received event .", t);
        }
    } else {
        handler.received(channel, message);
    }
}
```

```java
// dubbo-remoting/dubbo-remoting-api/.../transport/dispatcher/execution/ExecutionChannelHandler.java:44-63（节选）
@Override
public void received(Channel channel, Object message) throws RemotingException {
    ExecutorService executor = getPreferredExecutorService(message);

    if (message instanceof Request) {
        try {
            executor.execute(new ChannelEventRunnable(channel, handler, ChannelState.RECEIVED, message));
        } catch (Throwable t) {
            if (t instanceof RejectedExecutionException) {
                sendFeedback(channel, (Request) message, t);
            }
            throw new ExecutionException(message, channel, getClass() + " error when process received event.", t);
        }
    } else if (executor instanceof ThreadlessExecutor) {
        executor.execute(new ChannelEventRunnable(channel, handler, ChannelState.RECEIVED, message));
    } else {
        handler.received(channel, message);
    }
}
```

两条结论：

- `direct` 只有拿到 `ThreadlessExecutor`（消费端同步调用的回包路径）才入池，其余情况**直接在 Netty IO 线程上执行业务**。IO 线程一旦阻塞，整条连接上的其他请求都被拖住。
- `execution` 只把 `Request`（真正的服务请求）入池；非 `Request` 的对象（如心跳、响应回包）在非 `ThreadlessExecutor` 情况下同样直调。

`getPreferredExecutorService(message)` 来自 `WrappedChannelHandler`：当 message 自带 executor（例如同步调用挂的 `ThreadlessExecutor`）时优先用它，否则用共享业务池。这正是消费端同步调用「回包在调用线程上被消费」的机制入口。

## ThreadPool：四种实现与默认参数

### `@SPI` 默认是 fixed，`limited` 是死常量

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/threadpool/ThreadPool.java:29-38
@SPI(value = "fixed", scope = ExtensionScope.FRAMEWORK)
public interface ThreadPool {

    /**
     * Thread pool
     *
     * @param url URL contains thread parameter
     * @return thread pool
     */
    @Adaptive({THREADPOOL_KEY})
    Executor getExecutor(URL url);
}
```

> [!WARNING]
> 打假：**「默认线程池是 `limited`」不成立。** `CommonConstants.java:133` 确实定义了 `String DEFAULT_THREADPOOL = "limited";`，但对整棵源码树检索 `DEFAULT_THREADPOOL`，命中只有三处：常量自身定义、`dubbo-compatible` 里的同名历史常量、以及测试 `PerformanceServerTest` 的 import 与使用。**没有任何 main 代码消费它。** 判断真实默认值要看 `@SPI`：Provider 走 `fixed`，Consumer 走 `cached`（下一节）。

SPI 注册文件共 4 个扩展名：

```properties
# dubbo-common/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.common.threadpool.ThreadPool
fixed=org.apache.dubbo.common.threadpool.support.fixed.FixedThreadPool
cached=org.apache.dubbo.common.threadpool.support.cached.CachedThreadPool
limited=org.apache.dubbo.common.threadpool.support.limited.LimitedThreadPool
eager=org.apache.dubbo.common.threadpool.support.eager.EagerThreadPool
```

### 四个实现的行为对照

| 扩展名 | core / max | 空闲回收 | 兜底异常策略 | 适用 |
| :--- | :--- | :--- | :--- | :--- |
| `fixed`（Provider 默认） | `corethreads`=0 / `threads`=200 | `alive`=60s | `AbortPolicyWithReport` | 稳定并发、可预测延迟 |
| `cached`（Consumer 默认） | `corethreads`=0 / `threads`=**Integer.MAX_VALUE** | `alive`=60s | `AbortPolicyWithReport` | 突发流量、短任务 |
| `limited` | `corethreads`=0 / `threads`=200 | **永不收缩**（keepAlive=Long.MAX_VALUE） | `AbortPolicyWithReport` | 只想设上限、不回收 |
| `eager` | `corethreads`=0 / `threads`=**Integer.MAX_VALUE** | `alive`=60s | `AbortPolicyWithReport` | 队列优先扩容而非排队 |

> [!NOTE]
> **`threads` 的默认值 200 只属于 `fixed` 与 `limited`。** `cached` 与 `eager` 在源码里用的是 `url.getParameter(THREADS_KEY, Integer.MAX_VALUE)`（`CachedThreadPool.java:55`、`EagerThreadPool.java` 同），即「不配就无上限」。把「Dubbo 默认 200 线程」当成所有线程池的默认值会算错消费端容量。

`eager` 的特殊之处在队列：它把 `queues <= 0` 归一成 `1` 再构造 `TaskQueue`，由 `EagerThreadPoolExecutor` 在 core 线程忙时**优先创建新线程**而不是入队，用来对抗「core 已满、任务却在无界队列里排队导致 max 形同虚设」的问题。

### queues 的三态语义

只有 `queues` 是三态。以 `FixedThreadPool` 为例：

```java
// dubbo-common/.../threadpool/support/fixed/FixedThreadPool.java:48-61（节选）
int threads = url.getParameter(THREADS_KEY, DEFAULT_THREADS);
int queues = url.getParameter(QUEUES_KEY, DEFAULT_QUEUES);

BlockingQueue<Runnable> blockingQueue;

if (queues == 0) {
    blockingQueue = new SynchronousQueue<>();
} else if (queues < 0) {
    blockingQueue = new MemorySafeLinkedBlockingQueue<>();
} else {
    blockingQueue = new LinkedBlockingQueue<>(queues);
}
```

| `queues` 取值 | 队列实现 | 语义 | 生产含义 |
| :--- | :--- | :--- | :--- |
| `0`（默认） | `SynchronousQueue` | 不排队，直接交接 | 线程用满即拒绝，触发 `RejectedExecutionHandler`，**快速失败** |
| `> 0` | `LinkedBlockingQueue(queues)` | 有界排队 | 排队消化突发，但会引入尾延迟 |
| `< 0` | `MemorySafeLinkedBlockingQueue` | 无界但受剩余内存约束 | 不主动拒绝，堆内存不足时按策略丢弃 |

`queues=0` 与 `queues<0` 的取舍本质是**「背压 vs 缓冲」**：

- `queues=0` 配合 `fixed` 是最可预测的组合。请求超过线程数立刻抛 `RejectedExecutionException`，再由上层 `AbortPolicyWithReport` 打出线程栈告警。缺点是突发流量直接失败，不给你排队的机会；因此它适合「业务耗时短、CPU 密集、失败可由客户端重试」的场景。
- `queues<0` 走 `MemorySafeLinkedBlockingQueue`，它继承 `LinkedBlockingQueue` 但把容量设成 `Integer.MAX_VALUE`，并在入队前检查 JVM 剩余可用内存（构造函数默认阈值 `THE_256_MB = 256MB`）。剩余内存不足时不再入队，而是交给内部 `Rejector`（默认 `DiscardPolicy`）丢弃。也就是说它**不是「无界」而是「内存界」**：用可控的丢弃换取不 OOM。适合「业务耗时长、IO 密集、丢一点也不要雪崩」的场景。

> [!TIP]
> `queues` 传任意负值效果相同（只要有界队列与无界队列二选一），不要指望 `-1` / `-100` 代表不同的容量。真正能调容量的是 `>0` 的数值。

## 消费端线程模型

消费端是误解最集中的地方，分四点讲清楚。

### 默认 `cached` 从何而来

Provider 与 Consumer 走的是两套默认。`CommonConstants.java:133,135` 分别定义：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/constants/CommonConstants.java:133-135
String DEFAULT_THREADPOOL = "limited";
String DEFAULT_CLIENT_THREADPOOL = "cached";
```

前者是上文说的死常量，后者被 `AbstractClient.initExecutor` 真实消费：

```java
// dubbo-remoting/dubbo-remoting-api/.../transport/AbstractClient.java:145-156（节选）
private void initExecutor(URL url) {
    ExecutorRepository executorRepository = ExecutorRepository.getInstance(url.getOrDefaultApplicationModel());

    /*
     * Consumer's executor is shared globally, provider ip doesn't need to be part of the thread name.
     */
    url = url.addParameter(THREAD_NAME_KEY, CLIENT_THREAD_POOL_NAME)
            .addParameterIfAbsent(THREADPOOL_KEY, DEFAULT_CLIENT_THREADPOOL);
    executor = executorRepository.createExecutorIfAbsent(url);
    ...
}
```

注意用的是 `addParameterIfAbsent`：**只有 URL 上完全没有 `threadpool` 时才填 `cached`**，用户显式配置优先。Triple 协议的流式调用另有 `TripleProtocol.getOrCreateStreamExecutor`（:197-199）用同样的 `DEFAULT_CLIENT_THREADPOOL` 兜底。

### 消费端线程池是全局共享的

`DefaultExecutorRepository` 对消费者返回一个固定 key，所有消费者共用一个池：

```java
// dubbo-common/.../threadpool/manager/DefaultExecutorRepository.java:149-157
private String getConsumerKey(ServiceModel serviceModel) {
    // Consumer's executor is sharing globally, key=Integer.MAX_VALUE
    return MAX_KEY;
}
```

（`getConsumerKey(URL url)` 版本返回 `String.valueOf(Integer.MAX_VALUE)`，注释相同。）

所以「给某个 Reference 单独调 `threads`」在消费端语义上要注意：池是按 `Integer.MAX_VALUE` 这个 key 建的，第一个消费者建池时的参数会决定之后所有消费者共享的那个池。想隔离得另想办法，而不是改单个 Reference 的 `threads`。

### 同步调用不占消费端线程池

这是最容易被忽略的一点。`AbstractInvoker.getCallbackExecutor` 在同步模式下返回 `ThreadlessExecutor`：

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/protocol/AbstractInvoker.java:340-346
protected ExecutorService getCallbackExecutor(URL url, Invocation inv) {
    if (InvokeMode.SYNC == RpcUtils.getInvokeMode(getUrl(), inv)) {
        return new ThreadlessExecutor();
    }
    return ExecutorRepository.getInstance(url.getOrDefaultApplicationModel())
            .getExecutor(url);
}
```

`ThreadlessExecutor` 自身不持有任何线程：任务被塞进队列，只有调用 `waitAndDrain()` 的那个线程才真正执行它们。于是同步调用链是「业务线程发起 → Netty IO 线程收到回包 → 唤醒并交给调用线程消费」，**全程没有消费端业务线程池参与**。只有 `ASYNC` / `FUTURE` 才真正走 `ExecutorRepository.getExecutor(url)`，占用全局共享池。

> [!NOTE]
> 由此可推：「调大消费端 `threads` 能提高同步 RPC 吞吐」是错的。同步调用受限于调用方线程数与下游延迟，消费端池规模与它无关。要提升的是发起调用的业务线程池（通常是 Tomcat / 自有 Executor），不是 Dubbo 的消费端池。

### 多 Reference 默认共享一条连接

Dubbo 协议下，`connections` 默认 `0` 表示**共享连接**：

```java
// dubbo-rpc/dubbo-rpc-dubbo/.../protocol/dubbo/DubboProtocol.java:452-472（节选）
private ClientsProvider getClients(URL url) {
    int connections = url.getParameter(CONNECTIONS_KEY, 0);
    // whether to share connection
    // if not configured, connection is shared, otherwise, one connection for one service
    if (connections == 0) {
        String shareConnectionsStr = ... url.getParameter(SHARE_CONNECTIONS_KEY, ...)
                ... : ConfigurationUtils.getProperty(..., SHARE_CONNECTIONS_KEY, DEFAULT_SHARE_CONNECTIONS);
        connections = Integer.parseInt(shareConnectionsStr);
        return getSharedClient(url, connections);
    }
    List<ExchangeClient> clients =
            IntStream.range(0, connections).mapToObj((i) -> initClient(url)).collect(Collectors.toList());
    return new ExclusiveClientsProvider(clients);
}
```

`connections != 0` 时 `DataStore` 独占连接；`connections == 0` 时读 `shareconnections`，默认值 `"1"`：

```java
// dubbo-rpc/dubbo-rpc-dubbo/src/main/java/org/apache/dubbo/rpc/protocol/dubbo/Constants.java:21-27
String SHARE_CONNECTIONS_KEY = "shareconnections";

/**
 * By default, a consumer JVM instance and a provider JVM instance share a long TCP connection (except when connections are set),
 * which can set the number of long TCP connections shared to avoid the bottleneck of sharing a single long TCP connection.
 */
String DEFAULT_SHARE_CONNECTIONS = "1";
```

`getSharedClient` 按 `url.getAddress()` 缓存 `SharedClientsProvider`，命中时调用 `increaseCount()` 复用同一个实例，未命中才新建：

```java
// dubbo-rpc/dubbo-rpc-dubbo/.../protocol/dubbo/DubboProtocol.java:483-495（节选）
private SharedClientsProvider getSharedClient(URL url, int connectNum) {
    String key = url.getAddress();
    int expectedConnectNum = Math.max(connectNum, 1);
    return referenceClientMap.compute(key, (originKey, originValue) -> {
        if (originValue != null && originValue.increaseCount()) {
            return originValue;
        } else {
            return new SharedClientsProvider(
                    this, originKey, buildReferenceCountExchangeClientList(url, expectedConnectNum));
        }
    });
}
```

> [!WARNING]
> 默认情况下，**同一消费端进程里多个线程、多个 `@DubboReference` 调用同一个 Provider 地址，共用同一条 TCP 长连接**。这不是「每个 Reference 一条连接」。共享连接的代价是单连接成为吞吐与队头阻塞的瓶颈；`shareconnections` 调大或改用 `connections=N`（独占模式）才会得到多条连接。Triple 走 HTTP/2，多路复用特性让共享连接的影响小很多，但连接数仍由这些参数控制。

## 线程模型调优

### 场景到配置的映射

| 场景特征 | Dispatcher | ThreadPool | 关键参数 | 理由 |
| :--- | :--- | :--- | :--- | :--- |
| 业务耗时短、CPU 密集 | `all`（默认） | `fixed` | `threads` 适当调小、`queues=0` | 快速失败，避免任务排队放大延迟 |
| 业务耗时长、IO 密集（DB / 下游 RPC） | `all` | `fixed` 调大 `threads`，或 `cached` | `threads=500~1000`、`queues<0` | 用内存受控的无界队列兜住突发 |
| 需要连接事件有序 | `connection` | 任意 | — | connected/disconnected 进独立有序池 |
| 需要完全掌控派发 | `direct` / `message` | 任意 | — | 注意业务会占用 Netty IO 线程 |
| 想避免队列把 max 架空 | `all` | `eager` | `queues` 固定为 1 | core 忙时优先扩容而非排队 |

关于 `eager` 的适用性：它的 `TaskQueue` 只在 core 线程都忙时触发扩容，因此必须配合一个**很小的队列**。若给 `eager` 配一个大队列，任务会先排队，扩容时机被推迟，反而退化。

### IO 线程数与 `iothreads`

`iothreads` 与业务线程池无关，它控制 Netty EventLoop 线程数，默认：

```java
// dubbo-remoting/dubbo-remoting-api/src/main/java/org/apache/dubbo/remoting/Constants.java:118
int DEFAULT_IO_THREADS = Math.min(Runtime.getRuntime().availableProcessors() + 1, 32);
```

取值走 `getPositiveParameter`，即 **0 或负值会回落到默认**：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/URL.java:772-778
public int getPositiveParameter(String key, int defaultValue) {
    if (defaultValue <= 0) {
        throw new IllegalArgumentException("defaultValue <= 0");
    }
    int value = getParameter(key, defaultValue);
    return value <= 0 ? defaultValue : value;
}
```

Netty 服务端在 `NettyServer` 里用它初始化 worker group：

```java
// dubbo-remoting/dubbo-remoting-netty4/.../transport/netty4/NettyServer.java:157-160（节选）
bossGroup = new NioEventLoopGroup(1, new DefaultThreadFactory("NettyServerBoss", true));
workerGroup = new NioEventLoopGroup(
        getUrl().getPositiveParameter(IO_THREADS_KEY, Constants.DEFAULT_IO_THREADS),
        new DefaultThreadFactory("NettyServerWorker", true));
```

> [!TIP]
> `iothreads` 一般**不需要调**。`min(CPU+1, 32)` 对绝大多数机器已经够用，盲目调大会增加上下文切换。真正该调的是业务线程池；而如果业务真的跑到了 IO 线程上（用了 `direct`），那才需要关注 `iothreads`。

## 默认值汇总表

| 项 | 默认值 | 来源 | 是否被 `getPositiveParameter` 兜底 |
| :--- | :--- | :--- | :--- |
| Dispatcher 扩展名 | `all` | `Dispatcher.java:28` `@SPI(AllDispatcher.NAME)` | — |
| ThreadPool 扩展名（Provider） | `fixed` | `ThreadPool.java:29` `@SPI("fixed")` | — |
| ThreadPool 扩展名（Consumer） | `cached` | `CommonConstants.java:135` `DEFAULT_CLIENT_THREADPOOL` | — |
| `threads`（fixed / limited） | `200` | `CommonConstants.java:111` `DEFAULT_THREADS` | 否，0 就是 0 |
| `threads`（cached / eager） | `Integer.MAX_VALUE` | `CachedThreadPool.java:55` | 否 |
| `corethreads` | `0` | `CommonConstants.java:109` | 否 |
| `queues` | `0` → `SynchronousQueue` | `CommonConstants.java:141` `DEFAULT_QUEUES` | 否，三态语义 |
| `alive` | `60000` ms | `CommonConstants.java:143` `DEFAULT_ALIVE` | 否 |
| `threadname` | `Dubbo` | `CommonConstants.java:107` `DEFAULT_THREAD_NAME` | — |
| `iothreads` | `min(CPU+1, 32)` | `remoting/Constants.java:118` `DEFAULT_IO_THREADS` | **是**，≤0 回落默认 |
| `connections`（Dubbo 协议） | `0`（共享连接） | `DubboProtocol.java:453` | — |
| `shareconnections` | `1` | `dubbo-rpc-dubbo/Constants.java:27` | — |

## 陷阱清单

| 直觉写法 / 印象 | 源码实际 | 后果 |
| :--- | :--- | :--- |
| 「默认线程池是 `limited`」 | 常量存在但主源码不消费；实际 `fixed`(P) / `cached`(C) | 默认线程数与回收策略全算错 |
| 「`threads=0` 表示自动」 | `0` 就是 0，会建 0 核心线程池 | 服务不可用或直接拒绝 |
| 「所有线程池 `threads` 默认 200」 | 仅 `fixed` / `limited`；`cached` / `eager` 为 `Integer.MAX_VALUE` | 消费端容量误判 |
| 「消费端也用 `fixed`」 | `AbstractClient` 注入 `cached` | 池行为与预期不符 |
| 「改单个 Reference 的 `threads` 可隔离消费端池」 | 消费端池全局共享（key=`Integer.MAX_VALUE`） | 隔离失效 |
| 「调大消费端 `threads` 提升同步调用吞吐」 | 同步调用返回 `ThreadlessExecutor`，不占池 | 优化无效 |
| 「默认每个 Reference 一条连接」 | `connections=0` 时同地址共享连接 | 单连接成瓶颈却不自知 |
| 「`queues<0` 是无界队列，会 OOM」 | 是 `MemorySafeLinkedBlockingQueue`，受剩余内存约束并丢弃 | 误判为危险配置 |
| 「`iothreads` 也要按 `threads` 那样配」 | 走 `getPositiveParameter`，≤0 自动回落 | 与业务线程池调优混淆 |
| 「`direct` 只是少一层包装」 | 非 `ThreadlessExecutor` 时业务直接在 IO 线程执行 | IO 线程被业务阻塞 |

## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [remoting](/docs/CS/Framework/Dubbo/remoting.md)
- [Transporter](/docs/CS/Framework/Dubbo/Transporter.md)
- [Invocation](/docs/CS/Framework/Dubbo/Invocation.md)
- [Governance](/docs/CS/Framework/Dubbo/Governance.md)
- [ThreadPoolExecutor](/docs/CS/Java/JDK/Concurrency/ThreadPoolExecutor.md)

## References

1. [Apache Dubbo 官方文档](https://cn.dubbo.apache.org/zh-cn/overview/what/)
2. [dubbo-common threadpool 源码](https://github.com/apache/dubbo/tree/3.3/dubbo-common/src/main/java/org/apache/dubbo/common/threadpool)
3. [dubbo-remoting-api dispatcher 源码](https://github.com/apache/dubbo/tree/3.3/dubbo-remoting/dubbo-remoting-api/src/main/java/org/apache/dubbo/remoting/transport/dispatcher)
