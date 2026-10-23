## Introduction

Scala 2 最著名的机制是 `implicit`：一个关键字同时承担了"自动传参""类型类实例""扩展方法""隐式转换"四件事，既成就了类型类生态，也制造了难以预测的解析行为。Scala 3 做的不是删掉它，而是**把它拆成两半**——`given` 负责"这里有一个候选"，`using` 负责"这里需要一个候选"，中间那套搜索规则被单独规范下来。

本篇讲这套机制：given 的几种形态与作用域、搜索的优先级规则、类型类的标准写法、`Conversion` 与 `into`、以及从 Scala 2 迁移时的逐条对照。边界：类型层面的内容（联合/交集/opaque/match type）在 [类型系统](/docs/CS/Scala/Type_System.md)；扩展方法作为语法在 [语法骨架](/docs/CS/Scala/Syntax.md)；编译期求值与 `inline` 在 [宏与元编程](/docs/CS/Scala/Macros.md)；`derives` 派生在类型类之外还涉及 `Mirror`，见 [宏与元编程](/docs/CS/Scala/Macros.md)。

## Two Halves of One Search

```scala
trait Ord[T]:
  def compare(x: T, y: T): Int

// given：定义候选
given intOrd: Ord[Int] with
  def compare(x: Int, y: Int): Int = x.compare(y)

given [T](using ord: Ord[T]): Ord[List[T]] with
  def compare(xs: List[T], ys: List[T]): Int = ...   // deferred given：自己也要依赖候选

// using：声明需求
def max[T](x: T, y: T)(using ord: Ord[T]): T =
  if ord.compare(x, y) >= 0 then x else y

max(1, 2)      // 编译器插入 intOrd
```

`using` 子句在调用点由编译器填入，等价于显式写出 `max(1, 2)(using intOrd)`。几件事值得单独记住：

- `given` 可以是匿名（`given Ord[Int] with ...`）、具名（`given intOrd: ...`）、别名（`given ctx: Context = delegate`）、或带参数的（即 deferred given / "given with using clause"）。
- 具名 given 只在同一个文件内可见于"按名字引用"，跨文件靠类型。
- `summon[T]` 取代 Scala 2 的 `implicitly[T]`，语义相同但错误信息更好，且在 `inline` 上下文里有 `scala.compiletime.summonInline` 变体。
- context bound `def max[T: Ord] (x: T, y: T)` 是 `(using Ord[T])` 的简写，匿名时要用 `summon[Ord[T]]` 取出；SIP-64（3.6 起）改进了 context bounds 与 given 的写法，使命名更直接。

## Where Candidates Come From

搜索失败时最重要的问题是"它本来该从哪来"。候选来源只有四类，按此顺序考虑：

| 来源 | 写法 | 备注 |
| :--- | :--- | :--- |
| 词法作用域 | 同一作用域内定义的 given | 最内层优先 |
| 导入 | `import lib.given` / `import lib.{given Ord[Int]}` | Scala 3 用 `given` 选择器，**只导入 given 而不导入其他成员** |
| 类型的伴生对象 | `T` 的伴生里的 given | 无需导入即可用，这是类型类"实例跟着类型走"的实现 |
| 显式传参 | `f(using myOrd)` | 绕过搜索 |

导入语法是 Scala 3 的一个实际改进：`import lib._` 会把 given 一起带进来（也最容易引发歧义），而 `import lib.given` 只带 given；`import lib.{given, _}` 两者都要。稍精细一点可以写 `import lib.given Ord[Int]` 只导入特定类型的候选。

⚠️ 伴生对象这条路径在 Scala 3.10 收紧了：**隐式搜索只看调用点可访问的实例**。把 `given` 藏在 `private` 伴生对象里，以前能用，3.10 起报 "no implicit argument of type ... was found"，而使用者无法在自己的代码里绕过——这是库作者必须提前修的问题（公开的伴生 + 公开的 given）。

## Priorities and the Ambiguity Wall

多个候选同时满足时，编译器按**具体程度**排序：更具体（子类型关系上更靠下）的优先；具名 given 与匿名 given 之间、不同作用域深度之间也有规则，但**规则不保证总能定序**，定不出来就是硬错误：

```text
[error] ambiguous given instances: both given intOrd and given reverseOrd
        match type Ord[Int] of parameter ord of method max
```

遇到它时的排查顺序是固定的：

1. `-Vimplicits` 打开隐式搜索的详细日志，看候选集与每次尝试；
2. 用 `summon[Ord[Int]]` 在报错位置单独复现，缩小范围；
3. 检查是否有两条导入带进了同类候选（最常见原因是 `import lib._`）；
4. 确认候选本身是否可访问（3.10 的新规则）。

