## Introduction

湖仓（lakehouse）不是某个产品，而是**一种把"廉价开放存储"和"数仓级管理能力"合在一起的架构主张**。它的出现是为了终结一次长达十年的来回：先有数据仓库（存得贵、但管得好），再有人受不了成本把数据倒进数据湖（存得便宜、但管不住），最后发现两头都不对，于是试图在一套存储上同时拿到两者。

理解这条路为什么这样走，比记住湖仓的定义更有用——因为今天湖仓里的每一件东西（表格式、catalog、开放文件格式），都能追溯到前两代架构的某个具体失败。

数据仓库与数据湖的根本差异在 [DB](/docs/CS/DB/DB.md) 的 Data Warehousing 一节有概念铺垫：仓库装的是 OLTP 系统数据的只读副本，经 ETL 清洗转换后加载，模型是关系型的。本页讲它在大数据规模上的演进。

## Data Warehouse: Schema-on-Write

传统数仓的逻辑是**写入前先建模**：数据进来之前，必须先定好表结构、维度、口径，ETL 过程把数据清洗成这个结构再加载。这叫 schema-on-write。

好处是读的时候一切都是确定的：查询快、口径统一、数据质量有保障、血缘清晰。代价同样明确：

- **建模的前置成本高**，且一旦建好就很难改——加一个维度可能要回溯全量。
- **只能装结构化数据**。日志、埋点、图像、文本这些"暂时不知道怎么用"的数据进不来，而它们恰恰是体量最大的部分。
- **存储与计算耦合**。仓库用的是专有格式与专有存储，成本随数据量线性上升，且数据被锁在厂商里。
- 专门为分析另建一套存储引擎、只是共享 SQL 接口的 HTAP 方案（如 SAP HANA），本质上也是在这套逻辑下做优化。

## Data Lake: Schema-on-Read, and Its Failure

数据湖反过来：**先把原始数据原样落到廉价存储**（早期是 [HDFS](/docs/CS/Framework/Hadoop/HDFS.md)，现在是对象存储），格式开放（Parquet、ORC、Avro），什么时候用、怎么用，读取时再解释。这叫 schema-on-read。

它解决了成本与多样性的问题是真的：一份存储容纳所有形态的数据，机器学习可以直接读原始文件，不必受数仓模型的约束。

但第一代数据湖有个致命缺口——**它只有"文件"没有"表"**。没有事务、没有原子提交、没有隔离，于是：

- 作业写到一半失败，留下的是**部分数据**，下游读到脏的；
- 两个作业同时写同一目录，结果不可预测；
- 想删一行、改一条记录，只能重写整个分区；
- 没有 schema 约束与数据质量校验，也没有人知道某张表是谁建的、能不能删。

结果就是业界给它起的那个名字——**数据沼泽（data swamp）**：东西都在里面，但没人敢用。这个文件层缺口的修补者就是表格式，见 [Table Format](/docs/CS/BigData/Table_Format.md)。

## Lakehouse: What Actually Changed

湖仓的定义性主张是：**在开放、廉价的对象存储上，用一层表格式元数据拿到传统数仓的事务、治理与性能**。它保留了数据湖的两个核心资产（开放文件格式 + 存储的存算分离），同时把数仓的管理能力补回来。

把它拆成可验证的四条：

1. **开放存储**：数据是 Parquet / ORC，不是专有格式。这保证任何时候都能换引擎、换厂商，不被锁死。
2. **表格式提供事务与版本**：ACID 提交、快照隔离、时间旅行、行级更新。
3. **存算分离**：存储是对象存储，计算是独立的引擎集群，各自伸缩。这与 [YARN](/docs/CS/Framework/Hadoop/Yarn.md) 时代"数据与计算必须在同一台机器"的假设决裂。
4. **多引擎共享一份数据**：Spark 做 ETL、Trino 做交互查询、[Flink](/docs/CS/Framework/Flink/Flink.md) 做流、Python 做 ML，全部指向同一批文件、同一个 catalog。

第 4 条是湖仓真正区别于"带事务的数据湖"的地方，也是它依赖开放格式的原因：如果数据是专有格式，多引擎共享就无从谈起。这也解释了为什么 catalog（[Hive](/docs/CS/DB/Hive/Hive.md) Metastore、Iceberg REST Catalog、Unity Catalog）在湖仓里的地位被抬高——它从"查表在哪"变成了"跨引擎的统一命名空间与权限边界"。

