## Introduction

任务上线之后，SchedulerX 的问题基本落在四件事上：**它为什么没跑、为什么跑太多次、为什么跑不完、以及跑完之后怎么看**。本页按"流控 → 重试与超时 → 报警与监控 → 日志 → 排障清单"的顺序组织，最后一份清单按报错信息索引，可以直接当字典查。父级见 [ScheduleX](/docs/CS/Framework/Job/ScheduleX.md)。

## Rate Limiting and Priority

SchedulerX 的流控是分层的，每一层管的对象不同：

| 手段 | 管控对象 | 默认值 / 说明 |
| :--- | :--- | :--- |
| 实例并发数（任务级别） | 一个任务同时最多运行多少个实例 | **默认 1**，即上一次跑完才能跑下一次 |
| 单机子任务并发数 | 每台机器同时运行的子任务数 | 分布式任务流控 |
| 全局子任务并发数 | 全局最多同时运行多少子任务 | 走**拉模型**时才有效（子任务集中在 Master），默认 1,000 |
| 任务优先级队列（应用级别） | 一个应用同时最多运行多少个任务 | **可抢占**的优先级队列 |

要点：**"任务并发数 = 1"是默认而非配置错误**，它意味着任务串行；需要并发就必须显式调大。全局并发数只有拉模型才管得住——推模型下每台机器各自分配，没有全局视角。

## Retry and Timeout

- **实例失败自动重试**：高级配置里配次数与间隔（如重试 3 次、每次间隔 30 秒）；**默认重试 0 次、间隔 30 秒**。全部重试仍失败，实例状态才转为失败并报警。
- **子任务失败自动重试**：分布式模型（并行计算 / 内存网格 / 网格计算、分片）的子任务同样支持，也在高级配置里配。
- **超时只有任务级别，没有子任务级别**，可在控制台动态修改。2026-09-16 起**任务超时终止后支持失败自动重试**——之前超时终止与失败重试是两条独立路径。
- **禁用任务支持优雅下线**：正在执行的会跑完，下一次不再调度。

## Alerts and Monitoring

报警类型与近年新增：

- **失败报警 / 超时报警 / 无可用机器报警 / 机器繁忙报警**（后两项 2025-07-29 起支持）；
- **提前结束报警**：任务运行耗时**小于**期望时间也报警（2025-10-29）——用于捕捉"任务提前退出、其实没干活"的隐性故障；
- **通知策略模块**：可对不同的通知渠道设置生效时间段（2025-10-29）。

渠道按版本分档：基础版只有钉钉、邮件；专业版另加短信、电话、企业微信、飞书。

可观测能力同样按版本分档：

| 能力 | 基础版 | 专业版 |
| :--- | :--- | :--- |
| 任务大盘、日志服务 | 支持（日志限流 5 条/秒每任务） | 支持 |
| 查看堆栈 / Tracing / 用户大盘 / 工作流实例图 | 不支持 | 支持 |
| 链路加密、标签路由 | 不支持 | 支持 |

链路追踪方面，除专业版内置的 Tracing 外，还有独立 artifact `schedulerx-plugin-trace-opentelemetry`（最新 1.0.8）走 OpenTelemetry；Go SDK 自 2026-07 起也支持 OTel trace。

## Logs

- 客户端日志默认在 `${user.home}/logs/schedulerx`，核心是 `worker.log`；可用 `-Dschedulerx.log.path=` 改根路径。
- **日志服务（SLS）**：基础版与专业版都支持，但不单独计费，且**每个任务限流每秒 5 条**——高频日志会被丢。
- **`one_time` 任务跑完即销毁、不保留历史记录**；开启日志服务可保留最近 2 周执行日志。专业版另有 60 天内历史执行归档记录查看与模糊关键字搜索。

## Troubleshooting Index

按控制台/日志里出现的报错信息索引。

