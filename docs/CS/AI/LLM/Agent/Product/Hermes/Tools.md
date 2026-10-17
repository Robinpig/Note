## Introduction

Hermes 的工具系统遵循「**footprint ladder**」：先扩展现有代码 → CLI 命令 + Skill → service-gated tool（`check_fn` 回答可达性/opt-in，绝不在每会话暴露）→ 插件 → catalog 里的 MCP server → 最后才考虑新核心工具（fundamental、广有用、否则不可达）。核心工具因为随每次 API 调用下发，门槛最高。

> 事实来源：`tools/AGENTS.md`、`tools/registry.py`、`toolsets.py`、`model_tools.py`、`tools/delegate_tool.py`。基线 main @ 2026-10-17。

## Registry and Discovery

`tools/registry.py` 零依赖、被每个工具文件 import；每个 `tools/*.py` 在 import 期调用 `registry.register()`。`model_tools.py::discover_builtin_tools()` 触发发现，`run_agent.py` / `cli.py` / `batch_runner.py` / `environments/` 消费之。任何带顶层 `registry.register()` 的 `tools/*.py` 都会被**自动 import**——没有手工 import 列表。一整个包的工具从 `tools/<pkg>/tool.py` 注册（discovery 只在包内扫这一个文件），包内其他文件天然是库。

- 所有 handler 返回 **JSON 字符串**；唯一例外是「把像素交给模型」的工具，可返回多模态信封 `{"_multimodal": True, "content": [text, image_url…], "text_summary": str}`，图片路径必须走 `vision_tools._native_tool_result_images`，绝不用私有 vision 检查。
- 加核心工具 = 2 个文件：`tools/your_tool.py`（定义 + `registry.register(name=…, toolset=…, handler=…, check_fn=…, requires_env=[…])`）+ `toolsets.py`（把名字加进 `_HERMES_CORE_TOOLS` 或新 toolset）。`_HERMES_CORE_TOOLS` 是每个平台基础 toolset 默认继承的捆绑集，不是死代码。
- Schema 描述的「禁例」：不能点名其他 toolset 的工具（如 `browser_navigate` 写"prefer web_search"），跨引用在 `model_tools.py::get_tool_definitions()` 里动态注入。
- **Paths 用 `display_hermes_home()`（schema 构建于 import 期，multiplex 下显示启动 home，仅显示用）；状态文件用 `get_hermes_home()`（call 期，绝不 `Path.home()/.hermes` 或模块常量）**，让每个被服务的 profile 拿到自己的状态。

## Toolsets

`toolsets.py` 单一 `TOOLSETS` 字典，精确 **28 个键**（官方文档明确「不要写死列表到测试里」）：

`browser, clarify, code_execution, cronjob, debugging, delegation, discord, discord_admin, feishu_doc, feishu_drive, file, image_gen, kanban, memory, messaging, moa, rl, safe, search, session_search, skills, terminal, todo, tts, video, vision, web, yuanbao`。

按能力分组（非官方分组，便于索引；仅归类、不臆测各 toolset 内部语义）：

| 分组 | toolset 键 |
| :--- | :--- |
| 代码执行 | `terminal`, `code_execution`, `debugging`, `file` |
| 检索与记忆 | `search`, `web`, `session_search`, `memory`, `vision`, `browser` |
| 消息与平台集成 | `messaging`, `discord`, `discord_admin`, `feishu_doc`, `feishu_drive`, `yuanbao` |
| 任务编排 | `cronjob`, `kanban`, `todo`, `delegation`, `rl`, `moa`, `safe` |
| 多模态生成 | `image_gen`, `tts`, `video` |
| 技能与澄清 | `skills`, `clarify` |

> GUI 网关另有 `desktop_ui` / `project` 两个命名 toolset，经 `_load_enabled_toolsets(platform)` 折叠进，不出现在上面的核心 `TOOLSETS` 里（`tools/AGENTS.md`）。当 `browser.backend` 为 `browser-use` 时，`browser_exec` 取代其他 browser 工具。

按平台启用/禁用：`hermes tools`（curses）或 `config.yaml` 的 `tools.<platform>.enabled/disabled`。

## Terminal Backends

工具的终端不在笔记本上裸跑，而是跑在 `tools/environments/` 的终端后端之一：`terminal_tool_backends.py` / `tool_backend_helpers.py` 列出 **local、docker、ssh、modal、daytona、singularity** 六种（README 另称含 Vercel Sandbox 共 7 种）。Modal / Daytona 提供 serverless 持久化——空闲休眠、按需唤醒，idle 近乎零成本。远程后端文件可见性问题在 mount 处修复，而非加工具。

## Browser, MCP, TTS

- **Browser**：`browser_tool_*.py`（cdp / cloud / install / lifecycle / session / real_profile / vision）。原生 vision 嵌入是「历史」不是一次性载荷——`vision_tools._vision_analyze_native` 把图片烤进工具结果、之后每次 API 调用都重发；尺寸与重复策略在 `vision_tools_history_budget.py`（`vision: embed_target_bytes`、`max_calls_per_image`）。
- **MCP 客户端**：`mcp_tool_*.py`（config / discovery / transport / registration / content / errors）。**MCP 信任是 per-profile 记录**：`mcp_tool_registration.py::_record_scope_trust` 按 home 建键；次级 profile 绝不采用启动 profile 对同一 server 名的信任（见 [Extensions](/docs/CS/AI/LLM/Agent/Product/Hermes/Extensions.md)）。
- **TTS**：`tts_tool_providers.py` / `tts_command_provider.py`。

