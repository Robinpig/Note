## Introduction

HikariCP 的组件极少且职责单一，理解它只需抓住一条主链路与几个关键类。本文给出组件地图、借还时序，以及连接生命周期的后台维护线程 `HouseKeeper`；代理类为何用字节码生成，见 [Performance](/docs/CS/Java/ConnectionPool/HiKariCP/Performance.md)。

## Core Classes

| 类 | 职责 |
| --- | --- |
| `HikariDataSource` | 实现 `DataSource` / `Closeable`，持有 `HikariConfig` 与 `HikariPool`；`getConnection()` 入口，首次调用时 `double-checked locking` 惰性建池 |
| `HikariPool` | 池的真正实现：借还、`ConcurrentBag` 调度、`HouseKeeper` 后台维护、`ProxyConnection` 创建 |
| `ConcurrentBag<T>` | 无锁连接容器，`T=PoolEntry`；借出/归还走 ThreadLocal + 共享队列 + 队列窃取 |
| `PoolEntry` | 包装一条物理连接与其状态（最后访问、是否被标记驱逐）、`ConnectionState` 脏位 |
| `ProxyConnection` | 物理连接的代理，拦截 `close()` 改为归还、记录打开的 `Statement`、提交脏状态回滚 |
| `ProxyFactory` | 构建期由 Javassist 注入 `getProxyConnection(...)` 生成代理（见 Performance 的字节码优化） |
| `HikariPoolMXBean` | 运行时监控接口，经 `HikariDataSource.getHikariPoolMXBean()` 暴露（见 [Monitoring](/docs/CS/Java/ConnectionPool/HiKariCP/Monitoring.md)） |

## Borrow and Return Flow

```plantuml
HikariDataSource -> HikariPool: getConnection
HikariPool -> ConcurrentBag: borrow
ConcurrentBag  --> HikariPool: PoolEntry

HikariPool -> ProxyFactory : createProxyConnection
ProxyFactory --> HikariPool: ProxyConnection
HikariPool --> HikariDataSource: Connection
```

借出（`getConnection()`）在 `HikariDataSource` 里做惰性建池（`fastPathPool` 直接路径 + `pool` 的 `double-checked locking`），建池时调用 `validate()` 校验配置，失败抛 `PoolInitializationException`：

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

归还发生在 `ProxyConnection.close()`：它**不是真的关闭物理连接**，而是先关掉打开的 `Statement`、取消泄漏检测任务、在必要时回滚脏提交状态、重置连接状态，最后把 `delegate` 置为 `CLOSED_CONNECTION` 并 `poolEntry.recycle()` 归还给 `ConcurrentBag`：

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
}
```

## HouseKeeper

`HikariPool` 在构造时启动一个单线程调度器 `HouseKeeper`，周期性（默认每 30s，`housekeepingPeriodMs`）执行维护：

- **补充 `minIdle`**：空闲连接低于 `minimumIdle` 时异步创建补足。
- **回收 `idleTimeout`**：超过 `idleTimeout` 的空闲连接被退休（仅当 `minimumIdle < maximumPoolSize` 时才有意义）。
- **强制 `maxLifetime`**：超过 `maxLifetime` 的连接被异步替换（先建新、再关旧），避免命中 DB 端 `wait_timeout` 拿到死连接。
- **软驱逐（soft-evict）**：当检测到**时钟回拨**时，`HouseKeeper` 会对现有连接做 soft-evict，使其在下一次借出时被替换——这是 HikariCP 对 NTP/虚拟机时钟不同步的自我保护（见 [Configuration](/docs/CS/Java/ConnectionPool/HiKariCP/Configuration.md) 的时钟陷阱）。

## Links

- [HiKariCP](/docs/CS/Java/ConnectionPool/HiKariCP.md)
- [Performance](/docs/CS/Java/ConnectionPool/HiKariCP/Performance.md)
- [Configuration](/docs/CS/Java/ConnectionPool/HiKariCP/Configuration.md)
- [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)

## References

1. [HikariCP FAQ](https://github.com/brettwooldridge/HikariCP/wiki/FAQ)
