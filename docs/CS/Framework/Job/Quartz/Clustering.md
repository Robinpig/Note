## Introduction

Quartz 的集群能力经**共享数据库的 JDBC-JobStore**（`JobStoreTX` 或 `JobStoreCMT`）实现：集群中每个节点连同一个数据库，调度决策靠 DB 行锁竞争完成。它同时带来高可用（fail-over）与可扩展性（load balancing），但理解它的前提是接受一个事实——**Quartz 集群没有独立的协调服务，数据库就是它的协调服务**。本页讲清锁表语义、抢占与均衡、失效转移、misfire 恢复，以及官方明确列出的使用禁区。

## How Clustering Works

开启集群只需把 `org.quartz.jobStore.isClustered` 设为 `true`，集群中每个实例使用同一份 `quartz.properties`。允许的差异仅两项：线程池大小、`org.quartz.scheduler.instanceId`。每个节点的 instanceId 必须唯一，最省事的做法是把它设为 `AUTO`，由 Quartz 启动时自动生成。

集群的行为特征：

- **依赖数据库**：集群只在使用 JDBC-JobStore（`JobStoreTX` / `JobStoreCMT`）时可用，本质是各节点共享同一套表。
- **负载均衡自动发生**：每个节点尽可能快地触发任务。Trigger 的触发时刻到来时，**第一个抢到它（对其加锁）的节点**就是执行它的节点。
- **互斥执行**：每次触发只有一个节点执行。不一定是同一个节点——繁忙调度器（大量 Trigger）下接近随机，稀疏调度器（少量 Trigger）下偏向同一节点。
- **失效转移**：某节点在执行任务途中崩溃，其他节点检测到该状况，并识别出数据库中"在该失败节点上正在进行"的作业。标记了 recovery 属性（JobDetail 上的 "requests recovery"）的作业会由存活节点重新执行；未标记的作业直接被释放，等下次相关 Trigger 触发时再跑。
- **分区扩展**：集群特性最适合横向扩展**长时运行或 CPU 密集型作业**（把负载分摊到多节点）。若要扩展到上千个短作业（如 1 秒级），应考虑按作业集合分区，用多个独立 Scheduler（包括多个集群化 Scheduler 做 HA）分别承载。集群依赖一把集群级锁，节点越多竞争越劣——**超过约三个节点后，性能随数据库能力下降**。

## Locking Semantics

`QRTZ_LOCKS` 表是集群的全部协调机制：`StdRowLockSemaphore` 在关键路径上执行 `SELECT * FROM QRTZ_LOCKS WHERE SCHED_NAME = ? AND LOCK_NAME = ? FOR UPDATE`，锁行不存在时先按需 INSERT 再抢。以当前源码（2.5.x `main`）为准，**实际生效的锁只有两类**（`JobStoreSupport.java:86-88` 定义，`executeInNonManagedTXLock(lockName, ...)` 统一入口）：

| 锁名 | 保护的操作 |
| :--- | :--- |
| `TRIGGER_ACCESS` | 触发路径：读取 Trigger、抢占下次触发、`triggerJob` |
| `STATE_ACCESS` | Trigger 状态读写：触发前后改状态、misfire 处理改状态 |

> [!NOTE]
>
> 老文档常写 `QRTZ_LOCKS` 预置五行（`TRIGGER_ACCESS` / `JOB_ACCESS` / `CALENDAR` / `STATE_ACCESS` / `MISFIRE`），那是 1.x 时代的形态。当前源码里 `LOCK_JOB_ACCESS` 只剩一行注释（`JobStoreSupport.java:3282`），`CALENDAR` 与 `MISFIRE` 锁不再单独出现——协调被收敛进 `TRIGGER_ACCESS` + `STATE_ACCESS`。判断"现在实际是什么行为"要看锁的消费方，这是又一个"文档存在 ≠ 当前生效"的实例。

