## Introduction

大数据研究的是**当数据规模超出单机处理能力之后，如何把它存下、算完、管住**。它的边界不是某个 TB 数，而是一条工程判断：一旦数据放不进一台机器的内存与磁盘、一次全量扫描的时间超过业务能容忍的窗口，"换更快的机器"就不再是最优解，必须换成"多台机器分工 + 容忍部分失败"的架构。这条线之后的所有设计——分布式文件系统、批流计算引擎、列存格式、表格式、资源调度、数据治理——都是对同一个约束的不同层回应。

数据本身有三种形态：结构化的表、半结构化的 JSON / XML、非结构化的文本与图像视频。传统数据库擅长第一类且要求先有 schema，而大数据的现实是**数据先到、用法后定**，所以存储层普遍选择"先落原始文件、读时再解释"（schema-on-read），代价是把数据质量的责任从写入时推迟到了读取时。

> [!NOTE]
> 版本口径：本页与各分册涉及的版本以 2026-10 核实为准——Hadoop **3.5.0**（2026-04-02，3.5 线首个稳定版）、Spark **4.2.0**（2026-07-14）、Flink **2.3.0**（2026-06-25）、Hive **4.2.1**、Iceberg **1.12.0**（2026-09-29）、Delta Lake **4.4.0**（2026-08-20）、Hudi **1.2.0**（2026-05）、Parquet format **2.13.0**（2026-06-13）、ORC **2.3.1**（2026-07-16）、Trino **483**（2026-07-17）。各产品细节以分册为准，本页不复述。

## Four Computing Paradigms

大数据最早的分类是按**计算模式**分的，这个划分至今仍然有效，因为它对应的是四类根本不同的问题：

- **Batch（批处理）**：数据在计算开始前就已经全部就绪，任务是"对一份有界数据集算出一个结果"。吞吐优先，延迟可以是分钟到小时。代表是 [MapReduce](/docs/CS/Distributed/MapReduce.md) 与 [Spark](/docs/CS/Framework/Spark/Spark.md)。
- **Stream（流处理）**：数据无界地持续到达，任务永不结束，结果是持续更新的。延迟优先，从毫秒到秒。代表是 [Flink](/docs/CS/Framework/Flink/Flink.md) 与 Kafka Streams。
- **Interactive（交互式）**：人要等在数据旁边做即席查询，所以延迟预算被压到秒级，且必须为"查询形状完全不可预测"做优化。代表是 Trino / [Presto](/docs/CS/DB/Presto.md) 与 Impala。
- **Graph（图计算）**：数据本身是一张图，计算是沿边迭代传播，直到收敛。它的访问模式完全局部随机，与前三类"扫描大块数据"的假设相反，因此需要 BSP 之类的迭代模型，代表是 Giraph 与 GraphX。

批与流的关系值得单独强调：**批是流的一个特例**——数据有界、任务会终止的流。这是 Flink "批是有界的流"这一主张的来源，也是"流批一体"能成立的理论前提。反过来把流当成"小批的重复"（微批模型，Spark 的路线）则是另一种统一方式，代价是延迟下不来。两种统一路径的取舍见 [Processing Model](/docs/CS/BigData/Processing_Model.md)。

当年这个分类下还有一串名字，如今多数已退出主线：Pig（脚本化 MapReduce）与 Drill 基本停止演进，Storm 被 Flink 取代（[Storm](/docs/CS/Framework/Flink/Storm.md)），Giraph / Gelly 随图计算需求收缩而边缘化。**不要用这份十年前的名单做选型**，它记录的是历史脉络而非当下选项。

## Storage: From Files to Tables

数据落到对象存储或 [HDFS](/docs/CS/Framework/Hadoop/HDFS.md) 之后，要回答两个不同层次的问题，这是新手最容易混为一谈的地方：

**第一层是文件格式**——单个文件内部怎么组织字节。分析型负载的共性是"读少数列、扫大量行"，因此主流选择是列存：Parquet 与 ORC 把同列的值压在一起，配合字典编码、RLE、Delta 编码与块级压缩，既省空间又让"只读三列"变成可能。行存 Avro 仍有位置，它胜在 schema 演进与流式写入。编码原理与三种格式的取舍见 [Storage Format](/docs/CS/BigData/Storage_Format.md)。

