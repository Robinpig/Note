## Introduction

AgentScope Java 是 AgentScope 的 **Java 实现**，仓库 `agentscope-ai/agentscope-java`，自我定位一句话：**Build distributed, production-grade, long-running agents**（构建分布式的、生产级的、长运行的智能体）。这三个定语就是它与本库已收录的 Python 版 [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md) 的定位差异——Python 版的关键词是 flexible yet robust multi-agent platform，Java 版的关键词是**分布式与长运行**。

必须先说清一个容易混淆的前提：**agentscope-java 与 agentscope 是同一家族下用不同编程语言开发的两个独立框架**，不是同一个项目的语言绑定，也不是 Python 版的移植层。两者共享 AgentScope 品牌、模型无关（model-agnostic）的思路与 ReAct 主循环这些核心思想，但代码库、API 形态、工程约定完全独立：Python 版是 `async` / `AsyncGenerator` 世界，Java 版是 Reactor 的 `Mono` / `Flux` 世界；Python 版把一切能力塞进单一 `Agent` 类，Java 版拆成 `ReActAgent`（基础循环）与 `HarnessAgent`（工程能力装配）两层。读 Python 版笔记建立的直觉在这里只能复用一半，**差异部分正是本笔记要记录的主体**。

本笔记以官方文档 **v2 线**为基准，版本事实：JDK 17+（`pom.xml` `<java.version>17`）、Maven 3.9+；GA 线最新 **v2.0.4**（Release Notes 准备日期 2026-10-08），Maven Central 另有 `2.1.0-BETA1`（2026-10-15 实测 `agentscope-harness` 的 `maven-metadata.xml`）。本笔记的事实来源是**本地 `v2.0.4` 源码树逐包核对**（`/Users/robin/Projects/agentscope-java`，git tag `v2.0.4`）+ 官方文档站（v2 中文文档全量抓取）+ GitHub 仓库元数据 + Maven Central 坐标；凡涉及类名、方法签名、默认值、枚举值的地方，一律以源码为准，文档与源码冲突时以源码为准并在文中标注。

