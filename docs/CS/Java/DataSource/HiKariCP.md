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

Configure your HikariCP idleTimeout and maxLifeTime settings to be one minute less than the wait_timeout of MySQL.

## Links

- [DataSource](/docs/CS/Java/DataSource/DataSource.md)

## References

1. [HikariCP FAQ](https://github.com/brettwooldridge/HikariCP/wiki/FAQ)