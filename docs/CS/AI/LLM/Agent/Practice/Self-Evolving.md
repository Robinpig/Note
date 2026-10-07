## Self-Evolving (Self-Evolution)

## Introduction

Agent 能不能完成任务固然重要，但它能不能**从过去的任务中积累经验**，决定了它是否会越用越顺手。自进化（Self-Evolving）研究的正是：如何把一次次会话中的经历，转化为下一次可以复用的能力。

三种进化路径：

| 路径 | 更新的对象 | 例子 |
| --- | --- | --- |
| 上下文 / 记忆进化 | 下一次推理可见的事实、历史与用户模型 | Memory、召回、画像 |
| 结构进化 | Agent 可调用的流程、约束与操作方法 | Skill 创建/更新、ADAS |
| 参数进化 | 模型权重 | 训练 / 微调 |

> 核心结论：自进化不是"自动改动"，而是一条 **Agent CI/CD 流水线**——系统可以自动提出改变，但改变必须经过评测、门控、灰度、监控和回滚，才能成为新的稳定能力。

**Evolve Loop 六步**（经历 → 能力）：

1. Agent 在真实环境执行任务，产生对话、工具调用、错误与结果
2. 完整轨迹写入 SessionDB，成为可回溯的经历
3. 检索（如 FTS5）按关键词从历史会话找回相关消息
4. 后台复盘判断是否存在值得长期保存的事实或可复用流程
5. 结论写入 Memory / User Profile，或保存为可复用的 Skill
6. 下一次任务开始时，相关记忆和 Skill 重新带入上下文，改变 Agent 行动方式

闭环的核心不是"保存所有内容"，而是**将经历分层**：事实进入记忆，过程保存在会话档案，可复用的方法升级为 Skill。

## Hermes Case Study: Hermes's Self-Evolution Design

### Architecture: Self-Evolution Is Not an Isolated Module

三层主干架构：入口层（CLI / Gateway / ACP / Batch Runner / API Server / Python Library）→ AIAgent 核心层（Prompt Builder 组装提示/上下文/记忆/画像/Skill、Provider Resolution、Tool Dispatch）→ 存储与工具后端层（Session Storage 用 SQLite+FTS5 保存会话；Tool Backends 让 Agent 真正进入环境执行）。

三种入口（CLI Session、Gateway Message、Cron Job）数据流不同，却共享同一套执行、存储、记忆和 Skill 机制——**轨迹被统一保存，Evolve Loop 才能跨入口工作**。

### Periodic Nudges: Review Becomes a Background Mechanism Instead of Occasional

一轮交互结束后，系统可派生一个**独立复盘过程**：重新审视会话快照，判断是否应新增/修改记忆与 Skill。复盘与主会话分离（不改进行中的上下文），默认只有记忆管理、Skill 管理和只读文件工具，可配置更便宜的辅助模型。

它解决两个矛盾：全量塞回 Prompt → 上下文越长重要信息越稀释；完全依赖任务中主动记忆 → Agent 专注当前目标忘了沉淀。**Nudge 是在"什么都保存"和"什么都忘记"之间的筛选器。**

### Autonomous Skill Creation: Distilling Procedural Memory

`skill_manage` 允许 Agent 创建、修改、删除自己的 Skill。典型触发场景：找到可复用的多步骤工作流；经历死路后找到正确路径；用户纠正了处理方式。经验写成 `SKILL.md` 存入 `~/.hermes/skills/`——包含步骤、约束、避坑说明、引用资料和辅助脚本，是比零散记忆更完整的"程序性记忆"。

**Skill Self-Improvement 优先用 patch**：只需 Skill 名 + 旧文本 + 新文本三个参数。优势：影响范围小（保留已验证内容）、上下文成本低（只传变化部分）。可开启 `skills.write_approval` / `memory.write_approval`——后台变更先进待审核区，人看差异后决定是否应用：**Agent 可以提出改进，但高风险环境仍应保留人的确认权。**

### FTS5 Session Search: Retrieval Is Not Memory Itself

会话统一存 `~/.hermes/state.db`，FTS5 全文索引。`session_search` 按关键词返回**数据库里的真实消息**（不调 LLM、不摘要、不截断——不要与官网宣传的 "LLM summarization" 混淆）。分工：

- FTS5 负责低成本回答 **what happened**（过去发生过什么）
- 后台复盘和 Skill 提炼负责回答 **how to solve it**（下次怎么做）

只有把检索和抽象接起来，历史记录才可能转化为能力。可选的 Honcho 外部 Memory Provider 提供语义搜索、跨会话结论和用户画像，增强"Agent 对谁服务"的理解。

### Three-Layer Memory System