作为对照，XXL-JOB 的调度中心用一张 `xxl_job_lock` 表的**单行锁**（`schedule_lock`）串行化整个扫描-触发事务（`select * from xxl_job_lock where lock_name = 'schedule_lock' for update`），粒度更粗但实现更简单；ElasticJob 则完全不用 DB 锁，靠 ZooKeeper 临时节点与选举协调。三种协调底座的选择，本质是"数据库锁 / ZK 协调 / 无协调"的路线差异。

抢占式锁带来两个直接后果：**一**，触发决策的延迟取决于 DB 行锁竞争，数据库抖动会直接传导成调度延迟；**二**，节点负载分布取决于谁抢到锁，天然不保证均衡——这正是 XXL-JOB 在对比文档里反复批评 Quartz 的点（"抢占式获取 DB 锁……节点负载悬殊非常大"）。

## Misfire and Recovery

misfire 指 Trigger 的触发时刻已过而未被及时处理，常见原因有三：服务重启；调度线程被阻塞、线程耗尽；上次调度持续阻塞，下次调度被错过。

Quartz 的 misfire 处理由 `MisfireHandler` 线程统一执行（它是启动序列第 6 步），按 Trigger 上设置的 misfire 指令动作，常用指令包括：

- `MISFIRE_INSTRUCTION_FIRE_ONCE_NOW`：立即补触发一次，之后按原计划继续。
- `MISFIRE_INSTRUCTION_DO_NOTHING`：放弃本次过期触发，更新到下次触发时间。
- `MISFIRE_INSTRUCTION_SMART_POLICY`（CronTrigger 默认）：由 Trigger 根据自身语义智能决策，对 CronTrigger 等价于"立即补一次"。

恢复（recovery）是另一条独立路径：节点崩溃时正在执行的作业，若 JobDetail 设置了 `requestsRecovery`，会被其他节点检测到并重新执行；未设置的作业被释放。**恢复只覆盖"执行中崩溃"，misfire 只覆盖"没来得及触发"**，两者互补，别混为一谈。

## Constraints

官方文档明确列出的禁区，每一条都对应一类线上事故：

- **时钟必须同步**：集群跑在不同机器上时，必须有时钟同步服务（daemon）高频对表，**节点间时钟差必须在一秒以内**。Quartz 用本地时间比较触发时刻，时钟漂移直接造成误触发或漏触发。
- **非集群实例禁止连同一套表**：绝不对着其他实例正在（`start()` 过的）使用的同一套表启动一个非集群化实例——会导致严重数据损坏，且必然出现行为错乱。
- **节点数上限**：集群级锁的竞争随节点数恶化，约三个节点以上收益递减，规模化请走上文的分区方案。

## Example

Spring Boot + JDBC JobStore 集群的最小配置：

```properties
spring.quartz.job-store-type=jdbc
spring.quartz.jdbc.initialize-schema=never
# cluster
spring.quartz.properties.org.quartz.jobStore.isClustered=true
spring.quartz.properties.org.quartz.jobStore.clusterCheckinInterval=20000
spring.quartz.properties.org.quartz.scheduler.instanceId=AUTO
```

`clusterCheckinInterval` 是节点向 `QRTZ_SCHEDULER_STATE` 表汇报心跳的间隔，失效检测的判定时长约是其数倍；调小它加快故障发现，但增加 DB 写入。

## Links

- [Quartz](/docs/CS/Framework/Job/Quartz.md)
- [xxl-job](/docs/CS/Framework/Job/xxl-job.md)
- [ElasticJob](/docs/CS/Framework/Job/ElasticJob.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)

## References

- [Quartz Configuration Reference](http://www.quartz-scheduler.org/documentation/2.4.0-SNAPSHOT/configuration.html)
- [Quartz Scheduler Tutorial - Clustering](http://www.quartz-scheduler.org/documentation/quartz-2.4.0-SNAPSHOT/tutorials/tutorial-lesson-11.html)
