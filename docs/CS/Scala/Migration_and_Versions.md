## Introduction

Scala 的版本问题比其他语言复杂，因为它同时有**三条并行的线**：仍在维护的 Scala 2.13、面向库作者的 Scala 3 LTS、面向应用的 Scala Next。再加上"输出兼容"这一层 scala 特有的承诺（库不必交叉发布），判断"某段代码能不能编、某个库能不能用"需要同时看三个轴。

本篇是这套坐标系：三条线的定位与现状、三种兼容性的确切含义、语言特性从实验到稳定的流程、Scala 2 → 3 的迁移路径、以及 Scala 3.10 这次主动打破源码兼容的具体内容。

## Three Lines

| 线 | 写作时版本 | 定位 | 谁该用 |
| :--- | :--- | :--- | :--- |
| **Scala Next** | 3.10.0（2026-10-12） | 最新特性、修复与改进 | 应用 |
| **Scala 3 LTS** | 3.9.0（2026-09-03） | 只收补丁、诊断与工具改进 | **库作者**（兼容窗口最长） |
| **Scala 3.3 LTS** | 3.3.8（2026-06-10） | 旧 LTS，3.9.0 之后继续维护一年 | 消费者被卡住时才用 |
| **Scala 2.13** | 2.13.18（2025-11-24） | 无限期维护 | 遗留项目、大数据生态 |
| **Scala 2.12** | 2.12.21（2025-12-11） | 最小维护，只要 sbt 1 还在广泛使用 | 遗留 |

两条 Scala 3 线的分工逻辑是：Next 每出一个 minor 就带新语言特性，LTS 只从 Next 反向移植"不会破坏兼容"的修复——3.3 LTS 时期有近 43% 的编译器改动被反向移植过，这也是它能撑三年多的原因。

**JDK 下限**：自 Scala 3.8 起**最低 JDK 为 17**（此前 3.3 LTS / 3.7 支持 JDK 8+）。这是 Scala 3 现状里最容易被忽略的硬约束。

## Three Kinds of Compatibility

| 类型 | 含义 | 版本承诺 |
| :--- | :--- | :--- |
| **Patch 兼容** | 双向：3.3.3 编的库可被 3.3.4 用，反之亦然 | patch 版本之间 |
| **Minor（输出）兼容** | 向后：旧的产物可被更新的编译器使用 | minor 版本之间，无限期 |
| **Source 兼容** | 源码升级后仍能编译 | best-effort，不做硬承诺 |

"输出兼容"由两部分组成：**binary compatibility**（字节码）与 **TASTy compatibility**（新版编译器能读旧版元数据），其技术基础见 [编译流水线](/docs/CS/Scala/Compilation.md)。它的实际价值是：库发布一次，所有未来的 Scala 3 版本都能用，不必像 Scala 2 那样为每个二进制版本交叉发布。

但这套承诺覆盖不了源码层的主动破坏——3.10 就是第一次。

## Scala 3.10 Broke Source Compat on Purpose

3.10 是"Scala Next 开始删除遗留"的第一个版本。二进制兼容仍然保留（旧库照常可用），但**源码**必须改：

| 变更 | 影响 |
| :--- | :--- |
| `A with B` 等遗留语法成为错误 | 必须改成 `A & B` |
| 不可访问的伴生 given 不再被找到 | 库作者必须把 private 伴生里的 given 公开化 |
| `Rich*` 隐式类移除，`until`/`to`/`abs`/`max` 改为基本类型伴生里的扩展方法 | 普通调用点无感，**宏看到的树变了** |
| inline 期间常量折叠加强，且会校验宏展开结果的类型 | 生成病态代码的宏会失败 |
| 递归超限改为报 "Recursion limit exceeded" | 不再 `StackOverflowError` 崩溃 |

两个现实后果：

1. **Scala 2 与 3.10 的交叉编译不再受支持**——想同时支持两者的库只能停在 3.9 LTS；
2. **ZIO 生态需要先升级库再升级编译器**：官方在 3.10 公告里点名 ZIO、zio-blocks、izumi-reflect、neotype 的最低修复版本。

检查 3.10 产物前还需把 MiMa 升到 1.2.1 以上（该版本才支持 3.9/3.10）。

## How Features Mature: Experimental → Preview → Stable

语言特性不是直接进语言的，它有三态：

