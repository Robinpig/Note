## Introduction

计算引擎解决"怎么算"，资源调度解决"谁在什么机器上算"。这一层存在的理由很朴素：集群是有限的，而提交作业的人和组织是多个的。于是必须有人来仲裁三件事——**谁能拿到资源**（准入与配额）、**拿到多少**（隔离与超卖）、**冲突时谁先**（优先级与公平）。

调度层做得好，用户感知不到它的存在；做得不好，表现为"集群很忙但 throughput 很低"或者"我的作业永远排在后面"。它是大数据栈里最不性感、但对多租户平台最要命的一层。

[YARN](/docs/CS/Framework/Hadoop/Yarn.md) 是 Hadoop 生态的传统答案，组件与三种调度器见该页；本页讲这一层的通用问题与 YARN / Kubernetes / Mesos 三条路线的取舍。

## What a Scheduler Must Decide

任何集群调度器都要回答四个问题，差别只在答案的方式：

1. **资源抽象**：以什么为单位分配？YARN 是 container（内存 + CPU 份额），Kubernetes 是 pod（可含多个容器，声明 request 与 limit）。
2. **分配策略**：多个队列同时要资源时怎么分？这决定了多租户能否共存。
3. **隔离强度**：承诺的资源能否真正兑现？只做记账不 enforcement，就会出现"邻居抢光内存导致我被 OOM"。
4. **任务放置**：把 task 放在哪台机器？传统上要考虑数据本地性（data locality）——把计算挪到数据所在的机器，避免跨网络读。

第 4 点在存算分离之后重要性大幅下降：数据都在远端对象存储上，"离数据近"不再有意义，只剩下网络拓扑与机架感知。这是 YARN 时代的设计假设在湖仓时代失效的典型例子。

## YARN

YARN 把 MRv1 里那个什么都管的 JobTracker 拆成了两层——**资源管理**（ResourceManager，集群级）与**单个应用的调度与监控**（ApplicationMaster，应用级）。这个拆分是它最大的遗产：从此 Hadoop 不再只能跑 MapReduce，[Spark](/docs/CS/Framework/Spark/Spark.md)、[Flink](/docs/CS/Framework/Flink/Flink.md)、Tez 都能作为"应用"跑在同一个集群上。

三种内置调度器：

| 调度器 | 策略 | 适用 |
| :--- | :--- | :--- |
| FIFO | 先到先得，独占 | 单用户或极小集群；多租户下不可用 |
| Capacity | 划分固定配额的队列，队列内 FIFO，空闲容量可借出 | **Hadoop 默认**，企业多租户的标准选择 |
| Fair | 按需动态均分，长期看各队列获得相等份额 | 交互式与批处理混跑，要求响应公平 |

YARN 的资源模型有个历史包袱：**内存是硬约束，CPU 最初只是份额（shares）而非硬限制**，后期才引入 cgroups 做严格限制。这意味着 CPU 争抢在早期版本里靠"自觉"，配置时仍要确认所用版本是否启用了 cgroups。

它的强项是**与 Hadoop 生态的深度整合**：HDFS 的本地性、Kerberos、队列权限、联邦与 Router 都与之一体。弱项是它是为"长期运行的大数据集群"设计的，弹性伸缩与异构负载（比如同时跑在线服务）支持很弱。

## Kubernetes

Kubernetes 成为新建集群的默认选择，不是因为它比 YARN 更懂大数据，而是因为它是**整个基础设施的公共底座**：在线服务、离线计算、GPU 训练共用一套编排与运维体系，这对组织的吸引力远大于单点性能。

对大数据引擎的影响是具体的：

- **调度单位是 pod**，声明式的 resource request / limit，隔离由 cgroups 保证，比 YARN 严格。
- **弹性伸缩是原生的**：集群自动扩缩容、Pod 优先级与抢占、节点池（按机型区分 CPU 型 / 内存型 / GPU 型）。
- **没有内建的队列概念**，多租户靠 namespace + ResourceQuota + PriorityClass 组合而成，或者外接 Volcano / YuniKorn 这类批处理调度器来补上队列、gang scheduling 与作业级优先级。
- **数据本地性基本放弃**，与对象存储的存算分离天然契合。

Spark 与 Flink 都提供 native Kubernetes 模式，可以直接向 API Server 申请 executor / taskmanager pod。Flink 侧的实践结论是 [Application 模式](/docs/CS/Framework/Flink/Deployment.md)最适合生产（每个作业一个独立集群、main 方法在集群侧执行），session 模式适合开发调试。

## Mesos: A Closed Chapter

Mesos 的两级调度（framework 先拿到资源 offer 再自行决定接受与否）在学术界很有影响力，也让 [Spark](/docs/CS/Framework/Spark/Spark.md) 早期得以快速支持多种集群管理器。但它在产业上的位置已经被 Kubernetes 完全取代：**Spark 4.0 已移除 Mesos 支持**。新建系统不应再考虑它；存量系统迁移的直接目标通常是 Kubernetes。

## Comparison

| 维度 | YARN | Kubernetes | Mesos |
| :--- | :--- | :--- | :--- |
| 资源单位 | Container | Pod | Offer（资源邀约） |
| 调度模型 | 集中式 RM 分配 | 声明式 + 控制器调谐 | 两级调度（offer） |
| 多租户 | 队列（Capacity / Fair）成熟 | namespace + quota，需额外组件补队列 | 弱 |
| 弹性伸缩 | 弱 | 原生（HPA / Cluster Autoscaler） | 弱 |
| 批处理语义 | 好 | 需 Volcano / YuniKorn 补（gang scheduling） | 一般 |
| 生态与运维 | 绑定 Hadoop | 全基础设施统一 | 已边缘化 |
| 当下定位 | 存量 Hadoop 集群 | 新建默认 | 不应新用 |

## Deployment Modes and Their Scheduling Impact

引擎的部署模式决定了调度层看到的是什么，这一点常被忽略：

- **Session / 共享集群模式**：一个长期运行的集群承接多个作业。资源利用率高（作业间复用），但**隔离差**——一个作业打爆集群会拖累所有作业，且故障域共享。
- **Per-job / Application 模式**：每个作业起独立集群，跑完释放。隔离好、故障域独立，代价是每次启动都有申请资源与拉起进程的开销。
- 交互式与短查询偏好前者（要快），长跑的批作业偏好后者（要稳）。

调度层的选型因此不能只看引擎：还要看**作业形态混合度**。全是长跑批作业，YARN 的 Capacity 队列足够；批、流、在线、GPU 混布，Kubernetes 的价值才真正体现出来。

## Links

- [BigData](/docs/CS/BigData/BigData.md)
- [Yarn](/docs/CS/Framework/Hadoop/Yarn.md)
- [Spark Deploy](/docs/CS/Framework/Spark/Deploy.md)
- [Flink Deployment](/docs/CS/Framework/Flink/Deployment.md)
- [Hadoop](/docs/CS/Framework/Hadoop/Hadoop.md)

## References

1. [Apache Hadoop YARN](https://hadoop.apache.org/docs/stable/hadoop-yarn/hadoop-yarn-site/YARN.html)
2. [Apache Hadoop Capacity Scheduler](https://hadoop.apache.org/docs/stable/hadoop-yarn/hadoop-yarn-site/CapacityScheduler.html)
3. [Running Apache Flink on Kubernetes](https://flink.apache.org/)
4. [Running Spark on Kubernetes](https://spark.apache.org/docs/latest/running-on-kubernetes.html)
5. [Kubernetes Resource Management for Pods and Containers](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