| 现象 | 原因 | 处理 |
| :--- | :--- | :--- |
| 某个时间点没有调度 | 机器列表为空 / 全部繁忙 / 任务指定了已下线机器 | 先看应用管理的实例列表；分钟级（间隔 1 分钟）任务漏跑很可能是**服务端发布**引起，影响通常很小 |
| `No worker available for` | 客户端配置错误，或指定的 worker 已下线 | 登录 worker 看 `worker.log` |
| `all workers are busy` | 有 worker 的某项指标超过繁忙阈值 | 应用管理 → 查看实例 → 点"繁忙"看是哪个指标超标 |
| 实例停止后仍在执行 | Kill 只中断线程，已运行中的子任务会跑完 | 一般无需处理；要立即结束须在子任务里处理 interrupt 状态 |
| `one_time` 跑完找不到历史记录 | 一次性任务跑完自动销毁，防数据堆积 | 提前开启日志服务 |
| 找不到 JobProcessor / `jobProcessor is null` | bean 未注入、AOP 代理、ClassLoader 不一致等 | 六步排查见 [Client Access](/docs/CS/Framework/Job/ScheduleX/Client_Access.md) |
| `Dispatcher.timeout submit appGroupId xxx` | 应用重启 / FullGC / load 偏高导致提交失败；或客户端版本过低 | 配失败重试、保证实例健康、升级客户端 |
| `ClassNotFoundException` | Processor 类路径不对，或 worker 上根本没这个类 | className 必须是**全路径**；否则检查是否发错包、应用是否连了别人的机器 |
| `jobInstance=xxx don't update progress more than 60s` | worker 被销毁或执行中出 bug，60 秒未同步状态 | 检查执行节点；升级客户端 |
| `java.lang.ExceptionInInitializerError` | `icu4j` 与当前 JDK 版本不匹配 | 剔除 icu4j 或升级到最新版 |
| `task list is empty` | `map()` 传入的子任务列表为空 | 代码里判断为空则正常结束 job |
| `force terminate instance by xx` | 实例被强制停止（用户手动，或执行超时被系统终止） | 属正常现象，排查超时配置 |
| `result size more than 1000 bytes` | `ProcessResult` 的 result 超过 1000 **字节**（中文很容易超） | 缩短 result；较新版本会自动截断 |
| `timeout dispatch return init error` | 子任务分发失败且状态重置也失败 | 升级客户端后重试 |
| `the response is not json object` | HTTP 任务返回值不是 JSON（如 URL 需要鉴权） | 用 curl 验证返回值 |
| `The returned value is different from the expected value` | HTTP 返回值与自定义期望不符 | 同上 |
| `A service call error occurred` | HTTP 响应码与自定义响应码不符 | 同上 |
| `worker not ready for running` | Server 开始提交任务时 worker 尚未初始化完成 | 配置任务失败重试 |
| `xx is still running!` | Server 重复提交（如网络异常） | 可忽略 |
| SDK 日志文件完全不输出 | 日志组件冲突：`log4j-to-slf4j` 或 `log4j-over-slf4j` 在作祟 | 排除桥接包，或只保留一个日志组件 |

排障的通用次序：**先确认应用实例数不为 0（接入是否成功）→ 再看 worker.log（客户端视角）→ 再看控制台实例详情（服务端视角）→ 最后才是抓包和升级客户端**。绝大多数"调度问题"最终都落在接入配置、机器繁忙、业务代码异常三类上。

## Links

- [ScheduleX](/docs/CS/Framework/Job/ScheduleX.md)
- [Job Types](/docs/CS/Framework/Job/ScheduleX/Job_Types.md)
- [Timing](/docs/CS/Framework/Job/ScheduleX/Timing.md)
- [Client Access](/docs/CS/Framework/Job/ScheduleX/Client_Access.md)
- [Architecture](/docs/CS/Framework/Job/ScheduleX/Architecture.md)

## References

- [任务管理（高级配置：重试、并发、超时）](https://help.aliyun.com/zh/document_detail/2673709.html)
- [服务端发布记录](https://help.aliyun.com/zh/document_detail/2950302.html)
- [计费概述（基础版 / 专业版能力差异）](https://help.aliyun.com/zh/schedulerx/schedulerx-serverless/product-overview/billing-1/)
- [Java SDK release notes](https://www.alibabacloud.com/help/en/schedulerx/product-overview/java-sdk-release-notes)
