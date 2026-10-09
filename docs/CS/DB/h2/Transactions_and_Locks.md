## Introduction

H2 2.x 的事务与并发是**围绕 MVStore 的多版本能力搭起来的一层**：MVCC 读、键级写锁、真实的死锁检测、内存 undo 日志，再加上一个决定空间回收节奏的 `retentionTime`。这一页把它们的真实行为与默认值写清楚——顺带纠正若干广泛流传、但实际上属于 1.x 或属于文档滞后措辞的说法。锚定 2.5.252。

## Isolation Levels

`org/h2/engine/IsolationLevel.java` 里是**五档**：`READ_UNCOMMITTED`、`READ_COMMITTED`、`REPEATABLE_READ`、**`SNAPSHOT`**、`SERIALIZABLE`，默认 **READ_COMMITTED**（`SessionLocal.java:229`；对应 `Constants.java:194` 的 `DEFAULT_LOCK_MODE = LOCK_MODE_READ_COMMITTED = 3`）。

三个细节：

- `commands.html` 里 `SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL ...` 的语法表**漏列了 SNAPSHOT**，但 `command/dml/Parser.java:7714` 实际接受——以源码为准。
- `SET TRANSACTION ISOLATION LEVEL ...` 与 session 版本走同一个 `parseSetTransactionMode()`，**改的是会话级隔离**；源码里还留着注释 `TODO should affect only the current transaction`（`Parser.java:7633`）。也就是说「只影响当前事务」这件事并未实现。
- 文档警告「表多时 REPEATABLE READ / SNAPSHOT / SERIALIZABLE 极昂贵」，原因在 `SessionLocal.startStatementWithinTransaction`（`:1664`）：对不允许不可重复读的会话，**事务内第一条语句会把所有 schema 下的全部 MVTable 注册成依赖**。要的是快照隔离，就优先用 `SNAPSHOT` 而不是把语句写成 `SERIALIZABLE`。

## Locking and Write Conflicts

> [!WARNING]
> **「insert/update 只加表级共享锁」是文档措辞，不是实现——而且文档自己就不自洽**：`features.html` 的 Feature List 写的是 "Multiple connections, **row-level locking**"，而 `advanced.html` 的 MVCC 一节写的是 "Insert and update operations only issue a **shared lock on the table**"。两句都不能直接当事实用：2.x 的写冲突控制实际发生在 MVStore 的**条目（键）级**（`TransactionMap.lock()`，`tx/TransactionMap.java:312`），配合下面的阻塞与死锁判定。而 `SET LOCK_MODE` 虽然没被标 DEPRECATED，实际已被阉割：`Database.setLockMode()`（`:1956`）把 1 与 2 一律归一为 3，只有 0（完全不加锁）是另一个行为。按「1=表锁、2=读已提交表锁」去理解就错了。

行为上：

- 写-写冲突**不是立即报错**，而是 `Transaction.waitFor()`（`tx/Transaction.java:669`）阻塞等对方提交或回滚，超时抛 `LOCK_TIMEOUT`；同一主键的冲突映射为 **`CONCURRENT_UPDATE_1`（90131）**（`api/ErrorCode.java:1998`、`MVTable.java:702`）。`org.h2.api.ConcurrentUpdateInDatabaseException` **不存在**，别照旧文引用。
- 锁超时的默认值两处冲突：文档（`SET LOCK_TIMEOUT` / `SET DEFAULT_LOCK_TIMEOUT`）写 **1000 ms**，源码回退常量 `Constants.java:245` 的 `INITIAL_LOCK_TIMEOUT` 是 **2000 ms**。以源码为准，或显式设置。
- `SELECT ... FOR UPDATE` 支持完整变体：`FOR UPDATE [NOWAIT | WAIT n | SKIP LOCKED]`（commands.html 的 SELECT 语法；实现 `MVTable.lockRow():557` → `MVPrimaryIndex.lockRow():214`，其中 `timeoutMillis = -2` 表示 SKIP LOCKED）。
- 观测入口是 `INFORMATION_SCHEMA.LOCKS(TABLE_SCHEMA, TABLE_NAME, SESSION_ID, LOCK_TYPE)`，另有 `SESSIONS` / `SESSION_STATE` 定位是谁持锁。

## Deadlock Detection

