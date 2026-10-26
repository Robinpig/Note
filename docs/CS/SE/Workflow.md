## Introduction

工作流引擎（Workflow Engine）解决的是"**流程逻辑硬编码**"问题：审批、订单状态机、风控流程等业务的步骤、分支、会签、回退经常变化，如果全写在代码里，每次改动都要发版。工作流引擎把流程定义从代码中抽离为可配置的**流程模型**（BPMN 2.0 XML / JSON），由引擎负责节点流转、条件网关、任务分配、持久化与历史查询，业务代码只写每个节点的具体处理。

核心概念：流程定义（Process Definition）→ 流程实例（Process Instance）→ 执行流（Execution，含分支 token）→ 用户任务（UserTask，产生待办 Task）/ 服务任务（ServiceTask，自动执行）→ 网关（排他 Exclusive `XOR`、并行 Parallel `AND`、包含 Inclusive `OR`）。

## Typical Use Cases and Decision Criteria

值得上工作流引擎的信号：流程节点多且顺序常变、需要可视化配置与审批轨迹、有会签/加签/驳回/委派/超时升级、需要流程级别的事务与补偿。不值得的信号：只是简单的三态状态流转——此时用一个枚举 + 状态机（Spring StateMachine/Squirrel）更轻，引入引擎反而是过度设计。

## Engine Implementations

具体引擎的实现机制、表结构、Spring Boot 集成与代码示例已拆分到框架层：[Workflow (BPMN Engines)](/docs/CS/Framework/Workflow/Workflow.md) 枢纽对比 **Flowable / Camunda / Activiti** 三者（共同祖先 Activiti 5、版本基线、架构代际、许可证），并链接各自的实现分册：

- [Flowable](/docs/CS/Framework/Workflow/Flowable.md)：轻量嵌入式、Apache 2.0、BPMN+CMMN+DMN 一把梭，国内社区大。
- [Camunda](/docs/CS/Framework/Workflow/Camunda.md)：**双线**——Camunda 7（嵌入式+RDBMS+ACT_ 表+Apache 2.0）与 Camunda 8/Zeebe（云原生、事件溯源、Raft、gRPC、source-available 许可证）。
- [Activiti](/docs/CS/Framework/Workflow/Activiti.md)：三者共同祖先，Apache 2.0，拆为 activiti-core / activiti-cloud，但社区活跃度与标准覆盖弱于前两者。

## Distinction from Related Concepts

| 概念 | 职责 | 例子 |
|------|------|------|
| 工作流/BPM | 人工任务为主的长流程编排，强调审批与轨迹 | Flowable、Camunda、Activiti |
| 状态机 | 单对象的有限状态迁移与守卫条件 | Spring StateMachine、Cola StateMachine |
| 分布式编排 | 微服务调用编排、补偿事务 | [Seata](/docs/CS/Framework/Seata/Seata.md) Saga、Camunda Zeebe、Temporal |
| 规则引擎 | 条件→动作的决策逻辑外置 | Drools、DMN、LiteFlow（侧重轻量组件编排） |
| 任务调度 | 定时/依赖触发的批处理 DAG | Airflow、DolphinScheduler |

注意区分"业务流程"与"数据一致性流程"：跨服务最终一致性的 Saga 编排虽然也画成流程图，但关注的是补偿语义而不是人工审批，不要混用产品。

## Links

- [Workflow (BPMN Engines)](/docs/CS/Framework/Workflow/Workflow.md)
- [DDD](/docs/CS/SE/DDD.md)
- [Transaction](/docs/CS/SE/Transaction.md)
- [SystemDesign](/docs/CS/SE/SystemDesign.md)
- [Scheduled Task](/docs/CS/SE/Scheduled_Task.md)

## References

1. [BPMN 2.0 Specification](https://www.omg.org/spec/BPMN/2.0.2/)
