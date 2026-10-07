# Jetty Thread Model

## Introduction

Jetty 的线程模型要回答的问题不是「池子开多大」，而是**一个 IO 事件到来之后，这段代码应该在哪个线程上跑**。

传统 servlet 容器的假设是「一个请求占一个线程，线程可以随便阻塞」，于是线程数就等于并发数，调优等价于调 `maxThreads`。Jetty 的假设完全不同：它的事件驱动骨架（`SelectorManager` / `ManagedSelector` / `Connection` / `FlowControlStrategy`）里很多任务的**阻塞属性是未知的**——一个 handler 可能只写一个 206 响应头就返回，也可能在业务代码里 `sleep(3s)` 等下游。如果所有任务都排队等线程，selector 线程会被拖死；如果所有任务都在 selector 线程上直接跑，一个慢 handler 就会独占这颗核上的全部连接。

所以 Jetty 12 把决策权交给了**执行策略（ExecutionStrategy）**：由它根据「任务的阻塞属性」和「当前有没有可用的线程」在四种消费方式之间动态选择。线程池（`QueuedThreadPool`）退化成执行策略背后的一个资源供给方，而 `ThreadPoolBudget` / `ReservedThreadExecutor` 负责把「网络线程」和「业务线程」在同一个池子里做出预算隔离。虚拟线程（`VirtualThreadPool`）也不是第三种性能开关，而是把「线程不够用」这个前提换掉，于是租线程机制自动失效。

本文按这条主线展开：先看 `Server` 装了哪些线程相关的组件，再看池本身，然后是使用策略、租线程、`InvocationType` 传播、虚拟线程、回调串行化，最后是 HTTP/2 的 `executeImmediately` 与调参。

## Server triad and defaults

`Server` 构造器接受三个可空参数：线程池、调度器、缓冲区池。传 `null` 就自己建并注册成托管 bean（`jetty-server-12.1.14/org/eclipse/jetty/server/Server.java:149-159`）：

```java
public Server(@Name("threadPool") ThreadPool threadPool, @Name("scheduler") Scheduler scheduler,
              @Name("byteBufferPool") ByteBufferPool byteBufferPool)
{
    // Set the thread pool or create a default instance if null
    threadPool = (threadPool == null) ? new QueuedThreadPool() : threadPool;
    addBean(threadPool, "threadPool", true);
    ...
    // Set the scheduler or create a default instance if null
    scheduler = (scheduler == null) ? new ScheduledExecutorScheduler() : scheduler;
    addBean(scheduler, "scheduler", true);
    ...
    // Set the ByteBufferPool or create a default instance if null
    byteBufferPool = (byteBufferPool == null) ? new ArrayByteBufferPool() : byteBufferPool;
    addBean(byteBufferPool, "byteBufferPool", true);
```

getter 在 `Server.java:471`（`getThreadPool()`）与 `:477`（`getScheduler()`）。三个默认值都是「保守但够用」：`QueuedThreadPool` 走无参构造即 `maxThreads=200`，`ScheduledExecutorScheduler` 默认只有一颗线程的 `ScheduledExecutorService`（所以**绝不能把业务定时任务塞进 Scheduler**），`ArrayByteBufferPool` 按缓冲区分桶缓存。

| 组件 | 默认实现 | 关键默认值 | 源码位置 |
| :--- | :--- | :--- | :--- |
| ThreadPool | `QueuedThreadPool` | maxThreads 200、minThreads `Math.min(8, max)` | `QueuedThreadPool.java:125-133` |
| 队列 | `BlockingArrayQueue` | 名义容量 `Math.max(minThreads, 8) * 1024`，实际无界 | `QueuedThreadPool.java:181-182` |
| idleTimeout | — | 60000 ms | `QueuedThreadPool.java:137` |
| stopTimeout | — | 5000 ms | `QueuedThreadPool.java:177` |
| reservedThreads | — | `-1`（按启发式推导） | `QueuedThreadPool.java:114` |
| lowThreadsThreshold | — | 1（低于此值打告警） | `QueuedThreadPool.java:119` |
| tryExecutor | `TryExecutor.NO_TRY` | `doStart` 里替换为 `ReservedThreadExecutor` | `QueuedThreadPool.java:115, 224-244` |
| Scheduler | `ScheduledExecutorScheduler` | 单线程 | `Server.java:153` |
| ByteBufferPool | `ArrayByteBufferPool` | 分桶（`BufferCapacity`/`Retained`） | `Server.java:155` |

