## Introduction

**OpenClaw** 并不是传统意义上像 LangChain 或 AutoGen 那样侧重于“复杂任务拆解与多智能体协作”的底层算法框架，而是一个**极其强大、本地优先（Local-first）的个人 AI 助手网关与运行平台**。它的核心目标是打造一个运行在你自己设备上的“全能数字管家”，能够接管你所有的通讯渠道，并具备强大的本地工具执行能力

OpenClaw 的架构可以概括为：**“网关驱动（Gateway-driven） + 本地优先（Local-first） + 多智能体路由（Multi-agent Routing）”**。

它的核心哲学是：**Gateway（网关）只是控制平面，真正的产品是那个无处不在的助手。** 它不依赖于云端 SaaS，而是将 AI 的能力通过统一的控制平面，分发到你日常使用的所有 20 多种通讯软件中

## Architecture

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



## Memory

OpenClaw 的所有核心记忆都以纯文本 Markdown 文件的形式存储在用户的本地文件系统中（通常位于 ~/.openclaw/workspace/memory/ 目录下）


OpenClaw 的内置记忆系统模仿了人类的海马体-新皮层记忆巩固机制，分为短期和长期两层
GitHub
：
短期/每日记忆（Daily Logs）：系统会自动创建 memory/YYYY-MM-DD.md 文件，作为每日的追加日志（append-only）
博客园
。在每次会话（Session）启动时，系统会自动加载“今天”和“昨天”的日志，为 AI 提供最新的短期上下文
en.1991421.cn
。
长期/核心记忆（Curated Memory）：MEMORY.md 文件用于存储经过提炼的长期记忆
GitHub
。这里存放着用户的核心偏好、重要事实、长期项目状态等需要永久记住的信息。
记忆巩固（Consolidation）：系统会通过特定的机制（如 Memory Hook 或子代理），定期审查每日的短期日志，并将其中重要的信息提取、总结并写入到 MEMORY.md 中，完成从短期到长期的“记忆巩固”
GitHub
。




虽然源文件是 Markdown，但为了实现高效的检索，OpenClaw 在底层实现了向量化和索引机制：
本地 SQLite 向量库：OpenClaw 会将 MEMORY.md 和 memory/*.md 等文件切分成块（例如约 400 个 Token，80 个 Token 的重叠），生成向量嵌入，并存储在本地每个 Agent 专属的 SQLite 数据库中（如 ~/.openclaw/memory/.sqlite）[[8], [10]]。
Active Memory（主动记忆）：这是一个可选的、由插件拥有的阻塞型记忆子代理（sub-agent）
docs.openclaw.ai
。它会在 AI 生成主要回复之前运行，根据当前对话自动在向量库中搜索相关记忆，并将其注入到上下文中。
Memory Hooks（记忆钩子）：系统通过会话记忆钩子（session-memory hook）监听对话事件（如会话结束或特定触发词），自动将上下文刷新并持久化到记忆文件中
lucaberton.com
。

### Multi-Slot Memory

OpenClaw 的内置 Markdown 系统虽然优秀，但在处理超大规模上下文或复杂知识图谱时可能存在瓶颈。为此，OpenClaw 设计了多插槽记忆架构（Multi-Slot Memory Architecture）
GitHub
。
这意味着 OpenClaw 支持插件化替换，用户可以完全替换默认的记忆提供者，接入更高级的第三方方案
GitHub
。
社区生态与高级插件：
QMD (Query-Memory-Database)：一种混合检索引擎，能大幅提升记忆召回率[[14], [16]]。
Mem0 / MemSearch：第三方记忆插件，提供跨会话的持久化记忆、多层级架构或知识图谱支持[[2], [9], [17]]。
Obsidian 集成：用户可以直接将 Obsidian 笔记库作为外部大脑接入 OpenClaw
GitHub
。
分层记忆（Hierarchical Memory）：用轻量级索引+下钻详情文件来替代扁平的 MEMORY.md，以解决记忆文件过大导致的 Token 消耗问题[[6], [11]]。
总结


## SubAgent



在 OpenClaw 的架构中，主 Agent 和子代理之间存在着明确的层级关系和通信机制：

创建关系：主 Agent 通过 sessions_spawn 工具创建子代理，可以指定子代理的任务描述、使用的模型、超时时间等参数。

通信机制：子代理执行完成后，结果会自动推送给主 Agent。主 Agent 无需轮询检查子代理状态，这种推送机制减少了不必要的资源消耗。

状态管理：主 Agent 可以通过 subagents 工具查看当前活跃的子代理列表，也可以在必要时终止或引导子代理的行为。

资源继承：子代理可以继承主 Agent 的部分资源和权限，如文件系统访问、网络访问等，但也可以被限制在特定的权限范围内。

sessions_spawn 工具详解

sessions_spawn 是 OpenClaw 框架中用于创建子代理的核心工具。通过这个工具，主 Agent 可以动态创建新的子代理实例，并为其分配特定的任务。sessions_spawn 的设计遵循"简单易用、灵活可控"的原则，提供了丰富的参数配置选项。








## Links







## References

1. [深入理解OpenClaw技术架构与实现原理（上）-阿里云开发者社区](https://developer.aliyun.com/article/1717849)
1. [深入理解OpenClaw技术架构与实现原理（下）-阿里云开发者社区](https://developer.aliyun.com/article/1719929)
