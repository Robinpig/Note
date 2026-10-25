## Introduction

只要一条查询里有 `join`、`group by`、`distinct` 或窗口分区，数据就必须**按 key 重新分布**：同一个 key 的所有记录必须落到同一个下游任务里，否则聚合结果不完整。这一步就是 shuffle。

它之所以是大数据性能的头号瓶颈，是因为它一次性触及了三种最贵的资源：数据要**序列化**后跨网络发送（网络）、接收侧要**落盘**再读（磁盘 IO）、还要**排序或哈希**分桶（CPU）。一个跑得慢的作业，绝大多数时候慢在 shuffle 或者 shuffle 引发的长尾上，而不是慢在计算逻辑本身。

[Spark](/docs/CS/Framework/Spark/Spark.md) 侧的具体实现（map 端写、reduce 端读、shuffle manager 演进）见 [Shuffle](/docs/CS/Framework/Spark/Shuffle.md)，本页讲 shuffle 的通用机制与它最典型的故障——数据倾斜。

## Where Shuffle Comes From

在 [Spark](/docs/CS/Framework/Spark/Spark.md) 的术语里，依赖分**窄依赖**（一个分区只依赖上游一个分区，如 map / filter）与**宽依赖**（一个分区依赖上游多个分区）。**宽依赖就是 shuffle 的同义词**，也是 stage 的切分点。

```
窄依赖（可流水线，无 shuffle）      宽依赖（stage 边界，需 shuffle）
  A1 → B1                            A1 ┐
  A2 → B2                            A2 ├→ B1, B2, ...  （按 key 重分布）
  A3 → B3                            A3 ┘
```

判断标准很实用：**如果去掉 shuffle，结果会错，那它就是必需的**。所以优化 shuffle 的思路不是"消除 shuffle"，而是三个方向——减少 shuffle 的数据量、让 shuffle 的数据更均匀、让 shuffle 的读写更高效。

## Cost and Optimization

**减少数据量**是最有效的手段，因为它直接按比例降低三项开销：

- **列裁剪与谓词下推**：shuffle 前只保留需要的列与行。这是一切优化里收益/成本比最高的，也是列存格式（见 [Storage Format](/docs/CS/BigData/Storage_Format.md)）与统计信息存在的意义。
- **Map-side 预聚合（combiner / partial aggregate）**：在 map 端先把同 key 的部分结果合并，只把中间结果发走。对 `count`、`sum`、`max` 这类可结合运算有效；对 `avg`、`distinct count` 要改写成可结合形式（如 sum + count）才能用。
- **Broadcast join**：小表足够小时，把它广播到每个 executor，用本地 map-side join 完全绕开 shuffle。这是最彻底的"消除 shuffle"，代价是广播表必须能放进内存。
- **Bucket / 预分区**：如果两张表事先按同一个 key、同样的桶数分好桶，join 时就不需要再重分布。

**提高读写效率**则靠实现层：批量网络传输而非逐条、压缩传输、以及下面要讲的排序型与推送型 shuffle。

## Shuffle Implementations

shuffle 的实现经历过一次关键演进，驱动力是文件数量：

| 实现 | 做法 | 问题 / 特点 |
| :--- | :--- | :--- |
| Hash shuffle | 每个 map task 为每个 reduce task 写一个文件 | 文件数是 `M × R`，几千个 task 时文件句柄与随机写成为灾难；早期 Spark 的默认，早已废弃 |
| Sort-based shuffle | 每个 map task 只写一个数据文件 + 一个索引文件，文件内按 partition 排序 | 文件数降到 `M`，顺序写、顺序读；Spark 的默认实现 |
| External shuffle service | 把 map 输出交给常驻服务托管，与 executor 生命周期解耦 | executor 被回收后数据仍可读，支持动态资源伸缩 |
| Push-based / magnet shuffle | map 端把同 partition 的数据推送并合并到中间服务 | 进一步减少 reduce 端的随机小读，适合超大规模 shuffle |
| Pipelined（流） | 数据不落盘，直接在网络间流动 | 流处理与 MPP 引擎的做法，延迟最低但**不支持容错重算** |
| Blocking（批） | 上游完整产出并落盘后下游才读 | 批处理的做法，支持失败重算，代价是必须等 |

