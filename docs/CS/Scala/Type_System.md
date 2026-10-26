## Introduction

Scala 的类型系统不是"静态类型 + 推断"这么简单，它真正的特征是：**类型层本身是一门可编程的语言**。Scala 3 把这些能力收敛到 DOT 演算的一小组原语上——交集、联合、型变、依赖方法类型、类型层模式匹配——然后再用它们拼出日常语法。本篇讲这套原语的边界：型变标注的确切含义、类型格的形状、交集与联合取代了什么、opaque type 与 match type 各自的适用场景、以及 dependent / polymorphic / context function 三种函数类型的区分。

边界划分：候选值如何被编译器自动找出来在 [上下文抽象](/docs/CS/Scala/Contextual_Abstractions.md)；类型层能力的运行时代价与字节码形态在 [JVM 互操作](/docs/CS/Scala/JVM_Interop.md)；`match type` 与值层 `match` 的分工对照 [模式匹配](/docs/CS/Scala/Pattern_Matching.md)；`-Yexplicit-nulls` 与 `-Ycc` 这类实验开关的状态判定在 [版本线与迁移](/docs/CS/Scala/Migration_and_Versions.md)。本篇所有"从哪个版本起"的断言以 Scala Next 3.10.0 / LTS 3.9.0 为准。

## Variance Is an Obligation, Not an Annotation

型变标注写在类型参数上，声明的是**子类型关系如何随参数变化**：

```scala
class Box[+A]          // 协变：A <: B  ⟹  Box[A] <: Box[B]
class Sink[-A]         // 逆变：A <: B  ⟹  Sink[B] <: Sink[A]
class Inv[A]           // 不变：Box[A] 与 Box[B] 无子类型关系
```

编译器反过来会检查每个位置是否配得上这个声明：返回值位置允许协变，参数位置允许逆变，可变字段因为同时是读和写所以必须不变。`Function1[-T, +R]` 之所以能同时逆变入参、协变出参，就是这条检查的直接结论——它也是 Scala 里"函数可以安全替换"的基础：

```scala
val f: AnyRef => String = (x: AnyRef) => x.toString
val g: String => AnyRef = f          // 合法：AnyRef => String <: String => AnyRef
```

上界 `<:` 与下界 `>:` 则给出"参数可以往哪个方向动"：

```scala
def min[B >: A](x: B)(using ord: Ordering[B]): A   // List[A] 的定义，B 必须至少是 A 的超类
```

这条下界正是 `List[A]` 能安全做 `::` 的原因：向 `List[Cat]` 前插一个 `Dog` 得到的是 `List[Animal]`，而不是运行时爆炸。

## The Type Lattice

Scala 3 重画了类型格的顶端。Scala 2 里 `Any` 之下直接分 `AnyVal` / `AnyRef`；Scala 3 在 `Any` 与 `AnyRef` 之间插入了 `Matchable`：

| 类型 | 位置 | 说明 |
| :--- | :--- | :--- |
| `Any` | 顶 | `AnyVal`（`Int`、`Boolean`、`Unit`…）与 `AnyRef` 的共同超类 |
| `Matchable` | `Any` 之下 | 只有 `Matchable` 的值可以做模式匹配 |
| `AnyVal` / `AnyRef` | 两支 | 值类型 / 引用类型 |
| `Unit` | 值类型 | 只有一个值 `()`，对应 JVM 的 `void` 语义但有真实实例 |
| `Null` | 引用类型之底 | 常规模式下是 `AnyRef` 的子类型；`-Yexplicit-nulls` 下是所有引用类型的子类型 |
| `Nothing` | 全类型之底 | 无实例，用于"不会正常返回"（`throw`、`sys.exit`）与空集合的元素类型 |

`Matchable` 的插入解决的是一个实际的安全问题：某些抽象（如`Function1` 的实现细节或类型级代理）不应该被 `match` 窥探，Scala 3 让它们可以停在 `Any` 而不落到 `Matchable`，于是对这些值做模式匹配会得到警告。这是少见的"为了安全而收窄语言"的改动。

