## Introduction

本文覆盖 DolphinScheduler 3.4.3 的**定时触发（Quartz）**、**告警**与**部署/存储/版本基线**。核心结论：Quartz 仅作为定时器，`QRTZ_*` 表持久化 trigger；触发时 3.4.x 改为**经 RPC 直接唤醒 Master**（`WorkflowScheduleTriggerRequest`），不再像老版那样往 `t_ds_command` 写 `SCHEDULE` 命令；告警是独立的 Alert Server，SPI 化插件；元数据存储三套 schema 切换。

## Quartz Scheduling

`scheduler-api` 定义 `SchedulerApi`，实现在 `dolphinscheduler-scheduler-plugin/dolphinscheduler-scheduler-quartz`（Quartz `2.3.2`，`job-store-type: jdbc`，持久化到 `QRTZ_*` 表）。

### Trigger → RPC

`ProcessScheduleTask extends QuartzJobBean`（`scheduler/quartz/ProcessScheduleTask.java:46`）是 Quartz 真正执行的 Job。`executeInternal`（`ProcessScheduleTask.java:59`）在被触发时：

1. 读 `QuartzJobData`（projectId / scheduleId）；
2. 查 `Schedule`，若已删除或 `OFFLINE` 则删 job；
3. 通过 `IWorkflowControlClient.workflowInstanceController.workflowScheduleTrigger(WorkflowScheduleTriggerRequest)` **经 RPC 直接调用 Master** 创建工作流实例（`ProcessScheduleTask.java:28-29`、`:55`）。

> 与老版本差异：老版 Quartz Job 会 `INSERT` 一条 `CommandType.SCHEDULE` 到 `t_ds_command`，由 Master 轮询消费；3.4.x 的 `CommandType` 枚举已无 `SCHEDULE`（见 `common/enums/CommandType.java`），定时触发走 RPC 直连，延迟更低。

### Missed Fire Policy (3.4.3 / DSIP-107)

`ScheduleMissedFirePolicy`（`common/enums/`，三值）控制「调度器宕机/积压后如何补触发」：

| 策略 | 行为 |
|------|------|
| `SKIP_MISSED` | 跳过所有错过的时间点 |
| `FIRE_ONCE_NOW` | 只补触发一次 |
| `FIRE_ALL_MISSED` | 补触发所有错过的点（**默认**，`CronScheduleBuilderFactory.java:31` 当 policy 为 null 时取此值） |

`CronScheduleBuilderFactory.getFactory(policy)`（`scheduler/quartz/CronScheduleBuilderFactory.java:29`）按策略返回 `FireOnceNowCronScheduleBuilderFactory` / `FireAllMissedCronScheduleBuilderFactory`，在 `QuartzCornTriggerBuilder.java:84` 构建 trigger 时应用。

## Alert

告警是独立进程 `AlertServer`（`dolphinscheduler-alert/.../AlertServer.java`，`@SpringBootApplication`），配置（`dolphinscheduler-alert-server/.../application.yaml`）：

- `server.port: 50053`（HTTP 管理端口）
- `alert.port: 50052`（RPC 接收端口，Master/API 经 `AlertClient` 把告警请求发到这里）

### Alert SPI

与任务插件同构：`AlertChannel`（`alert/api/AlertChannel.java`）、`AlertChannelFactory`（`alert/api/AlertChannelFactory.java`）、`AlertPluginManager`（`alert/plugin/AlertPluginManager.java`）按 `@AutoService` 加载。内置 14 种插件（`dolphinscheduler-alert-plugins/`）：

`email` `dingtalk` `feishu` `wechat` `slack` `telegram` `webexteams` `http` `pagerduty` `script` `prometheus` `aliyunVoice` `sagemaker`(sagemaker 告警) 以及聚合模块 `dolphinscheduler-alert-all`。告警实例配置存 `t_ds_alert_plugin_instance`，告警记录存 `t_ds_alert`，发送状态存 `t_ds_alert_send_status`。

> 注意：3.4.x 告警从 Master 内嵌**剥离为独立 Alert Server + HA 选主**（`/nodes/alert-server` + `/nodes/alert-server-ha-leader`），多 Alert 实例通过 Registry 选主避免重复发送。

## API Server and UI

- **API Server**：`dolphinscheduler-api`，`server.port: 12345`（`application.yaml:19`）。承担 UI 后端、鉴权（PASSWORD / OAuth2 / LDAP / OIDC 可配）、项目管理、资源/数据源、写 `t_ds_command`、Python Gateway 等。
- **Web UI**：独立模块 `dolphinscheduler-ui`，技术栈 **Vue 3.2.39 + Vite 6.4.2 + TypeScript 4.8.3 + @vueuse/core 9.2.0**（`package.json`）。

