# HiveQL

## Introduction

HiveQL 是「接近 SQL、为 Hadoop 重新设计」的方言，由 HS2 编译器翻译成 Tez DAG 执行。它不追求完整实现 SQL 标准，更在意「能把声明式查询翻译成分布式批处理」。需要标准 SQL 互操作、子查询完全兼容、存储过程体系时，应改用 Spark SQL / Trino，或至少确认目标语法的 Hive 支持矩阵。

## Data Types

- **基础类型**：`TINYINT` / `SMALLINT` / `INT` / `BIGINT`、`FLOAT` / `DOUBLE`、`DECIMAL(p,s)`、`BOOLEAN`、`STRING`、`VARCHAR` / `CHAR`、`BINARY`、`DATE`、`TIMESTAMP`、`INTERVAL`。
- **复杂类型**：`ARRAY<t>`、`MAP<k,v>`、`STRUCT<f1:t1,...>`、`UNIONTYPE<t1,t2,...>`——配合 `LATERAL VIEW explode` / `get_json_object` 等做半结构化数据展开。

## DDL

HiveQL 的 DDL 表达力集中在把「分布式的物理布局」写进表定义：

- `PARTITIONED BY (col type, ...)`：声明分区列（分区列不算真实数据列，是目录维度）。
- `CLUSTERED BY (col) [SORTED BY (col)] INTO N BUCKETS`：声明分桶与桶内排序。
- `STORED AS <fmt>`（`TEXTFILE` / `ORC` / `PARQUET` / `AVRO` / ...）：声明文件格式。
- `STORED BY <handler>`：经 StorageHandler 挂非原生存储（Iceberg / HBase / Kafka）。
- `LOCATION`：指定数据目录；`EXTERNAL` 表必须配合 `LOCATION` 指向已有数据。
- `TBLPROPERTIES`：表级属性（如 `transactional='true'`、`table_type='ICEBERG'`）。

## DML and ACID Prerequisite

- `UPDATE` / `DELETE` / `MERGE`（upsert）**只对 ACID 表（ORC + 事务属性）可用**；非 ACID 表仍只能 `INSERT`（含 `INSERT OVERWRITE`）、`LOAD DATA`。这是早期 Hive「只支持导入和查询」说法的来源，但 3.0+ 重写后已不再是硬限制。
- **MERGE 语法**示例（按关联键做插入/更新/删除分支）：

```sql
MERGE INTO target t
USING source s ON t.id = s.id
WHEN MATCHED AND s.op = 'D' THEN DELETE
WHEN MATCHED THEN UPDATE SET t.val = s.val
WHEN NOT MATCHED THEN INSERT VALUES (s.id, s.val);
```

## Analytical Features

- **CTE**：`WITH` 子句提升可读性并允许同一子查询复用。
- **窗口函数**：`OVER (PARTITION BY ... ORDER BY ...)` 做排名、累计、滑动聚合。
- **LATERAL VIEW**：配合 `explode` / `posexplode` 把 ARRAY / MAP 展开成多行。
- **UDF / UDAF / UDTF**：三类自定义函数——普通标量（UDF）、聚合（UDAF）、表生成（UDTF，如 `explode`）。所有自定义 jar 须与运行 JDK 匹配（见 [Operations](/docs/CS/DB/Hive/Operations.md) 的 JDK floor）。
- **HPL/SQL**：Hive 的存储过程方言，提供变量、游标、流程控制，适合把既有 PL/SQL 逻辑迁到 Hive 侧。

## Cost-Based Optimizer

基于 Apache Calcite 的 CBO（4.0 升 1.25、4.1 升 1.33）会自动把符合条件的查询重写成物化视图、做 join 重排与列裁剪，并能利用列直方图统计改进偏斜列的选择率估计（4.0 新增）。`ANALYZE TABLE ... COMPUTE STATISTICS [FOR COLUMNS]` 喂给优化器的统计信息是性能命门——缺统计时 CBO 退化为基于规则的启发式计划。

## Scheduled Queries

4.0 起 HS2 内置 cron 调度，可让物化视图等周期性自刷，无需外部调度器：

```sql
CREATE SCHEDULED QUERY refresh_daily
  EVERY 10 MINUTES
  AS ALTER MATERIALIZED VIEW sales.daily_revenue REBUILD;
```

## Links

- [Hive](/docs/CS/DB/Hive.md)
- [Data Model](/docs/CS/DB/Hive/Data_Model.md)
- [Architecture](/docs/CS/DB/Hive/Architecture.md)
- [ACID and Transactions](/docs/CS/DB/Hive/ACID_and_Transactions.md)

## References

1. [Hive Documentation](https://hive.apache.org/docs/latest/)
2. [Apache Calcite](https://calcite.apache.org/)
3. [Hive 4 Key Features, in depth](https://www.aicassindra.com/blogs/hive_impala/hive_4_features.html)
