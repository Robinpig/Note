## Introduction

Scala 的工具链在这几年换过一轮：构建工具从 sbt 1.x 走到 **sbt 2.x**（2026-06 发布），命令行从裸 `scala` 变成 **Scala CLI**（自 3.5 起成为官方 `scala` 命令），IDE 侧统一到 **Metals + BSP**，格式化与重构交给 Scalafmt / Scalafix。这一轮变化的共同方向是**把"启动开销"和"配置开销"降下来**——这两项此前是 Scala 被抱怨最多的地方，甚至排在编译速度之前。

本篇讲这套闭环：构建工具三选一、依赖与解析、IDE 与语言服务器、格式化与自动重构、测试与覆盖率、以及库作者要用的二进制兼容检查。编译器内部的选项与产物见 [编译流水线](/docs/CS/Scala/Compilation.md)，版本与迁移规则见 [版本线与迁移](/docs/CS/Scala/Migration_and_Versions.md)。

## Build Tools

| 工具 | 构建定义写法 | 取向 | 适用 |
| :--- | :--- | :--- | :--- |
| **sbt 2.x** | `.sbt` DSL（Scala 3） | 官方主力，生态最大 | 绝大多数项目；插件最多 |
| **Scala CLI** | 源文件里的 `//> using` 指令 | 脚本化、零配置 | 单文件、教学、CI 片段、快速实验 |
| **Mill** | 普通 Scala 对象 | 显式、可调试 | 讨厌 DSL 魔法的团队 |

### sbt 2.x

sbt 2 在 2026-06 正式发布，是五年开发的成果。关键变化：

- **构建定义与插件改用 Scala 3**（3.8.4），因此**最低 JDK 17**；
- 用 **sbtn**（native-image 客户端）替代启动慢的 JVM 客户端，命令行调用从"等几秒"变成几十毫秒级；
- `compile` 与 `test` 重写为**可缓存任务**，本地/远程缓存与 Bazel 兼容；
- `test` 改为增量测试；
- **project matrix 内建**（1.x 需要插件），跨平台交叉构建成为一等公民；
- 依赖的跨平台写法统一为 `%%`（1.x 是 `%%%`）。

迁移靠 `sbt2-compat` 插件桥接 1.x 与 2.x 的源码差异，主要插件（Scala.js、Scala Native、sbt-assembly 等）已完成适配。

### Scala CLI

```scala
//> using scala 3.10
//> using dep org.typelevel::cats-effect:3.5.4

@main def hello(): Unit = println("hi")
```

`scala run hello.scala` 直接跑起来，无需 build 文件。它同时支持 `//> using scala 3.3.lts` 这样的版本线写法，因此是实验新版本最快的通道。配套有官方 **Scala Toolkit**（一组预选依赖，面向脚本与教学）。

### Mill

```scala
// build.mill
import mill._, scalalib._
object app extends ScalaModule:
  def scalaVersion = "3.9.0"
  def ivyDeps = Agg(ivy"dev.zio::zio:2.1.26")
```

构建逻辑就是普通 Scala 方法，可以跳转、可以调试、可以复用——这是它相对 sbt DSL 的核心主张。

## Dependency Resolution

三者底层都用 **Coursier** 做依赖解析（sbt 2 已升级到较新的 Coursier 版本），因此：

- 仓库配置、缓存位置、镜像行为由 Coursier 统一；
- `cs setup` 是官方推荐的安装方式（装 JDK、scala、sbt、Metals 等一整套）；
- 依赖冲突的排查手段是 `cs resolve` 与 `sbt dependencyTree`。

## IDE and Language Server

Scala 的 IDE 支持统一走 **Metals**（基于 LSP）+ **BSP**（Build Server Protocol）：构建服务器（sbt / Mill / Scala CLI）通过 BSP 向 Metals 提供编译与语义信息，编辑器只负责呈现。

- 语义信息来自编译器本身（presentation compiler + TASTy + SemanticDB），所以补全与跳转的正确性和编译器一致；
- 支持"best-effort 编译"——即使代码有错，补全仍然可用；
- 主流编辑器（VS Code、IntelliJ IDEA、Vim/Neovim、Emacs）都接 Metals；IntelliJ 另有自己的 Scala 插件，两条路径并存。

## Formatting, Linting, and Rewriting

| 工具 | 作用 |
| :--- | :--- |
| **Scalafmt** | 格式化（`.scalafmt.conf`），支持 Scala 3 语法与 `dialect = scala3` |
| **Scalafix** | 语义化的自动重写：弃用 API 替换、Scala 2 → 3 迁移规则、自定义 lint |
| **WartRemover** | 禁用特定语言构造（比 Scalafix 的 lint 更激进） |

Scala 2 → 3 迁移的主力就是 Scalafix 的 `Scala3RewriteFromScala2Old` 规则集，配合编译器的 `-source:3.0-migration` 与独立工具 `scala-migrate`，通常能自动解决大部分代码；剩下的难点集中在[宏](/docs/CS/Scala/Macros.md)、隐式转换与类型投影。

## Testing

| 框架 | 取向 |
| :--- | :--- |
| **MUnit** | 轻量、编译快，与 Metals 集成好，Typelevel 生态常用 |
| **ScalaTest** | 风格最全（AnyFunSuite / WordSpec / AsyncFunSuite 等），历史最久 |
| **Weaver** | 为 cats-effect / ZIO 设计的 effectful 测试 |
| **utest** | 极简，宏驱动 |
| **ScalaCheck** | 属性测试（property-based），常与上面任一框架搭配 |
| **ZIO Test** | ZIO 自带的测试与断言库 |

属性测试值得单独强调：Scala 的类型系统能挡住很多错误，但挡不住"逻辑错"，而 ScalaCheck 这类基于生成器的随机测试在 Scala 生态里有很高的使用率，这是函数式风格的直接收益。

覆盖率用 **Scoverage**（Scala 3.9 修了一批与 capture checking、大方法、柯里化构造器相关的插桩问题），支持 `// $COVERAGE-OFF$` / `// $COVERAGE-ON$` 标记。

## For Library Authors

发布库要额外过两道门：

1. **MiMa**（Migration Manager）：对比前后两个版本的二进制兼容。检查 3.9 / 3.10 产物需要 MiMa 1.2.1 或更新（该版本加入 3.9 / 3.10 支持并修掉若干误报）。
2. **Open Community Build**：官方用上千个开源项目验证每个新版本不会破坏生态；库作者可以自己加一个"针对 nightly 或 RC 构建"的 CI 任务，把问题提前暴露——Scala 3.10 的好几个修复就是这样被发现的。

文档侧：Scaladoc 可以编译文档里的代码片段（防止示例腐化），Scala 3.9 起片段还能声明它期望产生哪一行错误/警告。

## Links

- [Scala](/docs/CS/Scala/Scala.md)
- [编译流水线](/docs/CS/Scala/Compilation.md)
- [版本线与迁移](/docs/CS/Scala/Migration_and_Versions.md)
- [平台](/docs/CS/Scala/Platforms.md)
- [宏与元编程](/docs/CS/Scala/Macros.md)

## References

- [sbt 2 is now available（Scala 官方博客）](https://scala-lang.org/blog/2026/06/29/sbt2.html)
- [Scala CLI documentation](https://scala-cli.virtuslab.org/)
- [Mill documentation](https://mill-build.org/)
- [Metals](https://scalameta.org/metals/)
- [Scalafmt](https://scalameta.org/scalafmt/) / [Scalafix](https://scalameta.org/scalafix/)
- [Coursier](https://get-coursier.io/)
- [MiMa](https://github.com/lightbend/mima)