`QueuedThreadPool` 的类声明值得单独看一眼（`QueuedThreadPool.java:86`）：

```java
public class QueuedThreadPool extends ContainerLifeCycle implements ThreadFactory, SizedThreadPool, Dumpable, TryExecutor, VirtualThreads.Configurable
```

`SizedThreadPool` 意味着它可以被**租线程**，`VirtualThreads.Configurable` 意味着它可以被挂上一个虚拟线程执行器，`TryExecutor` 意味着它可以回答「你现在能不能立刻跑这个任务」。后两节分别展开。

## Two counter-intuitive QueuedThreadPool defaults

### Bounded queue logs WARN

```java
if (queue == null)
{
    int capacity = Math.max(_minThreads, 8) * 1024;
    queue = BlockingArrayQueue.newInstance(capacity, Integer.MAX_VALUE);
}
if (queue.remainingCapacity() != Integer.MAX_VALUE)
{
    LOG.warn("Detected thread pool queue {} bounded at {} entries, which can lead to unexpected behavior. Use an unbounded queue instead.", queue.getClass(), queue.remainingCapacity());
    _capacity = queue.remainingCapacity();
}
```

相对 `jetty-util-12.1.14/org/eclipse/jetty/util/thread/QueuedThreadPool.java:179-188`。

注意默认队列虽然名义上有个 `capacity`，但 `Integer.MAX_VALUE` 才是真正的上界，所以默认路径**不进** WARN 分支。类注释（`:48-53`）给了理由：已经提交的任务不能被拒绝——同一 HTTP 请求可能被拆成多个 job（请求头一个 job、每个数据帧一个 job、完成一个 job），此时因为队列满而拒绝后续 job，等于半途丢弃一个已经在处理的请求，还不如拒绝一条新连接。换句话说，Jetty 的背压手段是**连接数上限**（`SelectorManager` 的 `maxConnections`）和**超时**，不是队列长度。把 `ArrayBlockingQueue(500)` 塞进来的人通常是把 Tomcat 的 `acceptCount` 经验迁移错了。

### minThreads derived from maxThreads

`QueuedThreadPool(int maxThreads)` → `this(maxThreads, Math.min(8, maxThreads))`（`:130-133`）。也就是说 `new QueuedThreadPool(2)` 的 `minThreads` 是 2 而不是 8，`idleTimeout` 只在 `max > 8` 时才真正有意义。另有 `maxThreads < minThreads` 直接抛 `IllegalArgumentException`（`:172-173`）。

`doStart()` 里还有一处容易忽略的联动（`:224-244`）：`_reservedThreads == 0` 时 `_tryExecutor = NO_TRY`；否则先用静态启发式算一次，算出 0 仍然是 `NO_TRY`，算出正数才创建 `ReservedThreadExecutor` 并把池自身的 `idleTimeout` 传下去。

## ExecutionStrategy and AdaptiveExecutionStrategy

### Why EatWhatYouKill exists

假设只有「selector 线程收事件 + 池线程跑任务」这一个模型，就会遇到两个对立问题：

- 每个任务都 `execute()` 进池：任务切换开销、线程唤醒延迟、队头排队，小任务（读一个 TCP 分片、写一个响应头）的成本被放大数倍。
- 每个任务都在 selector 线程原地跑：一个阻塞的 handler 就让这颗核上所有连接停摆。

Jetty 的解法是让**生产者线程自己消费**（producer 也就是 consumer），但只在能安全地这么做时。这就是 `EatWhatYouKill`（EWYK）的原始动机。Jetty 12 已把它改名：

