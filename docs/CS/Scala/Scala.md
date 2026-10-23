## Introduction

Scala 的定位可以压成一句话：**在 JVM 上把面向对象与函数式编程合并进同一套静态类型系统，同时不放弃与 Java 的二进制互操作**。这句话里三个约束互相拉扯：要表达力就得往类型系统里塞东西（高阶类型、联合与交集类型、match type、given/using 的上下文抽象）；要互操作就得老老实实编译成 JVM 字节码、遵守 JVM 的对象模型与内存模型；两者叠加的账单是编译速度与学习曲线——这也是 Scala 二十年里被攻击最多的两点。

Scala 3（编译器代号 dotty）不是语法糖的一次升级，而是把语言的理论基础从 Scala 2 的"特性叠加"换成 DOT 演算之上更小、更一致的一组核心原语，再把 union / intersection、given / using、extension method、opaque type、match type 全部还原成这组原语在不同位置的应用。理解这一点决定了本子树的读法：那些看起来零散的新语法其实是同一套原语的几种写法，而不是需要逐个背诵的特性清单。

版本基线：写作时 Scala 有两条分发线——**Scala Next 3.10.0（2026-10-12）** 面向应用，**Scala LTS 3.9.0（2026-09-03）** 是库作者的推荐发布基线；更早的 **3.3 LTS 3.3.8（2026-06-10）** 仍处于维护期，**Scala 2.13.18（2025-11-24）** 是 2 线的现状。自 Scala 3.8 起**最低 JDK 为 17**。所有"从哪个版本开始能用"的断言都收在 [版本线与迁移](/docs/CS/Scala/Migration_and_Versions.md) 里，本页只负责串线。

## Expressiveness Comes From Types, Not Syntax

第一条主线是类型系统。Scala 的表达力几乎全部来自这里，而它的特殊性在于：**类型层本身是一门可以编程的语言**。 [Type_System](/docs/CS/Scala/Type_System.md) 是地基——型变标注 `+A` / `-A` 不是注释而是编译期义务，交集类型 `A & B` 取代了 Scala 2 的 `A with B`（后者在 3.10 起已经是编译错误），联合类型 `A | B` 让"要么这个要么那个"不必再包一层 `Either`，opaque type 给出零包装成本的新类型，match type 则把模式匹配搬到了类型层。除此之外还有 dependent function type、polymorphic function type 与 context function `?=>`，三者构成了 Scala 3 表达"依赖于值的类型"的方式。

类型之上是可以被编译器自动找出来的值， [Contextual_Abstractions](/docs/CS/Scala/Contextual_Abstractions.md) 讲这套机制：Scala 2 那个被滥用也成就了类型类生态的 `implicit` 在 Scala 3 里被拆成两半——`given` 定义候选、`using` 声明需求，中间是同一套隐式搜索规则。类型类、`Conversion`、扩展方法的"橡皮管"都由它承担，而它也是调试体验最差的一块：搜索失败时编译器给出的信息量取决于你能否读懂候选集与优先级。

模式匹配是第三条腿， [Pattern_Matching](/docs/CS/Scala/Pattern_Matching.md) 覆盖 extractor、`sealed` 带来的穷尽性检查、`boundary` / `break` 提供的非局部退出，以及 multiversal equality 这条"默认允许一切比较、开启 `strictEquality` 后反过来"的取舍——SIP-67 让严格相等下的模式匹配不再需要 `CanEqual`，但严格相等本身仍是 opt-in。

日常写得最多的容器在 [Collections](/docs/CS/Scala/Collections.md) ：Scala 2.13 把集合库整体重写过一次， Scala 3 沿用了这套三层结构（`IterableOnce` → `Iterable` → 具体集合）。这里的要点是 `View` 的惰性、`ArraySeq` 取代 `Array` 的不可变视图，以及"同一个 `map` 在不同集合上有不同复杂度"这件事必须查表而不是猜。

## Everything Has to Land on the JVM

第二条主线是落地。Scala 再怎么函数式，产物仍然是 JVM 字节码，于是它必须回答"我这套抽象在 JVM 上变成了什么"。 [JVM_Interop](/docs/CS/Scala/JVM_Interop.md) 是双向的：从 Scala 看 Java（null、泛型擦除、原始类型、SAM 转换），从 Java 看 Scala（trait 被编成 interface 加静态/默认方法、`object` 的静态转发、Scala 3.8 起大幅改进的 Java 泛型签名）。互操作不是"能调用就行"，而是两边语义不对齐的地方会静默出错——比如 Scala 的 `==` 是 `equals` 语义而 Java 的 `==` 是引用比较。

编译过程本身在 [Compilation](/docs/CS/Scala/Compilation.md) ：Scala 3 的产物除了 `.class` 还有一份 **TASTy**（带类型的抽象语法树），它正是"库编译一次、后续版本都能用"这个输出兼容承诺的载体。同一个仓库里 Zinc 做增量编译，编译慢的根因是隐式搜索与类型检查而不是代码生成。

