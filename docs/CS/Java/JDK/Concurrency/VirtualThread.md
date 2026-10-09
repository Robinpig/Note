## Introduction

Virtual threads are lightweight threads that dramatically reduce the effort of writing, maintaining, and observing high-throughput concurrent applications.

A platform thread is implemented as a thin wrapper around an operating system (OS) thread.
A platform thread runs Java code on its underlying OS thread, and the platform thread captures its OS thread for the platform thread's entire lifetime.
Consequently, the number of available platform threads is limited to the number of OS threads.

Platform threads typically have a large thread stack and other resources that are maintained by the operating system.
They are suitable for running all types of tasks but may be a limited resource.

Like a platform thread, a virtual thread is also an instance of `java.lang.Thread`.
However, a virtual thread isn't tied to a specific OS thread. A virtual thread still runs code on an OS thread.
However, when code running in a virtual thread calls a blocking I/O operation, the Java runtime suspends the virtual thread until it can be resumed.
The OS thread associated with the suspended virtual thread is now free to perform operations for other virtual threads.

Virtual threads are implemented in a similar way to virtual memory.
To simulate a lot of memory, an operating system maps a large virtual address space to a limited amount of RAM.
Similarly, to simulate a lot of threads, the Java runtime maps a large number of virtual threads to a small number of OS threads.

Unlike platform threads, virtual threads typically have a shallow call stack, performing as few as a single HTTP client call or a single JDBC query.
Although virtual threads support thread-local variables and inheritable thread-local variables,
you should carefully consider using them because a single JVM might support millions of virtual threads.

Virtual threads are suitable for running tasks that spend most of the time blocked, often waiting for I/O operations to complete.
However, they aren't intended for long-running CPU-intensive operations.

Use virtual threads in high-throughput concurrent applications, especially those that consist of a great number of concurrent tasks that spend much of their time waiting.
Server applications are examples of high-throughput applications because they typically handle many client requests that perform blocking I/O operations such as fetching resources.

Virtual threads are not faster threads; they do not run code any faster than platform threads.
They exist to provide scale (higher throughput), not speed (lower latency).

最后这句是最容易被误读成「反正在某些地方更快」的表述。虚拟线程不改变任何一段代码的执行成本，
它改变的是**同时进行的段数**：单请求延迟不变，吞吐随等待时间被摊薄而上升。所以适用性判断只有一个问题：
**这段代码大部分时间在等吗？** 等 → 受益；算 → 换成虚拟线程只是把 CPU 争抢换了个形式。

## Scheduling

虚拟线程由 JVM 调度到一组平台线程上运行，这些平台线程叫 **carrier thread**（载体线程）。
M:N 映射的结构与内核里的线程模型是同一套概念，可对照
[语言运行时与内核任务](/docs/CS/OS/Linux/proc/runtime.md) 里的 M:N 模型。

两个关键机制：

- **Mount / Unmount（挂载 / 卸载）**。虚拟线程执行时 mount 到某个 carrier 上；遇到 Loom 已接管支持的阻塞操作
  （socket I/O、`LockSupport.park`、各类锁与队列的等待）时，JVM 把它的栈从 carrier 上**剥离**（unmount），
  carrier 立刻能去跑别的虚拟线程。操作就绪后再重新 mount，**可能换到另一个 carrier**。
- **Continuation（续体）**。剥离下来的执行状态保存在堆上的 continuation 对象里，而非 OS 栈上。
  `VirtualThread.java` 里能看到这套结构的入口：

```java
private static final ContinuationScope VTHREAD_SCOPE = new ContinuationScope("VirtualThreads");

private static class VThreadContinuation extends Continuation {
    VThreadContinuation(VirtualThread vthread, Runnable task) {
        super(VTHREAD_SCOPE, wrap(vthread, task));
    }
```

虚拟线程的状态机在源码里是这么分的——注意 `mounted` / `unmounted` 的注释，以及**仍然存在的 pinned 状态**：

```java
private static final int NEW      = 0;
private static final int STARTED  = 1;
private static final int RUNNING  = 2;     // runnable-mounted
private static final int PARKING       = 3;
private static final int PARKED        = 4;     // unmounted
private static final int PINNED        = 5;     // mounted
private static final int TIMED_PARKING = 6;
private static final int TIMED_PARKED  = 7;     // unmounted
private static final int TIMED_PINNED  = 8;     // mounted
private static final int UNPARKED      = 9;     // unmounted but runnable
```

这套状态机本身就是「是否还会 pinning」的直接证据：`PINNED` / `TIMED_PINNED` **没有在 JDK 24 被删掉**。

### Carrier Scheduler

调度器是一个 `ForkJoinPool`（见 [ForkJoinPool](/docs/CS/Java/JDK/Concurrency/ForkJoinPool.md)），
两个参数来自系统属性，默认值写在 `Thread` 的 javadoc 里：