| 层 | 内容 | 特点 |
| --- | --- | --- |
| Session Context | `MEMORY.md`（环境事实/项目约定/经验）+ `USER.md`（用户偏好/画像） | 会话开始注入系统提示；会话级快照——修改立即写盘，下次会话才进提示（保 Prompt 前缀稳定） |
| Episodic Archive | 全部会话存 SQLite，`session_search` 按需检索 | 容量大、无固定 token 成本，回答"以前发生过什么" |
| Skill | 较长的操作流程与可复用方法 | 只在相关任务加载，**渐进式披露**：先看名称描述，需要时再读全文 |

三层的直观理解：Memory 是必须随身携带的少量关键事实，Archive 是需要时查阅的完整经历，Skill 是从经历中抽象出的做事方法。

**Hermes 的定位**：主路径是上下文/记忆进化；Skill 创建与 patch 是 Harness 级轻量结构进化；不更新权重，不属于参数进化。最大价值：**不需要等待模型重新训练，也能让 Agent 在使用中逐步形成属于自己的工作方法。**

## Evaluation: No Evaluation, No Evolution

评测不是进化完成后的验收环节，而是整个 Evolve Loop 的**信号源**。信号不准，Agent 不仅不会进化，反而会更稳定地重复错误。

### Triple Responsibilities

1. **方向指引**：告诉系统问题出在哪，下轮该改 Prompt、流程、工具还是记忆
2. **质量门控**：判断候选版本是否真的优于基线，防止错误更新污染后续任务
3. **经验筛选**：区分值得沉淀的成功路径与不应复用的偶然结果

传统评测打错分只是发布了个不够好的版本；自进化评测打错分，会让 Agent 把错误经验持续写进未来。

### Three Observation Surfaces

- **结果质量**：任务是否完成、输出是否准确完整符合约束
- **过程质量**：工具调用是否正确、关键步骤是否执行、路径是否安全可复现
- **资源效率**：Token、时延、工具调用次数是否合理——**必须在同预算下比较**，多花三倍 token 换一点点提升不算进化

实用策略：日常评测先做结果级筛选，失败样本和关键链路再做轨迹级诊断。

### Seven Evaluation Pitfalls

1. 评估器本身不可靠——LLM-as-Judge 偏爱长答案/特定表达，Agent 会学会迎合评估器
2. 只评结果不评过程——答案对不代表路径对
3. 评测粒度选错——整任务一个成败无法定位，逐节点检查成本爆炸；粗粒度筛选 + 细粒度诊断
4. 开放式任务难量化——与其打绝对分，不如 A/B 成对比较 + 拆维度
5. 评测集漂移——旧样本分数越来越高，真实体验持续下降
6. 忽略预算公平性——更多重试/采样/Token 换来的表面提升
7. 每次修改都跑全量评测——分层运行：日常核心回归集 → 候选验证集 → 上线最终测试集

### Three-Layer Evaluation System

精度、成本、覆盖面很难同时拉满，解法是分层组合：

1. **底层：规则与自动化校验**——能确定性判断的先交给规则（测试通过、Schema 合法、字段完整、超限拦截）。成本低、客观、覆盖面最大
2. **中层：LLM-as-Judge 与对照实验**——拆分评测维度、固定结构化输出、优先成对比较、同批样本同配置
3. **顶层：人工抽样与元评测集**——定期抽样比对人与 Judge 的一致性；维护已知正确/错误/边界样本检查评估器偏移

核心原则：**能用便宜、确定的方法覆盖，就不要急着用昂贵、主观的方法。**

### Evaluation Set Responsibility Isolation

同一批样本既发现问题、又选择方案、还证明有效 → 系统对这批题过拟合。三集分离：

- **Train 诊断集**（50-60%）：发现失败模式、分析根因，可暴露给修复 Agent
- **Validation 筛选集**（20-30%）：比较候选与基线，不暴露答案
- **Test 最终验证集**（15-20%）：上线前独立检查，保持精简稳定、严控使用频率

更新节奏：线上新失败样本持续进 Train；Validation 定期换旧样本；Test 只在任务分布明显变化时更新。

### The Endpoint Is Attribution, Not Scores

"60 分"不告诉你该改什么。失败四类归因：

- **系统性问题**：多样本同一种错误 → 触发 Prompt/流程/Playbook 更新
- **偶发个例**：孤立错误 → 写入案例或记忆，等更多证据
- **能力缺失**：缺工具/知识/数据 → 补能力，而不是继续改 Prompt
- **回归问题**：旧版本能做、更新后失败 → 立即回滚，样本加入核心回归集

### Evaluators Also Need Calibration

