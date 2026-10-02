## Introduction

YARN（Yet Another Resource Negotiator）是 Hadoop 2.x 引入的**集群资源管理与作业调度框架**。它把 MRv1 中 JobTracker 身兼的“资源管理”和“任务调度/监控”两大职责拆开，让 Hadoop 集群从“只能跑 MapReduce”变成一个可以同时运行多种计算引擎（MapReduce、[Spark](/docs/CS/Framework/Spark/Spark.md)、[Flink](/docs/CS/Framework/Flink/Flink.md)、Tez、Hive on Tez 等）的通用资源平台。

核心思想：YARN 只管**资源（CPU、内存）的统一分配与调度**，至于拿到资源后跑什么、怎么切分任务、如何容错，交给每个作业自己的 ApplicationMaster 决定。

## Components

### ResourceManager（RM）

全局唯一的主节点，是集群资源的最终仲裁者，包含两个核心组件：

- **Scheduler（调度器）**：只负责按容量/队列/公平策略把资源分配给应用，**不关心应用内部状态与监控**。常见调度器：FIFO、Capacity Scheduler、Fair Scheduler。
- **ApplicationsManager / ApplicationMasterService**：接收作业提交、协商启动该作业的第一个 Container 用来运行 ApplicationMaster，并在 AM 失败时负责重启它。

### NodeManager（NM）

每个工作节点上一个，是该节点的资源与任务管家：

- 向 RM 注册、定期**心跳**汇报节点资源与 Container 运行状态；
- 启动/监控本机的 **Container**（本质是一组受 cgroups/进程隔离限制的 CPU+内存资源）；
- 监控节点健康、管理本地磁盘与日志、按 RM 指令杀死/回收 Container；
- 为执行中的任务提供 auxiliary service（如 shuffle service，供 Reduce 拉取 Map 输出）。

### ApplicationMaster（AM）

**每个作业一个**，是“作业级”的协调者（与全局唯一的 RM 不同）：

- 向 RM 注册并申请资源（ResourceRequest：需要多少 Container、多大内存/CPU、期望的数据本地性）；
- 拿到 Container 后，与对应 NodeManager 通信，在其中启动具体任务（如 MapTask/ReduceTask、Spark Executor、Flink TaskManager）；
- 负责任务切分、调度、**容错重试**、进度与计数器监控；
- 作业完成后向 RM 注销并释放资源。

这样“作业如何执行”的逻辑就从 RM 中解耦了，这是 YARN 支持多引擎的关键。

### Container

YARN 资源分配的基本单位，是节点上一块**逻辑隔离的资源**（内存 + vcores，可结合 cgroups 做 CPU/内存隔离）。任务都运行在 Container 中，第一个 Container 专门用来启动 AM，之后的 Container 由 AM 向 RM 申请来运行具体 task。

## Workflow

```
Client 提交作业 -> RM 接收
  -> RM 在某个 NM 上分配第一个 Container，启动该作业的 ApplicationMaster
  -> AM 向 RM 注册并申请资源（一批 Container）
  -> RM 的 Scheduler 分配 Container（尽量考虑数据本地性，让任务靠近 HDFS 数据块）
  -> AM 联系对应 NM，在 Container 中启动 MapTask/ReduceTask（或其他引擎任务）
  -> 任务运行，NM 心跳给 RM、AM 监控任务
  -> AM 汇总结果，作业结束后向 RM 注销，RM 回收资源
```

## Scheduling

| 调度器 | 特点 |
| ---- | ---- |
| FIFO | 先进先出，简单但大作业会阻塞小作业 |
| Capacity Scheduler | 多队列、每队列保证容量，队列间可借用闲置资源（Hadoop 默认） |
| Fair Scheduler | 让多个作业随时间**公平共享**集群资源，小作业也能较快获得资源 |

资源模型上，YARN 对内存是强约束（超出 Container 内存上限的进程会被 NM kill），对 CPU 最初是弹性/基于 shares，现代版本可启用 cgroups 严格限制。

## YARN vs Other Resource Managers

YARN 是**以 Hadoop 为中心的静态资源分配 + Container 启动**模型（申请 Container、启动 JVM、进程长期占用）。对比：

- [Flink](/docs/CS/Framework/Flink/Flink.md) / Spark 可以运行在 YARN 之上（把各自的 JobManager/Driver、TaskManager/Executor 作为 Container 提交），也可运行在 Kubernetes 上。
- **Kubernetes** 以声明式、容器化（Docker/Pod）、长服务与批任务统一调度见长，正在成为 Flink/Spark 部署的新主流，YARN 仍广泛存在于存量 Hadoop/数据平台。
- Mesos 则是更早的通用两级调度器（master + framework）。

## Links

- [Hadoop](/docs/CS/Framework/Hadoop/Hadoop.md)
- [MapReduce](/docs/CS/Framework/Hadoop/MapReduce.md)
- [HDFS](/docs/CS/Framework/Hadoop/HDFS.md)
- [Flink on YARN](/docs/CS/Framework/Flink/JobManager.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)

## References

1. [Hadoop YARN Official Documentation](https://hadoop.apache.org/docs/stable/hadoop-yarn/hadoop-yarn-site/YARN.html)
2. [YARN Architecture](https://hadoop.apache.org/docs/stable/hadoop-yarn/hadoop-yarn-site/YARN.html)
3. [Hadoop: Capacity Scheduler](https://hadoop.apache.org/docs/stable/hadoop-yarn/hadoop-yarn-site/CapacityScheduler.html)
