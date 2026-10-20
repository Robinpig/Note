## Introduction

`Agent/` 装的是**包裹模型的那层东西**——让只会输出 token 的模型能在真实环境里执行、持久记住、并且会自我纠错。LLM 的四个局限（只会说不会做、没有记忆、知识截止、不会规划）都指向同一个结论：缺的不是更多参数，而是这层架构。

这个目录按**「机制 → 产品 → 演进」**三层组织。这个划分不是按篇幅或时间，而是按**读者要回答的问题**：想搞懂原理看 Theory，想选一个工具干活看 Product，想知道这层架构往哪走看 Practice。

| 分层 | 装什么 | 
| :--- | :--- |  
| Theory | 机制与概念：Agent 四组件、经典范式、Harness 工程、权限与沙箱、Skill 规范、上下文压缩 |  
| Product | 具体的 Agent 产品与框架实现 |  
| Practice | 演进方向与开发方式的自变化 | 

## How the Six Theory Articles Divide Responsibilities

这几篇的关系是**从抽象到具体**，不是并列：

**[Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)** 是总纲。它给出最核心的那个定义——**AI Agent 是一个能调用工具的循环系统**，以及四组件（Loop / Tools / Memory / Harness）。它的 ReAct 循环四步（Reason / Act / Observe / 回环）是所有 Agent 表面不同、底层一致的那层机制。常见的 Agent 模式（ReAct、Plan-and-Execute、Multi-Agent、SubAgent）也在这篇。

**Paradigm** 回答循环内部的组织方式问题：同样的 Reason-Act-Observe 四步，ReAct 每步重新决策（走一步看一步）、Plan-and-Solve 先一次性产出完整计划再严格执行（三思而后行）、Reflection 在任务完成后追加"执行-反思-优化"的自我批判迭代。三种范式各自的机制、提示词设计、代价与选型都在这篇。它的落点是一个 **TypeScript 最小 Agent Loop**——单文件、零第三方依赖，把提示词协议、正则解析、history 回灌、Finish 收敛、maxSteps 安全阀全部写进一个十几行的循环里；框架做的事，就是在这十几行上加重试、观测、权限与压缩，所以想看懂框架的抽象层究竟加在哪，先读这十几行。

**Harness** 是四组件里最容易被误解的一个，也是真正决定成败的一个。它的定义反直觉：**Harness 不是「越多越好」，而是对模型能力缺口的补偿面**。模型每强一分，曾经必需的组件就该抽掉一层——照抄别人的组件清单不会让 Agent 变强，反而可能在长任务里拖后腿。所以那篇值得读的不是「有哪些组件」，而是「现在该补哪一块、该拆哪一块」的判断方法。它还厘清了一个高频混淆：Runtime / Framework / Harness 三层分别解决「能稳定运行」「能方便开发」「能直接完成复杂任务」。

**Permission** 讲 Agent 能不能动、动了要不要问。这篇的核心结论是**沙箱与权限是两层不同的东西**：沙箱管「能不能」（OS 强制，Seatbelt / bubblewrap / Landlock+seccomp），权限管「该不该」（进程判定，deny → ask → allow）。它最反直觉的地方是**默认值差异大到危险**——Claude Code 沙箱默认关闭、OpenCode 权限默认全放行、Cline `--auto-approve` 默认 true，而 Codex 与 DSH 默认保守。另外记录了两个跨产品迁移最容易踩的坑：OpenCode「最后匹配者胜」与 Claude Code「deny 优先」是**相反的优先级模型**；以及本地 Agent 里**防线构建者和绕过者是同一个人**，所以企业管控必须是 managed settings 这类强制层而非默认配置。那篇还逐条核实并修正了本库此前关于 Claude Code 企业策略路径、DSH 插件计数与 `fs-local`、Linux 沙箱主流做法的三处过时结论。

**Skill** 是能力封装的最小单元，解决的是「这段流程说明我在三个项目里各贴了一遍给 AI」。它最反直觉的地方在成本侧：**skill 正文一旦加载就跨轮持续占用上下文**，不是一次性步骤；而且每个 skill 的 description 都会进每轮上下文，装 50 个就是每轮都为 50 条 description 付费。这篇的字段规范部分有几个必踩的坑——`allowed-tools` 写错成下划线**静默失效不报错**、个人 skill 会覆盖项目 skill、Codex 超过上下文 2% 会静默省略部分 skill。

