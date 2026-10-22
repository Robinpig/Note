## Introduction

Scala 的元编程史是一次推倒重来：Scala 2 的宏（`scala.reflect.macros`）直接操作编译器内部 API，能力极强但与编译器版本强绑定、错误信息糟糕、宏库往往只能用于特定编译器版本。**Scala 3 把这套东西整体废弃**，换成基于 `inline` + quote/splice 的多阶段编程（multi-stage programming）：宏操作的是带类型的表达式树 `Expr[T]`，且必须能跨编译单元工作——宏定义与宏使用可以在完全不同的项目里，因为类型信息通过 TASTy 传递而不是通过共享编译器实例。

本篇讲这套机制：`inline` 与编译期操作、quote / splice 的对称规则、`Mirror` 与 `derives` 派生、以及 Scala 3 宏的能力边界与常见失败。类型类的定义方式在 [上下文抽象](/docs/CS/Scala/Contextual_Abstractions.md)；TASTy 这一产物本身的格式与兼容承诺在 [编译流水线](/docs/CS/Scala/Compilation.md)。

## inline: Expand at Compile Time

`inline` 是 Scala 3 元编程的入口——它要求编译器在调用点展开方法体：

```scala
inline def assertTrue(inline cond: Boolean): Unit =
  if !cond then scala.compiletime.error("assertion failed")

assertTrue(2 > 1)      // 通过：常量折叠后条件为真
assertTrue(2 < 1)      // 编译错误，错误信息就在调用点
```

几个要点：

- `inline` 是**要求**而不是提示：编译器可以拒绝无法展开的调用；
- 参数上的 `inline` 表示"这个参数必须是常量，以便编译期折叠"；
- `transparent inline` 让展开后保留更精确的类型（常用于让字面量类型、单例类型透出）；
- `scala.compiletime` 提供一组编译期原语：`constValue`、`constValueOpt`、`summonInline`、`summonFrom`、`erasedValue`、`codeOf`、`error`、`errorFromString`。

这是 Scala 3 取代 Scala 2 宏最常用的一块：不需要写宏，靠 `inline` + 编译期操作就能做"类型级计算 + 编译期校验"。

## Quotes and Splices

真正的宏用 quote（`'`）与 splice（`${}`）构造代码，两者是对称的：

```scala
import scala.quoted.*

inline def debug(inline expr: Any): Unit =
  ${ debugImpl('expr) }

private def debugImpl(expr: Expr[Any])(using Quotes): Expr[Unit] =
  import quotes.reflect.*
  '{
    val value = $expr
    println(${ Expr(expr.show) } + " = " + value)
  }
```

规则：

- `'{ ... }` 把代码变成 `Expr[T]`（一段带类型的语法树）；
- `${ ... }` 把 `Expr[T]` 嵌回代码；
- 两者必须层数匹配——`${ ... '{ ... } ... }` 的嵌套深度必须归零，写错会得到明确的层数错误；
- 需要窥探或修改树时用 `quotes.reflect.*`（反射 API，操作 `Tree` 而非 `Expr`），这一步是"真正不安全"的地方，但被限制在显式导入的作用域内。

与 C 预处理器和 Rust macro 的对比值得记一笔：Scala 3 的宏操作**语法树**而不是字符流（与 [C 预处理器](/docs/CS/C/Preprocessor.md) 那种文本替换没有可比性），且类型在 quote 时就已确定（与 Rust 的 `macro_rules!` 相比多一层类型保证）。

## Derivation with Mirrors

大多数项目并不自己写宏，而是用 `derives` 让编译器生成实例：

```scala
case class Person(name: String, age: Int) derives Show, Eq

trait Show[T]:
  def show(t: T): String

object Show:
  inline def derived[T](using m: Mirror.Of[T]): Show[T] =
    // 典型实现：用 Mirror 拿到字段名与字段类型，再逐个 summon
    ${ derivedImpl[T] }   // 或直接用 inline + summonInline 实现
```

`Mirror` 把 ADT 的结构暴露给宏：`Mirror.ProductOf[T]` 描述 case class 的字段类型与标签，`Mirror.SumOf[T]` 描述 sealed 层次的分支。这是 Scala 3 把 Scala 2 时代 shapeless / magnolia 那些技巧标准化的结果——派生成为语言特性而不是库技巧。

## Boundaries and Failure Modes

宏的能力边界，以及最容易踩的坑：

| 限制 | 说明 |
| :--- | :--- |
| 不能改变已编译类型 | 宏展开发生在编译期，不能给已存在的类加成员（那是编译器插件的事） |
| 展开深度有上限 | 递归 inline 会报递归超限，可用 `-Xmax-inlines` 调整（默认 32 左右量级） |
| 宏的展开结果要能类型检查 | Scala 3.10 起会检查展开结果是否符合宏声明的类型，此前生成"碰巧能过"的病态代码现在会失败 |
| 常量折叠会影响宏 | 3.10 加强了 inline 期间的常量折叠，一些依赖"生成未类型化代码"的宏库会失效 |
| 反射 API 不稳定 | `quotes.reflect.*` 属于编译器内部 API 的稳定子集，但跨版本仍可能变化 |

最后两条是 3.10 升级的主要风险点：Scala 官方在 3.10 公告里点名要求 ZIO 生态的几个库升到指定版本（ZIO、zio-blocks、izumi-reflect、neotype）才能配合新编译器，原因正是宏看到的树变了。

## Compiler Plugins vs Macros

两者都能在编译期改写代码，分工不同：

| | 宏（`inline` + quote） | 编译器插件 |
| :--- | :--- | :--- |
| 作用范围 | 调用点展开 | 整个编译流程的某个 phase |
| 稳定性 | 有文档、受兼容承诺保护 | 依赖编译器内部 API，跨版本易碎 |
| 典型用途 | 派生、编译期校验、DSL 优化 | 代码插桩（覆盖率）、静态分析、注解处理器 |

Scoverage、kind-projector（Scala 2 时代）属于后者；Scala 3 里 kind-projector 的大部分功能已被原生类型 lambda 取代，这正是"语言特性取代插件"的好例子。

## Links

- [Scala](/docs/CS/Scala/Scala.md)
- [上下文抽象](/docs/CS/Scala/Contextual_Abstractions.md)
- [编译流水线](/docs/CS/Scala/Compilation.md)
- [类型系统](/docs/CS/Scala/Type_System.md)
- [C 预处理器](/docs/CS/C/Preprocessor.md)

## References

- [Scala 3 — Inline](https://docs.scala-lang.org/scala3/reference/metaprogramming/inline.html)
- [Macros: Quotes and Splices](https://docs.scala-lang.org/scala3/reference/metaprogramming/macros.html)
- [Compile-time Operations](https://docs.scala-lang.org/scala3/reference/metaprogramming/compiletime-ops.html)
- [Type Class Derivation](https://docs.scala-lang.org/scala3/reference/contextual/derivation.html)
- [TASTy Inspection](https://docs.scala-lang.org/scala3/reference/metaprogramming/tasty-inspect.html)
- [Dropped: Scala 2 Macros](https://docs.scala-lang.org/scala3/reference/dropped-features/macros.html)
