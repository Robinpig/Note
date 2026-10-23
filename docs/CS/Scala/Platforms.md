## Introduction

同一份 Scala 源码可以编译到三个不同的后端：JVM、JavaScript（Scala.js）、以及本地机器码（Scala Native）。它们共用同一门语言与大部分标准库，但**不共用同一套运行时语义**——JS 端没有真正的线程，`Long` 是近似的，反射不可用；Native 端是提前编译，有自己的 GC 与一套指针 API，同样没有反射。

"一次编写到处运行"在 Scala 里的真实含义是：**源码可移植，语义边界各不相同**。本篇讲三端的差异表、各自的互操作方式、以及交叉编译在工程上怎么组织。JVM 侧的互操作规则在 [JVM 互操作](/docs/CS/Scala/JVM_Interop.md)；构建侧的配置（project matrix、依赖后缀）见 [工具链](/docs/CS/Scala/Tooling.md)。

## Three Backends at a Glance

| 维度 | JVM | Scala.js | Scala Native |
| :--- | :--- | :--- | :--- |
| 产物 | `.class` + `.tasty` | JS（另有 Wasm 后端） | 本地可执行文件（经 LLVM） |
| 执行方式 | 解释 + [JIT](/docs/CS/Java/JDK/JVM/JIT.md) | JS 引擎执行 | 提前编译，无预热 |
| 内存管理 | [JVM GC](/docs/CS/memory/GC.md) | 宿主 GC | 自己的 GC（Immix / Commix 等） |
| 启动 | 有 JVM 启动与预热 | 取决于宿主 | 毫秒级（0.005s 量级） |
| 线程 | 真线程（含[虚拟线程](/docs/CS/Java/JDK/Loom.md)） | 无真线程，异步事件循环 | 有线程；虚拟线程为实验特性 |
| 反射 | 有 | 无 | 无 |
| `Long` | 真 64 位 | 近似（底层用 double 之外的方式模拟，有精度与性能代价） | 真 64 位 |
| 浮点 | IEEE 754 | 依赖宿主，部分场景有差异 | IEEE 754 |
| 与宿主互操作 | Java 库直接用 | `@js.native` facade | `@extern` 对象 + `unsafe` 指针 |

最后两行的实际后果：在 JS 端，依赖反射的库（大多数 JSON 序列化器的朴素实现、DI 容器）要么不能用，要么必须换成编译期派生（这正是 `derives` 与 [宏](/docs/CS/Scala/Macros.md) 派生的现实驱动力）。

## Scala.js

```scala
import scala.scalajs.js
import scala.scalajs.js.annotation.*

@js.native
trait Console extends js.Object:
  def log(msg: String): Unit = js.native

@JSExportTopLevel("main")
def main(): Unit = println("hello from Scala.js")
```

要点：

- **facade 是类型化的 JS 声明**，`@js.native` 成员只有类型没有实现，编译后被直接替换成对宿主对象的访问；
- 产物经过一个专门的优化器（含死代码消除），官方给出的量级是完整应用从约 45kB（gzip）起步；
- 增量编译在 1–2 秒量级，这是前端开发体验能成立的前提；
- **Wasm 后端**是较新的第二条路径，与 JS 后端共用优化器；`Long` 与 `java.lang.Math` 的实现在两条路径上各自优化过。

适用场合：前端与全栈（同一份领域模型在前后端共享）、Node.js 服务、serverless 函数（启动快的场合）。

## Scala Native

```scala
import scala.scalanative.unsafe.*

type Vec = CStruct3[Double, Double, Double]

@extern object stdlib:
  def malloc(size: CSize): Ptr[Byte] = extern

@main def main(): Unit =
  val ptr = stdlib.malloc(32.toCSize)
  println(ptr)
```

要点：

- **提前编译到 LLVM IR 再链接**，没有 JVM 启动与预热，启动时间在毫秒级——适合 CLI 工具、短生命周期进程；
- `scala.scalanative.unsafe.*` 提供 `Ptr`、`CStruct`、`sizeof`、`stackalloc`、`@extern` 等 C 互操作原语，可以直接调 C 库；
- **没有反射**，序列化、依赖注入等必须走编译期方案；
- GC 是可配置的（Immix、Commix 等），0.5.12 修复了多线程 release 构建下 Immix/Commix 的崩溃与挂起问题；
- 实验性的虚拟线程从 0.5.12 起提供（仅 Linux/macOS，依赖 continuation，要求 LLVM 16+，且 LTO 构建下不可用），主要面向 Scala 3 项目；
- 工具链要求：推荐 JDK 17+ 与 LLVM/Clang 16+，更旧的版本仍可用但已被移出测试矩阵。

适用场合：CLI、需要秒级以下启动的短任务、与 C 库深度集成；不适合的场合是需要反射、动态类加载或成熟生态库的场景。

## Cross-building

sbt 用 **project matrix** 表达"同一份代码 × 多个 Scala 版本 × 多个平台"：

```scala
// sbt 2.x：projectMatrix 已内建
lazy val core = (projectMatrix in file("core"))
  .settings(name := "core")
  .jvmPlatform(scalaVersions = Seq("3.9.0", "2.13.18"))
  .jsPlatform(scalaVersions = Seq("3.9.0"))
  .nativePlatform(scalaVersions = Seq("3.9.0"))
```

依赖的平台后缀规则是工程上最容易出错的一点：

- **sbt 1.x**：跨平台依赖要用 `%%%`，它会把 `_sjs1_3` / `_native0.5` 这类平台后缀拼进 artifact 名；
- **sbt 2.x**：统一用 `%%`，平台由构建自行解析，跨平台依赖写法与 JVM 库一致。

另外 Scala 版本的选择是矩阵的一个维度，而 Scala 3 的输出兼容承诺让这个维度比 Scala 2 时代轻得多（详见 [版本线与迁移](/docs/CS/Scala/Migration_and_Versions.md)）：Scala 3 库不需要为 3.9 / 3.10 分别发布。

## Choosing a Platform

判断顺序：

1. **是否需要 JVM 生态**（Spark、Kafka 客户端、绝大多数 Java 库）→ 只能 JVM；
2. **是否需要跑在浏览器或 Node** → Scala.js；
3. **是否在意启动延迟或要与 C 集成** → Scala Native；
4. **是否依赖反射 / 动态代理** → 排除 JS 与 Native；
5. 三者皆可时，按团队熟悉度与调试工具链选择——JVM 侧的诊断工具（JFR、async-profiler、`jstack`）远比其他两端成熟。

## Links

- [Scala](/docs/CS/Scala/Scala.md)
- [JVM 互操作](/docs/CS/Scala/JVM_Interop.md)
- [工具链](/docs/CS/Scala/Tooling.md)
- [编译流水线](/docs/CS/Scala/Compilation.md)
- [并发](/docs/CS/Scala/Concurrency.md)

## References

- [Scala.js documentation](https://www.scala-js.org/doc/)
- [Scala.js — JavaScript interoperability](https://www.scala-js.org/doc/interoperability/facade-types.html)
- [Scala Native documentation](https://scala-native.org/en/latest/)
- [Scala Native — native code interoperability](https://scala-native.org/en/latest/user/interop.html)
- [sbt project matrix](https://www.scala-sbt.org/1.x/docs/Project-Matrix.html)
