## Introduction

[Activiti](https://www.activiti.org/) 是三者中**最古老**的一个：2010 年由 Alfresco 发起，是 Java 生态 BPMN 2.0 开源的拓荒者。后来的 Flowable（2016）与 Camunda 7（2013）都从 Activiti 5 分出，因此 Activiti 是它们的共同祖先，表前缀 `ACT_*` 也起源于此。当前许可证为 **Apache 2.0**。

## Version Baseline

- **Activiti 8.x**：要求 **Java 17 / Spring Boot 3**（8.0.0 约 2023 年发布，版本线持续演进至 8.x；activiti-cloud 同步 8.x）。补写时以官方仓库 tag 复核最新补丁号。
- 历史上 Activiti 6 → 7 是架构大改（引入云原生拆分），升级并不平滑；Activiti 7 起明确"云原生"战略，拆分为 `activiti-core`（引擎）与 `activiti-cloud`（云原生组件集）。

## Architecture

引擎同样是 `ProcessEngine` + 一组 Service（`RepositoryService` / `RuntimeService` / `TaskService` / `HistoryService` / `IdentityService` / `ManagementService`），API 形态与 Flowable、Camunda 7 一脉相承——这也是三者代码互相"看得懂"的原因。表结构沿用 `ACT_RE_*` / `ACT_RU_*` / `ACT_HI_*` / `ACT_ID_*` / `ACT_GE_*`。

## activiti-core vs activiti-cloud

Activiti 7/8 把项目拆成两半：

- **activiti-core**：传统嵌入式 BPMN 引擎，直接落 JDBC 关系库，适合单体/嵌入式审批流。
- **activiti-cloud**：面向 Kubernetes / Spring Cloud 的云原生构建块——Runtime Bundle（不可变、可扩展的流程/决策运行时）、Audit Service、Query Service、Cloud Connectors、Application Service、Notification Service。本质是把引擎能力拆成可在分布式基础设施上独立伸缩的服务。

## Reality Check

> [!WARNING]
>
> 选型 Activiti 要正视几件"二手描述普遍比现实乐观"的事实：
>
> 1. **核心开发者已出走 Flowable**——社区活跃度显著下降，新特性与生态跟进慢于 Flowable / Camunda。
> 2. **标准覆盖不全**：历史上核心只做 BPMN 2.0，**CMMN 与 DMN 支持弱**（DMN 多依赖外部决策服务），不像 Flowable 一把梭 BPMN+CMMN+DMN。
> 3. **Spring Boot 3 / Jakarta EE 适配滞后**：相比 Flowable 7 一上来就 SB3/Java17，Activiti 的现代化节奏慢半拍。
> 4. GitHub Star 数（历史累计最多）是**历史遗产**，不代表当前生命力。

结论：Activiti 多见于历史/遗留项目延续，或已深度绑定 `activiti-cloud` 体系的团队；新项目除非有强约束，否则社区与标准覆盖上 Flowable / Camunda 7 更稳。

## Code Example

API 与 Flowable / Camunda 7 同源，迁移成本最低：

```java
ProcessEngine engine = ProcessEngines.getDefaultProcessEngine();
engine.getRuntimeService().startProcessInstanceByKey("expense", variables);
Task task = engine.getTaskService().createTaskQuery().taskAssignee(uid).singleResult();
engine.getTaskService().complete(task.getId());
```

activiti-cloud 场景下流程启停改走 Runtime Bundle 的 REST/gRPC，而非直接持有 `ProcessEngine`。

## Links

- [Workflow (BPMN Engines 枢纽)](/docs/CS/Framework/Workflow/Workflow.md)
- [Flowable](/docs/CS/Framework/Workflow/Flowable.md)
- [Camunda](/docs/CS/Framework/Workflow/Camunda.md)
- [Workflow (SE 概念)](/docs/CS/SE/Workflow.md)

## References

1. [Activiti Developer Guide](https://www.activiti.org/)
2. [Activiti Cloud Documentation](https://activiti.gitbook.io/activiti-7-developers-guide/)
3. [BPMN 2.0 Specification](https://www.omg.org/spec/BPMN/2.0.2/)
