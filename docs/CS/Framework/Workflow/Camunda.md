## Introduction

Camunda 的工作流产品有**两条架构完全不同的线**，这是选型时第一件要分清的事：

- **Camunda 7（Camunda Platform）**：2013 年从 Activiti 5 分出的经典嵌入式引擎，直接读写 `ACT_*` 关系表，社区版 Apache 2.0。
- **Camunda 8（Zeebe）**：云原生、事件溯源、Raft 共识、无 RDBMS 的分布式引擎，是当前主推线；**许可证为 Camunda Platform License（source-available，非 OSI / 非 Apache 2.0）**。

## Camunda 7 (Camunda Platform)

本质是运行在 JVM 里的 Java 库（`ProcessEngine`），可嵌入 Spring Boot 或作为独立服务（JBoss/Tomcat）部署，流程状态经 JDBC 落关系库（PostgreSQL / MySQL / Oracle / DB2）。

- **核心 Service**（与 Activiti 同源的 API 设计）：`RepositoryService`（部署/查询定义）、`RuntimeService`（启实例/变量/事件）、`TaskService`（用户任务）、`HistoryService`（轨迹）、`IdentityService`、`ManagementService`。
- **表前缀 `ACT_`**：repository `ACT_RE_*`、runtime `ACT_RU_*`、history `ACT_HI_*`、identity `ACT_ID_*`——与 Flowable/Activiti 同源，靠库名/表内容区分。
- **运维三件套（社区版可用）**：Cockpit（监控/流程实例钻取）、Tasklist（人工任务）、Admin；Optimize 为企业版（流程挖掘）。
- **Camunda Modeler**：公认最好用的 BPMN 建模器（桌面端、免费），是 Camunda 7 选型的最大加分项。
- **版本基线**：7.22 为 LTS（2026-04 发布），2025-04 进入维护模式，官方承诺维护到至少 2027；新项目不建议再从 7 起步。

## Camunda 8 (Zeebe)

Zeebe 是独立 Broker 集群，与 Camunda 7 是**两套引擎**，关键差异：

| 维度 | Camunda 7 | Camunda 8 (Zeebe) |
| :--- | :--- | :--- |
| 引擎架构 | 嵌入式 JVM + 关系库 | 分布式 Broker，事件溯源 append-only 日志 |
| 状态存储 | JDBC 关系库（共享 DB） | RocksDB（本地状态）+ 导出到 ES/OS 供 Operate/Optimize |
| 共识/扩展 | 垂直扩展、靠共享库悲观锁 | Raft 分区复制，加 Broker/分区水平扩展，无共享 DB 瓶颈 |
| 通信 | Java API / REST | gRPC（多语言 worker：Java / Node / C# / Go / Python） |
| BPMN 覆盖 | 完整 BPMN 2.0 | BPMN 2.0（子集 + 云原生扩展），早期缺失的高级模式到 8.x 已补齐 |
| 许可证 | Apache 2.0（社区版） | **Camunda Platform License（source-available，非 OSI）** |

- **优势**：水平扩展（生产集群可达数万实例/秒）、跨语言 worker、事件溯源带来 Operate 里的"时间旅行"调试、Connectors 市场（REST/Kafka/邮件/云服务等开箱即用）。
- **代价**：自建 Zeebe 集群的运维复杂度（或买 SaaS）；**失去共享 JDBC 事务一致性**——业务数据与流程状态分别提交，需自行处理最终一致；许可证不再是纯开源，对"必须 Apache 2.0/MIT"的项目是硬约束。

> [!WARNING]
>
> **7 → 8 是迁移不是升级**：底层从关系库事务模型变为事件溯源分区模型，流程部署需重新设计（如去掉强事务依赖、改用 job worker 模式）。不要指望改个版本号就平滑切换。

## DMN

两条线都支持 **DMN**（决策表，FEEL 表达式），可与 BPMN 流程通过 `BusinessRuleTask` 串联，把"条件→动作"的决策逻辑外置。

## Code Example

Camunda 7（API 与 Flowable/Activiti 7 同出一源，迁移成本最低）：

```java
ProcessEngine engine = ProcessEngines.getDefaultProcessEngine();
engine.getRuntimeService().startProcessInstanceByKey("expense", variables);
Task task = engine.getTaskService().createTaskQuery().taskAssignee(uid).singleResult();
engine.getTaskService().complete(task.getId());
```

Camunda 8（Zeebe 通过 gRPC client，worker 拉取任务）：

```java
// 部署与启动
ZeebeClient client = ZeebeClient.newClientBuilder().gatewayAddress("localhost:26500").build();
client.newDeployResourceCommand().addResourceFromClasspath("expense.bpmn").send().join();
client.newCreateInstanceCommand().bpmnProcessId("expense").latestVersion().variables(vars).send().join();

// worker 拉取并完成服务任务
client.newWorkerBuilder().jobType("charge").handler((jobClient, job) -> {
    // 业务逻辑
    jobClient.newCompleteCommand(job.getKey()).variables(result).send().join();
}).open();
```

## Links

- [Workflow (BPMN Engines 枢纽)](/docs/CS/Framework/Workflow/Workflow.md)
- [Flowable](/docs/CS/Framework/Workflow/Flowable.md)
- [Activiti](/docs/CS/Framework/Workflow/Activiti.md)
- [Workflow (SE 概念)](/docs/CS/SE/Workflow.md)

## References

1. [Camunda Platform 8 Documentation](https://docs.camunda.io/)
2. [Camunda Platform 7 Documentation](https://docs.camunda.org/)
3. [Camunda License (source-available)](https://camunda.com/legal/us/licensing/)
