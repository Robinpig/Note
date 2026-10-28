## Introduction

[TiDB](https://docs.pingcap.com/zh/tidb/stable/overview/) 是 PingCAP（平凯星辰）自主设计、研发的开源分布式关系型数据库，
同时支持 OLTP 与 OLAP，是一款 HTAP 融合型分布式数据库，具备水平扩缩容、金融级高可用、实时 HTAP、
云原生部署、兼容 MySQL 协议与生态等特性，目标是为用户提供一站式 OLTP / OLAP / HTAP 解决方案。
适合高可用、强一致要求较高、数据规模较大的应用场景。

与单机数据库相比，TiDB 的核心差异在于「**计算存储分离 + 数据自动分片 + Raft 多副本**」：
存储层按 key range 切成 Region 自动分布，计算层无状态横向扩展，副本一致性由 Raft 保证，
上层通过 MySQL 协议对外暴露，多数场景可直接替换 MySQL。

本文是 TiDB 主题的枢纽页，按「先看清整体形状，再逐层深入」的顺序组织分册。
建议从 [Architecture](#map-of-this-section) 建立全局图景，再按需进入各组件专页。

## Map of This Section

TiDB 的知识可以顺着一条「一条 SQL 的一生」的路径读下去，这也是本分册的组织顺序：

1. **[Architecture](/docs/CS/DB/TiDB/Architecture.md)** —— 先建立全局形状：四个核心组件（TiDB Server / PD / TiKV / TiFlash）、
   计算存储分离意味着什么、客户端接入链路（负载均衡 → TiProxy → TiDB Server）、
   以及 LTS / DMR 版本谱系（当前开源基线 v8.5.8 LTS，master 已切 CalVer `v26.3` 的 TiDB X 架构）。
2. **[TiDB_Server](/docs/CS/DB/TiDB/TiDB_Server.md)** —— SQL 层内部：MySQL 协议接入、parser、optimizer、
   executor 如何把 SQL 变成分布式执行计划；Coprocessor 下推为什么必要；DDL 的 job 队列与 owner 机制；
   行数据如何编码成 KV；统计信息与 auto-analyze。
3. **[TiKV](/docs/CS/DB/TiDB/TiKV.md)** —— 存储引擎：Region 三要素与默认阈值、multi-raft-group 写路径、
   RocksDB 的 raftdb / kvdb 与四个 ColumnFamily、BlockCache 与 MemTable 参数、Titan 的取舍、MVCC 落地。
4. **[Transaction](/docs/CS/DB/TiDB/Transaction.md)** —— 分布式事务：Percolator 两阶段提交、
   乐观 vs 悲观事务的默认与差异、SI/RR 隔离级别的实现、大事务上限、GC 的 safe point 与 compaction filter、
   资源管控 RU。
5. **[PD](/docs/CS/DB/TiDB/PD.md)** —— 集群大脑：为什么用 etcd、TSO 授时的物理时间 + 逻辑计数器、
   PD 存哪些元信息、调度器体系与 operator 下发流程、Placement Rules。
6. **[TiFlash](/docs/CS/DB/TiDB/TiFlash.md)** —— HTAP 的列存侧：Raft Learner 副本如何做到异步复制但不丢一致性、
   DeltaTree 存储组织、MPP 与 Exchange 算子、读引擎的选择。
7. **[Tools](/docs/CS/DB/TiDB/Tools.md)** —— 工具链分工：TiUP / Operator 部署、BR 物理备份与 PITR、
   Lightning 本地导入、DM 迁移、TiCDC 增量同步，以及已废弃组件（mydumper/loader/syncer/pump+drainer）的替代关系。

读完这条链，应该能回答三个问题：一条 SQL 从连接到返回结果经过了哪些组件；
一次写在 Raft 与 RocksDB 层如何落盘；PD 在哪些关键路径上不可缺席。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [MySQL](/docs/CS/DB/MySQL/MySQL.md)
- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [OceanBase](/docs/CS/DB/OceanBase.md)

## References

- https://docs.pingcap.com/zh/tidb/stable/overview/
- https://github.com/pingcap/tidb
- https://www.pingcap.com/blog/
