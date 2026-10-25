# Hive ACID and Transactions

## Introduction

Hive 3.0 对事务做了重写（ACID 2.0），4.x 延续并改进。它让 ORC 表支持 full ACID（INSERT / UPDATE / DELETE / MERGE）而无需锁全表，但代价是 delta 文件的结构性膨胀——必须靠 compaction 收敛。理解 ACID 先看「范围与表属性」，再看「机制」，最后看「compaction 这道运维命门」。

## Scope and Table Properties

- **ORC 表支持 full ACID**（`transactional=true`），其它格式仅 `insert-only` 事务（`insert_only=true`）；ACID 在 Hive 4 的 managed 表上默认开启。
- 表属性决定 ACID 类型：同时含 `transactional=true` 不含 `insert_only` 为 full ACID，含 `insert_only=true` 为 insert-only。详见 [Data Model](/docs/CS/DB/Hive/Data_Model.md)。

## Mechanism

- **DbTxnManager** 管理事务、**LockManager** 管理锁；读走 **MVCC**（多版本并发控制），写产生 **delta 文件**（写时复制 COW 模式），读不阻塞写。
- **事务元数据**落在 HMS 后端的关系表里：`txns`（开启的事务）、`txn_components`（事务涉及的表/分区）、`completed_txn_components`（已完成事务，供读判断可见性）。
- **零等待读（zero-wait readers）**：4.x 读事务不再必须等锁获取，只读已提交快照；只读查询跳过事务开销。

## Compaction

delta 文件不断堆积，必须靠 compaction 收敛，否则读放大失控。

- **minor compaction**：合并一组 delta 文件。
- **major compaction**：合并 base + 所有 delta 并清除墓碑（tombstone），是真正「收口」的动作。
- **query-based vs MapReduce-based**：4.x 主推 query-based compaction（用 HiveQL/Tez 执行），MR-based 已随 MR 引擎弃用；部分新特性（如 rebalance）只以 query-based 跑。
- **rebalance compaction**（HIVE-26674，随 4.0 引入）：解决隐式分桶 full-acid ORC 表因写入量不均导致的桶文件倾斜——`ALTER TABLE ... COMPACT 'REBALANCE' [CLUSTERED INTO N BUCKETS] [ORDER BY col]`。**限制**：只在分区内、只支持隐式分桶的 full-acid 表（显式 clustered 表与 insert-only 表不支持）、只走 query-based、运行期对表加独占写锁，**永不自动触发**，须排维护窗口手动执行。
- **compaction pooling**：通过 `hive.compactor.worker.pool` 把库/表/分区分到命名池，`hive.compactor.worker.{poolname}.threads` 给池分配专属 worker 线程，手动 `ALTER TABLE ... COMPACT ... POOL 'name'` 可覆盖；`hive.compactor.worker.pool.timeout`（0 禁用）控制超时回退 default 池。集群级 default 池至少要有 1 个 worker 线程，否则未标注请求永不处理。
- **服务模型**：compaction 由 HMS 内的 **Initiator**（按阈值发起请求）与 **Worker**（执行 compaction）构成，通过 Thrift 调度，不是独立外部进程。

## Isolation

4.x 提供两种并发控制模式，常见隔离级为 snapshot isolation / read committed（读已提交快照）。MVCC + 事务元数据使读不阻塞写、写不阻塞读，但长事务会拖累 compaction 的墓碑清理（未提交/长事务引用的 delta 不能合并）。

## Cost and Pitfalls

- 小文件（delta）膨胀是结构性问题：compaction 不及时会显著拖慢读。
- 语义混淆：ACID 表与非 ACID 表、managed 与 external 的语义差异要在建表时想清楚；混用会出现「删了数据还看得到」这类由未 compaction 的 tombstone 导致的困惑。
- compaction 本身消耗资源：池化与 rebalance 的独占锁要与 ETL 错峰。

## Links

- [Hive](/docs/CS/DB/Hive.md)
- [Storage Formats](/docs/CS/DB/Hive/Storage_Formats.md)
- [Data Model](/docs/CS/DB/Hive/Data_Model.md)
- [Iceberg Integration](/docs/CS/DB/Hive/Iceberg_Integration.md)
- [Operations](/docs/CS/DB/Hive/Operations.md)

## References

1. [Hive Documentation](https://hive.apache.org/docs/latest/)
2. [Hive Compaction Pooling](https://hive.apache.org/docs/latest/language/compaction-pooling/)
3. [[HIVE-26674] REBALANCE type compaction](https://issues.apache.org/jira/browse/HIVE-26674)
4. [Hive 4 Key Features, in depth](https://www.aicassindra.com/blogs/hive_impala/hive_4_features.html)
