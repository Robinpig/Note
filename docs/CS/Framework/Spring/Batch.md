## Introduction

[Spring Batch](https://spring.io/projects/spring-batch) 是一个轻量级的批处理框架，用来处理**大批量、重复性强、几乎不需要人工介入**的数据任务：日终对账、报表生成、数据迁移、ETL、批量发券、账单结算等。

它解决的不是"怎么写 for 循环"，而是批处理之所以难的那些横切问题：

| 批处理痛点 | Spring Batch 的应对 |
| ---- | ---- |
| 数据量大，内存放不下 | Chunk 分块处理，每读满一批就写一次并提交 |
| 跑到一半崩了要能接着跑 | `JobRepository` 记录读到了第几条，重启后从断点续跑（**Batch 6 起需要额外配置，见下文**） |
| 同一批数据不能重复消费 | `JobInstance` 由 identifying `JobParameters` 唯一标识，跑过的实例拒绝再跑 |
| 脏数据不能中断整批 | `skip` / `retry` 容错策略与阈值控制 |
| 性能不够要并行 | 多线程 step、分区 step、并行 flow |
| 事后要审计 | 每一步的执行时间、读写条数、提交次数都落在元数据表里 |

### 批处理与调度是两回事

这是最容易混淆的一点：**Spring Batch 只负责"跑"，不负责"什么时候跑"**。触发时机由调度负责——可以是 `cron`、`@Scheduled`、K8s CronJob、Jenkins、也可以是外部人工触发。调度部分见 [Spring Task](/docs/CS/Framework/Spring/Task.md?id=schedule)，本文只讲执行侧。

```java
@Scheduled(cron = "0 0 2 * * *")   // 触发：每天凌晨两点
void runDailySettlement() {
    jobOperator.start("settlementJob", new JobParameters());  // 执行：交给 Batch
}
```

### 版本基线

Spring Batch **6.0**（2025-11 GA）是 Boot 4 / Framework 7 一代的配套版本，也是本文的写作基线。它建立在 Framework 7、Spring Data 4、Jakarta EE 11、Jackson 3 之上，Java 17 起步。6.x 对 5.x 有**一批破坏性变更**，网上大量教程（含不少 2025 年之前的）在 Batch 6 上要么编译不过，要么编译通过但行为不对，见本文最后一节。

## 领域模型

Batch 的元数据有一套层层嵌套的身份概念，理解它们的区别是理解"续跑"与"防重"的前提：

| 概念 | 含义 | 类比 |
| ---- | ---- | ---- |
| `Job` | 一份作业的**配置**（由若干 Step 组成的流程） | 类定义 |
| `JobInstance` | 某个 Job 在**一组特定 identifying 参数**下的一次逻辑运行 | `new` 出来的实例 |
| `JobExecution` | 该 JobInstance 的一次实际执行尝试 | 调用方法；失败重试会产生新的 Execution |
| `Step` | Job 的一个执行阶段 | 方法 |
| `StepExecution` | Step 的一次执行，挂在某个 JobExecution 下 | 一次方法调用栈帧 |
| `ExecutionContext` | 附着在 Job/Step 上的键值存储，用来存断点位置 | 局部变量快照 |

一个 JobInstance 可以有多个 JobExecution：第一次跑失败了，用**同样**的参数再启动一次，会被识别为同一实例的第二次执行，Batch 会跳过已完成的 Step、从失败的 Step 的最后一个 chunk 边界继续。这正是批处理要的核心能力。

而如果用**不同**的 identifying 参数启动，则是一个新的 JobInstance——哪怕业务逻辑完全一样。反过来，同参数重复启动一个已经 `COMPLETED` 的实例，会被拒绝（详见「幂等」节）。

### 元数据表

JDBC 持久化时，`JobRepository` 使用 `BATCH_` 前缀的一组表：

| 表 | 内容 |
| ---- | ---- |
| `BATCH_JOB_INSTANCE` | JobInstance 身份（job 名 + 参数标识） |
| `BATCH_JOB_EXECUTION` | 每次执行的开始/结束时间、状态、退出码 |
| `BATCH_JOB_EXECUTION_PARAMS` | 本次执行的 JobParameters |
| `BATCH_JOB_EXECUTION_CONTEXT` | Job 级 ExecutionContext（序列化的断点信息） |
| `BATCH_STEP_EXECUTION` | 每个 step 的读写计数、提交/回滚计数 |
| `BATCH_STEP_EXECUTION_CONTEXT` | Step 级 ExecutionContext（读到第几条就存在这里） |

## Chunk 处理模型

Spring Batch 有两种 Step：

1. **面向分块（chunk-oriented）**：经典的读—处理—写三段式，绝大多数场景用它；
2. **Tasklet**：一个自由的任务单元（`TaskletStep`），适合"删个临时文件""调一次存储过程"这种不适合拆成读写的步骤。

分块模型的核心是三个组件的契约：

```java
public interface ItemReader<T> {
    T read() throws Exception;   // 返回 null 表示读完了
}

public interface ItemProcessor<I, O> {
    O process(I item) throws Exception;   // 返回 null 表示过滤掉这条
}

public interface ItemWriter<O> {
    void write(Chunk<? extends O> chunk) throws Exception;   // Batch 6 起是 Chunk 而非 List
}
```

执行单位是 **chunk**，它同时扮演三重角色：

```java
new StepBuilder("importStep", jobRepository)
    .chunk(500)                      // chunk 大小
    .reader(reader)
    .processor(processor)
    .writer(writer)
    .build();
```

- **提交间隔**：读满 500 条才交给 writer 一次性写，减少 IO 次数；
- **事务边界**：一个 chunk 对应一个事务，写失败整批回滚，不会出现写了半批的脏状态；
- **重启单元**：重启时从最后一个成功提交的 chunk 之后继续，粒度越细续跑丢失的重复工作越少，但事务开销越大。

> [!TIP]
> chunk 大小的调参本质是吞吐与安全性的权衡：太小则频繁提交、事务开销大；太大则失败回滚的重做成本高、内存占用高。经验区间是 100~1000，需要按单条数据的体积和处理耗时实测。

## JobRepository：Batch 6 最大的坑

这是升级 Boot 4 / Batch 6 时**唯一会静默出错、且后果最严重**的变更。

> [!WARNING]
> Batch 6 的 `DefaultBatchConfiguration` 不再构建 JDBC 版 JobRepository，其默认实现是一行 `return new ResourcelessJobRepository();`。
> 同时 Boot 4 的 `spring-boot-starter-batch` **只依赖内存模块** `spring-boot-batch`，不再像 Boot 3.5 那样传递依赖 `spring-boot-starter-jdbc`。
> 二者叠加的结果是：**作业照常跑、照常报 COMPLETED，但 `BATCH_*` 表一行都不写**。

后果完全不伴随异常或告警：

- 失败重启不再从断点继续，而是**从第 1 条重新开始**；
- 已完成的 job 用相同参数再跑一次会被接受（防重保护失效）；
- `RunIdIncrementer` 每次 JVM 启动都从 `run.id=1` 开始发放；
- 所有 `spring.batch.jdbc.*` 配置（含 `initialize-schema`、`table-prefix`）绑定到空处；
- 基于 `BATCH_JOB_EXECUTION` 的监控看板、告警、"上次成功运行时间"查询全部停在升级那天。

修复方式是显式引入 JDBC 版 starser：

```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-batch-jdbc</artifactId>
</dependency>
```

另一个相关陷阱：在 Boot 自动配置生效时，**不要加 `@EnableBatchProcessing`**——它会顶替掉 Boot 装配好的 `JobRepository` / `JobOperator`，退化为你自己手写的那份（通常就是内存版）。需要深度定制时才用，且理解它意味着放弃自动配置。

## Job 与 Step 配置

Batch 6 的 builder API 把此前隐式持有的依赖改为**构造期显式传入**：

```java
@Configuration
class SettlementJobConfig {

    @Bean
    Job settlementJob(JobRepository jobRepository, Step settleStep) {
        return new JobBuilder("settlementJob", jobRepository)   // JobRepository 成为必填构造参数
            .incrementer(new RunIdIncrementer())
            .start(settleStep)
            .build();
    }

    @Bean
    Step settleStep(JobRepository jobRepository,
                    PlatformTransactionManager txManager,
                    ItemReader<Order> reader,
                    ItemProcessor<Order, Bill> processor,
                    ItemWriter<Bill> writer) {
        return new StepBuilder("settleStep", jobRepository)
            .chunk(500)                          // 只传 chunk 大小
            .transactionManager(txManager)       // 事务管理器改为可选链式调用
            .reader(reader)
            .processor(processor)
            .writer(writer)
            .faultTolerant()
            .skip(FlatFileParseException.class)
            .skipLimit(50)
            .build();
    }
}
```

`JobBuilder(String)` 单参构造器和配套的 `.repository(...)` 方法在 6.0 已被移除；`StepBuilder.chunk(size, txManager)` 的双参形式也改为上述分离写法。

## JobOperator

Batch 6 把原先分离的 `JobLauncher`（启动）和 `JobExplorer`（查询历史）**合并为 `JobOperator`**，后者同时继承了二者的能力：

```java
@Service
class BatchJobService {

    private final JobOperator jobOperator;

    BatchJobService(JobOperator jobOperator) {
        this.jobOperator = jobOperator;
    }

    Long launch(String jobName, LocalDate bizDate) {
        JobParameters params = new JobParametersBuilder()
            .addLocalDate("bizDate", bizDate)          // 识别参数
            .addLong("run.id", System.currentTimeMillis())
            .toJobParameters();
        return jobOperator.start(jobName, params);
    }
}
```

Boot 的 `JobLauncherApplicationRunner` 会在应用启动时自动执行 detected job（可用 `spring.batch.job.enabled=false` 关掉），这是最常见的"容器一起来就跑批处理"的模式。

## JobParameters 与幂等

`JobParameters` 是每个 employee batch 作业的身份标识。Batch 6 里 `JobParameter` 变成了**不可变 record**，且名字作为字段内置其中；`JobParameters` 内部持有的不再是 `Map` 而是 `Set`：

```java
// Batch 6
JobParameter<LocalDate> p = new JobParameter<>("bizDate", today);
JobParameters params = new JobParameters(Set.of(p));
```

参数分为两类：

- **identifying（识别参数）**：参与计算 JobInstance 身份。相同则视为同一实例。
- **non-identifying（非识别参数）**：只记录、不参与身份计算，比如一个仅供日志用的 requestId。

```java
new JobParametersBuilder()
    .addString("status", "COMPLETED")        // identifying
    .addString("requestId", requestId, false) // 第三个参数 false = non-identifying
    .toJobParameters();
```

重复启动一个已完成的实例会拿到：

```
JobInstanceAlreadyCompleteException:
A job instance already exists and is complete for identifying parameters={...}
If you want to run this job again, change the parameters.
```

这是设计意图——Batch 拒绝重复执行已完成的工作。两种常规应对：给 Job 挂 `RunIdIncrementer`（每次自动补一个自增 `run.id`），或自己在参数里塞一个每次唯一的 identifying 值（时间戳、批次号）。选哪种取决于你的语义：**同一业务日期的重跑，到底应该被拒绝，还是应该被允许**。

## 流程编排

Job 不必是线性的，Batch 自带一套条件 DSL：

```java
@Bean
Job complexJob(JobRepository repo, Step validate, Step process, Step manualReview, Step archive) {
    return new JobBuilder("complexJob", repo)
        .start(validate)
            .on("FAILED").to(manualReview)          // 校验失败转人工
        .from(validate)
            .on("COMPLETED").to(process)            // 成功继续
        .from(process)
            .on("*").to(archive)                    // 默认转移
        .end()
        .build();
}
```

并行则用 `split` + `Flow`，让多个 step 在不同的 `TaskExecutor` 线程上同时推进：

```java
Flow flowA = new FlowBuilder<Flow>("flowA").start(stepA).build();
Flow flowB = new FlowBuilder<Flow>("flowB").start(stepB).build();

new JobBuilder("parallelJob", repo)
    .start(new FlowBuilder<Flow>("splitFlow")
        .split(new SimpleAsyncTaskExecutor())
        .add(flowA, flowB)
        .build())
    .end()
    .build();
```

更彻底的横向扩展是**分区（partitioning）**：`PartitionStep` 先由一个 master 步骤用 `Partitioner` 把数据切成若干网格（如按日期、按商户 ID 取模），再分发给多个 worker step 并行处理，各自独立提交事务。这是大批量场景提速的主要手段。

## 容错

`.faultTolerant()` 打开容错开关后可用：

| 策略 | 语义 | 适用 |
| ---- | ---- | ---- |
| `skip(Class)` / `skipLimit(n)` | 跳过符合条件的异常继续跑，超过阈值才让 step 失败 | 脏数据可容忍且事后能兜底重试，如 CSV 某行格式错 |
| `retry(Class)` / `retryLimit(n)` | 失败后重试，超过阈值转失败 | 偶发抖动，如网络超时、数据库死锁 |
| `noRollback(Class)` | 抛出该异常时不回滚当前 chunk | 该异常不影响已写入数据的正确性 |

监听器用于观测：`ReadListener`（读失败）、`ProcessListener`（处理失败）、`WriteListener`（写失败）、`SkipListener`（被跳过的条目，通常需要落到人工复核表）。

> [!WARNING]
> `skip` 是把双刃剑。跳过条数应当计入 step 的执行上下文并在 job 结束时告警：一个年久失修的作业可能因为源数据格式变更而在静静地跳过 100% 的条目，报表上却显示 COMPLETED。

## 从 5.x 迁移到 6

| 变更 | 5.x | 6.x |
| ---- | ---- | ---- |
| JobRepository 依赖 | builder 上 `.repository(...)`，可选 | **构造器必填** `new JobBuilder(name, repo)` |
| chunk 声明 | `.chunk(500, txManager)` | `.chunk(500).transactionManager(txManager)`，后者可选 |
| 启动/查询入口 | `JobLauncher` + `JobExplorer` | **`JobOperator`**（继承二者） |
| JobParameter | key 存在 Map 的键上 | **record**，名字是字段；`JobParameters` 持有 `Set` |
| 监听器基类 | `JobExecutionListenerSupport` 等抽象基类 | **全部移除**，直接 `implements` 接口（5.0 起有 default 方法） |
| `ChunkHandler` | `ChunkHandler` | `ChunkRequestHandler` |
| `setJobLauncher` | `setJobLauncher(JobLauncher)` | `setJobOperator(JobOperator)` |
| 默认存储 | JDBC | **内存（`ResourcelessJobRepository`）**，JDBC 需 `spring-boot-starter-batch-jdbc` |
| `@EnableBatchProcessing` | JDBC 参数全在这一个注解上 | 拆分为 `@EnableBatchProcessing` + `@EnableJdbcJobRepository`（或 `@EnableMongoJobRepository`）；Boot 自动配置下不要加 |

包结构也有大规模搬迁，编译报错时按这张表找：

| 原包 | 新包 |
| ---- | ---- |
| `o.s.b.core`（`Job`、`JobExecution`、`JobInstance`） | `o.s.b.core.job` |
| `o.s.b.core`（`JobParameter`、`JobParameters`、`RunIdIncrementer`） | `o.s.b.core.job.parameters` |
| `o.s.b.core`（`Step`、`StepExecution`、`StepContribution`） | `o.s.b.core.step` |
| `o.s.b.core`（各种 `*Listener`） | `o.s.b.core.listener` |
| `o.s.b.core.partition.support` | `o.s.b.core.partition` |
| `o.s.b.core.repository.dao`（JDBC DAO） | `o.s.b.core.repository.dao.jdbc` |
| `o.s.b.core.explore`（`JobExplorer` 相关） | `o.s.b.core.repository.explore` |

（`o.s.b.*` 即 `org.springframework.batch.*`）

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Task](/docs/CS/Framework/Spring/Task.md)
- [Spring Transaction](/docs/CS/Framework/Spring/Transaction.md)
- [Spring Data](/docs/CS/Framework/Spring/Data.md)
- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)

## References

1. [Spring Batch 项目主页](https://spring.io/projects/spring-batch)
2. [Spring Boot 4.0 Migration Guide](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide)
3. [Spring Batch Reference](https://docs.spring.io/spring-batch/reference/index.html)