```java
 * <p>This strategy was previously named EatWhatYouKill (EWYK) because its preference for a
 * producer to directly consume the tasks that it produces is similar to a hunting proverb
 * that says that a hunter should eat (i.e. consume) what they kill (i.e. produced).</p>
 */
@ManagedObject("Adaptive execution strategy")
public class AdaptiveExecutionStrategy extends ContainerLifeCycle implements ExecutionStrategy, Runnable
```

相对 `jetty-util-12.1.14/org/eclipse/jetty/util/thread/strategy/AdaptiveExecutionStrategy.java:88-93`。改名不只是换词：旧名字只描述了「生产者吃掉自己产的东西」这一半行为，而新实现实际在四种消费方式之间按任务属性选择。

### Four sub-strategies and selection rule

`SubStrategy` 枚举（`:110-128`）与注释里的语义（`:41-57`）：

| 子策略 | 缩写 | 生产者线程做什么 | 任务在哪里跑 |
| :--- | :--- | :--- | :--- |
| `PRODUCE_CONSUME` | PC | 继续生产 | 原地直接 `run()` |
| `PRODUCE_INVOKE_CONSUME` | PIC | 继续生产 | 原地，但经 `Invocable.invokeNonBlocking` 包装 |
| `PRODUCE_EXECUTE_CONSUME` | PEC | 继续生产 | 交给线程池 `execute()` |
| `EXECUTE_PRODUCE_CONSUME` | EPC | 先把「后续生产」派给别的线程，自己消费，再与对方抢生产权 | 原地 |

选择规则（`:59-70`）：

1. 任务是 `NON_BLOCKING` → **PC**（既然不阻塞，就地跑完最省）。
2. 生产者线程本身不是 `NON_BLOCKING`，且能拿到一个待用生产者线程（已有一个，或 `TryExecutor.tryExecute()` 成功启动一个）→ **EPC**。
3. 任务是 `EITHER` 且未选中 EPC → **PIC**。
4. 其余 → **PEC**。

规则 2 是「租线程」存在的唯一理由：EPC 需要一个**立刻可得**的线程来接管生产，而这个线程不能来自排队（队列里等 50ms 的话还不如直接 PEC）。注释 `:72-74` 还提醒：因为偏好 PC，在核多且任务多为 `NON_BLOCKING` 的机器上，**可能需要多个策略实例才能把 CPU 喂满**——单个策略实例同一时刻只有一个生产者线程（见 `State` 状态机 `IDLE/PRODUCING/REPRODUCING`，`:100-105`）。

链式执行是刻意设计的（`:76-86`）：一个策略产出的任务本身可以是另一个策略的生产者（`ManagedSelector` 一个策略、其上的每个 `Connection` 又一个策略、HTTP/2 每个 stream 再一个）。嵌套时任务应申报为 `EITHER`，这样上层在没有待用生产者时可以以 `invokeNonBlocking` 方式直接调下层，**避免下层饿死**，又不至于阻塞上层最后一个生产者。

### Thread constraints of dispatch and produce

接口契约（`jetty-util-12.1.14/org/eclipse/jetty/util/thread/ExecutionStrategy.java:25-41`）：

- `dispatch()`：保证任务**绝不**由调用这个方法的线程执行。
- `produce()`：允许由调用线程自己执行。

`AdaptiveExecutionStrategy` 的实现把差异收敛到一处（`:158-205`）：

```java
if (execute)
{
    // Try to avoid queuing a producer if we can run it directly.
    if (!_tryExecutor.tryExecute(this))
        _executor.execute(this);
}
```

`dispatch()` 走状态机决定是否要新起一个生产者（`IDLE` → 需要跑，`PRODUCING` → 标记 `REPRODUCING` 由现任生产者回头处理），最终把自己作为任务交给 `_tryExecutor` 或 `_executor`，因此调用线程（通常是 HTTP 解析线程调用 `Request` 的完成路径）不会陷入长时间消费。`produce()` 则直接 `tryProduce()`。