两个相关的语义细节：by-name given（`given (using ...)` 形式的按名参数）会影响递归解析的终止；Scala 3.9 起**等价的候选被视为发散（divergent）**而不是任选一个，这让"两个定义一模一样的 given"从静默变成显式失败。

## Type Classes, the Standard Shape

Scala 里类型类是一个 trait + 一组 given + 一组 extension 的固定组合，扩展方法负责把能力变成点号语法：

```scala
trait Show[T]:
  def show(t: T): String

object Show:
  def apply[T](using s: Show[T]): Show[T] = s                 // sumoner
  given Show[Int] with { def show(i: Int) = i.toString }
  extension [T](t: T)(using s: Show[T]) def display: String = s.show(t)

import Show.given
println(42.display)
```

`derives` 让编译器为 ADT 自动生成实例，背后是 `Mirror` 与宏派生：

```scala
case class Person(name: String, age: Int) derives Show
```

这一条的意义是"类型类不必手写样板"，也是 Scala 3 把 Scala 2 那些 shapeless / magnolia 技巧标准化的结果。

## Conversions, and Why `into` Exists

隐式转换是 `implicit` 里争议最大的那一项：全局开启意味着任何类型不匹配都可能被悄悄改写，可读性极差。Scala 3 的做法是让转换显式化——`Conversion[A, B]` 是一个普通的类型类，需要 `using` 才生效：

```scala
given Conversion[Int, String] with
  def apply(i: Int): String = i.toString
```

`Conversion` 默认不自动生效（需要 `scala.language.implicitConversions` 或作用域内有 given）。SIP-71 在 3.9 稳定了 `into`，它把"此处允许隐式转换"这件事**限定到 API 作者指定的参数或类型上**，而不是要求全体用户打开一个全局开关：

```scala
def appendAll[A](xs: List[A], ys: IterableOnce[A]): List[A] = xs ++ ys
// 用 into 标记：只在这个位置接受转换
def prependAll[A](xs: Conversion.into[IterableOnce[A]], ys: List[A]): List[A] = ...
```

这是"局部打开危险特性"的一个范本：危险还在，但边界由 API 定义者负责，而不是由调用方承担。

## Scala 2 to Scala 3 Cheat Sheet

| Scala 2 | Scala 3 | 说明 |
| :--- | :--- | :--- |
| `implicit val x: T = ...` | `given x: T = ...` | 候选实例 |
| `implicit def f[T] (...): T` | `given [T] (...): T = ...` | 带参候选 |
| `implicit class Pimped(v: V)` | `extension (v: V)` | 扩展方法 |
| `def f(implicit x: T)` | `def f(using x: T)` | 需求声明 |
| `implicitly[T]` | `summon[T]` | 取出候选 |
| `implicit object Foo extends Bar` | `given Foo: Bar with ...` | 单例候选 |
| `implicit conversion` | `Conversion[A, B]` 的 given | 转换 |
| `import lib._`（带 implicit） | `import lib.given` | 只导候选 |

迁移本身由 Scalafix 规则与编译器的 `-source:3.0-migration` 模式承担，能自动解决大部分；剩下的难点几乎全在隐式相关的位置（宏、隐式转换、类型投影），见 [版本线与迁移](/docs/CS/Scala/Migration_and_Versions.md)。

## Links

- [Scala](/docs/CS/Scala/Scala.md)
- [类型系统](/docs/CS/Scala/Type_System.md)
- [语法骨架](/docs/CS/Scala/Syntax.md)
- [宏与元编程](/docs/CS/Scala/Macros.md)
- [版本线与迁移](/docs/CS/Scala/Migration_and_Versions.md)

## References

- [Contextual Abstractions — Given Instances](https://docs.scala-lang.org/scala3/reference/contextual/givens.html)
- [Using Clauses](https://docs.scala-lang.org/scala3/reference/contextual/using-clauses.html)
- [Context Bounds](https://docs.scala-lang.org/scala3/reference/contextual/context-bounds.html)
- [Importing Givens](https://docs.scala-lang.org/scala3/reference/contextual/given-imports.html)
- [Relationship with Scala 2 Implicits](https://docs.scala-lang.org/scala3/reference/contextual/relationship-implicits.html)
- [Type Class Derivation](https://docs.scala-lang.org/scala3/reference/contextual/derivation.html)
- [Implicit Conversions](https://docs.scala-lang.org/scala3/reference/contextual/conversions.html)