| 状态 | 打开方式 | 承诺 |
| :--- | :--- | :--- |
| **experimental** | `import scala.language.experimental.X` / `-language:experimental.X` / `-experimental`；`-Ycc`、`-Yexplicit-nulls` 这类走编译器选项 | 无任何兼容保证，可能变化或被删 |
| **preview** | `-preview`（一次性打开所有预览特性） | 已被 SIP 委员会接受，**保证在后续某个 minor 版本中稳定**，但可能还有小的破坏性调整 |
| **stable** | 默认可用 | 遵循正常兼容规则 |

状态迁移只发生在 minor 版本（3.9、3.10…），绝不会在 LTS 的 patch 版本里发生。特性也可以跳过中间态（SIP-67 就是从 3.9 的 experimental 直接到 3.10 的 stable）。

写作时的几个坐标：

| 特性 | 状态 |
| :--- | :--- |
| 可选大括号、`@main`、`enum`、联合/交集类型、opaque type、match type、given/using/extension/context function | 3.0 起稳定 |
| named tuples（SIP-58） | 3.7 稳定 |
| better fors（SIP-62）、runtimeChecked（SIP-57） | 3.8 稳定 |
| `into`（SIP-71） | 3.9 稳定 |
| strict-equality 模式匹配（SIP-67） | 3.10 稳定 |
| `@unroll`（SIP-61）、可引用 package object（SIP-68）、带括号的偏函数字面量（SIP-74）、`:` 后单行 lambda（SIP-75） | 3.10 进入 preview |
| capture checking、explicit nulls、erased definitions、saferExceptions、灵活可变参数 | 仍 experimental |

## Migrating from Scala 2

迁移有三条工具链，通常组合使用：

1. **Scalafix** 的 `Scala3RewriteFromScala2Old` 规则集——批量重写语法（`implicit` → `given/using`、`with` → `&`、`implicit class` → `extension` 等）；
2. 编译器的 **`-source:3.0-migration`** 模式——放宽检查并把部分错误降级为警告，便于渐进迁移；
3. **scala-migrate**（`cs install scala-migrate`）——为整个构建生成迁移计划，逐个模块推进。

大部分代码可以自动迁移；剩下的硬骨头集中在三处：**Scala 2 宏**（必须重写为 `inline` + quote/splice，见 [宏与元编程](/docs/CS/Scala/Macros.md)）、**隐式转换**（要改成 `Conversion` 或 `into`，见 [上下文抽象](/docs/CS/Scala/Contextual_Abstractions.md)）、以及**类型投影**（已移除）。

一个实用的中间态是让库同时交叉发布 2.13 与 3.x（用 sbt 的 projectMatrix），让使用者按自己的步调迁移——注意这条路的终点是 3.9 LTS，因为 3.10 起不再支持交叉编译。

## Choosing a Version

| 场景 | 选择 |
| :--- | :--- |
| 新应用 | Scala Next（3.10），但要确认依赖库已适配 |
| 发布库 | Scala 3.9 LTS |
| 库要同时支持 Scala 2 | 2.13 + 3.9 LTS（不能到 3.10） |
| 大数据作业（Spark 等） | 跟随框架自带的 Scala 版本，通常是 2.12/2.13 |
| 保守的生产系统 | Scala 3.9 LTS |
| 想提前对齐未来行为 | 加 `-source:future` |

## Links

- [Scala](/docs/CS/Scala/Scala.md)
- [编译流水线](/docs/CS/Scala/Compilation.md)
- [上下文抽象](/docs/CS/Scala/Contextual_Abstractions.md)
- [宏与元编程](/docs/CS/Scala/Macros.md)
- [工具链](/docs/CS/Scala/Tooling.md)

## References

- [Scala Development Guarantees](https://www.scala-lang.org/development)
- [All Available Versions](https://www.scala-lang.org/download/all.html)
- [Scala 3.10 release notes（含 Breaking changes）](https://scala-lang.org/news/3.10)
- [Scala 3.9 LTS release notes](https://scala-lang.org/news/3.9)
- [JDK Compatibility](https://docs.scala-lang.org/overviews/jdk-compatibility/overview.html)
- [Scala 3 migration guide](https://docs.scala-lang.org/scala3/guides/migration/compatibility-intro.html)
- [List of all SIPs](https://docs.scala-lang.org/sips/all.html)
