## Introduction

`Agent/` 装的是**包裹模型的那层东西**——让只会输出 token 的模型能在真实环境里执行、持久记住、并且会自我纠错。LLM 的四个局限（只会说不会做、没有记忆、知识截止、不会规划）都指向同一个结论：缺的不是更多参数，而是这层架构。

这个目录按**「机制 → 产品 → 演进」**三层组织。这个划分不是按篇幅或时间，而是按**读者要回答的问题**：想搞懂原理看 Theory，想选一个工具干活看 Product，想知道这层架构往哪走看 Practice。

| 目录 | 装什么 | 枢纽 |
| :--- | :--- | :--- |
| [`Theory/`](https://github.com/Robinpig/Note/blob/master/docs/CS/AI/LLM/Agent/Theory/Agent.md) | 机制与概念：Agent 四组件、Harness 工程、权限与沙箱、Skill 规范、上下文压缩 | [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) |
| [`Product/`](https://github.com/Robinpig/Note/blob/master/docs/CS/AI/LLM/Agent/Product/Codex.md) | 具体的 Agent 产品与框架实现 | [Codex 源码剖析](/docs/CS/AI/LLM/Agent/Product/Codex.md) |
| [`Practice/`](https://github.com/Robinpig/Note/blob/master/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md) | 演进方向与开发方式的自变化 | [Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md) |

## How the Five Theory Articles Divide Responsibilities

这几篇的关系是**从抽象到具体**，不是并列：

**Agent** 是总纲。它给出最核心的那个定义——**AI Agent 是一个能调用工具的循环系统**，以及四组件（Loop / Tools / Memory / Harness）。它的 ReAct 循环四步（Reason / Act / Observe / 回环）是所有 Agent 表面不同、底层一致的那层机制。常见的 Agent 模式（ReAct、Plan-and-Execute、Multi-Agent、SubAgent）也在这篇。

**Harness** 是四组件里最容易被误解的一个，也是真正决定成败的一个。它的定义反直觉：**Harness 不是「越多越好」，而是对模型能力缺口的补偿面**。模型每强一分，曾经必需的组件就该抽掉一层——照抄别人的组件清单不会让 Agent 变强，反而可能在长任务里拖后腿。所以那篇值得读的不是「有哪些组件」，而是「现在该补哪一块、该拆哪一块」的判断方法。它还厘清了一个高频混淆：Runtime / Framework / Harness 三层分别解决「能稳定运行」「能方便开发」「能直接完成复杂任务」。

**Permission** 讲 Agent 能不能动、动了要不要问。这篇的核心结论是**沙箱与权限是两层不同的东西**：沙箱管「能不能」（OS 强制，Seatbelt / bubblewrap / Landlock+seccomp），权限管「该不该」（进程判定，deny → ask → allow）。它最反直觉的地方是**默认值差异大到危险**——Claude Code 沙箱默认关闭、OpenCode 权限默认全放行、Cline `--auto-approve` 默认 true，而 Codex 与 DSH 默认保守。另外记录了两个跨产品迁移最容易踩的坑：OpenCode「最后匹配者胜」与 Claude Code「deny 优先」是**相反的优先级模型**；以及本地 Agent 里**防线构建者和绕过者是同一个人**，所以企业管控必须是 managed settings 这类强制层而非默认配置。那篇还逐条核实并修正了本库此前关于 Claude Code 企业策略路径、DSH 插件计数与 `fs-local`、Linux 沙箱主流做法的三处过时结论。

**Skill** 是能力封装的最小单元，解决的是「这段流程说明我在三个项目里各贴了一遍给 AI」。它最反直觉的地方在成本侧：**skill 正文一旦加载就跨轮持续占用上下文**，不是一次性步骤；而且每个 skill 的 description 都会进每轮上下文，装 50 个就是每轮都为 50 条 description 付费。这篇的字段规范部分有几个必踩的坑——`allowed-tools` 写错成下划线**静默失效不报错**、个人 skill 会覆盖项目 skill、Codex 超过上下文 2% 会静默省略部分 skill。

**Compaction** 讲长会话怎么在窗口耗尽前活下来。它最反直觉的地方在**代价结构**上：压缩不是免费的，而是拿「模型对原始上下文的可见性」换「更长的会话时长」——厂商承认能力会下降（Codex 每次压缩后向用户发警告，说长线程与多次压缩会让模型变得不够准确）。这篇的骨架是六件事：阈值怎么定（**几乎全是 token 预算，不是「最近 N 轮」**）、保留什么、摘要由谁生成（**基本都要额外调一次 LLM**）、能否恢复（**原文通常还在盘上，但模型几乎都取不回**）、失败怎么处理、以及和 KV 缓存的交互（**各家在压缩过程中刻意在保缓存**：DSH 把指令放在回放前缀之后以复用热前缀，Claude Code 复用 system prompt 层，Pi 干脆禁掉摘要请求的 cache 写入）。附一张五家对比表与「陷阱」清单——其中「压缩会不会丢 skill 正文」的精确答案在 Claude Code 官方表里：**会重新注入，但每 skill 上限 5K、总计 25K token，超限时最老的先被丢弃**，这比直接消失更隐蔽。

## Product: Six Implementations

编程 Agent 是这一层最成熟的产品形态，几家的差异比想象中大，**不在「谁更强」而在架构选择**：

- **[Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode.md)** 与 **[Codex](/docs/CS/AI/LLM/Agent/Product/Codex.md)** 绑定单一模型厂商（Anthropic / OpenAI），但把各自厂商的 Harness 特性用得最透。Codex 那篇是**源码级剖析**（Rust 实现，从 `start_or_steer` 到 `run_turn` 的主循环、事件汇合、审批的异步实现），想理解「一个 Harness 内部长什么样」看它。
- **[OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode.md)** 与 **[Pi](/docs/CS/AI/LLM/Agent/Product/Pi.md)** 的卖点是**模型无关**——同一套 Agent loop 驱动 Anthropic / OpenAI / 任意 OpenAI 兼容端点。OpenCode 是客户端/服务器架构（内核是本地 HTTP 服务，TUI/Web/IDE 都是客户端，可远程 attach），Pi 则把能力藏进基础操作里（会话树、`@` 引用、Shell 集成），并把 Skill 与 Extension 的分工划得很清。
- **[DSH](/docs/CS/AI/LLM/Agent/Product/DSH.md)** 是**架构哲学最激进的一个**：「一切皆插件」，连驱动 Agent 运转的主循环都只是默认插件实现之一，没有特权内核。它也是本目录里唯一逐行读源码的笔记（793 行，涵盖 Cordis 微内核、七层洋葱模型、子进程管理的 pid 复用边界、PTY）。
- **[OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw.md)** 走的是另一条路：**本地优先的个人助手网关**，核心是接管 20 多种通讯软件 + 多 agent 路由，不服务于「写代码」这件事。

一篇横向对照见 [OpenCode 与 Claude Code 的对照表](/docs/CS/AI/LLM/Agent/Product/OpenCode.md?id=comparison-with-claude-code)，它把客户端架构、模型绑定、规则文件兼容性与扩展方式逐项列出。

## Where Practice Is Heading

能完成任务只是及格线，这一层关心的是**这层架构本身怎么继续变化**。

**[Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md)** 问的是：一次会话里的经历，能不能沉淀成下次可用的能力。它把这件事拆成上下文/记忆进化与结构进化两条路径，并配上评测体系（没有评测就没有进化）、Agent CI/CD 与人的校准位置。它也诚实地写了对立面——**闭环存在 ≠ 每次循环都会变好**，并给出「五类不能永久交给 Agent 的决策」。

**[Hermes](/docs/CS/AI/LLM/Agent/Practice/Hermes.md)** 是这条路的完整落地标本：三层记忆、Periodic Nudges 后台复盘、Autonomous Skill Creation 让 Agent 自建 Skill。它同时是理解 Harness 工程的具体实例——三层的每一层都能在其他产品里找到对应物。

**[Vibe](/docs/CS/AI/LLM/Agent/Practice/Vibe.md)** 记录的是这层工具对开发方式本身的反向影响：从 Karpathy 2025-02 提出的「氛围编程」，到他在 2026-02 亲手判定它 passé 并改推「agentic engineering」，再到 SDD（规范驱动开发）成为严肃工程的答案。它也订正了一个常见误解——原教旨版 vibe coding 是「不读 diff、只适合扔掉级项目」，把这个纪律用到生产系统上才是风险来源；后者（用 AI 写代码然后认真 review）其实是普通的软件开发。讨论「AI 参与写代码之后，人该把注意力放在哪」——答案是方向、判断与品味，以及把它们固定下来的 spec。

## A Sense of Orientation

四个组件各自对应什么、谁最容易被搞错，一张表收尾：

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

- [LLM 总纲](/docs/CS/AI/LLM/LLM.md)
- [模型总览](/docs/CS/AI/LLM/Model/Overview.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md)
- [Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md)