## Introduction

HikariCP 的「快」来自一组叠加的微优化，每一项单独看几乎不可测量，组合起来把单次借还开销压到极低。本文拆解 `FastList`、`ConcurrentBag`、字节码代理三项核心手段。组件与主链路见 [Architecture](/docs/CS/Java/ConnectionPool/HiKariCP/Architecture.md)。

## FastList vs ArrayList

一处非平凡的性能优化是移除 `ConnectionProxy` 里用于跟踪打开 `Statement` 的 `ArrayList<Statement>`：关闭 `Statement` 要从集合删除、关闭连接要遍历关闭所有打开的 `Statement` 并清空。Java `ArrayList` 出于通用性，每次 `get(int)` 都做范围检查，而这里的范围是我们能保证安全的，纯属开销。

此外 `ArrayList.remove(Object)` 从头到尾扫描；而 JDBC 常见用法是「用完立即关」或「逆序关」，从尾部扫描会更快。因此 `ArrayList<Statement>` 被替换为自定义类 `FastList`：消除范围检查，且移除扫描**从尾到头**。

Link: [ArrayList - JDK](/docs/CS/Java/JDK/Collection/List.md?id=arraylist)

## ConcurrentBag

HikariCP 实现了一个自定义的无锁集合 `ConcurrentBag`（灵感来自 .NET 的 `ConcurrentBag`，但内部实现完全不同）。它提供：

- **无锁设计**：借还路径避免 `synchronized` / 重量级锁
- **ThreadLocal 缓存**：线程优先取自己刚归还的连接，避免跨线程争用
- **队列窃取（queue-stealing）**：本线程无空闲时从共享队列/其他线程「窃取」连接
- **直接交接（direct hand-off）**：新连接可被直接交给等待者，不必先入队
- **最小化伪共享（false-sharing）**：通过字段填充降低 cache-line 争用

结果是高并发度、极低延迟、伪共享发生最少。7.x 又用 `VarHandle` 重写并发控制，进一步压低争用开销。

## Bytecode Optimizations

代理连接/语句/结果集的创建走 `invokevirtual -> invokestatic`：

```java
public final class ProxyFactory {
    private ProxyFactory() {
        // unconstructable
    }

    static ProxyConnection getProxyConnection(final PoolEntry poolEntry, final Connection connection, final FastList<Statement> openStatements, final ProxyLeakTask leakTask, final long now, final boolean isReadOnly, final boolean isAutoCommit) {
        // Body is replaced (injected) by JavassistProxyFactory
        throw new IllegalStateException("You need to run the CLI build and you need target/classes in your classpath to run.");
    }
}
```

`ProxyFactory` 的 `getProxyConnection(...)` 方法体在**构建期由 Javassist 注入**——HikariCP 不用 JDK 动态代理（反射 + 接口方法查表），而是在编译/打包阶段生成 `ProxyConnection` / `ProxyStatement` / `ProxyResultSet` 等具体代理类，把原本走虚方法分派的调用改成 `invokestatic` 直接调用，省去虚调用的方法表查找与去优化开销。这也是 `ProxyConnection.close()`（见 Architecture）能直接做归还逻辑、且不引入反射成本的来源。

## Cross-Pool Comparison

| 设计取舍 | HikariCP | Druid | DBCP2 |
| --- | --- | --- | --- |
| 连接容器 | `ConcurrentBag` 无锁 | 加锁的数组 + 双端队列 | Commons-Pool2 对象池 |
| 代理方式 | Javassist 字节码生成（静态调用） | 动态代理 / 包装器 | 动态代理 |
| 设计目标 | 极致借还性能 | 可观测 + 可管控（防火墙/统计） | 稳定通用、接口兼容 |
| 体积/依赖 | 极小 | 较大（含 Parser/Filter 体系） | 中等 |

HikariCP 通过「更少组件 + 无锁 + 字节码」在借还热路径上做到极致；代价是把监控、防注入等能力交还给外部体系（见 [Monitoring](/docs/CS/Java/ConnectionPool/HiKariCP/Monitoring.md)）。选型对照见 [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md) 的 `## Implementations Map`。

## Links

- [HiKariCP](/docs/CS/Java/ConnectionPool/HiKariCP.md)
- [Architecture](/docs/CS/Java/ConnectionPool/HiKariCP/Architecture.md)
- [Druid](/docs/CS/Java/ConnectionPool/Druid.md)
- [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)

## References

1. [HikariCP FAQ](https://github.com/brettwooldridge/HikariCP/wiki/FAQ)
