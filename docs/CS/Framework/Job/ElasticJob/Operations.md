# Operations

## Introduction

ElasticJob 的运维面由"独立管控端 + 动态配置 API + 原生镜像元数据"三块组成。本文聚焦上线与运维关注点：`3.0.5` 的 ElasticJob-UI 版本陷阱、`lifecycle` 动态配置、GraalVM 原生镜像支持，以及版本与 CVE 事实。配置与节点相关的运行时行为见 [Registry Center](/docs/CS/Framework/Job/ElasticJob/RegistryCenter.md)。

## ElasticJob-UI

ElasticJob-UI 是独立发布线的可视化管控端，提供作业管控、执行历史追踪、注册中心管理。关键陷阱：

> [!WARNING]
>
> **UI 与框架版本不同步**。框架已到 3.0.5（2026-02），UI 最新仍是 **3.0.2**（2022-10）。二者协议可能不完全对齐，升级框架时不要默认"UI 也跟着升"——应单独核对 UI 的兼容版本，否则可能出现管控端读不到新版本节点结构的问题。

UI 与框架是两套独立 artifact、独立发版节奏，部署时需手动对齐。

## Dynamic Configuration (lifecycle)

`lifecycle` 模块（`elasticjob-lifecycle`）提供运行时的动态配置能力：无需重启应用即可修改作业配置（cron、分片数、参数等），变更经 ZK `config` 节点监听实时下发到各节点。其对外能力即"Operation API"，由 `restful` 模块以 REST 形式暴露，ElasticJob-UI 正是它的前端消费者。

3.0.5 起，`lifecycle` 支持在 **GraalVM Native Image** 中动态配置作业；`bootstrap` 内置 GraalVM Reachability Metadata，使作业在原生镜像下仍可被动态注册与调度。

## Registry Center Connectivity

3.0.5 允许 `ZookeeperConfiguration` 跳过 **Ensemble Tracker**，以便在 Kubernetes 中连接启用 HA 的 ZooKeeper 集群（避免原生 Ensemble 探测与 K8s 服务发现冲突）。这是容器化部署时的常见适配点。

## GraalVM and Build Baseline

- `reachability-metadata` 模块为 GraalVM 原生镜像提供可达性元数据，`bootstrap` 已内置引用；
- 3.0.5 支持 **OpenJDK 22 / 23 / 24** 构建；运行要求 **Java 8+**（向下兼容旧运行时）。

## Version Facts

- 当前基线 **3.0.5**（2026-02-07 发布），是 2.1.5 之后 3.x 线的最新维护版。
- 3.0.5 安全修复三连：
  - **CVE-2025-25193**（Curator 相关）；
  - **CVE-2024-47535**（Apache Commons IO 相关）；
  - **CVE-2024-22259**（Spring 相关）。
  
  从更早版本升级时应优先核对这三项。
- 3.0.5 其他变更：Kernel 重构 Lambda 作业类的识别方式；移除并不存在的 `elasticjob-tracing-api` 与 `elasticjob-error-handler-spi` 模块声明；修复 `OneOffJobBootstrap` 在 Spring Boot Starter 下不可用的问题；内部 Quartz 升至 2.4.0。

## Links

- [ElasticJob](/docs/CS/Framework/Job/ElasticJob.md) — 枢纽：版本基线与演进
- [Registry Center](/docs/CS/Framework/Job/ElasticJob/RegistryCenter.md) — `config` 节点与动态配置下发
- [Job Types](/docs/CS/Framework/Job/ElasticJob/Job_Types.md) — `elasticjob-spring-boot-starter` 与 `@ElasticJobConfiguration`
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md) — 注册中心底座与 HA 部署

## References

- [ElasticJob 3.0.5 Release](https://github.com/apache/shardingsphere-elasticjob/releases/tag/3.0.5)
- [ElasticJob Downloads](https://shardingsphere.apache.org/elasticjob/current/cn/downloads/)
- [ElasticJob-UI (独立发版线)](https://github.com/apache/shardingsphere-elasticjob/tree/3.0.5/elasticjob-ui)
