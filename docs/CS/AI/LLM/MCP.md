## Introduction

MCP（模型上下文协议）是一个开源标准，用于将人工智能应用与外部系统连接起来。通过MCP，像Claude或ChatGPT这样的AI应用可以连接数据源（如本地文件、数据库）、工具（如搜索引擎、计算器）和工作流程（如专门提示）——使它们能够访问关键信息并执行任务。可以把MCP想象成AI应用的USB-C接口。正如USB-C提供了连接电子设备的标准化方式，MCP也提供了将AI应用与外部系统连接的标准化方式

**MCP能实现什么？**

- 客服可以访问您的Google日历和Notion，作为更个性化的AI助手。
- Claude Code 可以基于 Figma 设计生成整个网页应用。
- 企业聊天机器人可以连接组织内多个数据库，使用户能够通过聊天分析数据。
- AI模型可以在Blender上创建3D设计，并用3D打印机打印出来。



为什么需要MCP？

给大模型一个工具调用能力，当大模型决定在什么时候调用哪个工具


> [!NOTE]
>
> **Function Calling** 是指大语言模型能够理解用户的自然语言意图，并**将其转化为结构化的数据（通常是 JSON 格式），以便调用开发者预先定义好的外部工具、API 或代码函数**的能力 
>
> Function Calling 是 LLM 模型本身的一种“核心能力”，而 MCP 是一个“行业标准协议”；MCP 的底层运行高度依赖 Function Calling

| 维度           | Function Calling (函数调用)                            | MCP (Model Context Protocol)                               |
| :------------- | :----------------------------------------------------- | :--------------------------------------------------------- |
| **定义**       | LLM 模型的一种原生能力/特性                            | 连接 LLM 与外部工具/数据的通信协议                         |
| **所属层级**   | 模型层 (Model Layer)                                   | 架构/应用层 (Architecture Layer)                           |
| **核心作用**   | 将自然语言意图转化为结构化的机器指令 (JSON)            | 统一外部工具和数据源的接入标准，消除生态碎片化             |
| **解决的问题** | 模型“怎么准确表达调用需求”                             | 工具“怎么让所有 LLM 应用都能无缝接入”                      |
| **主导者**     | 各大模型厂商 (OpenAI, Anthropic, 智谱, 百度等)         | Anthropic (开源标准)                                       |
| **相互关系**   | **底层基础**：MCP 依赖 Function Calling 来触发工具执行 | **上层建筑**：MCP 将 Function Calling 的能力标准化、生态化 |






MCP遵循客户端-服务器架构，其中 MCP Host——Claude Code 或 Claude Desktop 等AI应用程序——与一个或多个MCP Server 建立连接。MCP 主机通过为每个 MCP Server 创建一个 MCP Client 来实现这一目标。每个 MCP Client 都与相应的 MCP Server 保持专用的一对一连接。MCP架构的主要组成者是：

- **MCP Host**：协调和管理一个或多个 MCP Server 的人工智能应用程序
- **MCP Client**：一个组件，用于维护与 MCP 服务器的连接，并从 MCP 服务器获取上下文，供 MCP 主机使用
- **MCP Server**：一个为 MCP Client 提供上下文的程序





MCP定义了一个严格的生命周期（lifecycle），用于客户端-服务器连接，确保了通信双方能进行适当的状态管理和能力协商。
MCP连接生命周期主要分为三个阶段：

- 初始化阶段，客户端与服务器进行协议版本和能力协商；
- 操作阶段，客户端与服务器按照协议正常通信，交换消息；
- 关闭阶段，客户端与服务器各自优雅地终止连接。











## 全链路：MCP、Function Calling、SGLang 和 Agent 如何串起来

### 六个概念，先分清职责

常见误区：模型返回了 `tool_calls` 就以为工具已经执行了；接入 MCP Server 后不明白为什么还要给模型传 `tools`。根源是把三件事混成了一件——**模型生成内容、推理服务处理格式、应用执行动作**。

| 概念 | 职责 |
| --- | --- |
| 模型权重 | 训练得到的参数张量，支撑理解问题、选择工具、生成参数的能力；**不是**工具注册表，不含具体工具的业务实现 |
| SGLang（推理引擎） | 加载模型、处理请求、调度计算、生成并解析输出，对应用提供模型 API |
| Function Calling | 模型与应用之间的**结构化函数调用机制**：应用告诉模型有哪些函数可用，模型返回"调用哪个、传什么参数"——负责**表达调用意图** |
| Tool Call | 一次具体的调用请求（`type: "function"` 场景下与 Function Calling 同义） |
| MCP | 应用与外部能力之间的**标准协议**：发现工具、请求执行、接收结果——负责**标准化工具接入与调用** |
| Agent | 围绕模型运行的程序：上下文管理、工具接入、执行调度、错误处理、终止条件；MCP Client 通常位于 Agent 内部 |

