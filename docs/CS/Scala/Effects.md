## Introduction

Scala 生态里最大的一次路线分歧，发生在"副作用该怎么编码"这件事上。一边是 JVM 原生的 `Future`——简单、与 Java 兼容，但一经创建立即执行、需要显式线程池、无法取消、资源安全靠手写 `try/finally`；另一边是把副作用编码成**值**的效应系统：`IO[A]` 只是"一段尚未发生的计算的描述"，什么时候跑、跑在哪个线程池、被打断时如何清理，全部由组合子决定。

本篇讲第二条路：为什么需要它、Cats Effect / ZIO / Kyo 各自的抽象、资源安全与取消语义、以及 [虚拟线程](/docs/CS/Java/JDK/Loom.md) 到来之后"直接式（direct style）"的回归如何改变这个格局。并发的 JVM 底层原语与 actor 模型见 [并发](/docs/CS/Scala/Concurrency.md)；流处理（fs2 / ZIO Stream）属于同一阵营，在本篇末尾点到。

## Why Future Is Not Enough

```scala
def fetch(id: Int)(using ec: ExecutionContext): Future[User] = ???

val f = fetch(1)     // 注意：调用即已开始执行
```

`Future` 的三个结构性限制：

1. **它是 eager 的**——构造即提交，所以"描述一段计算"和"执行一段计算"无法分开，重试、延迟、并发组合都要额外机制；
2. **取消是协作式的软取消**——没有传播机制，`f.cancel()` 并不存在，中断一个正在跑的计算做不到；
3. **资源安全靠约定**——`try/finally` 或 `loan pattern`，嵌套资源时样板迅速膨胀。

`Future` 还有一个隐性依赖：`ExecutionContext` 通常靠 `using`（Scala 2 是 implicit）传入，而全局 `ExecutionContext.global` 是 fork-join 池，一旦在里面做阻塞调用就会把线程池饿死。这条依赖在签名上几乎不可见，是生产事故的常见来源。

## Encoding Effects as Values

效应系统的核心主张只有一句：**把"做什么"和"何时做"分开**。

```scala
// cats-effect
val program: IO[Unit] =
  for
    _ <- IO.println("start")
    u <- fetchUser(1)
    _ <- IO.println(s"got $u")
  yield ()

program.unsafeRunSync()      // 唯一一处真正执行

// ZIO
val zprog: ZIO[Any, Throwable, Unit] =
  for
    _ <- Console.printLine("start")
    u <- fetchUserZ(1)
    _ <- Console.printLine(s"got $u")
  yield ()
```

三个参数的差别是选型时最实际的判断依据：

| 库 | 类型形状 | 错误通道 | 依赖通道 | 取向 |
| :--- | :--- | :--- | :--- | :--- |
| cats-effect | `IO[A]` | 固定为 `Throwable` | 无（靠 `Resource` / Reader 模式） | 最小、类型类驱动、Typelevel 生态通用底座 |
| ZIO | `ZIO[R, E, A]` | 任意 `E` | `R` | 电池全含：并发、流、配置、测试、日志一体 |
| Kyo | `A < S`（effect set） | 代数效应风格 | 通过 effect set 累积 | 直接式 + 代数效应，较新 |

`IO[A]` 的错误通道固定为 `Throwable`，所以业务错误要么自己用 `Either` 包一层（`IO[Either[Err, A]]`），要么用 `MonadError` 抽象；ZIO 的 `E` 让业务错误类型化，代价是签名变长、类型推断压力更大。

## Resource Safety and Cancellation

效应系统最不可替代的能力是**资源与取消的组合语义**：

```scala
// cats-effect
def withFile[A](path: String)(f: InputStream => IO[A]): IO[A] =
  Resource.make(IO.blocking(new FileInputStream(path)))(s => IO.blocking(s.close()).void)
    .use(f)

// ZIO
ZIO.acquireRelease(open)(close).flatMap(...)
```

`Resource` / `Scope` 保证：无论正常结束、抛错、还是被取消（包括外部中断和并发组合里的 `race` 输掉），close 都会被执行，并且**按获取的逆序**执行。这个保证写出来只要一层 `Resource.make`，手写则要嵌套的 `try/finally` 加状态标志——这就是效应系统的实际价值所在，而不是"代码更好看"。

