## Introduction

对象存储上放一批 Parquet 文件，只能叫"一堆文件"，不能叫"一张表"。缺的不是数据，是**把文件组织成表所需的语义**：哪些文件构成当前版本、写入是否原子、两个作业同时写会怎样、怎么删掉一行、怎么回退到昨天。文件格式（见 [Storage Format](/docs/CS/BigData/Storage_Format.md)）完全不回答这些问题——Parquet 文件本身不可变，改一行只能重写整个文件。

**表格式（table format）**就是补上这一层的元数据与协议。它的共同手法是：数据仍然是不可变的列存文件，另用一层元数据记录"文件清单 + 快照 + schema"，把对表的修改表达成**元数据的原子替换**。于是"删一行"不再需要重写大文件，而是"写一个新的快照元数据，指向旧文件 + 一个记录删除的附属文件"。

三强格局是 **Apache Iceberg**、**Delta Lake**、**Apache Hudi**。它们解决的问题高度重叠，但出发点不同，导致设计取舍明显分岔。

> [!NOTE]
> 版本口径（2026-10 核实）：Iceberg **1.12.0**（2026-09-29，移除 Spark 3.4 与 Flink 2.0 支持，新增 Flink 2.2 / 2.3）；Delta Lake **4.4.0**（2026-08-20，默认 Spark 4.2，3.3.3 为维护中的 3.x 线）；Hudi **1.2.0**（2026-05，表版本 9，0.14.2 / 0.15.1 为维护线）。

## Iceberg: Manifest Tree and Snapshot Isolation

Iceberg 的出发点是**解决 Hive 表在云上的规模问题**——Hive 靠目录列举文件，几万个分区时 listing 就成瓶颈，且分区与目录强绑定导致改分区要重写数据。

它的元数据是一棵树：

```
metadata.json            ← 表当前指针，指向当前 snapshot 与 schema
  └── manifest-list      ← 一个快照包含哪些 manifest
        └── manifest     ← 每个 manifest 描述一批数据文件 + 列级统计
              └── data file (Parquet / ORC / Avro)
```

每个写操作生成一个新的 snapshot，靠**原子地替换 metadata 指针**提交（在对象存储上是原子的 put-if-absent / rename，在 HDFS 与 NOSQL 上另有保证）。这一层带来几个直接能力：

- **快照隔离与时间旅行**：读者看到的是提交瞬间的 snapshot，写入不影响正在进行的查询；可以按 snapshot id 或时间戳读历史版本。
- **Hidden partitioning**：分区是元数据里的转换表达式（如 `days(ts)`），用户按原始列过滤即可命中分区裁剪，不必感知物理分区列。这解耦了 Hive 那种"目录即分区"的绑定。
- **Partition evolution**：后期改分区策略不重写老数据——新旧分区方案共存于不同 snapshot，规划时分别裁剪。
- **并发提交用乐观并发控制（OCC）**：多个写者各自基于同一基版本提交，冲突者重试。Iceberg 的重试基于"我要替换的基版本是否仍是当前版本"，因此并发写不同分区通常都能成功。

行级删除有两种承载方式：**position delete**（按"文件 + 行号"定位，写时不需要知道完整行）与 **equality delete**（按列值相等匹配，适合流式场景没有稳定行号时）。读时合并的方式又分 **copy-on-write**（直接重写文件，读快写放大）与 **merge-on-read**（写 delete 文件，读时合并，写轻读重）；1.12 还引入了把 equality delete 转换成 deletion vector 的维护任务。

生态上 Iceberg 是**中立性最强的**：Spark、Flink、Trino、[Hive](/docs/CS/DB/Hive.md) 4.x、Impala 都原生支持，REST Catalog 规范让 catalog 本身也能独立成服务（Unity Catalog、Polaris 等）。

## Delta Lake: Transaction Log

Delta 的出发点最朴素：**给数据湖加事务**。它的元数据是一条**线性提交日志**：

```
_delta_log/
  00000000000000000000.json
  00000000000000000001.json
  ...
  00000000000000000010.checkpoint.parquet    ← 每 10 个提交做一次 checkpoint
```

每个 JSON 提交记录本次新增 / 删除了哪些文件。读者从最近一个 checkpoint 往前重放后续 JSON，得到当前文件清单。并发同样用 OCC：两个写者争同一个版本号时，后到者基于先提交者的状态重算并重试。

Delta 的几个特点：

- **协议版本化独立于发行版**：`PROTOCOL.md` 用 reader / writer version 加具名 table features 表达，而不是跟着 4.x 走。这是它与 Iceberg "format version" 的对应物，选型时要看的是协议版本而非软件版本。
- **Delta Kernel**：把读写逻辑抽成独立库（Java / Rust），让非 Spark 引擎按统一语义接入，而不必各自重新实现协议。ClickHouse、DuckDB 等走的就是这条路。
- **UniForm**：自动生成 Iceberg / Hudi 元数据，让一份 Delta 表对外同时表现为 Iceberg 表。这是"三强趋同"的实际机制。
- **Catalog-managed tables**（4.1 起）：把提交仲裁交给 catalog 服务，向"catalog 中心化"演进，与 Iceberg REST Catalog 的方向一致。

