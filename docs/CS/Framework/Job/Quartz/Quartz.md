## Introduction

[Quartz](http://www.quartz-scheduler.org/) 是一个功能丰富、开源的作业调度库，可以从最小的独立应用到最大的电商系统嵌入几乎任何 Java 应用。Quartz 能创建简单或复杂的调度来执行几十、几百乃至上万个任务；任务被定义为标准 Java 组件，可以执行任何编程实现的行为。Quartz Scheduler 包含众多企业级特性，例如 JTA 事务与集群支持。

理解 Quartz 的关键是接受它的定位：**它是一个库，不是一个平台**。调度器运行在业务进程内，与业务代码同生共死——这带来了零部署成本的优点，也埋下了后面所有问题的种子（调度线程挤占业务线程、DB 锁抢占负载不均、无 UI）。本页讲核心对象模型、Trigger 家族、JobStore 选型与 Spring Boot 集成；集群与持久化的细节在 [Clustering](/docs/CS/Framework/Job/Quartz/Clustering.md)。

## Core Objects

Quartz 的 API 围绕一组"定义-触发-执行"的对象模型展开，全部经 `*Builder` 构造，最终注册进 `Scheduler`。

### JobDetail

传达给定 Job 实例的详细属性。JobDetail 通过 `JobBuilder` 创建。

Quartz **不存储 Job 类的实际实例**，而是允许通过 JobDetail 来定义一个实例。每个 Job 有 name 和 group，二者共同在单个 Scheduler 内唯一标识它。

### Trigger

所有 Trigger 的公共属性基础接口，用 `TriggerBuilder` 实例化具体 Trigger。

Trigger 是 Job 被调度的"机制"。多个 Trigger 可以指向同一个 Job，但一个 Trigger 只能指向一个 Job。Trigger 同样有 name + group 唯一标识。Trigger 可以通过把数据放进自己的 JobDataMap 来向 Job "传递"参数。

Trigger 家族按用途分四类：

| Trigger | 用途 | 关键配置 |
| :--- | :--- | :--- |
| `SimpleTrigger` | 一次性或在某一时刻起按固定间隔重复 N 次 | `startAt` / `repeatCount` / `repeatInterval` |
| `CronTrigger` | 按 Cron 表达式（秒级七段）在日/周/月粒度触发 | `cronScheduleFor` |
| `CalendarIntervalTrigger` | 按日历间隔（如"每 3 个月"）触发，自动跳过不存在的日期 | `interval` / `intervalUnit` |
| `DailyTimeIntervalTrigger` | 每天某时间段内按间隔触发（如工作日 9:00-18:00 每 30 分钟） | `startingDailyAt` / `endingDailyAt` / `interval` |

Cron 表达式为六段或七段（秒 分 时 日 月 周 [年]），特殊字符 `*`、`?`、`-`、`,`、`/`、`L`、`W`、`#` 语义与 Unix cron 大体一致，但**多出秒段且日/周不能同时指定**（其一必须为 `?`）。misfire 指令（如 `withMisfireHandlingInstructionFireOnceNow`）决定触发时刻错过后的补偿行为，见 [Clustering](/docs/CS/Framework/Job/Quartz/Clustering.md) 的 misfire 小节。

### JobDataMap

持有 Job 实例的状态信息。JobDataMap 在 Job 加入 Scheduler 时存储一次；对标注了 `@PersistJobDataAfterExecution` 的作业，每次执行后重新持久化。

JobDataMap 也可以挂在 Trigger 上——同一个 Job 被多个 Trigger 常规复用时，每次触发想喂给 Job 不同的输入数据，就用 Trigger 级的 map。执行时传给 Job 的 `JobExecutionContext` 里还有一个便捷 map，是 Trigger 的 JobDataMap 覆盖在 Job 的 JobDataMap 之上的合并结果。

> [!NOTE]
>
> 2.2.4 起 map 内部维护 dirty 标志，任何增删条目都会置位；但用 `JobDataMap(Map)` 从已有 map 构造新实例时，dirty 标志**不会**继承，直到新实例被修改才置位。

### JobExecutionContext

执行上下文包，在 Job 执行时传给 JobDetail 实例、Trigger 执行完后传给 Trigger。

通过 `getMergedJobDataMap()` 取到的便捷 map 是 JobDetail 的 JobDataMap 与 Trigger 的 JobDataMap 的合并（后者覆盖同名键），因此最佳实践是 Job 的 `execute()` 从这个 map 取数。注意：**不要期望 set 进这个 map 的值会回写到 Job 自己的 JobDataMap**——即使有 `@PersistJobDataAfterExecution`。试图修改合并 map 的内容通常会抛 `IllegalStateException`。

`JobExecutionContext` 也由 `Scheduler.getCurrentlyExecutingJobs()` 返回，与传给正在执行作业的是同一批实例。唯一例外是经 RMI 远程使用 Quartz 时，拿到的是克隆对象，对 Scheduler 和 Job 实例的引用已丢失（JobDetail 的克隆仍可用，只是没有运行中 job 实例的句柄）。

### Scheduler

Quartz Scheduler 的主接口。Scheduler 维护一份 JobDetails 与 Triggers 的注册表——**一旦注册，Scheduler 就负责在关联 Trigger 触发时执行 Job**。

Scheduler 实例由 `SchedulerFactory` 产出；已创建/初始化的 Scheduler 可经同一个 factory 找回复用。创建后 Scheduler 处于 stand-by 模式，必须调 `start()` 才会触发任何 Job。Job 由客户端程序定义（实现 `Job` 接口的类）并经 `scheduleJob(JobDetail, Trigger)` 或 `addJob(JobDetail, boolean)` 注册；Trigger 定义触发规则；已存储的 Job 也可经 `triggerJob(jobName, jobGroup)` 手动触发。客户端还可能关心三类监听器：`JobListener`（作业执行通知）、`TriggerListener`（触发通知）、`SchedulerListener`（调度器事件与错误），经 `ListenerManager` 关联到本地调度器。

启动序列（`SchedulerFactoryBean` → `SchedulerFactory`）：

1. 初始化 `SchedulerFactoryBean`
2. 初始化 `SchedulerFactory`
3. 创建线程池
4. 启动 `SchedulerFactoryBean`
5. `ClusterManager`（集群管理器，仅集群模式）
6. `MisfireHandler`（misfire 任务处理线程）
7. `QuartzSchedulerThread` 置 `paused=false`，开始取 Trigger 执行

## JobStore

JobStore 决定 Trigger 与 Job 的存放位置，也决定了 Quartz 能否集群：

| JobStore | 存储 | 集群 | 说明 |
| :--- | :--- | :--- | :--- |
| `RAMJobStore` | 内存 | 否 | 默认。最快，重启即丢，适合单机纯内存调度 |
| `JobStoreTX` | 关系库 | 是 | 自行管理事务，最常用的集群方案 |
| `JobStoreCMT` | 关系库 | 是（容器管理事务） | 需 J2EE 容器参与事务，应用服务器环境下用 |

集群细节（锁表语义、抢占、失效转移、misfire 恢复）全部在 [Clustering](/docs/CS/Framework/Job/Quartz/Clustering.md) 展开，本页不重复。

## Spring Boot Integration

classpath 上有 Quartz 时，Spring Boot 经 `SchedulerFactoryBean` 抽象自动配置 Scheduler。业务 Job 一般继承 `QuartzJobBean`，把 Spring 的依赖注入能力带进 Job 实例：

```java
package org.springframework.scheduling.quartz;

public abstract class QuartzJobBean implements Job {

    public final void execute(JobExecutionContext context) throws JobExecutionException {
        try {
            BeanWrapper bw = PropertyAccessorFactory.forBeanPropertyAccess(this);
            MutablePropertyValues pvs = new MutablePropertyValues();
            pvs.addPropertyValues(context.getScheduler().getContext());
            pvs.addPropertyValues(context.getMergedJobDataMap());
            bw.setPropertyValues(pvs, true);
        } catch (SchedulerException var4) {
            throw new JobExecutionException(var4);
        }

        this.executeInternal(context);
    }

    protected abstract void executeInternal(JobExecutionContext var1) throws JobExecutionException;
}
```

`execute()` 是 final 的：先把 scheduler context 与合并后的 JobDataMap 的属性注入到 Job bean，再调子类的 `executeInternal()`——这解决了 Quartz 自行实例化 Job 导致 Spring 容器注入失效的问题。注意此时**不会**自动注册 `Executor` bean，Quartz 的线程模型完全由 `spring.quartz.properties` 配置。

```groovy
// build.gradle
implementation 'org.springframework.boot:spring-boot-starter-quartz'
implementation 'org.springframework.boot:spring-boot-starter-jdbc'
implementation group: 'mysql', name: 'mysql-connector-java', version: '8.0.25'
```

```properties
spring.quartz.job-store-type=jdbc
# always run SQL to overwrite DB
spring.quartz.jdbc.initialize-schema=always
spring.datasource.url=jdbc:mysql://xxx.xxx.xxx.xxx/quartz?useUnicode=true&characterEncoding=utf8
spring.datasource.password=****
spring.datasource.username=xxx
```

`spring.quartz.jdbc.initialize-schema=always` 适合开发期自动建表；生产环境应改为 `never` 并手工执行随包发布的 `tables_*.sql`，否则每次重启都会重放 DDL。

## Version Lines

Quartz 目前维护**双版本线**，选错线会直接撞上包名错误：

| 版本线 | 最新版 | Java 基线 | 命名空间 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| 2.4.x | 2.4.1（2025-10） | Java 8 | `javax.*` | 兼容老系统的维护线 |
| 2.5.x | 2.5.2（2025-12） | Java 11+ | `jakarta.*` | 主线；2.5.0 起迁 Jakarta 命名空间 |

2.4.0 的主要变更是构建体系转 Gradle、最低 Java 版本升到 8、第三方依赖（slf4j、HikariCP 等）升级并改为 provided 作用域，同时从 `quartz-jobs` 移除有代码执行风险的 `NativeJob`。2.5.0 迁 Jakarta 命名空间后与 2.4.x **二进制不兼容**，升级须全量回归。当前基准写作时最新为 **2.5.2**。

## Limits

Quartz 不尽如人意的地方（也是平台型框架的立身之本）：

- **问题一**：调用 API 的方式操作任务，不人性化——没有 UI，任务增删改查全靠代码。
- **问题二**：需要持久化业务 `QuartzJobBean` 到底层数据表中，系统侵入性相当严重。
- **问题三**：调度逻辑和 `QuartzJobBean` 耦合在同一个项目中，调度任务数量增多、逻辑加重后，调度系统性能大大受限于业务。
- **问题四**：底层以"抢占式"获取 DB 锁并由抢占成功节点负责运行任务，导致节点负载悬殊非常大；而 XXL-JOB 通过执行器实现"协同分配式"运行任务，充分发挥集群优势，负载各节点均衡。

## Links

- [Clustering](/docs/CS/Framework/Job/Quartz/Clustering.md)
- [xxl-job](/docs/CS/Framework/Job/xxl-job.md)
- [ElasticJob](/docs/CS/Framework/Job/ElasticJob.md)
- [PowerJob](/docs/CS/Framework/Job/PowerJob.md)
- [Task](/docs/CS/Framework/Spring/Task.md)

## References

- [Quartz Configuration Reference](http://www.quartz-scheduler.org/documentation/2.4.0-SNAPSHOT/configuration.html)
- [Spring Boot - Quartz Scheduler](https://docs.spring.io/spring-boot/docs/current/reference/html/features.html#features.quartz)
- [Quartz Downloads](https://quartz-scheduler.org/downloads)
