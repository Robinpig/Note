## Introduction

**A2A（Agent2Agent）是一个开放的 agent 间通信协议**，由 Google 发起、2025 年捐赠给 Linux Foundation，由 AWS、Cisco、Google、IBM、Microsoft、Salesforce、SAP、ServiceNow 等组成的技术指导委员会维护，Apache 2.0 许可。

要解决的问题：Agent 由不同框架（LangGraph、CrewAI、Semantic Kernel、自研……）和不同厂商构建，彼此是**互不相通的孤岛**。A2A 为这些 agent 提供统一的语言，让它们能够**互相发现、委派任务、交换结果**。

核心设计哲学：**不透明协作（opaque collaboration）**。一个 agent 与远程 agent 协作时，把对方当黑盒——只依赖对方声明的 capabilities 和交换的信息，不需要也不允许访问对方的内部记忆、工具或私有逻辑。既保住了安全边界，也保住了各家的知识产权。

四大特性：

| 特性 | 说明 |
| --- | --- |
| Interoperability | 跨平台/框架的 agent 互联，组合成复合 AI 系统 |
| Complex Workflows | 子任务委派、信息交换、动作协调，解决单 agent 无法完成的复杂问题 |
| Secure & Opaque | 不共享内部记忆/工具/逻辑，安全且保护知识产权 |
| Extensible | 通过正式的协议扩展与自定义绑定增加能力，核心保持稳定 |

## Relationship with MCP

A2A 与 MCP **不是竞争而是互补**，解决两个不同的问题：

| | MCP | A2A |
| --- | --- | --- |
| 标准化对象 | agent ↔ 工具/资源 | agent ↔ agent |
| 解决的问题 | agent 如何连接它的工具、API、数据源 | 独立 agent 之间如何发现、委派、协作 |
| 对端是谁 | 工具（无状态的功能调用） | 另一个 agent（有状态、有自主性的黑盒） |
| 典型场景 | 给 agent 接 GitHub 仓库、SQL 数据库 | 让"代码审查 agent"与"测试 agent"协作 |

典型组合：**用 MCP 装备单个 agent 的工具能力，用 A2A 让这些专业 agent 跨框架安全协作**。一个 agent 可以同时是 MCP Client（用工具）和 A2A Client/Server（与 agent 协作）。

A2A 明确"不是"什么：

- **不是 agent 开发框架**（那是 LangGraph/CrewAI/ADK 的事），它是构建在任何框架之上的通信层
- **不是 sub-agent/工具调用协议**——agent 调自己的子 agent 或工具，用框架原生原语或 MCP
- **不是 MCP 的替代品**
- **不是聊天应用**（Slack/Discord 那种），是面向自主 agent 的机器对机器协议

## Core Concepts

### Three Types of Roles

| 角色 | 说明 |
| --- | --- |
| User | 最终用户（人或自动化服务），发起请求/目标 |
| A2A Client（Client Agent） | 代表用户发起通信的一方：应用、服务或另一个 agent |
| A2A Server（Remote Agent） | 暴露 HTTP 端点、实现 A2A 协议的 agent；对 client 是**黑盒** |

### Six Communication Elements

| 元素 | 作用 |
| --- | --- |
| **Agent Card** | JSON 元数据文档（"数字名片"），通常发布在 `/.well-known/agent-card.json`，描述身份、服务端点、支持的 A2A capabilities（streaming/push 等）、技能列表、输入输出模态、认证要求——client 靠它做**能力发现** |
| **Task** | 有状态的工作单元，由 agent 定义唯一 ID，有完整生命周期；支撑长任务跟踪与多轮交互 |
| **Message** | client 与 agent 之间的一次通信轮次，带角色（`user`/`agent`）和 `messageId`；承载指令、上下文、状态更新等非正式产出的内容 |
| **Part** | Message/Artifact 内的原子内容单元（oneof）：`text` 文本 / `raw` 内联字节 / `url` 文件引用 / `data` 结构化 JSON；可附 `mediaType`、`filename`、`metadata`——这个设计让 A2A **模态无关** |
| **Artifact** | agent 在任务中产出的"实体交付物"（文档、图片、结构化数据），有 `artifactId`，由一到多个 Part 组成，可增量流式传输；completed 状态的任务应当用 Artifact 返回结果 |
| **Extension** | 超出核心规范的扩展能力声明机制 |

Agent 响应请求时：能立即回答 → 返回 **Message**；需要执行长任务 → 创建 **Task**。

## Task Lifecycle

Task 是 A2A 的核心抽象——**协作被建模为有状态的工作单元**，状态迁移可观测：

```
submitted → working → input-required → completed / failed / cancelled
```

- `input-required` 是关键状态：任务中途可以暂停等用户/客户端补充输入，天然支持 **human-in-the-loop**
- 长任务运行中，client 通过 `tasks/get` 轮询，或用流式/推送获取更新
- 任务可以跨越多次消息交换（multi-turn），支持异步、多步骤工作流

## Communication Mechanism

三种交互模式，按任务时长与实时性需求选择：

| 机制 | 方式 | 适用场景 |
| --- | --- | --- |
| Request/Response（Polling） | `message/send` 提交，`tasks/get` 周期轮询 | 短任务或简单集成 |
| Streaming（SSE） | `message/stream` 建立长连接，服务端持续推 Task/Message/状态变更/Artifact 增量事件 | 需要实时进度与增量结果 |
| Push Notifications | client 提供 webhook URL，服务端在状态显著变化时主动 POST 通知 | 超长任务、无法维持长连接的场景 |

## Architecture Layering

规范分三层：

1. **Canonical Data Model（规范数据模型）**：所有实现必须理解的核心数据结构，以 Protocol Buffer 表达——Task、Message、Agent Card、Part、Artifact、Extension
2. **Abstract Operations（抽象操作）**：所有 A2A agent 必须支持的基本能力——Send Message、Stream Message（SSE）、Get/List/Cancel Task、Get Agent Card
3. **Protocol Bindings（协议绑定）**：操作到具体协议的映射——主绑定 **JSON-RPC 2.0 over HTTP**；另有 **gRPC**（二进制序列化、高性能流式）和 **HTTP/REST**；可扩展自定义绑定

## Ecosystem and Current Status

- **官方 SDK**：Python / JavaScript / Java / C#(.NET) / Go / Rust（[a2aproject](https://github.com/a2aproject)）
- **采用情况**（v1.0 GA 一年）：150+ 组织采用；Azure AI Foundry、AWS Bedrock AgentCore、Copilot Studio、Salesforce、SAP、ServiceNow 等企业平台一级集成；LangGraph、CrewAI 内置 A2A 兼容层
- **标准整合**：IBM 的 ACP（Agent Communication Protocol）于 2025-08 并入 A2A 规范
- **与 Agent 身份的关系**：Agent Card 是协议层的"能力身份"声明（能做什么），但不构成完整的 Agent Identity——不建立跨会话的行为身份、声誉或信任历史

## Links

- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md) — agent ↔ 工具的标准协议，与 A2A 互补
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) / [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [DSH](/docs/CS/AI/LLM/Agent/Product/DSH.md) / [Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md)

## References

- [A2A Protocol 官网](https://a2a-protocol.org/latest/)
- [Key Concepts](https://a2a-protocol.org/latest/topics/key-concepts/)
- [Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [A2A and MCP](https://a2a-protocol.org/latest/topics/a2a-and-mcp/)
- [a2aproject/A2A](https://github.com/a2aproject/A2A)
- [Agent2Agent (A2A) Protocol](https://agentica.wiki/articles/agent2agent-a2a-protocol)