## Intersection and Union Types

这两个是 Scala 3 最直观的新增，而且**不是语法糖**——它们是类型格上真实的交与并：

```scala
trait Resettable:
  def reset(): Unit
trait Growable[T]:
  def add(t: T): Unit

def f(x: Resettable & Growable[Int]): Unit =
  x.reset()          // 交集的成员是两边的并集
  x.add(1)

def g(x: Int | String): Int = x match
  case i: Int    => i
  case s: String => s.length
```

要点：

- **交集 `A & B` 取代了 Scala 2 的 `A with B`**，成员取并集；自 Scala 3.10 起遗留的 `A with B` 写法在类型位置已是编译错误（这也是 3.10 与 Scala 2 无法再交叉编译的原因之一）。
- **联合 `A | B` 的成员是两边的交集**——不经 `match` 缩小，只能调用 `Any` 上有的东西（`hashCode`、`toString`、`==`）。这条限制是 union type 与 `Either` 的根本分工：`Either` 携带"是哪一个"的证据，`A | B` 不携带，要靠值层判定。
- 联合类型是 `Either` 的轻量替代，但不是替代品：`Either` 可以嵌套、可以保留偏侧性、可以做 `leftMap`，union 只能做"二选一且当场判明"。

## Opaque Types

`opaque type` 给出一个**对外不透明、对内等于底层类型**的新类型，编译期是屏障，运行期是同一个东西：

```scala
object Logarithms:
  opaque type Logarithm = Double

  object Logarithm:
    def apply(d: Double): Logarithm = math.log(d)

  extension (x: Logarithm)
    def toDouble: Double = math.exp(x)
    def +(y: Logarithm): Logarithm = Logarithm(math.exp(x) + math.exp(y))
```

三条性质决定了它取代什么：

1. 边界外看不到 `Logarithm` 就是 `Double`，所以 `val x: Logarithm = 3.0` 不合法；
2. 边界内它就是 `Double`，运算不需要装箱、不需要 wrapper 对象；
3. 它定义在 object 内，作用域规则与伴生对象一致（因此 `given` 的可见性规则同样适用，3.10 起不可访问的伴生 given 不再被找到）。

它与 Scala 2 的 value class 的分工是：value class 只在"单个字段的类"上有意义且不能有自己的扩展方法集合，opaque type 更通用。**它不提供范围约束**——`opaque type Port = Int` 不会阻止 `Port(99999)`，要约束仍然靠 refine 类型或库（如 iron / neotype）。

## Match Types

match type 把模式匹配搬到了类型层：

```scala
type Elem[X] = X match
  case String      => Char
  case Array[t]    => t
  case Iterable[t] => t

val c: Elem[String]  = 'a'   // Elem[String] 归约到 Char
val i: Elem[List[Int]] = 1   // 归约到 Int
```

归约发生在编译期，归约不下去时（如 `Elem[Int]`）该类型是"未归约"的抽象类型，任何使用都会失败。它的典型用途是**让返回类型依赖于入参类型**——这正是依赖类型想做的事，Scala 用"类型层模式匹配 + 归约"这条更受限但可判定的路径实现。写法上的坑是递归 match type 需要显式终止条件，否则编译器报归约超限；Scala 3.10 起超限会以 "Recursion limit exceeded" 报告而不再是 `StackOverflowError` 崩溃。

## Three Kinds of Function Type

Scala 3 有三种长得像函数的东西，混淆它们是读不懂新代码的主要原因：

| 写法 | 名称 | 含义 |
| :--- | :--- | :--- |
| `(e: T) => e.Key` | dependent function type | 返回类型依赖于**参数值** |
| `[A] => List[A] => Option[A]` | polymorphic function type | 调用方选择类型参数，函数体内对 `A` 抽象 |
| `ExecutionContext ?=> T` | context function | 参数由编译器按 `using` 规则自动填入 |

