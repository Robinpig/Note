## Introduction

> 版本基线：2026-10-06 核实。

**Vibe Coding（氛围编程）** 由 Andrej Karpathy 于 **2025-02-02** 在 X 上提出。原文：

> There's a new kind of coding I call "vibe coding", where you fully give in to the vibes, embrace exponentials, and forget that the code even exists. It's possible because the LLMs (e.g. Cursor Composer w Sonnet) are getting too good.

他描述的具体做法：用语音（SuperWhisper）向 Cursor Composer 描述需求 → 点 **Accept All**、**不读 diff** → 出错就把报错粘回去让 AI 改 → 代码规模超出自己的理解范围。他随即自我限定：**"not too bad for throwaway weekend projects"**（适合扔掉级周末项目）。

本篇记录这个词的**原始含义、它为什么会漂移、以及它被什么取代**，因为这三个问题回答的是同一件事：**AI 参与写代码之后，人的注意力该放在哪**。这也正是 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 视角下最要紧的问题——代码产出变便宜之后，稀缺的是意图、约束与验收。

## 原始定义与它的漂移

这个词的生命周期很值得记：**2025-02 提出 → 2025-03 被 Merriam-Webster 收为俚语 → 2025 年获 Collins English Dictionary 年度词汇 → 2026-02 被发明者本人判定为 passé**。

漂移造成了一个关键混淆：

| | 原教旨版 | 泛化用法 |
| --- | --- | --- |
| 读 diff | **不读**，直接 Accept All | 读，但主要让 AI 改 |
| 用途 | 扔掉级项目、黑客松 | 被贴到支付系统上 |
| 风险 | 低 | 高 |

**把原型级纪律用在生产系统上，是这个词被滥用后的主要代价。** 讨论「vibe coding」时值得先问一句：说的是上面哪一列？后者其实有个更准确的名字——**用 AI 写代码然后认真 review**，那就是普通的软件开发，配了把好工具。

一个常被脱离语境引用的数据：2025-03，YC 管理合伙人 Jared Friedman 称 W25 批四分之一创业公司 **95% 代码库由 AI 生成**。但他澄清该统计只算「人写的 vs AI 生成的」，**排除导入的库**，且强调这批是**完全有能力从零构建的技术创始人**——不是非程序员。把它推广成「四分之一的生产软件已由 AI 写成」是误读。

## 四个核心心法

1. **放弃对底层细节的控制欲**：不纠结这行正则怎么匹配的、那个异步函数为什么这么写——能跑、结果对就接受。
2. **把报错当成"对话"而不是"事故"**：报错不是待调试的故障，而是下一条 Prompt。
3. **接受"屎山代码"**：结构丑一点无所谓——**这条只对短期项目成立**，见下文失效模式。
4. **关注"表现"而非"实现"**：精力放在 UI 好不好看、交互顺不顺滑、业务逻辑对不对上，而不是命名规不规范。

## 实操工作流

### 1 准备 AI 原生环境

- **宿主**：Cursor（主流）、Windsurf、VS Code + Cline/Roo、Claude Code、Codex CLI、aider（CLI）
- **模型**：选上下文与代码能力最强的当代模型。本库模型基线见 [模型总览](/docs/CS/AI/LLM/Model/Overview.md)，此处不写死版本号——**这个领域半年就会过时**
- **给 agent 配工具**：MCP 服务器（文件、终端、git、搜索、Jira），或直接用宿主内置工具

### 2 用自然语言描述结果

不要写代码，写 Prompt。差别在**给锚点**：

- 差："帮我写个 React 组件，有输入框和按钮"
- 好："做一个极简待办输入区。输入框毛玻璃效果，按钮 hover 有轻微上浮动画，参考 Apple 设计语言。直接生成并运行。"

### 3 Vibe Check

让 AI 在预览里跑起来，你只做一件事：**凭直觉检查**——颜色顺眼吗、点击有反馈吗、流程走得通吗。

