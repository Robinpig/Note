## Introduction

大模型（LLM）狭义上指基于深度学习算法进行训练的自然语言处理（NLP）模型，主要应用于自然语言理解和生成等领域，广义上还包括机器视觉（CV）大模型、多模态大模型和科学计算大模型等。
它是由具有大量参数（通常数十亿个权重或更多）的[人工神经网络](/docs/CS/AI/CNN.md)组成的一类语言模型，使用自监督学习或半监督学习对大量未标记文本进行训练

## LLM 的局限性

- **只会说不会做**——它能告诉你"你可以去天气 App 查一下"，但它自己不会去查
- **没有记忆**——上下文窗口一满就"失忆"，跨会话什么都没留下
- **知识截止**——训练数据有截止日期，昨天发生的事它不知道
- **不会规划**——你让它"做一份竞品分析"，它只会线性回答，不会自己拆解成"先搜集资料、再逐个分析、再对比价格"这样的步骤

驱动真实 LLM 的关键在于提示工程（Prompt Engineering）

## 本库的分类

这个目录按**「模型 → 协议 → Agent → 平台」**四层组织，四层恰好是「一个 LLM 应用从选模型到上线」的真实顺序：

| 目录 | 装什么 | 入口 |
| :--- | :--- | :--- |
| `Model/` | 模型本体与厂商：型号、架构、定价、权重与许可 | [模型总览](/docs/CS/AI/LLM/Model/Overview.md) |
| `Protocol/` | 跨厂商的接入协议：工具调用、MCP、A2A | [Tools](/docs/CS/AI/LLM/Protocol/Tools.md) |
| `Agent/` | 包裹模型的运行框架与编程 Agent，按机制 / 产品 / 演进分三层 | [Agent 目录](/docs/CS/AI/LLM/Agent/README.md) |
| `Platform/` | 可视化把模型组装成服务的现成产品 | [LLM 应用开发平台](/docs/CS/AI/LLM/Platform/Platform.md) |

先说清一件事：**「模型」和「模型上的东西」是这个目录最常见的混淆点**。DeepSeek 有模型也开源了 agent 框架（dsh），Anthropic 有 Claude 模型也有 Claude Code 工具，两者在工程上完全不同——模型是 API 定价的消费者，Agent 是 API 的调用方。所以它们分处 `Model/` 与 `Agent/`，前者关心上下文长度与每百万 token 的价格，后者关心 loop、工具与记忆。

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

前面列的四个局限，其实指向同一件事——**LLM 缺的不是更多参数，而是一个能在真实环境里执行、持久记住、并且会自我纠错的包裹层**。这个包裹层就是 Agent，它的四构成（Loop / Tools / Memory / Harness）在 [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) 里有完整拆解。这一层内部按**机制 / 产品 / 演进**再分三层，入口是 [Agent 目录](/docs/CS/AI/LLM/Agent/README.md)。

其中真正决定成败的是 Harness，而它最反直觉的一点写在 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 里：**Harness 是对模型能力缺口的补偿面**。模型每强一分，曾经必需的组件就该抽掉一层；照抄别人的组件清单并不会让你的 Agent 变强，反而可能在长任务里拖后腿。所以那篇笔记值得读的不是"有哪些组件"，而是"现在该补哪一块、该拆哪一块"的判断方法。

工具这一环单独拎出来，因为这里最容易搞错归属：很多人以为「调用工具」是模型的能力，实际上模型只负责输出结构化的调用意图，真正执行动作、把结果回灌上下文的是外层框架——这一层的梳理见 [Tools](/docs/CS/AI/LLM/Protocol/Tools.md)。而工具如何做到"一次实现、处处接入"，目前的事实标准是 [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)（常被比作 AI 应用的 USB-C）。再往前一步，当协作发生在多个 Agent 之间而不是 Agent 与工具之间时，缺的是另一层协议，那便是与 MCP 互补的 [A2A](/docs/CS/AI/LLM/Protocol/A2A.md)。

一句话串起来：**模型负责决策，Harness 负责执行，MCP 解决工具和 N 个 Agent 的对接成本，A2A 解决 Agent 之间的对话成本。**

