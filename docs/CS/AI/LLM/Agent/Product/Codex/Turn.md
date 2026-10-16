> 版本基线：核实于 2026-10-16，对应 commit `6b991972c5b5`（`main`，2026-10-15）。

## Introduction

一个 Turn 的生命周期可以概括成五问：**输入怎么进来**（`start_or_steer`）、**循环怎么转**（`run_turn`）、**事件怎么出去**（`run_sampling_request` 分发）、**中途怎么改**（注入、挂起、取消）、**结果怎么留下来**（Rollout）。这一页按这个顺序走一遍，所有结论都能在 `core/src/session/` 下找到落点。

## Receive Task: start_or_steer

`turn_input.rs` 的 `handle()` 按 `TurnInputMode` 分三条路，`start_or_steer` 是其中主路：

| 模式 | 语义 |
| :--- | :--- |
| `StartOrSteer` | 启动新 Turn，或把输入注入正在运行的 Turn |
| `StartIfIdle` | 空闲才启动；非空 `UserInput` 记为 `TurnStartKind::User`，`ResponseItem` 等内部输入记为 `Automatic` |
| `ContinueIfIdle` | 带 `expected_previous_turn_id` 的续跑，只接受内部 response 输入（否则 `InvalidRequest`） |

提交的输入有四种形态：`UserInput`（用户内容）、`ResponseItem` / `AnnotatedResponseItem`（内部条目）、`InterAgentCommunication`（**跨 Agent 通信**，多 Agent 协作的入口）。

`start_or_steer` 判断这次输入是**启动新 Turn、注入现有 Turn，还是拒绝**；随后构造 `TurnContext` 并 `spawn_task` 为后台 `SessionTask`（统一取消、事件、生命周期）。三类上下文对象各管一段：

- **TurnContext**：长期身份、环境快照、输出约束——整个 Turn 不变
- **StepContext**：一次请求前捕获的不可变设置（模型、路由、环境）——每次采样重建
- **SessionTask**：后台任务句柄——统一取消、事件、生命周期

## Main Loop run_turn

`run_turn`（`turn.rs:166`）的签名本身就说明了循环的输入输出：

```rust
pub(crate) async fn run_turn(
    sess: Arc<Session>,
    turn_context: Arc<TurnContext>,
    mut input: Vec<TurnInput>,
    mcp_startup_requirements: &mut McpStartupRequirements,
    prewarmed_client_session: Option<ModelClientSession>,
    cancellation_token: CancellationToken,
) -> CodexResult<Option<String>>
```

源码注释把循环语义写得很直白：每次采样请求后，模型要么**请求函数调用**（执行完把输出带进下一次采样），要么**只回一条助手消息**（记入历史，Turn 完成）。实践上一次采样一般只含其中一种 item。骨架：

```rust
async fn run_turn(...) {
    预先压缩过长上下文（新输入记录之前）；
    解析本轮输入显式点名的 MCP server / 插件；
    loop {
        捕获一个 StepContext；
        从会话历史生成本次 prompt；
        let result = run_sampling_request(prompt).await;
        if 需要继续 {
            如有必要则压缩上下文；
            continue;
        }
        break;
    }
}
```

**StepContext 快照**保证决策与执行看到同一套设置；**历史受控输入**保证模型看到的每一条都有出处；**满则压缩后继续**让长任务不撞窗口。循环是否继续由 `needs_follow_up` 类控制信号决定——工具刚启动、服务端返回 `end_turn: false`、用户插入新输入、hook 要求继续，都会让它为真。

## Pre-Sampling Compaction

`run_turn` 的第一步不是采样，而是 `run_pre_sampling_compact`——**在新输入被记录之前**就预估「待进入上下文的条目（context diff / 全量重注入 + 用户输入）会不会把 Thread 推过压缩阈值」，会则主动压缩。这个顺序很关键：压缩失败时输入还没落账，可以用 `run_hooks_and_record_inputs` 原样补记，Turn 不丢用户消息。

