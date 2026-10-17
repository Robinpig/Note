## Introduction

Hermes 的整体结构是**三层骨架 + facade/siblings 模块拆分 + 两条贯穿不变式**。理解任何一块之前，先记住这两条设计透镜（来自仓库根 `AGENTS.md`）：

- **每会话 prompt 缓存神圣不可侵犯**：会话中途变动历史上下文、切换 toolset、重载记忆或重建系统提示，都会打碎缓存前缀、成倍放大用户成本。唯一例外是上下文压缩。因此 slash 命令若要改系统提示态，默认推迟到下一会话，仅以 `--now` 显式 opt-in（如 `skills install --now`）。
- **核心窄腰，能力在边缘**：每个模型工具都随每次 API 调用下发，所以新增核心工具的门槛极高。新能力应作为 CLI 命令 + Skill、service-gated tool（`check_fn` 回答可达性/opt-in，绝不在每会话暴露）、插件或 catalog 里的 MCP server 出现，而非膨胀 core。

> 事实来源：仓库根 `AGENTS.md` 与 `hermes_cli/AGENTS.md`、`agent/AGENTS.md`。基线 main @ 2026-10-17。

## Three-Layer Backbone

| 层 | 组件 | 职责（已核实） |
| :--- | :--- | :--- |
| 入口层 | CLI（`hermes`）/ TUI / 网关 / 桌面端 / ACP / Batch Runner / API Server / Python Library | 接收人与系统的请求，适配不同交互形态 |
| 核心层 | `AIAgent`（`run_agent.py` facade）：`system_prompt`（三层组装）、`model_tools`（Provider Resolution）、`toolsets`（Tool Dispatch） | 组装提示/上下文/记忆/画像/Skill，选模型，调度工具 |
| 后端层 | `hermes_state`（SQLite + FTS5）、Tool Backends、终端后端 | 持久化全部会话；让 Agent 真正进入环境执行动作 |

三种入口（CLI Session、Gateway Message、Cron Job）数据流不同，却共享同一套执行、存储、记忆与 Skill 机制——**轨迹统一保存，Evolve Loop 才能跨入口工作**。

## Facade + Siblings Layout

曾经的「god file」一律拆成 **facade（公开入口 + 其他包 import 的名字）+ 同名 `<stem>_<topic>.py` siblings**，每个 sibling 只管一个主题：

- `run_agent.py`（AIAgent facade）↔ `agent/turn_*.py`、`agent/compression_facade.py` …
- `cli.py`（HermesCLI REPL + slash 分发）↔ `hermes_cli/cli_*_mixin.py`
- `hermes_state.py`（SessionDB facade）↔ `hermes_state_*.py`（消息、会话、WAL、搜索、gateway、压缩、维修等 30+ 个 sibling）
- `gateway/run.py` ↔ `gateway/run_*.py`（startup / adapters / inbound / turn / busy / notifications / shutdown …）
- `tools/mcp_tool.py` ↔ `mcp_tool_*.py`；`tools/registry.py` 无依赖、被所有工具 import

规则：sibling 在函数内部 late-import facade（绝不模块级循环）；patch 要打在「生产代码真正读取的那个模块」——打在定义模块上若 facade 是 seam，则静默通过。复杂度按单元 ratchet（`scripts/code_health/config.py`）：新函数 CC ≤ 20、≤ 300 行、嵌套 ≤ 6；文件 ≤ 2000 行；已超限的单元只能下降。

## Four Surfaces, One Core

同一套 agent core 暴露给四种表面，工具集按**会话**而非进程决定是否可用：

- **CLI**：`cli.py` + `hermes_cli/cli_*_mixin.py`（REPL、slash 注册表、curses 选择器、Rich 渲染 banner/面板、prompt_toolkit 输入与补全）。
- **TUI**：`ui-tui/`（Ink/TypeScript 终端 UI）+ `tui_gateway/`（Python JSON-RPC 后端，也服务桌面端）。桌面端 `apps/desktop`（Electron + `apps/shared`）。
- **Messaging Gateway**：`gateway/` 单进程接约 27 个平台适配器，详见 [Gateway](/docs/CS/AI/LLM/Agent/Product/Hermes/Gateway.md)。
- **API Server / ACP**：`gateway/platforms/api_server*` 提供 HTTP `/v1` + OpenAI 兼容路由；`acp_adapter/` 把 Hermes 暴露为 Agent Client Protocol 服务端（含 `permissions`、`edit_approval`），可被外部 IDE/客户端驱动。