死锁检测**存在**，做法是沿 `blockingTransaction` 链走一圈找环（`Transaction.isDeadlocked()`，`tx/Transaction.java:683`），并选 **sequenceNum 最大的「最年轻」事务当 victim** 回滚。MVStore 内部错误码 `ERROR_TRANSACTIONS_DEADLOCK = 105`（`util/DataUtils.java:109`）在 JDBC 层映射为 `ErrorCode.DEADLOCK_1`。在 REPEATABLE_READ 下用 `FOR UPDATE` 锁行时，若发现该行自快照之后被改过，也走同一条死锁路径（`mvstore/tx/TxDecisionMaker.java:366-385`）。

## Snapshots and MVCC Semantics

快照时间点由隔离级别决定：READ_COMMITTED 不记快照、按语句读最新已提交版本；其余档位由 `SessionLocal.endTransaction()`（`:800-801`）记下 `snapshotDataModificationId`，形成**事务级快照**。JDBC 侧 `Connection.setTransactionIsolation()` 与 `SET SESSION CHARACTERISTICS` 等价（都是会话级）。

大多数 DDL（如 `CREATE TABLE`）会提交当前事务；`GRANT`/`REVOKE` 与 `SET DB_CLOSE_DELAY` 一类也会——放在事务中间会悄悄改变回滚边界。

## Savepoints and Two-Phase Commit

保存点三件套都实现了：`SAVEPOINT name`、`ROLLBACK [WORK] TO SAVEPOINT name`、**`RELEASE SAVEPOINT name`**（`Parser.java:721/847/894`），操作不存在的保存点报 `SAVEPOINT_IS_INVALID_1`。

两阶段提交：`PREPARE COMMIT <name>` 把事务置为 prepared，之后用 `COMMIT TRANSACTION <name>` / `ROLLBACK TRANSACTION <name>` 处置（**需要 admin**）。悬而未决的 in-doubt 事务可以从 **`INFORMATION_SCHEMA.IN_DOUBT(TRANSACTION_NAME, TRANSACTION_STATE)`** 查（`InformationSchemaTable.java:740`；恢复实现 `mvstore/db/MVInDoubtTransaction.java`）。

## Long Transactions Are Expensive Here

这条链条解释了「为什么一个没结束的事务会让库变大」：

1. undo 日志是**内存里的 radix-tree map**（`TransactionStore.undoLogs:77`、`Transaction.undoLogRootReferences:166`），只在提交时才随之落盘——长事务意味着这块内存一直占着。
2. MVStore 的 `retentionTime` 默认 **45000 ms**（`FileStore.java:1368`），chunk 只有在「时间 + retentionTime 已过」**且**不被 `oldestVersionToKeep` 引用时才能被覆写（`FileStore.java:729`、`MVStore.java:213/1342`）。打开中的事务会压低 `oldestVersionToKeep`。
3. 于是长事务直接钉住空间回收；再加上 `AUTO_COMPACT_FILL_RATE` 默认 90，缩写得等自动 compact 判据满足。机制细节见 [MVStore: Space Reclamation](/docs/CS/DB/h2/MVStore.md)。
4. 并发打开的事务数默认是 **255**（`h2.maxOpenTransactions`，`TransactionStore.java:129`，且是 **JVM 全局静态量**，按库设置无效），而文档 `Limits and Limitations` 仍写 65535。

## Optimizer and Statistics

Feature List 里那句「cost-based optimizer，复杂查询用遗传算法」**在源码里确有其事**：`command/query/Optimizer.java:153 calculateGenetic()`，`MAX_GENETIC = 500`，做法是随机全排列 + 两两交换爬山；表数低于阈值时用暴力枚举，另有贪心路径，代价估算在 `TableFilter`。

统计信息的真实形态比想象中小：

