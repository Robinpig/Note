## Introduction

Hermes 的扩展面与「核心窄腰」不变式同源：**插件绝不碰 core**。新能力优先走 CLI 命令 + Skill、service-gated tool、插件或 catalog 里的 MCP server，而非塞进 `AIAgent`。本篇覆盖插件种类与发现机制、`plugin-catalog` 社区生态、cron（含 kanban 多 agent 工作队列）与 context files。机制总览见 [Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md)。

> 事实来源：`plugins/AGENTS.md`、`plugin-catalog/`、`cron/AGENTS.md`。基线 main @ 2026-10-17。

## Plugins Never Touch Core（Teknium, 2026-05）

插件住自己的目录、在框架提供的 ABC / hook / `ctx` 表面上工作。插件**严禁**修改 `run_agent.py`、`cli.py`、`gateway/run.py`、`hermes_cli/main.py` 等。若它需要框架没有的能力，**拓宽通用插件表面**（新 hook、新 `ctx` 方法）让插件用——绝不在 core 里硬编码插件特定逻辑（PR #5295 移除了 95 行硬编码的 honcho argparse）。插件 setup 走 `hermes memory setup` → `provider.post_setup(hermes_home, config)`，绝不开平行顶级命令。没有具体消费者的 hook 是投机基础设施，会被拒。

## In-Tree Policy（2026 年持续收紧）