谁来评测评估器？人工校准（定期抽样、多人独立判断）、多评估器交叉（分歧进人工复核）、元评测集监控、无泄漏诊断。评估器偏移时应**先暂停自动写入记忆或流程**。评估器不是最终权威，而是需要监控、校准和回退的系统组件。

## Agent CI/CD: Self-Evolution Is Not Fully Automatic

### Three Reasons Automation ≠ Full Automation

1. **单次任务看到的上下文不完整**——不知道规则背后的历史决策与兼容性要求，一次"合理"重写可能删掉稳定的边界逻辑
2. **局部改进 ≠ 全局改进**——改一个 Skill 的输出格式可能破坏另一个的输入契约；只有完整任务集比较才能判断是进化还是过拟合
3. **错误经验会复利**——未验证的 Skill 进入知识库会被当正确经验继续提炼（技能污染，论文 *When Self-Evolution Backfires*）；准入门控必须发生在变更提交之前

合理边界：**允许 Agent 自动发现、自动提议、自动实验；是否进入稳定版本，由证据和治理流程决定。**

### Seven-Stage Closed Loop

信号汇聚（评测诊断/线上失败/用户纠正/历史 Playbook/外部研究）→ 生成候选（只是候选，不能覆盖稳定版本）→ 独立评测（隔离环境、同数据集同预算同评测器）→ 安全门控（结构检查→回归评测→统计检验→一致性检查→高风险人工确认）→ 灰度发布（如 10% 流量观察 7 天，比例由业务风险决定）→ 监控与回滚（触发阈值立即撤回）→ 经验沉淀（成功写 Playbook，失败也记录假设/证据/原因）。

### Five Engineering Pillars

1. **三路信号汇聚**：本轮评测（哪里出问题）+ 历史 Playbook（以前为什么这样设计）+ 外部研究（尚未尝试的新方向）
2. **分层门控**：自动门控承担规模，人负责最后的责任边界
3. **灰度与回流**：离线数据覆盖不了真实用户表达与长尾环境；失败不是被隐藏，而是被送回候选池
4. **版本化一切**：Prompt、Skill、Memory Schema、工作流、Harness 配置都要有版本号/来源/变更说明/评测结果——没有版本无法比较，没有来源无法追责，没有稳定版本谈不上回滚
5. **Diff 修改**：默认倾向补丁式更新而非整文件重生成——变化半径越小，验证成本和意外破坏越小（SkillOS：执行器保持冻结，专门 Skill Curator 更新 SkillRepo——生成答案和治理能力库是两种职责）

### Dreaming: Discovering Long-Term Patterns Beyond Tasks

同步评测看一条轨迹，难以发现跨项目/跨时间反复出现的问题。异步 Dreaming（Claude Managed Agents 研究预览）按计划回顾历史会话与记忆，寻找三类模式：反复出现的失败原因、成功但成本/时延明显偏高的路径、Skill 与记忆未覆盖的知识缺口。输出应为**结构化候选**（证据/频率/影响范围/建议位置/预期收益/风险等级），进入同一条 CI/CD 管线。分工：**同步评测优化单次任务，异步 Dreaming 发现系统性模式；它们都提出变化，但都不跳过发布治理。**

### Seven Questions for Implementation

信号可靠吗？变化范围清楚吗？基线可比较吗？门控完整吗？可以灰度吗？能够回滚吗？经验会回流吗？——**任何一项答不上来，系统就还没准备好自动应用变化。**

## Human Role: Calibrator of Evolution Direction

> 人的价值不在于逐步操作 Agent，而在于设定目标、划定边界、处理高风险例外，并校准长期进化方向。

### Human-at-the-right-step

每一步都要人确认的 Human-in-every-step 会把人拖回执行细节：任务多了人是吞吐瓶颈，提醒多了产生审批疲劳（机械点同意或干脆关闭审核）。合理分工：**Agent 负责高频、可验证、可回滚的执行；人负责低频、高影响、带价值判断的决策。**

人提供三类不可替代的输入：高质量数据（用户纠正/领域案例/失败证据）、价值判断（什么值得优化、什么代价不可接受）、最终裁决（高风险变更是否上线、回滚到哪、哪些权限永不开放）。

### Autonomy Is an Adjustable Level

| 等级 | 描述 | 适用 |
| --- | --- | --- |
| Level 0 人工执行 | Agent 分析建议，人完成动作 | 新领域、不可逆操作、高风险 |
| Level 1 提案后审批 | Agent 生成候选附 Diff/证据/评测，人批关键变更 | 多数自进化系统的默认起点 |
| Level 2 受监督自治 | 低风险变化过自动门控即生效，持续监控，异常升级给人 | — |
| Level 3 高度自治 | 边界内持续优化，人做周期性方向审计 | 成熟、可逆、证据充分、回滚可靠 |

