## Introduction

数据不会自己走进湖仓。把业务系统里的数据搬到分析侧这一整条链路叫**数据集成**，它是 OLTP 世界与大数据世界的接缝，也是整条链路上最容易出问题、却最少被认真设计的一环。

难点集中在三处：**怎么拿到变更**（业务库不会主动通知你）、**怎么保证不丢不重**（链路任何一跳都可能失败）、**怎么应对 schema 变更**（上游加了一列，下游是不是要全表回溯）。这三件事没有一件能靠"定时跑个全量"彻底解决。

## ETL vs ELT

顺序的差别决定了能力边界：

- **ETL**（Extract → Transform → Load）：在数据进目标系统**之前**完成清洗转换。这是传统数仓的做法，因为仓库存储昂贵、只该放加工好的数据。
- **ELT**（Extract → Load → Transform）：先把原始数据**原样**落进湖仓，转换留到读时或用 SQL 在湖上做。

对象存储让存储成本降到可以忽略，**ELT 因此成为湖仓的默认**。它的好处不只是省钱：原始数据保留在 ODS 层（见 [Lakehouse](/docs/CS/BigData/Lakehouse.md) 的分层），清洗逻辑出错时可以重跑，而不必回到业务库重新抽一次——业务库的历史状态往往已经不可复原。

代价是"raw 层"必须真的管起来：没有 schema 约束、没有质量校验的原始数据堆在湖里，就是数据沼泽。所以 ELT 的隐含前提是表格式与治理（见 [Table Format](/docs/CS/BigData/Table_Format.md) 与 [Data Governance](/docs/CS/BigData/Governance.md)）已经就位。

## Change Data Capture

全量抽取在数据量小的时候可行，一旦表到千万行以上，"每天抽一次全量"就同时在压垮源库、网络和存储。CDC 解决的是**只拿变化的那部分**。

三种实现方式的差别很大：

| 方式 | 做法 | 评价 |
| :--- | :--- | :--- |
| 基于日志 | 直接解析数据库的事务日志（MySQL binlog、PostgreSQL WAL、Oracle redo log） | **首选**。对源库几乎无侵入，能拿到完整的插入/更新/删除，且保留顺序 |
| 基于时间戳 / 自增 ID 轮询 | 按 `updated_at` 或 `id` 增量查询 | 简单，但**抓不到删除**（行没了就查不到），且时间戳不单调时漏数据 |
| 触发器 | 在源表上建触发器把变更写进影子表 | 能抓删除，但**侵入源库事务**、增加写延迟，运维负担重 |

基于日志的 CDC 之所以是首选，除了低侵入，还因为它天然携带**顺序与事务边界**——日志本身就是按提交顺序写的，这让它能够还原出"这一批变更属于同一个事务"。

> [!WARNING]
> 基于时间戳的增量同步**抓不到删除**，这是它最常被低估的缺陷。业务上"用户注销了"这类事件如果靠 `updated_at` 同步，下游会永远保留这个用户。若必须用轮询方案，得在源库侧改成软删除（标记而非物理删除）。

## Snapshot Plus Incremental

完整的同步链路是两段式的：

1. **全量快照（snapshot）**：在某个一致性位点把表的当前状态完整读出来。关键是要拿到**对应的日志位点**（binlog 的 file + position，或 PostgreSQL 的 LSN），后面从哪儿接着读全靠它。
2. **增量追平（streaming）**：从快照时的位点开始消费日志，把这段时间内的变更追上。
3. **稳态**：之后持续消费增量。

这三步之间不能丢位点，否则要么漏数据（位点太靠后），要么重复数据（位点太靠前）。重复通常可接受——只要下游是幂等写入；漏数据则不可接受。所以工程上的默认取向是宁可重复：**配合 upsert，重复无副作用**。

## Delivery Semantics on the Sink Side

CDC 链路的语义按"端到端"算，而不是按某一跳算。消息系统（[Kafka](/docs/CS/MQ/Kafka/Kafka.md)）能做到精确一次投递，但如果下游是追加写的文件，重放仍然会造成重复行。因此关键在于 **sink 是否幂等**：

- **追加型 sink**（普通 Parquet 表）：不幂等。重放即重复。
- **Upsert 型 sink**（按主键覆盖的表格式表）：幂等。同一条变更写多次结果相同——这正是 CDC 入湖必须选支持行级更新的表格式的根本原因。

