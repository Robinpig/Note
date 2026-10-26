## Introduction

[PowerJob](https://github.com/PowerJob/PowerJob)（原 OhMyScheduler）是全新一代分布式任务调度与计算框架，能让开发者轻松完成作业的调度与繁杂任务的分布式计算。它在四族调度器里功能面最宽：定时策略覆盖 CRON、固定频率、固定延迟、每日时间段与 OpenAPI；执行模式从单机、广播一路扩展到 Map/MapReduce——寥寥数行处理器代码即可获得集群分布式计算能力；并原生支持 DAG 工作流与上下游任务间的数据传递。

技术栈上，Server 与 Worker 均为 Spring 应用，二者经自研 `powerjob-remote` 远程框架通信（5.1.x 引入 MU 协议，支持单向网络环境下 worker 主动访问 server 的双向通讯）；调度精度由 Server 内的哈希时间轮保证。当前版本基线 **v5.1.7**（2026-10-01 发布），仍兼容 Java 8。

```java
@Slf4j
@EnableScheduling
@SpringBootApplication
public class PowerJobServerApplication {
    public static void main(String[] args) {

        pre();

        // Start SpringBoot application.
        try {
            SpringApplication.run(PowerJobServerApplication.class, args);
        } catch (Throwable t) {
            throw t;
        }
    }

    private static void pre() {
        log.info(TIPS);
        PropertyUtils.init();
    }
}
```

## Architecture

仓库模块即架构分层（以 master / 5.1.x 为准）：

| 模块 | 角色 |
| :--- | :--- |
| `powerjob-server` | 调度中心：`server-core`（调度、实例、工作流引擎）+ `server-common`（时间轮等公共组件）+ `server-starter` |
| `powerjob-worker` | 执行端：拉取任务、执行处理器、上报状态；`worker-agent` 支持容器化部署 |
| `powerjob-client` | 嵌入业务的 OpenAPI 客户端（触发任务、查询实例） |
| `powerjob-common` | 两端共享的模型、枚举、协议 |
| `powerjob-remote` | 自研远程通讯框架（`remote-framework` + `remote-impl-akka`） |
| `powerjob-official-processors` | 官方处理器库（SQL、Shell、Python 等） |
| Console | 前端：任务管理、状态监控、日志查看 |

与 XXL-JOB 的全局扫描不同，PowerJob Server 是**多活但分片**的：`PowerScheduleService` 按 `listAppIdByCurrentServer(当前 server 地址)` 取 app 列表，**每个 app 固定由绑定的 server 调度**，server 集群共同分担调度压力而无需 DB 锁竞争。

### Remote Transport

Server 与 Worker 的通讯不直连 akka，而是走 `powerjob-remote` 抽象层：

- `RemoteEngine`：引擎门面，`PowerJobRemoteEngine` 为默认实现；
- `CSInitializer`（Client-Server 初始化器）：`AkkaCSInitializer` 为当前默认实现，负责建连、角色协商；
- `Transporter` / `Protocol`：传输层 SPI，`AkkaTransporter`（akka-remote 经典实现）与 5.1.x 新增的 **MU 协议**是两种实现。MU 面向单向网络环境（worker 可主动访问 server、反向不通），发布时标注 BETA，仅建议开发环境使用。

> [!NOTE]
>
> 早期文章常说"PowerJob 通过 akka-remote 派发任务"——4.x 时代属实；5.x 起传输层已被 `Transporter` SPI 收敛，akka 只是其中一个实现。判断"现在用什么协议"要看 `TransportService.defaultProtocol()` 的装配，而不是历史印象。

## Task Scheduling

调度主流程在 `PowerScheduleService`（源码级）：

1. **调度周期 15s**：`SCHEDULE_RATE = 15000`，三类调度任务（CRON 任务 `scheduleNormalJob`、CRON 工作流 `scheduleCronWorkflow`、FIX_RATE/FIX_DELAY 任务 `scheduleFrequentJob`）各按此周期跑；单次耗时超 15s 会打 warn 提示数据库压力过大。
2. **按 app 分片扫描**：取本 server 绑定的 appId 列表，按 `MAX_APP_NUM = 10` 分批并发；查询窗口是 `nextTriggerTime <= now + 2 * SCHEDULE_RATE`（预读未来 30s）。
3. **先落库再调度**：对每个到期任务经 `instanceService.create(...)` 生成 Instance 记录（任务执行实例）并 flush——**调度记录先于调度动作写入**，防止"时间轮到期了但实例记录丢失"。
4. **推入时间轮**：`InstanceTimeWheelService.schedule(instanceId, delay, () -> dispatchService.dispatch(...))`，到期回调即派发。
5. **刷新下次触发时间**：`refreshJob(...)` 按时间表达式计算并写回 `nextTriggerTime`。
6. **Worker 执行 → 上报状态 → Server 更新 Instance 状态**；`InstanceStatusCheckService` 负责超时重试与失败补偿。

源码注释里留着一次设计反复的痕迹：javadoc 自述"原设计 FIX_RATE/FIX_DELAY 不需要被调度、创建后直接派发，只需要失败重试；后来统一走时间轮——那样写不太优雅，东一坨代码西一坨代码的，还是牺牲点性能统一调度算了（优雅，永不过时～）"。当前所有表达式类型都统一经时间轮驱动。

## Timing Wheel

PowerJob 的时间轮是自研的**单层哈希轮**（`tech.powerjob.server.common.timewheel.HashedWheelTimer`），不是多层分级结构。`InstanceTimeWheelService` 同时持两个轮：

| 轮 | 构造参数 | 用途 |
| :--- | :--- | :--- |
| 精确轮 `TIMER` | `new HashedWheelTimer(1, 4096, CPU核数 × 4)` | 每 1ms 走一格、4096 槽、独立处理线程池（核数×4，CallerRun 拒绝策略） |
| 慢轮 `SLOW_TIMER` | `new HashedWheelTimer(10000, 12, 0)` | 每 10s 走一格、12 槽（格式化为 16）、无独立线程池 |
| 非精确轮 `INACCURATE_TIMER` | `new HashedWheelTimer(5000, 16, 0)`（`HashedWheelTimerHolder`） | 每 5s 走一格，用于非精确场景 |

`HashedWheelTimer` 的实现要点（源码注释与构造逻辑）：

- **最小精度 1ms、误差 1ms**——精度天花板来自 `Thread.sleep` 本身不精确，与 Netty 的 HashedWheelTimer 同源思想；
- 轮盘大小格式化为 **2 的 N 次方**，用 `& mask` 代替取余；
- `schedule(uniqueId, delayMS, timerTask)` 的 `uniqueId` **必须是 snowflake 算法生成的 ID**（实例 ID），用于取消表定位。

长短延迟的分流策略在 `InstanceTimeWheelService.schedule`：

- 延迟 ≤ `LONG_DELAY_THRESHOLD_MS`（60s）：直接进精确轮；
- 延迟 > 60s：先进慢轮，到期前 60s（`expectTriggerTime - now`）再转入精确轮——**避免为少量远未来任务占用 4096 槽的精确轮**；
- 取消表 `CARGO`：`MIN_INTERVAL_MS = 1000` 以下的任务不入表（太近来不及取消），`fetchTimerFuture(uniqueId)` 供停止任务时取消。

> [!WARNING]
>
> 本笔记早期版本写的是"分层时间轮：第一层秒级 60 槽、第二层分钟级 60 槽、第三层小时级 24 槽，任务到期逐级降级"——**该描述与源码不符**。当前实现是单层哈希轮 + 精确/非精确双轮 + 60s 长延迟降级（`InstanceTimeWheelService.java`）。三层 60/60/24 的说法无法在 PowerJob 任何版本源码里得到印证，以此为准会写错取消与降级的全部边界条件。

## Timing Strategies

`TimingStrategyService` 按 `TimeExpressionType` 分派到策略 handler（构造时注入全部 `TimingStrategyHandler` 组成 `EnumMap`）：

| 表达式类型 | Handler | 说明 |
| :--- | :--- | :--- |
| `CRON` | `CronTimingStrategyHandler` | Cron 表达式，经 `PowerScheduleService.scheduleNormalJob` 走时间轮 |
| `FIX_RATE` | `FixedRateTimingStrategyHandler` | 固定频率，统一调度后同样入轮 |
| `FIX_DELAY` | `FixedDelayTimingStrategyHandler` | 固定延迟（上次执行结束后计时） |
| `DAILY_TIME_INTERVAL` | `DailyTimeIntervalStrategyHandler` | 每日时间段内按间隔触发；5.1.7 修复了"每日窗口开始前首次触发不落在窗口边界"的问题 |
| `API` | `ApiTimingStrategyHandler` | OpenAPI 自定义调度策略（如延迟执行） |
| （工作流） | `WorkflowTimingStrategyHandler` | 工作流实例的 CRON 触发 |

`calculateNextTriggerTimes` 一次算 5 次触发时间供 UI 预览；CRON 模式最小连续执行间隔为 `SCHEDULE_RATE`（15s）——注意源码此处注释仍写作"忽略 5S 内的重复执行"，与常量 15000ms 不一致，**以常量为准**。

## Execution Modes

四种执行模式是 PowerJob 区别于纯调度器的核心能力：

- **单机（stand-alone）**：常规模式，Master 实例选定一个 worker 执行；
- **广播（broadcast）**：集群内所有 worker 各执行一遍，如全集群清日志；
- **Map**：任务拆成多个子任务分发到不同 worker，如批量更新大数据表分片并行；
- **MapReduce**：Map 阶段并行处理 + Reduce 阶段汇总结果，开发者实现 `MapReduceProcessor` 寥寥数行即获得分布式计算能力，Worker 支持自定义运行时核心数（`#1102`）。

## Workflow

PowerJob 原生支持 DAG 工作流（Workflow）：在线配置任务依赖关系、可视化编排，并支持上下游任务间的数据传递。工作流与任务共用时间轮与实例体系——`scheduleCronWorkflow` 先生成 workflow 实例记录再推轮；子任务的 Job 定义随工作流实例保存（5.1.7 修复了冷加载后 workflow 调度元数据丢失的问题）。需要"调度 + 编排 + 轻量计算"合一的场景，PowerJob 是四族里唯一一站式覆盖的。

## Processors and Ecosystem

- **处理器类型**：Java（Spring Bean / 内置 / 外置类）、Shell、Python，官方处理器库 `powerjob-official-processors` 提供 SQL 等开箱实现（5.1.5 修复了 SQL processor 结果日志累积上一行值的问题）；多语言调度规划经 HTTP 开放。
- **接入方式**：`powerjob-worker-spring-boot-starter` 零配置接入；`powerjob-client` 供业务系统 OpenAPI 触发；`powerjob-worker-agent` 支持容器与随机端口（`port = -1` 时随机分配，`#1102`）。
- **Maven 坐标**：`tech.powerjob:powerjob-worker` 等（4.x 起从旧的 `com.github.kfcfans` 迁移）。

## Version Facts

- 基线 **v5.1.7**（2026-10-01）：小功能 bugfix 版；修复 DAILY_TIME_INTERVAL 首次触发边界、workflow 子实例 Job 定义保留与冷加载元数据恢复、SpEL 应用类型解析、MU 连接关闭竞态、Worker 锁中断等。
- **升级兼容策略**：5.1.x 保持 Java 8、协议、鉴权行为、配置与数据库 schema 不变；**Server 可单独升级，不强依赖 Client/Worker/Console 同步升级**——想用 MU 传输或 Worker 侧修复才需要升级对应组件。
- MU 通讯协议为 5.1.x 重磅特性但标注 **BETA**，仅建议开发环境使用。
- 官方文档在语雀：<https://www.yuque.com/powerjob/guidence/intro>；在线试用 <https://try.powerjob.tech>。

## Links

- [xxl-job](/docs/CS/Framework/Job/xxl-job.md)
- [ElasticJob](/docs/CS/Framework/Job/ElasticJob.md)
- [Quartz](/docs/CS/Framework/Job/Quartz/Quartz.md)
- [Job](/docs/CS/Framework/Job/Job.md)
- [Task](/docs/CS/Framework/Spring/Task.md)

## References

- [PowerJob GitHub](https://github.com/PowerJob/PowerJob)
- [PowerJob 官方文档](https://www.yuque.com/powerjob/guidence/intro)
- [PowerJob Releases](https://github.com/PowerJob/PowerJob/releases)
