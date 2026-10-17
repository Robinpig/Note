## Introduction

Hermes 的差异化不在「能调多少工具」，而在 **agent 会随时间长大**：它跨会话沉淀 Skill 与记忆，并由一组**后台自治循环（autonomous loops）**持续维护、去重、复用这些资产。这条能力链是 Self-Evolving 理论的完整工程落地——它改的是 Harness 层的轻量结构（Skill 包、记忆条目、配置），**不更新模型权重，不属于参数进化**。

本篇从源码逐层拆解自进化闭环：每轮对话结束后的 **background review**（复盘）、长周期运行的 **curator**（Skill 生命周期治理）、用户/agent 触发的 **`/learn`**（蒸馏任意来源成 Skill）、**learning graph**（桌面端「学习可视化」）、驱动这一切的 **periodic scheduler**（全进程单一定时器），以及把多个 Skill 打包的 **skill bundles**。

> 事实基线：`NousResearch/hermes-agent` `main @ 2026-10-17`。所有符号来自 `agent/background_review.py`、`agent/curator.py`、`agent/learn_prompt.py`、`agent/learning_graph.py`、`agent/learning_mutations.py`、`agent/periodic_scheduler.py`、`agent/skill_bundles.py`。Evolve Loop 的治理（成功率 / 成本 / 人工反馈 / 回归测试）见 [Practice/Hermes](/docs/CS/AI/LLM/Agent/Practice/Hermes.md) 与 [Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md)。

## Background Review — 每轮后的隐性复盘

`agent/background_review.py` 在**每个 turn 结束后 fork 一个 review agent**，对该轮对话做质量评估。关键设计：

- **不可见的分叉**：review fork 对用户透明——前台 turn 已经返回，复盘在后台发生；会话结束或被显式 stop 时，该 fork 必须以与前台新 turn 相同的方式被取消（review fork 对用户不可见，但占用父 session 用量）。
- **取消握手（bounded cancellation）**：`_BackgroundReviewRun` 提供原子化的「准入第一个 provider-capable review 阶段」与取消。`_BACKGROUND_REVIEW_CANCEL_TIMEOUT_SECONDS = 2.0`——若 review 在 2 秒内不确认取消，前台照常继续（前台优先，绝不因后台复盘卡住交互）。
- **用量归属**：review fork 的 token 用量**归因到父 session**（`request_hard_interrupt` 前先快照计数器，issue #87250），避免复盘偷偷记到别的账上。
- **路由配置**：`auxiliary.background_review.{provider,model}` 决定复盘由哪个 side-LLM 跑；这复用 AgentLoop 篇里的 auxiliary side-LLM 机制，不占主模型上下文。

复盘产出是后续 Skill 创建 / curator 决策的数据源——它把「哪些做法有效、哪些重复、哪些可复用」量化成信号。

## Curator — Skill 生命周期治理

`agent/curator.py` 是**后台自治维护者**，按固定周期扫描所有「curator 托管的」Skill，在 `active / stale / archived` 三态间迁移。它是自进化闭环的「纪律层」：保证 Skill 库不被一次性创建淹没、又能从长期不使用中自动收敛。

| 维度 | 事实（源码） |
| :--- | :--- |
| 默认开关 | `is_enabled()` 默认 `True`（无配置即开启） |
| 周期 | `DEFAULT_INTERVAL_HOURS = 24 * 7`（**7 天**） |
| 最小空闲 | `DEFAULT_MIN_IDLE_HOURS = 2`（2 小时内不判定 stale） |
| 状态机 | `apply_automatic_transitions()`：按各 skill 最近**真实活动**在 active ↔ stale ↔ archived 间迁移 |
| 最大破坏动作 | 移到 `~/.hermes/skills/.archive/`——**只归档、永不删除** |
| pinned 豁免 | `pinned` 或受 cron 引用的 skill 完全跳过（不归档 / 不合并 / 不裁剪） |
| 状态持久化 | `.curator_state` 文件；`load_state/save_state` |
| 暂停 | `set_paused/is_paused`；`should_run_now()` 同时门控 enabled、paused、上次运行时间 |

不变式（写在模块 docstring 与 `skill_manage` 提示词里）：

- **only curator-managed skills are touched**——非 curator 托管的 skill 绝不动；
- **never delete, only archive (recoverable)**——删除 = 归档，可 `hermes curator restore <name>` 恢复；
- **pinned skills bypass all transitions**——`pinned=yes` 的 skill 整条跳过；
- `use_count == 0` 是「无证据」而非「stale」——**从不归档从未使用的 skill**（避免误杀刚装还没用上的）；
- cron 引用的 skill（`cron=yes`）受保护，归档前需先解除引用。

CLI 暴露：`hermes curator <status|run|archive|restore|pin|unpin|prune>`，其中 `prune` 在 `use_count < 1` 时**拒绝**删（强制只归档）。测试覆盖 `test_curator_*.py` 十余个文件，含 rollback / staging / 分类 / 报告。

## `/learn` — 把任意来源蒸馏成 Skill

`agent/learn_prompt.py::build_learn_prompt()` 构造 `/learn` 的提示词：把用户描述（代码目录、文档 URL、「刚做完的流程」、粘贴的笔记）转成一个可复用 Skill。它**不是蒸馏引擎、不占模型工具足迹**——所有 surface（CLI / 网关 `/learn` / 仪表盘）都把它当作一次普通 turn 调用，因此在 local / Docker / 远程后端表现一致。

生成严格遵循两套硬标准（`_AUTHORING_STANDARDS` + `_KNOWLEDGE_SKILL_STANDARDS`）：

