## Introduction

Scala 与 Java 可以互相调用，这件事在语法层面几乎无感——直接 `new ArrayList[String]()` 就行。但"能调用"和"语义对齐"是两件事：Scala 的 `==` 是 `equals` 语义而 Java 的 `==` 是引用比较；Scala 的泛型默认不变量化而 Java 数组是协变的；Scala 的 trait 在 JVM 上没有对应物。这些不对齐的地方不会报错，只会静默产生错误行为。

本篇是双向的：从 Scala 看 Java（null、擦除、装箱、SAM、异常），以及从 Java 看 Scala（trait 编成什么、`object` 编成什么、名字 mangling、值类与 opaque type 的擦除结果）。平台层面的另外两个后端见 [平台](/docs/CS/Scala/Platforms.md)，编译产物与 TASTy 见 [编译流水线](/docs/CS/Scala/Compilation.md)。

## From Scala to Java

```scala
import java.util.{List => JList, ArrayList}

val xs: ArrayList[String] = new ArrayList[String]()
xs.add("a")
val n: Int = xs.size()
```

顺滑，但有五个具体的坑：

| 坑 | 说明 | 应对 |
| :--- | :--- | :--- |
| `null` | Java 返回值可能是 `null`，Scala 侧类型里看不出来 | 开启实验的 `-Yexplicit-nulls` 后用 `String \| Null`，或边界处立刻转换（见 [类型系统](/docs/CS/Scala/Type_System.md)） |
| 泛型擦除 | `xs: JList[Int]` 的元素类型运行时不可验证 | 不要对 Java 集合做带元素类型的模式匹配（见 [模式匹配](/docs/CS/Scala/Pattern_Matching.md)） |
| 数组协变 | Java 的 `Array[String]` 可以赋给 `Array[Object]` | Scala 的 `Array[T]` 同样协变（与 Scala 集合相反），这是唯一的不变 |
| 装箱 | `Int` 传给需要 `Integer` 的 API 会装箱 | 性能敏感处用 `Array[Int]` 或专门库 |
| checked exception | Scala **不检查**受检异常 | 与 Java 库对接时要自己记得 catch；`saferExceptions`（实验）试图把异常也纳入类型 |

集合互转用 `scala.jdk.CollectionConverters`（返回包装视图，零拷贝）：

```scala
import scala.jdk.CollectionConverters.*
val scalaBuf: scala.collection.mutable.Buffer[Int] = javaList.asScala
val javaList2: java.util.List[Int] = scalaBuf.asJava
```

## SAM Conversion

Java 的函数式接口（`@FunctionalInterface`）可以直接用 Scala 函数字面量填：

```scala
val r: Runnable = () => println("run")
executor.submit(r)

val cmp: java.util.Comparator[String] = (a, b) => a.length - b.length
```

Scala 3 改进了 SAM 转换的推断：参数类型可以按目标类型推断，不需要重复标注；并且 Scala 自己的 `trait` 只要只有一个抽象方法，也可以被这样转换。

## From Java to Scala: What Gets Emitted

反过来看编译器把 Scala 结构编成了什么——这是 Java 侧能否顺滑使用的决定因素：

| Scala 结构 | JVM 产物 | Java 侧可见性 |
| :--- | :--- | :--- |
| `trait` | `interface` + 抽象方法；具体实现编成 `default` 方法或静态转发 | 可以 `implements`，但混入（`with`）在 Java 侧要手写 |
| `class` | 普通 `class` | 正常 |
| `object Foo` | `Foo$` 单例类（含 `MODULE$`）+ `Foo` 的静态转发方法 | Java 用 `Foo$.MODULE$` 或静态转发器 |
| `case class` | 类 + 伴生工厂（`apply`）+ `equals`/`hashCode`/`toString`/`copy` | 工厂方法可用，但伴生的 `unapply` 对 Java 无意义 |
| `enum` | `sealed class` + 分支类 + 伴生的 `values` / `valueOf` | 可用，但不等于 Java `enum` |
| `opaque type` | 擦除为底层类型 | 完全透明（这正是它的设计目标） |
| value class | 擦除为底层类型（有编译器生成的伴生扩展） | 透明 |
| 运算符 `+`、`::` | 名字 mangling：`$plus`、`$colon$colon` | Java 侧要写 mangled 名，或用 `@targetName` 指定 |

两个值得单独记的：

- **`@targetName`**（Scala 3 特性）允许给方法指定一个 JVM 层面的名字，解决 mangling 与重载冲突（例如带 `using` 子句的方法在擦除后签名撞车）；
- **泛型签名**：Scala 3.8 大幅改进了向 Java 侧输出的泛型签名（HKT、context function、值类、trait 字段等场景），因为很多 Java 工具与框架是读签名字串而不是读字节码的。

## Annotations, Varargs, and Statics

- 注解直接复用 JVM 注解机制；Scala 注解可以加在类型、参数、字段上，Java 侧能否读到取决于 `@Retention`；
- 可变参数：`def f(xs: Int*)` 编成 `int...`，Java 侧可直接传数组；反过来说 Java 的 varargs 在 Scala 侧也可用；
- `object` 里的成员没有真正的 JVM `static`——Scala 3 也提供 `@static` 之类手段（SIP-30 的遗留），但一般靠静态转发器就够了；
- 顶层定义（Scala 3）编译成以文件名为前缀的合成类，Java 侧要按这个名字访问。

## Where the JVM Limits Scala

有三处是"Scala 想要但 JVM 给不了"，理解它们能解释不少设计选择：

1. **值类型**：Scala 的值类 / opaque type 只是编译期抽象，运行期仍会装箱（除非被内联掉）。JVM 侧的真正值类型要等 [Valhalla](/docs/CS/Java/JDK/Valhalla.md)。
2. **泛型的具体化**：擦除是所有"运行时拿不到类型参数"问题的根源，`TypeTest` 与 `ClassTag` 都是补丁。
3. **尾调用优化**：JVM 没有 TCO 指令，`@tailrec` 只能保证"编译器把它优化成循环"这件事成立，而不保证任意互递归被优化。

这三条也解释了为什么 Scala Native（不需要遵守 JVM 对象模型）在某些场景下能给出更好的产物，见 [平台](/docs/CS/Scala/Platforms.md)。

## Links

- [Scala](/docs/CS/Scala/Scala.md)
- [编译流水线](/docs/CS/Scala/Compilation.md)
- [平台](/docs/CS/Scala/Platforms.md)
- [类型系统](/docs/CS/Scala/Type_System.md)
- [模式匹配](/docs/CS/Scala/Pattern_Matching.md)

## References

- [Scala 3 — Relationship with Java](https://docs.scala-lang.org/scala3/book/interacting-with-java.html)
- [Java Interop FAQ](https://docs.scala-lang.org/overviews/java-interop.html)
- [Universal Apply Methods / @targetName](https://docs.scala-lang.org/scala3/reference/other-new-features/targetName.html)
- [Conversions Between Java and Scala Collections](https://docs.scala-lang.org/overviews/collections-2.13/conversions-between-java-and-scala-collections.html)
