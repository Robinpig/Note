## Introduction

> 版本基线：2026-10-06 核实（源码 `NousResearch/hermes-agent`，`config_version: 49`，v0.17 线）。

Hermes Agent（"The agent that grows with you"）是 **Nous Research 开源、NVIDIA 重点推介的自进化 agent 框架**，也是 DeepEvolution 系列文章分析的具体对象。它的价值不在于更新模型权重，而在于让 Agent 在使用过程中持续沉淀记忆与 Skill——属于 [Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md) 中「上下文 / 记忆进化 + Harness 级轻量结构进化」的完整落地标本，也是理解 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 工程的具体实例。

与同属 Harness 实例的 [DSH](/docs/CS/AI/LLM/Agent/Product/DSH.md)、[Codex](/docs/CS/AI/LLM/Agent/Product/Codex.md) 相比，Hermes 的差异化定位是 **local-first、model-agnostic、跨会话持久进化**：不绑定任何模型或云（Nous Portal / OpenRouter / NIM / 本地 Ollama 皆可），强调在本地硬件上 24/7 运行、越用越顺手。

> 本笔记聚焦 Hermes 自身的工程机制；自进化的评测体系、CI/CD 与人的校准作用见 Self-Evolving。下文所有配置项均来自仓库 `cli-config.yaml.example`，实现细节来自对应源码模块。

## 架构：三层主干 + 多入口

| 层 | 组件 | 职责（已核实） |
| --- | --- | --- |
| 入口层 | CLI（`hermes`）/ Gateway / ACP / Batch Runner / API Server / Python Library | 接收人与系统的请求，适配不同交互形态 |
| 核心层 | `AIAgent`：`system_prompt`（三层组装）、`model_tools`（Provider Resolution）、`toolsets`（Tool Dispatch） | 组装提示/上下文/记忆/画像/Skill，选模型，调度工具 |
| 后端层 | `hermes_state`（SQLite + FTS5）、Tool Backends、6 种运行后端 | 持久化全部会话；让 Agent 真正进入环境执行动作 |

三种入口（CLI Session、Gateway Message、Cron Job）数据流不同，却共享同一套执行、存储、记忆和 Skill 机制——**轨迹被统一保存，Evolve Loop 才能跨入口工作**。

### 入口层：六种形态

| 入口 | 形态 | 说明 |
| --- | --- | --- |
| CLI | `hermes` 启动的交互式 TUI | 多行编辑、slash 命令补全、对话历史、中断重定向、流式工具输出 |
| Gateway | 单一网关联接消息平台 | Telegram / Discord / Slack / WhatsApp / Signal / Email 共用一个 gateway 进程，跨平台对话连续 |
| ACP | `acp_adapter/` 协议服务端 | 把 Hermes 暴露为 Agent Client Protocol 服务端（含 `permissions`、`edit_approval` 模块），可被外部 IDE/客户端驱动 |
| Batch Runner | `batch_runner.py` | 批量生成轨迹，用于训练下一代工具调用模型；默认关闭记忆 |
| API Server | `/v1` 路由 | 以 HTTP 服务暴露 Agent 能力，restart 时有独立的 drain 宽限 |
| Python Library | 可 import 的 `hermes` 包 | 在自有代码里以库的形式调用 Agent |

### 运行后端：在哪执行工具

Hermes 的工具不在你的笔记本上裸跑，而是跑在**六种终端后端**之一：local、Docker、SSH、Singularity、Modal、Daytona。其中 Modal / Daytona 提供 **serverless 持久化**——环境空闲时休眠、按需唤醒，idle 期间几乎零成本。这解释了为什么它"不在你的笔记本上"也能从 Telegram 指挥云端 VM 干活。

### 模型与提供商：Provider Resolution

`hermes model` 一行切换，无代码改动、无锁定。已支持的提供商：Nous Portal、OpenRouter（200+ 模型）、NovitaAI、NVIDIA NIM（Nemotron）、Xiaomi MiMo、z.ai/GLM、Kimi/Moonshot、MiniMax、Hugging Face、OpenAI，以及任意自托管 endpoint（NIM / vLLM / 本地 Ollama）。子智能体还可单独覆盖 `model` / `provider`。

## Evolve Loop 的四个关键机制

### Periodic Nudges：后台复盘（已核实实现名 `background_review`）

一轮交互结束后派生一个**独立复盘过程**：重读会话快照，判断是否新增/修改记忆与 Skill。源码里它叫 `background_review`——一个 **daemon 线程里的 post-turn 记忆/技能自改进 review fork**，在 nudge 间隔触发时写入 skills/memories。复盘与主会话分离（不污染进行中的上下文），并可用更便宜的辅助模型降本（配置 `background_review.provider: "auto"`）。