构造器里有三行接线容易被跳过（`:145-156`）：

```java
_producer = producer;
_executor = VirtualThreads.getExecutor(executor);
_tryExecutor = TryExecutor.asTryExecutor(executor);
_isUseVirtualThreads = VirtualThreads.isUseVirtualThreads(executor);
```

也就是说：**策略持有的 executor 可能已经被换成虚拟线程 executor**，而是否换由 `VirtualThreads.Configurable` 决定。

### Who owns the strategy

`ManagedSelector` 每个实例持一个（`jetty-server-12.1.14/org/eclipse/jetty/server/ManagedSelector.java:88, 98-100`）：

```java
_strategy = new AdaptiveExecutionStrategy(new SelectorProducer(), executor);
```

所以 selector 数量（见 [Connector](/docs/CS/Framework/Jetty/Connector.md)）在效果上等于「并行生产者实例数」，而不只是文件描述符的分片单位。这与 Tomcat 的 Poller 语义差别很大。

## Thread leasing ThreadPoolBudget and ReservedThreadExecutor

Jetty 里「网络线程」和「业务线程」通常**是同一个池**，靠租约（lease）在预算上区分。`QueuedThreadPool` 类注释（`:55-63`）说得很直白：需要线程的组件（acceptor、selector）用 `ThreadPoolBudget` 从池里**租**线程；这些线程从池的角度算 active，但不能拿来跑未租用的 job（处理 HTTP 请求、WebSocket 帧）。

预算侧（`jetty-util-12.1.14/org/eclipse/jetty/util/thread/ThreadPoolBudget.java`）：`leaseTo()` 登记租约后立刻 `check(maxThreads)`（`:120-134`），不足时抛

```java
throw new IllegalStateException(String.format("Insufficient configured threads: required=%d < max=%d for %s", required, maxThreads, pool));
```

（`:143-150`）。这条异常是**启动期**失败，不是运行期抖动——所以「`maxThreads` 配成 4 但 selector 租掉 4」这类配置是起不来的，而不是慢慢劣化。

租线程侧（`jetty-util-12.1.14/org/eclipse/jetty/util/thread/ReservedThreadExecutor.java`）：`doStart()` 里 `_lease = ThreadPoolBudget.leaseFrom(getExecutor(), this, getCapacity())`（`:186`），容量由静态启发式决定（`:119-132`）：

```java
public static int reservedThreads(Executor executor, int capacity)
{
    if (capacity >= 0)
        return capacity;
    if (VirtualThreads.isUseVirtualThreads(executor))
        return 0;
    int cpus = ProcessorUtils.availableProcessors();
    if (executor instanceof ThreadPool.SizedThreadPool)
    {
        int threads = ((ThreadPool.SizedThreadPool)executor).getMaxThreads();
        return Math.max(1, MathUtils.ceilToNextPowerOfTwo(Math.min(cpus, threads / 8)));
    }
    return cpus;
}
```

三个结论直接可用于容量测算：默认 `reservedThreads = -1` 时，8 核 / `maxThreads=200` 得到 `ceilToNextPowerOfTwo(min(8, 25)) = 8` 个保留线程；`maxThreads=16` 时得到 `min(8,2)=2`；一旦给池挂了虚拟线程执行器，**保留线程数直接归 0**（因为不需要抢线程，见下一节）。

`tryExecute()`（`:213-231`）的语义是「有就立刻给，没有就失败」：从 `ThreadIdPool` `take()` 到一个 `ReservedThread` 就 `wakeup(task)` 返回 true；取不到则顺手 `startReservedThread()` 补充库存并返回 **false**——注意它不会阻塞等待，因此调用方（`AdaptiveExecutionStrategy.dispatch()`）能立刻退化到 `_executor.execute(this)`。`startReservedThread()` 受 `_maxPending` 限制（`:233-238`，默认 `maxPending == 0` 时取 capacity），避免被抢线程的请求把保留线程撑爆。

