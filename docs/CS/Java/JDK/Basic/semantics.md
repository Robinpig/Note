## Introduction

这里收录 Java 语言中**容易被忽略、但直接影响程序正确性与可维护性的语义规则**，分两层：一是《Effective Java》式的**使用纪律（idiom）**，二是 JLS 层面的**底层求值/内存语义**。它们大多不是新 API，而是对既有语法语义的正确理解。

## for-each

**Prefer for-each loops to traditional for loops.**

for-each（增强 for 循环）在编译后等价于对 `Iterable` 调用 `iterator()` 并用 `hasNext()`/`next()` 遍历，对数组则编译为带下标的普通 for。它消除了手写索引/迭代器时的两类典型错误：

- 迭代器被重复 `next()`（一次循环里调两次，漏元素或抛 `NoSuchElementException`）；
- 在多个集合间遍历时把迭代器/索引变量用混。

```java
// 传统写法：i、j 很容易写错，且嵌套时可读性差
for (Iterator<Suit> i = suits.iterator(); i.hasNext(); ) {
    Suit suit = i.next();
    for (Iterator<Rank> j = ranks.iterator(); j.hasNext(); )
        deck.add(new Card(suit, j.next()));
}

// for-each：意图清晰，不接触迭代器
for (Suit suit : suits)
    for (Rank rank : ranks)
        deck.add(new Card(suit, rank));
```

三类不适用 for-each 的场景：需要**删除**元素（用 `Iterator.remove()` 或 `Collection.removeIf`）、需要**替换/赋值**元素（数组或 list 的 set）、需要并行遍历多个集合（必须显式控制迭代器或索引）。

## try-with-resources

**Prefer try-with-resources to try-finally.**

Java 7 之前靠 `try-finally` 关闭资源，但当 `try` 块和 `close()` **同时抛异常**时，finally 中的异常会压制（suppress）原始异常，堆栈里只剩关闭异常，真正的故障被吞掉。多个资源时还要嵌套 finally，代码脆弱。

实现了 `AutoCloseable` 的资源放进 try-with-resources 后：编译器生成的代码保证逆序关闭，且被抑制的异常通过 `addSuppressed` 保留下来，`getSuppressed()` 仍可取回。

```java
// 正确写法：即使 read 与 close 都失败，也能看到 read 的根因异常
try (InputStream in = new FileInputStream(src);
     OutputStream out = new FileOutputStream(dst)) {
    in.transferTo(out);
}
```

## interface

### Refer to objects by their interfaces

只要接口类型存在，变量、参数、返回值、字段就应优先用接口（`List`、`Map`、`Set`）而不是具体类（`ArrayList`、`HashMap`）声明。好处是切换实现时只改构造器一处：

```java
List<String> users = new ArrayList<>();   // 换 LinkedList 只影响这一行
```

若依赖了具体类的特殊方法（如 `LinkedHashMap` 的顺序语义），就必须用具体类型声明。规则是「用满足需求的最抽象类型」；没有合适接口时（如 `String`、`ThreadPoolExecutor` 的调优 API），用具体类本身正当。

### Prefer interfaces to reflection

[Reflection](/docs/CS/Java/JDK/Basic/Reflection.md) 能在运行时按名字加载类、访问方法和字段，代价是：

- **丧失编译期类型检查**：方法名拼错、参数类型不符，运行到该路径才炸；
- **代码啰嗦且性能差**：方法发现、参数装箱、`setAccessible` 都有开销，JIT 也难以内联反射调用；
- **破坏封装**：可访问私有成员，依赖内部实现，升级 JDK/库时极易失效（模块系统之后还受 opens 限制）。

推荐模式是：**用反射只做「实例化」这一步**——通过 `Class.forName` 拿到类后，让创建出的对象以某个编译期已知的接口或父类类型被引用，后续调用全部走正常方法：

```java
Set<String> s = (Set<String>) Class.forName("java.util.LinkedHashSet")
                                   .getDeclaredConstructor().newInstance();
s.add("x"); // 编译期检查，无需反射
```

典型正当用途是依赖注入、[SPI](/docs/CS/Java/JDK/Basic/SPI.md) 加载、序列化框架这类「编译期确实不知道具体类」的基础设施；普通业务逻辑应优先用接口与工厂方法。

## Value vs Reference

**Java 只有值传递（pass-by-value）。** 方法参数无论是基本类型还是引用类型，传递的都是「值的一个拷贝」：

- 基本类型：拷贝的是值本身，方法内修改不影响调用方；
- 引用类型：拷贝的是**引用的值**（对象地址），因此方法内可通过该引用修改对象的**内部状态**，但**无法让调用方的引用指向另一个对象**。

```java
static void swap(Object a, Object b) { Object t = a; a = b; b = t; } // 无效：只交换了拷贝
static void append(List<String> l) { l.add("x"); }                  // 有效：通过引用改了对象内部
```

这一语义常被误读为"对象按引用传递"。理解它可避免写出"试图交换两个对象引用"的无效代码，也解释了数组/集合作为参数时被原地修改的现象。

## Evaluation Order

JLS §15.7 规定：**操作数按左到右的顺序求值（eager，除了短路运算符）**。这条规则带来两个易错点：

- **复合副作用陷阱**：`i = i++;` 中 `i++` 先返回旧值再自增，但赋值又用旧值覆盖了自增结果——最终 `i` 不变。不要在同一表达式里对同一变量既读又写又赋值。
- **方法实参求值顺序**：`f(a(), b())` 中 `a()` 一定先于 `b()` 被调用（左到右），但 `a()` 与 `b()` 的求值互不依赖；若两者有共享可变状态，行为仍可预测但易读性差，应避免。

