## Introduction

[Flowable](https://www.flowable.com/open-source) 是当前 Java 生态主流的轻量工作流引擎，2016 年由 **原 Activiti 核心团队**（Tijs Rademakers 等）从 Activiti 分出，全面支持 BPMN 2.0，并扩展出 CMMN（案例管理）、DMN（决策表）与 Event Registry。Open Source 社区版为 **Apache 2.0**；Flowable Work / Engage 为商业版（建模器、案例平台等需授权）。

## Version Baseline

- **开源主线 7.x**：7.0.0 于 2023-09 发布，要求 **Spring Boot 3 / Java 17 / Jakarta EE**（彻底弃用 `javax.*`）。7.x 做了一轮"减肥"——**移除表单引擎、内容引擎、Mule、JMS、传统异步历史**，专注 BPMN / CMMN / DMN / Event-Registry 四大内核，jar 体积下降约 40%。
- **平台侧日期版本**：自 2024 起 Flowable 平台采用日期版本号（2025.2、2026.1），引入 Agentic Case Platform、MCP 双向集成等商业能力。
- Flowable 6.x 仍有大量企业存量（Spring Boot 2.x / Java 8）。补写时以 flowable.com 发布页复核最新开源 tag，不要写死补丁号。

## Architecture

`ProcessEngine` 是总入口，按职责拆成若干 Service：

| Service | 职责 |
| :--- | :--- |
| `RepositoryService` | 部署 BPMN/CMMN/DMN、查询流程定义、挂起/激活 |
| `RuntimeService` | 启动流程实例、读写流程变量、触发消息/信号事件 |
| `TaskService` | 用户任务待办查询、认领、完成、委派 |
| `HistoryService` | 查询历史轨迹（审批记录、变量快照、活动实例） |
| `ManagementService` | 作业（Job）管理、异步执行器控制 |
| `IdentityService` | 用户/组（ACT_ID_*）管理 |
| `FormService` | 表单数据（7.x 后弱化） |

表结构沿用 Activiti 的 `ACT_` 前缀，这是它最显著的运维特征：

- `ACT_RE_*`（repository）：流程/案例/决策定义，部署后长期存在。
- `ACT_RU_*`（runtime）：运行时状态，**流程结束即删除**——这是与历史表分离的关键设计。
- `ACT_HI_*`（history）：历史轨迹，永久保留（受 `history-level` 控制：none/activity/audit/full）。
- `ACT_ID_*`（identity）：用户、组、成员关系。
- `ACT_GE_*`（general）：通用数据（如二进制资源 `ACT_GE_BYTEARRAY`）。

## Async and Job Executor

异步服务任务、定时器、异步历史事件由 **Job Executor** 处理：

- 定时扫描 `ACT_RU_JOB` 表执行到期作业；**排他作业（exclusive job）** 保证集群环境下同一流程实例的 job 单线程、只执行一次（靠数据库行锁）。
- 作业失败按重试次数退避，最终进入死信表 `ACT_RU_DEADLETTER_JOB`；超时未触发进 `ACT_RU_TIMER_JOB`，被挂起进 `ACT_RU_SUSPENDED_JOB`，历史型异步作业进 `ACT_RU_HISTORY_JOB`。
- 7.x 默认开启 `async-history-enabled`（批量异步写历史，降低主流程 RT）。

## Spring Boot Integration

`flowable-spring-boot-starter-process` 自动装配 `ProcessEngine` 及全部 Service Bean，开箱即用：

```yaml
flowable:
  database-schema-update: true      # 首次自动建 43 张表
  history-level: audit              # none / activity / audit / full
  async-history-enabled: true       # 7.x 默认批量异步历史
```

- 服务任务可用 `flowable:delegateExpression="${myBean}"` 挂 Spring Bean，业务实现 `JavaDelegate`。
- 暴露原生 REST（Jakarta 9 规范，OpenAPI 3）：`GET /process-definitions`、`POST /runtime/process-instances`、`GET /runtime/tasks`、`POST /runtime/tasks/{id}`。

```java
runtimeService.startProcessInstanceByKey("expense", vars);          // 发起
Task task = taskService.createTaskQuery().taskAssignee(uid).singleResult();
taskService.complete(task.getId(), Map.of("approved", true));        // 审批通过，自动走条件网关
```

## Listeners

`ExecutionListener` / `TaskListener` 在节点创建、赋值、完成等生命周期切入，常用于埋点、通知、自动赋值：

- ExecutionListener：`start` / `end` / `take`（连线）事件。
- TaskListener：`create` / `assignment` / `complete` / `delete` 事件。

## Links

- [Workflow (BPMN Engines 枢纽)](/docs/CS/Framework/Workflow/Workflow.md)
- [Camunda](/docs/CS/Framework/Workflow/Camunda.md)
- [Activiti](/docs/CS/Framework/Workflow/Activiti.md)
- [Workflow (SE 概念)](/docs/CS/SE/Workflow.md)

## References

1. [Flowable Open Source Documentation](https://www.flowable.com/open-source/docs)
2. [BPMN 2.0 Specification](https://www.omg.org/spec/BPMN/2.0.2/)
