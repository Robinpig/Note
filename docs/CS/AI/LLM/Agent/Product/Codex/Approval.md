> 版本基线：核实于 2026-10-16，对应 commit `6b991972c5b5`（`main`，2026-10-15）。

## Introduction

审批是 Codex 四层安全模型（沙箱 / 策略 / 审批 / schema）里的**人的层**：沙箱回答「能不能」，审批回答「有没有人允许」。Codex 的实现有两个特点——**异步等待**（不阻塞执行链路，用 oneshot  channel 挂起等决策）与 **fail closed**（等待中断开连接一律按拒绝处理）。2026 年的代码里这条线还长出了三个新能力：可路由给子 agent 的自动评审、按类别细粒度的审批开关、以及信任级别驱动的默认策略。

## Asynchronous Approval

`session/mod.rs:2923` 的 `request_command_approval` 是命令审批的唯一入口：

```rust
pub async fn request_command_approval(
    &self,
    turn_context: &TurnContext,
    kind: ExecApprovalKind,
    ...
    call_id: String,
    approval_id: Option<String>,
    ...
) -> ReviewDecision
```

流程：创建 oneshot channel → 以 `effective_approval_id` 登记等待者（`insert_pending_approval`）→ 发 `ExecApprovalRequest` 事件给 UI → `rx_approve.await.unwrap_or(ReviewDecision::Abort)`。

最后那行就是 **fail closed** 的全文：发送端被丢弃（连接断开、Turn 被取消）时 `await` 返回 `Err`，一律映射为 `Abort`，绝不偷偷放行。请求按 `call_id` + `approval_id` 双键匹配——`approval_id` 标识**子命令回调与 stdin 写入**（一条命令执行期间可能多次回调审批），命令级审批用 `call_id`。

文件修改走独立的 `request_patch_approval`（`mod.rs:3018`）通道，事件是 `ApplyPatchApprovalRequest`，携带 `changes`（路径 → 文件变更）与 `grant_root`（授权根）。命令与补丁在 UI 上按风险分别呈现。

审批请求事件还携带丰富的上下文供人决策：`parsed_cmd`（解析后的命令结构）、`reason`、`network_approval_context`（网络审批）、`proposed_execpolicy_amendment`（建议放行的命令前缀规则）、`additional_permissions`（额外文件权限）、`plugin_attribution`（这个命令来自哪个插件的哪个脚本）。

## ReviewDecision

决策不是一个布尔，而是 `protocol/approvals.rs` 里的枚举：

| 变体 | 语义 |
| :--- | :--- |
| `Approved` | 仅此一次放行 |
| `ApprovedForSession` | 本会话内放行同类请求 |
| `Abort` | 拒绝并中断 |
| `NetworkPolicyAmendment` | 放行并把该 host 写入网络策略（allow 或 deny） |
| `ApprovedExecpolicyAmendment` | 放行并把命令前缀写入 execpolicy 规则 |

`available_decisions` 字段让客户端知道**这次审批能选什么**；老客户端不填时，服务端用 `default_available_decisions` 按请求类型派生（例如网络审批默认给 `Approved` + `ApprovedForSession` + 可选 amend + `Abort`）。

## AskForApproval

策略侧（`protocol/protocol.rs:1097`）的 `AskForApproval` 有四态：

| 变体（config 值） | 语义 |
| :--- | :--- |
| `UnlessTrusted`（`untrusted`） | 不信任项目的内部策略：命令默认要审批，除非 execpolicy 规则显式放行 |
| `OnRequest`（默认，别名 `on-failure`） | 模型自行决定何时请求审批 |
| `Granular`（`granular`） | 按类别细粒度开关，见下 |
| `Never` | 从不问人；失败直接返回给模型 |

两个容易踩的点：

- **`untrusted` 在 `config.toml` 里已不再支持**（`core/src/config/mod.rs:230` 明确报错 "approval_policy = \"untrusted\" is no longer supported"）——它降级为**内部策略**，由 `TrustLevel` 自动套用，用户配置里应该删掉这一行。
- **`on-failure` 是 `on-request` 的 serde 别名**，不是独立模式：老配置写 `on-failure` 现在等价于默认行为。

`Granular(GranularApprovalConfig)` 把审批分成五个可独立开关的类别（`true` = 允许弹出，`false` = 该类请求自动拒绝、不打扰用户）：`sandbox_approval`（沙箱逃逸与命令审批）、`rules`（execpolicy `prompt` 规则触发）、`skill_approval`（skill 脚本执行触发）、`request_permissions`（`request_permissions` 工具触发）、`mcp_elicitations`（MCP elicitation 提示）。

## ApprovalsReviewer

2026 年新增的一层：**审批可以路由给别人审**。`config_types.rs:183` 的 `ApprovalsReviewer`：

| 值 | 语义 |
| :--- | :--- |
| `user`（默认） | 交给人 |
| `auto_review`（别名 `guardian_subagent`） | 交给一个精心提示的子 agent：收集相关上下文、按风险决策框架给出批准/拒绝 |

它覆盖的场景包括沙箱逃逸、被拦截的网络访问、MCP 审批提示与 ARC 升级。注意这是**审批路由**，不是沙箱降级——auto_review 否掉的请求同样是 `Denied`/`Abort`。

## TrustLevel

`config_types.rs:642` 的 `TrustLevel`（`trusted` / `untrusted`）是**项目目录级**的信任标记，它同时决定该目录下套用的 approval policy 与 sandbox mode——这就是 `untrusted` 从用户配置消失后的去处：不信任项目自动落入保守策略，不需要用户手写。

## Links

- [Codex 主入口](/docs/CS/AI/LLM/Agent/Product/Codex/Codex.md) / [Turn：任务生命周期](/docs/CS/AI/LLM/Agent/Product/Codex/Turn.md)
- [Sandbox：沙箱](/docs/CS/AI/LLM/Agent/Product/Codex/Sandbox.md) — 审批管「该不该」，沙箱管「能不能」
- [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md) — 沙箱与权限的两层之分、各家默认值对照
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) — 四层安全模型与 fail closed 原则

## References

- [openai/codex](https://github.com/openai/codex)
