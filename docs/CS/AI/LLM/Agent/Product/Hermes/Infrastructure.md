## Introduction

Hermes 把「核心窄腰、能力在边缘」贯彻到基础设施层：运行它的 Python 环境、SQLite 存储、容器镜像、对外协议适配，全都是可独立替换、可源码审计的部件，而非云厂商锁定件。本篇拆四个最容易被视为「黑盒」的差异化基建：

- **`native/fts5_cjk`**——手写的 SQLite FTS5 扩展，让会话历史的中文 / 日文 / 韩文检索不再退化为 `LIKE` 全表扫描；
- **`pm/`**——基于 `uv` 的自研依赖与环境管理器，带 14 天 release-age 护栏；
- **`docker/`**——s6-rc 进程监管 + tini 收尾 + 多层 entrypoint 的镜像构建；
- **`acp_adapter/`**——把 Hermes 暴露为 ACP（Agent Client Protocol）可对接实体的适配层。

> 事实基线：`NousResearch/hermes-agent` `main @ 2026-10-17`。符号来自 `native/fts5_cjk/`（README + `fts5_cjk.c` + 自带 `vendor/sqlite3.h`）、`pm/AGENTS.md`、`docker/`（SOUL / entrypoint / s6-rc.d / build_agent.py）、`acp_adapter/`。

## native/fts5_cjk — 中文友好的 FTS5 分词

会话检索的痛点：SQLite 默认 FTS5 `unicode61` 分词器对 CJK 按字切，1–2 字的中文 / 日文 / 韩文词会**漏检索、退化成 `LIKE` 全表扫描**。`native/fts5_cjk` 是一个 C 写的 FTS5 tokenizer 扩展，语义对齐 **Lucene CJKAnalyzer**：`unicode61 + CJK 字符 bigrams`（相邻字两两成词）。

| 维度 | 事实（源码） |
| :--- | :--- |
| 实现 | `fts5_cjk.c`（~9.6 KB），FTS5 扩展；构建脚本 `build.sh` |
| 语义 | `unicode61` + CJK 字符 bigram（Lucene `CJKAnalyzer` 等价） |
| 依赖 | 优先系统 `sqlite3ext.h`，否则用 `vendor/` 自带副本——**无需 `libsqlite3-dev`** |
| 安装位置 | 构建到 `~/.hermes/lib/` |
| 索引 | 下次 `SessionDB` 打开时创建 `messages_fts_cjk`（external-content，排除 tool 行，同 v23 存储纪律） |
| 回填 | 已有库跑 `hermes sessions optimize-storage`；新消息实时索引 |
| 关闭 | `config.yaml` 设 `sessions.cjk_fts: false` |
| 覆盖路径 | 环境变量 `HERMES_FTS5_CJK_SO` |
| 溯源 | 由 Soju06 贡献（PR #65544） |

这是 Hermes 在「中文 / 日文用户会话检索」上区别于纯英文假定 agent 的硬证据：检索质量不依赖外部向量库，原生 SQLite 即可。

## pm — 基于 uv 的包 / 环境管理器

`pm/AGENTS.md` 规定：PM **独占** Hermes 的 Python 依赖变更，用户与插件都不得用裸 `pip` / `uv` 改 Hermes 环境。`pm.sync_venv(['extra'], explicit=True)` 处理声明的 runtime extras，`hermes pm install` 做安装 / 同步，`hermes pm repair` 修损坏依赖；调用方拿到的是**解释器或工具路径，不是 uv**（封装隔离）。

依赖钉死策略（CI 与 reviewer 强制）：

