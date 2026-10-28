## Introduction

Apache Commons DBCP 是历史最悠久的 JDBC 连接池之一，底层依赖 **Apache Commons Pool2**（`org.apache.commons.pool2`）做对象池化。

Version baseline: 最新稳定版 **2.14.0**（2025-12-11），要求 **Java 8+**。注意 **DBCP 1.x 与 2.x 不二进制兼容**：2.x 包名从 `org.apache.commons.dbcp` 改为 `org.apache.commons.dbcp2`，Maven 坐标也从 `commons-dbcp:commons-dbcp` 改为 `org.apache.commons:commons-dbcp2`，迁移需改 import 后重新编译。Java 6 / 7 用户只能用 1.3.x / 1.4.x，新项目一律用 2.x。

DBCP2 是「无特殊诉求时的稳妥默认」：接口稳定、文档完备、经 JMX 暴露监控，底层对象池（`GenericObjectPool`）久经考验。若追求极致性能选 [HikariCP](/docs/CS/Java/ConnectionPool/HiKariCP.md)，若要强监控/防注入选 [Druid](/docs/CS/Java/ConnectionPool/Druid.md)，总览见 [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)。

## Map of This Section

DBCP2 的本质是「在成熟的 Commons Pool2 对象池之上，套一层 JDBC 适配」。本节四篇分册从不同角度把它讲透：

- [Architecture](/docs/CS/Java/ConnectionPool/DBCP/Architecture.md) 是骨架：先讲清底层引擎 `GenericObjectPool`（Commons Pool2）与 DBCP2 适配层 `BasicDataSource` / `PoolingDataSource` 的关系，再给借还时序；并附 DBCP 1.x 与 2.x 的包名/坐标差异，避免迁移踩坑。
- [Configuration](/docs/CS/Java/ConnectionPool/DBCP/Configuration.md) 是把参数拧进生产：完整参数表（规模/校验驱逐/生命周期/泄漏）、DBCP 1.x→2.x 的参数改名映射、Spring Boot `spring.datasource.dbcp2.*` 装配、以及 `maxConnLifetimeMillis` 必须短于 DB `wait_timeout` 的铁律。
- [Monitoring](/docs/CS/Java/ConnectionPool/DBCP/Monitoring.md) 讲如何观测：经 `GenericObjectPoolMXBean` / `setJmxEnabled` 暴露的 JMX 指标、Micrometer 的 `jdbc.connections.*`、以及 Abandoned 泄漏检测（`logAbandoned` 打印堆栈），并对比 Druid / HikariCP 的监控路径。
- [Performance](/docs/CS/Java/ConnectionPool/DBCP/Performance.md) 讲定位与调优：DBCP2 为什么是「稳妥默认而非最快」，常见调优取舍（maxIdle 不必低于 maxTotal、testOnBorrow 的代价、lifo 默认），以及与 HikariCP / Druid 的选型对照。

## Links

- [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)
- [HiKariCP](/docs/CS/Java/ConnectionPool/HiKariCP.md)
- [Druid](/docs/CS/Java/ConnectionPool/Druid.md)

## References

1. [Apache Commons DBCP 2.x Changes](https://commons.apache.org/proper/commons-dbcp/changes.html)
2. [Apache Commons DBCP Configuration](https://commons.apache.org/proper/commons-dbcp/configuration.html)
3. [Apache Commons Pool2](https://commons.apache.org/proper/commons-pool/)