再往外一层是平台， [Platforms](/docs/CS/Scala/Platforms.md) 讲同一份源码在 JVM、Scala.js、Scala Native 三个后端上的差异：JS 端没有真线程、`Long` 的语义被近似；Native 端用 LLVM 提前编译、有自己的 GC 与一套 `unsafe` 指针 API，反射不可用。Scala.js 还多出一个 Wasm 后端。三端共用一套语言，但语义边界各自不同，这是"一次编写到处运行"在 Scala 里的真实含义。

## Concurrency Has Two Competing Answers

第三条主线是并发，也是 Scala 生态分歧最大的地方。 [Concurrency](/docs/CS/Scala/Concurrency.md) 从 JVM 侧讲起：`Future` 与 `ExecutionContext` 这套模型的传播语义（为什么捕获上下文会让人意外）、`Promise` 的单赋值约定、以及 Java 并发原语在 Scala 里的直接使用。它也交代 actor 模型这条支线——Akka 自 2022-10 起改用 BSL 1.1 许可（生产使用需商业授权，三年后自动转 Apache-2.0），Apache Pekko 是从 Akka 2.6.x 分叉出去的 Apache-2.0 替代。

另一条是纯函数式的效应系统， [Effects](/docs/CS/Scala/Effects.md) 讲 `IO` monad 这条路：Cats Effect、ZIO、Kyo 各自把"副作用"编码成值，换来可组合的资源安全、取消语义与结构化并发。真正值得注意的是方向变化——[虚拟线程](/docs/CS/Java/JDK/Loom.md) 到来之后，"直接式（direct style）"重新变得可行（Ox 就是这条路线），于是生态在"monad 编码"与"语言级能力 + 虚拟线程"之间重新站队，而 Scala 3 的 capture checking 一旦成熟，会把一部分效应追踪搬进类型系统。

## Compile-time Programming Is a Normal Tool

Scala 的一个独特之处是元编程被当成日常工具而非黑魔法。 [Macros](/docs/CS/Scala/Macros.md) 覆盖 `inline`、`quote` / `splice` 这套对称的多阶段编程，以及 Scala 2 宏被整体弃用这件事本身带来的后果：Scala 3 的宏操作的是带类型的树，而且必须跨编译单元（宏定义在另一项目里也照样工作），代价是宏的展开时机受 `inline` 语义约束。类型类派生（`derives`）、`Mirror`、编译期常量折叠都建立在这之上。

## Building and Choosing Libraries

工程侧的顺序也是固定的。 [Tooling](/docs/CS/Scala/Tooling.md) 讲构建与开发闭环：sbt 2.x 在 2026-06 正式发布（构建定义改用 Scala 3、最低 JDK 17、内置 Bazel 兼容缓存与 project matrix），Scala CLI 已经成为官方 `scala` 命令，Mill 提供另一种纯 Scala 对象的写法；编辑器侧是 Metals + BSP，格式化与重构是 Scalafmt / Scalafix，二进制兼容检查靠 MiMa。

选库是另一件事， [Ecosystem](/docs/CS/Scala/Ecosystem.md) 按职能分层给出 Typelevel 系（cats、cats-effect、fs2、http4s、doobie、circe、tapir）、ZIO 系、以及 Akka/Pekko 与 Play 的定位，并明确一个现实判断：**选 Typelevel 还是 ZIO 是阵营选择，混用代价很高**。

## Where Scala Sits Among Languages

横向看，Scala 的位置由它同时占住的两个格子定义。对 [Java](/docs/CS/Java/Java.md) 而言它共享全部生态与 [JVM](/docs/CS/Java/JDK/JVM/JVM.md) 运行时——包括 [GC](/docs/CS/memory/GC.md) 与 [JIT](/docs/CS/Java/JDK/JVM/JIT.md)——却把类型系统的表达力拉高一大截，代价是编译慢得多、代码风格差异极大；对 [Rust](/docs/CS/Rust/Rust.md) 而言两者都在类型系统里做重活，但 Rust 的活是内存安全、Scala 的活是抽象表达，前者没有 GC 而后者离不开；对 [Go](/docs/CS/Go/Go.md) 而言一个要极简与快速编译、一个要表达力，取向几乎相反；对 [Python](/docs/CS/Python/Python.md) 这类动态语言，Scala 把决策整体前移到编译期。语言级速览见 [编程语言横向对比](/docs/CS/Languages.md)。

Scala 最容易被误判的一点是"它就是更好的 Java"。这句话一半对——作为 Java 的替代品它确实成立；另一半错——当它被当成 Haskell 使用时，写出来的代码与 Java 风格几乎没有共同点，而这两种写法共用同一个编译器，正是它社区分裂与技术债的来源。

## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)
- [垃圾回收](/docs/CS/memory/GC.md)
- [编译原理](/docs/CS/Compiler/Compiler.md)
- [软件工程](/docs/CS/SE/Engineering.md)

## References

- [The Scala Programming Language](https://www.scala-lang.org/)
- [Scala 3 Reference](https://docs.scala-lang.org/scala3/reference/)
- [Scala 3 Book](https://docs.scala-lang.org/scala3/book/introduction.html)
- [Scala Development Guarantees（Next / LTS 与兼容性承诺）](https://www.scala-lang.org/development)
- [All Available Versions](https://www.scala-lang.org/download/all.html)
- [JDK Compatibility](https://docs.scala-lang.org/overviews/jdk-compatibility/overview.html)
