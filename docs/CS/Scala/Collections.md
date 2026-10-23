## Introduction

Scala 的集合库是它最独特、也是最常被误用的一块。独特之处在于：它是**同一套操作名覆盖可变与不可变两套实现**的设计（`map` 在 `List`、`Vector`、`ArraySeq`、`mutable.ArrayBuffer` 上写法完全一样），并且这套设计在 Scala 2.13 被彻底重写过——旧的三层继承 + `CanBuildFrom` 被换成 `IterableOnce` / `Iterable` / 具体集合的三层加 `IterableFactory`，Scala 3 完整继承了这次重写的结果。

被误用的原因在于**抽象泄漏**：同一个 `map` 在不同集合上的复杂度完全不同，`List.appended` 是 O(n) 而 `Vector.appended` 是均摊 O(log n)，看代码看不出来。本篇讲清层次结构、操作分类、主要实现的复杂度、以及惰性视图与 Java 互转。函数式组合子在效应系统中的对应物（fs2、ZIO Stream）见 [函数式效应系统](/docs/CS/Scala/Effects.md)，语法层面的 for 推导见 [语法骨架](/docs/CS/Scala/Syntax.md)。

## Three Layers and Two Flavours

```text
IterableOnce[A]          // 只能遍历一次，是 Iterator 与所有集合的共同下界
  └── Iterable[A]        // 可反复遍历，提供 iterator
        ├── Seq[A]       // 有序
        ├── Set[A]       // 唯一
        └── Map[K, V]    // 键值
```

`IterableOnce` 的存在是 2.13 重写的关键：它把"只消费一次的东西"（`Iterator`、`Array` 的某些视图）与"可反复遍历的集合"分开，于是 `foldLeft` 这类只需要单次遍历的操作可以接受 `Iterator`，而 `size` 这类需要反复遍历的操作只能挂在 `Iterable` 上。

三个包的分工：

| 包 | 内容 | 说明 |
| :--- | :--- | :--- |
| `scala.collection` | 通用接口 | 只描述操作，不承诺可变性 |
| `scala.collection.immutable` | 不可变实现 | **默认**，`Predef` 里的 `List` / `Map` / `Set` 都指向这里 |
| `scala.collection.mutable` | 可变实现 | 需显式导入 |

默认不可变是 Scala 的默认取向，也是它函数式风格的物理基础：不可变集合可以在线程间自由共享，见 [并发](/docs/CS/Scala/Concurrency.md)。

## Operations Fall Into Three Classes

| 类别 | 例子 | 返回 | 语义 |
| :--- | :--- | :--- | :--- |
| transformer | `map` / `flatMap` / `filter` / `++` | 同构的新集合 | 结构不变、元素变 |
| accessor | `head` / `last` / `find` / `size` | 单个值 | 需要"挑一个" |
| builder | `groupBy` / `toMap` / `distinct` | 异构的新集合 | 结构也变 |

返回类型由 `IterableFactory` 决定，这是 2.13 之后 `map` 能"保持集合种类"的机制：`List[Int].map(f)` 得到 `List[B]`，`Vector[Int].map(f)` 得到 `Vector[B]`。代价是**编译期要找这个工厂**，这也是集合操作编译慢、错误信息冗长的原因之一。

一个必须知道的边界情况：`Map.map` 要求函数返回键值对，否则结果类型会退化成 `Iterable`：

```scala
Map("a" -> 1).map((k, v) => v * 2)          // Iterable[Int]，不是 Map
Map("a" -> 1).map((k, v) => (k, v * 2))     // Map[String, Int]
```

## Complexity Is Not Uniform

同一操作在不同实现上的代价差一个数量级，这是使用集合库前必须查的表：

| 实现 | 结构 | `head` | `apply(i)` | `appended` | `prepended` | 适用场景 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `List` | 单向链表 | O(1) | O(n) | O(n) | O(1) | 小集合、只在头部操作、模式匹配解构 |
| `Vector` | 位映射向量（类 RRB） | 均摊 O(1) | 均摊 O(1) | 均摊 O(log n) | 均摊 O(log n) | 默认选择，随机访问 + 追加 |
| `ArraySeq` | 数组的不可变视图 | O(1) | O(1) | O(n) | O(n) | 定长、原始类型密集、与 Java 数组互操作 |
| `LazyList` | 惰性链表 | O(1)（可能触发计算） | O(n) | O(1) 惰性 | O(1) | 无限序列、按需生成 |
| `Queue` | 双端 | O(1) | O(n) | O(1) | O(1) | FIFO |
| `Set` / `Map` | CHAMP trie（2.13 起） | — | — | 均摊 O(log n) | — | 默认哈希容器 |

