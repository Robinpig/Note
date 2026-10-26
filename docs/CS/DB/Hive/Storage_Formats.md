# Hive Storage Formats

## Introduction

存储格式决定列存效率、压缩比与是否支持 ACID。Hive 托管表的默认选择是 ORC（ACID 必需、与 Hive 生态绑定最深），跨引擎共享则选 Parquet。两者都是列存 + 块级压缩 + 谓词下推，但内部结构不同。

## ORC

ORC（Optimized Row Columnar）是 Hive 原生列存格式，自带轻量索引、谓词下推，**ACID 事务必需**。

- **内部结构**：文件按 **stripe**（默认约 64–256 MB）切分，每个 stripe 含若干行组（row group）；stripe 尾部有 **index**（行组级 min/max、位置索引）与 **footer**（schema、stripe 统计）；文件末尾有 **postscript**（压缩与 schema 概要）。行组级统计（min/max/sum/count、bloom filter）支撑谓词下推与行组跳过。
- **谓词下推 / 向量化**：ORC 配合 Hive 向量化执行（vectorized query execution）按列批量处理，显著快于行式解释执行。
- **Bloom Filter**：可对列建 bloom filter 加速等值过滤（尤其 `IN` / 点查式谓词）。
- **适用**：Hive 托管表、ACID、向量化读、需要统计信息与索引的场景。

## Parquet

Parquet 是跨引擎通用列存（Spark / Impala / Trino 一等公民）。

- **内部结构**：文件由若干 **row group**（行集合的水平切片）组成，每个 row group 内含按列的 **column chunk**，column chunk 再分 **page**（最小编码单位）；文件尾部 **footer** 含 schema 与每列统计与偏移；支持 **dictionary encoding**（低基数列）。
- **适用**：多引擎共享、湖仓；与 Spark / Impala 侧工具链配合最顺。

## TextFile, Avro, RCFile, SequenceFile

| 格式 | 特点 | 适用 |
| :--- | :--- | :--- |
| **TextFile** | 默认但最慢，无压缩 / 无列裁剪优势 | 临时导入、方便人类读 |
| **Avro** | 行存、schema 演化友好 | 数据交换、流式 |
| **RCFile / SequenceFile** | 早期格式，基本被 ORC / Parquet 取代 | 历史兼容 |

## ORC vs Parquet

ORC 与 Hive 生态（ACID、向量化执行、统计信息）绑定更深，是 Hive 托管表的默认选择；Parquet 在 Spark / Impala 侧更通用，是多引擎 lakehouse 的公约数。两者都支持嵌套类型与谓词下推，差异主要体现在与各自「主场」引擎的优化器/统计协同上，而非格式能力本身。

## Column-Oriented vs Wide-Column

ORC / Parquet 的「列存」把同列跨行压在一起面向扫描聚合，这与 BigTable / HBase 那种「列族内行存」的宽列存储不是一回事——后者优化的是按 RowKey 的点查与范围扫描，前者优化的是「读少数列做聚合」。见 [DataBases](/docs/CS/DB/DB.md) 的 Row Versus Column-Oriented。

## Links

- [Hive](/docs/CS/DB/Hive/Hive.md)
- [Data Model](/docs/CS/DB/Hive/Data_Model.md)
- [ACID and Transactions](/docs/CS/DB/Hive/ACID_and_Transactions.md)
- [Iceberg Integration](/docs/CS/DB/Hive/Iceberg_Integration.md)

## References

1. [Apache ORC](https://orc.apache.org/)
2. [Apache Parquet](https://parquet.apache.org/)
3. [Apache Hive](https://hive.apache.org/)
4. [Hive 4 Key Features, in depth](https://www.aicassindra.com/blogs/hive_impala/hive_4_features.html)
