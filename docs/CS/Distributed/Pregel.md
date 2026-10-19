# Pregel

Pregel 是 Google 在 2009 年提出、2010 年 SIGMOD 论文公开的**分布式图计算框架**，专门处理十亿顶点 / 万亿边级别的大规模图（PageRank、单源最短路径、连通分量、社区发现等）。它的核心思想是把图**按顶点分区、常驻内存、按"超步"迭代推进**，从而把本来多轮、带跨步状态依赖的图算法，表达成一组顶点上的本地计算 + 消息传递，避免每次迭代都重新加载全图。

Pregel 与 [MapReduce](/docs/CS/Distributed/MapReduce.md)（批处理）、[MillWheel](/docs/CS/Distributed/MillWheel.md)（流处理）一起，构成本目录"批 → 流 → 图"三种数据并行视角的闭环：MR 处理无迭代的离线批；MillWheel 处理无界的事件流；Pregel 处理有结构、需多轮迭代收敛的图。

## BSP Model

Pregel 采用 **BSP（Bulk Synchronous Parallel，块同步并行）** 模型，把计算切成一系列**超步（superstep）**，超步之间用全局**屏障同步（barrier）**隔开：

- **顶点为中心（vertex-centric）**：每个顶点持有自己的状态（值、出边列表）。计算逻辑只写在一个 `Compute()` 函数里，对"当前顶点 + 本轮收到的消息"负责。
- **消息传递（message passing）**：在超步 S 中，顶点可以沿出边向**其他顶点（任意分区）**发送消息；这些消息在屏障之后、超步 S+1 才被目标顶点收到。顶点之间不直接共享内存，只通过消息通信——这正是 [Replica](/docs/CS/Distributed/Replica.md) / [Partition](/docs/CS/Distributed/Partition.md) 思路在图上的体现：图被切分，状态本地化，交互靠消息。
- **投票停机（vote to halt）**：当顶点"无事可做"时调用 `voteHalt()`，进入非活跃态、不再参与计算；但一旦在后续超步收到新消息，它会被**重新激活**。所有顶点都停机时，整个作业结束。

一个典型的 `Compute()` 形如：

```
void Compute(MessageIterator msgs):
    for m in msgs: acc += m.value          # 聚合本轮消息（如邻居的 PageRank 贡献）
    if superstep == 0:
        value = 1 / N                       # 初始化
    else:
        value = 0.15 / N + 0.85 * acc
    if superstep < MAX:
        for edge in outEdges: SendMessageTo(edge.target, value / outDegree)
        voteHalt()
```

PageRank、最短路径（初始化源点 dist=0、其余 ∞，每轮松弛）、连通分量等都天然契合这个模型。

## Pregel vs MapReduce

图算法用 [MapReduce](/docs/CS/Distributed/MapReduce.md) 也能实现，但代价高昂：MR 是"无状态、一次性的 map+reduce"，而图迭代需要在**多轮 job 之间保持图结构和中间状态**。用 MR 跑 PageRank，每一轮迭代都是一次独立 job——要重新从 HDFS 读全图、shuffle、写回，I/O 与调度开销被放大多倍，且无法利用"图结构基本不变、只有值在变"的局部性。

Pregel 的差别在于：

| 维度 | MapReduce | Pregel |
|---|---|---|
| 计算范式 | map + reduce 两阶段，无迭代语义 | 超步迭代，顶点程序循环 |
| 图驻留 | 每轮重新加载全图 | 图分区常驻 worker，值就地更新 |
| 通信 | 仅 shuffle 一次 | 每超步沿边发消息，多轮 |
| 适合 | 无迭代批处理（ETL、索引构建） | 多轮收敛的图算法 |
| 终止 | job 结束 | 所有顶点 voteHalt |

代价是 Pregel 把图分成若干 Partition 后，跨分区的消息会引入网络开销，且**图分区质量**直接影响负载均衡（热点顶点 / 幂律度分布是经典难题，引出后来的 PowerGraph / GAS 模型按边切分）。

## Fault Tolerance and Optimizations

- **容错**：Master 给每个 Worker 分配 Partition；Worker 定期把分区状态 + 邻接拓扑 **checkpoint** 到持久存储。某 Worker 失效时，Master 把它负责的 Partition 重新分配给其他 Worker，并从最近 checkpoint **重放**（replay）该 Partition 的"输入消息日志"恢复状态，不需要重跑整个作业。
- **Combiner（组合器）**：发送端可以在本地先合并发往同一目标顶点的多条消息（如求和），大幅削减跨网络消息量。
- **Aggregator（聚合器）**：每个超步收集所有顶点的某个值（如最小/最大/求和、全局边计数），在下一超步前可得全局结果，用于全局收敛判断或算法参数。
- **拓扑结构**：Master 仅负责协调与屏障，实际计算与图数据都在 Worker 上；Worker 之间对等，避免 Master 成为计算瓶颈（与 [Borg](/docs/CS/Distributed/Borg.md) 的中心调度思路不同，Pregel 的计算是去中心、数据本地化的）。

## Open Source Implementations

- **Apache Giraph**：Facebook 开源、基于 Hadoop 的 Pregel 实现，用 MR 的 infrastructure 跑 BSP 迭代，FB 用它算社交图。
- **GraphX**：Spark 上的图计算，把图表示为 `RDD[Vertex]` + `RDD[Edge]`，复用 Spark 的弹性分布式数据集与 lineage 容错，更偏向"图 + 表"混合分析。
- **PowerGraph / GraphLab**：提出 **GAS（Gather-Apply-Scatter）** 模型，按**边**而非按**点**切分以缓解幂律图的热点，是 Pregel 之后图计算的重要演进。

## Links

- [MapReduce](/docs/CS/Distributed/MapReduce.md)
- [MillWheel](/docs/CS/Distributed/MillWheel.md)
- [Borg](/docs/CS/Distributed/Borg.md)
- [Replica](/docs/CS/Distributed/Replica.md)

## References

- Pregel: A System for Large-Scale Graph Processing (Malewicz et al., SIGMOD 2010)
- Pregel paper: https://kowshik.github.io/JPregel/pregel_paper.pdf
- Giraph: https://giraph.apache.org/
- GraphX: https://spark.apache.org/graphx/
