## Introduction

Scala 3 换了语法：大括号变成可选的，缩进成为结构，`if` 加了 `then`，`given` / `using` / `extension` / `enum` / `export` 这些新关键字把 Scala 2 里靠 `implicit` 拼出来的东西变成语言设施。这些改动看起来是"更好看的写法"，但背后有一个共同目的：**让"类型类的定义""代数数据类型的定义""能力的选择"这三件事有各自专门的语法**，而不是都塞进 `implicit` 一种机制里。

本篇只讲语法层：可选大括号与缩进、新控制语法、顶层定义与 `@main`、enum 与 ADT、trait 参数与 `open` / `export`、`extension` 与运算符规则、以及通配符与可变参数的新写法。语义归别的篇：类型层面的含义在 [类型系统](/docs/CS/Scala/Type_System.md)，候选如何被找出来在 [上下文抽象](/docs/CS/Scala/Contextual_Abstractions.md)，容器本身在 [集合库](/docs/CS/Scala/Collections.md)。

## Optional Braces

Scala 3 的分号推断从"括号定界"改成"缩进定界"，`{` `}` 可以整体省略：

```scala
trait Ord[T]:
  def compare(x: T, y: T): Int

  def compareAll(xs: List[T])(using Ord[T]): Int =
    var acc = 0
    for x <- xs do
      acc += compare(x, xs.head)
    acc
end Ord
```

三条规则值得单独记住：

- **`:` 之后换行并缩进**等价于开括号。`def f(x: Int): Int =` 之后的缩进块、以及 `if ... then` 之后的缩进块都遵循这条。
- **`end` 标记是可选的**（`end Ord`、`end if`、`end def`），纯粹为了可读性；它会被编译器核对，写错了会报错，这在长文件里很有用。
- **fewer braces**（SIP-44）允许把最后一组参数写成缩进块而不是括号，3.3 起已是标准语法：

```scala
List(1, 2, 3).map: x =>
  val y = x * 2
  y + 1
```

坑：缩进语法与部分应用、中缀调用混用时，`a b c` 这种写法会被解析成链式调用，老代码迁移时最容易在这里出错；另外把 `case` 写在同一缩进层级会导致匹配块被提前关闭。

## New Control Syntax

```scala
if x > 0 then "pos" else "neg"

for
  x <- xs
  y <- ys
  if x != y
yield (x, y)

for x <- xs do println(x)

while cond do body()

try risky()
catch case e: IOException => fallback
finally cleanup()
```

`for` 的 `do` 形式对应"只要副作用不产生结果"，`yield` 形式对应"产生结果"——两者在 Scala 2 里是同一条语法的两种解析，Scala 3 把它们分成显式两种。`for` 本身仍然只是 `flatMap` / `map` / `withFilter` 的语法糖，语义与开销见 [集合库](/docs/CS/Scala/Collections.md)；SIP-62（"better fors"，3.8 起稳定）放宽了其中一些限制，比如不再强制要求每个生成器的类型完全对齐。

## Top-level Definitions and @main

Scala 2 里所有定义都必须包在 `object` / `class` 里；Scala 3 允许顶层定义，编译成以文件名为前缀的合成类：

```scala
// Greeting.scala
type Id[A] = A
def greet(name: String): String = s"hi $name"

@main def run(args: String*): Unit =
  println(greet(args.headOption.getOrElse("world")))
```

`@main` 生成一个真正的 `main` 方法（含 `Array[String]` 签名），可以有多个，也可以分布式定义在不同文件里；它取代的是 Scala 2 里 `object Main extends App` 那套（后者因为 `DelayedInit` 被移除而失效）。

## Enums and ADTs

`enum` 是 Scala 3 对代数数据类型的一等支持，取代了 Scala 2 里 `sealed trait` + `case class` 手写的样板：

```scala
enum Color(val rgb: Int):
  case Red   extends Color(0xFF0000)
  case Green extends Color(0x00FF00)
  case Blue  extends Color(0x0000FF)

enum Option[+T]:
  case Some(x: T)
  case None
```

编译产物是 `sealed class` + `case` 分支（值分支编译成 `val` 单例、参数化分支编译成 `case` 类），因此 `enum` 与手写 sealed 层次在模式匹配上等价，穷尽性检查照样生效。带参数的 case 还可以构成 **GADT**——让类型参数在不同分支上有不同实例化，这是 `enum` 相对旧写法最重要的能力：

