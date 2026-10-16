> 版本基线：核实于 2026-10-16，对应 commit `6b991972c5b5`（`main`，2026-10-15）。

## Introduction

Codex 的扩展面在 2025–2026 年间从「MCP 一个口子」长成了五套并存的机制：**MCP**（标准工具接入）、**Skills**（受控指令注入）、**Plugins**（打包分发单元）、**Hooks**（生命周期回调）、**Connectors**（应用连接器）。它们的共同约束是：接入必须走主链——被选择 → 纳入 StepContext → 模型可见 → Router/策略验证 → 执行 → Item 回填 → 事件可见。**不让扩展绕过 Harness**，否则失去日志、取消和审批。

## MCP

MCP 相关代码横跨多个 crate，是扩展面里最重的：

| 落点 | 职责 |
| :--- | :--- |
| `codex-mcp` crate | MCP 客户端核心：`McpConfig`、`McpServerRegistration`、`McpProtocolMode`、`ResolvedMcpCatalog`、`McpPluginAttribution`，以及 `DEFAULT_OPTIONAL_MCP_STARTUP_GRACE`（可选 server 的启动宽限） |
| `rmcp-client` | 底层 RMC 协议客户端 |
| `session/mcp*.rs` | 运行时接线：`mcp_runtime`（生命周期）、`mcp_prewarm`（预热）、`mcp_refresh`（运行中刷新） |
| `core/src/mcp*.rs` | 工具侧落地：`mcp_tool_call`、`mcp_tool_exposure`（暴露给模型）、`mcp_tool_approval_templates`（审批模板）、`mcp_skill_dependencies`（skill 对 MCP 的依赖）、`mcp_openai_file` |
| `elicitations` | MCP elicitation：服务端可以向用户发起结构化提问（`ElicitationRequest` 有 `openai/userVerification` 与 `Form` 两种模式），也受 `Granular` 审批的 `mcp_elicitations` 开关控制 |

MCP 工具与内置工具走同一条路由与审批链——`mcp_tool_approval_templates` 的存在说明 MCP 调用同样要过人机审批，且审批提示可以按服务端定制。MCP 协议本身见 [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)。

## Skills

Skill 是「受控的指令注入」：一个目录、一份说明，模型按需加载。代码分布：

- **`skills` crate**：`parser`（解析 SKILL 说明）、`loading`（从多个 root 发现与加载）、`selection`（选用，含 `select_skills_from_mentions` 显式提及路径）、`mentions`（输入里的 @提及语法）、`metadata` / `model` / `name_counts` / `invocation` / `interface`
- **`core/src/skills.rs`**：host 侧装配——`SkillScope` 标注来源、`detect_implicit_skill_invocation` **隐式调用检测**（不显式 @ 也可能触发）、`record_plugin_turn_usage` 记录插件 skill 的本轮用量；发现逻辑适配多环境（`TurnEnvironmentSnapshot` 的主仓库优先）
- **`skills_config.rs`**：配置面。`SkillsConfig` 三个键——`bundled`（内置 skill 包，默认开启）、`include_instructions`（是否注入自动 skill 指令块）、`max_context_tokens`（**可用 skill 目录的最大 token 数，默认取模型上下文窗口的 2%，设置时上限 10000**）

**2% 这条最反直觉**：skill 的 description 会进每轮上下文，装得越多每轮越贵；超过预算时 Codex **静默省略**部分 skill 而不是报错。`skills.config` 支持按 `path` 或 `name` 选择器启用/禁用单个 skill，**后出现的规则覆盖先出现的**（同名选择器去重，路径选择器即使当前没有匹配 skill 也保持有效）。Skill 的通用规范见 [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md)。

## Plugins

插件是**打包分发单元**（`plugin` crate 的 `PluginManifest`）：一个插件可以同时带 skills、MCP servers、apps 与 hooks：