- PyPI：`>=floor,<next_major`（如 `httpx>=0.28.1,<1`）；pre-1.0：`<0.(minor+2)`（如 `>=0.29,<0.32`）；Git URL 用 **40 位 commit SHA**；GitHub Actions 用 SHA + `# vN` 注释。裸 `>=X.Y.Z` 被 CI 拒绝。
- **14 天 release-age 检查**（`[tool.uv] exclude-newer = "3 days"` 是 Hermes **自身**依赖的护栏，仅 lock 时跑——`hermes pm lock` / CI lock check，**绝不跑在用户机器上**；每个生成 workspace 都 drop 这个 cutoff，`pm/workspace.py::_without_release_age`，所以无上传时间的镜像不会破坏安装，issue #135589）。
- 插件 `python_dependencies` 走插件自己的策略；Teknium 明确：「插件不必遵守我们的 14 天规则，只有 Hermes 自身依赖要」；钉死的依赖需 >3 天。

改 `pyproject.toml` 后必须 `hermes pm lock` → re-source `./activate` → 提交 `pyproject.toml` 与 `uv.lock`。

## docker — s6-rc 监管的镜像

`docker/` 下是一套生产镜像构建，而非单个 Dockerfile。关键件：

- **`SOUL.md`**：这是 agent 的 persona 系统提示（"You are Hermes Agent, built by Nous Research…"），随镜像打包，不是部署文档。
- **`entrypoint.sh` / `entrypoint-dispatch.sh` / `main-wrapper.sh`**：多层 entrypoint，按角色分发（agent / sandbox-desktop / 等）。
- **`s6-rc.d/`**：用 **s6 进程监管** 拉起多服务（比 systemd 轻、适合容器），异常退出自动重启。
- **`tini-shim.sh`**：用 `tini` 作 PID 1 收尾僵尸、正确转发信号。
- **`build_agent.py`**：镜像构建脚本（非裸 `docker build`），`stage2-hook.sh` / `cont-init.d/` 做初始化钩子；`sandbox-desktop.Dockerfile` + `sandbox-desktop-smoke.sh` 是桌面沙箱变体。

这解释了为何 Hermes 能在「本地二进制 / Docker / 云端 sandbox」间一致运行：运行契约由 entrypoint 分发 + s6 监管定义，与平台无关。

## acp_adapter — ACP 协议适配层

`acp_adapter/`（19 个文件）把 Hermes 暴露为 **ACP（Agent Client Protocol）** 可对接的实体——让外部 IDE / 工具 / 评测框架能以标准协议驱动 Hermes，而非走私有 CLI 协议。模块平面：

| 模块 | 职责 |
| :--- | :--- |
| `server.py` / `session.py` | ACP server 与单会话生命周期 |
| `gateway_server.py` / `gateway_session_meta.py` / `gateway_commands.py` | 网关侧 ACP 接入（会话元数据、命令） |
| `auth.py` / `permissions.py` / `provenance.py` | 鉴权、权限、来源溯源 |
| `edit_approval.py` / `elicitation.py` | 编辑审批、向用户索取澄清 |
| `tools.py` / `catalog.py` / `model_catalog.py` | 工具 / 技能 / 模型目录暴露 |
| `events.py` / `content.py` / `commands.py` | 事件流、内容归一、命令处理 |
| `__main__.py` / `entry.py` | 入口与装配 |

与 AgentLoop 篇的 `acp_openai_bridge.py` / `copilot_acp_client.py` 呼应：Hermes 既能被 ACP client 调用（`acp_adapter` 服务端），也能作为 ACP client 去驱动别的 Agent（Copilot），协议层双向打通。

## Links

- [Architecture](/docs/CS/AI/LLM/Agent/Product/Hermes/Architecture.md)
- [Memory](/docs/CS/AI/LLM/Agent/Product/Hermes/Memory.md)
- [Gateway](/docs/CS/AI/LLM/Agent/Product/Hermes/Gateway.md)
- [Extensions](/docs/CS/AI/LLM/Agent/Product/Hermes/Extensions.md)

## References

- [Hermes Agent 仓库（NousResearch/hermes-agent）](https://github.com/NousResearch/hermes-agent)
- [uv（Python 包 / 环境管理器）](https://github.com/astral-sh/uv)
- [s6 进程监管（s6-rc）](https://skarnet.org/software/s6/)
