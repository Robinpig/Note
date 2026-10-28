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
| `powerjob-remote` | 自研远程通讯框架（`remote-framework` + `remote-impl-akka` / `remote-impl-http`） |
| `powerjob-official-processors` | 官方处理器库（SQL、Shell、Python 等） |
| Console | 前端：任务管理、状态监控、日志查看 |

与 XXL-JOB 的全局扫描不同，PowerJob Server 是**多活但分片**的：`PowerScheduleService` 按 `listAppIdByCurrentServer(当前 server 地址)` 取 app 列表，**每个 app 固定由绑定的 server 调度**，server 集群共同分担调度压力而无需 DB 锁竞争。执行侧则是**两级派发**：Server 只把整个 instance 派给选中的 Master Worker，再由该 Worker 的 `TaskTracker` 协调子任务分发（细节见 [Execution Modes](/docs/CS/Framework/Job/PowerJob/Execution_Modes.md)）。

### Remote Transport

Server 与 Worker 的通讯走 `powerjob-remote` 抽象层，核心是一层 `Transporter` SPI：

- `RemoteEngine`：引擎门面，`PowerJobRemoteEngine` 为默认实现；
- `CSInitializer`（Client-Server 初始化器）：负责建连、角色协商；
- `Transporter` / `Protocol`：传输层 SPI，`AkkaTransporter`（akka-remote）与 `VertxTransporter`（HTTP）是 4.x 起就并存的两套实现；5.1.x 新增的 **MU 协议**面向单向网络环境（worker 可主动访问 server、反向不通），发布时标注 BETA，仅建议开发环境使用。

> [!NOTE]
>
> 早期文章常说"PowerJob 通过 akka-remote 派发任务"——4.x 时代 akka 确实是主力，但**传输层自 4.x 起就已被 `Transporter` SPI 收敛**（本机 4.3.9 源码 `powerjob-remote` 下同时有 `AkkaTransporter` 与 `VertxTransporter` 两种实现）。"5.x 起才收敛到 SPI"的说法不成立；真正 5.x 新增的是 **MU 协议**。判断"现在用什么协议"要看 `TransportService.defaultProtocol()` 的装配，而不是历史印象。

## How to Read This Subtree

按"调度是怎么发生的 → 时间怎么算准 → 任务怎么执行 → 多个任务怎么编排 → 处理器怎么写"的顺序读：

先读[调度原理](/docs/CS/Framework/Job/PowerJob/Scheduling.md)：15s 扫描循环、按 app 分片、`listAppIdByCurrentServer` 多活分片、先落库后调度，是理解整个 Server 调度循环的前提。时间精度交给[时间轮](/docs/CS/Framework/Job/PowerJob/Timing_Wheel.md)：单层哈希轮 + 精确/慢速双轮 + 60s 长延迟降级，以及为什么"三层 60/60/24 分级轮"是错的。[定时策略](/docs/CS/Framework/Job/PowerJob/Timing_Strategies.md)讲 `TimeExpressionType` 到 handler 的 `EnumMap` 分派、"一次算 5 次触发时间"。"下次触发时间"算好后，[执行模式](/docs/CS/Framework/Job/PowerJob/Execution_Modes.md)回答"任务最终落在哪些 Worker、怎么拆"——两级派发与 Light/Heavy `TaskTracker` 是这里的核心。多个任务间的依赖与数据传递交给[工作流](/docs/CS/Framework/Job/PowerJob/Workflow.md)；具体怎么写执行体、怎么接入业务系统，看[处理器与生态](/docs/CS/Framework/Job/PowerJob/Processors.md)。

```text
                   ┌─ Scheduling      调度循环 / 按 app 分片 / 先落库后调度
       枢纽 PowerJob ─┤
                   │  ├─ Timing Wheel    单层哈希轮 / 双轮 / 60s 降级
                   │  ├─ Timing Strategies  EnumMap 分派 / 6 种表达式
                   ├─ Execution Modes  两级派发 / Light+Heavy TaskTracker
                   ├─ Workflow         DAG / 上下游数据传递
                   └─ Processors       处理器类型 / worker-client-agent / 版本
```

## 版本与核实口径

### 版本锚点

- **基线 v5.1.7**（2026-10-01）：Releases 与 Maven Central 双重核实。5.1.x 保持 Java 8、协议、鉴权、配置与 schema 不变，Server 可单独升级。
- **本机源码 checkout 为 4.3.9（master, 2024-03）**：本子树"原理与实现细节"六篇分册的断言（常量、`EnumMap`、两级派发、`isLightweightTask` 判定等）均以这份 4.3.9 源码逐行核对，路径:行号随文给出。
- **5.x 独有项**，本机 4.3.9 源码中**不存在**，一律标注"需回 v5.1.7 源码确认"：MU 协议、`INACCURATE_TIMER`（`HashedWheelTimerHolder`）、`DailyTimeIntervalStrategyHandler`、以及 5.1.7 的工作流修复。

### 已证伪清单

以下条目曾以"事实"形态流传，已被 4.3.9 源码推翻：

- **"分层时间轮：秒级 60 槽 / 分钟级 60 槽 / 小时级 24 槽，任务到期逐级降级"**：实际是**单层哈希轮**（`HashedWheelTimer`），配精确轮 + 慢速轮 + 60s 长延迟降级。三层 60/60/24 在 PowerJob 任何版本源码里都得不到印证。
- **"5.x 起传输层才收敛到 `Transporter` SPI"**：4.3.9 已有 `Transporter` 接口与 `AkkaTransporter` + `VertxTransporter` 两套实现。真正 5.x 新增的是 **MU 协议**。

## Links

- [Scheduling](/docs/CS/Framework/Job/PowerJob/Scheduling.md)
- [Timing Wheel](/docs/CS/Framework/Job/PowerJob/Timing_Wheel.md)
- [Timing Strategies](/docs/CS/Framework/Job/PowerJob/Timing_Strategies.md)
- [Execution Modes](/docs/CS/Framework/Job/PowerJob/Execution_Modes.md)
- [Workflow](/docs/CS/Framework/Job/PowerJob/Workflow.md)
- [Processors](/docs/CS/Framework/Job/PowerJob/Processors.md)
- [Job](/docs/CS/Framework/Job/Job.md)
- [Task](/docs/CS/Framework/Spring/Task.md)

## References

- [PowerJob GitHub](https://github.com/PowerJob/PowerJob)
- [PowerJob 官方文档](https://www.yuque.com/powerjob/guidence/intro)
- [PowerJob Releases](https://github.com/PowerJob/PowerJob/releases)