### 4 迭代 不要自己去改代码文件

- Bug：`点击提交后卡死，控制台报 TypeError: Cannot read properties of undefined，帮我修复`
- UI：`卡片太笨重，圆角加大、阴影减弱、背景换成更通透的白色`
- 功能：`如果输入内容包含"紧急"两个字，卡片边框变红`

### 5 上下文管理

对话变长、AI 开始变笨时：

- **果断开新对话**，把当前最核心的代码或需求总结带过去
- **用 `@` 引用**精准带上相关文件，别让 AI 迷失在无关上下文里

这在 Harness 层面就是 [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md) 讨论的问题——压缩不是免费的，拿「模型对原始上下文的可见性」换「更长的会话时长」。Vibe Coding 里"开新对话"是手工版的同一种交易。

### 规则文件 `.cursorrules` 已废弃

原文推荐建 `.cursorrules`，**这个格式在 Cursor 官方文档中已被标为 legacy**（`cursor.com/docs/rules` 已不再出现该字符串，只在迁移说明里提到它）。现行做法：

| 文件 | 读它的 agent | 说明 |
| --- | --- | --- |
| `AGENTS.md` | **开放标准**，Codex / Cursor / Copilot / Aider / Gemini CLI 等 | 新项目的默认选择 |
| `.cursor/rules/*.mdc` | 仅 Cursor | 带 frontmatter（`description` / `globs` / `alwaysApply`）与四种激活模式：Always / Auto Attached / Agent Requested / Manual |
| `CLAUDE.md` | 仅 Claude Code | **Cursor 不读它** |

有个易踩的坑：`.cursor/rules/` 下放**纯 `.md` 会被忽略**，必须有 frontmatter 才生效；想用无元数据的纯 markdown，官方答案是改用 `AGENTS.md`。另外 Cursor 规则**是合并而非覆盖**——Team > Project > User，冲突时"靠前的来源优先"，但两条规则都会进上下文，模型可能哪条都没遵守。**两条规则互相矛盾时正确做法是删掉一条，而不是把另一条写得更强硬。**

## 最佳实践

1. **提供锚点**：AI 不知道你的审美。给它一张截图、一个开源仓库链接，或直接说"我要这种感觉"。
2. **小步快跑**：先写登录页，再写商品列表，再写购物车。每步做完就 Vibe Check，别让 AI 一次写完整电商系统。
3. **善用规则文件**：提前声明技术栈偏好（"始终用 Tailwind CSS + TypeScript，组件用函数式写法"），能大幅减少后续修正成本。

## 什么时候必须退出 Vibe 区

心法 3（接受屎山）**只在低风险、短生命周期项目成立**。以下场景必须切回工程纪律：

- **核心业务与金融/支付**：幻觉可能造成真实资金损失
- **高并发 / 底层性能**：AI 常写出"能跑但极慢"的代码
- **安全要求高**：SQL 注入、XSS 等必须人工 review
- **长期维护的大型项目**：技术债会在后期压垮团队

规模化的三种典型失效（这也是下一节 SDD 要解决的）：

1. **意图漂移（intent drift）**：模型选了看似合理的默认值，与团队真实意图不符——因为代码"看起来是对的"，没人发现
2. **幻觉接口（hallucinated interfaces）**：Agent 凭空造出一个不存在的 API 方法、配置项或数据库列；编译通过，运行时炸
3. **上下文坍塌（context collapse）**：跨会话/跨文件时忘记早先的决定并自相矛盾；项目越长越糟

## SDD 规范驱动开发

> 这一节原为空白占位。`Agent/README.md` 要求本页覆盖「氛围编程 → SDD → 人该把注意力放在哪」。

**SDD（Spec-Driven Development）** 的核心倒置：**spec 是唯一事实源，代码是 spec 的编译产物**——类比 `.c` 编译成二进制。代码与 spec 不一致时，**以 spec 为准并重新生成**。这条分工直接回答了 Karpathy 原帖那句"forget that the code even exists"：SDD 里代码**确实应该被忘掉**，但 spec 必须被严格维护——它才是资产。