两条实践结论：

1. **默认用 `Vector` 而不是 `List`**，除非你要在头部反复 `::` 或者要用模式匹配解构；`List` 是链表，`xs.length` 与 `xs(1000)` 都是线性的。
2. **`List` 上 `:+`（追加）是 O(n)**，循环里反复 `xs :+ x` 构造列表是二次复杂度——要么反向 `x :: xs` 最后 `reverse`，要么一开始就用 `ListBuffer` / `Vector`。

## Views

`View` 把一串 transformer 变成惰性管线，避免每一步都产生中间集合：

```scala
val result = (1 to 1_000_000).view
  .map(_ * 2)
  .filter(_ % 3 == 0)
  .take(10)
  .toList          // 只在这里才开始计算，且只算够 10 个
```

要点与坑：

- `.view` 之后必须有一个严格化操作（`toList` / `toVector` / `force`）才会执行；
- view 是**一次性**的（它是 `IterableOnce`），重复遍历会重新计算甚至抛异常，需要重复用时先 `toVector`；
- 对小集合，view 的额外开销可能大于省下的分配——它只在"链条长 + 数据大 + 提前终止"时才划算；
- `Iterator` 与 `View` 的取舍：前者更底层、更省，后者可组合且不破坏集合 API。

## Interop with Java Collections

Scala 与 Java 集合互不兼容（Scala 2.13 之后 Scala 集合不再实现 `java.util` 接口），转换靠显式 converters：

```scala
import scala.jdk.CollectionConverters.*

val jList: java.util.List[Int] = List(1, 2, 3).asJava
val sList: mutable.Buffer[Int] = jList.asScala
```

它的成本是零——`asJava` / `asScala` 返回的是包装视图，不是拷贝。而 `scala.collection.JavaConverters`（Scala 2 的老 API）已弃用。反过来在 [JVM 互操作](/docs/CS/Scala/JVM_Interop.md) 里还有更一般的互操作规则。

## Performance Notes

几点与 JVM 现实有关的：

- **原语装箱**：`List[Int]` 的元素在 JVM 上是 `java.lang.Integer`。`@specialized` 在 Scala 3 中支持有限且带来代码膨胀，性能敏感场景应直接用 `Array[Int]` / `ArraySeq[Int]`，或者用专门库。
- **`for` 推导的开销**：`for` 展开成 `flatMap` / `map` / `withFilter`，每一步都有函数调用与工厂查找；带 `if` 守卫的推导在 Scala 2.13+ 用 `withFilter` 惰性过滤，避免了中间集合，但闭包本身仍有分配。热循环里手写 `while` 仍是合法选择。
- **结构共享**：不可变集合的 `updated` / `appended` 共享大部分节点，所以"复制"并不等于"全量拷贝"——这是 `Vector` 与 `Map` 可以放心传递的前提。

## Links

- [Scala](/docs/CS/Scala/Scala.md)
- [语法骨架](/docs/CS/Scala/Syntax.md)
- [函数式效应系统](/docs/CS/Scala/Effects.md)
- [并发](/docs/CS/Scala/Concurrency.md)
- [JVM 互操作](/docs/CS/Scala/JVM_Interop.md)

## References

- [Scala 2.13 Collections Architecture（Scala 3 沿用）](https://docs.scala-lang.org/overviews/core/architecture-of-scala-213-collections.html)
- [Immutable Collections Overview](https://docs.scala-lang.org/overviews/collections-2.13/introduction.html)
- [Performance Characteristics](https://docs.scala-lang.org/overviews/collections-2.13/performance-characteristics.html)
- [Views](https://docs.scala-lang.org/overviews/collections-2.13/views.html)
- [Conversions Between Java and Scala Collections](https://docs.scala-lang.org/overviews/collections-2.13/conversions-between-java-and-scala-collections.html)