原则：**能力与权限必须分开**（技术上能改文件 ≠ 系统应该授权）；升级由连续证据驱动（稳定成功率、无严重回归、回滚演练过），降级由严重回归/越权/安全告警/方向漂移触发。

### Five Categories of Decisions That Can Never Be Permanently Delegated to Agents

1. **规则级记忆的准入**——"这次方案 A 不错"和"以后永远用 A"完全不同，错误规则会被反复调用并衍生新错误
2. **Prompt/Skill/权限规则更新的最终确认**——执行者不能决定自己的红线（Agent 不能删除自己的安全约束）
3. **回归后的业务裁决**——回滚到哪版、冻结什么、暂停管线，涉及用户影响和业务代价
4. **新领域冷启动**——没有历史数据时 Agent 不知道什么叫"好"，首批样本/初始 Skill/安全边界必须由领域专家提供；第一圈必须有人推动
5. **安全边界的设定与调整**——默认最小权限，红线不能由被红线约束的执行者自行决定

### Combating Review Fatigue: Three Channels

1. **自动化高置信过滤**：格式/静态/回归/显著性/规则一致性先挡掉明显错误，只把值得判断的变化交给人
2. **批量异步审核**：中风险更新按主题聚类，一次判断一类变化（只展示 Diff、证据、关键评测变化）
3. **高风险实时授权**：安全边界、权限扩大、不可逆操作执行前明确授权，保留责任人/理由/版本记录

核心不是让人看更多，而是**减少无意义审核，提高每次介入的信息密度**：风险与不可逆性越高，人的介入越同步、越深入。

### Direction Observation: Preventing 'Every Step Right, Whole Thing Drifts'

门控检查"这步是否安全"，无法判断"一百步后是否仍在靠近目标"。方向漂移的例子：成功率持续提高但回答越来越长；工具调用变多没有收益；拒答率不断升高；为满足评分器失去自然表达。三层防护：

1. **定期方向审计**：每月/每版本回看 Skill 库、记忆类型、输出风格、权限变化是否符合最初设计意图
2. **方向性约束指标**：平均输出长度、工具调用次数、无效重试率、拒答率、人工纠正率、单位成功任务成本
3. **评测集显式加入意图对齐**：不只问答案对不对，还检查简洁性、格式规范、语气适度、是否过度拒绝

**Agent 越自主，人越不需要盯着每一步；但人越需要看清它正在成为谁。**

## Caution: Existence of a Loop ≠ Every Iteration Improves

Agent 可能保存错误记忆、把偶然成功误判为通用经验、Skill 多次 patch 后冲突、把不安全内容带入后续会话。没有任务成功率/成本/人工反馈/回归测试，就无法证明新 Skill 优于旧版本。可靠的 Evolve Loop 还需要：

- 明确什么经验值得保存，什么只属于一次性上下文
- 为自动写入保留审核、版本和回退机制
- 用真实任务或测试验证 Skill 修改是否带来改善
- 定期清理过期、冲突和低价值的记忆

**自进化最重要的能力，不是"自己敢改"，而是"知道什么时候可以改、为什么值得改，以及改错后怎样安全回来"。**

## Links

- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) / [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md) — Skill 是自进化沉淀的核心载体
- [Hermes](/docs/CS/AI/LLM/Agent/Practice/Hermes.md) — 自进化 Agent 的完整工程案例
- [DSH](/docs/CS/AI/LLM/Agent/Product/DSH.md) / [LLM](/docs/CS/AI/LLM/LLM.md)

## References

- [DeepEvolution（二）：Hermes 的自进化设计](https://mp.weixin.qq.com/s/mCD-dfq9SMJQJB-jxN8XWw)
- [DeepEvolution（三）：没有评测，就没有进化](https://mp.weixin.qq.com/s/VDE1K2k_n7xdTEO6uUtCsQ)
- [DeepEvolution（五）：Agent CI/CD 流水线](https://mp.weixin.qq.com/s/VEvoN5PG05SRg8wCdU1Rpg)
- [DeepEvolution（六）：人是进化方向的校准器](https://mp.weixin.qq.com/s/jAKOEngu-0kCD-A9D3h2iQ)
- SkillOS: Learning Skill Curation for Self-Evolving Agents
- When Self-Evolution Backfires: Pre-Commit Gating against Skill Contamination in LLM Agents
- MOSS: Self-Evolution through Source-Level Rewriting in Autonomous Agent Systems
- MUSE-Autoskill: Self-Evolving Agents via Skill Creation, Memory, Management, and Evaluation
- NIST AI RMF / Levels of Autonomy for AI Agents
- Claude Managed Agents: dreaming, outcomes, and multiagent orchestration