## 选模型 这件事本身

模型能力的问题最终会落成成本问题，而 2026 年的定价结构让这件事比想象复杂：同档位模型的输入价格正在收敛，但缓存倍率、长上下文是否加价、thinking token 按什么计价，这三项的差距远大于标价差距。比如同样把一个 900K token 的代码库一次性喂进去，按标价算一遍和按某家的无台阶结构算一遍，账单可以差三倍以上。

[模型总览](/docs/CS/AI/LLM/Model/Overview.md) 是这块的枢纽，横向汇总了闭源三家与中国模型的价格、上下文与协议，并单列了最容易记错的几处（比如「Llama 4 非商用」是误传、国产旗舰的协议正在集体收紧、OpenAI 的 272K 是整单重算的台阶而非斜坡）。各家的完整型号表与架构演进在专页：[DeepSeek](/docs/CS/AI/LLM/Model/DeepSeek.md) 的峰谷分时定价与 encoder–decoder MoE、[OpenAI](/docs/CS/AI/LLM/Model/OpenAI.md) 的 GPT-6 家族与长上下文台阶、[Claude](/docs/CS/AI/LLM/Model/Claude.md) 的四档命名与自适应 thinking、[Qwen](/docs/CS/AI/LLM/Model/Qwen.md) 与[开源模型全景](/docs/CS/AI/LLM/Model/Open_Model.md) 的协议陷阱。当负载稳定到一定程度，云端按 token 计费就该换成自建——这条路见[本地部署与推理引擎](/docs/CS/AI/LLM/Model/Inference.md)。

## 让它越用越顺手

能完成任务只是及格线。[Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md) 关心的是另一件事：一次会话里的经历，能不能沉淀成下次可用的能力。它把这件事拆成上下文/记忆进化与结构进化两条路径，并配套了评测、CI/CD 和人在其中的位置。想知道这条路真跑起来长什么样，[Hermes](/docs/CS/AI/LLM/Agent/Practice/Hermes.md) 是个完整落地标本——三层记忆、定时唤醒、Skill 自创建都在里面。

## 不想自己攒 Harness：平台这条线

如果你不想从零搭这套东西，另一条路是用现成的平台（可视化画布 + 内置 RAG + 现成运维）。这笔账的本质是**用可控性和迁移成本换开发速度**：画布是厂商的产品表面，风向一变最先被砍的往往就是它，真正能沉淀的是 SDK、协议和数据模型。选型时先问数据能不能出内网，候选名单会立刻缩短——[LLM 应用开发平台](/docs/CS/AI/LLM/Platform/Platform.md) 是这块的枢纽，把玩家分成五类并划了边界。

几个常被放在一起比的产品，差异其实比想象中大：[Coze](/docs/CS/AI/LLM/Platform/Coze.md) 的独特点是"开发 + 评测观测"原生一体（Studio 搭 agent、Loop 调效果）；[Dify](/docs/CS/AI/LLM/Platform/Dify.md) 强在 RAG 管线可调得深、插件生态成熟；[HiAgent](/docs/CS/AI/LLM/Platform/HiAgent.md) 是火山引擎面向企业私有化的那条线，核心命题是组织里的多个 Agent 如何协同分工。反过来，如果主要诉求是吃透复杂文档（表格、扫描件、带版式的 PDF），要看的不是通用平台，而是偏科生 [RAGFlow](/docs/CS/AI/LLM/Platform/RAGFlow.md)。

画布和代码也不必二选一：[Langflow](/docs/CS/Framework/LangTool/Langflow.md) 允许一边可视化编排一边改组件源码、导出成 Python；而团队本就 Python 为主、希望类型系统直接约束 LLM 输出时，[Pydantic AI](/docs/CS/Framework/PydanticAI.md) 是从第一天就按生产标准设计的那一派。

## Links

- [模型总览](/docs/CS/AI/LLM/Model/Overview.md)
- [Agent 目录](/docs/CS/AI/LLM/Agent/README.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md)
- [AI](/docs/CS/AI/AI.md)
- [NLP](/docs/CS/AI/NLP/NLP.md)