## Every Spawn Goes Through One Env Builder

子进程（terminal、`execute_code`、后台进程、delegation 子、ACP/MCP stdio 子）的环境统一由 `environments/local.py::build_subprocess_env`（+ `hermes_constants.apply_subprocess_home_env` + `env_passthrough.py::resolve_passthrough_value`）构建。**为代表被服务 profile 行动的子进程**用 `served_profile_child_env(target_home=, inherit_credentials=)`：丢弃启动 profile 的 `.env` / `TERMINAL_*` 残留（`strip_launch_profile_env`），钉死目标 home，只叠加目标自己的密钥。`os.environ.copy()` 会钉死启动 profile；contextvars 不跨进程，所以要在 `Popen` 前解析。`UnscopedSecretError` 是 spawn-site bug，不是加 environ fallback 的理由。

**后台进程 teardown 先通知父进程**：`process_registry_termination.py::ProcessTerminationMixin._terminate_host_pid` 先快照后代、只 SIGTERM 记录的父进程、等 `terminal.daemon_term_grace_seconds` 让其退出并收割子进程，再 SIGTERM 快照幸存者、最后 SIGKILL 仍无视两者的——绝不在父进程之前 SIGTERM 后代（否则浏览器 zygote 中途被杀会把 exit 0 变成 SIGTRAP core dump）。

## Delegation: Subagents

`tools/delegate_tool.py` 派生一个**隔离上下文 + 终端会话**的子代理；父进程等摘要，除非 `background=true`（返回 delegation id，经 async-delegation 完成队列回填）。形态：单发（`goal` + 可选 `context` / `toolsets`）或批处理（`tasks: […]`），并发由 `delegation.max_concurrent_children` 封顶（**默认 10**；异步派发超出部分同步跑，下限 1、无上限）。后台批处理默认作为一个完成返回；`delegation.independent_completions` 拆成完成**单元**（`delegate_tool_dispatch._units_of`）：同 `group` 的 task 合并报告，未分组的各自独立完成。

- **角色**：`leaf`（默认，无 `delegate_task`/`clarify`/`memory`/`send_message`/`cronjob`，保留 `execute_code`）与 `orchestrator`（保留 `delegate_task`，由 `delegation.orchestrator_enabled` 门控、受 `delegation.max_spawn_depth` **默认 1（扁平；2 才启用 orchestrator→leaf，3+ 更深）** 约束）。
- 配置旋钮：`max_concurrent_children`、`independent_completions`、`max_spawn_depth`、`child_timeout_seconds`、`orchestrator_enabled`、`subagent_auto_approve`、`inherit_mcp_toolsets`、`max_iterations`。
- **后台 delegation 是进程局部的**；必须跨重启存活的工作用 `cronjob` 或 `terminal(background=True, notify_on_complete=True)`。`heartbeat=N` 在同一次派生上发 `heartbeat` 事件（仅 delta 输出，`HEARTBEAT_MIN_SECONDS` 下限，所有会话共用一个 daemon 定时器线程）。
- **Stop fan-out**：turn 的硬中断只触达 `_active_children`；后台单元在派发时即分离，所以每个 stop 表面（网关 `/stop` 忙/闲路径、TUI `session.interrupt`、ACP `cancel`、CLI `/stop` via `interrupt_all`）也调用 `async_delegation.interrupt_for_session`。深度 > 0 的 delegation 总是同步的，中断递归穿过子自己的 `_active_children` fan-out；被中断项的 `summary` 是子最后的真实 assistant 文本。

## Approval and Floors

`tools/approval*.py` 覆盖命令审批：`approval`（门面）、`approval_context`、`approval_detection`、`approval_floors`（基线门槛）、`approval_gateway_wait`、`approval_human_wait`、`approval_prompt`、`approval_smart`（分类器）、`approval_yolo`。`security.tirith_*` 在执行前扫描同形异义 URL、pipe-to-shell、终端注入、环境变量篡改，`tirith_fail_open` 控制不可用时是否放行。详见 [Memory](/docs/CS/AI/LLM/Agent/Product/Hermes/Memory.md) 的 secret scope 与 [Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md) 的「能力属于会话而非进程」原则。

## Links

- [Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md)
- [Architecture](/docs/CS/AI/LLM/Agent/Product/Hermes/Architecture.md)
- [AgentLoop](/docs/CS/AI/LLM/Agent/Product/Hermes/AgentLoop.md)
- [Skills](/docs/CS/AI/LLM/Agent/Product/Hermes/Skills.md)
- [Memory](/docs/CS/AI/LLM/Agent/Product/Hermes/Memory.md)
- [Extensions](/docs/CS/AI/LLM/Agent/Product/Hermes/Extensions.md)

## References

- [Hermes Agent tools/AGENTS.md](https://github.com/NousResearch/hermes-agent/blob/main/tools/AGENTS.md)
- [Hermes Agent Tools & Toolsets 文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/tools)
- [Hermes Agent 添加工具文档](https://hermes-agent.nousresearch.com/docs/developer-guide/adding-tools)