## Deployment and Ports

默认端口汇总（生产 profile，来自各模块 `application.yaml`）：

| 角色 | 端口 | 配置 key |
|------|------|---------|
| API Server | 12345 | `server.port` |
| Master RPC | 5678 | `master.listen-port` |
| Worker RPC | 1234 | `worker.listen-port` |
| Alert RPC / HTTP | 50052 / 50053 | `alert.port` / `server.port` |
| Python Gateway 服务端 / Python 侧 | 25333 / 25334 | `python-gateway.gateway-server-port` / `python-port` |

- 部署形态：`deploy/` 下有 docker / kubernetes(helm) / terraform 等；`dolphinscheduler-dist` 产出二进制包；`dolphinscheduler-standalone-server` 是单机一键包（默认 `registry.type=jdbc` + H2，便于演示）。
- 数据库：元数据存储默认 MySQL / PostgreSQL，standalone 用 H2（`application.yaml:22` `active: h2`）；生产 `registry.type=zookeeper`。

## Database Schema

`dolphinscheduler-dao/src/main/resources/sql/` 提供三套等价 schema：`dolphinscheduler_h2.sql` / `dolphinscheduler_mysql.sql` / `dolphinscheduler_postgresql.sql`，外加 `upgrade/`（版本升级脚本）与 `soft_version`。核心表（约 58 张，含 Quartz 的 `QRTZ_*` 11 张）：

| 类别 | 表 |
|------|----|
| 触发/命令 | `t_ds_command`、`t_ds_serial_command`、`t_ds_error_command` |
| 定义 | `t_ds_workflow_definition`(+`_log`)、`t_ds_task_definition`(+`_log`)、`t_ds_workflow_task_relation`(+`_log`)、`t_ds_schedules` |
| 实例 | `t_ds_workflow_instance`、`t_ds_task_instance`、`t_ds_task_instance_context`、`t_ds_relation_workflow_instance` |
| 资源/租户/用户 | `t_ds_project`、`t_ds_tenant`、`t_ds_user`、`t_ds_datasource`、`t_ds_resources`、`t_ds_environment`、`t_ds_worker_group`、`t_ds_queue` |
| 任务组/告警 | `t_ds_task_group`、`t_ds_task_group_queue`、`t_ds_alert`、`t_ds_alert_plugin_instance`、`t_ds_alert_send_status` |
| 扩展 | `t_ds_k8s`(+`_namespace`)、`t_ds_plugin_define`、`t_ds_audit_log`、`t_ds_cluster`、`t_ds_fav_task`、`t_ds_relation_sub_workflow` |
| Registry(JDBC 实现) | `t_ds_jdbc_registry_data`、`t_ds_jdbc_registry_lock`、`t_ds_jdbc_registry_client_heartbeat`、`t_ds_jdbc_registry_data_change_event` |
| 定时(Quartz) | `QRTZ_JOB_DETAILS`、`QRTZ_TRIGGERS`、`QRTZ_CRON_TRIGGERS`、`QRTZ_FIRED_TRIGGERS`、`QRTZ_LOCKS` 等 |

## Version Baseline (3.4.3)

来自根 `pom.xml` 与 `dolphinscheduler-bom/pom.xml`：

| 组件 | 版本 |
|------|------|
| DolphinScheduler | 3.4.3（2026-09-08 发布） |
| Java（编译目标） | 1.8 |
| Spring Boot | 2.7.11 |
| Netty | 4.1.53.Final |
| Quartz | 2.3.2 |
| Apache Curator | 5.5.0（备选 profile 4.3.0） |
| Apache ZooKeeper | 3.8.3（备选 profile 3.4.14） |
| MyBatis-Plus / Druid | BOM 托管（连接池 Druid） |
| gRPC / protobuf | `io.grpc`（部分插件与 Python Gateway 使用） |

## Links
- [DolphinScheduler](/docs/CS/Framework/Job/DolphinScheduler)
- [DolphinScheduler Master Engine](/docs/CS/Framework/Job/DolphinScheduler/Master.md)
- [DolphinScheduler Registry and Failover](/docs/CS/Framework/Job/DolphinScheduler/Registry_Failover.md)
- [Quartz](/docs/CS/Framework/Job/Quartz.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)

## References

- [apache/dolphinscheduler @ 3.4.3](https://github.com/apache/dolphinscheduler/releases/tag/3.4.3)
- 源码模块：`dolphinscheduler-scheduler-plugin/`、`dolphinscheduler-alert/`、`dolphinscheduler-api/`、`dolphinscheduler-dao/`、`dolphinscheduler-ui/`