**Compaction** 讲长会话怎么在窗口耗尽前活下来。它最反直觉的地方在**代价结构**上：压缩不是免费的，而是拿「模型对原始上下文的可见性」换「更长的会话时长」——厂商承认能力会下降（Codex 每次压缩后向用户发警告，说长线程与多次压缩会让模型变得不够准确）。这篇的骨架是六件事：阈值怎么定（**几乎全是 token 预算，不是「最近 N 轮」**）、保留什么、摘要由谁生成（**基本都要额外调一次 LLM**）、能否恢复（**原文通常还在盘上，但模型几乎都取不回**）、失败怎么处理、以及和 KV 缓存的交互（**各家在压缩过程中刻意在保缓存**：DSH 把指令放在回放前缀之后以复用热前缀，Claude Code 复用 system prompt 层，Pi 干脆禁掉摘要请求的 cache 写入）。附一张五家对比表与「陷阱」清单——其中「压缩会不会丢 skill 正文」的精确答案在 Claude Code 官方表里：**会重新注入，但每 skill 上限 5K、总计 25K token，超限时最老的先被丢弃**，这比直接消失更隐蔽。

## Product: Ten Implementations

编程 Agent 是这一层最成熟的产品形态，几家的差异比想象中大，**不在「谁更强」而在架构选择**：

- **[Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)** 与 **[Codex](/docs/CS/AI/LLM/Agent/Product/Codex/Codex.md)** 绑定单一模型厂商（Anthropic / OpenAI），但把各自厂商的 Harness 特性用得最透。Claude Code 已拆分为枢纽主文件 + 7 个专题页（Architecture / Permission / Hooks / Memory / Subagents / Extensions / Headless），以 `@anthropic-ai/claude-code` 2.1.301 与官方文档为基线，覆盖三阶段 agentic loop、六权限模式与 auto mode 后台 classifier（默认拦截清单、3/20 次回退阈值）、Bash sandbox（Seatbelt / bubblewrap+socat）、33 个 hook 事件与 matcher/if 两级过滤、CLAUDE.md 四层拼接加载与 rules 路径限定、subagent 与 agent teams 的 mailbox 架构、Skills/Plugins/MCP/Output styles 四层扩展，以及 `claude -p` / `--bare` / GitHub Actions 的非交互面。Codex 那篇是**源码级剖析**（Rust 实现，从 `start_or_steer` 到 `run_turn` 的主循环、事件汇合、审批的异步实现），想理解「一个 Harness 内部长什么样」看它。已拆分为枢纽主文件 + 8 个专题页（Architecture / Turn / Tools / Approval / Sandbox / AppServer / Extensions / MultiAgent），以 commit `6b991972c5b5` 为基线覆盖 crate 地图、`run_turn` 主循环与采样前压缩、`ToolCallRuntime` 的 RwLock 并发闸门、审批 fail closed 与 `Granular` 五类开关、三平台沙箱后端、app-server v1/v2 协议、MCP/Skills/Plugins/Hooks/Connectors 五套扩展与多 Agent V2 / Memories / Code Mode。
- **[cc-haha](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)** 是 **Claude Code 的开源复刻 + Electron 桌面工作台**（MIT，引擎 `claude-haha` 源自修复的 Claude Code 源码）：在同源的 agentic harness 之上叠加 GUI 多会话工作台、内置浏览器预览、可视化 MCP / SubAgent 管理器、Skill 市场（ClawHub / SkillHub）、Agent Teams 可视化协作与 Dynamic Workflow 编排、Computer Use、BYO 多模型，以及 H5 远控 + 微信 / 飞书 / 钉钉 / Telegram / WhatsApp 整合与计划任务。已拆分为枢纽主文件 + 7 个专题页（Architecture / Models / Permission / AgentTeams / ComputerUse / Integrations / MCP_Skills），以 GitHub `main` 最新 commit 为基线，覆盖桌面外壳与 `claude-haha` 内核边界、5 档权限、多 Agent 协作画布、桌面控制授权、IM / 远控 / 定时任务；底层 loop / hooks / memory / subagents / skills / MCP 机制与 Claude Code 同源，统一交叉链到 [ClaudeCode 家族](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md) 不重写。