所以"CDC 入湖"这个需求，直接决定了表格式的选择方向：需要高频 upsert 的场景，[Hudi](/docs/CS/BigData/Table_Format.md) 的记录级索引（RLI）与 MOR 表是天然匹配，Iceberg 与 Delta 则靠 delete 文件 / deletion vector 实现。反过来说，**如果目标表不支持行级更新，CDC 就只能退化成"追加流水 + 下游自己取最新一条"**，把去重成本推给每一个消费者。

## Schema Evolution

上游加列、改列类型、删列，是同步链路的日常。表格式能做的只是在**存储层**容忍变更（加列、列类型的安全提升通常没问题），但语义层面的兼容要人来判：

- **加列**：通常安全，下游读历史数据时新列为 null。
- **删列**：下游如果还引用了就会失败，需要协调下线。
- **改列类型**：只有" widening"（int → bigint、float → double）通常安全，收窄会丢精度。
- **改列名**：等价于删 + 加，是最危险的一种——下游查询不会报错，只会静默读到 null。

实践上，schema 变更应该在**管道入口**就被拦住并告警，而不是等到下游报表数字异常才发现。这也是 Avro 这类自带 schema 的格式在数据交换层仍有价值的原因（见 [Storage Format](/docs/CS/BigData/Storage_Format.md)）。

## SCD: Turning Changes into History

CDC 给的是"这一行现在是什么"，而分析往往要"这一行在过去某个时刻是什么"。把变更流落成带历史的维度表就是缓慢变化维：

- **Type 1**：直接覆盖。只保留最新状态，实现最简单（upsert 即可），代价是丢历史。
- **Type 2**：每次变更插入一个新版本行，带生效时间与失效时间（或 `is_current` 标记）。保留完整历史，join 时要带上时间条件。这是维度表的主流做法。
- **Type 3**：只额外保留一个"上一次的值"列，保留一次变更历史，很少用。

落在实现上，Type 2 需要把 CDC 的 update 事件转成"旧版本失效 + 新版本插入"两步——这已经不是简单的 upsert，而是需要 merge 语义。Spark 4.2 在声明式流水线里提供的 Auto CDC 正是针对这个场景：直接消费行级变更流，自动做 SCD Type 1 的 upsert。

## Tooling Landscape

| 类别 | 代表 | 特点 |
| :--- | :--- | :--- |
| 日志型 CDC 采集 | Debezium、canal（见 [canal](/docs/CS/DB/Middleware/canal.md)） | 解析 binlog / WAL，产出变更流 |
| 流式集成框架 | Kafka Connect（见 [Connect](/docs/CS/MQ/Kafka/Connect.md)）、Flink CDC（见 [Connector](/docs/CS/Framework/Flink/Connector.md)） | 托管 connector 的生命周期与位点 |
| 批量数据同步 | DataX、Sqoop | 全量 / 按字段增量，跨异构数据源；适合一次性搬迁与离线补数 |
| 日志与埋点采集 | Flume、Filebeat、各类 agent | 非数据库数据源的接入 |
| 编排调度 | Airflow、DolphinScheduler | 任务依赖与重试，不负责数据本身 |

选型的核心判断是**变更频率与延迟要求**：分钟级以上、表不大，批量同步足够；秒级、表大、且需要捕获删除，就必须上日志型 CDC。

## Links

- [BigData](/docs/CS/BigData/BigData.md)
- [Table Format](/docs/CS/BigData/Table_Format.md)
- [Lakehouse](/docs/CS/BigData/Lakehouse.md)
- [Kafka Connect](/docs/CS/MQ/Kafka/Connect.md)
- [Flink Connector](/docs/CS/Framework/Flink/Connector.md)
- [canal](/docs/CS/DB/Middleware/canal.md)

## References

1. [Debezium Documentation](https://debezium.io/documentation/)
2. [Kafka Connect](https://kafka.apache.org/documentation/#connect)
3. [Flink CDC Connectors](https://nightlies.apache.org/flink/flink-cdc-docs-stable/)
4. [Designing Data-Intensive Applications, Ch.11 Stream Processing](https://dataintensive.net/)
5. [OpenLineage](https://openlineage.io/)
