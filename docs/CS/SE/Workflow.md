## Introduction

工作流引擎（Workflow Engine）解决的是"**流程逻辑硬编码**"问题：审批、订单状态机、风控流程等业务的步骤、分支、会签、回退经常变化，如果全写在代码里，每次改动都要发版。工作流引擎把流程定义从代码中抽离为可配置的**流程模型**（BPMN 2.0 XML / JSON），由引擎负责节点流转、条件网关、任务分配、持久化与历史查询，业务代码只写每个节点的具体处理。

核心概念：流程定义（Process Definition）→ 流程实例（Process Instance）→ 执行流（Execution，含分支 token）→ 用户任务（UserTask，产生待办 Task）/ 服务任务（ServiceTask，自动执行）→ 网关（排他 Exclusive `XOR`、并行 Parallel `AND`、包含 Inclusive `OR`）。

## 典型使用场景与判断

值得上工作流引擎的信号：流程节点多且顺序常变、需要可视化配置与审批轨迹、有会签/加签/驳回/委派/超时升级、需要流程级别的事务与补偿。不值得的信号：只是简单的三态状态流转——此时用一个枚举 + 状态机（Spring StateMachine/Squirrel）更轻，引入引擎反而是过度设计。

## Flowable

[Flowable](https://www.flowable.com/open-source) 是当前 Java 生态主流的轻量工作流引擎，从 Activiti 分叉而来，同一批核心作者，全面支持 BPMN 2.0，并扩展出 CMMN（案例管理）、DMN（决策表）。

- 架构：流程定义部署为 BPMN XML（表 `ACT_RE_*`），运行时状态写 `ACT_RU_*`（流程结束即删除），历史写 `ACT_HI_*`；`ACT_ID_*` 为身份表。大量 `ACT_` 表是它最显著的运维特征。
- 异步执行：Job Executor 定时扫 `ACT_RU_JOB` 表执行异步服务任务/定时器，配合排他模式保证集群下单实例只执行一次；死信任务进 `ACT_RU_DEADLETTER_JOB`。
- 集成方式：与 Spring Boot  starter 集成，`RuntimeService` 启动流程、`TaskService` 办理待办、`HistoryService` 查轨迹；服务任务可用 `flowable:delegateExpression` 挂 Spring Bean。
- 监听器：ExecutionListener / TaskListener 可在节点创建、完成等生命周期切入，用于埋点与通知。

```java
runtimeService.startProcessInstanceByKey("expense", vars);          // 发起
Task task = taskService.createTaskQuery().taskAssignee(uid).singleResult();
taskService.complete(task.getId(), Map.of("approved", true));        // 审批通过，自动走条件网关
```

## 与相关概念的区分

| 概念 | 职责 | 例子 |
|------|------|------|
| 工作流/BPM | 人工任务为主的长流程编排，强调审批与轨迹 | Flowable、Camunda、Activiti |
| 状态机 | 单对象的有限状态迁移与守卫条件 | Spring StateMachine、Cola StateMachine |
| 分布式编排 | 微服务调用编排、补偿事务 | [Seata](/docs/CS/Framework/Seata/Seata.md) Saga、Camunda Zeebe、Temporal |
| 规则引擎 | 条件→动作的决策逻辑外置 | Drools、DMN、LiteFlow（侧重轻量组件编排） |
| 任务调度 | 定时/依赖触发的批处理 DAG | Airflow、DolphinScheduler |

注意区分"业务流程"与"数据一致性流程"：跨服务最终一致性的 Saga 编排虽然也画成流程图，但关注的是补偿语义而不是人工审批，不要混用产品。

## Links

- [DDD](/docs/CS/SE/DDD.md)
- [Transaction](/docs/CS/SE/Transaction.md)
- [SystemDesign](/docs/CS/SE/SystemDesign.md)

## References

1. [Flowable Open Source Documentation](https://www.flowable.com/open-source/docs)
2. [BPMN 2.0 Specification](https://www.omg.org/spec/BPMN/2.0.2/)