```
PluginManifest
├── name / version / description / keywords
├── paths
│   ├── skills: Vec<...>            # 随包分发的 skill
│   ├── onboarding_skill            # 首次使用引导 skill
│   ├── mcp_servers                 # 内嵌或引用的 MCP server 声明
│   ├── apps                        # 应用（Connector 类）
│   └── hooks                       # 内嵌或引用的 hooks 声明
└── interface                       # 面向模型与 UI 的元数据
    ├── display_name / 三级描述 / developer_name / category / capabilities
    ├── website_url / privacy_policy_url / terms_of_service_url
    ├── default_prompt / brand_color / composer_icon / logo / screenshots
```

`interface` 的存在说明插件面向**市场分发**（展示、品牌、合规链接都在清单里）。加载与目录在 `core-plugins` crate：`catalog`（目录）、`discoverable`（可发现性）、`executor_provider` / `executor_hooks`（执行与 hooks 提供方）、`agent_plugin_manifest` / `agent_plugin_mcp_overlay`（agent 插件清单与 MCP 覆盖）、`app_mcp_routing`、`git_policy`。会话侧 `session/plugin_selection.rs` 与 `active_plugin_inventory_tests.rs` 管选用与生效清单；用户输入里的显式插件提及由 `collect_explicit_plugin_ids` 收集（见 [Turn](/docs/CS/AI/LLM/Agent/Product/Codex/Turn.md)）。

## Hooks

Hooks 是**生命周期回调**，让外部逻辑在特定时机观察或拦截执行（`hooks` crate）：

- **三态结果**（`HookResult`）：`Success` / `FailedContinue`（失败但继续执行后续 hook 与操作）/ `FailedAbort`（失败且中止操作）——失败不必然中断，由 hook 自己声明
- **载荷**（`HookPayload`）：`session_id`、`cwd`、`client`、`triggered_at`、`hook_event`
- **事件**（`HookEvent`，snake_case 序列化）：当前 Rust 侧实现的事件是 `after_agent`（带 `thread_id`、`turn_id`、`input_messages`、`last_assistant_message`）；配置层（`config/src/hook_config.rs`、`hooks/src/config_rules.rs`）还认更多事件名（如 `SessionStart` 这类非 matcher 形式的事件）
- **执行侧**：`core/src/hook_runtime.rs`（运行时）、`hook_mcp_executor.rs`（经 MCP 执行的 hook）、`output_spill.rs`（大输出落盘，`hooks/src/output_spill.rs` 同源）、`legacy_notify.rs`（旧通知通道兼容）
- **异步语义**：hook 可能跨 Turn 才完成，`run_turn` 每轮开始前 `drain_async_hook_results` 先落账（见 [Turn](/docs/CS/AI/LLM/Agent/Product/Codex/Turn.md)）

插件清单里可以内嵌 hooks（`PluginManifestHooks::Inline`）或引用 hooks 文件（`Paths`）——插件与 hooks 在分发层是打通的。

## Connectors

`connectors` crate 连接外部应用（Connector 类集成）：`connector_runtime`（运行与持久化）、`metadata_store` / `directory_cache`（元数据与目录缓存）、`app_tool_policy`（应用工具策略）、`filter` / `merge`（工具过滤与合并）、`plugin_config`（插件化配置）。与 `core/src/connectors.rs` 的会话侧装配配合——连接器暴露的工具同样过 Router 与审批链。

## Links

- [Codex 主入口](/docs/CS/AI/LLM/Agent/Product/Codex/Codex.md) / [Turn：任务生命周期](/docs/CS/AI/LLM/Agent/Product/Codex/Turn.md)
- [Tools：工具系统](/docs/CS/AI/LLM/Agent/Product/Codex/Tools.md) / [MultiAgent：多 Agent 与记忆](/docs/CS/AI/LLM/Agent/Product/Codex/MultiAgent.md)
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md) / [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) — 扩展必须走主链的原则出处

## References

- [openai/codex](https://github.com/openai/codex)