一句话分工：**Agent 管理任务循环，SGLang 运行模型，模型生成工具调用请求，Agent 再通过 MCP 执行工具，并把结果送回模型。**

Function Calling 与 MCP 不是强制绑定的：Function Calling 可以连接本地函数或普通 HTTP API；MCP 工具也可以由普通程序直接调用，不必先问模型。两者通过 Agent 中的**适配代码**衔接。

### 工具先被发现，再被介绍给模型

初始化两条线独立进行：

- SGLang 加载模型权重、Tokenizer、Chat Template 和工具解析配置
- Agent 与 MCP Server 初始化通信、协商能力，请求 `tools/list`（工具列表可缓存，按变化更新）

MCP 工具定义 → 模型 `tools` 元素的第一次关键转换——`inputSchema` 映射为 `parameters`，外层按模型 API 要求包装：

```json
// MCP tools/list 返回的工具定义
{ "name": "get_weather", "description": "查询城市天气",
  "inputSchema": { "type": "object",
    "properties": { "city": {"type": "string"} }, "required": ["city"] } }

// Agent 适配后发给模型的 Chat Completions tools 元素
{ "type": "function", "function": {
    "name": "get_weather", "description": "查询城市天气",
    "parameters": { "type": "object",
      "properties": { "city": {"type": "string"} }, "required": ["city"] } } }
```

实际适配还涉及名称限制、Schema 兼容、不同 Server 的工具重名。Agent 需维护"**模型可见工具名 → 对应 Server 和真实工具名**"的路由——模型只需知道工具用途和参数格式，不需要知道 Server 地址、连接方式或凭据。

### messages 和 tools 怎样进入模型

用户问"北京天气怎么样？"，Agent 把问题放入 `messages`、把本轮允许的工具放入 `tools`，发起第一次推理请求。输入经过两层处理：

```
messages + tools
  ↓ Chat Template：按模型要求编排角色标记、对话内容、工具说明
  ↓ Tokenizer：编码为 token IDs
```

**模型不直接读取 MCP 协议对象**——工具名称、描述、参数约束通过输入序列进入上下文。新增工具改变的是上下文和工具路由，**不需要修改模型权重**。这是通用工具使用能力（权重支撑）与具体工具接入（本轮工具说明）的区别。

### 权重、推理、模板和解析器各做什么

```
输入 token IDs
  ↓ Embedding + 模型各层计算（使用权重）→ 下一个 token 的 logits
  ↓ 采样/选择（可能受解码约束限制）→ 下一个 token ID
  ↓ 重复生成输出 token 序列
```

- 模型输出可能是 `<tool_call>{"name":"get_weather",...}</tool_call>` 这类原生格式（**不同模型格式不同**，这只是示例）
- **Tool Parser** 负责识别模型原生格式、转换为 API 的 `tool_calls`——所以模型、Chat Template、Tool Parser 必须匹配
- 三种"正确"要分清：**格式可解析**（解析器管）、**参数符合 Schema**（校验管）、**业务含义正确**（语义判断 + 业务校验管）。约束解码限制输出形式，但不保证业务答案正确；给不擅长工具使用的模型配解析器，也不会自动获得可靠的工具选择能力

### 两个 call：一个提出请求，一个执行请求

```json
// 模型 API → Agent 边界：模型提出的调用请求（arguments 是 JSON 字符串）
{ "role": "assistant", "tool_calls": [{ "id": "call_1", "type": "function",
    "function": { "name": "get_weather", "arguments": "{\"city\":\"北京\"}" } }] }

// MCP Client → MCP Server 边界：发给工具服务的执行请求
{ "jsonrpc": "2.0", "id": 42, "method": "tools/call",
  "params": { "name": "get_weather", "arguments": {"city": "北京"} } }
```

- **看到 `tool_calls` 只能说明模型提出了调用；工具是否执行，要看 Agent 后续是否调度成功**
- 两个 ID 不同：`call_1` 关联模型对话中的调用与结果，`42` 关联 MCP 请求与响应；Agent 负责维护这两层关联
- `arguments` 在模型 API 中是 JSON 字符串，Agent 需解析成对象、校验参数和执行条件再转发
- **实际业务操作发生在 MCP Server 侧**：工具名本身没有执行能力，执行能力来自服务端代码和下游系统（天气 API / 缓存 / 数据库）