本笔记采用「枢纽 + 分册」结构，与 Python 版 AgentScope 家族的分册惯例对齐（主笔记 + 分册同目录，分册不带文件名前缀）。七个专题已拆为独立分册（均基于本地 `v2.0.4` 源码逐包核对，统一放在 `AgentScopeJava/` 子目录）。各分册由哪里接手、按什么顺序读，见下文 [How to Read the Subsystem Notes](#how-to-read-the-subsystem-notes)。

## Modules And Versions

AgentScope Java 按「核心 / Harness / 扩展」分层发包，Maven groupId 统一为 `io.agentscope`，Central 上已发布上百个构件（2026-10-15 实测）。版本由 `agentscope-dependencies-bom` / `agentscope-bom` 统一管。

| 层 | 构件 | 内容 |
| :--- | :--- | :--- |
| 核心 | `agentscope-core` | `ReActAgent`、`Toolkit`、消息与事件、权限、状态存储、`ModelRegistry` SPI |
| Harness | `agentscope-harness` | `HarnessAgent`、工作区、文件系统、沙箱、记忆、会话日志；依赖 core，一个坐标即可拉起 |
| 模型扩展 | `agentscope-extensions-model-{openai,openai-official,dashscope,gemini,anthropic,ollama}` | 各厂商 Chat Model + Credential + Formatter |
| 存储扩展 | `agentscope-extensions-{redis,jdbc,mongodb}` | 分布式 `AgentStateStore` / `BaseStore` / 快照 |
| 沙箱扩展 | `agentscope-extensions-sandbox-{docker,kubernetes,daytona,e2b,agentrun}` | 五类沙箱后端（Docker / K8s / Daytona / E2B / 阿里云 AgentRun） |
| 频道扩展 | `agentscope-extensions-channel-{feishu,dingtalk,wecom,weixin,github,gitlab}` | 消息平台接入 |
| 技能扩展 | `agentscope-extensions-skill-{git,mysql}-repository`、`agentscope-extensions-nacos-skill` | 技能市场后端 |
| 框架集成 | `agentscope-{openai,dashscope,...}-spring-boot-starter`、`agentscope-admin-spring-boot-starter` | Spring Boot 自动装配；另有 Micronaut / [Quarkus](/docs/CS/Java/Quarkus.md) 扩展 |

两个值得记住的设计事实：

1. **模型实现不在 core 里**。core 只保留 `Model` / `ChatModelBase` / `Formatter` / `ModelRegistry` 通用契约，OpenAI、DashScope、Gemini、Anthropic、Ollama 的具体实现全部在独立扩展模块，通过 Java SPI（`META-INF/services/io.agentscope.core.model.spi.ModelProvider`）被 `ModelRegistry` 自动发现。加一家厂商 = 加一个模块，core 不动。
2. **示例仓库即文档**。可运行示例集中在 `agentscope-examples/documentation/`（按主题分 `context/`、`tool/`、`hitl/`、`streaming/`、`model/` 等子目录），官方文档页几乎每个主题都指向对应示例类。

## Quickstart

### Installation

`HarnessAgent` 是推荐入口：它把工作区、长期记忆、会话持久化、子 Agent、沙箱打包进一个 builder，依赖 `agentscope-harness` 会自动把 `agentscope-core` 拉进来。quickstart 用 `.model("dashscope:qwen-plus")` 走 DashScope，因此还要引对应模型扩展：

```xml
<dependency>
    <groupId>io.agentscope</groupId>
    <artifactId>agentscope-harness</artifactId>
    <version>${agentscope.version}</version>
</dependency>
<dependency>
    <groupId>io.agentscope</groupId>
    <artifactId>agentscope-extensions-model-dashscope</artifactId>
    <version>${agentscope.version}</version>
</dependency>
```

只需要 ReActAgent 的推理、工具与上下文 API 时，`agentscope-core` 单独也够。MCP 集成需要官方 MCP SDK。

### First Agent

核心模式：**应用启动时定义共享 Builder，每次请求 `builder.build()` 创建新实例，执行完关闭**；请求身份放进独立的 `RuntimeContext`：

```java
import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.core.message.Msg;
import io.agentscope.core.message.UserMessage;
import io.agentscope.harness.agent.HarnessAgent;
import java.nio.file.Path;

public class FirstAgent {
    private static final HarnessAgent.Builder AGENT_BUILDER = HarnessAgent.builder()
            .name("note-taker")
            .agentId("note-taker")
            .sysPrompt("你是一个帮助用户做笔记的助手。")
            .model("dashscope:qwen-plus")
            .workspace(Path.of(".agentscope/workspace"));

    public static void main(String[] args) {
        try (HarnessAgent agent = AGENT_BUILDER.build()) {
            RuntimeContext ctx = RuntimeContext.builder()
                    .userId("alice").sessionId("demo-session").build();
            agent.call(new UserMessage("我叫天宇，今天准备一个技术分享。"), ctx).block();
        }
        // 下一次请求用新实例；相同会话身份从持久日志恢复上下文
        try (HarnessAgent agent = AGENT_BUILDER.build()) {
            RuntimeContext ctx = RuntimeContext.builder()
                    .userId("alice").sessionId("demo-session").build();
            Msg reply = agent.call(new UserMessage("我叫什么？今天要干什么？"), ctx).block();
            System.out.println(reply.getTextContent());
        }
    }
}
```

三个要点：`call` 返回 `Mono<Msg>`，`.block()` 只是命令行示例的等待方式；一次 call 内部可以多次推理 + 多次工具执行；相同 `(userId, sessionId)` 的下一次调用会自动从 Session Log 恢复上下文——Harness 默认保存执行日志与 checkpoint，**不需要额外创建 `AgentSession`**。原生日志落在 workspace 为当前身份解析的根下 `.agentscope-runtime/`。

### Streaming And Web

边生成边显示用 `streamEvents`（返回 `Flux<AgentEvent>`，订阅后才启动执行）：

```java
agent.streamEvents(new UserMessage("帮我把分享的准备工作列成三条。"), ctx)
        .doOnNext(event -> {
            if (event.getType() == AgentEventType.TEXT_BLOCK_DELTA) {
                System.out.print(((TextBlockDeltaEvent) event).getDelta());
            } else if (event.getType() == AgentEventType.TOOL_CALL_START) {
                System.out.println("\n[tool] " + ((ToolCallStartEvent) event).getToolCallName());
            }
        })
        .blockLast();
```

WebFlux 里用 `Mono.using` 管理实例生命周期——订阅时构建、完成/报错/取消时关闭，**不要在 try 块里返回尚未订阅的 `Mono`**：

```java
return Mono.using(
        AGENT_BUILDER::build,
        agent -> agent.call(new UserMessage(userInput), ctx),
        HarnessAgent::close);
```

`userId` 应来自已认证身份，`sessionId` 应经过访问权限检查；共享的模型、工具与中间件必须支持并发使用。不同会话可并行，**同一会话跨实例的请求要由应用按顺序调度**——日志写入隔离不等于自动排队。

### When To Use AgentSession

日常问答、工作流节点、随请求完成的流式界面继续用 `call` / `streamEvents`。当产品需要「关闭页面后继续运行」「忙时接收并保存下一项任务」「运行中补充要求」「中断后继续原任务」时，用 `agent.session(ctx)` 提供的 `AgentSession`：它负责持久接收任务、安排后台执行，前端独立读快照与持久事件。完整机制见 [会话分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Session.md)。

## Architecture Overview

### Two Agent Classes, One Loop

Java 版把 Python 版的「单一 `Agent` 类」拆成两层，这是两版架构最直观的差异：

| 层 | 类 | 提供什么 |
| :--- | :--- | :--- |
| 基础循环 | `ReActAgent` | 「模型推理 → 执行工具 → 结果交回模型」的循环，加权限、HITL、上下文与状态管理、中间件、事件流 |
| 工程装配 | `HarnessAgent` | 内部封装 `ReActAgent`（薄包装，builder 接口大体一致），额外内置工作区、长期记忆、上下文压缩、技能、子 Agent、沙箱、会话日志与恢复 |

ReAct 循环本身两版一致；Harness 的内置能力在循环的相应阶段参与工作，推理-执行循环本质上没有变化。

### One Execution, End To End

一次执行读起来是四步：**读取当前会话状态 → 构建模型输入 → 按需调用工具 → 保存结果**。工作区、记忆、压缩都在这些步骤里生效。身份与状态的分界是这套架构的骨架：

- **`RuntimeContext`**（per-call）：`userId` / `sessionId`、字符串属性、类型化属性、`runId`。瞬态，不持久化，决定这次调用读写哪个状态槽位。
- **`AgentState`**（持久化）：对话上下文、压缩摘要、权限规则、Plan Mode 状态、任务与工具状态。由 `AgentStateStore` 或（默认）原生 Session Log 的 checkpoint 保存。
- **长期记忆**（跨 session）：`memory/YYYY-MM-DD.md` 只追加，后台节流任务合并进 `MEMORY.md`，每次 call 加载为**参考上下文**而非 System 指令。

状态分三层流转（调用内 / 跨调用 / 长期），框架自动在层之间搬数据；压缩、记忆提炼、后台维护都受节流闸门管着，不会每轮都跑。

### The Extension Surface

围绕 ReAct 循环，Java 版的扩展面比 Python 版更「工程化」也更分散：

- **工具**：`Toolkit` 统一注册 Java 工具（`@Tool` 注解反射或继承 `ToolBase`）、MCP 客户端、技能；工具组可运行时切换。
- **权限**：五模式（DEFAULT / ACCEPT_EDITS / EXPLORE / BYPASS / DONT_ASK）+ 规则 DSL + 工具自带 `checkPermissions`（不可绕过）+ 危险路径保护。
- **中间件**：**5 个 hook**（`MiddlewareBase` 接口）——4 个洋葱型（`onAgent` / `onReasoning` / `onActing` / `onModelCall`，before/after 包裹）+ 1 个管道型（`onSystemPrompt`，顺序变换字符串）；`order()` 默认 1，数值越大越靠外层，同级保持注册顺序。
- **工作区**：`AGENTS.md` / `MEMORY.md` / `tools.json` / `skills/` / `subagents/` / `plans/` / `knowledge/` 一套逻辑目录，同一布局可落本机磁盘、共享 KV 或沙箱容器。
- **会话**：原生 Session Log（`commits` 提交批次 + `blobs` 大载荷 + `inbox` 输入队列 + `exports` 导出进度，原子版本比较写入）+ checkpoint + AgentSession 后台调度。
- **服务化**：重新设计的 AgentScope Service（Session / Turn 模型 + 公共 SSE + 快照）+ Channel / Gateway（会话管理、per-session 并发、多 agent 路由）。

## How to Read the Subsystem Notes

七个分册按「**装配 → 边界 → 状态 → 持久 → 能力**」几条线组织，大致对应上面 `The Extension Surface` 一节枚举的那些扩展维度。只想把框架用起来的读者读完 Quickstart 与 Architecture Overview 即可；要改框架行为、或判断某个能力该不该自己补，按下面几条线找对应分册。

**装配线：一次调用长什么样。**[智能体分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md) 讲智能体接口与调用方式——`Agent` 三段式接口组合、`ReActAgent.Builder` 完整参数、实例生命周期、结构化输出、单次执行控制句柄 `AgentRun`、中断与 HITL、模型容错。串起「一次 call 内部发生了什么」的另一半在 [消息分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Message.md)：`Msg` + `AgentEvent` 双视图，`call` 消费全部事件还你一条 `Msg`、`streamEvents` 逐事件交给你，以及和 harness 远程线格式、Service 持久事件的边界。

**边界线：工具与工具调用这条路。**[工具分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Tool.md) 把工具体系、权限（五模式 + 规则 DSL + 工具自带 `checkPermissions`）、中间件（5 个 hook）、Plan Mode 合在一册——它们都挂在「一次工具调用怎么被放行、执行、拦截」这条链上。与 Python 版 7-hook 反射自动检测不同，Java 版是 5 个 hook + 显式 `order()` 排序。

**状态线：上下文与记忆。**[上下文分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Context.md) 讲 `AgentState` 与它的存储实现、`RuntimeContext` 的 per-call 语义、上下文压缩与工具结果卸载的取舍、两层长期记忆。最值得记的一条订正：core 的 `memory` 包在 2.0.0 已整体废弃，v2 记忆能力全部迁到 harness 层。

**持久线：会话恢复与服务化。**[会话分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Session.md) 把 Session Log 当一层独立于 Agent 执行的持久基础设施讲——可回放、可恢复、可导出，`AgentSession` 在其上提供「提交任务、后台执行、中断续做」；[工作区分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Workspace.md) 解决 Agent 与文件世界的关系，拆成工作区目录 / 文件系统访问模式 / 沙箱后端三个正交关注点，是 HarnessAgent 定义与进化的 source of truth。

**能力线：可复用能力与委派。**[技能分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Skill.md) 覆盖 Skill 与子 Agent——Skill 是「能力包」（`SKILL.md` + 参考文档，解决上下文预算问题），子 Agent 是「能力的执行体」，两者共用工作区声明与沙箱投影机制，合册最能看清「委派」这条链路。

## Comparison With Python AgentScope

同族两个框架的逐项对照（Python 侧事实见 [AgentScope 主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)及其分册，Java 侧为 v2 文档事实）：

| 维度 | AgentScope（Python） | AgentScope Java |
| :--- | :--- | :--- |
| 语言 / 并发模型 | Python 3，asyncio + `AsyncGenerator` | Java 17+，Reactor `Mono` / `Flux` |
| Agent 抽象 | 单一 `Agent` 类，能力全内置 | `ReActAgent` 基础循环 + `HarnessAgent` 薄包装装配 |
| 入口方法 | `reply()` / `reply_stream()` | `call()` → `Mono<Msg>` / `streamEvents()` → `Flux<AgentEvent>` / `observe()` |
| 中间件 | 7 hook（6 onion + 1 transformer），反射自动检测 | **5 个 hook**（4 onion + 1 transformer），`order()` 显式排序 |
| 权限 | 5 模式 + 三级规则 + `bypass_immune` 安全 ASK | 5 模式 + 规则 DSL + `ToolBase.checkPermissions` 恒生效（bypass-immune）+ 危险路径强制 ASK |
| 上下文压缩 | `ContextConfig` 三 ratio + `SummarySchema` 五维摘要 | `CompactionConfig`（token / 消息条数双触发，动态阈值）+ `ToolResultEvictionConfig`（宽度卸载，与压缩正交） |
| 记忆 | 三类长期记忆中间件 | 两层记忆（`memory/YYYY-MM-DD.md` 日流水账 + `MEMORY.md` 策划版）+ `memory_search` / `memory_get` / `memory_save` / `session_search` 四个工具 |
| 工作区 | `BackendBase` 三原语 + 6 种 workspace 后端 | 逻辑目录布局 + 3 种 filesystem 模式 + 5 种沙箱后端 + `IsolationScope` |
| 会话持久化 | `AgentState` Pydantic 模型 + SQL / Redis storage | `AgentState` + `AgentStateStore`（LEGACY）；**默认 EVENT_LOG 原生 Session Log + checkpoint** |
| 服务化 | FastAPI app + Web UI + `MessageBus` 六原语 | AgentScope Service（Session / Turn + 公共 SSE）+ Channel / Gateway + Spring starters |
| 技能 | `skill/` 包 + Jinja2 渲染 | 四层合成（projectGlobal → 市场 → workspace/skills → <userId>/skills）+ 市场后端（Git / Nacos / MySQL / classpath）+ 自学习闭环 |
| 子 Agent | `A2AAgent` 适配器 + Pipeline 编排 | `subagents/*.md` 声明 + `agent_spawn` + 远程 Agent Protocol（HTTP SSE） |
| 实时语音 | `RealtimeAgent` 专篇 | v2 文档未见对应章节 |

一句话总结差异：**Python 版把 Harness 层能力压进 Framework 核心，Java 版则把工程能力做成了可替换的装配层**（filesystem / store / sandbox / skill repository 全是 SPI），换存储、换沙箱、换技能市场都不改 agent 代码——这是它「distributed, production-grade」定位的直接体现。

## Links

- [Agent 目录](/docs/CS/AI/LLM/Agent/README.md)
- [LangChain4j](/docs/CS/AI/LLM/LangTool/LangChain4j.md) / [LLM 应用开发框架](/docs/CS/AI/LangTools.md)
- [DSH](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md) / [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md) / [Pi](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [Agent Theory](/docs/CS/AI/LLM/Agent/Theory/Agent.md) / [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) / [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md) / [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)

## References

- [AgentScope Java 快速开始](https://java.agentscope.io/v2/zh/docs/quickstart)
- [AgentScope Java Harness 架构](https://java.agentscope.io/v2/zh/docs/harness/architecture)
- [AgentScope Java 工作区](https://java.agentscope.io/v2/zh/docs/harness/workspace)
- [AgentScope Java 文件系统](https://java.agentscope.io/v2/zh/docs/harness/filesystem)
- [AgentScope Java 会话日志](https://java.agentscope.io/v2/zh/docs/harness/session-log)
- [AgentScope Java 技能](https://java.agentscope.io/v2/zh/docs/harness/skill)
- [AgentScope Java 子 Agent](https://java.agentscope.io/v2/zh/docs/harness/subagent)
- [AgentScope Java Channel](https://java.agentscope.io/v2/zh/docs/harness/channel)
- [AgentScope Java Release Notes](https://java.agentscope.io/v2/zh/docs/others/release-notes)
- [AgentScope Java 上生产指南](https://java.agentscope.io/v2/zh/docs/others/going-to-production)
- [agentscope-java GitHub](https://github.com/agentscope-ai/agentscope-java)