- **Frontmatter 8 条**：`name` 小写连字符 ≤64；`description` 一句 ≤60 字（**最常被违反的规则**，系统提示的 skill 索引截断到 60 字、每会话加载，超出的部分永远不路由）；`version: 0.1.0`；`author` 固定字面量 `Hermes`（**绝不**从 host 环境填 OS 用户名 / git config，避免隐私泄漏，因为 Skill 会被分享发布）；`platforms` 仅在用 OS 绑定原语时声明；`metadata.hermes.tags`。
- **正文 8 段顺序**：标题 + intro → When to Use → Prerequisites → How to Run → Quick Reference → Procedure → Pitfalls → Verification。所有运行都框定为「通过 Hermes 工具」（如 `terminal` 而非 `cat`、`search_files` 而非 `grep`、`patch` 而非 `sed`）。
- **知识库布局（book-to-skill）**：大段散文源（书 / 论文堆 / 大型文档）不塞进单 SKILL.md，而是 lean 核心索引 + 按需 `references/` 逐章文件（每章 100–150 行、蒸馏结构而非摘要）——查询成本跟着答案走，不跟着源走。
- **源卫生（Trojan Source 防御）**：源文本是 DATA 不是指令；蒸馏前**丢弃不可见 / 双向 Unicode 控制字符**（零宽、bidi 嵌入 / 覆盖 / 隔离、tag 字符），绝不让源里的隐藏指令混进 Skill。

空请求语义为「把刚才这轮对话流程蒸馏成 Skill」——这是 Hermes 从一次具体操作中沉淀通用能力的核心入口。

## Learning Graph — 桌面端「学习可视化」

`agent/learning_graph.py` + `agent/learning_mutations.py` 把「用户随时间真正学到的东西」渲染成一张图（desktop journey panel）：

- **节点**：非 base、learned/profile 的 Skill（`SkillNode`：name / category / source / use_count / state / created_by / pinned / related）+ `MEMORY.md` / `USER.md` 的每个条目作为 `memory:` 节点（`memory:<source>:<index>:<fingerprint>`，fingerprint 是条目文本的 sha256 前 12 位，保证图重画后仍能定位到用户点的那张卡片，issue #119668）。
- **边**：
  - Skill ↔ Skill：`related_skills` 双向边（两端都存在才连）；
  - Memory ↔ Skill：**词法重叠 top-4**（skill 名命中权重 6）+ 文本 token 交集。
- **学习信号过滤**（`_has_learning_signal`）：只有 agent 创建、用户 `/learn` 教过、或真正用过（use_count > 0）的 skill 才入图；external mount（用户配置的，非学会的）**永不入 milestones**（issue #108032）。
- **编辑（learning_mutations）**：用户删 skill = **归档**（`hermes curator restore` 可恢复）；删 memory 在 MemoryStore 跨进程锁内重写文件；所有 id 解析都**在锁内按条目文本匹配**，避免列表漂移后改错卡片。

## Periodic Scheduler — 驱动所有后台循环的单一心跳

`agent/periodic_scheduler.py` 把所有周期性后台回调（delegate heartbeat、durable turn-lease 刷新、turn-liveness watchdog、curator、background review 调度）收敛到**全进程一个 daemon 线程 + 一个 heap**：

- 线程只负责按 `due` 时间排序并 dispatch；每个到期的 body 跑在**自己的短命 daemon worker** 上，因此一个阻塞的回调不会拖慢无关的 lease / liveness 定时器。
- 稳态线程数接近 0——worker 只在 body 真正运行期间存在，绝不「每 handle 一个线程」。原文明确这是为了消除 ~130 个 in-process subagent 各自 per-child daemon 线程带来的 2–3 倍线程膨胀。
- 语义：首次调用在 `schedule` 后 `interval` 秒发生；body 返回 `False` 自杀；body 抛异常仅 debug 日志并重新排期（一个坏回调绝不能杀死共享线程）；handle 永不自我重叠（in-flight 返回后才 re-queue）。

## Skill Bundles — 把多个 Skill 别名成一个斜杠命令

`agent/skill_bundles.py`：`<HERMES_HOME>/skill-bundles/*.yaml`（字段 `name` / `description` / `skills: [...]` / 可选 `instruction`）把多个 Skill 打包。`/<bundle>` 把所有成员 Skill 加载进**一条 user message**。

- **slash dispatch 先查 bundle**：若 bundle 与 skill 撞 slug，**bundle 优先**（设计如此）。
- 缓存按**内容摘要**而非时间戳失效（`_bundles_sig` 用 sha256 每文件；同大小重写 / 时钟偏移仍能感知变更），并带「写中途 stamp 必须 stale」的防竞态（mid-scan 落盘不能误判命中）。
- 文件级 CRUD：`save_bundle` / `delete_bundle` / `get_bundle`，写用 `atomic_write_text` 防网关进程读到半截 YAML；disabled skill 在 bundle 调用时**重新应用** disabled 列表（绕过 scan-time 过滤，#58888）。

## Links

- [Architecture](/docs/CS/AI/LLM/Agent/Product/Hermes/Architecture.md)
- [AgentLoop](/docs/CS/AI/LLM/Agent/Product/Hermes/AgentLoop.md)
- [Skills](/docs/CS/AI/LLM/Agent/Product/Hermes/Skills.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/Hermes/Tools.md)
- [Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md)

## References

- [Hermes Agent 仓库（NousResearch/hermes-agent）](https://github.com/NousResearch/hermes-agent)
- [agentskills.io（Skill 开放标准）](https://agentskills.io)