- **2026-05 起不再新增 in-tree memory provider**：`plugins/memory/` 已关闭。新后端以独立 repo 实现同一 `MemoryProvider` ABC，经同一发现路径、由 `hermes memory setup` / `post_setup()` 集成（详见 [Memory](/docs/CS/AI/LLM/Agent/Product/Hermes/Memory.md)）。
- **其它离开 core 的特性**：Home Assistant platform + toolset、Spotify toolset（2026-10）→ `plugin-catalog/homeassistant.yaml` / `spotify.yaml`，保留名字/config/env，并在 `hermes_cli/left_core_migration.py::LEFT_CORE` 记一行（catalog 插件 + 只读「此 home 在用」谓词）；`hermes update` 与 agent/gateway start 为用过的 home 自动装插件。安装与转换 core 时代状态是分开的两步。Core 特例变成插件设的 `PlatformEntry` seam（`trusted_inbound`、`display_tier`、`shared_env_prefixes`），**绝不**名字检查。
- **2026-06 起不再新增第三方产品插件**：可观测性/metrics 后端、vendor SaaS 连接器、分析看板、付费服务捆绑都作为独立插件 repo 发布（`~/.hermes/plugins/` 或 pip entry point），在 Discord `#plugins-skills-and-skins` 推广。理由：每个被吸收的产品都是对快变 core 的维护负担、且后端不在我们掌控。`kanban/`、`disk-cleanup/` 是先例不是邀请（Langfuse 已迁出到官方 catalog 插件）。关掉这类 PR 是耦合决策，非质量评判。
- 参考/docs-companion 插件（`example-dashboard`、`strike-freedom-cockpit`、`plugin-llm-example`、`plugin-llm-async-example`）住在 [`hermes-example-plugins`](https://github.com/NousResearch/hermes-example-plugins)，不在本树。

## Plugin Catalog（`plugin-catalog/`，2026-09）

**树外插件的唯一发现系统**。每个条目一个 YAML，**强制 40-hex SHA pin**，经 PR 人工合并（`plugin-catalog/README.md` = 准入政策，逐字镜像到 `website/docs/developer-guide/plugins/catalog-submission.md`）。当前 **645 个**条目。

- `removed.yaml` 是 kill list——每个安装路径（CLI、dashboard、TUI）都拒绝匹配（repo URL 按 canonical `host/owner/repo` 比较，所以 `git@`/`ssh://`/`www.` 拼写都匹配）；只有 CLI 有响亮的 `--allow-removed`，它记在 install record 上，是 update/enable/load 时唯一豁免同一检查的东西（`gate_manifest`）。
- Catalog provenance 住在 installer 拥有的 `.install-metadata.json` record（`catalog` 块，sha = 检出的 commit），**绝不**在树里——树内 `.hermes-catalog.json` 只是 Desktop 读「在此安装」的便利副本，Python 永不信任它（仓库可发伪造版）。
- 代码：`hermes_cli/plugin_catalog.py`（加载器，从 docs build 发布的 `/docs/api/plugin-catalog.json` 实时刷新，树内 fallback）、`hermes_cli/plugins_cmd_catalog.py`（解析、`.hermes-catalog.json` provenance sidecar、search/info/validate、update 时 re-pin、dashboard/TUI payload）。**绝不加第二个名字索引**：裸名经 catalog 解析或报错。

## Plugin Kinds & Discovery

| 种类 | 位置 | 发现 | 备注 |
| :--- | :--- | :--- | :--- |
| General | `plugins/<name>/`、`~/.hermes/plugins/`、`./.hermes/plugins/`、`pip` entry points | `PluginManager`（`hermes_cli/plugins.py`），later-wins | `register(ctx)` 注册 hooks（`pre_tool_call`、`post_tool_call`、`pre_llm_call`、`post_llm_call`、`on_session_start`、`on_session_end`）、tools（`ctx.register_tool`）、CLI 子命令（`ctx.register_cli_command`——argparse 树在 startup 接进 `hermes`，无 `main.py` 改动）、语言包（`provides_locales` 在 manifest 自动注册 `locales/<lang>[.tui|.desktop].yaml` via `ctx.register_locale_dir`） |
| Memory provider | `plugins/memory/<name>/` | `plugins/memory/__init__.py`：bundled → `$HERMES_HOME/plugins/` → `./.hermes/plugins/`（opt-in `HERMES_ENABLE_PROJECT_PLUGINS`）→ `hermes_agent.memory_providers` entry points；**bundled-first** | 由 `memory.provider` 按名激活，所以 drop-in 目录不能遮蔽已发布者（与 general 的 later-wins 相反）。枚举不 import。`MemoryProvider` ABC（`agent/memory_provider.py`），`agent/memory_manager.py` 编排 |
| Model provider | `plugins/model-providers/<name>/` | `providers/__init__.py._discover_providers()`，**lazy**，首次 `get_provider_profile()`/`list_providers()` 时；bundled → `$HERMES_HOME/plugins/model-providers/` → legacy `providers/<name>.py` | `__init__.py` 在 load 时调 `providers.register_provider(ProviderProfile(...))`；**last-writer-wins**，用户插件覆盖 bundled profile。`PluginManager` 记 `kind: model-provider` manifest 但**不 import 它们**（会双重实例化）；无 `kind:` 的 manifest 按 source 启发式自动 coerce |
| Context engine / image-gen / others | `plugins/context_engine/`、`plugins/image_gen/` … | ABC + orchestrator + 每插件目录 | 接进 `agent/context_engine.py`、`agent/image_gen_provider.py` |
| Platform adapters | `plugins/platforms/<name>/adapter.py` | 网关 | Token-lock 与 scoped-secret 规则在 `gateway/AGENTS.md`（`irc`、`feishu` 是 canonical） |

当前规模：**41 个 model-provider**（nous / openrouter / anthropic / gemini / bedrock / azure-foundry / vertex / deepseek / qwen / kimi / stepfun / minimax / xiaomi / tencent-tokenhub / xai / openai-codex / custom / router …）、**65 个 optional-mcp**、**13 个内置 Skill 类目 + 23 个 optional-skills 类目**（见 [Skills](/docs/CS/AI/LLM/Agent/Product/Hermes/Skills.md)）、约 27 个消息平台适配器（Telegram/Discord/Slack/WhatsApp/Signal/Email/WeCom/DingTalk/Feishu/WeiXin/QQBot/YuanBao/Teams/Matrix/A2A/SMS/IRC …，外加 `gateway/platforms/` 的 `api_server` 基础设施、webhook、tcp_site、msgraph）。

**发现时机坑**：`discover_plugins()` 只作为 import `model_tools.py` 的副作用运行。不先 import `model_tools.py` 就读插件状态的代码必须显式调 `discover_plugins()`（幂等）。Hook 从 `model_tools.py`（pre/post tool）与 `run_agent.py`（lifecycle）触发。非强制的 `discover_plugins()` 在 `_discovered` 上短路；每个 mid-run 加载路径（任意表面的 install/enable/update、`reload-plugins` verb）跑 `discover_plugins(force=True)`，且 `PluginManager.on_plugin_loaded` 从那次 sweep 内为新建插件触发、带激活摘要（`hermes_cli/plugins_activation.py`：handler 现在就活；tools/prompt 下一会话；`deferred.mcp_servers` 直到 `mcp.reload`）。**绝不从 RPC 发那个事件**。Auxiliary LLM 调用（titling、compression、MoA、vision …）从 `agent/auxiliary_hooks.py` 发 `pre_auxiliary_call`/`post_auxiliary_call`（payload = `*_api_request` 形状 + `aux_task`），**绝不**发 turn-scoped 的 `pre/post_api_request`（#79733）。插件改默认值时加一个按「已有 config」信号键控的迁移守卫（`_explicitly_configured`），让老用户保留旧默认。

**生命周期 hook 在所属 profile 的 scope 下触发，调用方绑它**：`on_session_start`/`on_session_end`/`sync_turn`/`shutdown` 从 turn（已绑）**和** eviction/shutdown/`tui_gateway` teardown/cron 完成（由调用方经 `_run_release_in_profile_scope`、`_session_profile_runtime_scope`、`_profile_cron_scope` 绑定）两路调用。一个进程服务多个 profile，所以 provider 绝不在 `initialize()` 缓存 `hermes_home` 当「唯一 home」——按每次传入的 home 存键（`hermes_home_key()`）——且绝不为凭证读 `os.environ`（`agent.secret_scope.get_secret`；`check_fn` 也是）。后台工作经 `agent.memory_provider.spawn_context_thread` 起，绝不裸 `threading.Thread`，否则 worker 无 scope、fail-closed 或写进 launch profile 的租户。Platform 插件绝不变异 `os.environ`：YAML 经 `_shared.apply_yaml_bridge` 进 `PlatformConfig.extra`，门控经 `platform_gate_env`（`gateway/AGENTS.md`）。

## Plugin Host Boundary（`plugins.isolation: host`）

`in_process`（默认）把用户插件 import 进 Hermes。`host` 把每个非 bundled 插件跑在**每 profile 的宿主进程**（`hermes_cli/plugin_host.py` parent、`plugin_host_child.py` child、`plugin_host_wire.py` 帧化 JSON 协议）。child 把插件交给 `RemotePluginContext`；Hermes 注册代理（tools、hooks、commands、provider 对象作为它检查的 ABC 的子类）。不变式：

- **每个用户代码 import 路径都路由到 host 或拒绝**——general 插件（`plugins_loader`）、memory/context engine/cron provider（`load_instance`）、model-provider profile（`plugin_host_profiles.py`：无凭证提取按文件指纹缓存，因为发现跑在 `hermes_cli.config`/`auth` import 期；override 按名在 host 内跑）、dashboard API（ASGI bridge）。`plugins/plugin_loader.load_plugin_module` 拒绝任何其它合成命名空间 import。新用户代码 loader 必须做同样的事。
- **不能跨的只有一张表**：`plugin_isolation.HOST_UNSUPPORTED_CTX_METHODS`（live 网关 / 适配器对象）。运行时拒绝与静态审计（`plugin_isolation_audit.py`，由 `hermes plugins validate/show` 展示）都读它；`evals/plugin_isolation/audit_catalog.py` 重测 catalog。
- **host 绝不 spawn host**（`HERMES_PLUGIN_HOST_PROCESS=1` 让 `isolation_mode()` 在那变成 in_process），且不能在模块 import 持锁时启动（model-provider 发现是已知情形）。
- **被 operator pin 时隔离方不能 opt out**：`isolation_mode()` / `host_launcher()` 经托管的 overlay 读（`load_config_readonly`），所以 `/etc/hermes/config.yaml` 胜过 profile 自己的 config。绝不对它们切到裸用户 config 读。
- 插件保持 tenant-unaware：无新 API，同一 `ctx`。每 profile env 来自 `served_profile_child_env`，所以 host 只看到自己 profile 的密钥。

## Native Plugin Compatibility Contract

兼容性是一条**行为契约**，不是单体的 `PLUGIN_API_VERSION`、manifest 宽的 native `api:` 匹配、或不相关 payload 上的版本字面量。已文档化的表面保持可加：

- Hook payload 数据作为**关键字字段**添加；callback 做签名检查，所以旧窄签名只收它们声明的字段、`**kwargs` callback 收全 payload。
- 绝不移除或重命名 `PluginContext` 方法；新参数可选、带默认、尽量 keyword-only。
- 未知 native manifest 字段被忽略。
- 新的 provider 方法给默认实现；可选 callback kwargs 做签名检查，非无条件转发。
- 局部 schema 版本只给有 wire 或持久契约的能力，且旧 state/config/session replay 保留或迁移。
- 弃用：每进程一次 warning、文档化替换 + 迁移说明、移除前 ≥ 2 个后续 minor release。
- 兼容测试经**真实发现路径**加载冻结插件并断言结果——绝不断言确切的 registry/catalog 计数、源码读取测试、或「全局版本字面量变了」。

**Internal import paths are not API**：PR #102117 把内部移进 `<stem>_<topic>` siblings。保留旧 import 路径给外部插件的临时兼容层在 2026-09-14 窗口后移除；旧路径现在抛 `ImportError`，作为插件 load error 浮现在 `hermes plugins list`。插件建在 `ctx` 与文档化 ABC 上。**绝不**为内部移动加 re-export shim。`hermes_cli/plugin_compat.py` 只作为三个 inert stub 存活，给仍跑的 pre-removal updater import。

## Cron（含 Kanban 多 Agent 工作队列）

`cron/`（+ `kanban/`）——定时任务与多 agent 工作队列。Agents 经 `cronjob` tool 调度；用户经 `hermes cron list|add|edit|pause|resume|run|remove` 或 `/cron`。调度格式：duration（`"30m"`、`"2h"`、`"1d"`）、"every" 短语（`"every 2h"`、`"every monday 9am"`）、5 段 cron（`"0 9 * * *"`）、ISO one-shot（`"2026-06-01T09:00:00Z"`）。

- `cron/jobs.py`（job store）+ `cron/scheduler.py`（tick loop；`scheduler_*.py` siblings）。
- **Inactivity watchdog** 在 cron agent 会话上（`_cron_inactivity_seconds()`）：默认 600s idle，会话被硬中断以免独占调度器；长但活跃的 job（`_MAX_*` 外）不触发。
- 发现 stamp 带死 owner 的**一次性**恢复（`cron/occurrences.py`），executions ledger 的 `scheduled_instant` 阻止二次 fire，`cron.catch_up_missed: false` 默认不补跑。
- 每 home tick lock `<home>/cron/.tick.lock` 防跨进程重复 tick。
- **Headless tick 拒绝、绝不 spawn**：`hermes cron tick`（系统 crontab / 外部调度器）调 `tick(headless=True)`；`cron/scheduler_gateway_gate.py` 在发现时跳过 agent job，避免未受管 daemon。同样策略用于 approvals（headless/cron = 拒绝）。in-process ticker 与 `hermes cron run` 非 headless。
- `scheduler_provider.py::_start_multiplex` 是**一个** ticker 顺序迭代 `profiles_to_serve()`（home + secret scope + terminal scope 下），**绝不** N 个并行 ticker。Supervision（`scheduler_thread.py::`）在 host 网关进程 tick 每个 profile 的 store。

## Context Files

AGENTS.md 风格上下文文件只在启动时从 CWD 加载并设上限（`CONTEXT_FILE_MAX_CHARS` / 由上下文窗口动态推算的 `context_file_max_chars`）；**绝不**把安装树的 `AGENTS.md` 当项目上下文加载（PR #64611）。子目录提示（`agent/subdirectory_hints.py`）追加到工具结果（head+尾超出 `_MAX_HINT_CHARS = 32_000` 的部分被截断并记录日志，绝不排进 chat 状态告警），且拒绝工作目录外路径，所以 `~/.codex/AGENTS.md` / `~/.claude/CLAUDE.md` 永不混入。

## Links

- [Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md)
- [Architecture](/docs/CS/AI/LLM/Agent/Product/Hermes/Architecture.md)
- [AgentLoop](/docs/CS/AI/LLM/Agent/Product/Hermes/AgentLoop.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/Hermes/Tools.md)
- [Skills](/docs/CS/AI/LLM/Agent/Product/Hermes/Skills.md)
- [Memory](/docs/CS/AI/LLM/Agent/Product/Hermes/Memory.md)

## References

- [Hermes Agent plugins/AGENTS.md](https://github.com/NousResearch/hermes-agent/blob/main/plugins/AGENTS.md)
- [Hermes Agent plugin catalog](https://github.com/NousResearch/hermes-agent/tree/main/plugin-catalog)
- [Hermes Agent 插件开发文档](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/index)
- [Hermes Agent cron 内部文档](https://hermes-agent.nousresearch.com/docs/developer-guide/cron-internals)
- [hermes-example-plugins](https://github.com/NousResearch/hermes-example-plugins)
