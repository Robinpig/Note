## Introduction

"什么时候触发"在 SchedulerX 里被拆成三件互相独立的事：**时间类型**（按什么表达式算下一次）、**日历与时区**（在什么日/什么时区上算）、**数据时间**（这次跑的是哪一天的数据）。三者叠加后才是任务真正被触发的时刻与语义。本页按这个顺序展开。父级见 [ScheduleX](/docs/CS/Framework/Job/ScheduleX.md)。

## Time Types

控制台与官方产品页口径下共四种时间类型：

| 时间类型 | 语义 | 精度 | 适用场景 |
| :--- | :--- | :--- | :--- |
| `cron` | Unix Crontab 表达式 | 分钟级，**不支持秒级** | 绝大多数定时场景 |
| `fixed_rate` | 固定频率轮询 | **不支持秒级** | 弥补 cron 的短板：cron 的间隔必须被 60 整除，无法表达"每 40 分钟一次" |
| `second_delay` | 上次**跑完**之后再隔 N 秒 | 秒级（可切毫秒） | 实时性要求高的业务，如间隔 10 秒的轮询 |
| `one_time` | 指定时刻跑一次 | — | 一次性任务（如"11 月 11 日 0 点执行一次"） |

三条容易踩的事实：

- **`second_delay` 的"延迟"是相对上次结束时刻**，不是相对上次开始时刻——它天然避免了任务重叠，但也意味着执行耗时会计入周期。
- **秒级与毫秒级的开关在客户端**：`setEnableSecondDelayCycleIntervalMs(true)` 后，控制台上 `second_delay` 配置的单位由秒变为毫秒（默认 false）。
- **`one_time` 跑完自动销毁，不保留任何历史记录**。要排查就得先开日志服务（保留最近 2 周执行日志）。这是"一次性任务跑完在哪看历史记录"这个问题的标准答案：看不到，除非提前开了日志。

另外，除定时触发外还有两类触发源：**控制台手工触发**与 **OpenAPI 触发**；Go SDK 自 2026-08 起 `JobContext` 可拿 `triggerType`，业务代码因此能区分自己是被 cron 触发还是被人工重跑触发。

## Calendar and Time Zone

- **日历**：内置多种日历，也支持自定义导入。典型用法是金融场景——"只在交易日执行"。
- **时区**：任务可按国家所在时区执行，适用于跨国业务。时区与日历是独立的两层：前者决定"几点算几点"，后者决定"这一天算不算"。

## Data Time and Backfill

任务可以携带**数据状态**。创建任务时填写数据偏移后，运行时刻不变，但 `context.getDataTime()` 返回偏移后的时刻：

```text
每天 00:30 运行，但处理前一天的数据 → 数据偏移 -1 小时
运行时刻不变（00:30），context.getDataTime() = 前一天 23:30
```

这条设计的价值在于**重刷数据（backfill）**：当业务变更（新增字段）或发现历史数据错误时，可重刷某些任务/工作流过去一段时间的数据，**只支持天级别**，每个新实例带不同的数据时间。换句话说，数据时间让"重跑"与"跑哪一天的数据"解耦——这也是数据仓库类任务必须配数据偏移的原因。

## Routing: Machines, Labels, and Units

触发时刻确定后，"落到哪台机器"由分发引擎决定：

- **指定机器**：任务可绑定到特定机器。机器下线则无法调度（对应报错 `No worker available for`）。
- **标签路由**（专业版）：客户端 `setLabel()` 打标签，任务管理指定标签执行，用于灰度、压测。专业版还可配置"无标签任务能否调度到有标签的 Worker 上"。
- **单元化围栏**（客户端参数）：`setEnableUnits()` / `setEnableSites()` 白名单、`setDisableUnits()` / `setDisableSites()` 黑名单，白名单优先。

## Missed Triggers and Expiration

SchedulerX 的高可靠靠"主备 + At-least-once + failover + 定期轮检"保证，但并不意味着"每个时刻一定被触发一次"。实践中最常见的两类漏跑：

- **分钟级任务（间隔 1 分钟）某一时刻没跑**：官方明确说明很可能是**服务端发布**引起的，一般对业务影响很小。判断路径是先看应用管理里机器列表是否存在、是否全部繁忙，再看任务是否指定了已下线的机器。
- **任务长期未触发**：可配置**任务过期时间**，过期后默认自动禁用（2026-09-16 服务端能力）。这是防"僵尸任务"的手段，而不是补偿机制。

与"漏跑"相对的另一端是**故意不再触发**：禁用任务时支持优雅下线——当前正在执行会继续执行，下一次不再调度（2026-03-20 服务端能力）。

## Scheduling Cost

时间类型的选择会直接体现在账单上（专业版按任务调度 CU 计费）：

- 单机任务：单次调度 CU = 1。
- 非单机任务：单次调度 CU = 单次调度的 Worker 数量。
- **`second_delay` 类型每分钟只算一次调度 CU**；而 `cron` / `fixed_rate` 按调度频率逐次计算。

即：秒级任务被刻意定价得更便宜，但"每次调度拉多少台机器"是实打实的成本项。把广播任务挂到几十台 Worker 上时，CU 消耗是线性放大的。

## Links

- [ScheduleX](/docs/CS/Framework/Job/ScheduleX.md)
- [Job Types](/docs/CS/Framework/Job/ScheduleX/Job_Types.md)
- [Workflow](/docs/CS/Framework/Job/ScheduleX/Workflow.md)
- [Operations](/docs/CS/Framework/Job/ScheduleX/Operations.md)

## References

- [分布式调度任务功能全面解析（时间类型 / 日历 / 时区）](https://helpcdn.aliyun.com/zh/edas/function)
- [阿里云专有云 EDAS SchedulerX 技术白皮书（数据时间 / 重刷数据）](http://apsara-doc.oss-cn-hangzhou.aliyuncs.com/apsara-pdf/enterprise/v_3_10_0_20200506/edas/zh/schedulerx-apsarastack-technical-whitepaper.pdf)
- [服务端发布记录](https://help.aliyun.com/zh/document_detail/2950302.html)
- [计费概述（调度 CU 计量口径）](https://help.aliyun.com/zh/schedulerx/schedulerx-serverless/product-overview/billing-1/)
- [SchedulerxWorker 配置参数说明](https://help.aliyun.com/zh/mse/user-guide/schedulerxworker-parameters)
