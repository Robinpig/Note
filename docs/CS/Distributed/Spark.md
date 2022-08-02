# Spark

## 简述

Apache基金会下分布式计算框架，基于内存，速度快，高可用。

它的主要组件有：

- **SparkCore**：将分布式数据抽象为弹性分布式数据集（RDD），实现了应用任务调度、RPC、序列化和压缩，并为运行在其上的上层组件提供API。
- **SparkSQL**：Spark Sql 是Spark来操作结构化数据的程序包，可以让我使用SQL语句的方式来查询数据，Spark支持 多种数据源，包含Hive表，parquest以及JSON等内容。
- **SparkStreaming**： 是Spark提供的实时数据进行流式计算的组件。
- **MLlib**：提供常用机器学习算法的实现库。
- **GraphX**：提供一个分布式图计算框架，能高效进行图计算。
- **BlinkDB**：用于在海量数据上进行交互式SQL的近似查询引擎。
- **Tachyon**：以内存为中心高容错的的分布式文件系统。

## 整体架构

- **Driver** 用户编写数据处理逻辑，包含创建的**SparkContext**是用户逻辑与Spark集群主要交互接口。
- **Cluster Manager**负责集群的资源管理与调度，也可使用Hadoop的**YARN**或Apache的**Mesos**和**Standalone**。
- **Worker Node**是集群中可用节点，其中包含**Executor**作为运行进程，**Task**为计算单元。

## 组成

### RDD

 RDD（Resilient Distributed Dataset）叫做**弹性分布式数据集**，**是Spark中最基本的数据抽象**，它代表一个不可变、可分区、里面的元素可并行计算的集合。RDD具有数据流模型的特点：自动容错、位置感知性调度和可伸缩性。RDD允许用户在执行多个查询时显式地将工作集缓存在内存中，后续的查询能够重用工作集，这极大地提升了查询速度。 

#### RDD特性

- 一系列分区信息（**Partition**）

对于RDD来说，每个分片都会被一个计算任务处理，并决定并行计算的粒度。用户可以在创建RDD时指定RDD的分片个数，如果没有指定，那么就会采用默认值。默认值就是程序所分配到的CPU Core的数目。

- 每个分区一个**计算函数**

Spark中RDD的计算是以分片为单位的，每个RDD都会实现compute函数以达到这个目的。compute函数会对迭代器进行复合，不需要保存每次计算的结果。

- RDD之间的**依赖关系**。

RDD的每次转换都会生成一个新的RDD，所以RDD之间就会形成类似于流水线一样的前后依赖关系。在部分分区数据丢失时，Spark可以通过这个依赖关系重新计算丢失的分区数据，而不是对RDD的所有分区进行重新计算。

- **Partitioner**，即RDD的分片函数，类型Hadoop的Partitioner。

当前Spark中实现了两种类型的分片函数，一个是基于哈希的HashPartitioner，另外一个是基于范围的RangePartitioner。只有对于于key-value的RDD，才会有Partitioner，非key-value的RDD的Parititioner的值是None。Partitioner函数不但决定了RDD本身的分片数量，也决定了parent RDD Shuffle输出时的分片数量。

- **最佳位置列表**
一个列表，存储存取每个Partition的优先位置（preferred location）。对于一个HDFS文件来说，这个列表保存的就是每个Partition所在的块的位置。按照“移动数据不如移动计算”的理念，Spark在进行任务调度的时候，会尽可能地将计算任务分配到其所要处理数据块的存储位置。

#### RDD创建方式

1. 已存在的Scala集合创建
2. 加载成文件
3. RDD转换

#### RDD转换

通过转换算子，如map，filter等。

#### RDD依赖



Dependency

##### 窄依赖

窄依赖对优化更有利

##### 宽依赖

多个子RDD的partition依赖于同个parent RDD的partition



#### 容错机制

基于Lineage，RDD之间的转换关系构成compute chain作为Lineage，部分计算结果丢失可通过Lineage重算。

#### RDD缓存

persist()或cache()标记一个要被持久化的RDD，首次触发后，该RDD将保留在计算节点内存中便于重用，即持久化到内存或缓存

#### 共享变量

## SparkStreaming

支持数据源有Kafka、HDFS、Twitter和TCP socket等。

将流式计算分解成短小的批处理作业数据Stream转换成RDD

## Scheduler

任务调度模块，包含DAGScheduler和TaskScheduler，将用户提交计算任务按照DAG划分成不同阶段，再将任务提交到集群完成计算。

Deploy

Executor

Shuffle

Storage

Master/Slave消息传递