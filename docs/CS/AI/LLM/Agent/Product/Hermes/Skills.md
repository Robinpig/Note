## Introduction

Skill 是 Hermes **自进化闭环的程序性记忆侧**：Agent 在完成任务后把可复用的方法沉淀成 `SKILL.md` 目录，下次相关任务按需加载。本篇覆盖两套 surface、frontmatter 规范、作者规范（由测试强制）、以及后台 curator 的生命周期。机制总览见 [Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md) 的「Seven Companion Volumes」。

> 事实来源：`skills/AGENTS.md`、`optional-skills/` 目录、`agent/curator.py`、`tools/skill_usage.py`。基线 main @ 2026-10-17。

## Two Surfaces

- **`skills/`** —— 内置、默认加载，按类目组织（`skills/github/`、`skills/mlops/` …），当前 **13 个**类目。
- **`optional-skills/`** —— 更重或更小众的 Skill，**随仓发布但默认不激活**，经 `hermes skills install official/<category>/<skill>` 安装（适配器 `tools/skills_hub_official.py::OptionalSkillSource`）。当前 **23 个**类目，含 `autonomous-ai-agents`、`blockchain`、`communication`、`creative`、`devops`、`email`、`health`、`mcp`、`migration`、`mlops`、`productivity`、`research`、`security`、`web-development` 等。

审查一个 Skill PR 时先判目标目录：重依赖或小众的走 `optional-skills/`。

## SKILL.md Frontmatter

`name`、`description`、`version`、`author`、`license`、`platforms`（OS 门控：`[macos]`、`[linux, macos]` …）、`metadata.hermes.tags`、`metadata.hermes.category`、`metadata.hermes.related_skills`、`metadata.hermes.config`（`skills.config.<key>`，setup 时询问、加载时注入）。顶层 `tags:` / `category:` 也被接受，由 loader 从 `metadata.hermes.*` 镜像。格式兼容 **agentskills.io** 开放标准（[Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md) 的 References 给出链接）。

## Authoring Standards（HARDLINE）

每个新增/现代化 Skill（内置、optional 或社区贡献）合并前必须满足 `tests/skills/test_authoring_standards.py` 的 8 条：

1. **`description` ≤ 60 字符、单句、以句号结尾**。长描述会撑大列表、稀释注意力；陈述能力而非实现；禁用营销词（"powerful"/"comprehensive"/"seamless"/"advanced"）；不重复名字。
2. **正文用反引号引用原生 Hermes 工具**（如 `terminal`、`web_extract`、`read_file`、`patch`、`search_files`、`vision_analyze`、`browser_navigate`、`delegate_task`），绝不说 shell 工具名（`grep`→`search_files`、`cat/head/tail`→`read_file`、`sed/awk`→`patch`、`find/ls`→`search_files target='files'`）。MCP 依赖写在 `## Prerequisites`。
3. **`platforms:` 门控对照真实 import 审计**：硬编码 `/tmp`、`fcntl`、`termios`、`os.setsid`、`os.kill(pid,0)`、`/proc`、`signal.SIGKILL`、bash heredoc、`osascript`、`apt`、`systemctl` 等 POSIX 原语需声明平台；优先用 `tempfile.gettempdir`、`pathlib.Path`、`psutil.pid_exists`、Python 过滤来跨平台。
4. **`author` 把人放第一**：外部贡献者真名 + GitHub handle 在前，"Hermes Agent" 在后；用 Hermes 起草的 commit 也要替换成真名。
5. **现代小节顺序**：`# <Skill> Skill`、2–3 句 intro（做什么/不做什么）、`## When to Use`、`## Prerequisites`、`## How to Run`、`## Quick Reference`、`## Procedure`、`## Pitfalls`、`## Verification`。复杂 Skill ~200 行、简单 ~100 行。
6. **`scripts/` `references/` `templates/`**：别让模型每轮内联写解析器或非平凡逻辑，ship 一个 helper 脚本按 skill 相对路径引用。
7. **测试在 `tests/skills/test_<skill>_skill.py`**，仅 stdlib + pytest + `unittest.mock`，无真实网络。
8. **`.env.example` 改动放在清晰界定的块内**，只在 Skill 自身块内编辑，块外的贡献者副本改动会在 salvage 时丢弃。

Skill 加载工具**不做 offset/limit 分页**——Agent 必须整篇读（root）。外部 Skill PR 的 salvage/modernisation 清单在 `references/new-skill-pr-salvage.md`。

## Curator: Skill Lifecycle（自进化闭环）

后台维护追踪 agent 创建 Skill 的使用情况、自动归档过期者；归档进 `~/.hermes/skills/.archive/`，可恢复。核心 `agent/curator.py`（review loop、自动状态机、LLM review prompt）+ `agent/curator_backup.py`（运行前 tar.gz 快照）；CLI `hermes_cli/curator.py` → `hermes curator status|run|pause|resume|pin|unpin|archive|restore|prune|backup|rollback`；遥测 `tools/skill_usage.py` 拥有 `~/.hermes/skills/.usage.json`（`use_count`、`view_count`、`patch_count`、`last_activity_at`、`state` active/stale/archived、`pinned`）。配置 `curator:` —— `enabled`、`interval_hours`、`min_idle_hours`、`stale_after_days`、`archive_after_days`、`backup.*`；其 LLM 调用经 `auxiliary` 路由（见 [AgentLoop](/docs/CS/AI/LLM/Agent/Product/Hermes/AgentLoop.md)）。

**不变式**：

- 只触碰 `created_by: "agent"` 的 Skill（内置 + hub 安装的免动；`prune_builtins` 让确定性失活遍历归档内置 Skill，但绝不进 LLM 候选列表，也不进 `skills.disabled`——`skill_view` 拒绝这些名字，fork 必须只拿到可读写的 Skill）。
- **永不删除**——归档是上限；pinned Skill 豁免所有自动状态机与 LLM review。
- `skill_manage(action="delete")` 拒绝 pinned Skill，但 `patch`/`edit`/`write_file`/`remove_file` 仍可用，让 Agent 持续改进它。

> 这是 [Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md) 中「Harness 级轻量结构进化」的具体落点：Skill 的创建与 patch 改的是文件结构，**不更新权重**。可靠的 Evolve Loop 仍需治理（成功率/成本/人工反馈/回归测试），见 Practice 篇。

## Links

- [Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md)
- [Architecture](/docs/CS/AI/LLM/Agent/Product/Hermes/Architecture.md)
- [AgentLoop](/docs/CS/AI/LLM/Agent/Product/Hermes/AgentLoop.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/Hermes/Tools.md)
- [Memory](/docs/CS/AI/LLM/Agent/Product/Hermes/Memory.md)
- [Extensions](/docs/CS/AI/LLM/Agent/Product/Hermes/Extensions.md)

## References

- [Hermes Agent skills/AGENTS.md](https://github.com/NousResearch/hermes-agent/blob/main/skills/AGENTS.md)
- [Hermes Agent 创建 Skill 文档](https://hermes-agent.nousresearch.com/docs/developer-guide/creating-skills)
- [Hermes Agent Skills 用户文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- [agentskills.io（Skill 开放标准）](https://agentskills.io)