```scala
val head: [A] => List[A] => Option[A] =
  [A] => (xs: List[A]) => xs.headOption

def withContext[T](body: ExecutionContext ?=> T): T =
  body(using summon[ExecutionContext])
```

context function 是"隐式参数"在函数类型上的对应物，也是 direct style 效应传递的语法基础——`?=>` 让能力（capability）沿调用链自动传递而不必逐层手写参数，配合 capture checking 时可以进一步约束"能力不许逃出作用域"。

## Higher-Kinded Types and Type Lambdas

泛型参数本身可以是构造器，`F[_]` 就是"接受一个类型构造出另一个类型"：

```scala
trait Functor[F[_]]:
  def map[A, B](fa: F[A])(f: A => B): F[B]

type Tup2 = [X] =>> (X, X)        // 类型 lambda：把二元类型部分应用成一元的
type EitherString = [X] =>> Either[String, X]
```

`=>>` 是 Scala 3 的类型 lambda 语法（对应 Scala 2 里靠 type projection 或类型成员的绕法）。它是高阶类型能被写出来、被推断出来的前提，也是 cats 那套 `F[_]` 抽象的载体。

## Experimental Extensions Worth Knowing

两个仍在实验状态但方向明确的类型层扩展：

```scala
// -Yexplicit-nulls：Null 从 AnyRef 的子类型提升为所有引用类型的子类型，
// 于是 String 与 String | Null 成为不同类型，Java 返回值要显式声明可空
val s: String | Null = javaMap.get("k")
```

- **explicit nulls**（`-Yexplicit-nulls`）：把空值纳入类型系统，代价是与未标注的 Java 库边界处需要大量 `| Null` 与 `.nn`（非空断言）。
- **capture checking**（`-Ycc` 或 `import scala.language.experimental.captureChecking`）：在类型上标注捕获集，`T^{io}` 表示这个值捕获了 `io` 能力，`A -> B` 是纯函数箭头而 `A => B` 是可捕获任意能力的旧箭头。这是 Scala 把效应与资源逃逸问题搬进类型系统的尝试，方向接近 Rust 的借用检查但落在 JVM 上；写作时仍是实验特性，尚不可用于生产。

## Links

- [Scala](/docs/CS/Scala/Scala.md)
- [上下文抽象](/docs/CS/Scala/Contextual_Abstractions.md)
- [模式匹配](/docs/CS/Scala/Pattern_Matching.md)
- [JVM 互操作](/docs/CS/Scala/JVM_Interop.md)
- [编程语言横向对比](/docs/CS/Languages.md)

## References

- [Scala 3 Reference — New Types](https://docs.scala-lang.org/scala3/reference/new-types.html)
- [Union Types](https://docs.scala-lang.org/scala3/reference/new-types/union-types.html) / [Intersection Types](https://docs.scala-lang.org/scala3/reference/new-types/intersection-types.html)
- [Opaque Type Aliases](https://docs.scala-lang.org/scala3/reference/other-new-features/opaques.html)
- [Match Types](https://docs.scala-lang.org/scala3/reference/new-types/match-types.html)
- [Dependent Function Types](https://docs.scala-lang.org/scala3/reference/new-types/dependent-function-types.html)
- [Polymorphic Function Types](https://docs.scala-lang.org/scala3/reference/new-types/polymorphic-function-types.html)
- [Context Functions](https://docs.scala-lang.org/scala3/reference/contextual/context-functions.html)
- [Type Lambdas](https://docs.scala-lang.org/scala3/reference/new-types/type-lambdas.html)
- [Explicit Nulls（实验）](https://docs.scala-lang.org/scala3/reference/experimental/explicit-nulls.html)
- [Capture Checking（实验）](https://docs.scala-lang.org/scala3/reference/experimental/cc.html)