两个间隔由配置驱动：

- `memory.nudge_interval: 10`——每 10 个用户轮次提醒 Agent 考虑保存记忆
- `skills.creation_nudge_interval: 15`——每 15 次工具调用迭代提醒考虑沉淀 Skill

它在「什么都保存」（上下文爆炸、注意力稀释）和「什么都忘记」（不沉淀）之间充当筛选器。

### Autonomous Skill Creation：程序性记忆

Agent 在完成复杂任务后可创建、修改、复用自己的 Skill，写入 `~/.hermes/skills/`（`external_dirs` 则是只读的跨 Agent 共享目录，本地技能同名优先）。每个 `SKILL.md` 采用 **agentskills.io 开放标准**的 frontmatter：

```yaml
---
name: agent-merge-conflict-arbiter
description: "Neutral arbiter for merge conflicts between two agents."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Multi-Agent, Git, Merge-Conflict]
    related_skills: [hermes-agent]
---
```

正文是步骤、约束、避坑说明、引用资料与辅助脚本——比零散记忆更完整的「程序性记忆」，与 [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md) 规范同构。

- **Skill Self-Improvement 优先用 patch**：只传变化部分（旧文本 → 新文本），影响范围小、上下文成本低。
- 可开启高风险环境的额外把关（见下方「安全与人工把关」）。

> 注：DeepEvolution 文章提到的 `skill_manage` 工具名、以及 `skills.write_approval` / `memory.write_approval` 两个开关，在**当前源码与 `cli-config.yaml.example` 中均不存在**（grep 零命中）。技能/记忆写入直接由 `background_review` 守护线程完成，没有"先进待审核区、人看差异再应用"这个简单配置开关。下文「安全与人工把关」给出了真正存在的人工把关机制。

### FTS5 Session Search：检索不等于记忆

会话统一存 `~/.hermes/state.db`，SQLite **FTS5 全文索引**，并额外支持 **trigram 与 CJK（中日韩）分词**——对中文检索友好。`session_search` 返回**数据库里的真实消息**（不摘要、不截断）。分工：

- FTS5 低成本回答 **what happened**（过去发生过什么）
- 后台复盘与 Skill 提炼回答 **how to solve it**（下次怎么做）
- 另有 **LLM summarization** 层做跨会话召回摘要——这是两个独立能力，不要与"session_search 返回原文"混淆

可选的 Honcho 外部 Memory Provider 提供语义搜索、跨会话结论和用户画像（dialectic user modeling）。

### 三层记忆系统

| 层 | 内容 | 特点（已核实配置） |
| --- | --- | --- |
| Session Context | `MEMORY.md`（环境事实/项目约定）+ `USER.md`（用户偏好/画像） | 会话开始注入系统提示；`memory_char_limit: 2200`（~800 token）、`user_char_limit: 1375`（~500 token），超限由 Agent 自己合并/替换 |
| Episodic Archive | 全部会话存 `state.db`，按需检索 | 容量大、无固定 token 成本；默认 `retention_days: 90` 自动 prune 已结束会话 |
| Skill | 较长的操作流程与可复用方法 | 相关任务才加载，渐进式披露：先看名称描述，需要时读全文 |

直观理解：Memory 是随身携带的少量关键事实，Archive 是需要时查阅的完整经历，Skill 是从经历中抽象出的做事方法。

## 子智能体与并行化

Hermes 把子智能体当作**面向子任务的、生命周期很短的隔离工作单元**（`delegate_task` 工具，由 `delegation:` 配置驱动）：

- **上下文封顶**：`_MAX_CONTEXT_CHARS = 32000`，子智能体只拿聚焦的上下文与工具集——适合上下文窗口有限的本地模型
- **隔离任务环境**：delegate 跑在隔离的任务环境里（in-process），不继承父进程的 `working_directory`
- `delegation.max_iterations: 250`——每个子智能体最多 250 次工具调用
- `delegation.max_concurrent_children: 10`（默认）——批处理并行度，超过 10 会线性放大 API 成本
- `delegation.max_spawn_depth: 1`——默认扁平（禁止子代再派生子代），调到 2 需中间 Agent 带 `role="orchestrator"`
- `delegation.subagent_auto_approve: false`——子智能体命中危险命令审批时默认**自动拒绝**（父 TUI 持有 stdin，阻塞会死锁）

也支持用 Python 脚本通过 RPC 调用工具，把多步流水线压缩成零上下文成本的回合。

## 安全与人工把关

