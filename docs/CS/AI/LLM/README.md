## Introduction

`LLM/` 下面有四层，按**「一个 LLM 应用从选模型到上线」的真实顺序**组织。这一页是 `LLM/` 的入口，模型层的细节从 [模型总览](/docs/CS/AI/LLM/Model/Overview.md) 进。

| 目录 | 装什么 | 枢纽 |
| :--- | :--- | :--- |
| [`Model/`](https://github.com/Robinpig/Note/blob/master/docs/CS/AI/LLM/Model/Overview.md) | 模型本体与厂商：型号、架构、定价、权重与许可 | [模型总览](/docs/CS/AI/LLM/Model/Overview.md) |
| [`Protocol/`](https://github.com/Robinpig/Note/blob/master/docs/CS/AI/LLM/Protocol/Tools.md) | 跨厂商接入协议：工具调用、MCP、A2A | [Tools](/docs/CS/AI/LLM/Protocol/Tools.md) |
| [`Agent/`](https://github.com/Robinpig/Note/blob/master/docs/CS/AI/LLM/Agent/README.md) | 包裹模型的运行框架与编程 Agent，按机制 / 产品 / 演进分三层 | [Agent 目录](/docs/CS/AI/LLM/Agent/README.md) |
| [`Platform/`](https://github.com/Robinpig/Note/blob/master/docs/CS/AI/LLM/Platform/Platform.md) | 可视化把模型组装成服务的现成产品 | [LLM 应用开发平台](/docs/CS/AI/LLM/Platform/Platform.md) |

先说清这个目录最常见的混淆点：**「模型」和「模型上的东西」不是一回事**。DeepSeek 有模型，也开源了 agent 框架（dsh）；Anthropic 有 Claude 模型，也有 Claude Code 工具。两者在工程上完全不同——模型是 API 定价的消费者，Agent 是 API 的调用方。所以它们分处 `Model/` 与 `Agent/`，前者关心上下文长度与每百万 token 的价格，后者关心 loop、工具与记忆。搞混这一点，选型时会拿完全不同的指标去比。

## 模型

2026 年 10 月的市场有一个反复出现的现象：同档位模型的**输入价格正在收敛，但缓存倍率、长上下文是否加价、thinking token 按什么计价**这三项的差距远大于标价差距。三个月前还能靠标价分辨厂商，现在不行了。

[模型总览](/docs/CS/AI/LLM/Model/Overview.md) 是这块的枢纽，横向汇总了闭源三家与中国模型的价格、上下文与协议，并单列了几处最常见的误传。各家专页：[DeepSeek](/docs/CS/AI/LLM/Model/DeepSeek.md)（峰谷分时定价与 encoder–decoder MoE）、[OpenAI](/docs/CS/AI/LLM/Model/OpenAI.md)（GPT-6 家族与 272K 长上下文台阶）、[Claude](/docs/CS/AI/LLM/Model/Claude.md)（四档命名与无法关闭的 thinking）、[Qwen](/docs/CS/AI/LLM/Model/Qwen.md) 与[开源模型全景](/docs/CS/AI/LLM/Model/Open_Model.md)（协议陷阱）。负载稳定到一定程度就该自建，[本地部署与推理引擎](/docs/CS/AI/LLM/Model/Inference.md) 讲这条路。

## 协议

模型只会输出 token，是**工具调用**让它从「会说」变成「能做」——而工具如何做到「一次实现、处处接入」，目前的事实标准是 MCP（常被比作 AI 应用的 USB-C）。再往前一步，当协作发生在多个 Agent 之间而不是 Agent 与工具之间时，缺的是另一层协议，那便是与 MCP 互补的 A2A。

这三篇的关系是分层的：[Tools](/docs/CS/AI/LLM/Protocol/Tools.md) 讲工具生态的三个层次（函数调用能力本身、工具接入协议、面向 AI 编程的现成工具集），[MCP](/docs/CS/AI/LLM/Protocol/MCP.md) 讲客户端—服务器架构与 host/client/server 的分工，[A2A](/docs/CS/AI/LLM/Protocol/A2A.md) 讲 agent 间通信。归属上最容易被误解的一点：**「调用工具」不是模型的能力**，模型只输出结构化的调用意图，真正执行动作、把结果回灌上下文的是外层框架。

## Agent

LLM 的四个局限——只会说不会做、没有记忆、知识截止、不会规划——其实指向同一件事：**它缺的不是更多参数，而是一个能在真实环境里执行、持久记住、并且会自我纠错的包裹层**。这个包裹层就是 Agent，其四构成（Loop / Tools / Memory / Harness）在 [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) 里有完整拆解。

这一层内部又按**机制 / 产品 / 演进**分三层，入口是 [Agent 目录](/docs/CS/AI/LLM/Agent/README.md)。其中真正决定成败的是 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)，而它最反直觉的一点是：**Harness 是对模型能力缺口的补偿面**。模型每强一分，曾经必需的组件就该抽掉一层；照抄别人的组件清单不会让 Agent 变强，反而可能在长任务里拖后腿。所以那篇值得读的不是「有哪些组件」，而是「现在该补哪一块、该拆哪一块」的判断方法。另一个高频踩坑点是 [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md)——它的字段规范有「拼错不报错」的坑，而正文一旦加载就跨轮持续占用上下文，不是你以为的一次性提示词。

编程 Agent 是这一层最成熟的产品形态，几个常被放在一起比：[Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode.md) 与 [Codex](/docs/CS/AI/LLM/Agent/Product/Codex.md) 绑定单一厂商但把 Harness 特性用得最透，后者是源码级剖析；[OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode.md) 与 [Pi](/docs/CS/AI/LLM/Agent/Product/Pi.md) 的卖点是模型无关，差异在客户端架构与扩展方式；[DeepSeek Harness](/docs/CS/AI/LLM/Agent/Product/DSH.md) 展示「一切皆插件」的另一种解法。能完成任务只是及格线，[Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md) 关心的是经历能否沉淀成下次可用的能力，[Hermes](/docs/CS/AI/LLM/Agent/Practice/Hermes.md) 是个完整落地标本，而 [Vibe](/docs/CS/AI/LLM/Agent/Practice/Vibe.md) 记录的是这套工具对开发方式本身的影响。

## 平台

不想从零搭 Harness，另一条路是用现成平台（可视化画布 + 内置 RAG + 现成运维）。这笔账的本质是**用可控性和迁移成本换开发速度**：画布是厂商的产品表面，风向一变最先被砍的往往就是它，真正能沉淀的是 SDK、协议和数据模型。选型时先问数据能不能出内网，候选名单会立刻缩短。

[LLM 应用开发平台](/docs/CS/AI/LLM/Platform/Platform.md) 把玩家分成五类并划了边界。常被放在一起比的几个差异其实比想象中大：[Coze](/docs/CS/AI/LLM/Platform/Coze.md) 的独特点是「开发 + 评测观测」原生一体，[Dify](/docs/CS/AI/LLM/Platform/Dify.md) 强在 RAG 管线可调得深、插件生态成熟，[HiAgent](/docs/CS/AI/LLM/Platform/HiAgent.md) 是火山引擎面向企业私有化的那条线。如果主要诉求是吃透复杂文档，要看的不是通用平台，而是偏科生 [RAGFlow](/docs/CS/AI/LLM/Platform/RAGFlow.md)。

## Links

- [AI](/docs/CS/AI/AI.md)
- [Transformer](/docs/CS/AI/Transformer.md)
- [NLP](/docs/CS/AI/NLP/NLP.md)
- [RAG](/docs/CS/AI/RAG.md)