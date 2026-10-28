## Introduction

> Ensure a class has only one instance, and provide a global point of access to it.
> —— GoF

单例模式保证一个类在进程中只有一个实例，并提供一个全局访问点。需要它的动机通常是"这个资源本该只有一份"：配置中心客户端、线程池、连接池、日志句柄、全局缓存、ID 生成器的段分配器。

单例的真正难点从来不是"怎么写"，而是三件事：**并发下不要产生第二个实例**、**反序列化/反射不要绕过私有构造器**、以及最容易被忽略的——**单例是可变的全局状态，它会把依赖关系藏起来**。

## Five Implementations

| 写法 | 懒加载 | 线程安全 | 防反射 | 防反序列化 | 结论 |
|------|--------|---------|--------|-----------|------|
| 饿汉（static final 字段） | 否 | 是（类初始化） | 否 | 否 | 最简单，实例化成本高时浪费 |
| 懒汉（用时 new） | 是 | 否 | 否 | 否 | 不要用 |
| 双检锁（DCL） | 是 | 是（需 volatile） | 否 | 否 | 经典写法，见下文 volatile 问题 |
| 静态内部类 Holder | 是 | 是（类初始化） | 否 | 否 | 懒加载 + 无线程同步开销，推荐 |
| 枚举 | 否 | 是 | 是 | 是 | Effective Java 推荐，但无法懒加载 |

```java
// 静态内部类 Holder：首次调用 getInstance 才加载 Holder 类，由 JVM 类初始化保证唯一
class Singleton {
    private Singleton() {}
    private static class Holder { static final Singleton INSTANCE = new Singleton(); }
    public static Singleton getInstance() { return Holder.INSTANCE; }
}

// 枚举：JVM 保证枚举常量全局唯一，天然免疫反射与反序列化
enum Singleton { INSTANCE; }
```

## Why DCL Needs volatile

双检锁里 `instance` 必须是 `volatile`，否则在 x86 之外的平台上可能读到"引用已赋值、构造器还没跑完"的半成品对象。根源在于 `instance = new Singleton()` 不是原子动作，优化后实际顺序可能是：

1. 分配内存；
2. 把引用 `instance` 指向这块内存；
3. 执行构造器初始化字段。

没有 `volatile` 时，另一个线程在步骤 2 之后、3 之前进入第一次判空，看到非 null 就直接返回一个字段全是默认值的对象。JDK 5 起的 JSR-133 内存模型规定 `volatile` 写与读之间建立 happens-before，构造器的所有写入对后续读可见，这个洞才被正式堵上。Holder 写法则绕开了整个问题——它依赖的是 JVM 对类初始化的同步保证。

## How Singletons Break

单例号称"唯一"，实际上有四条绕过硬私有构造器的路径：

- **反射**：`setAccessible(true)` 后调私有构造器，Holder 与 DCL 都拦不住（可在构造器里加"已初始化则抛异常"的防御）；
- **反序列化**：`readObject()` 会新建实例，需实现 `readResolve()` 返回既有实例；
- **多 ClassLoader**：同名类被两个类加载器各加载一份，各自持有"单例"，容器/模块化场景下是真事故；
- **多个进程/节点**：进程内单例对分布式毫无约束，需要的是分布式锁或注册中心，见 [Consul](/docs/CS/Framework/Spring_Cloud/Consul.md) 一类方案。

枚举一次性解决前两条，这是 Effective Java 把它列为首选的原因。

## The Spring Caveat

Spring 容器默认的 `singleton` scope 与 GoF 单例**不是一回事**：它指"同一个 ApplicationContext 内一个 bean 定义只创建一个实例"，而不是"JVM 内全局唯一"。同一个类在两个容器里就是两个实例；容器还没启动时代码手动 new 的也没有约束。

更工程化的态度是把单例当作**坏味道的中和剂而非目标**：可变全局状态让单元测试必须处理跨用例污染、让调用链隐式变长。Spring 的做法正是把"唯一"这件事从类内部挪到容器——类只负责无状态，实例的唯一性由 [IoC 容器](/docs/CS/Framework/Spring/IoC.md)统一管理，依赖方根本不感知"这是不是单例"。只有当资源本身要求进程唯一（如 `Executors` 创建的线程池）时，类级单例才是正解。

## Links

- [Design Patterns](/docs/CS/DesignPatterns/DesignPatterns.md)
- [Factory Method](/docs/CS/DesignPatterns/FactoryMethod.md)
- [Builder](/docs/CS/DesignPatterns/Builder.md)
- [IoC 容器](/docs/CS/Framework/Spring/IoC.md)
- [Java 并发](/docs/CS/Java/JDK/Concurrency/Concurrency.md)

## References

1. [Effective Java (3rd Edition) - Item 3: Enforce the singleton property](https://www.informit.com/store/effective-java-9780134685991)
2. [Refactoring.Guru - Singleton](https://refactoring.guru/design-patterns/singleton)
3. [OODesign - Singleton Pattern](https://www.oodesign.com/singleton-pattern)
4. [JSR-133 Java Memory Model and Thread Specification](https://www.cs.umd.edu/~pugh/java/memoryModel/jsr133.pdf)
