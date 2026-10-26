## Introduction

Spark 的内存管理要同时伺候两类需求：**执行内存（execution）**（shuffle、排序、join、聚合）与**存储内存（storage）**（RDD 缓存、广播变量）。Spark 1.6 起引入**统一内存管理（Unified Memory Manager）**，让两者共享同一块内存池并允许互相借用——这就是 Spark 内存模型的核心。

它与 [Shuffle](/docs/CS/Framework/Spark/Shuffle.md) 直接相关（shuffle 的缓冲区从这里申请），也是 [RDD](/docs/CS/Framework/Spark/RDD.md) 缓存能否放得下的决定因素。

## Executor 内存布局

一个 executor 的可用内存由 `spark.executor.memory`（堆内）+ `spark.executor.memoryOverhead`（堆外，含 JVM 自身开销、Netty、字符串/类元数据等）组成。堆内部分大致切分如下：

```
<------------------- spark.executor.memory (JVM heap) ------------------->
+----------+---------------+-------------------------------------------+
| Reserved |  User Memory  |            Spark Memory (fraction)         |
|  ~300MB  |  用户数据结构  |   Storage Memory      |  Execution Memory |
+----------+---------------+-------------------------------------------+
                           ↑                      ↑
                     storageFraction 边界   可与 storage 互相借用
```

| 区域 | 用途 | 可调参数 |
| ---- | ---- | ---- |
| Reserved Memory | 系统保留（约 300MB），不可用于计算 | 不可调 |
| User Memory | 用户代码里自己创建的数据结构（如 driver 侧的大集合、UDF 中的对象） | 间接由 `spark.memory.fraction` 决定 |
| Storage Memory | RDD 缓存、广播变量、task 结果 | `spark.memory.storageFraction`（Spark Memory 内 storage 的初始占比） |
| Execution Memory | shuffle、排序、hash join、聚合 | 与 storage 共享 Spark Memory |
| Off-heap / Overhead | Tungsten 堆外页、Netty、JVM 自身 | `spark.executor.memoryOverhead`、`spark.memory.offHeap.size` |

`spark.memory.fraction` 控制 Spark Memory 占（heap − reserved）的比例，默认 0.6；`spark.memory.storageFraction` 默认 0.5，即 Spark Memory 里 storage 的初始边界。

## 统一内存管理：软边界与借用规则

两块内存之间是**可移动的边界**，规则是：

| 情形 | 行为 |
| ---- | ---- |
| execution 不够用，storage 有富余 | execution 可以**借** storage 的空间；必要时驱逐 storage 的缓存块（但不会把 storage 压到低于初始边界） |
| storage 不够用，execution 有富余 | storage 可以**借** execution 的空间；但反过来 execution 不能强制收回这部分（只有 execution 自身释放后才归还） |

这套设计的效果是：缓存少的作业几乎拿到全部内存做计算；缓存多的作业也能保住一部分缓存不被计算挤掉。代价是**缓存不再"一放就一辈子"**——被驱逐后用到时会重算（对 `MEMORY_ONLY` 尤其明显，必要时用 `MEMORY_AND_DISK`）。

## Tungsten：为什么 Spark 要自己管内存

JVM 对象模型对数据密集计算很不友好：每个对象有对象头、装箱开销，堆上几千万个对象会让 GC 压力巨大。Tungsten 项目（Spark 1.4~1.6 落地）给出两条对策：

1. **堆外二进制格式**：数据以紧凑的字节序列存储（`UnsafeRow`），Spark 自己按 schema 解释字节，避免 Java 对象开销；
2. **页式内存管理**：通过 `MemoryManager` / `MemoryAllocator` 以"页（page）"为单位申请堆内或堆外内存，配合 MemoryConsumer 的 spill 协议——申请不到时按页 spill 到磁盘，而不是等 OOM。

再叠加 **whole-stage codegen**（把一串算子融合成一个 Java 方法，消除虚函数调用与迭代器开销），这就是 Spark SQL 明显快于手写 RDD 的主要原因（见 [SQL](/docs/CS/Framework/Spark/SQL.md)）。

## 存储侧：缓存与广播

- RDD 缓存块由 BlockManager 管理，按 blockId 分布在各 executor，可选序列化与副本；
- 广播变量以 Torrent 方式分发（分块 + 多点互传），避免 driver 成为瓶颈；
- 缓存块的**位置信息会参与调度**：缓存了数据的节点会成为后续 task 的 preferred location。

## 执行侧：shuffle 与溢出

- shuffle 写路径向 execution 内存申请缓冲区，满了按分区排序后 spill 成文件（见 [Shuffle](/docs/CS/Framework/Spark/Shuffle.md)）；
- hash join / 聚合同样走 Tungsten 的 `BytesToBytesMap` 等结构，放不下就 spill；
- **spill 次数是最好的健康指标**：偶发 spill 正常，频繁 spill 说明内存或分区配置不合理。

## 典型 OOM 与处置

| 现象 | 位置 | 常见原因与处理 |
| ---- | ---- | ---- |
| `java.lang.OutOfMemoryError: Java heap space` | executor 堆内 | 数据倾斜导致单 task 过大 → 增大分区数 / 打散热点 key；或 user memory 里塞了大对象 → 改广播或调大 `spark.memory.fraction` 反向让出空间 |
| `OutOfMemoryError: Unable to acquire memory` | execution 内存 | 并发 task 多、单 task 内存大 → 调 `spark.executor.cores`（降低并发度）或加大内存 |
| Container killed by YARN（超出物理内存） | 堆外 | 堆外 / overhead 不够 → 调 `spark.executor.memoryOverhead`（K8s 上对应 memoryOverheadFactor） |
| driver OOM | driver | `collect()` 拉回大量数据、广播变量过大、driver 端累积大量 task 元数据 → 避免 collect 全量、限制结果集 |

## 调优顺序建议

1. 先看 UI：spill、GC 时间占比、shuffle 量三者定位是内存问题还是数据问题；
2. 若是倾斜，先解决倾斜（内存调再大也不均匀）；
3. 再定 `spark.executor.memory` × `spark.executor.cores`（cores 越多，单 executor 内并发 task 越多，单 task 分到的内存越少）；
4. 最后才调 `spark.memory.fraction` / `storageFraction` 这两个比例参数。

## Links

- [RDD](/docs/CS/Framework/Spark/RDD.md)
- [Shuffle](/docs/CS/Framework/Spark/Shuffle.md)
- [Scheduler](/docs/CS/Framework/Spark/Scheduler.md)
- [SQL](/docs/CS/Framework/Spark/SQL.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)

## References

1. [Spark Docs - Memory Tuning](https://spark.apache.org/docs/latest/tuning.html#memory-tuning)
2. [Spark Docs - Configuration: Application / Memory](https://spark.apache.org/docs/latest/configuration.html#memory-management)
3. [Project Tungsten: Bringing Apache Spark Closer to Bare Metal](https://www.databricks.com/blog/2015/04/28/project-tungsten-bringing-spark-closer-to-bare-metal.html)