同一份租约预算还被 acceptor 与 selector 使用：`SelectorManager.defaultSelectors()` 通过 `SizedThreadPool.getMaxThreads()` 推导 selector 数，逻辑串在 [Connector](/docs/CS/Framework/Jetty/Connector.md)。

## InvocationType decides thread affinity

执行策略的选择规则全部依赖任务的 `InvocationType`（`BLOCKING` / `NON_BLOCKING` / `EITHER`），所以它其实是一个**线程模型声明**。传播链：

- `Handler.Abstract` 默认申报 `BLOCKING`（`jetty-server-12.1.14/org/eclipse/jetty/server/Handler.java:489, 497-498, 532-535`）——**这是有意的保守默认**：普通 handler 里可能有阻塞 IO。
- 想要 PC 就地跑，必须显式继承 `Handler.NonBlocking`（`:567-575`）或在 `onRequest` 里自己保证不阻塞。
- `Handler.AbstractContainer` 在 `_dynamic` 为真时 `getInvocationType()` 恒返回 `BLOCKING`（注释 `:577-585`）：动态增删子 handler 意味着聚合结果会变，缓存就不可信。
- `Server.getInvocationType()`（`:275-294`）三级判断：`isDynamic()` → `BLOCKING`；已 started → 直接返回缓存 `_invocationType`；否则从 `NON_BLOCKING` 起用 `Invocable.combine` 遍历 handler 树。缓存在 `doStart()` 里写入（`:632-634`），注释明确要求「handler 不得在服务器启动后改变 InvocationType」。

字段初值是 `InvocationType.NON_BLOCKING`（`:102`），配合 `getInvocationType()` 的 `isStarted()` 分支可以看出一个**陷阱**：在未启动的 Server 上查询聚合类型是实时遍历，在启动后是缓存值。运行期通过 `setHandler()` 换掉整棵树时，聚合值不会重算，而 `_dynamic` 是唯一能强制它退回 `BLOCKING` 的开关。

对线程模型的实际影响：`Server` 申报 `BLOCKING` 时，连接上的任务几乎只能走 PEC 或 EPC，selector 线程被强制解放、代价是多一次线程切换；申报 `NON_BLOCKING` 时才可能全程 PC（零切换）。这也是「Jetty 上纯异步 handler 吞吐高、同步 handler 优势小」的根因，请求侧细节见 [RequestFlow](/docs/CS/Framework/Jetty/RequestFlow.md)。

## Virtual threads

### Detection by reflection only

`jetty-util-12.1.14/org/eclipse/jetty/util/VirtualThreads.java:32` 的静态初始化在类加载时就完成探测（`:35` `private static final Executor executor = getNamedVirtualThreadsExecutor(null)`），实现是纯反射（`:144-157`）：

```java
Class<?> builderClass = Class.forName("java.lang.Thread$Builder");
Object threadBuilder = Thread.class.getMethod("ofVirtual").invoke(null);
if (StringUtil.isNotBlank(namePrefix))
    threadBuilder = builderClass.getMethod("name", String.class, long.class).invoke(threadBuilder, namePrefix, 0L);
ThreadFactory factory = (ThreadFactory)builderClass.getMethod("factory").invoke(threadBuilder);
return (Executor)Executors.class.getMethod("newThreadPerTaskExecutor", ThreadFactory.class).invoke(null, factory);
```

失败 `catch (Throwable x) { return null; }`，于是 `areSupported()`（`:91-94`）就是 `executor != null`。这个设计让 `jetty-util` 能编译在 Java 17 上运行在 Java 21+，但也意味着**探测发生在任何组件之前**：`VirtualThreadPool` 构造即判定。

### Configurable is the only hook

`VirtualThreads.Configurable`（`:201-224`）定义 `getVirtualThreadsExecutor()` / `setVirtualThreadsExecutor(Executor)`；`getVirtualThreadsExecutor(Executor)`（`:173-178`）只在参数实现了该接口时才返回其虚拟执行器，否则 `null`；`isUseVirtualThreads(Executor)`（`:188-193`）判「实现了接口**且**已配置」。`Configurable` 的默认 setter 在运行时不支持时抛 `UnsupportedOperationException`（`:217-224`）。注意 `isUseVirtualThreads()` 的 boolean 版本（`:231-234`）与 `setUseVirtualThreads(boolean)` 都已 `@Deprecated(forRemoval = true)`——12.1 的口径是「配了 executor 才叫启用」，不是布尔开关。

