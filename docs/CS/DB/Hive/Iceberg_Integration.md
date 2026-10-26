# Hive Iceberg Integration

## Introduction

4.0 起 **Apache Iceberg 成为一等公民表格式**，是 Hive 4 最大的功能性变化：`STORED BY ICEBERG` 声明后，普通 HiveQL 即可对该表做行级 `DELETE` / `UPDATE` / `MERGE`，并支持向量化读写。Iceberg 是开放表格式，Spark / Impala / Trino 可直接读 Hive 写的 Iceberg 表而**无需格式转换**——这是「多引擎 lakehouse」得以成立的前提，也是 Hive 在 2026 年仍能占据一席之地的核心底气。

## Copy-on-Write vs Merge-on-Read

Iceberg 提供两种行级变更实现：

- **Copy-on-Write（COW）**：更新/删除时重写受影响的数据文件，读路径简单、无额外合并开销，但写放大大。
- **Merge-on-Read（MOR）**：行级变更写入独立的 delete 文件（position delete / equality delete），读时合并，写路径轻、读时略重。Hive 默认与 Spark/Trino 协商选择，可按表设置。

## Feature Evolution

- **4.0 基础**：snapshot 管理、branches & tags、DML（含 COW / MOR）、partition 级操作、已有表就地迁移（`ALTER TABLE ... SET TBLPROPERTIES('table_type'='ICEBERG')`）、物化视图、Iceberg major compaction（`OPTIMIZE TABLE`）、time travel。
- **4.1 增强**：storage-partitioned joins、partition 级列统计、table compaction。
- **4.2 增强**：deletion vectors、auto compaction、**Iceberg REST Catalog client**（让 Hive 与 Spark / Trino / Flink 共用同一个 catalog 服务，而非各自指 metastore）、Z-ordering、variant type。

## Partition Evolution, Sort Order, Hidden Partitioning

Iceberg 的 partitioning 与存储布局解耦：**partition evolution** 允许后期改变分区策略而不重写旧数据；**sort order** 定义文件内排序以加速范围过滤；**hidden partitioning** 让查询用原始列过滤即可命中分区转换（如 day(ts)），用户无需感知物理分区列。这与 Hive 原生分区（HDFS 目录即分区、改分区需重写）形成对比。

## Deletes: Position vs Equality

- **Position delete**：按「文件 + 行号」标记删除，定位快、与 MOR 配合。
- **Equality delete**：按「列值相等」标记删除，适合无稳定行号的流式/批式删除。两者都由 Iceberg 的 delete 文件承载，Hive 的 ACID 语义（见 [ACID and Transactions](/docs/CS/DB/Hive/ACID_and_Transactions.md)）在 Iceberg 表上由 Iceberg 自己的事务/快照机制提供，而非 Hive 的 delta 文件。

## Catalog: HiveCatalog vs REST Catalog

Hive 既可用自带的 **HiveCatalog**（元数据仍经 HMS），也可用 4.2 引入的 **Iceberg REST Catalog client** 对接独立 catalog 服务（Unity Catalog、Polaris 等），实现跨引擎统一命名空间。选择取决于你是要「Hive 继续当元数据Owner」还是「把 catalog 剥离成共享服务」。

## Why It Matters

Iceberg 让 Hive 写的表成为开放、引擎无关的资产：Spark 做 ETL/ML、Trino/Impala 做交互读、Flink 做流，全部指向同一批 Iceberg 文件与同一 catalog。Hive 从「只能自己读的仓库」变成「多引擎湖仓的写入口之一」。

## Links

- [Hive](/docs/CS/DB/Hive/Hive.md)
- [ACID and Transactions](/docs/CS/DB/Hive/ACID_and_Transactions.md)
- [Storage Formats](/docs/CS/DB/Hive/Storage_Formats.md)
- [Operations](/docs/CS/DB/Hive/Operations.md)

## References

1. [Apache Iceberg](https://iceberg.apache.org/)
2. [Hive 4.0 - Overview of Major Changes](https://hive.apache.org/docs/latest/overview-of-major-changes/)
3. [Hive 4 Key Features, in depth](https://www.aicassindra.com/blogs/hive_impala/hive_4_features.html)
