## Introduction

Hermes 是 DeepEvolution 系列文章分析的一个**自进化 Agent** 开源案例（CLI / 网关 / 定时任务多入口）。它的价值不在于更新模型权重，而在于让 Agent 在使用过程中持续沉淀记忆与 Skill——属于 [Self-Evolving](/docs/CS/AI/LLM/Self-Evolving.md) 中「上下文 / 记忆进化 + Harness 级轻量结构进化」的完整落地标本，也是理解 [Harness](/docs/CS/AI/LLM/Harness.md) 工程的具体实例。

> 本笔记聚焦 Hermes 自身的机制；自进化的评测体系、CI/CD 与人的校准作用见 Self-Evolving。

## 架构：三层主干

| 层 | 组件 | 职责 |
| --- | --- | --- |
| 入口层 | CLI / Gateway / ACP / Batch Runner / API Server / Python Library | 接收人与系统的请求，适配不同交互形态 |
| 核心层 | AIAgent：Prompt Builder、Provider Resolution、Tool Dispatch | 组装提示/上下文/记忆/画像/Skill，选模型，调度工具 |
| 后端层 | Session Storage（SQLite + FTS5）、Tool Backends | 持久化全部会话；让 Agent 真正进入环境执行动作 |

三种入口（CLI Session、Gateway Message、Cron Job）数据流不同，却共享同一套执行、存储、记忆和 Skill 机制——**轨迹被统一保存，Evolve Loop 才能跨入口工作**。

## Evolve Loop 的四个关键机制

### Periodic Nudges：后台复盘

一轮交互结束后派生一个**独立复盘过程**：重读会话快照，判断是否新增/修改记忆与 Skill。复盘与主会话分离（不污染进行中的上下文），默认只有记忆管理、Skill 管理和只读文件工具，并可配置更便宜的辅助模型降本。

它在「什么都保存」（上下文爆炸、注意力稀释）和「什么都忘记」（不沉淀）之间充当筛选器。

### Autonomous Skill Creation：程序性记忆

`skill_manage` 允许 Agent 创建、修改、删除自己的 Skill，写入 `~/.hermes/skills/`。典型触发：发现可复用的多步骤工作流、走通死路后的正确路径、用户纠正了处理方式。每个 `SKILL.md` 包含步骤、约束、避坑说明、引用资料和辅助脚本——是比零散记忆更完整的「程序性记忆」，与 [Skill](/docs/CS/AI/LLM/Skill.md) 规范同构。

- **Skill Self-Improvement 优先用 patch**：只需 Skill 名 + 旧文本 + 新文本三个参数，影响范围小、上下文成本低。
- 可开启 `skills.write_approval` / `memory.write_approval`：后台变更先进待审核区，人看差异后再应用——Agent 可以提出改进，高风险环境保留人的确认权。

### FTS5 Session Search：检索不等于记忆

会话统一存 `~/.hermes/state.db`，SQLite FTS5 全文索引。`session_search` 返回**数据库里的真实消息**（不调 LLM、不摘要、不截断，不要与 "LLM summarization" 宣传混淆）。分工：

- FTS5 低成本回答 **what happened**（过去发生过什么）
- 后台复盘与 Skill 提炼回答 **how to solve it**（下次怎么做）

可选的 Honcho 外部 Memory Provider 提供语义搜索、跨会话结论和用户画像。

### 三层记忆系统

| 层 | 内容 | 特点 |
| --- | --- | --- |
| Session Context | `MEMORY.md`（环境事实/项目约定）+ `USER.md`（用户偏好/画像） | 会话开始注入系统提示；修改立即写盘、下次会话才生效（保 Prompt 前缀稳定） |
| Episodic Archive | 全部会话存 SQLite，按需检索 | 容量大、无固定 token 成本 |
| Skill | 较长的操作流程与可复用方法 | 相关任务才加载，渐进式披露：先看名称描述，需要时读全文 |

直观理解：Memory 是随身携带的少量关键事实，Archive 是需要时查阅的完整经历，Skill 是从经历中抽象出的做事方法。

## 定位与边界

Hermes 的主路径是**上下文/记忆进化**；Skill 创建与 patch 是 Harness 级轻量结构进化；**不更新权重，不属于参数进化**。最大价值：不需要等待模型重新训练，Agent 也能在使用中逐步形成属于自己的工作方法。

它与 [DSH](/docs/CS/AI/LLM/DSH.md)、[Codex](/docs/CS/AI/LLM/Codex.md) 同属 Harness 工程实例，但侧重不同：Codex/DSH 重在工具闭环与执行安全，Hermes 重在跨会话的记忆与 Skill 沉淀。

## Links

- [Self-Evolving](/docs/CS/AI/LLM/Self-Evolving.md) — 自进化理论、评测与 CI/CD（Hermes 案例的完整上下文）
- [Harness](/docs/CS/AI/LLM/Harness.md) — Harness 补偿面理论与 Agent 开发三层
- [Skill](/docs/CS/AI/LLM/Skill.md) — SKILL.md 规范
- [Agent](/docs/CS/AI/LLM/Agent.md) — Agent 四构成（Loop/Tools/Memory/Harness）
- [DSH](/docs/CS/AI/LLM/DSH.md) / [Codex](/docs/CS/AI/LLM/Codex.md) — 另外两个 Harness 工程实例

## References

- [DeepEvolution（二）：Hermes 的自进化设计](https://mp.weixin.qq.com/s/mCD-dfq9SMJQJB-jxN8XWw)
