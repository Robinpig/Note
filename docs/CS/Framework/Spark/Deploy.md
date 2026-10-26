## Introduction

Spark 的部署回答两件事：**Driver 跑在哪**（deploy mode），以及**Executor 由谁分配**（cluster manager）。这两件事正交组合，构成 Spark 的各种运行形态。

进程角色：

- **Driver**：执行用户 `main()`，持有 `SparkContext`，运行 DAGScheduler / TaskScheduler，与 executor 保持心跳（详见 [Scheduler](/docs/CS/Framework/Spark/Scheduler.md)）；
- **Executor**：执行 task、存放 RDD 缓存与 shuffle 数据，生命周期由集群管理器管理（内存布局见 [Memory](/docs/CS/Framework/Spark/Memory.md)）。

## 两种 deploy mode

| 维度 | client 模式 | cluster 模式 |
| ---- | ---- | ---- |
| Driver 位置 | 提交作业的机器 | 集群内部（YARN 的 AM / K8s 的 driver pod） |
| 网络要求 | Driver 与 executor 必须互通，提交机不能断 | 只要集群内可达，提交方可断开 |
| 日志与结果 | 直接在提交机看 | 需要到集群侧收集（`yarn logs` / pod log） |
| 适用 | 交互式（spark-shell、notebook）、调试 | **生产作业** |

```shell
./bin/spark-submit \
  --master yarn \
  --deploy-mode cluster \
  --executor-memory 8g --executor-cores 4 --num-executors 20 \
  --class com.example.App app.jar
```

## 三种（曾经四种）集群管理器

| 管理器 | 形态 | 现状 |
| ---- | ---- | ---- |
| Standalone | Spark 自带的 master/worker，部署最简单 | 小规模、测试环境常用 |
| YARN | 交给 Hadoop 的 ResourceManager 分配 container | 传统 Hadoop 集群主流，与 [HDFS](/docs/CS/Framework/Hadoop/HDFS.md) 同置时数据本地性好 |
| Kubernetes | driver / executor 都是 Pod | 云原生首选；Spark 4.0 起提供官方 **Spark Kubernetes Operator**，把应用声明成 CRD 管理 |
| Mesos | —— | **Spark 4.0 已移除支持**（若仍在使用需迁移到 YARN / K8s / Standalone） |

> [!NOTE]
> 早期论文里 Spark 是"构建在 Mesos 之上"的（见 [Spark](/docs/CS/Framework/Spark/Spark.md) 的论文要点），这是 2010 年前后的历史背景。Mesos 在 Spark 4.0 已被移除，"Spark 依赖 Mesos"不再是现状描述。

## 版本基线（Spark 4.x）

| 项 | 4.x 要求 |
| ---- | ---- |
| JDK | **17 起**（JDK 8 / 11 不再支持） |
| Scala | 默认 2.13，Scala 2.12 支持已移除（Spark 3 多为 2.12） |
| Hadoop | 需 3.3.6+ |
| SQL 默认行为 | ANSI 模式默认开启；默认表 provider 由 `spark.sql.sources.default` 决定 |
| 其他 | servlet API 从 `javax` 迁到 `jakarta`；事件日志默认压缩与滚动归档 |

稳定版节奏上，4.0 系列（2025 起）、4.1 系列、4.2.0（2026-07）都在维护中，生产选版本时应以官方 downloads 页标注的稳定版为准。

## Spark Connect

Spark Connect 把"客户端"与"Spark 集群"解耦：客户端通过 gRPC 把未解析的逻辑计划发给服务端，服务端解析、优化、执行，再把结果流式返回。

收益：

- 客户端极轻（PySpark 客户端包很小），不必在提交机装完整 Spark；
- 多语言客户端（Python / Java / Scala / Go / Rust / Swift），跨语言能力对齐；
- driver 与客户端隔离，稳定性更好、便于多租户与远程开发。

Spark 4.0 起可用 `spark.api.mode` 开关，并提供了默认启用 Connect 的发行包；SQL/DataFrame 功能已基本对齐传统模式。

## 资源与弹性

- **静态分配**：`--num-executors`、`--executor-cores`、`--executor-memory` 固定；
- **动态资源分配**（`spark.dynamicAllocation.enabled`）：按待处理 task 数量伸缩 executor。注意它依赖 **external shuffle service**（或在 K8s 上用 shuffle tracking），否则 executor 被回收会丢 shuffle 数据，导致 FetchFailed 重算；
- **推测执行**：慢 task 另起一份（参数见 [Scheduler](/docs/CS/Framework/Spark/Scheduler.md)）；
- **K8s 上**：Spark 4.0 起 executor pod 按批次分配（默认批大小 10）、PVC 使用 `ReadWriteOncePod` 访问模式。

## 选型建议

| 场景 | 推荐 |
| ---- | ---- |
| 本地开发 / 单元测试 | `local[*]`、spark-shell |
| 已建 Hadoop 集群，作业与 HDFS 同置 | YARN + cluster 模式 |
| 云原生、容器化、需要声明式运维 | Kubernetes + Spark Kubernetes Operator |
| 远程/多语言/轻客户端接入 | Spark Connect |
| 小规模固定集群 | Standalone |

## Links

- [Scheduler](/docs/CS/Framework/Spark/Scheduler.md)
- [Memory](/docs/CS/Framework/Spark/Memory.md)
- [Shuffle](/docs/CS/Framework/Spark/Shuffle.md)
- [SQL](/docs/CS/Framework/Spark/SQL.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)

## References

1. [Spark Docs - Cluster Mode Overview](https://spark.apache.org/docs/latest/cluster-overview.html)
2. [Spark Docs - Running Spark on Kubernetes](https://spark.apache.org/docs/latest/running-on-kubernetes.html)
3. [Spark Docs - Migration Guide: Spark Core 4.0（Mesos 移除等）](https://spark.apache.org/docs/4.0.0/core-migration-guide.html)
4. [Spark Release 4.0.0（Spark Connect、K8s Operator）](https://spark.apache.org/releases/spark-release-4-0-0.html)
