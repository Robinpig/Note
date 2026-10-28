## Introduction

工作流（Workflow）是 SchedulerX 里编排 Job 的 **DAG**：控制台拖拽节点、连线定义依赖，工作流本身作为一个可被调度（Cron 或 API 触发）的实体存在。它解决的是"先跑 A，A 成功后并行跑 B 和 C，都成功再跑 D"这类依赖问题——如果用多个 Cron 任务互相触发来实现，系统会迅速变成一团乱麻。本页讲清工作流的触发语义、数据传递与运维操作。父级见 [ScheduleX](/docs/CS/Framework/Job/ScheduleX.md)。

## Trigger Semantics

三条规则决定了工作流与单任务的边界：

- **工作流中的 Job 没有独立调度时间**，跟随工作流的时间开始调度。想让某个 Job 自己按 cron 跑，就不该放进工作流。
- **工作流至少要 2 个 Job 且存在依赖关系**；只有 1 个 Job 时请直接用任务管理。
- **支持跨应用编排**——可以把不同应用下的任务编排进同一个工作流。

触发方式有两种：配 Cron 表达式定时触发，或通过 API 触发。

## Data Passing

上游把执行结果作为输出，下游从 `JobContext` 读上游数据：

```java
// 上游：把结果放进 ProcessResult
@Override
public ProcessResult process(JobContext context) throws Exception {
    return new ProcessResult(true, String.valueOf(1));   // result ≤ 1000 Byte
}

// 下游：读所有父节点的数据
@Override
public ProcessResult process(JobContext context) throws Exception {
    List<JobInstanceData> upstreamDatas = context.getUpstreamData();
    int sum = 0;
    for (JobInstanceData data : upstreamDatas) {
        // data.getJobName() / data.getData()
        sum += Integer.valueOf(data.getData());
    }
    return new ProcessResult(true, String.valueOf(sum));
}
```

关键点：

- `JobContext.getUpstreamData()` 返回的是 **List**——一个节点可能有多个父节点。
- `result` 的**长度限制是 1000 字节而非字符数**，含中文很容易超限，超限任务直接失败。
- **分布式 Java 任务要用 MapReduce 模型做数据传递**（在 `reduce` 里返回结果）。
- 自 **SDK 1.14.2** 起，`JobContext` 还能获取**工作流参数**（服务端 2026-08-05 同步上线）。

> [!WARNING]
>
> 官方「工作流调度」页面至今仍写着"当前只有 Java 任务支持数据传输"，但服务端 2026-03-20 的发布记录中已有"脚本任务支持上下游数据传递（需 Agent 更新到 1.13.5 及以上）"。**文档滞后于产品**：判断能否用，看 Agent 版本而不是看那句限制说明。

## Operations on Workflow Instances

近年产品迭代集中在"失败之后怎么办"，这也是工作流运维的真实痛点：

| 能力 | 上线时间 | 说明 |
| :--- | :--- | :--- |
| 已完成节点重跑自身 / 重跑自身及下游 | 2025-10-29 | 局部重跑，不必整条重来 |
| 失败节点跳过 | 2025-10-29 | 阻塞时让下游继续 |
| 工作流中的任务可禁用 | 2026-07-30 | 禁用后该节点被跳过 |
| 工作流支持按状态保留历史记录 | 2026-03-20 | 历史留存策略 |
| 一键导入工作流（自动新建或更新任务） | 2026-09-16 | 迁移与复用 |
| 画布坐标不丢失、基本信息与 DAG 编辑分离 | 2026-08-05 | 编辑体验 |
| 工作流参数（SDK ≥ 1.14.2） | 2026-08-05 | 参数化工作流 |

可观测性方面，**工作流实例图**是专业版能力（基础版不支持）；专业版还保存最近 60 天的历史执行归档记录并支持模糊关键字查询（基础版只显示最近 30 条）。

## Script Variables in Workflows

XXL-JOB 版与脚本任务在工作流里有自己的变量语法（来源：MSE 任务调度 XXL-JOB 版工作流文档）：

```bash
#!/bin/bash
# 系统变量
echo "System schedule time: ${system.schedule.time}"
echo "System data time:     ${system.data.time}"
echo "System data date:     ${system.biz.curdate}"
echo "Workflow Instance ID: ${system.workflow.instance.id}"
# 自定义变量：向下游传递
echo "#{setValue(var1=hello)}"
echo "#{setResult(5050)}"
```

自定义变量需在工作流节点的"自定义参数"里声明（含变量名与类型），否则 `setValue` 的赋值只在当前节点内生效，不会向下游传递。

## Design Trade-offs

与专用编排系统（如 [DolphinScheduler](/docs/CS/Framework/Job/DolphinScheduler.md)）相比，SchedulerX 的工作流定位是**调度平台自带的轻量编排**：

- 优势：与任务、报警、日志服务同一套体系，跨应用编排无需额外系统，任务本身可复用。
- 边界：节点类型受 JobType 约束，数据传递受 1000 字节限制，重刷数据只支持天级别；真正的大数据管道（Spark/Flink/DataX 步骤编排）应该交给 DolphinScheduler 或 DataWorks，而不是塞进调度器的工作流里。

## Links

- [ScheduleX](/docs/CS/Framework/Job/ScheduleX.md)
- [Job Types](/docs/CS/Framework/Job/ScheduleX/Job_Types.md)
- [Timing](/docs/CS/Framework/Job/ScheduleX/Timing.md)
- [Operations](/docs/CS/Framework/Job/ScheduleX/Operations.md)
- [DolphinScheduler](/docs/CS/Framework/Job/DolphinScheduler.md)

## References

- [工作流调度（SchedulerX 版 / Serverless）](https://help.aliyun.com/zh/schedulerx/schedulerx-serverless/user-guide/use-workflows-to-orchestrate-jobs)
- [创建工作流并使用 DAG 编排任务（XXL-JOB 版脚本变量）](https://help.aliyun.com/zh/schedulerx/schedulerx-xxljob/user-guide/workflow-process-management)
- [服务端发布记录](https://help.aliyun.com/zh/document_detail/2950302.html)
- [Java SDK release notes](https://www.alibabacloud.com/help/en/schedulerx/product-overview/java-sdk-release-notes)