## Layered Modeling

开放存储解决了"存得下、管得住"，但没解决"怎么让人看懂"。湖仓之上仍然需要建模，国内实践通行的分层是：

| 层 | 全称 | 内容 | 建模特征 |
| :--- | :--- | :--- | :--- |
| ODS | Operational Data Store | 原始数据镜像，与源头基本一致 | 几乎不做加工，保留原始粒度与字段，用于回溯与对账 |
| DWD | Data Warehouse Detail | 清洗、去重、标准化后的明细数据 | 粒度与业务过程一致，开始统一口径与编码 |
| DWS | Data Warehouse Summary | 面向主题的轻度/中度汇总 | 按主题域建宽表，服务多场景复用 |
| ADS | Application Data Store | 面向具体应用的结果表 | 高度定制，直接对接报表与接口 |

分层的价值不在"层数多"，而在**把加工过程变成可复用、可回溯的资产**：上游只做一次清洗，下游不再各洗各的；出问题能逐层下钻到 ODS 对账。反模式也很典型——层数堆到七八层、每层只做一点点加工，结果是血缘长得无法维护。

## Dimensional Modeling

明细层的建模方法仍然是 Kimball 那套维度建模，它在湖仓里没有过时：

- **事实表**存业务过程的度量（订单金额、点击次数、停留时长），**维度表**存描述性上下文（用户、商品、时间、渠道）。
- **星型模型**：事实表直接连各维度表，一层展开。查询路径短、join 少，是分析场景的首选。
- **雪花模型**：维度表再规范化拆分（商品 → 品类 → 部门）。省存储但增加 join，列存下省下的空间通常不值得多出来的 join 代价。
- 事实表按粒度分三类：**事务型**（每个事件一行）、**周期快照**（定期记录状态）、**累计快照**（记录一个有生命周期的实体的各阶段时间点）。

**缓慢变化维（SCD）**是维度建模里最容易做错的一环——维度属性会变（用户换了城市、商品改了类目），而历史事实不能跟着变。常见处理：Type 1 直接覆盖（丢历史）、Type 2 加版本行与生效时间（保历史，最常用）、Type 3 加一个"旧值"列（只保一次）。CDC 语义与 SCD 的对应关系在 [Data Integration](/docs/CS/BigData/Data_Integration.md) 里有更具体的落法。

## Where Hive Fits

在湖仓叙事里 [Hive](/docs/CS/DB/Hive/Hive.md) 的位置发生了分化，值得单独说明：它的**查询执行层（HS2 + Tez + LLAP）**份额在收缩，被 Trino / Spark SQL 这类引擎挤占；但它的 **Metastore（HMS）**反而成了湖仓的事实标准 catalog——Iceberg、Delta、Hudi 都支持 HMS，连 Spark 与 Trino 也常靠它找表。4.x 起 Hive 自己也成了 Iceberg 的一等公民，见 [Iceberg Integration](/docs/CS/DB/Hive/Iceberg_Integration.md)。

所以"要不要用 Hive"在 2026 年是两个问题：**要不要用 HMS 当 catalog**（多数情况下仍值得）与**要不要用 HS2 跑查询**（新建项目通常不必）。

## Links

- [BigData](/docs/CS/BigData/BigData.md)
- [Table Format](/docs/CS/BigData/Table_Format.md)
- [Storage Format](/docs/CS/BigData/Storage_Format.md)
- [Hive](/docs/CS/DB/Hive/Hive.md)
- [SQL Engine](/docs/CS/BigData/SQL_Engine.md)
- [Data Governance](/docs/CS/BigData/Governance.md)

## References

1. [Lakehouse: A New Generation of Open Platforms (CIDR 2021)](https://www.cidrdb.org/cidr2021/papers/cidr2021_paper17.pdf)
2. [Databricks - What is a Lakehouse?](https://www.databricks.com/glossary/lakehouse)
3. [The Data Warehouse Toolkit (Kimball & Ross)](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/books/)
4. [Apache Hive Metastore](https://cwiki.apache.org/confluence/display/Hive/Design)
