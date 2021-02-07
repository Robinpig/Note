# Hadoop

## 简述

Apache基金会下**分布式系统基础架构**，其主要包括：

- 分布式文件系统HDFS
- 分布式计算系统MapReduce
- 分布式资源管理系统YARN

## 架构

### HDFS

**Hadoop Distributed File System**(分布式文件系统），能提供对数据访问的高吞吐量，提供高可靠性（多副本实现）、高扩展性和高吞吐率。

**基本原理**：将数据文件以指定块大小拆分，以副本方式存储到多台机器上。

#### 基本概念

**数据块**  Block

默认基本存储单位，块大小**64M**，文件多大就占据多少空间。

**元数据节点** NameNode

职责是管理文件系统命名空间，所有文件夹与文件元数据保存在**文件系统树**上，使用版本号VERSION，写操作记录到修改日志，在成功之前同步文件系统。

**数据节点** DataNode

实质存储数据位置，

**从元数据节点** Secondary NameNode

帮助NameNode将内存存储元数据信息checkpoint到硬盘上。

#### 运行机制

##### 读写流程 

基于**RPC**请求调用

##### 副本机制

副本系数决定副本数，确定后不可改，默认3个副本，提供容错机制，丢失或宕机自动恢复。

##### 数据负载均衡

##### 机架感知

##### Hadoop序列化

##### SequenceFile

二进制文件支持的数据结构，用于合并小文件，其特点有：

- 支持压缩
  - 基于Record 只压缩Value
  - 基于Block 对Key和Value都压缩
- 本地化任务支持
- 难度低

##### MapFile

排序后的SequenceFile，由data和index组成，index记录Record的Key值与偏移量。使用index检索效率更高，但会消耗内存存储空间。

### MapReduce

编程模型，Map任务并行处理后排序输入到Reduce任务统一处理。

并行计算模型，map()分治,统一到reduce()，

### YARN

Yet Another Resource Negotiator，将MapReduce架构中资源管理与作业调度监控功能分离。

YARN可分离业务，在其之上可运行其它计算框架有：

- 离线计算框架：MapReduce
- DAG计算框架：Tez
- 流式计算框架：Storm
- 内存计算框架：Spark