**第二层是表格式**——一堆文件怎么构成一张"表"，谁负责事务、谁记住哪些文件是当前版本。裸的一批 Parquet 文件没有原子提交、没有隔离、没有"删一行"的能力，这正是 Iceberg / Delta Lake / Hudi 要补的：它们用元数据层记录快照与文件清单，把对象存储上"只能整文件覆写"的限制，包装成看起来像数据库的表。三强对比见 [Table Format](/docs/CS/BigData/Table_Format.md)。

把这两层加上"廉价对象存储 + 开放格式 + 多引擎可读"三件事合起来，就是当下最主流的**湖仓（lakehouse）**形态：它既不是早期"什么都往里扔"的数据湖，也不是要求先建模再入库的传统数仓，而是用表格式在开放存储上拿到接近数仓的管理能力。演进脉络与分层建模见 [Lakehouse](/docs/CS/BigData/Lakehouse.md)。

## Execution: SQL, Shuffle, and Resources

绝大多数大数据作业最终是以 SQL 提交的，但底下跑的东西差别很大。[SQL Engine](/docs/CS/BigData/SQL_Engine.md) 梳理了 SQL-on-Hadoop 这条谱系：Hive 把 SQL 编译成 Tez / MR 作业（稳但慢），Spark SQL 走内存 + 代码生成，Trino / Impala 走 MPP 流水线（快但不容错）。它们共同的优化手段是三件——统计信息驱动的 CBO、向量化执行、以及把算子链编译成字节码的 codegen。

真正决定一个作业跑多久的，往往是**数据重分布**。只要涉及 join、group by、去重，数据就必须按 key 重新分区，这一步叫 shuffle：它同时是网络、磁盘与 CPU 的瓶颈，也是"某个 key 特别大导致单个 task 拖垮整个作业"的根源。[Shuffle and Data Skew](/docs/CS/BigData/Shuffle.md) 讲了 shuffle 的几种实现与倾斜的诊断、解法。

再往下一层是**资源**：谁拿到容器、谁先跑、超卖了怎么办。[YARN](/docs/CS/Framework/Hadoop/Yarn.md) 是 Hadoop 生态的传统答案（Capacity / Fair / FIFO 三种调度器），Kubernetes 是当下新建集群的默认选择，两者对比与选型见 [Resource Scheduling](/docs/CS/BigData/Resource_Scheduling.md)。

## Ingestion and Governance

数据不会自己进湖。把业务库的变更同步到分析侧这件事叫 CDC，它是"数据库"与"大数据"两个世界的接缝：全量抽取 + 增量日志订阅、如何保证不丢不重、如何处理 schema 变更。见 [Data Integration](/docs/CS/BigData/Data_Integration.md)。

最后一层是治理。当表数量从几十张涨到几万张，"这张表是谁建的、能不能删、改了会影响谁"就必须有系统回答，而不是靠人记。元数据采集、血缘、数据质量、权限，构成 [Data Governance](/docs/CS/BigData/Governance.md) 的内容。

## Architecture Evolution

怎么把这些部件组装起来，历史上有过两次范式更替。**Lambda 架构**用批、流两套系统并存（批保证准确、流提供实时，查询结果时合并），代价是同一份逻辑要写两遍、维护两套。**Kappa 架构**主张只用一套流系统，靠重放历史日志来重算，把"两套"收敛成"一套"，代价是对消息系统的存储能力与重放性能要求极高。**流批一体**则是引擎层面的收敛：同一个 SQL、同一份代码，跑在批模式还是流模式只是运行时选择。这一段历史与取舍见 [Lambda and Kappa Architecture](/docs/CS/BigData/Lambda_Kappa.md)。

## Links

- [Processing Model](/docs/CS/BigData/Processing_Model.md)
- [Storage Format](/docs/CS/BigData/Storage_Format.md)
- [Table Format](/docs/CS/BigData/Table_Format.md)
- [Lakehouse](/docs/CS/BigData/Lakehouse.md)
- [Shuffle and Data Skew](/docs/CS/BigData/Shuffle.md)
- [Data Governance](/docs/CS/BigData/Governance.md)

## References

1. [Apache Hadoop](https://hadoop.apache.org/)
2. [Apache Spark](https://spark.apache.org/)
3. [Apache Flink](https://flink.apache.org/)
4. [Apache Iceberg](https://iceberg.apache.org/)
5. [Apache Parquet](https://parquet.apache.org/)
6. [The Lambda Architecture (Nathan Marz)](http://nathanmarz.com/blog/how-to-beat-the-cap-theorem.html)
7. [Questioning the Lambda Architecture (Jay Kreps)](https://www.oreilly.com/radar/questioning-the-lambda-architecture/)