`QueuedThreadPool` 侧对应 `getVirtualThreadsExecutor()` / `setVirtualThreadsExecutor()`（`QueuedThreadPool.java:537, 543-547`，setter 校验运行时支持）。`Server` 里唯一显式走这条路的点在内部委托的 `execute`（`Server.java:970-973`）：

```java
VirtualThreads.execute(getThreadPool(), runnable);
```

即：**池上挂了虚拟执行器，Server 级任务就改投虚拟线程**；没挂就原样投递。这正是 `AdaptiveExecutionStrategy` 构造器里 `_executor = VirtualThreads.getExecutor(executor)` 的同一条机制。

### VirtualThreadPool is not a pool

类注释与声明（`jetty-util-12.1.14/org/eclipse/jetty/util/thread/VirtualThreadPool.java:30-38`）：「an implementation of `ThreadPool` interface that **does not pool**, but instead uses `VirtualThreads`」，`@ManagedObject("A thread non-pool for virtual threads")`，`extends ContainerLifeCycle implements ThreadPool, Dumpable, TryExecutor, VirtualThreads.Configurable`。

实现是 thread-per-task 加一个 `Semaphore`（`:50`），默认 `this(200)` 的 `maxTasks`（`:52-62`），运行时不支持就在构造期抛 `IllegalStateException("Virtual Threads not supported")`。12.1.6 起 `getMaxThreads()` / `setMaxThreads()` 已 `@Deprecated(forRemoval = true, since = "12.1.6")`，改名 `getMaxConcurrentTasks()` / `setMaxConcurrentTasks()`（`:87-120`）——**改名本身就是要抹掉「线程数」的错觉**：它限制的是并发 task 数，不是可创建的线程数。

语义连锁反应（判断依据是上面 `reservedThreads()` 的 `isUseVirtualThreads → 0` 分支与 `Semaphore` 的存在）：

- `ReservedThreadExecutor` 容量归 0，`_tryExecutor` 退化为 `NO_TRY`，EPC 子策略基本不再被选中，策略倾向 PC/PIC——虚拟线程上阻塞便宜，就地跑即可。
- 阻塞不再消耗 OS 线程，但 `maxConcurrentTasks` 变成真正的闸门：超出后 `execute()` 的行为由信号量决定，负载尖峰时的表现是「拿不到 permit」而不是「线程池排队」，`getQueueSize()` 这类指标失去意义。
- 线程名与 thread dump 形态改变（thread-per-task，`Thread.ofVirtual().name(prefix, 0)` 从 1 开始编号），基于「线程数 = 并发数」的监控与 arthas/jstack 经验需要重写。

### Differences from Tomcat

⚠️ Jetty 侧**不存在** `VirtualThreadExecutor` / `VirtualThreadsScopedScheduler` / `ScopedScheduler` 这三个类名（在 12.1.14 源码镜像 `jetty-util` / `jetty-io` / `jetty-server` 全量检索零命中）。`VirtualThreadExecutor` 是 Tomcat 的实现类（`tomcat-util-11.0.26/org/apache/tomcat/util/threads/VirtualThreadExecutor.java`）。把「Jetty 12 有 VirtualThreadExecutor」写进文章就是错的。