Delta 与 Spark / Databricks 绑定最深（4.4.0 默认构建于 Spark 4.2），这是它的优势也是它的边界。

## Hudi: Timeline and Incremental Everything

Hudi 的出发点与前两者不同：**它一开始就是为 upsert 和增量处理设计的**，目标是把数据库级的更新能力搬到数据湖，并让下游能按增量消费。

核心结构是 `.hoodie` 下的 **timeline**——按时间顺序记录所有操作（commit / deltacommit / compaction / clean / clustering），配合一个 **metadata table**（文件清单、列统计、bloom filter、记录级索引）避免在云存储上反复 listing。

Hudi 的两张表类型：

- **COW（Copy-on-Write）**：更新即重写受影响的文件，读路径最简单。
- **MOR（Merge-on-Read）**：更新写入增量日志文件（avro log），读时与基线 Parquet 合并；compaction 定期把日志并入基线。写入延迟最低，适合高频小更新。

它的差异化能力在**索引**上：bloom filter、bucket index、以及 1.2 起完整支持的 **Record Level Index（RLI）**——直接定位某条记录所在文件，这让大规模 upsert 不必全表扫描。这是三强里索引体系最完整的。此外 Hudi 自带**自优化的表服务**：compaction、clustering、cleaning 异步执行且大多不阻塞写入，运维负担显著低于另两者。

代价是概念最多：timeline、file group、file slice、instant、table service 构成了陡峭的学习曲线。1.x 起类型系统扩展到 VECTOR / VARIANT / BLOB，并支持 Lance 作为 base file，方向是把湖仓推向 AI / 多模态负载。

## Comparison

| 维度 | Iceberg | Delta Lake | Hudi |
| :--- | :--- | :--- | :--- |
| 元数据组织 | manifest 树 + snapshot 指针 | 线性 JSON 日志 + checkpoint | timeline + metadata table |
| 规划代价 | 只读相关 manifest，文件极多时最优 | 重放 checkpoint 之后的日志 | metadata table 避免 listing |
| 行级更新 | position / equality delete + COW / MOR | deletion vector + COW | log 文件 + COW / MOR |
| 索引能力 | 逐步增强（bloom、deletion vector） | 基础（data skipping） | 最强（bloom / bucket / RLI） |
| 并发写 | OCC，分区不冲突通常都成功 | OCC，争版本号重试 | OCC + 表服务协调 |
| 表维护 | 需外部调度 compaction / 聚簇 | OPTIMIZE / liquid clustering | 内置异步 compaction / clustering / clean |
| 引擎生态 | 最中立（Spark / Flink / Trino / Hive / Impala） | 与 Spark 最深，经 Kernel 外扩 | Spark / Flink 为主 |
| 学习曲线 | 中 | 低 | 高 |
| 最适场景 | 多引擎共享的开放湖仓、超大规模表 | Spark 为主的湖仓、Databricks 体系 | 高频 upsert、CDC 入湖、增量链路 |

## How to Choose

- **要多个引擎读同一张表**（Spark 写、Trino 查、Flink 流读）——选 Iceberg。它的 REST Catalog 与中立治理是三家里最成熟的。
- **技术栈以 Spark / Databricks 为主**，且希望最少的运维心智——选 Delta Lake。UniForm 保留了将来转 Iceberg 的退路。
- **主链路是 CDC 入湖、高频 upsert**，或希望引擎自己把 compaction / clustering 管起来——选 Hudi。RLI 在大规模点更新场景是决定性的。
- **已有 Hive 数仓要演进**——Iceberg 是 [Hive](/docs/CS/DB/Hive.md) 4.x 的一等公民表格式，见 [Iceberg Integration](/docs/CS/DB/Hive/Iceberg_Integration.md)；Hive 原生的 ACID ORC 方案见 [ACID and Transactions](/docs/CS/DB/Hive/ACID_and_Transactions.md)。

三强的边界正在模糊：Delta 用 UniForm 生成 Iceberg 元数据，Iceberg 引入 deletion vector 与聚簇，Hudi 也在靠 metadata table 收敛规划代价。**真正该锁定的不是格式，而是"数据文件是不是开放的 Parquet / ORC"**——只要底座开放，格式迁移的成本就可控。

## Links

- [BigData](/docs/CS/BigData/BigData.md)
- [Storage Format](/docs/CS/BigData/Storage_Format.md)
- [Lakehouse](/docs/CS/BigData/Lakehouse.md)
- [Iceberg Integration](/docs/CS/DB/Hive/Iceberg_Integration.md)
- [Data Integration](/docs/CS/BigData/Data_Integration.md)

## References

1. [Apache Iceberg Documentation](https://iceberg.apache.org/docs/latest/)
2. [Iceberg Spec - Tables and Snapshots](https://iceberg.apache.org/spec/)
3. [Delta Lake Documentation](https://docs.delta.io/latest/index.html)
4. [Delta Lake Protocol (PROTOCOL.md)](https://github.com/delta-io/delta/blob/master/PROTOCOL.md)
5. [Apache Hudi Documentation](https://hudi.apache.org/docs/overview/)
6. [Apache Hudi Technical Specification 1.0](https://hudi.apache.org/learn/tech-specs)
