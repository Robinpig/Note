## Introduction

Scala 3 编译器（dotty）的产物有两个：JVM 字节码 `.class`，以及一份 **TASTy**（Typed Abstract Syntax Tree）`.tasty` 文件。第二份产物是它与 Scala 2 最本质的区别，也是"库编译一次、后续编译器版本都能用"这个承诺的载体——Scala 2 需要为每个二进制版本交叉发布（`_2.12`、`_2.13`），Scala 3 不需要。

本篇讲这条流水线：各阶段做什么、TASTy 里装了什么、增量编译如何判断"哪个文件需要重编"、以及编译慢的真实成因在哪几个阶段。库作者关心的兼容承诺落在 [版本线与迁移](/docs/CS/Scala/Migration_and_Versions.md)；构建工具与 IDE 如何消费这些产物见 [工具链](/docs/CS/Scala/Tooling.md)。

## The Pipeline

```text
源码
  ↓ scanner / parser          词法与语法，产出未类型化的树
  ↓ desugar                   把 for 推导、for-comprehension、字符串插值等还原成核心语法
  ↓ typer                     类型检查 + 隐式搜索 + 重载决议 + 类型推断  ← 最贵的一步
  ↓ posttyper                 类型检查后的清理（含检查、适配）
  ↓ pickling                  写出 TASTy
  ↓ transforms                pattern match 编译、lazy val、闭包提升、erasure…
  ↓ JVM backend               genBCode，生成 .class
.class + .tasty
```

几个实操要点：

- **typer 是最贵的阶段**。隐式搜索会在候选集上做带回溯的探索，`inline` 展开与宏也在这一时期发生，所以"编译慢"几乎总是 typer 慢，而不是代码生成慢。
- Scala 3 把多个小 phase 融合成若干 **mega phase**，减少中间树的遍历次数（这是它相对 Scala 2 的一大内部改进）；用 `-Xprint:<phase>` 可以看到某个阶段后的树：
  ```bash
  scalac -Xprint:typer Foo.scala        # 看类型检查后的样子（调试隐式问题的利器）
  scalac -Xprint:erasure Foo.scala      # 看擦除后的样子（理解重载/签名问题）
  ```
- **erasure 之后的树才对应 JVM 现实**：泛型消失、值类被换成底层类型、闭包变成类。理解"编译器报的错在哪个阶段"决定了该看哪一层。

## TASTy

`.tasty` 是一份带完整类型信息的序列化语法树，与 `.class` 一起发布到仓库。它承担四件事：

| 用途 | 说明 |
| :--- | :--- |
| 跨模块内联 | `inline` 方法被调用时，编译器从 TASTy 读出原始树再展开 |
| 宏的跨编译单元 | 宏定义与使用在不同项目里也成立，因为类型信息随 TASTy 传递 |
| 输出兼容 | 新版编译器能读旧版产出的 TASTy，这是"无需交叉发布"的技术基础 |
| 工具链 | IDE 语义、Scaladoc、SemanticDB 生成都从它读取 |

代价是每个产物多一份文件，且 TASTy 的格式要随语言演进而扩展——因此 Scala 3 的兼容承诺明确分成两层：**binary compatibility**（字节码层面）与 **TASTy compatibility**（新版编译器能读旧元数据），合称 **output compatibility**。官方承诺是：minor 版本向后兼容（旧产物可被新版本使用），patch 版本双向兼容。

## Why Scala 2 Needed Cross-publishing

对照有助于理解这个设计的价值：

| | Scala 2 | Scala 3 |
| :--- | :--- | :--- |
| 元数据载体 |  pickle 塞进 `.class` 的注解里 | 独立 `.tasty` 文件 |
| 二进制版本后缀 | `_2.12` / `_2.13`，跨大版本需重新发布 | 统一 `_3` |
| 库升级编译器 | 需交叉发布，生态被割裂 | 发布一次，向后可用 |
| 与 3.10 的关系 | — | **例外**：3.10 移除了遗留语法，Scala 2 / 3.10 交叉编译不再受支持 |

最后一行是重要例外：3.10 开始删除为兼容 Scala 2 而保留的旧语法（`A with B` 之类），所以库若要同时支持 Scala 2 与 Scala 3，实际只能停在 Scala 3.9 LTS——这是"输出兼容"承诺没有覆盖的场景（源码兼容被主动打破了，二进制兼容仍在）。

## Incremental Compilation with Zinc

Zinc 是 Scala 的增量编译器，sbt、Mill、Scala CLI 共用：

- 它记录每个源文件的 **依赖关系**与 **公开 API 的哈希**；
- 改动一个文件后，只重编译"依赖了它且 API 哈希发生变化"的下游文件；
- 因此**改一个方法体（API 未变）与改一个签名（API 变）的重编范围差别巨大**——这也是为什么给 `case class` 加字段会触发大范围重编。

实践建议：把稳定的 API 与频繁改动的业务逻辑分到不同模块，是缩短增量编译时间最有效的手段。

## Why It's Slow, and What Actually Helps

编译慢的成因按重要性排：

1. **隐式搜索**：候选多、层次深时探索空间迅速膨胀；减少 `import lib._`、减少作用域内候选数量是直接的优化。
2. **`inline` 与宏展开**：展开结果还要再过一遍 typer。
3. **类型层面的计算**：match type 归约、高阶类型的推断，都比普通类型检查贵。
4. **编译单元数量**：每个文件都要完整走一遍流水线，JVM 启动与 JIT 预热是固定成本。
5. **宏与编译器插件**：插件在每个编译单元上运行。

真正有效的手段依次是：拆分模块、减少隐式候选、避免过度使用 `inline` 做通用逻辑、以及升级构建工具（sbt 2 用 native-image 客户端 `sbtn` 把启动成本降到几十毫秒级）。反过来，**减少代码量几乎无效**——瓶颈不在代码生成。

## Compiler Options Worth Knowing

| 类别 | 例子 | 用途 |
| :--- | :--- | :--- |
| 输出 | `-Xprint:typer`、`-Xprint:all` | 看中间树 |
| 详细日志 | `-Vimplicits`、`-Vprint:typer` | 调试隐式与推断 |
| 严格化 | `-Xfatal-warnings`、`-Wunused:all` | 把警告变错误、检查未使用 |
| 源码版本 | `-source:future`、`-source:3.0-migration` | 提前启用未来行为 / 迁移模式 |
| 实验 | `-experimental`、`-preview`、`-Ycc`、`-Yexplicit-nulls` | 打开实验与预览特性 |
| 目标 | `--release 17` | 控制字节码与 API 级别 |

其中 `-source:future` 值得单独提：它提前启用"下一个版本将成为默认"的行为，是让代码逐步对齐未来的官方通道，与 `-source:3.0-migration`（迁移期放宽）方向相反。

## Links

- [Scala](/docs/CS/Scala/Scala.md)
- [版本线与迁移](/docs/CS/Scala/Migration_and_Versions.md)
- [工具链](/docs/CS/Scala/Tooling.md)
- [宏与元编程](/docs/CS/Scala/Macros.md)
- [JVM 互操作](/docs/CS/Scala/JVM_Interop.md)

## References

- [Scala 3 Compiler Phases（dotty 文档）](https://dotty.epfl.ch/docs/internals/overview.html)
- [TASTy format](https://docs.scala-lang.org/scala3/reference/metaprogramming/tasty.html)
- [Binary Compatibility / Output Compatibility](https://www.scala-lang.org/development)
- [Scala 3 Compiler Options](https://docs.scala-lang.org/scala3/reference/compiler-options/index.html)
- [Zinc incremental compiler](https://github.com/sbt/zinc)
