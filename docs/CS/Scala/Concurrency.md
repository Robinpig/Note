## Introduction

Scala 跑在 JVM 上，因此它的并发故事必须分层讲：**最底层是 JVM 的内存模型与锁原语**，中间是 Scala 自己的 `Future` / `Promise` 封装，再往上才是生态里的 actor 与效应系统。这三层经常被混谈，而绝大多数并发 bug 来自"以为自己在用第三层，实际行为由第一层决定"。

本篇讲底层与中间层：JMM 在 Scala 里的可见性规则、`Future` 的执行语义与陷阱、直接使用 `java.util.concurrent` 的场合、以及 actor 模型这条支线（含 Akka 的许可变化）。把副作用编码成值的高层方案在 [函数式效应系统](/docs/CS/Scala/Effects.md)；JVM 本身的线程与内存模型在 [JVM](/docs/CS/Java/JDK/JVM/JVM.md) 与 [JDK](/docs/CS/Java/JDK/JDK.md)。

## The JVM Floor

Scala 没有自己的内存模型——它直接继承 JMM，所有可见性问题与 Java 完全一致：

```scala
@volatile private var running = true        // 保证跨线程可见
private val lock = new Object()

def increment(): Unit = lock.synchronized { count += 1 }   // 互斥 + 可见性
```

要点：

- `@volatile` 只保证可见性与禁止重排序，**不保证复合操作的原子性**（`x += 1` 仍需锁或原子类）；
- `synchronized` 是可重入的互斥锁，退出时释放并建立 happens-before；
- 原子类（`AtomicInteger`、`AtomicReference`、Java 8 的 `LongAdder`）是无锁路径，Scala 直接用即可；
- 不可变值（`case class` 的 `val` 字段、不可变集合）天然线程安全，这是 Scala 偏函数式风格在并发上的实际收益。

实践上的默认建议是：**共享可变状态要么用 `AtomicReference` 存一个不可变快照，要么用 actor 串行化**，不要靠"小心一点"来维持正确性。

## Future: Eager, Context-carrying

```scala
import scala.concurrent.{Future, Promise}
import scala.concurrent.ExecutionContext

def fetch(id: Int)(using ec: ExecutionContext): Future[User] =
  Future { httpGet(s"/users/$id") }        // 立即在某个线程上开始执行

val p = Promise[Int]()
p.success(42)                              // 只能成功一次，再 success 抛异常
```

`Future` 的几个性质必须记牢：

1. **eager**：`Future { ... }` 在构造时提交，所以"定义"与"执行"不可分；要惰性就用 `IO` 或者 `Future` 外面再包一层。
2. **需要 `ExecutionContext`**：通常靠 `using`（Scala 2 是 `implicit`）传入。全局的 `ExecutionContext.global` 是 fork-join 池，**在里面做阻塞 IO 会饿死线程池**——阻塞调用要么用 `scala.concurrent.blocking { ... }` 包住（让池扩容），要么用专门的阻塞池。
3. **回调而非阻塞**：`map` / `flatMap` / `recover` / `zip` / `sequence` 都是回调式组合；`Await.result` 只应在测试与程序边界使用，在业务代码里用它等于把一个异步模型硬改回同步。
4. **无取消**：`Future` 没有取消机制，`Promise.tryFailure` 只能让等待方失败，跑着的计算不会停。

这套模型的适用边界很清楚：简单的并行调用、与 Java 异步 API 对接、以及不想引入效应系统的小项目。一旦需要取消、资源安全、并发上限与统一错误处理，就该转到 [效应系统](/docs/CS/Scala/Effects.md)。

## Use java.util.concurrent Directly

并发原语层面 Scala 没有替代品，也不需要：线程池、信号量、闩锁、并发集合全部直接用 JDK 的。

| 需求 | 直接用 |
| :--- | :--- |
| 固定大小的线程池 | `Executors.newFixedThreadPool` → 转成 `ExecutionContext.fromExecutor` |
| 限流 | `Semaphore` |
| 等待一组任务 | `CountDownLatch` / `CompletableFuture.allOf` |
| 并发容器 | `ConcurrentHashMap`、`ConcurrentLinkedQueue` |
| 定时任务 | `ScheduledExecutorService`（或用 [JDK 的 timer 设施](/docs/CS/Java/JDK/sche.md)） |