### 工具返回后，为什么还要再问一次模型

Agent 把 MCP 结果转换成 `tool` 消息追加进历史，并保留前一条 assistant 的 `tool_calls` 消息（模型才能把"请求查天气"与"返回的数据"对应起来），然后发起第二次推理：

```json
{ "role": "tool", "tool_call_id": "call_1",
  "content": "{\"city\":\"北京\",\"temperature\":26,\"unit\":\"℃\"}" }
```

- MCP 结果不限于文本（可能是结构化内容、图片），适配层应保留目标模型接口能接收的信息，不能一概转字符串
- **"模型知道了刚查到的天气" = 它在当前上下文中获得了这条信息**——工具结果进入上下文，模型权重保持不变；变化的是对话内容和推理临时状态/缓存，不是重新训练

### 完整时序（一轮"查北京天气"）

1. Agent 提交用户问题和可用工具定义
2. SGLang 编排输入（Chat Template → Tokenizer）、运行模型
3. 模型生成调用内容，Tool Parser 解析为 `tool_calls`
4. Agent 解析校验参数，转换为 MCP `tools/call`
5. MCP Server 执行工具，返回业务结果
6. Agent 保存调用消息并追加工具结果
7. 再次推理，生成最终回答或下一次调用

本例两次推理、一次工具执行。工程细节：

- **流式输出**：工具名和参数可能分片到达，须组装完整可校验的请求再执行，不能把参数片段当完整 JSON
- **并行**：互不依赖的调用可并行；有数据依赖（先查用户 ID 再查订单）必须等待
- **循环控制**：Agent 需定义超时、失败处理、重试和轮数上限；有副作用的操作重试前考虑幂等性；模型继续提出动作不意味着程序必须无限循环

### 八处转换 = 八个排查点

| 位置 | 转换 | 重点检查 |
| --- | --- | --- |
| Agent 工具适配层 | MCP 定义 → 模型 `tools` | 名称、Schema、工具路由 |
| 输入模板层 | messages + tools → 输入序列 | 模板是否匹配模型 |
| Tokenizer | 输入序列 → token IDs | 编码、特殊标记、上下文长度 |
| 模型运行时 | 输入 token → 输出 token | 模型能力与生成设置 |
| Tool Parser | 原生输出 → `tool_calls` | 解析器、结束标记、流式组装 |
| Agent / MCP Client | `tool_calls` → `tools/call` | 参数解析、校验与路由 |
| MCP Server | 协议参数 → 业务操作 | 工具实现、访问权限、下游错误 |
| Agent 结果适配层 | MCP 结果 → tool 消息 | 结果内容与调用 ID 关联 |

排查方向：模型没获得正确的工具说明 → 查工具发现和输入适配；返回原始调用文本 → 查模板与解析器；有 `tool_calls` 却没业务请求 → 查 Agent 执行环节；业务调用成功但回答失真 → 查结果回填和后续推理。**按边界保存结构化记录，比只看最终答案更容易定位问题。**

控制权的分布：Agent 决定暴露哪些工具、是否执行、何时结束；模型在这些条件下提出动作；工具服务负责业务执行及服务侧校验。**模型生成下一步的请求，程序把请求变成动作，动作的结果再成为模型下一步的依据。**

## Tools

MCP 让 Claude 连接外部工具和数据源。以下是 10 个必装：

**filesystem** - 文件系统读写，访问本地文件
**postgres/sqlite** - 数据库操作，查询和修改数据
**github** - GitHub API，管理 issues 和 PRs
**puppeteer** - 浏览器自动化，网页截图和爬虫
**fetch** - HTTP 请求，调用外部 API
**memory** - 持久化记忆，跨会话保存信息
**sequential-thinking** - 深度思考，复杂问题推理
**exa** - 搜索引擎，获取最新网络信息
**slack/discord** - 消息平台，发送通知
**notion** - 笔记管理，自动更新文档

```
# 添加 MCP 服务器 
claude mcp add filesystem – npx -y @anthropic-ai/mcp-server-filesystem /path/to/project 

# 查看已配置的服务器 
claude mcp list
```








## Links

- [A2A](/docs/CS/AI/LLM/A2A.md) — agent ↔ agent 的标准协议，与 MCP 互补
- [Agent](/docs/CS/AI/LLM/Agent.md)
- [LLM 应用开发平台](/docs/CS/AI/LLM/Platform.md) — 平台侧同时充当 MCP Client 与 Server

## References

- [MCP、Function Calling、SGLang 和 Agent，到底如何串起来？](https://mp.weixin.qq.com/s/f0N9Rj0qzASgyFU57DjRgg)
