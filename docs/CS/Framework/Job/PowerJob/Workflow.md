## Introduction

PowerJob 原生支持 DAG 工作流（Workflow）：在线配置任务依赖、可视化编排，并支持上下游任务间的数据传递。它与普通任务**共用时间轮与实例体系**——工作流实例的 CRON 触发走 `scheduleCronWorkflow`，子任务仍是普通的 Job 实例。本文以 `powerjob-server/.../core/scheduler/PowerScheduleService.java` 的 `scheduleWorkflowCore` 与 `WorkflowTimingStrategyHandler`（4.3.9）为据，并标注 5.1.7 的工作流修复。

## Workflow Cron Trigger

工作流的定时入口是 `scheduleCronWorkflow()` → `scheduleWorkflowCore(...)`（`PowerScheduleService.java:91`、`:208-241`），与任务调度同构：

1. 查询窗口同样是 `nextTriggerTime <= now + 2 * SCHEDULE_RATE`，按 `MAX_APP_NUM = 10` 分批；
2. **先建实例**：`workflowInstanceManager.create(wfInfo, null, nextTriggerTime, null)`（`:222`）——先落 workflow 实例记录，防止"算出了触发时间却没记录"；
3. **推入时间轮**：`InstanceTimeWheelService.schedule(wfInstanceId, delay, () -> workflowInstanceManager.start(wfInfo, wfInstanceId))`（`:230`）；
4. **刷新下次触发**：`refreshWorkflow(...)`（`:234`）按 `TimeExpressionType.CRON` 算回写。

`WorkflowTimingStrategyHandler`（4.3.9 实存于 `.../scheduler/auxiliary/impl/`）负责工作流实例的 CRON 表达式解析，与普通任务的 `CronTimingStrategyHandler` 是两条独立 handler。

## Data Passing

工作流"上下游数据传递"在源码里体现为 `TaskTracker` 上的 `appendedWfContext` 字段（`powerjob-worker/.../tracker/task/TaskTracker.java`，注释 "追加的工作流上下文数据 @since 2021/02/05`"）：上游节点把数据写入工作流上下文，下游节点在启动时读取，从而串起 DAG 上的数据流。它的载体是 instance 级别的运行上下文，而非任务参数本身。

## Why One-stop

需要"调度 + 编排 + 轻量计算"合一的场景，PowerJob 是四族调度器（Quartz / XXL-JOB / ElasticJob / PowerJob）里**唯一一站式**覆盖的：工作流编排、Map/MapReduce 分布式计算、四种定时策略都内建，无需外接 DolphinScheduler 一类专用编排系统。代价是 Server + Console 的运维体量比 XXL-JOB 略重。

## 5.x 待确认

- **5.1.7 两处工作流修复**：① 冷加载后 workflow 调度元数据丢失；② 子实例的 Job 定义随 workflow 实例保存（更早版本冷加载可能丢子任务定义）。这两条均属 5.x 行为，需回 v5.1.7 源码 (`core/workflow/`) 确认具体实现与受影响版本范围。
- 工作流的 DAG 依赖图解析、环检测、失败重试策略等细节，建议以 5.1.7 源码 `WorkflowInstanceManager` / `DAG` 相关类为准。

## Links

- [PowerJob](/docs/CS/Framework/Job/PowerJob.md)
- [Scheduling](/docs/CS/Framework/Job/PowerJob/Scheduling.md)
- [Execution Modes](/docs/CS/Framework/Job/PowerJob/Execution_Modes.md)
- [Job](/docs/CS/Framework/Job/Job.md)

## References

- [PowerJob GitHub](https://github.com/PowerJob/PowerJob)
- [PowerJob 官方文档](https://www.yuque.com/powerjob/guidence/intro)
