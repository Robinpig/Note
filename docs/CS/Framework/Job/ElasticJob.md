## Introduction

[ElasticJob](https://shardingsphere.apache.org/elasticjob/current/cn/overview/) 通过弹性调度、资源管控、以及作业治理的功能，打造一个适用于互联网场景的分布式调度解决方案，并通过开放的架构设计，提供多元化的作业生态。它的各个产品使用统一的作业 API，开发者仅需一次开发，即可随意部署。

ElasticJob 的前身是当当网 2014 年开源的 elastic-job，2020 年 5 月 28 日捐赠成为 [Apache ShardingSphere](https://shardingsphere.apache.org/) 子项目。它与 XXL-JOB 代表分布式调度的两条对立路线：**XXL-JOB 把调度集中到平台，ElasticJob 把调度摊回每个节点**——没有调度中心，每个引入依赖的应用节点自带 Quartz 调度器与执行器，节点间通过 ZooKeeper 就"谁执行哪一片"达成共识。

## Architecture

使用 ElasticJob 能够让开发工程师不再担心任务的线性吞吐量提升等非功能需求，使他们能够更加专注于面向业务编码设计；同时，它也能够解放运维工程师，使他们不必再担心任务的可用性和相关管理需求，只通过轻松增加服务节点即可达到自动化运维的目的。

ElasticJob 定位为轻量级无中心化解决方案，使用 jar 的形式提供分布式任务的协调服务。

![](https://shardingsphere.apache.org/elasticjob/current/img/architecture/elasticjob_lite.png)

### Decentralization and ZooKeeper

去中心化的全部协调经 ZooKeeper 完成。以源码（`kernel/.../internal/storage/JobNodePath.java`）为准，ZK 上的节点结构为：

| ZK 路径（`/{namespace}/{jobName}/` 下） | 用途 |
| :--- | :--- |
| `config` | 作业配置（cron、分片数、分片参数等），变更实时下发 |
| `instances/{instanceId}` | 实例注册（临时节点，实例下线自动删除） |
| `servers/{instanceId}` | 受控服务器（作业服务器）列表，可置 ENABLED / DISABLED |
| `sharding/{item}/instance` | 分片项 item 归属哪个实例 |
| `leader/election/instance` | 主节点选举（临时节点，leader 崩溃后自动重选） |
| `leader/items`、`leader/latch` | 失效转移：leader 接管故障实例的分片项，latch 为接管屏障 |

**主节点（leader）是去中心化架构里唯一的"临时中心"**：它由 ZK 选举产生，负责失效转移与重新分片的协调；leader 崩溃时临时节点消失，其余节点自动重新选举——无中心架构得以成立的关键。反过来，去中心化 ≠ 不依赖任何中心服务：**ZK 就是它的隐性中心**，ZK 集群不可用时，已运行实例照常执行，但实例上下线、重新分片、失效转移全部停摆。选 ElasticJob 的前提是具备 ZK 运维能力（官方要求 ZooKeeper 3.6.0+）。

单机调度底座仍是 Quartz（3.0.5 将内部 Quartz 依赖升级至 2.4.0）：每个节点本地 Quartz 负责按 cron 触发，ZK 只负责"这次触发由谁跑、跑哪片"。

### Sharding and Failover

弹性调度的两个核心机制：

- **分片**：作业按配置切成 N 个分片项，每个分片项携带参数（如 `0=北京,1=上海`），由不同实例各执其一。加节点即重新分片、执行能力随资源线性增长；相同任务经分片参数路由可聚合至相同执行器处理。
- **失效转移**：某实例崩溃，其ZK 临时节点消失，leader 将故障实例的分片项写入失效转移队列（`leader/items`），由存活实例抢 latch 接管——崩溃时正在执行的分片被重跑，未触发的不补。

官方把这类能力归入"作业治理"三件套：**失效转移、错过作业重新执行（misfire）、自诊断修复**。作业间依赖（DAG）在官方功能列表里仍是 TODO 状态——需要工作流编排的应看 DolphinScheduler / PowerJob。

## Evolution: From Two Products to One

2.x 时代 ElasticJob 是双产品：**ElasticJob-Lite**（去中心化 jar 形态）与 **ElasticJob-Cloud**（基于 Mesos 的资源治理 + 容器化执行，中心式）。二者对比如下（历史形态，仅助于理解演进）：

| 维度 | ElasticJob-Lite | ElasticJob-Cloud |
| :--- | :--- | :--- |
| 去中心化 | 是 | 否 |
| 资源分配 | 否 | 是（Mesos） |
| 作业执行 | Daemon | Daemon + Transient |
| 部署依赖 | ZooKeeper | ZooKeeper + Mesos |

Cloud 因使用量不足、依赖过重，社区 2023 年 10 月投票决定移除（PR #2288）；至 **3.0.5 发布时 Cloud 产物已从 Downloads 页消失**，ElasticJob-Lite 更名为 ElasticJob（去 Lite 后缀），Spring Boot starter  artifact 相应从 `elasticjob-lite-spring-boot-starter` 改为 `elasticjob-spring-boot-starter`，动态配置 API 独立为 `elasticjob-lifecycle` 模块。当前仓库模块布局：`api` / `bootstrap` / `kernel` / `lifecycle` / `registry-center` / `restful` / `spring` / `ecosystem` / `reachability-metadata` / `distribution`——**没有 cloud**。

## Operations

- **ElasticJob-UI**：独立发布线的可视化管控端（作业管控、执行历史追踪、注册中心管理），注意它**与框架版本不同步**——框架 3.0.5（2026-02）时 UI 最新仍是 3.0.2（2022-10）。
- **Operation API**：`elasticjob-lifecycle` 模块提供的运行时动态配置能力，3.0.5 起支持在 GraalVM Native Image 中动态配置作业；bootstrap 内置 GraalVM Reachability Metadata。
- **注册中心连通性**：3.0.5 允许 `ZookeeperConfiguration` 跳过 Ensemble Tracker，以便在 Kubernetes 中连接启用 HA 的 ZooKeeper 集群。
- **构建基线**：3.0.5 支持 OpenJDK 22/23/24 构建，运行要求 Java 8+。

## Version Facts

- 当前基线 **3.0.5**（2026-02-07 发布），是 2.1.5 之后 3.x 线的最新维护版。
- 3.0.5 安全修复三连：**CVE-2025-25193**（Curator 相关）、**CVE-2024-47535**（Apache IO 相关）、**CVE-2024-22259**（Spring 相关）；从更早版本升级时应优先核对这三项。
- 3.0.5 其他变更：Kernel 重构 Lambda 作业类的识别方式；移除并不存在的 `elasticjob-tracing-api` 与 `elasticjob-error-handler-spi` 模块声明；修复 `OneOffJobBootstrap` 在 Spring Boot Starter 下不可用的问题；内部 Quartz 升至 2.4.0。

## Comparison with XXL-JOB

| 维度 | ElasticJob | XXL-JOB |
| :--- | :--- | :--- |
| 调度决策 | 节点对等 + ZK 协商 | 调度中心集中决策 |
| 外部依赖 | ZooKeeper | MySQL |
| 执行扩容 | 加分片即扩容 | 加执行器机器 |
| 运维界面 | ElasticJob-UI（独立部署） | 调度中心自带 Web UI |
| 在线改代码 | 无 | GLUE |
| 负载均衡 | 分片天然均匀 | 路由策略决定 |
| 适合场景 | 有 ZK 基础、任务可分片、要弹性伸缩 | 无 ZK、要开箱即用的平台 |

## Links

- [xxl-job](/docs/CS/Framework/Job/xxl-job.md)
- [PowerJob](/docs/CS/Framework/Job/PowerJob.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Quartz](/docs/CS/Framework/Job/Quartz/Quartz.md)
- [Job](/docs/CS/Framework/Job/Job.md)

## References

- [Apache ShardingSphere ElasticJob - Overview](https://shardingsphere.apache.org/elasticjob/current/cn/overview/)
- [Apache ShardingSphere ElasticJob - Downloads](https://shardingsphere.apache.org/elasticjob/current/cn/downloads/)
- [Apache ShardingSphere ElasticJob GitHub](https://github.com/apache/shardingsphere-elasticjob)
- [Remove the ElasticJob Cloud from ShardingSphere ElasticJob](https://lists.apache.org/thread.html/1k6zkvx9dwf2hq2xbb1ngxyxrhw5rd23)
