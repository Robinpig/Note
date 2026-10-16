> 版本基线：核实于 2026-10-16，对应 commit `6b991972c5b5`（`main`，2026-10-15）。

## Introduction

Codex 的工具系统回答三个问题：**模型能看到哪些工具**（ToolRouter 的 `model_visible_specs`）、**多个工具调用怎么并发**（ToolCallRuntime 的锁闸门）、**执行过程怎么留痕**（`executed_tool_calls` 记录器）。再加上 `spec_plan` 的计划层与网络审批上下文，构成「模型能力 ↔ 执行器」之间的完整中间层。

## ToolRouter

`tools/router.rs` 的 `ToolRouter` 持有两张表：`model_visible_specs`（模型可见的工具规格）与 `ToolRegistry`（真实执行器注册表），负责「模型可见名 → 真实执行器」的映射。四层形态：

| 层 | 对象 | 说明 |
| :--- | :--- | :--- |
| 协议层 | `FunctionCall` | 模型输出里的工具调用请求 |
| 路由层 | `ToolCall` | 经 `ToolRouter` 解析后的可执行调用（带 `ToolCallSource` 来源标注） |
| 执行层 | handler | 具体工具实现 |
| 回填层 | `FunctionCallOutput` | 结果作为 Item 写回会话历史 |

`spec_plan.rs` 负责**工具计划**——哪些工具在这一步对模型可见、以什么顺序暴露；`hosted_spec.rs` 与 `catalog_parameters.rs` 处理托管工具与目录参数。工具名这类跨 crate 标识在独立 `tools` crate（`codex_tools::ToolName`）。

## ToolCallRuntime and Concurrency

`tools/parallel.rs` 的 `ToolCallRuntime`（:46）是工具执行的并发控制器，核心字段只有一个：

```rust
pub(crate) struct ToolCallRuntime {
    session: Arc<Session>,
    // Tool calls may run later, so retain the step whose tool list advertised them.
    step_context: Arc<StepContext>,
    tracker: SharedTurnDiffTracker,
    parallel_execution: Arc<RwLock<()>>,
}
```

`parallel_execution` 是一把**单元互斥锁**（`RwLock<()>`，值本身不携带数据，只表达独占/共享语义）：声明支持并行的工具拿**读锁**并行执行，独占工具拿**写锁**等待，全部监听 `CancellationToken`。配套机制：

- `AbortOnDropHandle`：任务句柄丢弃即中止，取消不需要显式 join
- `ToolCallState` / `SharedTurnDiffTracker`：跨工具调用共享本轮 diff 跟踪，补丁类工具的结果可以合并呈现
- `call_trace`：每次工具调用的追踪记录

失败路径上，`FunctionCallError::Fatal` 直接冒泡为 `CodexErr::Fatal`，其余错误转成失败响应的 Item 回填给模型——**工具失败是给模型看的事实，不是让循环崩溃的异常**。

## Tool Call Recording

`tools/executed_tool_calls.rs` 是一个常被忽略但很重要的模块：它把每次工具调用**记录下来**（`prepare_direct_call` 预登记、`attach_direct_call_to_output` 挂到输出 Item 上）。记录带强引用计数——如果调用没有真正送达模型（`strong_count() == 0`），就不挂载。它服务三件事：审计（谁在什么时候调了什么）、`turn_diff_tracker` 的文件变更汇总、以及多 Agent 场景下子调用的归属。

## Network Approval

`tools/network_approval.rs` 处理**网络访问审批**：沙箱默认禁网，模型发起网络请求时构造 `NetworkApprovalContext`（目标 host），经审批后可产出 `NetworkPolicyAmendment`（对该 host 的 allow / deny 规则）。也就是说网络策略不是静态配置-only，**可以在会话中按 host 动态扩展**，每次扩展都要过人机审批。与 `network-proxy` crate 的分工见 [Sandbox](/docs/CS/AI/LLM/Agent/Product/Codex/Sandbox.md)。

## Unified Exec and Shell

命令执行收敛到 `core/src/unified_exec/` 与 `exec-server`：本地进程（`local_process`）、远端进程（`remote_process`，经 Noise 加密中继）、沙箱内文件系统（`sandboxed_file_system` / `sandboxed_file_open`）都走同一套 `ExecutorFileSystem` 抽象。`shell-command` crate 负责 shell 快照与环境继承（`shell_snapshot` / `exec_env`），`apply-patch` 处理补丁应用。执行服务可代理到远端——这是 Codex Web / 云端任务的地基，见 [MultiAgent](/docs/CS/AI/LLM/Agent/Product/Codex/MultiAgent.md)。

## Built-in Tools

内置工具分几族（以 `core/src/tools/` 与 `tools/` crate 为准）：

| 族 | 代表 | 说明 |
| :--- | :--- | :--- |
| 文件 | read / write / edit | 走 `ExecutorFileSystem`，受沙箱可写根约束 |
| 命令 | shell / exec | 受审批与沙箱双重约束 |
| 计划 | update_plan | 任务清单；多 Agent 场景可按角色省略其指令 |
| 检索 | web_search、file-search | 网络检索受网络审批约束 |
| 协作 | multi_agent_tool、spawn | 派生与等待子 Agent，见 [MultiAgent](/docs/CS/AI/LLM/Agent/Product/Codex/MultiAgent.md) |
| 扩展 | MCP 工具、Skill 脚本 | 经 [Extensions](/docs/CS/AI/LLM/Agent/Product/Codex/Extensions.md) 的链路接入 |

扩展接入必须走主链：被选择 → 纳入 StepContext → 模型可见 → Router/策略验证 → 执行 → Item 回填 → 事件可见。**不让扩展绕过 Harness**，否则会失去日志、取消和审批。

## Links

- [Codex 主入口](/docs/CS/AI/LLM/Agent/Product/Codex/Codex.md) / [Turn：任务生命周期](/docs/CS/AI/LLM/Agent/Product/Codex/Turn.md)
- [Approval：审批](/docs/CS/AI/LLM/Agent/Product/Codex/Approval.md) / [Sandbox：沙箱](/docs/CS/AI/LLM/Agent/Product/Codex/Sandbox.md)
- [Extensions：MCP/Skills/Plugins/Hooks](/docs/CS/AI/LLM/Agent/Product/Codex/Extensions.md)
- [Tools](/docs/CS/AI/LLM/Protocol/Tools.md) — 工具协议的通用讨论

## References

- [openai/codex](https://github.com/openai/codex)