> 「Surface capability 是会话的属性，不是进程环境」：桌面面板、应用内浏览器、消息反应这类「只有对面是谁才有意义」的工具，必须放进具名 toolset（`desktop_ui`、`project`），由会话的 platform 决定加载，绝不靠 `HERMES_DESKTOP=1` 之类的 env 开关（详见 [Tools](/docs/CS/AI/LLM/Agent/Product/Hermes/Tools.md)）。

## Process Model: One Process, Many Profiles

Hermes 用 **profiles** 实现多实例隔离：`~/.hermes/config.yaml`（设置）、`.env`（仅密钥）、`logs/`（日志），全部经 `get_hermes_home()` 做 profile-aware 路径解析。关键约束：

- **一个进程服务多个 profile**。`os.environ`、模块全局、import-time 值都只持有「启动 profile」的值；任何在 turn 之外运行的代码（boot 探针、eviction、ticker、延迟回调、RPC 方法、线程跳变、子进程派生）都必须显式绑定所属 profile scope——未绑定的读取是静默的默认 profile 泄漏。
- **Secret scope 失败即关闭**（`agent/secret_scope.py::get_secret` 在 `set_multiplex_active(True)` 之后才放行；否则抛 `UnscopedSecretError`）。网关、cron、migrate、`serve` 都会设置它；新多 home 主机也必须设置，否则所有守卫静默失效。隔离发生在 profile **之间**，子进程通过 `copy_context` 继承。
- `gateway.multiplex_profiles` 默认 **on**，但 `GatewayConfig` 保留 unset 标志，由 `resolve_multiplex_mode` 每次启动裁定（默认 profile / ≥2 profile / 无非独立次级网关 / 无 preflight 阻塞 / 可迁移主机 → True）。

## Update Pipeline

`hermes update` 是事务化的 `plan → snapshot → apply → restart-per-kind → verify → report`：快照覆盖**每个** profile 且文件集一致（从不是部分或分层）；重启是 fleet-wide 且 drain-first，按各单元所在 home 界定范围；post-commit 失败走 follow-up（exit 0），回执写入 `logs/update_receipts/`；绝不拿 pulled code 在 pre-pull 解释器里跑。`update_handoff.py` / `update_serve_obligations.py` 是冻结兼容面——删名字会中途 brick 升级。

## Deployment

工具不在笔记本上裸跑，而是跑在终端后端之一（见 [Tools](/docs/CS/AI/LLM/Agent/Product/Hermes/Tools.md)）：local / Docker / SSH / Singularity / Modal / Daytona，README 另称含 Vercel Sandbox 共 7 种。其中 Modal / Daytona 提供 **serverless 持久化**——环境空闲时休眠、按需唤醒，idle 期间几乎零成本。还支持 nix（`flake.nix`）、Docker（`Dockerfile` + `docker-compose.yml`）、Windows 原生（PowerShell 安装器 / MSIX）、Android Termux（签名 APT 仓库）。生产重建容器时，学到的 Skill/记忆靠快照（`snapshot.sh` 带凭据过滤器，自动排除 `.env`/token/secret）存活。

## Links

- [Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md)
- [AgentLoop](/docs/CS/AI/LLM/Agent/Product/Hermes/AgentLoop.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/Hermes/Tools.md)
- [Gateway](/docs/CS/AI/LLM/Agent/Product/Hermes/Gateway.md)
- [Memory](/docs/CS/AI/LLM/Agent/Product/Hermes/Memory.md)
- [Extensions](/docs/CS/AI/LLM/Agent/Product/Hermes/Extensions.md)

## References

- [Hermes Agent 仓库根 AGENTS.md](https://github.com/NousResearch/hermes-agent/blob/main/AGENTS.md)
- [Hermes Agent 架构文档](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture)
- [Hermes Agent 安装文档](https://hermes-agent.nousresearch.com/docs/getting-started/installation)