取消是配套的：cats-effect 的取消是协作式的，在 `uncancelable` 区间之外、在每个组合子边界（"yield point"）检查取消信号；因此**不可打断的操作必须包在 `IO.uncancelable` 或 `IO.blocking` 里**，否则 cleanup 可能被中断。这个模型与 Go 的 [context](/docs/CS/Go/Concurrency/Context.md) 取消在思想上同源，但 Scala 这边由类型系统（而非约定）承担传播责任。

## Concurrency Combinators

并发不再是"手动起线程再等结果"，而是组合子：

```scala
List(url1, url2, url3).parTraverse(fetch)      // 并行遍历，失败即整体失败
IO.race(first, second)                         // 竞速，输的一方被取消
IO.both(a, b)                                  // 二者都跑，返回对
// 显式 fiber（轻量协程）：父作用域取消时子 fiber 一并取消
for
  fiber <- task.start
  _     <- otherWork
  a     <- fiber.join
yield a
```

这几条组合子把"结构化并发"变成默认：父计算被取消时子 fiber 一并取消，作用域结束时不允许子 fiber 泄漏。这一点与 [Go 的 errgroup](/docs/CS/Go/Concurrency/errgroup.md) 是同一类问题的两种回答——Go 靠库与 `context`，Scala 靠类型与 fiber 树。

## Direct Style Returns

[Loom 虚拟线程](/docs/CS/Java/JDK/Loom.md) 落地之后，生态里出现了明显的反向运动：**既然一个虚拟线程的成本已经接近一次函数调用，为什么还要把每个副作用都包进 monad？**

```scala
// direct style（Ox 风格）：看起来就是普通阻塞代码，底层是虚拟线程
def handle(id: Int)(using Ox, StandardInterpreter): User =
  val user = fetchUser(id)          // 阻塞，但跑在虚拟线程上
  log.info(s"got $user")
  user
```

这条路线的代表是 Ox（SoftwareMill）与 Kyo 的 direct style 支持。它的主张是：虚拟线程提供了廉价阻塞，于是"阻塞写法 + 结构化并发作用域"就够了，不需要 `IO` 的包装；取消与资源安全由作用域（`Ox` 的 `supervised`、JDK 的 `StructuredTaskScope`）而非类型提供。

两种路线并不是非此即彼，但选型时必须明确：

| 维度 | 效应系统（IO monad） | 直接式 + 虚拟线程 |
| :--- | :--- | :--- |
| 副作用是否进类型 | 是，`IO[A]` 与 `A` 区分 | 否，签名看不到 |
| 取消传播 | 类型层保证，组合子自动 | 作用域 + 中断，靠约定 |
| 与 Java 库互操作 | 需要 `IO.blocking` 包装 | 天然一致 |
| 学习成本 | 高（monad、fiber、Resource） | 低（就是普通代码） |
| 成熟生态 | 大（http4s、doobie、fs2） | 较新 |

值得注意的是 Scala 3 的 **capture checking**（实验特性，见 [类型系统](/docs/CS/Scala/Type_System.md)）瞄准的正是中间地带：让"这个函数捕获了 IO 能力"进入类型，同时保留直接式的写法。它成熟与否决定了 Scala 长期会落在哪一侧。

## Streams

流是效应系统的自然延伸：一旦副作用是值，"一串带副作用的元素"就是 `Stream[F, A]`（fs2）或 `ZStream`：

```scala
// fs2：拉取式、资源安全、自带背压
Files[IO].readAll(path)
  .through(text.utf8.decode)
  .through(text.lines)
  .filter(_.nonEmpty)
  .evalMap(line => process(line))
  .compile.drain
```

与 [Akka Streams](/docs/CS/Scala/Ecosystem.md) 的对比是：fs2 的背压来自拉取语义（下游拉上游），Akka Streams 的背压来自 Reactive Streams 的 request-n 协议；前者是纯函数式的，后者是 actor 之上的反应器实现。

## Links

- [Scala](/docs/CS/Scala/Scala.md)
- [并发](/docs/CS/Scala/Concurrency.md)
- [上下文抽象](/docs/CS/Scala/Contextual_Abstractions.md)
- [生态系统](/docs/CS/Scala/Ecosystem.md)
- [Loom（虚拟线程）](/docs/CS/Java/JDK/Loom.md)

## References

- [Cats Effect documentation](https://typelevel.org/cats-effect/)
- [ZIO documentation](https://zio.dev/)
- [Ox — direct style Scala concurrency](https://ox.softwaremill.com/)
- [fs2 — functional streams](https://fs2.io/)
- [Scala 3 capture checking（实验）](https://docs.scala-lang.org/scala3/reference/experimental/cc.html)
