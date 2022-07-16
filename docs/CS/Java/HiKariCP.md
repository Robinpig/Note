## Introduction

[HikariCP](https://github.com/brettwooldridge/HikariCP) contains many micro-optimizations that individually are barely measurable, but together combine as a boost to overall performance.
Some of these optimizations are measured in fractions of a millisecond amortized over millions of invocations.

### ArrayList

One non-trivial (performance-wise) optimization was eliminating the use of an ArrayList<Statement> instance in the ConnectionProxy used to track open Statement instances.
When a Statement is closed, it must be removed from this collection, and when the Connection is closed it must iterate the collection and close any open Statement instances, and finally must clear the collection.
The Java ArrayList, wisely for general purpose use, performs a range check upon every `get(int index)` call.
However, because we can provide guarantees about our ranges, this check is merely overhead.

Additionally, the `remove(Object)` implementation performs a scan from head to tail,
however common patterns in JDBC programming are to close Statements immediately after use, or in reverse order of opening.
For these cases, a scan that starts at the tail will perform better.
Therefore, ArrayList<Statement> was replaced with a custom class FastList which eliminates range checking and performs removal scans **from tail to head**.

Link: [ArrayList - JDK](/docs/CS/Java/JDK/Collection/List.md?id=ArrayList)

### ConcurrentBag

HikariCP contains a custom lock-free collection called a ConcurrentBag.
The idea was borrowed from the C# .NET ConcurrentBag class, but the internal implementation quite different.
The ConcurrentBag provides...

- A lock-free design
- ThreadLocal caching
- Queue-stealing
- Direct hand-off optimizations

...resulting in a high degree of concurrency, extremely low latency, and minimized occurrences of false-sharing.

### Invocation

`invokevirtual` -> `invokestatic`

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

```plantuml
HikariDataSource -> HikariPool: getConnection
HikariPool -> ConcurrentBag: borrow
ConcurrentBag  --> HikariPool: PoolEntry

HikariPool -> ProxyFactory : createProxyConnection
ProxyFactory --> HikariPool: ProxyConnection
HikariPool --> HikariDataSource: Connection”
```


## Links

- [DataSource](/docs/CS/Java/DataSource/DataSource.md)