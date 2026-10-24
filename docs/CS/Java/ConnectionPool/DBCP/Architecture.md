## Introduction

DBCP2 自身不实现对象池算法，而是复用 **Apache Commons Pool2** 的 `GenericObjectPool` 作为底层引擎，在其上提供 JDBC 适配。理解 DBCP2 只需抓住「Pool2 引擎 + JDBC 适配层」两层。

## Commons Pool2 Engine

| 类 | 职责 |
| --- | --- |
| `GenericObjectPool<T>` | 通用对象池实现，borrow / return / evict 的核心算法都在这里；实现 `GenericObjectPoolMXBean`（见 [Monitoring](/docs/CS/Java/ConnectionPool/DBCP/Monitoring.md)） |
| `PoolableConnectionFactory` | 连接工厂：创建物理连接、校验、重置状态、销毁 |
| `GenericObjectPoolConfig` | 池规模与行为配置（`maxTotal` / `maxIdle` / `minIdle` / `lifo` / evictor ...） |
| `DefaultPooledObject` | 包装被池化的对象，跟踪状态与最后使用时间（Abandoned 检测依赖 `TrackedUse`） |

## DBCP2 Adapter Layer

| 类 | 职责 |
| --- | --- |
| `BasicDataSource` | 最常用的 `DataSource` 实现，内部持有 `GenericObjectPool<PoolableConnection>` + `PoolableConnectionFactory`，`getConnection()` 直接委托池 |
| `PoolingDataSource` | 更通用的包装：持有一个外部 `ObjectPool<PooledConnection>`，与具体池实现解耦 |
| `PoolableConnection` | 物理连接的代理，`Connection.close()` 被改为 `returnObject`（归还），而非真正关闭 |
| `PoolingConnection` | 在池化连接之上再池化 `PreparedStatement`（`poolPreparedStatements`） |

## Borrow and Return Flow

借出：`BasicDataSource.getConnection()` → `GenericObjectPool.borrowObject()` →（无空闲时）`PoolableConnectionFactory.makeObject()` 创建物理连接 → 返回 `PoolableConnection`。

归还：应用调用 `Connection.close()` → `PoolableConnection` 拦截 → `GenericObjectPool.returnObject()` → 连接回到空闲队列（并视 `testOnReturn` 做校验）。

> 与 [HikariCP](/docs/CS/Java/ConnectionPool/HiKariCP/Architecture.md) 不同，DBCP2 的借还走 Commons Pool2 的通用 `borrowObject` / `returnObject`，而非自研的 `ConcurrentBag`；代价是更高的锁争用与对象分配，但换来与任意对象池化场景一致的稳定语义。

## DBCP 1.x vs 2.x

DBCP 2.0（2014-03）起不再是 1.x 的二进制兼容升级，而是包名与坐标都改了：

| 维度 | DBCP 1.x | DBCP 2.x |
| --- | --- | --- |
| 包名 | `org.apache.commons.dbcp` | `org.apache.commons.dbcp2` |
| Maven 坐标 | `commons-dbcp:commons-dbcp` | `org.apache.commons:commons-dbcp2` |
| JDBC 版本 | 1.x 支持到 JDBC 4（Java 6） | 2.x 支持 JDBC 4.2（Java 8）；2.4.0 仍覆盖 Java 7 |
| 参数名 | `maxActive` / `maxWait` / `removeAbandoned` | `maxTotal` / `maxWaitMillis` / `removeAbandonedOnBorrow` 等（见 [Configuration](/docs/CS/Java/ConnectionPool/DBCP/Configuration.md)） |

迁移只需改 import 包名与依赖坐标后重新编译；**但 1.x 的配置属性名在 2.x 已失效**，沿用旧属性名会被静默忽略（见 Configuration 的参数改名表）。

## Links

- [DBCP](/docs/CS/Java/ConnectionPool/DBCP.md)
- [Configuration](/docs/CS/Java/ConnectionPool/DBCP/Configuration.md)
- [Monitoring](/docs/CS/Java/ConnectionPool/DBCP/Monitoring.md)
- [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)

## References

1. [Apache Commons Pool2](https://commons.apache.org/proper/commons-pool/)
2. [Apache Commons DBCP Configuration](https://commons.apache.org/proper/commons-dbcp/configuration.html)
