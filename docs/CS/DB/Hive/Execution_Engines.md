# Hive Execution Engines

## Introduction

HiveQL 的执行后端在 4.x 收敛为 **Tez 唯一**。历史上 Hive 先后支持 MapReduce（默认）、Tez、Spark 三种执行引擎，4.x 移除了 Spark、弃用了 MapReduce，Tez 成为唯一受支持且默认的执行后端。理解这段演进，是升级 3.x → 4.x 时排查 `hive.execution.engine` 配置、改写作业的前提。

## Tez

Tez 是 DAG 执行框架，用有向无环图取代 MR 的固定 map→reduce 阶段：

- 阶段间数据留在内存 / 本地盘，不再每阶段写 HDFS，典型分析查询比 MR 快 2~10 倍。
- **容器复用**：JVM 容器跨 task 复用，降低启动开销。
- **Shuffle**：Tez 自有 shuffle 服务，比 MR 的 shuffle 更省。
- 运行在 YARN 之上，资源由 YARN 调度。

## LLAP

LLAP（Low Latency Analytical Processing）在 Tez 之上加一层**常驻执行 + 缓存守护进程**：

- 把热数据与部分计算留在进程内，把交互式查询压到亚秒级。
- 不改变执行模型，只是把「每次都从存储冷启动」变成「热路径常驻」。
- 配合 Tez 的 fragmented readers 做 I/O 并行。

## MapReduce (deprecated)

MR 是 1.x / 2.x 的默认引擎，4.x **已弃用**：还在但不再做性能投入，部分新特性（如 rebalance compaction）只以 query-based compaction 跑。把它当作迁移目标而非回退项。

## Spark (removed)

Hive on Spark 在 4.0 **被移除**——`SET hive.execution.engine=spark` 在 4.x 直接不工作。这类作业要么迁到 Tez，要么改用 Spark SQL 直接读同一批 metastore 表（Spark 侧经 HMS / Iceberg catalog，不经 Hive 执行）。

## 4.x Convergence

```
MR (1.x/2.x 默认, 4.x 弃用) --> Tez (DAG, 4.x 唯一引擎, 默认)
   \--> Spark (2.x/3.x 可选, 4.x 移除)
LLAP: 常驻守护 + 缓存, 叠加在 Tez 之上做交互式加速
```

迁移到 4.x 的脚本必须确认 `hive.execution.engine` 不再被设成 `mr` / `spark`，否则作业会直接失败或悄然走不被维护的路径。

## Links

- [Hive](/docs/CS/DB/Hive.md)
- [Architecture](/docs/CS/DB/Hive/Architecture.md)
- [Operations](/docs/CS/DB/Hive/Operations.md)

## References

1. [Apache Tez](https://tez.apache.org/)
2. [Hive 4.0 - Overview of Major Changes](https://hive.apache.org/docs/latest/overview-of-major-changes/)
3. [Hive 4 Key Features, in depth](https://www.aicassindra.com/blogs/hive_impala/hive_4_features.html)
