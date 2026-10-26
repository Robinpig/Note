## Introduction

> Separate the construction of a complex object from its representation so that the same construction process can create different representations.
> —— GoF

建造者模式把一个复杂对象的构建过程与它的最终表示拆开：调用方只给出参数，由一个 Builder 分步承接，最后在 `build()` 里统一校验并产出不可变对象。它治理的是**构造器参数膨胀**——当可选参数多到出现"哪个组合对应哪个构造器"的猜谜游戏时，就是该换 Builder 的信号。

## Three Ways to Pass Parameters

Effective Java 第 2 条的经典对比，按演进顺序：

**1. 重叠构造器（Telescoping Constructor）**：想要几个参数就写一个对应签名的构造器。参数一多就是组合爆炸，且调用方读代码时根本分不清 `new User(1, null, null, true)` 里那个 `true` 是什么。

```java
new User(id);                              // 只填 id
new User(id, name);                        // 填 id + name
new User(id, name, null, null, null, true); // 猜参数
```

**2. JavaBeans 设值方式**：无参构造器 + 一串 setter，调用方可读了。但代价是**对象状态在构造完成前不一致**——setter 之间的顺序约束（先 setA 再 setB）无人校验，且对象从此可变，线程间共享需要额外同步。

**3. Builder**：兼顾可读性与不可变性，唯一的"缺点"是要先写一个 builder 类。

```java
User u = new User.Builder(id, name)   // 必填参数放构造器
             .age(18).vip(true)        // 可选参数链式设值
             .build();                 // 此处统一校验、产出不可变对象
```

校验逻辑集中在 `build()` 是常被低估的价值：`age` 与 `birthday` 是否矛盾、`vip` 是否需要 `phone`，都在一处判定，不会出现"建了一半的非法对象"。

## The Signature Move

必填参数进 Builder 构造器、可选参数做成返回 `this` 的设值方法、`build()` 私有化目标类构造器——这三步决定了它和普通 setter 的区别：**调用链结束前对象根本不存在**。目标类字段全部 `final`，天然不可变、天然线程安全，也不需要防御性拷贝之外的同步手段。

Lombok 的 `@Builder` 把样板机械化，但它会为**所有**字段生成设值方法（含非空校验需要自己加 `@NonNull` 或手工 build），参数多时不如手写 Builder 可控。JDK 自己也是这么用的：`HttpRequest.newBuilder()`、`Stream.Builder`、`StringBuilder`（严格说是同族简化版）、以及 protobuf 的 `Message.Builder`——protobuf 把 Builder 用成了消息构造的标准接口，`build()` 之后得到不可变消息。

## Boundary with Similar Patterns

- **工厂方法**：工厂一次成型、通常返回接口类型、重点是"选哪个实现"；Builder 分步装配、重点是"怎么组装"、通常产出具体类型。二者可串接：工厂决定造什么，Builder 决定怎么造；
- **原型模式**：从现有实例拷贝再改，改的是已有状态；Builder 从零累积，改的是参数；
- **不可变 + 静态工厂**：参数少（1~3 个）时静态工厂方法更直接，别为两个参数建一套 Builder——Effective Java 同样警告"参数少就别用 Builder"。

## Links

- [Design Patterns](/docs/CS/DesignPatterns/DesignPatterns.md)
- [Factory Method](/docs/CS/DesignPatterns/FactoryMethod.md)
- [Singleton](/docs/CS/DesignPatterns/Singleton.md)
- [OOP](/docs/CS/Java/OOP.md)

## References

1. [Refactoring.Guru - Builder](https://refactoring.guru/design-patterns/builder)
2. [OODesign - Builder Pattern](https://www.oodesign.com/builder-pattern)
3. [Effective Java (3rd Edition) - Item 2: Consider a builder when faced with many constructor parameters](https://www.informit.com/store/effective-java-9780134685991)
