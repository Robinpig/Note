## Introduction

XXL-JOB 是一个分布式任务调度平台，核心设计目标是开发迅速、学习简单、轻量级、易扩展。它把调度行为抽象形成"调度中心"公共平台，而平台自身并不承担业务逻辑；将任务抽象成分散的 JobHandler，交由"执行器"统一管理——"调度"和"任务"两部分相互解耦，提高系统整体稳定性和扩展性。

存储只支持 MySQL；调度中心支持集群部署，集群情况下各节点务必连接同一个 MySQL 实例；如果 MySQL 做主从，调度中心集群节点务必强制走主库。建表 SQL 位置：

```
/xxl-job/doc/db/tables_xxl_job.sql
```

```xml
<!-- http://repo1.maven.org/maven2/com/xuxueli/xxl-job-core/ -->
<dependency>
    <groupId>com.xuxueli</groupId>
    <artifactId>xxl-job-core</artifactId>
    <version>${最新稳定版本}</version>
</dependency>
```

本篇是总览：架构、核心概念与策略族谱。执行器侧与调度中心侧的源码级展开分别见 [xxl-job-executor](/docs/CS/Framework/Job/xxl-job-executor.md) 与 [xxl-job-scheduler](/docs/CS/Framework/Job/xxl-job-scheduler.md)。

## Architecture

参考官方文档：

![](https://www.xuxueli.com/doc/static/xxl-job/images/img_Qohm.png)

- **调度模块（调度中心）**：负责管理调度信息，按照调度配置发出调度请求，自身不承担业务代码。调度系统与任务解耦，提高了系统可用性和稳定性，同时调度系统性能不再受限于任务模块；支持可视化、简单且动态的管理调度信息，包括任务新建、更新、删除、GLUE 开发和任务报警等，所有操作实时生效，同时支持监控调度结果以及执行日志，支持执行器 Failover。
- **执行模块（执行器）**：负责接收调度请求并执行任务逻辑。任务模块专注于任务的执行等操作，开发和维护更加简单高效；接收"调度中心"的执行请求、终止请求和日志请求等。

## Core Concepts

### Registration and Discovery

执行器启动后内嵌 Netty 服务（默认端口 9999），周期性向调度中心注册（`ExecutorRegistryThread`，间隔 `BEAT_TIMEOUT` 30s）。调度中心维护 `xxl_job_group` / `xxl_job_registry` 两张表：前者是人工维护的执行器列表（AppName → 地址簿），后者是自动注册的在线机器表。路由时若地址簿非空用手工录入的地址，为空则用注册表自动发现的在线机器——这给了"固定机器清单"与"弹性扩缩"两种接入方式。

### Route Strategy

路由策略决定调度请求发往哪个执行器。当前版本共 10 种（`ExecutorRouteStrategyEnum`，每种挂一个 `ExecutorRouter` 策略实现）：

| 策略 | 语义 |
| :--- | :--- |
| `FIRST` | 固定选择第一个地址 |
| `LAST` | 固定选择最后一个地址 |
| `ROUND` | 轮询 |
| `RANDOM` | 随机 |
| `CONSISTENT_HASH` | 按任务参数一致性哈希，同参数落到同机 |
| `LEAST_FREQUENTLY_USED` | 最不经常使用（LFU） |
| `LEAST_RECENTLY_USED` | 最近最少使用（LRU） |
| `FAILOVER` | 故障转移：按顺序心跳检测，第一个存活的当选 |
| `BUSYOVER` | 忙碌转移：跳过忙碌节点，按顺序找空闲节点 |
| `SHARDING_BROADCAST` | 分片广播：所有机器都触发，各执一个分片（不走 router） |

### Block Strategy

阻塞处理策略是"调度过于密集、执行器来不及处理"时的行为约定，共三种生效策略（`ExecutorBlockStrategyEnum`；`CONCURRENT_EXECUTION` 并行执行在源码中已被注释废弃）：

| 策略 | 语义 |
| :--- | :--- |
| `SERIAL_EXECUTION`（默认） | 单机串行：同一 Job 的触发进同一队列顺序执行 |
| `DISCARD_LATER` | 丢弃后续调度：运行中则直接拒绝本次触发 |
| `COVER_EARLY` | 覆盖之前调度：kill 掉运行中的旧线程，立即执行本次 |

### Misfire Strategy

调度过期策略即 misfire：调度中心错过触发时刻的补偿处理。策略枚举（`MisfireStrategyEnum`）经 `MisfireHandler` SPI 落地，共两种：`DO_NOTHING`（忽略，直接计算下次触发时间）与 `FIRE_ONCE_NOW`（立即补偿触发一次）。过期判定阈值是预读窗口 5s（`PRE_READ_MS`）——过期超 5s 走忽略、5s 内立即补一次，细节见 [xxl-job-scheduler](/docs/CS/Framework/Job/xxl-job-scheduler.md)。

### GLUE

GLUE 是 XXL-JOB 的在线代码能力：任务逻辑以 Groovy/Shell/Python/PowerShell 等源码形式存在调度中心（`xxl_job_glue` 表），执行时由执行器拉取、经 `GlueFactory` 编译装载。业务代码迭代不再需要发版执行器。3.5.0 起新增执行器维度的 GLUE 模式开关（`xxl.job.executor.glueenabled`）。

### Trigger Types

触发策略覆盖常见调度语义：CRON 触发、固定间隔触发、固定延时触发、API（事件）触发、人工触发、父子任务触发。

## Version Evolution

版本基线为 **v3.5.0**（2026-10-09 发布）。几个划代节点：

- **2.x**：功能主体（调度中心 + 执行器 + GLUE + 路由/阻塞/misfire 策略族），本系列笔记的源码摘录即以此时代为准。
- **3.0.0**（2025-02）：数据模型与配置体系重构。
- **3.5.0**（2026-10）：OpenAPI 能力增强（任务增删改查、启停、触发全流程可编程）；AccessToken 从全局废弃、改为**执行器维度隔离**（`xxl_job_group.access_token`，OpenAPI 通讯协议随之适配，调度中心与执行器需一并升级）；`xxl_job_group.app_name` 加唯一索引、`title` 字段统一改名 `name`；`xxl_job_log` 加 `alarm_status` 索引；修复调度中心 Tab XSS 问题。源码结构上，misfire 与 route 的策略类已从 `xxl-job-core` 移至 `xxl-job-admin` 的 `business/scheduler` 包下，`ShardingUtil` 标记 deprecated。

## Links

- [xxl-job-executor](/docs/CS/Framework/Job/xxl-job-executor.md)
- [xxl-job-scheduler](/docs/CS/Framework/Job/xxl-job-scheduler.md)
- [Job](/docs/CS/Framework/Job/Job.md)
- [Task](/docs/CS/Framework/Spring/Task.md)
- [Scheduled Task](/docs/CS/SE/Scheduled_Task.md)

## References

- [XXL-JOB 官方文档](http://www.xuxueli.com/xxl-job/)
- [XXL-JOB GitHub](https://github.com/xuxueli/xxl-job)