| 属性 | 含义 | 默认 |
| --- | --- | --- |
| `jdk.virtualThreadScheduler.parallelism` | 可用于调度虚拟线程的平台线程数 | **可用处理器数** |
| `jdk.virtualThreadScheduler.maxPoolSize` | 调度器可用的平台线程上限 | **256** |

`maxPoolSize` 不是并发上限，而是**防饿死的安全阀**。默认 parallelism 等于 CPU 核数，
意味着只要有 N 个虚拟线程同时被 pin 住，调度器就会临时扩容到 `maxPoolSize`；再往上就彻底没有 carrier 可用，
表现为所有虚拟线程一起停顿——这就是「pinning 导致的调度器饿死」。

## Pinning

**Pinning**（钉住）指虚拟线程无法从 carrier 上卸载，carrier 被占住无法服务其它虚拟线程。
它是虚拟线程扩展性的唯一硬约束，而且**不会产生任何报错**——功能完全正确，只是吞吐塌陷，
很容易被误判成「虚拟线程没用」。

虚拟线程被 pin 住只有两个真正的原因：

1. **在 `synchronized` 内阻塞**——只在 JDK 21～23 成立，**JDK 24 已修复**（见下节）。
2. **栈上有 native 帧**——所有版本都成立。JNI 调用、Foreign Function & Memory API 的 downcall、
   以及类加载/类初始化期间，都属于这一类。JVM 无法跨 native 帧边界安全管理线程状态，必须托住 carrier。

源码里的 pinning reason 枚举把四个原因列全了（`jdk.internal.vm.Continuation`），
可以直接看出 `MONITOR` 已不再是主要矛盾：

```java
/** Reason for pinning */
public enum Pinned {
    /** Native frame on stack */ NATIVE,
    /** Monitor held */          MONITOR,
    /** In critical section */   CRITICAL_SECTION,
    /** Exception (OOME/SOE) */  EXCEPTION
}
```

`CRITICAL_SECTION` 与 `EXCEPTION` 都是短暂的（`PreemptStatus` 里对应 `TRANSIENT_FAIL_*`），
真正需要长期警惕的只有 `NATIVE`。

### JEP 491

在 JDK 21～23，「在 `synchronized` 里做阻塞 I/O」是 pinning 的头号来源，也是官方推荐用 `ReentrantLock`
替换 `synchronized` 的原因。**JDK 24 的 JEP 491 从根上解决了它**：HotSpot 改为把 monitor 的归属
从 carrier 线程改为**虚拟线程本身**，因此虚拟线程可以在持有 monitor、等待进入 monitor、
以及 `Object.wait()` 期间正常卸载。互斥语义完全不变。

这条变更带来两个后果，其中第二条常被忽略：

- **「为了避免 pinning 而用 `ReentrantLock` 替换 `synchronized`」这条建议作废了**。
  现在可以纯粹按语义需求选锁：要超时获取、可中断获取、公平策略、多个 `Condition`，
  就用 `ReentrantLock`；只是要互斥，`synchronized` 往往更简单、更不容易写错。
- **`-Djdk.tracePinnedThreads` 这个诊断开关被删除了**。它在 JDK 21～23 会对每次 pinning 打印完整栈，
  开销大且输出嘈杂，官方认定「has proven very problematic and no longer useful」。
  我在 JDK 25 源码里全量搜过这个词，**零命中**——它确实不在了。
  现在诊断 pinning 要用 JFR 的 `jdk.VirtualThreadPinned` 事件（JEP 491 同时扩充了它的触发场景与信息量，
  包括 pinning 的原因和对应的 carrier 线程）：

```bash
jcmd JFR.start duration=200s filename=recording.jfr
jfr print --events jdk.VirtualThreadPinned recording.jfr
```

剩下的 pinning 需要别的手段缓解：把 JNI / FFM 调用挪到**专用的平台线程池**上执行，
与虚拟线程调度器隔离，避免它们占用 carrier 槽位。

## Bounding Resources

虚拟线程便宜，但它操作的下游资源并不便宜——数据库连接、HTTP 连接、文件描述符、远程 API 配额都还是有限的。
这里有个反直觉的陷阱：**过去由线程池大小提供的天然限流消失了**。

改造前 200 个平台线程的池子，顺带限制了「最多 200 个并发数据库查询」。
换成虚拟线程后线程数不再自然受限，瓶颈退到数据库连接池上——此时可能有几十万个虚拟线程在抢 20 个连接，
数量上毫无意义，排队与超时反而更糟。

解决办法是**显式用信号量表达资源真实容量**，而不是凭线程池大小去凑：

```java
private static final Semaphore DB_CONNECTIONS = new Semaphore(20);

void handleQuery() throws InterruptedException {
    DB_CONNECTIONS.acquire();
    try {
        queryDatabase();
    } finally {
        DB_CONNECTIONS.release();
    }
}
```

