## Introduction

OpenAI Codex 是一个 AI 编程代理（AI Coding Agent），目标不是帮你补全代码，而是直接参与并完成整个开发任务——写代码、修 Bug、跑测试、提 Pull Request

## Installation

```shell
npm install -g @openai/codex --registry=https://registry.npmmirror.com

# mac
brew install --cask codex
```

认证信息在 ~/.codex/auth.json

## Harness 源码剖析

Harness 的通用概念（三层边界 Host/Harness/Model、Thread/Turn/Step/Item 四级粒度、四层安全、业务系统接入要点）已提炼到 [Harness](/docs/CS/AI/LLM/Harness.md) 笔记的「工程实例：Codex」一节。本篇只记录 Codex 仓库本身的源码级实现（对应 commit `633ab199cf`）。

开源仓库不含模型权重，只公开 CLI、核心运行时、app-server、SDK 等集成面。

## 项目结构

```
codex/
├── codex-cli/          # Node.js 包装层
├── codex-rs/           # Rust 工作区（Harness 主体）
│   ├── core/           # 会话、Turn、Agent loop、工具
│   ├── app-server/     # JSON-RPC 服务
│   ├── protocol/       # Thread/Turn/Item 事件协议
│   ├── tools/          # 工具定义与运行时
│   ├── sandboxing/     # 沙箱
│   ├── exec-server/    # 执行服务
│   ├── rollout/        # 历史记录与恢复
│   ├── thread-store/   # Thread 持久化
│   └── codex-mcp/      # MCP 接入
└── sdk/                # Python / TS SDK
```

Core 关键入口（`codex-rs/core/src`）：

| 文件 | 作用 |
| --- | --- |
| `session/turn_input.rs` | 启动 / 转向一个 Turn |
| `session/turn.rs` | `run_turn` 主循环 |
| `session/step_context.rs` | 采样快照 |
| `tools/router.rs` | ToolRouter |
| `tools/parallel.rs` | 并发控制 |
| `session/mod.rs` | 审批请求 |

## 一条任务如何运行

以"修复登录接口偶发 500 并跑测试"为例，完整走一遍。

### 接收任务：start_or_steer

`turn_input.rs` 的 `start_or_steer` 判断这次输入是**启动新 Turn、注入现有 Turn，还是拒绝**；随后构造 `TurnContext` 并 `spawn_task` 为后台 `SessionTask`。

- **TurnContext**：长期身份、环境快照、输出约束
- **StepContext**：一次请求前捕获的不可变设置（模型、路由、环境）
- **SessionTask**：统一取消、事件、生命周期

### 主循环 run_turn

```rust
async fn run_turn(...) {
    预先压缩过长上下文；
    解析本轮需要的 MCP / 技能 / 插件；
    记录用户输入和上下文注入；
    loop {
        取出用户在运行期间追加的输入；
        捕获一个 StepContext；
        从 Session 的会话历史生成本次 prompt；
        let result = run_sampling_request(prompt).await;
        if 需要继续 {
            如有必要则压缩上下文；
            continue;
        }
        break;
    }
}
```

三个关键机制：**StepContext 快照**（决策与执行看到同一套设置）、**历史受控输入**、**满则压缩后继续**。循环是否继续由 `needs_follow_up` 控制信号决定——工具刚启动、服务端返回 `end_turn: false`、用户插入新输入、hook 要求继续，都会让它为真。

### 事件汇合

`run_sampling_request` 创建 `ToolCallRuntime`，把 `ResponseEvent`（文本 delta、推理、Item 添加/完成）分发出去。**UI 订阅的是事实流，而不是自己保存一份状态。**

### 工具调度与并发

- `ToolRouter` 持有 `model_visible_specs` 与 `ToolRegistry`，负责"模型可见名 → 真实执行器"的映射
- `ToolCallRuntime` 用 Tokio 的 `RwLock` 做并发闸门：声明支持并行的工具拿**读锁**并行执行，独占工具拿**写锁**等待，全部监听 `CancellationToken`
- 四层形态：协议层 `FunctionCall` → 路由层 `ToolCall` → 执行层 handler → 回填层 `FunctionCallOutput`

### 安全边界：审批的异步实现

四层安全模型（沙箱 / 策略 / 审批 / schema）见 [Harness](/docs/CS/AI/LLM/Harness.md) 笔记。Codex 的源码实现在审批这层：

