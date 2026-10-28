## Introduction

BPMN 工作流引擎解决的是"流程逻辑硬编码"问题：审批、订单状态机、风控流程等业务的步骤、分支、会签、回退经常变化，如果全写在代码里，每次改动都要发版。引擎把流程定义从代码中抽离为可配置的**流程模型**（BPMN 2.0 XML），负责节点流转、条件网关、任务分配、持久化与历史查询，业务代码只写每个节点的具体处理。

Java 生态里 **Flowable / Camunda / Activiti** 是三强，三者共享同一祖先——**Activiti 5**（Alfresco 于 2010 年发起的 BPMN 开源项目）。2013 年 Camunda 从中分出形成 Camunda 7；2016 年原 Activiti 核心团队分出形成 Flowable。这条血统的直接后果是：**三者至今都沿用 `ACT_` 表前缀**（repository 表 `ACT_RE_*`、runtime 表 `ACT_RU_*`、history 表 `ACT_HI_*`、identity 表 `ACT_ID_*`、general 表 `ACT_GE_*`），运维上极易混淆。

> [!WARNING]
>
> **Camunda 的"7"和"8"不是同一个引擎的版本升级，而是两套架构**：Camunda 7 是嵌入式 + 关系库的经典引擎（直接读写 `ACT_*` 表）；Camunda 8（Zeebe）是云原生、事件溯源、Raft 共识、无 RDBMS 的分布式引擎。从 7 迁 8 是重新架构流程部署，不是改个版本号。选型时务必先分清代际。

## Shared Concepts

三者的核心抽象一致（术语与 Activiti 5 一脉相承）：

- **Process Definition → Process Instance → Execution（含分支 token）**：定义部署后产生实例，引擎用执行流（token）在节点间推进。
- **UserTask / ServiceTask**：UserTask 产生待办 Task（人工）；ServiceTask 自动执行（Java delegate / 表达式 / 外部 worker）。
- **网关**：排他 `XOR`、并行 `AND`、包含 `OR`（Inclusive），以及事件网关。
- **Job Executor / Timer**：异步服务任务、定时器由后台作业执行器扫描作业表触发。
- **History Service**：流程结束后的轨迹查询（审批记录、变量快照）。

核心概念对比见 [Workflow (SE)](/docs/CS/SE/Workflow.md) 的"与相关概念区分"——工作流/BPM 与状态机（Spring StateMachine）、分布式编排（Seata Saga / Temporal）、规则引擎（Drools/DMN）、任务调度（Quartz/DolphinScheduler）是不同职责，不要混用。

## Three Engine Comparison

| 维度 | Flowable | Camunda | Activiti |
| :--- | :--- | :--- | :--- |
| 起源 | 2016 年从 Activiti 分出（原核心团队） | 2013 年从 Activiti 分出（Camunda 公司） | 2010 年 Alfresco 发起，三者共同祖先 |
| 当前主版本 | 开源 7.x（7.0.0 / 2023-09，Spring Boot 3 / Java 17 / Jakarta）；平台侧改日期版本（2025.2、2026.1） | **双线**：7（7.22 LTS / 2026-04，2025-04 进维护）与 8/Zeebe（8.x / 2026-04 到 8.6 级 GA） | 8.x（Java 17 / Spring Boot 3；8.0.0 ~2023，版本线持续至 8.x） |
| 架构代际 | 嵌入式 + 关系库（`ACT_*` 表） | 7=嵌入式+RDBMS；8=事件溯源 Broker+Raft（无 RDBMS） | 嵌入式 + 关系库（`ACT_*` 表） |
| 状态存储 | JDBC 关系库 | 7=JDBC；8=RocksDB + ES/OS 导出 | JDBC 关系库 |
| 客户端/协议 | Java API / REST | 7=Java/REST；8=gRPC（多语言 worker：Java/Node/C#/Go/Python） | Java API / REST（activiti-cloud 走 Spring Cloud） |
| 标准覆盖 | BPMN 2.0 + CMMN + DMN + Event Registry | BPMN 2.0 + DMN（CMMN 支持有限）；8 有 Connectors 市场 | 核心 BPMN 2.0；历史上 CMMN/DMN 覆盖弱（DMN 多依赖外部决策服务） |
| 许可证 | Open Source 社区版 Apache 2.0；Work/Engage 商业 | 7 社区版 Apache 2.0；**8 为 Camunda Platform License（source-available，非 OSI / 非 Apache 2.0）** | Apache 2.0 |
| 定位 | 轻量嵌入式审批流，国内社区大、文档多 | 7=建模体验最佳（Camunda Modeler）+ Cockpit；8=高吞吐微服务编排 | 历史最久、Star 最多（legacy），云原生 activiti-cloud |

> [!NOTE]
>
> 版本基线是 2026-10 现场核实：Flowable 开源最新稳定线为 7.x，平台侧已改日期版本号，最新开源 tag 以 flowable.com 发布页为准；Camunda 7.22 为 LTS、已进入维护，Camunda 8 是当前主推线；Activiti 主线为 8.x。补写新笔记时以官方发布页/仓库 tag 复核，不要沿用本文写死的补丁号。

## Selection Guidance

- **选 Flowable**：要轻量嵌入 Spring Boot、需要 BPMN+CMMN+DMN 一把梭、Apache 2.0 纯开源、国内资料与社区活跃——审批流 / 工单 / OA 场景最常见。注意其商业建模器（Flowable Design/Work）需授权。
- **选 Camunda 7**：看重建模与可观测性（Camunda Modeler 公认最好用、Cockpit 运维面板），且接受嵌入式 + 关系库的传统架构；社区版 Apache 2.0 可用。
- **选 Camunda 8 / Zeebe**：要云原生、高吞吐、跨语言 worker、水平扩展的微服务编排——但必须接受 **source-available 许可证**（非 OSI 开源）与更高的运维复杂度（自建 Zeebe 集群或买 SaaS）。
- **选 Activiti**：多为历史/遗留项目延续；新项目除非已深度绑定 activiti-cloud 体系，否则社区活跃度与标准覆盖均弱于前两者。

## Links

- [Flowable](/docs/CS/Framework/Workflow/Flowable.md)
- [Camunda](/docs/CS/Framework/Workflow/Camunda.md)
- [Activiti](/docs/CS/Framework/Workflow/Activiti.md)
- [Workflow (SE 概念)](/docs/CS/SE/Workflow.md)
- [Seata (Saga 编排)](/docs/CS/Framework/Seata/Seata.md)

## References

1. [BPMN 2.0 Specification](https://www.omg.org/spec/BPMN/2.0.2/)
2. [Flowable Open Source Documentation](https://www.flowable.com/open-source/docs)
3. [Camunda Platform 8 Documentation](https://docs.camunda.io/)
4. [Activiti Developer Guide](https://www.activiti.org/)
