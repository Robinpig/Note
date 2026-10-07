## Introduction

MapReduce 是 Hadoop 的**分布式离线批处理计算模型与框架**，用于在大规模普通商用机集群上并行处理海量数据。它把计算抽象成两个用户可编程的函数——`Map` 和 `Reduce`，框架负责数据切分、任务调度、容错、网络分发与聚合。

它的设计哲学是“**移动计算而非移动数据（moving computation to data）**”：尽可能把计算任务调度到存放对应 HDFS 数据块的节点本地执行，减少网络传输。MapReduce 适合吞吐量大、延迟不敏感的批量 ETL/统计；现代实时分析多用 [Flink](/docs/CS/Framework/Flink/Flink.md)、[Spark](/docs/CS/Framework/Spark/Spark.md)，但 MR 的 shuffle/分区思想仍是理解这些框架的基础。

## Programming Model

一次作业（Job）把输入切成若干分片（InputSplit），经过三阶段：

1. **Map**：每个输入记录（key/value）调用用户的 `map()`，输出若干中间键值对。
2. **Shuffle & Sort**（框架完成）：按 key 分区（partition）、排序（sort）、归并，把相同 key 的中间数据送到同一个 Reducer；这是 MR 最核心也最“重”的环节。
3. **Reduce**：对每个 key 及其值集合调用 `reduce()`，聚合输出最终结果。

```
Input Split -> [Map] -> (k,v) -> partition -> shuffle(网络传输) -> sort/merge -> [Reduce] -> Output(HDFS)
```

- **Partition**：决定中间 key 去哪一个 Reducer，默认 `HashPartitioner`：`reduceId = (k.hashCode() & MAX_VALUE) % numReduces`，保证同 key 进同一 reducer。
- **Sort**：每个 Reducer 收到的数据按 key 排序，因此 `reduce()` 看到的是有序的 key 分组。
- **Combiner（可选的本地预聚合）**：在 Map 端先做一次“局部 reduce”，减少 shuffle 的数据量（要求满足结合律，如求和、计数；求平均不能直接用）。
- WordCount 是最经典示例：map 输出 `(word,1)`，shuffle 按 word 分组，reduce 求和。

## MRv2 on YARN

早期 MRv1 里 JobTracker 既管资源又管任务调度，是明显瓶颈与单点。Hadoop 2.x 的 **MRv2 把资源管理与作业生命周期管理解耦**，并把资源管理交给 [YARN](/docs/CS/Framework/Hadoop/Yarn.md)：

- 一个 MR 作业提交后，YARN 启动该作业专属的 **MRAppMaster（ApplicationMaster）**，负责本次作业的任务切分、向 ResourceManager 申请资源、监控与容错。
- 拿到 Container 后，MRAppMaster 启动 **MapTask / ReduceTask** 运行在各 NodeManager 节点上。
- ResourceManager 不再关心“这是不是 MR 任务”，从而使同一套 YARN 可以同时跑 MR、Spark、Flink、Tez 等多种计算引擎。

## Map / Reduce Task

### MapTask

- 顺序读取本地分片，调用 `map()`。
- 输出先写**环形内存缓冲区**（`mapreduce.task.io.sort.mb`，默认 100MB），达到阈值（默认 80%）后**spill（溢写）**到本地磁盘，每次溢写产生一个有序小文件并可能运行 combiner/压缩。
- Map 结束时把多个溢写文件 **merge** 成一个大的有序文件，等待 Reduce 拉取。

### ReduceTask and Shuffle

- **Copy（fetch/pull）**：Reduce 主动去各 MapTask 节点**拉取（pull）**属于自己分区的数据（这点与 Flink 的上游 push 模型形成对比，见 [Flink Dataflow](/docs/CS/Framework/Flink/Dataflow.md)）。
- **Merge/Sort**：把拉到的多个文件归并排序，按 key 分组。
- **Reduce**：逐组调用 `reduce()`，结果通常写回 HDFS（每个 reducer 一个 part 文件）。

Shuffle 涉及大量磁盘 IO 与网络传输，是 MR 性能的关键瓶颈：调优常围绕缓冲区大小、溢写阈值、combiner、压缩（snappy/lzo）、慢节点（speculative execution 推测执行）、JVM 复用（JVM reuse）展开。

## Fault Tolerance

- Map/Reduce Task 无状态、幂等，失败后由 MRAppMaster **重新调度执行**；Map 输出若丢失（节点故障），重跑对应 MapTask 即可（这也是为什么 Reduce 依赖的 Map 输出要能重新生成）。
- ApplicationMaster 失败由 YARN 的 ResourceManager/ApplicationMaster 重试机制重启。
- 数据可靠性由 [HDFS](/docs/CS/Framework/Hadoop/HDFS.md) 的多副本保证。

## Trade-offs

- 优点：模型简单、容错强、横向扩展好、适合超大规模批处理、数据本地性好。
- 缺点：**每两个阶段之间都把中间结果落盘**，多轮迭代/交互查询时反复读写 HDFS，延迟高；只有 Map/Reduce 两个原语，复杂作业需要串联多个 Job；编程样板代码多。
- 这些缺点催生了 DAG 引擎：[Spark](/docs/CS/Framework/Spark/Spark.md) 用 RDD 的内存流水线与 DAG 减少落盘，Tez 把多 MR 串成一个 DAG；[Flink](/docs/CS/Framework/Flink/Flink.md) 则以原生流式执行同时覆盖批与流。

## Links

- [Hadoop](/docs/CS/Framework/Hadoop/Hadoop.md)
- [YARN](/docs/CS/Framework/Hadoop/Yarn.md)
- [HDFS](/docs/CS/Framework/Hadoop/HDFS.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)
- [分布式 MapReduce 概念](/docs/CS/Distributed/MapReduce.md)

## References

1. [Hadoop MapReduce Tutorial (official)](https://hadoop.apache.org/docs/stable/hadoop-mapreduce-client/hadoop-mapreduce-client-core/MapReduceTutorial.html)
2. [Hadoop Architecture - YARN & MRv2](https://hadoop.apache.org/docs/stable/hadoop-yarn/hadoop-yarn-site/YARN.html)
3. [MapReduce Original Paper (Dean & Ghemawat)](https://research.google/pubs/mapreduce-simplified-data-processing-on-large-clusters/)