审批是**异步等待**：`Session::request_command_approval` 创建 oneshot channel、以 `approval_id` 登记等待者，发事件给 UI，然后 await 用户决策。**fail closed**——批准则继续，拒绝则产生拒绝结果，Turn 被中断或连接断开一律默认 `Abort`，不偷偷放行。文件修改走独立的 `request_patch_approval` 通道，命令与补丁在 UI 上按风险分别呈现。

### 历史与恢复

两类历史要分清：给模型的**事实**、给人/系统的**记录**。工具结果由 `drain_in_flight` 写回 `record_annotated_conversation_items`；Rollout 支撑恢复、分叉与审计；上下文压缩后仍保持后续可用。**Harness 本质上是外部记忆管理器。**

### 运行中的变化

三种停止方式：正常完成、工具失败（可继续）、用户中断。取消沿调用链传播（模型 / 工具 / 审批都能被打断）；模型流失败有重试状态；用户中途插话进入 `input_queue`，可控地并入下一轮。

### app-server 控制面

对外生命周期：

```
initialize → thread/start 或 thread/resume → turn/start → 持续接收 item/* 与 delta 事件 → turn/completed
```

双向 JSON-RPC：客户端发 `turn/start`，服务端推 `item/started`、delta、审批请求。队列有界并做背压，过载时返回可重试错误。三种接入层选择：

| 方式 | 适用 |
| --- | --- |
| `codex exec` | 脚本化调用 |
| SDK | 程序内嵌 |
| app-server | 复杂 UI、长期 Thread |

### 扩展能力

| 扩展 | 定位 |
| --- | --- |
| MCP | 标准工具接入点 |
| Skills | 受控的指令注入 |
| Plugins | 扩展包 |
| 多 Agent | 同一运行时内协作；**权限不天然继承** |

扩展接入必须走主链：被选择 → 纳入 StepContext → 模型可见 → Router/策略验证 → 执行 → Item 回填 → 事件可见。**不让扩展绕过 Harness**，否则会失去日志、取消和审批。

## 常见问题

| 问题 | 回答 |
| --- | --- |
| 这是不是 ReAct？ | 不是。ReAct 是模式，Harness 是完整生产运行时 |
| 会改变模型能力吗？ | 不改权重，但影响表现（尤其长任务的上下文正确性与恢复能力） |
| 开源仓库含模型吗？ | 不含，只有 CLI、运行时、app-server、SDK |
| 核心入口在哪？ | 理解运行看 `run_turn`，理解控制看 app-server，理解安全看 `ToolRouter` + `request_command_approval` |

## 源码阅读路线

```
app-server/README.md
  ↓ 先理解协议与生命周期
session/turn_input.rs
  ↓ 输入如何启动/转向一个 Turn
tasks/regular.rs + tasks/mod.rs
  ↓ 后台任务如何获得取消与完成生命周期
session/turn.rs::run_turn
  ↓ 主循环如何反复采样
tools/spec_plan.rs + tools/router.rs + tools/parallel.rs
  ↓ 工具计划、分派与并发控制
session/mod.rs::request_*_approval
  ↓ 人工审批如何卡住真实执行
```

六个核心符号可以先记下：`run_turn`（采样循环）、`StepContext`（请求固定快照）、`ToolRouter`（模型能力 ↔ 执行器）、`CancellationToken`（停止传播）、`RolloutItem`（恢复审计事实）、`app-server`（驱动内核的控制协议）。

## Links

- [Harness](/docs/CS/AI/LLM/Harness.md) — 通用 Harness 概念，含「工程实例：Codex」一节
- [Agent](/docs/CS/AI/LLM/Agent.md) — Agent 四构成（Loop/Tools/Memory/Harness）
- [Claude](/docs/CS/AI/LLM/Claude.md) / [OpenCode](/docs/CS/AI/LLM/OpenCode.md) / [OpenClaw](/docs/CS/AI/LLM/OpenClaw.md)
- [DSH](/docs/CS/AI/LLM/DSH.md) / [MCP](/docs/CS/AI/LLM/MCP.md) / [Self-Evolving](/docs/CS/AI/LLM/Self-Evolving.md)

## References

- [万字长文 | 深度解读 Codex Harness 源码](https://mp.weixin.qq.com/s/xa2xrK-LyM5Ktow2hq1vWQ)
- [openai/codex](https://github.com/openai/codex)