- **[OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)** 与 **[Pi](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)** 的卖点是**模型无关**——同一套 Agent loop 驱动 Anthropic / OpenAI / 任意 OpenAI 兼容端点。OpenCode 是客户端/服务器架构（内核是本地 HTTP 服务，TUI/Web/IDE 都是客户端，可远程 attach），已拆分为枢纽主文件 + 10 个专题页（Architecture / Agent / Tools / Rules / Skills / Commands / TUI / MCP / Plugin / CLI，2.0 为独立主版本线、1.x 永不被动推到 2.x），以 npm `opencode-ai` 1.19.2 稳定线为基线覆盖 C/S 边界、双主 Agent 与 13 键权限模型、Markdown 扩展面与 Plugin 事件钩子；Pi 则把能力藏进基础操作里（会话树、`@` 引用、Shell 集成），并把 Skill 与 Extension 的分工划得很清。Pi 已拆分为枢纽主文件 + 6 个专题页（Session / Interaction / Context / Extensions / Security / Architecture，原 `LLM/Pi-Architecture.md` 已并入家族目录），以 v1.3.0 + main 为基线覆盖 JSONL 会话树与三分支操作、每命令独立 shell 进程的 Shell 集成、压缩阈值公式与切割点规则、Agent Skills 规范与 Extension 工具 exposure 五态、project trust 决策链与四类隔离环境、11 个 workspace 包的两层协作循环。
- **[DSH](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)** 是**架构哲学最激进的一个**：「一切皆插件」，连驱动 Agent 运转的主循环都只是默认插件实现之一，没有特权内核。已拆分为枢纽主文件 + 7 个子文件（Cordis 微内核、Agent Loop & Session、Context/Memory/Knowledge、Permission & Sandbox、Subprocess Management、Tool Layer、Plugin Development），逐行源码剖析覆盖了 Fiber 状态机、事件分派五模式、进程树收割六类死法等底层机制。
- **[OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)** 走的是另一条路：**本地优先的个人助手网关**，核心是接管 20 多种通讯软件 + 多 agent 路由，不服务于「写代码」这件事。已拆分为枢纽主文件 + 15 个专题页（Gateway / Lifecycle / Clients / Deployment / Runtime / Memory / SubAgent / Process / Channels / Storage / Plugins / Integrations / Media / Security / Observability），源码级覆盖 18789 单端口协议面、worker placement 的 turn claim 权威链、SQLite-only 存储与 context engine 插件化压缩。
- **[Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md)** 是 **Nous Research 开源、MIT 许可的自进化个人 AI agent**：同一套 agent core 跑在 CLI / TUI / 消息网关（约 27 个平台）/ Electron 桌面端，跨会话持续沉淀记忆与 Skill，用 40+ 个 model-provider、在本地硬件或云端 24/7 运行。已拆分为枢纽主文件 + 8 个专题页（Architecture / AgentLoop / Tools / Skills / Memory / Gateway / Evolve / Extensions / Infrastructure），源码级覆盖 facade/siblings 三层骨架、34 段 turn 循环、registry 自发现 28 toolset、curator 自进化 Skill 生命周期与 background review 复盘、FTS5+CJK 会话检索、双消息守卫网关、「插件不碰 core」铁律，以及 fts5_cjk / pm / docker / acp_adapter 差异化基建。与 OpenClaw 同源本地优先个人助手路线，并显式提供 `hermes claw migrate` 一键迁移。
- **[AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)** 是这层里**唯一的通用 Python Agent 框架**（非编程 Agent 产品），阿里巴巴开源，v2.0 起把 Framework 和 Harness 两层合并：单一 `Agent` 类内置 ReAct 循环、七 hook 中间件、五模式权限引擎、结构化上下文压缩与运行时状态注入，往下有 formatter / workspace 沙箱 / RAG / Skill 四套基础设施，再往上附带 FastAPI Agent Service（多租户、频道接入、Hub、调度）。源码级剖析见该文。
- **[AgentScopeJava](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)** 与上面的 AgentScope 是**同族不同语言的两个独立框架**（`agentscope-java` 仓库，Java 21+/Reactor 响应式），不是后者的移植版——Event/Message 模型、Session Log 持久化、沙箱后端选型都是独立设计。它把 Session Log（commits/blobs/inbox 三层结构 + 原子 CAS）做成一等模块，往下扩出 Workspace（文件系统模式 × 沙箱后端 × IsolationScope 三维）、Skill（四层合成 + 市场后端 + 自学习闭环）与 SubAgent（同步/后台/远程三态）。已拆分为枢纽主文件 + 7 个子文件。