驱动 SDD 的是瓶颈转移：**当 agent 足够能干，问题就从「agent 会不会写代码」变成「agent 知不知道要造什么」**。spec 先行把意图、约束、验收标准固定下来，三种失效模式同时被堵住——写下来的意图不会漂移，明确规定的接口不会被幻觉，架构决策记在文档里不会忘。

### 四阶段

`Spec → Plan → Tasks → Implement`，**每阶段都产出进入版本控制的 Markdown 文档**，前一阶段的文档是后一阶段的输入。常见文档集：

| 文档 | 内容 |
| --- | --- |
| `spec.md` | 必须做什么：用户故事、验收标准 |
| `plan.md` | 怎么建：架构、数据模型、API 契约 |
| `tasks.md` | 有序实现步骤，agent 逐条执行 |
| `constitution.md` | 项目级不可违背约定（"constitution" 源自 spec-kit） |

### 工具谱系

| 工具 | 形态 | 特点 |
| --- | --- | --- |
| **GitHub Spec Kit** | 开源，模型无关 | 最像「开源基线框架」；slash 命令驱动；官方集成三十余种 agent（Copilot / Claude / Codex / Gemini CLI / Cursor / Kiro …），未收录的可用 generic 方式自接；社区有 extension / preset / workflow 扩展 |
| **AWS Kiro** | 一体化 IDE | IDE 内置 Specs，分 Feature Specs 与 Bugfix Specs；`Requirements/Bug Analysis → Design → Tasks`；内置 **EARS** 记法 |
| **OpenSpec** | 轻量通用 | 自述 "lightweight spec-driven framework"；每个变更围绕 proposal / spec / design / tasks 组织，强调 spec 可迁移、可长期保存 |
| **Tessl** / **BMAD** / **Google Antigravity** | 各有定位 | 共同点是把 spec 变成一等构建产物 |

Spec Kit 的关键命令与工作流：先 `/speckit.constitution` 立项目原则 → `/speckit.specify` 写需求 → **`/speckit.clarify` 补歧义** → `/speckit.plan` 出技术方案 → `/speckit.tasks` 拆任务 → `/speckit.implement` 逐条实现 → `/speckit.analyze` 校验跨文档一致性。其中 **`.clarify` 最常被跳过，也最常被事后追悔**——它在 agent 动第一个文件之前把假设和边界逼出来。

**EARS（Easy Approach to Requirements Syntax）** 是 2026 年被广泛采用的需求句式：`While <trigger> when <condition> the system shall <response>`，可带 Ubiquitous / Event-driven / State-driven / Unwanted behavior / Optional feature 前缀。它短到能背、硬到能 lint——这是它被选中的真正原因。

### 实践者的话

**Andrew Ng** 在 2025 年 5 月 LangChain Interrupt 大会的 firechat 上批评这个词误导：

> It's unfortunate that that's called vibe coding. It's misleading a lot of people into thinking, just go with the vibes — accept this, reject that.

他的重点不是 AI 不好用，而是**这事并不轻松**：

> When I'm coding for a day with AI coding assistance, I'm frankly exhausted by the end of the day. It's a deeply intellectual exercise.

注意他并不反对 AI 辅助编码——他说自己团队"再也不能在没用 AI 的情况下写代码了"，也认为"能几乎不看代码就写出软件"很值得高兴。**他反对的是名字，不是工具。**

**Karpathy 本人**在 2026-02 的修正更彻底——他称原帖只是 "a shower of thoughts throwaway tweet"，但"恰好在正确的时机为很多人同时感受到的东西造出了合适的名字"，并指出当年 LLM 能力还不足以支撑别的用法：