| 对照点 | Jetty 12.1 | Tomcat 11 |
| :--- | :--- | :--- |
| 入口类 | `VirtualThreadPool`（`util/thread/`） | `VirtualThreadExecutor`（`util/threads/`） |
| 接入方式 | 换成 `ThreadPool` bean，或给 `QueuedThreadPool` 挂 `setVirtualThreadsExecutor` | connector 上 `useVirtualThreads="true"` |
| 是否仍有池语义 | 无池，thread-per-task + `Semaphore` 限并发 | 无池，每任务一虚拟线程 |
| 与平台池共存 | 可共存（`QueuedThreadPool` + 虚拟执行器），选择权在 `ExecutionStrategy` | 通常整条 connector 切换 |
| 保留线程 | 自动归 0 | 无此概念 |
| 支持性探测 | 全反射，失败 `areSupported()==false` | 直接编译在支持版本上 |

Tomcat 侧细节见 [Tomcat 线程模型](/docs/CS/Framework/Tomcat/threads.md)。

## SerializedInvoker serializes callbacks

异步 servlet / 响应式流有两条回调链（`onDataAvailable`、`onAllDataRead`、`onError` 与写出侧的 `isReady`/`onWritePossible`），它们的**语义要求顺序执行、且不能并发**。如果每个回调都独立 `execute()` 进池，两个回调可能被两个线程同时取到，应用侧就得自己加锁。

`SerializedInvoker`（`jetty-util-12.1.14/org/eclipse/jetty/util/thread/SerializedInvoker.java:39`）用一条内部链表把提交串成单执行者：类注释同时给出两个关键约束（`:28-37`）——

```java
 * Ensures serial invocation of submitted tasks.
 * <p>
 * The {@link InvocationType} of the {@link Runnable} returned from this class is
 * always {@link InvocationType#BLOCKING} since a blocking task may be added to the queue
 * at any time.
```

所以**任何经 `SerializedInvoker` 包装的任务在执行策略眼里都是 BLOCKING**，永远不会被 PC 就地跑掉；注释还交代了灵感来源是 reactive-streams-servlet 的 `NonBlockingMutexExecutor`。同族的 `SerializedExecutor` 用于「按序但可并发执行」的场景（一次一个 task 交给 executor，前一个被 executor 取走后立刻提交下一个），适合 `ReadLineListener` 之类。

`HttpChannelState` 用的是子类化的 `HttpChannelSerializedInvoker`（`jetty-server-12.1.14/org/eclipse/jetty/server/HttpChannelState.java:115-116, 140-143`），`:141` 的注释点出它防的是什么：「prevent infinite recursion of callbacks calling methods calling callbacks」——比如 `onError` 回调里调 `complete()`，`complete()` 又触发 `onComplete`，再触发一次错误处理。串行化把这类重入收敛为「当前线程正在跑，新任务只入队」（配合 `isCurrentThreadInvoking()`，`:89`）。回调链整体见 [RequestFlow](/docs/CS/Framework/Jetty/RequestFlow.md)。

## executeImmediately for unqueueable tasks

`ThreadPool` 上有 `executeImmediately(Runnable)`（`TryExecutor`/`ThreadPool` 侧定义），语义在 `HTTP2ServerConnection.java:194-227` 的注释里说得很清楚：这类任务**不能被排队**，因为队列里可能根本没有线程能跑它，而它承载的是协议状态推进（收到 `SETTINGS`/`PING`/`WINDOW_UPDATE` 后必须向前推进一步，否则对端流控死锁）。

这与 HTTP/2 的多路复用直接相关：一条连接上多个 stream 共享同一个连接级策略实例，如果控制帧处理排在 200 个 stream 数据帧任务之后，就会出现「窗口不更新 → 对端停滞 → 我方线程全在等」的经典死锁。HTTP/2 的连接与流线程分工见 [HTTP/2](/docs/CS/Framework/Jetty/Http2.md)。

判断某个任务该不该走 `executeImmediately`，源码里能站得住的依据是：该任务是否是**协议前进的必要条件**，以及它是否保证不阻塞（否则就地跑会拖垮整个连接）。业务逻辑永远不该用它。

## Tuning and pitfalls

