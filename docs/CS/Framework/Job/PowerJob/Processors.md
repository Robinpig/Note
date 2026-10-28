## Introduction

处理器（Processor）是 PowerJob 任务的"执行体"，生态接入方式决定了它好不好落地到业务系统。本文汇总处理器类型、`powerjob-worker` 系列接入组件，以及版本基线事实；其中版本基线以 Web 核实的 **v5.1.7（2026-10-01）** 为准。

## Processor Types

- **Java**：分 Spring Bean、内置类、外置类三种加载方式，是主力的执行形态；
- **Shell / Python**：官方处理器库 `powerjob-official-processors` 提供 SQL、Shell、Python 等开箱实现（5.1.5 修复了 SQL processor 结果日志累积上一行值的问题）；
- **多语言**：规划经 HTTP 开放，非 Java 运行时通过 HTTP 触发器接入。

## Worker and Client

| 组件 | 角色 | 接入方式 |
| :--- | :--- | :--- |
| `powerjob-worker` | 执行端：拉取任务、执行处理器、上报状态 | 被 starter 包装 |
| `powerjob-worker-spring-boot-starter` | 业务侧零配置接入 | Spring Boot starter |
| `powerjob-worker-agent` | 容器化部署，支持随机端口（`port = -1` 时由系统分配，见 `#1102`） | 独立 agent 进程 |
| `powerjob-client` | 嵌入业务的 OpenAPI 客户端（触发任务、查询实例） | 业务系统直接依赖 |

Maven 坐标已迁移到 `tech.powerjob:powerjob-*`，**4.x 起从旧的 `com.github.kfcfans` groupId 切换**（老项目升级需注意依赖坐标）。

## Version Facts

- **基线 v5.1.7**（2026-10-01，Web 核实 Releases / Maven Central）：小功能 bugfix 版；修复 DAILY_TIME_INTERVAL 首次触发边界、workflow 子实例 Job 定义保留与冷加载元数据恢复、SpEL 应用类型解析、MU 连接关闭竞态、Worker 锁中断等。
- **升级兼容策略**：5.1.x 保持 Java 8、协议、鉴权行为、配置与数据库 schema 不变；**Server 可单独升级，不强依赖 Client/Worker/Console 同步升级**——只有要用 MU 传输或 Worker 侧修复时才需要升级对应组件。
- **MU 通讯协议**：5.1.x 重磅特性，但标注 **BETA**，仅建议开发环境使用；本机 4.3.9 源码中 `powerjob-remote` 仅有 `AkkaTransporter` 与 `VertxTransporter`（HTTP）两种实现，**无任何 MU**，证实 MU 是 5.x 新增（详见枢纽页 Architecture）。

## Ecosystem Links

- 官方文档（语雀）：<https://www.yuque.com/powerjob/guidence/intro>
- 在线试用：<https://try.powerjob.tech>

## 5.x 待确认

- `powerjob-official-processors` 在 5.1.7 的具体处理器清单（SQL / Shell / Python 之外是否新增），需回 5.1.7 源码或文档确认。
- MU 协议的服务端 `Transporter` 实现类的真实包路径与启用开关，需回 5.1.7 `powerjob-remote` 确认。

## Links

- [PowerJob](/docs/CS/Framework/Job/PowerJob.md)
- [Execution Modes](/docs/CS/Framework/Job/PowerJob/Execution_Modes.md)
- [Workflow](/docs/CS/Framework/Job/PowerJob/Workflow.md)
- [Job](/docs/CS/Framework/Job/Job.md)

## References

- [PowerJob GitHub](https://github.com/PowerJob/PowerJob)
- [PowerJob Releases](https://github.com/PowerJob/PowerJob/releases)
- [PowerJob 官方文档](https://www.yuque.com/powerjob/guidence/intro)
