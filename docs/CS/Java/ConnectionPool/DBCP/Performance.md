## Introduction

DBCP2 的定位是「**无特殊诉求时的稳妥默认**」，而非性能冠军。本文讲清它的取舍边界、常见调优要点，以及与 [HikariCP](/docs/CS/Java/ConnectionPool/HiKariCP/Performance.md) / [Druid](/docs/CS/Java/ConnectionPool/Druid.md) 的选型对照。组件与配置见 [Architecture](/docs/CS/Java/ConnectionPool/DBCP/Architecture.md) / [Configuration](/docs/CS/Java/ConnectionPool/DBCP/Configuration.md)。

## Positioning

- DBCP2 复用 Commons Pool2 的通用对象池，借还走 `borrowObject` / `returnObject`，带锁与对象分配开销，**高并发争用下不如 HikariCP 的 `ConcurrentBag` 无锁路径**。
- 但它接口稳定、文档完备、久经考验，且底层 `GenericObjectPool` 的语义对调试与迁移都更可预测——这正是「稳妥默认」的含义。
- 何时该换 HikariCP：争用（而非配置错误）成为瓶颈——成百上千线程并发借还、且 `MeanBorrowWaitTimeMillis` 高但连接并不短缺。

## Tuning FAQ

- **`maxIdle` 不必低于 `maxTotal`**：当 `maxIdle` 低于 `maxTotal` 时，空闲连接一旦超过 `maxIdle` 会被立即关闭，下一个突发又重建——这种 close-reopen 抖动在 TLS 下尤其昂贵。让 evictor 在静默期自然收缩即可。
- **`testOnBorrow=true` 更安全但更慢**：每次借出多一次到 DB 的往返。只要 evictor 在测空闲连接、且 `maxConnLifetimeMillis` 在退役旧连接，残存风险很小；仅当网络设备在你能承受的扫描间隔内就切断空闲流时才保留。
- **`lifo=true`（默认）**：默认借出最近使用的空闲连接，保持一组「热连接」、其余让 evictor 自然老化；只有需要流量均匀打散（如负载均衡后会话分散）时才切 FIFO。
- **配置后读 JMX 生效值**：DBCP2 会静默忽略未知/遗留属性，配完务必经 `GenericObjectPoolMXBean` 读回 `MaxTotal` 等确认。

## Cross-Pool Comparison

| 设计取舍 | DBCP2 | HikariCP | Druid |
| --- | --- | --- | --- |
| 底层引擎 | Commons Pool2 `GenericObjectPool` | 自研 `ConcurrentBag` 无锁 | 加锁数组 + 双端队列 |
| 代理方式 | 动态代理 / 包装器 | Javassist 字节码生成 | 动态代理 / 包装器 |
| 性能定位 | 稳定通用、非最快 | 极致借还性能 | 中等，偏功能 |
| 监控/管控 | JMX + Micrometer | MXBean + Micrometer | Web 控制台 + 防火墙 |
| 适用 | 无特殊诉求的稳妥默认 | 高并发、追求低延迟 | 要开箱监控面板 + SQL 防火墙 |

选型对照见 [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md) 的 `## Implementations Map`。

## Links

- [DBCP](/docs/CS/Java/ConnectionPool/DBCP.md)
- [Configuration](/docs/CS/Java/ConnectionPool/DBCP/Configuration.md)
- [HiKariCP](/docs/CS/Java/ConnectionPool/HiKariCP.md)
- [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)

## References

1. [Tuning Apache Commons DBCP2 for Production](https://www.database-connection-pooling.com/pool-architecture-algorithm-fundamentals/hikaricp-vs-c3p0-vs-dbcp2-benchmark/tuning-apache-commons-dbcp2-for-production)
2. [Apache Commons DBCP Configuration](https://commons.apache.org/proper/commons-dbcp/configuration.html)
