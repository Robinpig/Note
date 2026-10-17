## Introduction

Hermes 的「记忆」是多层、跨会话、可检索的：少量关键事实随身（Session Context）、完整经历落盘（Episodic Archive）、可复用方法进 Skill。本篇覆盖三层记忆、SQLite **FTS5 全文检索（自带 CJK 分词原生扩展）**、持久化 memory provider 插件（含 Honcho 辩证式用户建模），以及支撑这一切的 `hermes_state_*.py` SessionDB 家族与 secret scope / 多 profile 隔离。机制总览见 [Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md)。

> 事实来源：`hermes_state.py` 及 `hermes_state_*.py` siblings、`agent/memory_manager.py`、`agent/memory_provider.py`、`plugins/memory/`。基线 main @ 2026-10-17。

## Three-Layer Memory

| 层 | 内容 | 特点（已核实配置） |
| :--- | :--- | :--- |
| Session Context | `MEMORY.md`（环境事实/项目约定）+ `USER.md`（用户偏好/画像） | 会话开始注入系统提示；`memory_char_limit: 2200`（~800 token）、`user_char_limit: 1375`（~500 token），超限由 Agent 自己合并/替换 |
| Episodic Archive | 全部会话存 `state.db`，按需检索 | 容量大、无固定 token 成本；默认 `retention_days: 90` 自动 prune 已结束会话 |
| Skill | 较长的操作流程与可复用方法 | 相关任务才加载，渐进式披露：先看名称+描述，需要时读全文（见 [Skills](/docs/CS/AI/LLM/Agent/Product/Hermes/Skills.md)） |

直观理解：**Memory 是随身携带的少量关键事实，Archive 是需要时查阅的完整经历，Skill 是从经历中抽象出的做事方法**。

## state.db: SQLite + FTS5（含 CJK 原生分词）

全部会话统一存 `~/.hermes/state.db`（`hermes_state.py::DEFAULT_DB_PATH = get_hermes_home() / "state.db"`），由 `SessionDB` facade 管理。`SessionDB`：

- **Process-wide 共享写入连接注册表**（#90837）：长生命周期的进程内调用方经 `hermes_state_registry.acquire()` 每解析路径共享一个 writer；one-shot、恢复流、跨 profile 只读走 `SessionDB()` + 各自 `close()`。
- **文件权限加固**：`_secure_state_db_files()` 显式把 `state.db`、`-wal`、`-shm` 设成非 umask 默认权限，避免被其他用户读到。
- **损坏防护**：`has_invalid_sqlite_header_preopen`、`is_zeroed_state_db`、`is_malformed_schema_error`、`is_sqlite_lock_error`、`quarantine_invalid_state_db`、`repair_state_db_schema` —— 打开前先 preflight 可写性，跨进程锁冲突会 quarantine。

**FTS5 全文索引**是检索主力，且 Hermes 自带 **`native/fts5_cjk/` 原生分词扩展**（`fts5_cjk.c` + vendored `sqlite3.h`/`sqlite3ext.h`，`build.sh` 编译成 `.dylib/.so`），由 `hermes_state_fts.py::load_fts5_cjk_extension` 加载到 writer 连接（`_fts_cjk_loaded` / `_fts_cjk_available` 标志，`messages_fts_cjk` 表）。这让中文/日文/韩文检索不再依赖 trigram hack，对中文会话友好。

> **检索 ≠ 记忆**：`session_search` 返回数据库里的**真实消息**（不摘要、不截断），低成本回答 **what happened（过去发生过什么）**；后台复盘与 Skill 提炼（`background_review`）回答 **how to solve it（下次怎么做）**；另有独立的 **LLM summarization** 层做跨会话召回摘要——三个是独立能力，不要与「session_search 返回原文」混淆（[Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md) 正文有同样提醒）。

## Memory Provider Plugin（Honcho = 辩证式用户建模）

持久化记忆走可插拔的 **Memory Provider**（`agent/memory_provider.py::MemoryProvider` ABC，由 `agent/memory_manager.py` 编排：`sync_turn` / `prefetch` / `shutdown` / 可选 `post_setup`）。激活方式：`memory.provider` 指定名字 → `hermes memory setup` → `provider.post_setup(hermes_home, config)`，**绝不开平行顶级命令**。

**在树政策（2026 年收紧）**：

- **2026-05 起不再新增 in-tree memory provider**：`plugins/memory/` 已关闭。`byterover`、`retaindb` 在 2026-10-15 移除；`hindsight`（2026-09）、`honcho`、`supermemory`、`mem0`、`openviking`、`holographic`（2026-10）全部迁到 **plugin catalog**，由 `hermes_cli/memory_provider_migration.py` 为仍在用的 home 自动安装。宿主侧代码只通过 `plugins.memory.import_provider_module` 解析 provider 模块，绝不 `plugins.memory.<name>` 直接 import。
- 新后端以独立 repo 实现同一 `MemoryProvider` ABC，走同样的发现路径。

**Honcho**（[Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md) References 链接）提供语义搜索、跨会话结论与**辩证式（dialectic）用户建模**——把用户画像当成与 Agent 的持续辩证对话产物，而非一次性写死。

## Secret Scope & Multi-Profile Isolation

记忆与密钥都按 **profile**（home）隔离，这是「一个进程服务多 profile」跑得起来的根：

- `agent/secret_scope.py::get_secret` 在 `set_multiplex_active(True)` 之后才放行；否则抛 `UnscopedSecretError`。网关、cron、migrate、`serve` 都会设置它；未绑定的读取是静默的默认 profile 泄漏。
- `hermes_state` 走 `get_hermes_home()`（call 期解析，**绝不** `Path.home()/.hermes` 或模块常量），让每个被服务的 profile 拿到自己的状态。
- 生命周期钩子（`on_session_end`/`sync_turn`/`shutdown`）从 turn（已绑 scope）**和** eviction/shutdown/cron 完成（由调用方经 `_run_release_in_profile_scope` / `_session_profile_runtime_scope` / `_profile_cron_scope` 绑定）两路触发——provider 绝不在 `initialize()` 缓存 `hermes_home` 当「唯一 home」，而应按每次传入的 home 存键（`hermes_home_key()`），且绝不为凭证读 `os.environ`（用 `get_secret`）。
- 后台工作经 `agent.memory_provider.spawn_context_thread` 起，**绝不用裸 `threading.Thread`**——否则 worker 无 scope、fail-closed 或写进启动 profile 的租户。

## Links

- [Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md)
- [Architecture](/docs/CS/AI/LLM/Agent/Product/Hermes/Architecture.md)
- [AgentLoop](/docs/CS/AI/LLM/Agent/Product/Hermes/AgentLoop.md)
- [Skills](/docs/CS/AI/LLM/Agent/Product/Hermes/Skills.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/Hermes/Tools.md)
- [Gateway](/docs/CS/AI/LLM/Agent/Product/Hermes/Gateway.md)

## References

- [Hermes Agent hermes_state.py](https://github.com/NousResearch/hermes-agent/blob/main/hermes_state.py)
- [Hermes Agent 记忆文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory)
- [Honcho（辩证式用户建模）](https://github.com/plastic-labs/honcho)
- [agentskills.io（Skill 开放标准）](https://agentskills.io)