把这些配成 `ExecutionContext` 是 Scala 侧唯一要做的事，**不同用途的池要分开**（CPU 密集、阻塞 IO、定时任务各一个），这是避免"一个线程池被一种任务占满"的标准做法。

## Actors: Akka, Pekko, and a License Fork

actor 模型提供另一条路：**状态私有、通过消息通信、由监督策略决定失败后怎么办**。它是 Erlang 那条路线在 JVM 上的实现，适合有状态的分布式服务。

历史与现实要分开说：Akka 自 2022-10 起改用 **BSL 1.1**（Business Source License）许可，生产使用需要 Lightbend 的商业授权，每个版本在发布三年后自动转为 Apache-2.0。**Apache Pekko** 是从 Akka 2.6.x（BSL 之前）分叉出来的 Apache-2.0 项目，是最接近的开源替代。这个分叉是 Scala 生态近年最重要的事件之一：它把生态按许可切成两半，也让"选型必须先查许可"成为常态。

actor 的核心语义：

- 每个 actor 一次只处理一条消息，因此**actor 内部的状态不需要锁**；
- mailbox 是有界的还是无界的决定背压是否存在（无界 mailbox + 慢消费者 = 内存增长）；
- 监督（supervision）决定子进程失败后是重启、停止还是上报；
- 集群扩展（cluster sharding、分布式数据）把"按 key 分布的有状态实体"变成内建能力。

actor 与效应系统不是竞争关系而是层次不同：前者是"状态在哪里"的答案，后者是"副作用怎么组织"的答案；Akka/Pekko 内部也可以用 `Future` 或 Pekko 的 typed actor + `AskPattern`。

## Virtual Threads Change the Calculus

[JDK 21 起的虚拟线程](/docs/CS/Java/JDK/Loom.md)让"一个请求一个线程"重新可行，Scala 侧的变化是：

- Scala 代码不需要改写即可使用虚拟线程——`Executors.newVirtualThreadPerTaskExecutor()` 配成 `ExecutionContext` 就行；
- 阻塞调用不再需要特殊线程池，这直接削弱了"必须用 `IO` 才能避免线程耗尽"这一论证的一半；
- 结构化并发由 JDK 的 `StructuredTaskScope` 或库（Ox）提供，父作用域退出时子任务一并结束；
- 代价是**pinning**：在 `synchronized` 块或 native 方法里阻塞会把虚拟线程钉在载体线程上，因此旧的同步代码迁移过来未必立刻受益。

这也是 [效应系统](/docs/CS/Scala/Effects.md) 那篇里"直接式回归"的技术背景。Scala Native 侧则相反——它从 0.5.12 起才有实验性的虚拟线程实现（仅 Unix，依赖 continuation，且需 LLVM 16+），见 [平台](/docs/CS/Scala/Platforms.md)。

## Diagnosis

并发问题的排查顺序与其他 JVM 语言一致：

1. 数据竞争靠 `ThreadSanitizer` 或 JVM 的 `-XX:+UseThreadPriorities`… 实际上 Scala 生态没有专用 race detector，靠 [Java 的内存模型](/docs/CS/Java/JDK/JVM/JVM.md) 推理 + 压测；对比 [Go 的 race detector](/docs/CS/Go/Concurrency/RaceDetector.md) 会发现 JVM 侧缺少这一等工具是真实劣势。
2. 线程池耗尽表现为吞吐骤降而无异常，用 `jstack` / `jcmd Thread.print` 看线程栈，看是否大量线程卡在同一阻塞点。
3. 死锁看 `jstack` 的 "Found one Java-level deadlock" 段。

## Links

- [Scala](/docs/CS/Scala/Scala.md)
- [函数式效应系统](/docs/CS/Scala/Effects.md)
- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
- [Loom（虚拟线程）](/docs/CS/Java/JDK/Loom.md)
- [集合库](/docs/CS/Scala/Collections.md)

## References

- [Futures and Promises（Scala 官方文档）](https://docs.scala-lang.org/overviews/core/futures.html)
- [Akka documentation](https://doc.akka.io/docs/akka/current/index.html)
- [Akka BSL License FAQ](https://akka.io/bsl-license-faq)
- [Apache Pekko](https://pekko.apache.org/)
- [JDK Compatibility for Scala](https://docs.scala-lang.org/overviews/jdk-compatibility/overview.html)
