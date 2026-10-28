## Introduction

TiDB Server 是集群的 SQL 层，也是唯一直接对应用暴露的组件。它做四件事：用 MySQL 协议跟客户端通信、把 SQL 编译成分布式执行计划、把能下推的计算发给存储节点、把结果组装成 MySQL 结果集。它不存数据，因此可以水平扩缩；但也正因无状态，跨节点的会话状态（临时表、会话变量）不能随连接迁移——这也是 TiProxy 连接迁移存在一系列限制的根源。

本页按「进来一条 SQL 之后发生什么」的顺序展开：协议接入 → KV 映射 → 优化 → 执行与下推 → DDL → 统计信息。存储层如何承接这些请求见 [TiKV](/docs/CS/DB/TiDB/TiKV.md)。

## Row to Key-Value Mapping

关系模型到 KV 的映射是整个 SQL 层的地基。每张表分配一个集群内唯一的 TableID；每行分配表内唯一的 RowID（整数主键则直接用主键值）。编码规则：

- 行数据：`Key: t{TableID}_r{RowID}`，`Value: [col1, col2, ...]`
- 主键/唯一索引：`Key: t{TableID}_i{IndexID}_{索引列值}`，`Value: RowID`
- 普通二级索引：`Key: t{TableID}_i{IndexID}_{索引列值}_{RowID}`，`Value: null`

前缀常量 `tablePrefix='t'`、`recordPrefixSep='r'`、`indexPrefixSep='i'`；元信息（Database/Table 定义）以 `m_` 前缀同样存进 TiKV。这个设计带来两个直接后果：**所有索引查询最终都是 KV 范围扫描**，以及**行内列的顺序即编码顺序**——把高频过滤列放前面，范围扫描能少读数据。

## SQL Compilation Pipeline

TiDB Server 收到 MySQL Protocol Packet 后：

1. **解析与校验**：parser 生成 AST，做合法性检查；
2. **逻辑优化**：做等价变换（谓词下推、常量折叠、列裁剪等），得到与原始查询等价的逻辑计划；
3. **物理优化**：基于统计信息和数据分布，估算每个物理算子的执行开销，选择总成本最低的物理计划，包括索引选择、join 顺序、join 算法；
4. **计划缓存**：`PREPARE` 场景下可开启执行计划缓存，省掉重复的计划生成开销。

执行计划按 task 分四类：`root task`（在 TiDB Server 执行）、`cop task`（下推到 TiKV 或 TiFlash 并行执行）、`batchCop task`（TiFlash 批量）、`MPP task`（TiFlash 跨节点 shuffle）。EXPLAIN 输出里出现 `ExchangeSender`/`ExchangeReceiver` 即表示 MPP 生效。

## Coprocessor

为什么要下推：以 `select count(*) from user where name = "TiDB"` 为例，朴素做法是从 TiKV 逐行读取，每行至少一次 RPC，且不满足条件的行也被网络传输，聚合只能在 SQL 层做。TiDB 的解法是谓词与聚合都下推到存储节点：每个节点只返回本地 `Count(*)`，SQL 层累加。

Coprocessor 的计算单元以 Region 为单位——一个 cop 请求不会跨 Region。这意味着下推能省网络，但单 Region 的并行度受 Region 大小限制（默认 256 MiB）；大表调小 Region 能提高扫描并行度，代价是调度元信息变多。

## DDL Execution

TiDB 用**在线异步变更**执行 DDL：DDL 不阻塞并发 DML，且不支持离线 DDL。机制：

- 每个 TiDB 节点都可能通过 etcd 竞选成为 **DDL Owner**（全集群同时只有一个，有任期并主动续约；`run-ddl` 配置可让节点放弃竞选），`ADMIN SHOW DDL` 可查看；
- DDL 请求被封装成 Job，按类型进入 KV 层的 Job 队列，Owner 串行或按相关性并行处理，完成后移入 history 队列；
- 从 v6.2.0 起 Owner 做相关性判断：同表 DDL 互相阻塞、`DROP DATABASE` 与库内对象 DDL 互相阻塞，不同表的加索引/列类型变更可并发；v8.2.0 起不同表的逻辑 DDL 也可并行；
- `ADD INDEX` 经历 `absent → delete only → write only → write reorg → public` 五个状态，public 前索引对用户不可用；这是典型的 F1 在线 schema 变更算法（官方源码阅读文章点名，v8.5 计算页只写「Online Schema 变更算法」，未点名 F1）；
- 物理 DDL 只有 `ADD INDEX` 与有损列类型变更（如 INT→CHAR）两种，耗时长且消耗 TiKV CPU/IO；ADD INDEX 从 v8.5.0 起支持 Fast Online DDL 加速，并有 `tidb_ddl_reorg_max_write_speed` 等调速变量。

## Statistics

统计信息是优化器的输入，三类构成：**等深直方图**（估算范围谓词，`NUM BUCKETS` 控制桶数）、**Count-Min Sketch**（等值/IN 谓词估算，Version 2 起改用直方图以避免哈希冲突）、**Top-N**（频率统计，默认 20、最大 1024）。

自动维护链路：DML 自动更新行数与修改行数，TiDB 按 `20 * stats-lease`（默认 3s）周期持久化；当修改行数/总行数超过 `tidb_auto_analyze_ratio`（默认 0.5）且处于时间窗口内，后台自动 `ANALYZE TABLE`。**行数小于 1000 的表不触发自动 analyze**——小表统计信息常年不准，排查执行计划问题时这是常见盲区。统计信息 Version 1 自 v8.5.6 起废弃，引用旧调优经验时要留意版本。

## Links

- [TiDB Architecture](/docs/CS/DB/TiDB/Architecture.md)
- [TiDB Transaction](/docs/CS/DB/TiDB/Transaction.md)
- [TiKV](/docs/CS/DB/TiDB/TiKV.md)
- [MySQL Optimizer](/docs/CS/DB/MySQL/Optimizer.md)

## References

- [TiDB 数据库的计算](https://docs.pingcap.com/zh/tidb/stable/tidb-computing/)
- [SQL 优化](https://docs.pingcap.com/zh/tidb/v8.5/sql-optimization-concepts/)
- [EXPLAIN 语句](https://docs.pingcap.com/tidb/dev/sql-statement-explain)
- [DDL 简介](https://docs.pingcap.com/zh/tidb/v8.5/ddl-introduction/)
- [常规统计信息](https://docs.pingcap.com/zh/tidb/v8.5/statistics/)
- [TiDB 源码阅读文章：DDL 与 F1 算法](https://pingcap.com/blog-cn/tidb-source-code-reading-17)
