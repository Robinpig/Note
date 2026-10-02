## Introduction

大模型（LLM）狭义上指基于深度学习算法进行训练的自然语言处理（NLP）模型，主要应用于自然语言理解和生成等领域，广义上还包括机器视觉（CV）大模型、多模态大模型和科学计算大模型等。
它是由具有大量参数（通常数十亿个权重或更多）的[人工神经网络](/docs/CS/AI/CNN.md)组成的一类语言模型，使用自监督学习或半监督学习对大量未标记文本进行训练

## LLM 的局限性

- **只会说不会做**——它能告诉你"你可以去天气 App 查一下"，但它自己不会去查
- **没有记忆**——上下文窗口一满就"失忆"，跨会话什么都没留下
- **知识截止**——训练数据有截止日期，昨天发生的事它不知道
- **不会规划**——你让它"做一份竞品分析"，它只会线性回答，不会自己拆解成"先搜集资料、再逐个分析、再对比价格"这样的步骤

驱动真实 LLM 的关键在于提示工程（Prompt Engineering）

## 模型基础

LLM 在结构上就是"把 [Transformer](/docs/CS/AI/Transformer.md) 的 decoder-only 变体堆到很大，再用海量语料做自监督预训练"。因此许多看起来像产品问题的现象，根因都在架构里（详见 [Transformer](/docs/CS/AI/Transformer.md)）：

| LLM 侧的现象/术语 | Transformer 侧的根因 |
| ---------------- | ------------------- |
| 上下文窗口有限、超长文本昂贵 | self-attention 时间/空间复杂度为 O(n²) |
| KV cache 吃显存、并发上不去 | 自回归 decode 需缓存历史 K/V，显存 ∝ 层数 × kv 头数 × d_head × 长度 |
| 首字延迟（TTFT） vs 生成速度 | prefill 算力密集、decode 带宽密集两个阶段 |
| 幻觉 | 建模目标是 token 分布而非事实，靠 [RAG](/docs/CS/AI/RAG.md) 从外部补事实 |
| 位置信息、长文本外推 | 位置编码：RoPE / ALiBi 及其插值扩展 |

## 从"会说"到"能做"：补上模型的四个缺口

前面列的四个局限，其实指向同一件事——**LLM 缺的不是更多参数，而是一个能在真实环境里执行、持久记住、并且会自我纠错的包裹层**。这个包裹层就是 Agent，它的四构成（Loop / Tools / Memory / Harness）在 [Agent](/docs/CS/AI/LLM/Agent.md) 里有完整拆解。

其中真正决定成败的是 Harness，而它最反直觉的一点写在 [Harness](/docs/CS/AI/LLM/Harness.md) 里：**Harness 是对模型能力缺口的补偿面**。模型每强一分，曾经必需的组件就该抽掉一层；照抄别人的组件清单并不会让你的 Agent 变强，反而可能在长任务里拖后腿。所以那篇笔记值得读的不是"有哪些组件"，而是"现在该补哪一块、该拆哪一块"的判断方法。

工具这一环单独拎出来，因为这里最容易搞错归属：很多人以为「调用工具」是模型的能力，实际上模型只负责输出结构化的调用意图，真正执行动作、把结果回灌上下文的是外层框架——这一层的梳理见 [Tools](/docs/CS/AI/LLM/Tools.md)。而工具如何做到"一次实现、处处接入"，目前的事实标准是 [MCP](/docs/CS/AI/LLM/MCP.md)（常被比作 AI 应用的 USB-C）。再往前一步，当协作发生在多个 Agent 之间而不是 Agent 与工具之间时，缺的是另一层协议，那便是与 MCP 互补的 [A2A](/docs/CS/AI/LLM/A2A.md)。

一句话串起来：**模型负责决策，Harness 负责执行，MCP 解决工具和 N 个 Agent 的对接成本，A2A 解决 Agent 之间的对话成本。**

## 让它越用越顺手

能完成任务只是及格线。[Self-Evolving](/docs/CS/AI/LLM/Self-Evolving.md) 关心的是另一件事：一次会话里的经历，能不能沉淀成下次可用的能力。它把这件事拆成上下文/记忆进化与结构进化两条路径，并配套了评测、CI/CD 和人在其中的位置。想知道这条路真跑起来长什么样，[Hermes](/docs/CS/AI/LLM/Hermes.md) 是个完整落地标本——三层记忆、定时唤醒、Skill 自创建都在里面。

## 不想自己攒 Harness：平台这条线

如果你不想从零搭这套东西，另一条路是用现成的平台（可视化画布 + 内置 RAG + 现成运维）。这笔账的本质是**用可控性和迁移成本换开发速度**：画布是厂商的产品表面，风向一变最先被砍的往往就是它，真正能沉淀的是 SDK、协议和数据模型。选型时先问数据能不能出内网，候选名单会立刻缩短——[LLM 应用开发平台](/docs/CS/AI/LLM/Platform.md) 是这块的枢纽，把玩家分成五类并划了边界。

几个常被放在一起比的产品，差异其实比想象中大：[Coze](/docs/CS/AI/LLM/Coze.md) 的独特点是"开发 + 评测观测"原生一体（Studio 搭 agent、Loop 调效果）；[Dify](/docs/CS/AI/LLM/Dify.md) 强在 RAG 管线可调得深、插件生态成熟；[HiAgent](/docs/CS/AI/LLM/HiAgent.md) 是火山引擎面向企业私有化的那条线，核心命题是组织里的多个 Agent 如何协同分工。反过来，如果主要诉求是吃透复杂文档（表格、扫描件、带版式的 PDF），要看的不是通用平台，而是偏科生 [RAGFlow](/docs/CS/AI/LLM/RAGFlow.md)。

画布和代码也不必二选一：[Langflow](/docs/CS/AI/LLM/LangTool/Langflow.md) 允许一边可视化编排一边改组件源码、导出成 Python；而团队本就 Python 为主、希望类型系统直接约束 LLM 输出时，[Pydantic AI](/docs/CS/AI/LLM/PydanticAI.md) 是从第一天就按生产标准设计的那一派。

以上都是"用别人的平台"。另一条路是自己攒：[LangChain](/docs/CS/AI/LLM/LangTool/LangChain.md) 给出模型与工具的跨厂商抽象，[LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md) 在它下面给出有状态图运行时——循环重试、断点恢复、人工审批闸门都落在这一层。这条代码框架线与平台线各自适合谁、同层还有哪些玩家，[LLM 应用开发框架](/docs/CS/AI/LangTools.md) 画了一张横向地图。

## Links

- [AI](/docs/CS/AI/AI.md)
- [NLP](/docs/CS/AI/NLP/NLP.md)