```scala
enum Expr[T]:
  case IntExpr(i: Int)      extends Expr[Int]
  case BoolExpr(b: Boolean) extends Expr[Boolean]
```

## Traits, `open`, and `export`

三个互斥的小改动，目的都是让组合关系更明确：

| 设施 | 作用 | 为什么需要 |
| :--- | :--- | :--- |
| trait 参数 | `trait Greeting(val name: String)` | 取代 Scala 2 里靠抽象成员 + 早期初始化器的绕法（early initializer 已被移除） |
| `open` | `open class Base` | 默认禁止继承，只有标 `open` 的类可以被继承；`trait` 与 `abstract class` 默认 open |
| `export` | `export inner.members` | 把某个成员的成员提升为本类型的成员，取代"手写一堆转发方法"与 Cake pattern 的一部分 |
| `transparent` | `transparent trait` | 让父类型在推断中被看穿，常用于把抽象层从推断结果里去掉 |

`export` 值得多说一句：它是组合优于继承在语言层的表达——把能力委托给一个字段，再 `export` 出去，对外看起来与继承无异，但内部是可替换的。这是 Scala 3 用来替代 Scala 2 里泛滥的 `extends X with Y` 堆叠的手段。

## Extension Methods and Operators

`extension` 把 Scala 2 的 `implicit class` 变成专门的语法：

```scala
extension (s: String)
  def shout: String = s.toUpperCase + "!"

extension [T](xs: List[T])(using ord: Ordering[T])
  def sortedDesc: List[T] = xs.sorted.reverse
```

要点：泛型扩展写成两段参数（`[T]` 与值参数），`using` 子句可以出现在第二段，因此**扩展方法的能力可以有约束**。SIP-54（3.4 起）允许来自多个源的扩展重载共存，解决了"两个库给同一类型加了同名扩展就冲突"的问题。

运算符方面有三条规则：

- 符号运算符（`+`、`::`）默认可用中缀形式；**字母数字方法想用中缀形式，必须标 `infix`**（这是对 Scala 2 那种 `a to b` 满天飞的收紧）。
- 以 `:` 结尾的运算符是右结合的，且左侧是方法接收者（`x :: list` 等价于 `list.::(x)`）。
- `end` 之外，运算符优先级由首字符决定，与 Scala 2 一致。

## Smaller Syntax Changes

批量列出迁移时必然撞到的那些：

| 写法 | Scala 3 | 说明 |
| :--- | :--- | :--- |
| 类型通配符 | `List[?]`、`[? <: Foo]` | 取代 `_`，`_` 现在只用于匿名参数 |
| 可变参数展开 | `f(xs*)` | 取代 `f(xs: _*)`；SIP-70 允许多个展开（写作时仍是实验特性） |
| 参数解构 | `xs.map((a, b) => ...)` | parameter untupling：接受元组的函数可直接写成多参数形式 |
| 字符串插值 | `s"..."` / `f"..."` / `raw"..."` | 与 Scala 2 一致，但 `$` 的转义规则变了（需用 `$$` 输出字面 `$`） |
| 数字字面量 | `0b1010`、`1_000_000`、`1.5f` | SIP-42（3.5）加入二进制字面量 |
| 具名元组 | `(name = "a", age = 1)` | SIP-58，3.7 起稳定 |
| 单行 lambda | `xs.map: x => x + 1` | SIP-75，3.10 进入 preview |

## Links

- [Scala](/docs/CS/Scala/Scala.md)
- [类型系统](/docs/CS/Scala/Type_System.md)
- [上下文抽象](/docs/CS/Scala/Contextual_Abstractions.md)
- [模式匹配](/docs/CS/Scala/Pattern_Matching.md)
- [集合库](/docs/CS/Scala/Collections.md)

## References

- [Scala 3 Syntax Summary](https://docs.scala-lang.org/scala3/reference/syntax.html)
- [Optional Braces](https://docs.scala-lang.org/scala3/reference/other-new-features/optional-braces.html)
- [Enums / Algebraic Data Types](https://docs.scala-lang.org/scala3/reference/enums/adts.html)
- [Extension Methods](https://docs.scala-lang.org/scala3/reference/contextual/extension-methods.html)
- [Export Clauses](https://docs.scala-lang.org/scala3/reference/other-new-features/export.html)
- [Main Methods](https://docs.scala-lang.org/scala3/reference/changed-features/main-functions.html)
- [Scala 3 Syntax Rewriting（迁移对照）](https://docs.scala-lang.org/scala3/reference/other-new-features/keyword-syntax.html)