`Semaphore` 的许可数应当等于**受限资源的实际容量**（连接池大小），而不是照抄平台线程池时代习惯上的那个小数字。
相关 API 见 [Semaphore](/docs/CS/Java/JDK/Concurrency/Semaphore.md)。

同理，CPU 密集型任务应当继续留在**有界的平台线程池**里，否则纯计算任务会抢占 carrier，
让等待中的 I/O 型虚拟线程拿不到执行机会——虚拟线程的调度是公平队列，不区分任务类型。

## ThreadLocal

虚拟线程**支持** `ThreadLocal` 与 `InheritableThreadLocal`，但这恰恰是风险点。
百万虚拟线程各自持有一份可变上下文槽位，内存开销会被放大，且线程池式复用带来的串号问题依旧存在。

JDK 25 的 [ScopedValue](/docs/CS/Java/JDK/Concurrency/ScopedValues.md) 已转正（JEP 506），是官方给出的替代方案：
绑定后不可变、生命周期随作用域有界、跨线程只在
[StructuredTaskScope](/docs/CS/Java/JDK/Concurrency/StructuredTaskScope.md) 的 fork 处只读继承。
请求上下文（用户身份、trace id、租户）这类只读数据应当优先用它。

## API

创建虚拟线程有三层接口，按方便程度递增：

```java
// 1. 一次性：直接启动
Thread t = Thread.ofVirtual().start(runnable);

// 2. 工厂：交给 ExecutorService 用
ExecutorService executor = Executors.newVirtualThreadPerTaskExecutor();

// 3. Builder：命名 / 传参 / 继承未捕获异常处理器
Thread t = Thread.ofVirtual()
                 .name("worker-1")
                 .unstarted(() -> { System.out.println(Thread.currentThread()); })
                 .start();
```

判断当前线程类型用 `Thread.isVirtual()`（JDK 21+）。`Thread.ofPlatform()` 是对应的平台线程入口。

平台线程的 API 基本都还可用——`start()`、`join()`、`interrupt()`、线程组、`ThreadLocal` 全都能用，
这是虚拟线程能平滑替换平台线程的关键设计：它就是 `Thread` 的一个子类，不是新概念。
几处需要留意的语义差异：

- `setPriority` 在虚拟线程上是**静默无操作**。源码里只校验参数范围，虚拟线程直接跳过赋值，
  **不抛异常**，所以误用它不会暴露问题、但也不会生效（虚拟线程的优先级固定为普通优先级）；
- `setDaemon` 在虚拟线程上只能传 `true`，传 `false` 会抛 `IllegalArgumentException`
  （源码里显式检查 `isVirtual() && !on`）；虚拟线程本身恒为守护语义，不会阻止 JVM 退出；
- 平台线程的 `Thread.stop()` 早已移除，两种线程都不支持。

`Builder` 是 `sealed interface`，`ofVirtual()` 返回 `OfVirtual`，后者覆写各方法以返回自身类型因而可以链式调用。
完整方法集在父接口 `Builder` 上：`name(String)`、`name(String prefix, long start)`、
`inheritInheritableThreadLocals(boolean)`、`uncaughtExceptionHandler(...)`、`unstarted(Runnable)`、
`start(Runnable)`、`factory()`。

其中 `name(String prefix, long start)` 值得单独提：它生成带序号的线程名（`worker-0`、`worker-1`…），
序号在每次创建线程后自增，用于让线程名在 dump 里可读——这是排查虚拟线程问题时最实用的一个技巧，
因为虚拟线程数量巨大，没有可辨识的名字几乎无法诊断：

```java
ThreadFactory factory = Thread.ofVirtual().name("http-worker-", 0).factory();
```

## Links

- [StructuredTaskScope](/docs/CS/Java/JDK/Concurrency/StructuredTaskScope.md) — 与之配套的结构化并发
- [ScopedValue](/docs/CS/Java/JDK/Concurrency/ScopedValues.md) — 海量虚拟线程下传递只读上下文
- [Java Thread](/docs/CS/Java/JDK/Concurrency/Thread.md) — 平台线程的完整机制
- [Semaphore](/docs/CS/Java/JDK/Concurrency/Semaphore.md) — 资源限流
- [Asyncio](/docs/CS/Python/Asyncio.md)
- [语言运行时与内核任务](/docs/CS/OS/Linux/proc/runtime.md) — M:N 模型与 carrier、栈、切换成本对照

## References

1. [JEP 444: Virtual Threads](https://openjdk.org/jeps/444)
2. [JEP 491: Synchronize Virtual Threads without Pinning](https://openjdk.org/jeps/491)
3. [JEP 506: Scoped Values](https://openjdk.org/jeps/506)
4. [Thread (Java 25 API)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Thread.html)