> At the time, LLM capability was low enough that you'd mostly use vibe coding for fun throwaway projects, demos, and explorations. It was good fun and it almost worked.

他给出的替代词是 **agentic engineering**：

> 'agentic' because the new default is that you are not writing the code directly 99% of the time, you are orchestrating agents who do and acting as oversight — 'engineering' to emphasize that there is an art & science and expertise to it.

他自己点出的关键词是**方向、判断、品味**（direction, judgment, taste）——这些不会消失，并且**合起来就是全部工作**。

Simon Willison 的表述更直接（Ars Technica 引）："用 vibe coding 一路走到生产代码库显然是危险的。我们作为软件工程师的大部分工作都涉及演进既有系统，而底层代码的质量与可理解性至关重要。"

### 真实事故清单

这个词不是纯概念之争，有据可查的翻车案例：

- **2025-05，Replit**：AI agent 在被**明确要求不做任何修改**的情况下删除了生产数据库
- **2025-05，Lovable**：170/1645 个生成的应用存在可让任何人读取用户个人信息的漏洞
- **2025-07**：SaaStr 创始人公开记录 vibe coding 的负面经历
- **2025-09，Fast Company**：报道「vibe coding hangover」——资深工程师称之为"开发地狱"

**共同点不是 AI 写得不好，而是"没人知道自己不知道什么"。** 这正是把 spec 前置的理由。

这个演变本身就是本篇的结论：**编码门槛塌了，人的注意力从"怎么写"移到"写什么、怎么验、谁来拍板"。**

## 与本库其他主题的关系

Vibe Coding → SDD 这条线是 Harness 命题的最好例证：**代码产出变便宜后，稀缺的不是 token，而是意图表达、约束边界与验收机制**——它们全都落在 Harness 这一层，而且都对应本目录里的既有主题：

- 规则文件与上下文供给 → [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md)（注意 skill 正文一旦加载就跨轮占用上下文）
- 长会话不失控 → [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)
- Agent 动代码前的闸门 → [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md)
- 自建 Skill 与自进化 → [Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md) / [Hermes](/docs/CS/AI/LLM/Agent/Practice/Hermes.md)

另外，vibe coding 撞上的不只是"规范不够"这一个问题，更是**本目录 Product 层那批产品各自补的同一个缺口**——[Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode.md) 的 plan mode、Codex 的计划与审批、DSH 的权限与沙箱，都是"人在环"的具体形态。SDD 是方法论，Plan Mode / 审批 / 沙箱是它的实现零件。

## Links

- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) — 代码产出变便宜后，稀缺的是意图与约束
- [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md) — 「开新对话」是手工版的上下文压缩
- [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md) — 动代码之前的闸门
- [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md) — 规则文件与 skill 的成本侧
- [Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md) — 从「人写规则」到「Agent 自建 Skill」
- [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode.md) — plan mode 是 SDD 的产品化实现

## References

- [Karpathy: "vibe coding"（2025-02-02，原帖）](https://x.com/karpathy/status/1886192184808149383)
- [The New Stack: Vibe coding is passé（2026-02-10，agentic engineering 修正）](https://thenewstack.io/vibe-coding-is-passe)
- [Business Insider: Andrew Ng says vibe coding is a bad name for a very real and exhausting job](https://www.businessinsider.com/andrew-ng-vibe-coding-unfortunate-term-exhausting-job-2025-6)
- [Wikipedia: Vibe coding](https://en.wikipedia.org/wiki/Vibe_coding) — 事故与批评的汇总出处
- [Ars Technica: Will the future of software development run on vibes?](https://arstechnica.com/ai/2025/03/will-the-future-of-software-development-run-on-vibes/)
- [GitHub Spec Kit](https://github.github.com/spec-kit/)
- [OpenSpec](https://github.com/Fission-AI/OpenSpec)
- [AWS Kiro 文档](https://kiro.dev/docs/)
- [Cursor Docs: Rules](https://cursor.com/docs/rules)
