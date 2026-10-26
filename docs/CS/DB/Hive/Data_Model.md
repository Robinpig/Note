# Hive Data Model

## Introduction

Hive 的数据模型是「数据库 → 表 → 分区 → 分桶 → 行」的层级，落盘结构是「HDFS 目录即分区」。把数据模型想清楚，是建表时避免「删了数据还看得到」「DROP 误删数据」这类事故的前提。核心决策集中在表的托管方式、分区/分桶粒度、SerDe 映射与约束。

## Database and Table Types

- **Database / Schema**：命名空间，默认 `default`。
- **Managed Table（内部表）vs External Table（外部表）**：核心差异在 `DROP`。Managed 表 `DROP` 同时删元数据**和**数据；External 表（`EXTERNAL` 关键字，`LOCATION` 指向已有数据）`DROP` 只删元数据、数据原样保留——外部表常用来把 HBase、已存在的 HDFS 目录「映射」进 Hive。在 CDP 等发行版里，非 ACID 托管表迁到新集群时还可能被 HMS 自动转成外部表。
- **Transactional properties**：表的 ACID 与否由表属性决定——`transactional=true` 是 full ACID（仅 ORC），`insert_only=true` 是 insert-only ACID，都不含则是非 ACID 表。详见 [ACID and Transactions](/docs/CS/DB/Hive/ACID_and_Transactions.md)。

## Partition

分区按某列（通常是日期 / 地域）切分，每张分区是 HDFS 上一个子目录。查询带分区谓词时走**分区裁剪（partition pruning）**，跳过无关目录，是 Hive 最大的提速手段之一。

- **静态分区**：`INSERT` 时显式指定分区值。
- **动态分区**：由输入数据决定分区值，`hive.exec.dynamic.partition` 控制开关，`hive.exec.dynamic.partition.mode`（strict / nonstrict）限制是否允许全动态。

## Bucket (Clustering)

对列做哈希、把数据分成固定数量的桶文件（`CLUSTERED BY ... INTO N BUCKETS`），用于采样、map-side join 与更细的分布控制；可叠加 `SORTED BY` 在桶内排序。注意 Hive 在**未显式分桶的 full-acid ORC 表上也会隐式创建桶文件**，这正是 rebalance compaction 要解决的问题（见 [ACID and Transactions](/docs/CS/DB/Hive/ACID_and_Transactions.md)）。

## SerDe and StorageHandler

- **SerDe（Serializer / Deserializer）**：决定行如何与文件字节互转。内置 `LazySimpleSerDe`（文本）、`AvroSerDe`、`ORCSerDe`、`ParquetHiveSerDe`、`OpenCSVSerDe`、`RegexSerDe`、JSON 处理等；4.2.1 修了 Avro SerDe schema URL 处理的安全漏洞（不要信任用户提供的 schema URL）。
- **StorageHandler**：把非原生存储（如 HBase、Iceberg、Kafka）挂成 Hive 表——`STORED BY` 后面跟 Handler 类，如 `org.apache.hadoop.hive.hbase.HBaseStorageHandler` 把 HBase 表映射为外部表。

## Views, Materialized Views and Constraints

- **View**：逻辑视图，保存查询定义、不存数据，用来封装复杂 join / 列投影。
- **Materialized View**：物理物化、可建存储处理器与重写；4.x 支持 Iceberg 源、改进刷新，且配合 **Scheduled Queries**（`CREATE SCHEDULED QUERY ... EVERY n MINUTES AS ALTER MATERIALIZED VIEW ... REBUILD`）让 HS2 按 cron 自刷，无需外部调度器。
- **Constraints**：3.0+ 支持主键 / 外键 / 唯一 / 非空约束（默认 ENABLE NOVALIDATE，仅作为元数据提示，不强制校验数据），主要用于与 BI 工具和表格式（如 Iceberg）的互操作。
- **Temporary Tables**：会话级临时表，存于临时仓库、会话结束自动清理，适合 ETL 中间结果。

## Links

- [Hive](/docs/CS/DB/Hive/Hive.md)
- [Storage Formats](/docs/CS/DB/Hive/Storage_Formats.md)
- [HiveQL](/docs/CS/DB/Hive/HiveQL.md)
- [ACID and Transactions](/docs/CS/DB/Hive/ACID_and_Transactions.md)

## References

1. [Apache Hive](https://hive.apache.org/)
2. [Hive LanguageManual DDL](https://cwiki.apache.org/confluence/spaces/Hive/pages/27362034/LanguageManual+DDL)
3. [Hive LanguageManual DML](https://cwiki.apache.org/confluence/spaces/Hive/pages/27362036/LanguageManual+DML)
4. [Hive 4 Key Features, in depth](https://www.aicassindra.com/blogs/hive_impala/hive_4_features.html)