1. **acceptor 也在租线程**。每个 acceptor 从池里租 1 个线程，selector 各租 1 个，`ReservedThreadExecutor` 再租 `capacity` 个。`maxThreads` 必须显著大于这些租约之和，否则 `ThreadPoolBudget.check()` 在启动期直接 `IllegalStateException("Insufficient configured threads")`。反过来，把 `maxThreads` 调到刚好等于租用线程数会导致没有线程跑请求。
2. **保留线程用尽表现为「不收新连接」**。`tryExecute()` 失败不阻塞、不抛异常，策略退化成 `PEC`（任务进池排队）。当池同时被慢 handler 打满时，症状是连接在 TCP 层已被 accept 但迟迟不读、客户端看到超时，而 `getBusyThreads()` 已满。看 `getAvailable()`（`ReservedThreadExecutor.java:152-155`）与 `_pcMode/_pecMode` 计数器（`AdaptiveExecutionStrategy.java:130-133`，dump 里可见）区分「策略在退化」还是「池不够」。
3. **别把队列换成有界的**。见上文 WARN 分支；要限制并发用 `maxConnections` 或应用侧信号量，不要用队列长度做背压。连接数、accept 速率、低资源收缩与请求级限流的完整工具箱见 [Limiting](/docs/CS/Framework/Jetty/Limiting.md)。
4. **minThreads 太小会让突发变慢**。默认 `min(8, max)` 意味着低峰期只有 8 条线程存活，突发时要现场创建线程；对延迟敏感的服务显式把 `minThreads` 提到接近稳态并发。
5. **`_lowThreadsThreshold = 1`**（`QueuedThreadPool.java:119`）：可用线程低于 1 才告警，阈值很低，别指望日志能及时提示线程饥饿。
6. **handler 申报 `BLOCKING` 会吃掉 PC 优化**。默认的 `Handler.Abstract` 就是 `BLOCKING`；纯内存/纯异步的 handler 继承 `Handler.NonBlocking` 才能真正零切换。但一旦 handler 树里有动态容器（`_dynamic`），`Server.getInvocationType()` 恒为 `BLOCKING`（`Handler.java:577-585`），全局优化被拉平——这是「动态上下文」的真实代价。
7. **`Server` 启动后改 handler 的 InvocationType 不被允许**（`Server.java:632-634` 注释），缓存值不会重算。热更新 handler 树请同时考虑 `setDynamic(true)`。
8. **Scheduler 是共享的单线程**。`ScheduledExecutorScheduler` 默认只有一颗线程，任何耗时任务（清理、批量刷盘、外部探活）都会延后所有超时任务，包括连接空闲超时与请求超时。这类工作放自己的线程池，或给 scheduler 配 `ScheduledExecutorService`。
9. **VirtualThreadPool 下 `maxThreads` 语义变化**。`getMaxThreads()` 在 12.1.6 后已废弃，等价于 `getMaxConcurrentTasks()`，它不再对应任何 OS 线程数；`getBusyThreads()` / `getIdleThreads()` / `getQueueSize()` 等 `QueuedThreadPool` 指标也不适用。用虚拟线程时监控要换成 task 维度与 GC/内存指标。
10. **`getExecutor()` 返回的可能是虚拟线程执行器**。`AdaptiveExecutionStrategy` 构造里对 `_executor` 做了 `VirtualThreads.getExecutor(executor)` 替换（`:148`），排查线程名与实际执行位置的对应关系时注意这一层间接。

## Links

- [Jetty 架构与组件总览](/docs/CS/Framework/Jetty/Jetty.md)
- [Jetty Connector 与 SelectorManager](/docs/CS/Framework/Jetty/Connector.md)
- [Jetty 请求处理流程](/docs/CS/Framework/Jetty/RequestFlow.md)
- [Jetty HTTP/2 与流控](/docs/CS/Framework/Jetty/Http2.md)
- [Tomcat 线程模型](/docs/CS/Framework/Tomcat/threads.md)
- [Netty 线程模型](/docs/CS/Framework/Netty/Netty.md)

## References

- [Jetty 12 Programming Guide — Thread Pool](https://jetty.org/docs/jetty/12/programming-guide/arch/threads.html)
- [Jetty 文档首页](https://jetty.org/docs/)
