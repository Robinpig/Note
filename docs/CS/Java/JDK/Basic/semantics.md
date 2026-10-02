## Introduction

这里收录《Effective Java》中几条容易被忽略、但直接影响程序正确性与可维护性的语义规则（language semantics / idiom）。
它们大多不是新 API，而是对 Java 既有语法语义的使用纪律：for-each、try-with-resources、面向接口编程、慎用反射。

## for-each

**Prefer for-each loops to traditional for loops.**

for-each（增强 for 循环）在编译后等价于对 `Iterable` 调用 `iterator()` 并用 `hasNext()`/`next()` 遍历，
对数组则编译为带下标的普通 for。它消除了手写索引/迭代器时的两类典型错误：

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

三类不适用 for-each 的场景：需要**删除**元素（用 `Iterator.remove()` 或 `Collection.removeIf`）、
需要**替换/赋值**元素（数组或 list 的 set）、需要并行遍历多个集合（必须显式控制迭代器或索引）。

## try-with-resources

**Prefer try-with-resources to try-finally.**

Java 7 之前靠 `try-finally` 关闭资源，但当 `try` 块和 `close()` **同时抛异常**时，finally 中的异常会压制（suppress）
原始异常，堆栈里只剩关闭异常，真正的故障被吞掉。多个资源时还要嵌套 finally，代码脆弱。

实现了 `AutoCloseable` 的资源放进 try-with-resources 后：编译器生成的代码保证逆序关闭，
且被抑制的异常通过 `addSuppressed` 保留下来，`getSuppressed()` 仍可取回。

```java
// 正确写法：即使 read 与 close 都失败，也能看到 read 的根因异常
try (InputStream in = new FileInputStream(src);
     OutputStream out = new FileOutputStream(dst)) {
    in.transferTo(out);
}
```

## interface

### Refer to objects by their interfaces

只要接口类型存在，变量、参数、返回值、字段就应优先用接口（如 `List`、`Map`、`Set`）而不是具体类（`ArrayList`、`HashMap`）声明。
好处是切换实现时只改构造器一处：

```java
// 面向接口：换 LinkedList 只影响这一行
List<String> users = new ArrayList<>();
```

若依赖了具体类的特殊方法（如 `LinkedHashMap` 的顺序语义），就必须用具体类型声明——规则是「用满足需求的最抽象类型」。
没有合适接口时（如 `String`、`ThreadPoolExecutor` 的调优 API），用具体类本身是正当的。

### Prefer interfaces to reflection

[Reflection](/docs/CS/Java/JDK/Basic/Reflection.md) 能在运行时按名字加载类、访问方法和字段，代价是：

- **丧失编译期类型检查**：方法名拼错、参数类型不符，运行到该路径才炸；
- **代码啰嗦且性能差**：方法发现、参数装箱、`setAccessible` 都有开销，JIT 也难以内联反射调用；
- **破坏封装**：可访问私有成员，依赖内部实现，升级 JDK/库时极易失效（模块系统之后还受 opens 限制）。

推荐模式是：**用反射只做「实例化」这一步**——通过 `Class.forName` 拿到类后，
让创建出的对象以某个编译期已知的接口或父类类型被引用，后续调用全部走正常方法：

```java
// 反射仅限于构造，使用时仍是静态类型
Set<String> s = (Set<String>) Class.forName("java.util.LinkedHashSet")
                                   .getDeclaredConstructor().newInstance();
s.add("x"); // 编译期检查，无需反射
```

典型正当用途是依赖注入、[SPI](/docs/CS/Java/JDK/Basic/SPI.md) 加载、序列化框架这类「编译期确实不知道具体类」的基础设施；
普通业务逻辑应优先用接口与工厂方法。

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [Reflection](/docs/CS/Java/JDK/Basic/Reflection.md)
- [Generics](/docs/CS/Java/JDK/Basic/Generics.md) — 面向接口声明时常配合泛型
- [SPI](/docs/CS/Java/JDK/Basic/SPI.md)

## References

1. [Effective Java, 3rd Edition (Bloch)](https://www.oreilly.com/library/view/effective-java-3rd/9780134686097/)