一篇横向对照见 [OpenCode 与 Claude Code 的对照表](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md?id=comparison-with-claude-code)，它把客户端架构、模型绑定、规则文件兼容性与扩展方式逐项列出。另有 [cc-haha 的三向对照](/docs/CS/AI/LLM/Agent/Product/CcHaha/Comparison.md)，把 Claude Code / OpenCode / cc-haha 的开源路线、内核形态、权限模型、多 Agent 编排（含 cc-haha 的 Dynamic Workflow 真功能）、Computer Use、MCP/Skill、IM/远控逐项并列。

## Where Practice Is Heading

能完成任务只是及格线，这一层关心的是**这层架构本身怎么继续变化**。

**[Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md)** 问的是：一次会话里的经历，能不能沉淀成下次可用的能力。它把这件事拆成上下文/记忆进化与结构进化两条路径，并配上评测体系（没有评测就没有进化）、Agent CI/CD 与人的校准位置。它也诚实地写了对立面——**闭环存在 ≠ 每次循环都会变好**，并给出「五类不能永久交给 Agent 的决策」。

**[Hermes](/docs/CS/AI/LLM/Agent/Practice/Hermes.md)** 是这条路的完整落地标本：三层记忆、Periodic Nudges 后台复盘、Autonomous Skill Creation 让 Agent 自建 Skill。它同时是理解 Harness 工程的具体实例——三层的每一层都能在其他产品里找到对应物。其工程实现侧的源码级拆解见 [Hermes 产品家族](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md)（主笔记 + 8 个专题页）。

**[Vibe](/docs/CS/AI/LLM/Agent/Practice/Vibe.md)** 记录的是这层工具对开发方式本身的反向影响：从 Karpathy 2025-02 提出的「氛围编程」，到他在 2026-02 亲手判定它 passé 并改推「agentic engineering」，再到 SDD（规范驱动开发）成为严肃工程的答案。它也订正了一个常见误解——原教旨版 vibe coding 是「不读 diff、只适合扔掉级项目」，把这个纪律用到生产系统上才是风险来源；后者（用 AI 写代码然后认真 review）其实是普通的软件开发。讨论「AI 参与写代码之后，人该把注意力放在哪」——答案是方向、判断与品味，以及把它们固定下来的 spec。

## A Sense of Orientation

四组件与 Skill 封装各自对应什么、谁最容易被搞错，一张表收尾：

| 组件 | 是什么 | 最常见的误解 | 详见 |
| :--- | :--- | :--- | :--- |
| **Loop** | 调用模型→执行工具→观察结果的循环 | 以为「调用工具」是模型的能力 | [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) |
| **Tools** | 模型可调用的具体能力 | 以为 Tool 承担「怎么做」 | [Tools](/docs/CS/AI/LLM/Protocol/Tools.md) / [MCP](/docs/CS/AI/LLM/Protocol/MCP.md) |
| **Memory** | 管理每轮 Context 的存读写 | 以为必须用向量数据库 | [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) |
| **Harness** | 基础设施：错误处理、权限、编排 | 以为组件越多越好 | [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) |
| **Skill** | 可复用的方法打包成目录 | 以为是一次性提示词 | [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md) |

两个常被当成第五、第六组件的东西，其实不在四组件里——它们是 Harness 内部的两块专项机制：**上下文压缩**属于「认知」层，**权限与沙箱**属于「行动」层。判断一个 Agent 产品的成熟度，看的也不是「有没有规划功能」，而是**压缩策略、权限粒度、恢复语义**这三项做得对不对。

最后一行是最容易放错位置的：**Skill 不在四组件里，它是 Harness 侧的能力封装机制**——属于「Tools 与 Memory 怎么被组织起来」，而不是第五个组件。

## Links

- [LLM](/docs/CS/AI/LLM/LLM.md)
- [模型总览](/docs/CS/AI/LLM/Model/Overview.md)
- [Paradigm](/docs/CS/AI/LLM/Agent/Theory/Paradigm.md)
- [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md)
- [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)