- `ANALYZE` / `ANALYZE TABLE` 计算的是**列选择度**（min-count 草图，`command/ddl/Analyze.java`），结果存进 `Column.selectivity`（默认值来自 `SELECTIVITY_DEFAULT`）。可以手工指定：`ALTER TABLE t ALTER COLUMN c SELECTIVITY n`。
- 2.x 相关的 `INFORMATION_SCHEMA` 视图**只有 `QUERY_STATISTICS`**（配合 `SET QUERY_STATISTICS_MAX_ROWS`）以及 `SESSIONS` / `SESSION_STATE` / `LOCKS` / `SETTINGS`。1.x 时代的 `TABLE_STATISTICS`、`INDEX_SCAN`、`ROWCOUNT`、`SELECT_SELECTIVITY` **都已不存在**。
- **没有 `/*+ */` 提示、没有 `STRAIGHT_JOIN`**。能控制连接顺序的手段只有三种：把 `JOIN` 按期望顺序书写、给列设 SELECTIVITY、以及 `SET OPTIMIZE_REUSE_RESULTS`。
- 无 `WHERE` 的 `COUNT(*)` 走 `isQuickAggregateQuery`（`command/query/Select.java:1604`），行数取自 `MVPrimaryIndex.getRowCount() = map.sizeAsLong()`，是 **O(1)**（`:404`）；只要近似值可用 `getRowCountMax()`。

## Knobs That Actually Exist

| 开关 | 事实 |
| :--- | :--- |
| `SET CACHE_SIZE` | 单位 KB，默认按内存自动取 64 MB / 每 GB RAM 并向上取 2 的幂，持久化；透传到 `MVStore.Builder.cacheSize`（单位 MB） |
| `SET MAX_MEMORY_ROWS` | 默认 40 000 / 每 GB RAM（自动按内存缩放） |
| `SET RETENTION_TIME` | 对应 MVStore 的 retentionTime，默认 45 s |
| `nioMapped:` 前缀 | 唯一真实的 mmap 通道（`store/fs/niomapped/FilePathNioMapped.java`） |
| `SET QUERY_STATISTICS` | 打开查询耗时统计 |
| `WRITE_DELAY` | 映射到 `setAutoCommitDelay`，默认 500 ms |

**不存在的开关**（常被引用）：`CACHE_ROWS`、`MULTI_THREADED`（2.x 已移除）、`WRITE_BUFFER`、`FILE_STORE_MMAP`、`h2.mmapUse`、`h2.aoQueueIfFull`、`MULTI_LOGICAL_LOG_RECOVERY`、`SCROLLABLE_RESULTSET`。两个**语法保留但没有消费方的死参数**：`SET MAX_MEMORY_UNDO`、`CACHE_TYPE`（文档还在介绍 `TQ`/`SOFT_LRU`，实际永远走 `CacheLongKeyLIRS`）。

## Clustering

所谓高可用是：两台机器各存一份同一份库，正常时双写，一侧故障后另一侧继续跑；**只能用在 server 模式**，集群可用 `CreateCluster` 工具在不中断存活端的情况下重建。**没有仲裁**——网络分区时两侧都可能继续写，修复要靠外部判断，把它当复制方案是误用。

## Pitfalls

1. 别说 H2 没有 SNAPSHOT 档，也别找不到 `SNAPSHOT` 的语法文档就以为不支持。
2. 别引用 `ConcurrentUpdateInDatabaseException`（不存在）；冲突看错误码 90131 与 `DEADLOCK`。
3. `LOCK_MODE=1/2` 早已归一为 3，「表锁模式」在 2.x 不成立。
4. 1.x 的统计视图名全部失效，只剩 `QUERY_STATISTICS`。
5. 事务类实名以 `mvstore/tx/` 为准：`Transaction`、`TransactionStore`（`MVStoreTransaction`、`MVSessions`、`MVTempStore` 都不存在）。
6. 想要「只影响当前事务」的隔离级别，H2 做不到——它是会话级，用完记得改回来。

## Links

- [H2](/docs/CS/DB/h2/H2.md)
- [MVStore](/docs/CS/DB/h2/MVStore.md)
- [Connection and Servers](/docs/CS/DB/h2/Connection_and_Servers.md)
- [SQL Language](/docs/CS/DB/h2/SQL_Language.md)
- [WAL](/docs/CS/DB/WAL.md)
- [RocksDB Compaction](/docs/CS/DB/RocksDB/Compaction.md)

## References

1. [H2 Database Engine - Advanced Features](https://h2database.com/html/advanced.html)
2. [H2 Database Engine - Commands](https://h2database.com/html/commands.html)
3. [H2 Database Engine - System Tables](https://h2database.com/html/systemtables.html)
4. [H2 source at tag 2.5.252: org/h2/mvstore/tx/Transaction.java](https://github.com/h2database/h2/blob/2.5.252/src/main/h2/org/h2/mvstore/tx/Transaction.java)