流引擎与批引擎在这里的分野很清楚：**要能失败重算就必须物化，要低延迟就不能物化**。这也是 [Flink](/docs/CS/Framework/Flink/Flink.md) 批模式与流模式在 shuffle 上不同、以及 Trino 这类交互式引擎选择流水线交换而放弃细粒度容错的原因。

## Data Skew

数据倾斜指的是**数据按 key 分布极不均匀**：少数 key 聚集了绝大部分记录。由于 shuffle 是按 key 分区的，这些 key 对应的那几个下游 task 就会拿到几十倍于同侪的数据量，于是：

- 那几个 task 跑得极慢，整个 stage 等它们（**长尾**）；
- 它们更容易 OOM，失败后重试仍然慢，最终拖垮作业；
- 集群绝大部分资源在等着，利用率极低。

常见成因：

1. **业务热点本身存在**：头部主播、爆款商品、超级大客户。这是真实的分布，不是 bug。
2. **大量 null 或默认值**：`user_id = null`、`-1`、`0` 这类"未登录/未知"被当成同一个 key 聚合，往往单个 key 就能占掉一半数据。这是最常见、也最好修的一类。
3. **分区粒度太粗**：按天分区但某天有活动，当天分区巨大。
4. **join 的一端有重复 key**：一对多 join 时多侧的热点被放大。

**诊断方法**很直接：看 stage 里各 task 的处理记录数与耗时的分布。如果中位数 task 几秒跑完、最大值是几十分钟，且输入记录数差出数量级，就是倾斜。Spark UI 的 task 列表与 shuffle read 记录数是主要依据。

## Handling Skew

| 解法 | 做法 | 适用 |
| :--- | :--- | :--- |
| 过滤或单独处理热点 | 把 null / 默认值先剔除或单独走一条路径 | null 或默认值造成的倾斜，首选 |
| 两阶段聚合（加盐） | 给 key 加随机前缀先局部聚合，再去盐全局聚合 | 聚合类（group by）倾斜，最通用 |
| Broadcast join | 小表广播，直接 map-side join | 一端足够小 |
| Skew join 拆分 | 把大表的热点 key 单独拆出，与另一表的对应行做广播 join，其余走正常 shuffle join | join 倾斜且两端都大 |
| 提高分区数 | 增大 shuffle partition 数 | 仅对"分区太少"有效，**对真倾斜无效**——热点 key 无论多少分区都仍在一个桶里 |
| 自适应执行 | 运行时依据实际统计重新规划 join 策略并拆分倾斜分区 | 引擎支持时的一劳永逸方案 |

**"提高分区数能治倾斜"是最常见的误解**。它治的是分区数不足导致的单 task 数据量过大，而真倾斜的根因是 key 分布本身——同一个 key 的所有记录必然进同一个分区，分区数再多也拆不开。区分这两者的办法是看倾斜 task 的输入记录数：如果各 task 记录数差不多但都很大，是分区太少；如果极不均匀，是倾斜。

现代引擎在把这件事自动化：**自适应查询执行（AQE）**在运行时用已完成的 stage 的真实统计替换规划期的估算，据此动态合并小分区、把倾斜分区拆成多个、并把本可广播的 join 改成广播。这让"手动加盐"这条老技巧在新版本上不再是必需品——但它依赖统计信息的准确性，因此 `ANALYZE TABLE` 仍是前置条件。

## Links

- [BigData](/docs/CS/BigData/BigData.md)
- [Shuffle](/docs/CS/Framework/Spark/Shuffle.md)
- [Processing Model](/docs/CS/BigData/Processing_Model.md)
- [SQL Engine](/docs/CS/BigData/SQL_Engine.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)

## References

1. [Apache Spark - Shuffle behavior and tuning](https://spark.apache.org/docs/latest/rdd-programming-guide.html#shuffle-operations)
2. [Apache Spark Adaptive Query Execution](https://spark.apache.org/docs/latest/sql-performance-tuning.html#adaptive-query-execution)
3. [Apache Flink - Task chaining and resource groups](https://flink.apache.org/)
4. [Magnet: Push-based Shuffle Service for Large-scale Data Processing (VLDB 2020)](https://www.vldb.org/pvldb/vol13/p3382-shen.pdf)
