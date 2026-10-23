## Introduction

模式匹配在 Scala 里不是 `switch` 的加强版，而是**解构 + 类型收窄 + 穷尽性检查**的组合设施。它承担了三件通常在别的语言里分开的事：把代数数据类型拆开、把 `A | B` 这样的联合类型缩到一边、把泛型擦除后丢失的类型信息用类型测试重新拿回来。这三件事共用一个 `match`，是 Scala 代码看起来"密度很高"的主要原因。

本篇讲值层模式匹配的机制与边界：extractor 的三种形态、sealed 带来的穷尽性检查、擦除与 `TypeTest`、`boundary` / `break` 提供的非局部退出、以及 multiversal equality 这条默认宽松、可选收紧的相等语义。类型层的模式匹配（match type）在 [类型系统](/docs/CS/Scala/Type_System.md)；`enum` 与 ADT 的定义在 [语法骨架](/docs/CS/Scala/Syntax.md)。

## Three Shapes of `unapply`

自定义模式的入口是 extractor，三种形态对应三种需求：

```scala
// 1. 提取单个值
object Email:
  def unapply(s: String): Option[(String, String)] =
    s.split("@", 2) match
      case Array(user, domain) => Some((user, domain))
      case _                   => None

// 2. 布尔判定（不绑定变量）
object Even:
  def unapply(i: Int): Boolean = i % 2 == 0

// 3. 提取定长序列
object Split:
  def unapplySeq(s: String): Option[Seq[String]] = Some(s.split(",").toSeq)
```

```scala
"a@b.com" match
  case Email(user, domain) => s"$user at $domain"
  case _                   => "not an email"

n match
  case Even() => "even"
  case _      => "odd"
```

关键性质：extractor 是普通方法调用，没有特权；模式匹配失败就是 `unapply` 返回 `None`（或 `false`）。这也意味着**模式的开销就是一次函数调用**——它不像 `switch` 那样天然廉价，热路径上的匹配要考虑这一点。

`case class` 的伴生自带 `apply` / `unapply`，所以自定义 ADT 不需要手写 extractor；Scala 3 的 `enum` 同样自动生成。

## Exhaustivity Is a Warning, Not a Guarantee

`sealed` 的作用是告诉编译器"子类型都在这个文件里"，于是检查可以判定是否漏了分支：

```scala
enum Shape:
  case Circle(r: Double)
  case Rect(w: Double, h: Double)

def area(s: Shape): Double = s match
  case Shape.Circle(r) => math.Pi * r * r
  // 漏掉 Rect —— 编译器警告：match may not be exhaustive
```

三条实际结论：

- **穷尽性是警告不是错误**，要靠 `-Xfatal-warnings`（或 sbt 里 `scalacOptions += "-Xfatal-warnings"`）把它变成失败，否则它会被忽略。
- **`sealed` 只在同文件内有效**；跨文件扩展会让检查失效。Scala 3 的 `enum` 天然满足这个约束。
- 加了 `case _ =>` 兜底后检查就永远通过了，代价是以后新增分支时不会再提醒你——把兜底写窄（明确列出剩余分支）通常比 `case _` 更好。

## Erasure, TypeTest, and runtimeChecked

JVM 擦除泛型，所以 `case xs: List[Int]` 这类模式只能检查出"是个 `List`"，元素类型检查不到，编译器会给出 unchecked 警告。Scala 3 用 `TypeTest` 把这件事显式化：

```scala
val xs: List[Any] = List(1, "a")

xs match
  case ints: List[Int] => ...     // warning: unchecked，元素类型无法验证
```

`TypeTest`（`scala.reflect.TypeTest`）是给 extractor 用的显式类型测试抽象，让库作者可以自己提供"如何判断元素类型"的实现。SIP-57（3.8 起稳定）引入 `runtimeChecked` 来替代那些被误用的 `@unchecked`：后者是"闭嘴"，前者是"我知道这里要运行时检查，并且明确要求生成它"——语义相同但意图可查。