短路运算符 `&&`、`||`、`?:` 的**右操作数可能不被求值**（条件已定），`|`、`&`、`^` 则总是求两侧——不要用 `|` 当 `||` 的"安全版"，二者语义不同。

## equals and hashCode

自定义值类型（非枚举、非单例）重写 `equals` 时必须同时重写 `hashCode`，并遵守契约：

- **自反性** `x.equals(x)` 为 true；**对称性** `x.equals(y) == y.equals(x)`；**传递性**；**一致性**（比较所用字段不变时结果不变）；**对 null 返回 false**；
- **`hashCode` 一致性**：相等的对象必须有相等的哈希码；**反之不要求**（哈希冲突允许）。
- 二者必须基于**同一组字段**：改了 `equals` 的比较字段，就必须同步更新 `hashCode`，否则对象在 `HashMap`/`HashSet` 中"丢失"。
- 高效写法：先 `if (this == o) return true;` 快速短路，再用 `getClass()`（或 `instanceof` 视是否需要子类兼容）判断类型，最后逐字段比较。

```java
@Override public boolean equals(Object o) {
    return o instanceof Point p && x == p.x && y == p.y;
}
@Override public int hashCode() {
    return Objects.hash(x, y);   // 与 equals 同字段集
}
```

现代写法优先用 [`record`](/docs/CS/Java/JDK/New.md?id=record)（自动生成正确的 `equals`/`hashCode`/`toString`）或 `java.util.Objects` 工具，避免手写失误。

## Exception Suppression

异常的"屏蔽"有两层含义，都关乎故障可见性：

- **try-with-resources 的 suppressed**：`try` 块与 `close()` 都抛异常时，close 的异常被挂到 `try` 异常的 `getSuppressed()` 上，根因不丢失（见 [try-with-resources](#try-with-resources)）；
- **finally 吞异常**：在 `finally` 块里 `return` 或 `throw`，会**直接丢弃** `try`/`catch` 中待传播的原异常——这是比 try-finally 资源泄漏更隐蔽的 bug，应禁止在 finally 中 return/throw。

```java
try {
    throw new IllegalStateException("root");
} finally {
    return;   // 错误：吞掉 IllegalStateException，调用方什么异常都看不到
}
```

## Generics Erasure

Java 泛型是**编译期**机制，**类型参数在运行时被擦除（erasure）**到其最左边界（无边界时 `Object`）。后果：

- 不能 `new T()`、`instanceof T`、`T.class`——运行时没有 `T` 的具体类信息；
- 桥方法（bridge method）：为保持多态，编译器在子类生成签名擦除后的合成方法转发到实际方法；
- 泛型数组禁止直接创建（`new T[size]` 非法），需用 `ArrayList` 或 `(T[]) new Object[size]` 并 `@SuppressWarnings`；
- 类型擦除使 `List<Integer>` 与 `List<String>` 在运行时是**同一个类**（`List`），这也是泛型不能用于方法重载区分（仅靠泛型差异）的原因。

与反射交互时拿到的是擦除后的类型，需用 `AnnotatedType`/`getGenericReturnType` 等 API 还原参数化信息。通配符的上界/下界与 `PECS`（Producer Extends, Consumer Super）规则见 [Generics](/docs/CS/Java/JDK/Basic/Generics.md)。

## final Semantics

`final` 字段的语义远超"不可重新赋值"，它还携带 **JMM（Java 内存模型）保证**：

- **跨线程可见性**：正确构造（未逸出 `this`）的对象，其 `final` 字段的值对其它线程**立即可见**，且 JMM 禁止把 `final` 字段的写入重排到构造器之外——即"冻结（freeze）"动作后，任何线程看到的都是完全构造好的 `final` 值；
- **this 逸出破坏保证**：若在构造器中把 `this` 发布给其它线程（如启动线程、注册监听器、赋值静态字段），`final` 的可见性保证失效；
- **与双重检查锁（DCL）**：`final` 字段的冻结语义足以让 `public static final Holder INSTANCE = new Holder()` 这类惰性初始化在部分场景免用 `volatile`；但若需发布**可变**对象仍需 `volatile`（见 [volatile](/docs/CS/Java/JDK/Concurrency/volatile.md)）。

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [PrimitiveType](/docs/CS/Java/JDK/Basic/PrimitiveType.md) — 装箱/拆箱与 == 的语义
- [Generics](/docs/CS/Java/JDK/Basic/Generics.md) — 类型擦除与通配符
- [Object](/docs/CS/Java/JDK/Basic/Object.md) — equals/hashCode/record
- [Reflection](/docs/CS/Java/JDK/Basic/Reflection.md) — 反射与泛型擦除
- [SPI](/docs/CS/Java/JDK/Basic/SPI.md)
- [volatile](/docs/CS/Java/JDK/Concurrency/volatile.md) — final 与 DCL 的可见性对照

## References

1. [Effective Java, 3rd Edition (Bloch)](https://www.oreilly.com/library/view/effective-java-3rd/9780134686097/)
2. [JLS §15.7 Evaluation Order](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.7)
3. [JLS §17.5 final Field Semantics](https://docs.oracle.com/javase/specs/jls/se25/html/jls-17.html#jls-17.5)
