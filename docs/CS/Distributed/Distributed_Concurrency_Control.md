# Distributed Concurrency Control

分布式并发控制研究"多个节点上的并发事务如何保证隔离性与一致性"（ACID 的 I），是原子提交协议（见 [Consensus](/docs/CS/Distributed/Consensus/Consensus.md) 的 2PC / 3PC）之上的**隔离实现层**。经典综述来自 Bernstein、Hadzilacos、Goodman 的《Concurrency Control and Recovery in Database Systems》，以及 Brewers 的 cs262 课程笔记；本库刚写的 [Distributed Transaction Patterns](/docs/CS/Distributed/Distributed_Transaction_Patterns.md) 覆盖应用层 Saga / TCC，本篇覆盖"单节点 / 分布式隔离的算法谱系"，三者构成"提交协议 → 事务模式 → 隔离算法"的完整链条。

## Major Methods

- **两段锁 2PL（Two-Phase Locking）**：事务分"加锁（增长）阶段"与"释放（收缩）阶段"，两阶段不重叠；保证 conflict serializable。代价是易死锁，需死锁检测 / 超时回滚，且锁持有到事务结束（长事务锁竞争重）。
- **时间戳排序 TO（Timestamp Ordering）**：给每个事务授予全局时间戳，所有操作按时间戳顺序执行以保持串行等价。变种有 Basic TO、Conservative TO、Multiversion TO（MVTO）。时间戳的"全局有序"直接依赖 [Time](/docs/CS/Distributed/Time.md) 笔记里的逻辑时钟 / 向量时钟 / TrueTime——没有可靠的事件定序，TO 无从谈起。
- **乐观并发控制 OCC（Optimistic CC）**：读阶段不加锁、只记录读集；验证阶段检查与并发事务是否冲突；通过才写阶段提交。适合低冲突场景，冲突高时大量回滚；HBase / Cassandra 类系统常采用。
- **多版本并发控制 MVCC（Multiversion CC）**：为每个数据维护多个版本，读不阻塞写、写不阻塞读；PostgreSQL、MySQL InnoDB、[TiDB](/docs/CS/DB/TiDB/TiDB.md)、[CockroachDB](/docs/CS/Distributed/CockroachDB.md) 都用。与快照隔离（Snapshot Isolation, SI）紧密相关。

## Isolation Levels and Anomalies

- ANSI 隔离级别：Read Uncommitted / Read Committed / Repeatable Read / Serializable。
- **Snapshot Isolation 的陷阱**：SI 能挡脏读、不可重复读、幻读，但**不保证 serializable**——存在 write skew（写偏斜）等异常，需要额外机制（如显式谓词锁、Serializable Snapshot Isolation）才能升级到真正串行化。这是 MVCC 系统在"性能 vs 严格一致"上的典型取舍。

## Relationship to Other Notes

- 与 [Consensus](/docs/CS/Distributed/Consensus/Consensus.md)：2PC / 3PC 解决"是否一起提交"，本篇解决"并发提交时如何互不干扰"。
- 与 [Distributed Transaction Patterns](/docs/CS/Distributed/Distributed_Transaction_Patterns.md)：Saga / TCC 在应用层绕过数据库隔离，用补偿 / 预留达成最终一致；本篇是它们之下、存储引擎内部的隔离实现。
- 与数据库专页：[TiDB](/docs/CS/DB/TiDB/TiDB.md)（Percolator MVCC + 2PC）、[CockroachDB](/docs/CS/Distributed/CockroachDB.md)（HLC + MVCC）、[PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)（MVCC + SI）都可在本篇找到理论锚点。

## Links

- [Consensus](/docs/CS/Distributed/Consensus/Consensus.md)
- [Distributed Transaction Patterns](/docs/CS/Distributed/Distributed_Transaction_Patterns.md)
- [TiDB](/docs/CS/DB/TiDB/TiDB.md)
- [CockroachDB](/docs/CS/Distributed/CockroachDB.md)

## References

- Concurrency Control in Distributed Database Systems (Bernstein, Hadzilacos, Goodman; cs262 notes by Brew)
- Notes: https://people.eecs.berkeley.edu/~brewer/cs262/concurrency-distributed-databases.pdf