Hermes 的"人的确认权"不是靠一个记忆/技能审批开关，而是落在几处真实存在的安全机制上：

- **`protected_instruction_files`**：Agent 写 `AGENTS.md` / `CLAUDE.md` / `SOUL.md` 等"指挥自身"的指令文件时，**永远要求人工批准**（即便开了 `--yolo`；无人可答时直接拒绝）。可用 `protected_instruction_extra_patterns` 用 fnmatch 扩展保护范围。
- **tirith 命令预扫描**（`security.tirith_*`）：执行前检测同形异义 URL、pipe-to-shell、终端注入、环境变量篡改；`tirith_fail_open` 控制不可用时是否放行。
- **危险命令审批**：工具执行危险命令时的 approval 流程（与 [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md) 的 fail-closed 思路一致）。
- **`background_review` 无审批开关**：技能/记忆的后台写入目前直接落盘，没有"待审核区"。高风险环境应靠 `protected_instruction_files` + 危险命令审批 + 只读 `external_dirs` 组合来约束，而不是依赖一个不存在的 `write_approval` 键。

## 部署、持久化与快照

Agent 在生产中会因代码发布/配置变更而重建容器。**学到的技能/记忆若不能存活，每次都要重新教**。Hermes 的做法是快照 + 恢复：

- `snapshot.sh` 把 `/sandbox/.hermes-data/`（技能、记忆、会话、定时任务）打成 tarball；`tear-down.sh` 销毁，`bring-up.sh` 重建，`restore.sh` 重新注水
- 快照带**凭据过滤器**，自动排除 `.env` / `token` / `secret`，tarball 可安全分享

在 NVIDIA NemoClaw 的私有数据场景里，Hermes 跑在 **OpenShell 沙箱**中：凭据隔离（Slack/Outlook token 永不让 Agent 看见，认证在沙箱代理出口完成）+ 网络策略（Agent 被禁止访问公网，GitHub/论坛数据经只读 ETL 注入）。即便 Agent 被攻破，也无法把内部数据外发。

## 定位与边界

Hermes 的主路径是**上下文/记忆进化**；Skill 创建与 patch 是 Harness 级轻量结构进化；**不更新权重，不属于参数进化**。最大价值：不需要等待模型重新训练，Agent 也能在使用中逐步形成属于自己的工作方法。

它与 DSH / Codex 同属 Harness 工程实例，但侧重不同：Codex/DSH 重在工具闭环与执行安全，Hermes 重在跨会话的记忆与 Skill 沉淀，且以"可靠设计"为卖点——Nous Research 会**人工筛选并压测**随附的每一项 Skill、工具和插件，让 30B 级别的本地模型也能开箱即用。

**自进化的可靠性不来自框架自带，而来自治理**：没有任务成功率/成本/人工反馈/回归测试，就无法证明新 Skill 优于旧版本。可靠的 Evolve Loop 还需要明确什么经验值得保存、为自动写入保留版本与回退、用真实任务验证 Skill 修改、定期清理过期冲突记忆——这部分见 Self-Evolving 的"Agent CI/CD"与"人的角色"。

## Links

- [Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md) — 自进化理论、评测与 CI/CD（Hermes 案例的完整上下文）
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) — Harness 补偿面理论与 Agent 开发三层
- [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md) — SKILL.md 规范（与 Hermes 的 agentskills.io 格式同构）
- [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md) — 危险命令审批与 fail-closed 思路
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) — Agent 四构成（Loop/Tools/Memory/Harness）
- [DSH](/docs/CS/AI/LLM/Agent/Product/DSH.md) / [Codex](/docs/CS/AI/LLM/Agent/Product/Codex.md) — 另外两个 Harness 工程实例（侧重执行安全）

## References

- [Hermes Agent 官方仓库（NousResearch/hermes-agent）](https://github.com/NousResearch/hermes-agent)
- [Hermes Agent 文档](https://hermes-agent.nousresearch.com/)
- [DeepEvolution（二）：Hermes 的自进化设计](https://mp.weixin.qq.com/s/mCD-dfq9SMJQJB-jxN8XWw)
- [NVIDIA：Deploy Self-Evolving Agents with a Hermes Agent and NVIDIA NemoClaw](https://developer.nvidia.com/blog/deploy-self-evolving-agents-for-faster-more-secure-research-with-a-hermes-agent-and-nvidia-nemoclaw/)
- `cli-config.yaml.example`（仓库内，config_version 49）—— 本文所有 `memory.*` / `skills.*` / `delegation.*` / `security.*` 配置的出处
- `optional-skills/autonomous-ai-agents/honcho/SKILL.md` —— Honcho dialectic 用户建模技能样本
