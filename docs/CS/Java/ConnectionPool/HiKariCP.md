## Introduction

[HikariCP](https://github.com/brettwooldridge/HikariCP) 包含许多微优化，单独来看几乎不可测量，但组合在一起能够提升整体性能。
其中一些优化以毫秒级的分摊成本衡量，分布在数百万次调用中。

### ArrayList

一个非平凡（性能方面）的优化是消除了 ConnectionProxy 中用于跟踪已打开 Statement 实例的 ArrayList<Statement>。
当 Statement 关闭时，必须将其从该集合中移除；当 Connection 关闭时，必须遍历集合并关闭所有打开的 Statement 实例，最后清空集合。
Java 的 ArrayList，为了通用目的而明智地设计，在每个 `get(int index)` 调用上执行范围检查。
然而，由于我们可以保证范围安全，这种检查仅仅是开销。

此外，`remove(Object)` 实现从头到尾扫描，
但 JDBC 编程中的常见模式是在使用后立即关闭 Statement，或者按打开的逆序关闭。
对于这些情况，从尾部开始扫描的性能更好。
因此，ArrayList<Statement> 被替换为自定义类 FastList，它消除了范围检查并执行**从尾到头**的移除扫描。

Link: [ArrayList - JDK](/docs/CS/Java/JDK/Collection/List.md?id=ArrayList)

### ConcurrentBag

HikariCP 包含一个称为 ConcurrentBag 的自定义无锁集合。
该思路借鉴自 C# .NET 的 ConcurrentBag 类，但内部实现有很大不同。
ConcurrentBag 提供：

- 无锁设计
- ThreadLocal 缓存
- 队列窃取
- 直接交接优化

...从而实现了高度并发、极低延迟，并最大程度减少了伪共享的发生。

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
HikariPool --> HikariDataSource: Connection"
```

```java
public class HikariDataSource extends HikariConfig implements DataSource, Closeable {

    private final AtomicBoolean isShutdown = new AtomicBoolean();

    private final HikariPool fastPathPool;
    private volatile HikariPool pool;

    @Override
    public Connection getConnection() throws SQLException
    {
        if (isClosed()) {
            throw new SQLException("HikariDataSource " + this + " has been closed.");
        }

        if (fastPathPool != null) {
            return fastPathPool.getConnection();
        }

        // See http://en.wikipedia.org/wiki/Double-checked_locking#Usage_in_Java
        HikariPool result = pool;
        if (result == null) {
            synchronized (this) {
                result = pool;
                if (result == null) {
                    validate();
                    try {
                        pool = result = new HikariPool(this);
                        this.seal();
                    }
                    catch (PoolInitializationException pie) {
                        if (pie.getCause() instanceof SQLException) {
                            throw (SQLException) pie.getCause();
                        }
                        else {
                            throw pie;
                        }
                    }
                }
            }
        }

        return result.getConnection();
    }
}
```

## ProxyConnection

Closing statements can cause connection eviction, so this must run before the conditional below

```java
public abstract class ProxyConnection implements Connection {
    @Override
    public final void close() throws SQLException {
        // Closing statements can cause connection eviction, so this must run before the conditional below
        closeStatements();

        if (delegate != ClosedConnection.CLOSED_CONNECTION) {
            leakTask.cancel();

            try {
                if (isCommitStateDirty && !isAutoCommit) {
                    delegate.rollback();
                    lastAccess = currentTime();
                    LOGGER.debug("{} - Executed rollback on connection {} due to dirty commit state on close().", poolEntry.getPoolName(), delegate);
                }

                if (dirtyBits != 0) {
                    poolEntry.resetConnectionState(this, dirtyBits);
                    lastAccess = currentTime();
                }

                delegate.clearWarnings();
            } catch (SQLException e) {
                // when connections are aborted, exceptions are often thrown that should not reach the application
                if (!poolEntry.isMarkedEvicted()) {
                    throw checkException(e);
                }
            } finally {
                delegate = ClosedConnection.CLOSED_CONNECTION;
                poolEntry.recycle(lastAccess);
            }
        }
    }

    private synchronized void closeStatements() {
        final int size = openStatements.size();
        if (size > 0) {
            for (int i = 0; i < size && delegate != ClosedConnection.CLOSED_CONNECTION; i++) {
                try (Statement ignored = openStatements.get(i)) {
                    // automatic resource cleanup
                } catch (SQLException e) {
                    LOGGER.warn("{} - Connection {} marked as broken because of an exception closing open statements during Connection.close()",
                            poolEntry.getPoolName(), delegate);
                    leakTask.cancel();
                    poolEntry.evict("(exception closing Statements during Connection.close())");
                    delegate = ClosedConnection.CLOSED_CONNECTION;
                }
            }

            openStatements.clear();
        }
    }
}
```

## Connection

将 HikariCP 的 idleTimeout 和 maxLifeTime 设置配置为比 MySQL 的 wait_timeout 少一分钟。

## Links

- [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)

## References

1. [HikariCP FAQ](https://github.com/brettwooldridge/HikariCP/wiki/FAQ)