## Non-local Exits: boundary and break

Scala 3 移除了非局部返回（在闭包里 `return` 抛出 `NonLocalReturnControl` 的那套），用 `boundary` / `break` 替代：

```scala
import scala.util.boundary, boundary.break

def firstNegative(xs: List[Int]): Option[Int] = boundary:
  for x <- xs do
    if x < 0 then break(Some(x))
  None
```

`boundary` 划定一个可退出作用域，`break` 从中返回。它比旧的 `return` 更可预测（退出点由作用域决定，而不由方法决定），也是"没有异常开销的提前退出"——实现上确实依赖异常，但语义被限制在词法作用域内。它常被视为 Scala 走向代数效应的一块垫脚石：boundary 类似 handler，break 类似 effect operation。

## Multiversal Equality

Scala 2 允许任意两个对象用 `==` 比较，于是 `Option[Int] == "x"` 合法且总是 false——这类 bug 静默无声。Scala 3 提供了 opt-in 的 `strictEquality`：

```scala
// 全局开启（sbt: scalacOptions += "-language:strictEquality"）
// 或者局部：import scala.language.strictEquality

val a: Option[Int] = Some(1)
a == "x"   // 开启后编译错误：Values of types Option[Int] and String cannot be compared
```

开启后只有"存在 `CanEqual[A, B]` 给定实例"的类型之间才能比较。SIP-67（3.10 起稳定）进一步让**严格相等模式下的模式匹配不再需要 `CanEqual`**——此前开启严格相等会让 ADT 的模式匹配也要求 `CanEqual` 实例，成为推广这一特性的主要阻力。需要强调的是：`strictEquality` 至今仍是 opt-in，绝大多数项目没有开启。

## Matching on Union Types

联合类型与模式匹配是配套设计：`A | B` 不携带"是哪一个"的证据，判定的唯一手段就是 match：

```scala
def render(v: Int | String | Boolean): String = v match
  case i: Int     => i.toString
  case s: String  => s
  case b: Boolean => if b then "yes" else "no"
```

编译器会检查每个分支的类型并收窄，分支顺序影响结果（`case i: Int` 在前时 `Int` 分支会先命中）。对比 `Either`：后者在类型里就带着偏侧信息，可以 `fold` 而不必 match，代价是要多包一层。选哪个取决于"是不是需要把这个可能性传给别处"。

## What It Compiles To

理解产物有助于判断热路径成本：

- 对 `sealed` 层次且分支较多时，编译器可能生成 `tableswitch` / `lookupswitch`；
- 其余情况是 `if (x instanceof T) { ... } else if ...` 的链，分支越多越靠后的分支越慢；
- extractor 分支则是"调用 `unapply` + 判空"的序列；
- `case class` 的解构是字段访问，没有额外开销。

所以对性能敏感的代码，把高频分支放在前面、避免在循环里反复做 extractor 匹配，比换数据结构更直接。

## Links

- [Scala](/docs/CS/Scala/Scala.md)
- [类型系统](/docs/CS/Scala/Type_System.md)
- [语法骨架](/docs/CS/Scala/Syntax.md)
- [集合库](/docs/CS/Scala/Collections.md)
- [函数式效应系统](/docs/CS/Scala/Effects.md)

## References

- [Pattern Matching（Scala 3 Book）](https://docs.scala-lang.org/scala3/book/taste-pattern-matching.html)
- [Extractors](https://docs.scala-lang.org/scala3/reference/changed-features/pattern-matching.html)
- [Multiversal Equality](https://docs.scala-lang.org/scala3/reference/contextual/multiversal-equality.html)
- [TypeTest](https://docs.scala-lang.org/scala3/reference/other-new-features/type-test.html)
- [Nonlocal Returns Dropped（boundary/break）](https://docs.scala-lang.org/scala3/reference/dropped-features/nonlocal-returns.html)
- [Match Types](https://docs.scala-lang.org/scala3/reference/new-types/match-types.html)
