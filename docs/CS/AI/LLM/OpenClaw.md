## Introduction

**OpenClaw** 并不是传统意义上像 LangChain 或 AutoGen 那样侧重于“复杂任务拆解与多智能体协作”的底层算法框架，而是一个**极其强大、本地优先（Local-first）的个人 AI 助手网关与运行平台**。它的核心目标是打造一个运行在你自己设备上的“全能数字管家”，能够接管你所有的通讯渠道，并具备强大的本地工具执行能力

OpenClaw 的架构可以概括为：**“网关驱动（Gateway-driven） + 本地优先（Local-first） + 多智能体路由（Multi-agent Routing）”**。

它的核心哲学是：**Gateway（网关）只是控制平面，真正的产品是那个无处不在的助手。** 它不依赖于云端 SaaS，而是将 AI 的能力通过统一的控制平面，分发到你日常使用的所有 20 多种通讯软件中



OpenClaw 的架构可以清晰地划分为以下五个核心层：

#### 1. 渠道接入层 (Channel Adapters Layer)

这是 OpenClaw 最直观的“触角”，采用了经典的**适配器模式（Adapter Pattern）**。

- **功能**：将极其碎片化的通讯协议统一抽象为标准化的内部消息格式。
- **覆盖面**：支持高达 20+ 种主流 IM，包括 WhatsApp、Telegram、Slack、Discord、Signal、iMessage、微信（WeChat）、QQ、飞书（Feishu）、Matrix 等。
- **架构意义**：实现了“一次接入，全渠道响应”。无论用户从哪个 App 发消息，Gateway 都能无缝接收并路由。

#### 2. 网关与控制平面 (Gateway & Control Plane)

这是 OpenClaw 的**核心枢纽（大脑）**，完全由 TypeScript/Node.js 构建。

- **会话与状态管理**：维护所有渠道的长连接、消息队列和会话上下文。
- **多智能体路由 (Multi-agent Routing)**：这是其架构的灵魂。它不是把所有消息扔给同一个大模型，而是**根据消息来源（渠道、账户、特定联系人或群组），将消息路由到不同的、相互隔离的 Agent（工作区）**。
- **事件总线**：处理工具调用结果、系统事件和异步任务。

#### 3. 智能体运行层 (Agent Runtime & Workspace)

在 Gateway 之下，是具体的 Agent 运行环境。

- **Workspace 隔离**：每个被路由到的 Agent 拥有独立的工作区（Workspace）和独立的会话状态（Per-agent sessions）。这意味着你的“工作助手 Agent”和“家庭助手 Agent”不仅人设不同，其记忆、文件和上下文也是完全物理/逻辑隔离的。
- **本地上下文**：Agent 可以读取本地文件系统，实现真正的“个人助理”功能（如整理本地笔记、管理本地代码等）。

#### 4. 工具与沙箱执行层 (Tool & Sandbox Execution)

这是 OpenClaw 在**安全性与能力**之间取得平衡的关键架构设计。它提供了一个极其精细的安全模型：

- **Main Session（主会话/单用户模式）**：默认情况下，如果是你本人直接与 Agent 交互（Main session），工具（如执行 Shell 命令、读写文件）**直接在宿主机（Host）上运行**。这赋予了 Agent 最高的本地控制权限，实现“极致的本地体验”。
- **Non-main Session（非主会话/多用户/群聊模式）**：当 Agent 在群聊中，或者处理来自不可信联系人的消息时，架构会自动切换安全策略。通过配置 `sandbox.mode: "non-main"`，Agent 的工具执行会被强制放入**沙箱**中。
- **沙箱后端支持**：默认使用 **Docker** 进行容器级隔离，同时也支持 **SSH** 和 **OpenShell** 后端，确保即使 Agent 被恶意 Prompt 注入，也无法破坏宿主机。

#### 5. 交互与客户端层 (Client & UI Layer)

除了 IM 渠道，OpenClaw 还提供了原生的富交互客户端。

- **跨平台原生应用**：使用 **Swift (macOS/iOS)** 和 **Kotlin (Android)** 开发，保证了在移动端的语音交互（Speak and Listen）体验极其流畅和低延迟。
- **Live Canvas**：支持在客户端渲染动态的、可控的 Canvas（画布），用于展示复杂的 UI、图表或交互式内容，突破了纯文本聊天的限制。