压缩能力按 provider 能力分两档（`RemoteCompactionSupport`）：`V2` 支持远端压缩任务，`Unsupported` 只能本地摘要。自动摘要与 `TokenBudget` feature 互斥（`auto_summarization_enabled` 要求该 feature 未启用）。压缩的通用机制与各家对比见 [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)。

## Hooks Drain

每轮用户提示落账之前，先 `drain_async_hook_results` 把**上一个 Turn 期间延迟返回的 hook 结果**写进历史。hook 是异步的（可能跨 Turn 才完成），如果不在下一轮开始前清账，模型的下一采样就会漏掉这些事实。hook 机制本身见 [Extensions](/docs/CS/AI/LLM/Agent/Product/Codex/Extensions.md)。

## MCP Startup Requirements

`McpStartupRequirements`（`required_servers` + `required_plugins`）在**一个用户 Turn 内跨重启保留**：运行期间用户显式点名要用的 MCP server 或插件，即使会话重启也必须就位。此外用户输入里的插件提及会经 `collect_explicit_plugin_ids` 收集，与历史累积的需求合并去重后一并启动。

## Event Merging

`run_sampling_request` 创建 `ToolCallRuntime`，把 `ResponseEvent`（文本 delta、推理、Item 添加/完成）分发出去。**UI 订阅的是事实流，而不是自己保存一份状态**——宿主只接收 Item 事件，不自己维护任务状态。这是同一个内核驱动 TUI、IDE 与 app-server 的前提。

## Steering and Cancellation

运行期改注有两条通道：`session/inject.rs` 把消息注入现有 Turn（不新开 Turn），`input_queue` 承接用户中途插话并可控地并入下一轮；`turn_suspension.rs` 处理挂起。取消沿调用链传播（模型流 / 工具 / 审批都能被打断），统一载体是 `CancellationToken`。三种停止方式：正常完成、工具失败（可继续）、用户中断。审批等待中的连接断开默认 `Abort`（fail closed，见 [Approval](/docs/CS/AI/LLM/Agent/Product/Codex/Approval.md)）。

## History and Recovery

两类历史要分清：给模型的**事实**、给人/系统的**记录**。工具结果由执行链路写回 `record_annotated_conversation_items`；Rollout 支撑恢复、分叉与审计。

Rollout 的存储形态（`rollout/src/lib.rs`）：

- **JSONL 行式文件**：`RolloutLine` = timestamp + ordinal + item，一条一行；`~/.codex/sessions/` 存活跃会话，`archived_sessions/` 存归档
- **解析有专用通道**：`decode_rollout_line` 绕开 Serde 的 flattened-envelope 缓冲（`arbitrary_precision` 下浮点数会被吞，serde-rs/json#721），解析边界只有这一处
- **恢复语义**：`InitialHistory` / `ResumedHistory` 区分冷启与恢复；`RetainedContextEntry` / `RetainedContextEvent` 记录压缩后仍保留的上下文；`CompactionResumeMetadata` 记住压缩点，恢复后摘要继续生效
- **索引与检索**：`session_index`（会话索引）、`rollout_reference_index`（引用索引）、`reverse_jsonl_scanner`（倒序扫描，避免读整个文件）、`search`、`maintenance`、`compression`（历史文件压缩）
- **SQLite 旁路**：`state_db` 与 `thread-store` 承接 Rollout 之外的查询型状态

**Harness 本质上是外部记忆管理器。** 跨会话的长期记忆（Memories 两阶段固化）是另一套系统，见 [MultiAgent](/docs/CS/AI/LLM/Agent/Product/Codex/MultiAgent.md)。

## Links

- [Codex 主入口](/docs/CS/AI/LLM/Agent/Product/Codex/Codex.md) / [Architecture：仓库与 crate 地图](/docs/CS/AI/LLM/Agent/Product/Codex/Architecture.md)
- [Approval：审批](/docs/CS/AI/LLM/Agent/Product/Codex/Approval.md) / [Extensions：MCP/Skills/Plugins/Hooks](/docs/CS/AI/LLM/Agent/Product/Codex/Extensions.md)
- [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md) — 压缩的通用机制与各家实现对比
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) — 「工程实例：Codex」提炼的可迁移设计

## References

- [openai/codex](https://github.com/openai/codex)
