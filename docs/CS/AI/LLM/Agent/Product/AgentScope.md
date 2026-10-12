## Introduction

AgentScope 是阿里巴巴开源的 Python Agent 框架，从 v2.0 开始面向生产场景。核心设计目标是「充分发挥大模型的推理与工具调用能力，而非用严格的提示词和固化的编排方式来束缚它们」——这句话来自官方 README，也是理解它架构选择的钥匙。

这个定位把 AgentScope 放在了 Framework 与 Harness 之间：它提供 LangChain 级别的跨厂商抽象，又把权限、上下文压缩、运行时状态注入这些通常由 Harness 层处理的能力直接做进了核心 Agent 类。再往上，它还附带一套开箱即用的 Agent Service（FastAPI 后端 + 预构建 Web UI），把单个 Agent 包装成多租户、多会话的在线服务。

本笔记以 **v2.0.8** 为基准，全部结论来自本地源码 `/Users/robin/Projects/agentscope` 的逐文件阅读。

## Architecture Overview

AgentScope v2.0 的核心架构可以概括为三层：

| 层次 | 组件 | 职责 |
| :--- | :--- | :--- |
| **Core Agent** | `Agent` 类 + ReAct 循环 | 推理-行动的主循环、上下文管理、事件流式输出 |
| **Infrastructure** | Model / Toolkit / Permission / Middleware / Offloader | 模型调用、工具执行、权限判定、可插拔钩子、上下文卸载 |
| **Service** | FastAPI 后端 + Web UI | 多租户多会话、频道接入、Hub（MCP/Skill）、定时调度 |

核心设计选择只有一个——**一切围绕 `Agent` 类展开**。没有 BaseAgent → ReActAgent → PlanAgent 的类继承层次，`Agent` 就是唯一入口。ReAct 循环是内置的，规划、子 Agent、HITL、中断、压缩全都是这个类里的方法或中间件实现。这意味着一个 AgentScope Agent 可以同时具备 ReAct、Plan-and-Execute、HITL、上下文压缩等能力，而不需要切换类。

## The Unified Agent Class

`Agent` 类（`agent/_agent.py`，约 2500 行）是整个框架的心脏。构造函数接收四大配置对象：

```python
Agent(
    name="Friday",
    system_prompt="...",
    model=DashScopeChatModel(...),
    toolkit=Toolkit(tools=[Bash(), Grep(), ...]),
    middlewares=[...],
    model_config=ModelConfig(...),        # fallback model + retries
    context_config=ContextConfig(...),    # 压缩阈值 + 摘要模板
    react_config=ReActConfig(...),        # max_iters + 中断行为
    injection_config=InjectionConfig(...),# 运行时状态注入
)
```

四个 Config 是 Pydantic BaseModel，字段默认值覆盖了绝大多数场景。`_validate_configs()` 在构造时检查一个核心不变量：`reserve_ratio < trigger_ratio`、`context_buffer_ratio < trigger_ratio`——确保压缩阈值、缓冲区间距、保留区三者不重叠。

Agent 的两个公开方法是 `reply()` 和 `reply_stream()`，后者返回 `AsyncGenerator[AgentEvent | Msg]`。内部统一走 `_reply()` → 中间件链 → `_reply_impl()` 主循环。

## Message System

AgentScope 的消息模型是 **结构化 ContentBlock 列表**，而不是纯文本。`Msg.content` 是 `list[ContentBlock]`，六种 block 类型：

| Block 类型 | 角色限制 | 内容 |
| :--- | :--- | :--- |
| `TextBlock` | 全部 | 文本 |
| `ThinkingBlock` | 仅 assistant | 模型推理过程（reasoning token） |
| `ToolCallBlock` | 仅 assistant | 工具调用意图（id + name + input JSON） |
| `ToolResultBlock` | 仅 assistant | 工具执行结果（id + name + output + state） |
| `DataBlock` | user / assistant | 多模态数据（image / audio / file） |
| `HintBlock` | 仅 assistant | 系统提示（运行时注入、offload 提醒） |

role 有严格约束：`user` 只收 TextBlock + DataBlock；`system` 只收 TextBlock；`assistant` 收全部。`Msg` 的 Pydantic validator 在构造时强制执行这些约束。

`Msg` 还携带 token usage（input/output/cache 分拆）、`structured_output`（结构化输出时填充）、`finished_reason`（COMPLETED / INTERRUPTED / EXCEED_MAX_ITERS / ERROR）等元数据。`append_event()` 方法是流式输出的重建器——把一串 AgentEvent 按 reply_id 归并到一条 Msg 的 content 里。

## Event-Driven Streaming

AgentScope 的输出是**事件流**，不是文本流。`agent._agent.py` 的事件类型覆盖了 reply 的每个阶段：

```
REPLY_START → MODEL_CALL_START → TEXT_BLOCK_START → TEXT_BLOCK_DELTA* → TEXT_BLOCK_END
                               → TOOL_CALL_START → TOOL_CALL_DELTA* → TOOL_CALL_END
                               → THINKING_BLOCK_START → ...
                               → MODEL_CALL_END → ...
→ (每轮 ReAct 循环)
→ REPLY_END
```

还有三类交互事件：
- `REQUIRE_USER_CONFIRM` / `USER_CONFIRM_RESULT` —— 工具调用需要人工确认，Agent 暂停等待
- `REQUIRE_EXTERNAL_EXECUTION` / `EXTERNAL_EXECUTION_RESULT` —— 外部系统执行的工具（后台任务卸载），Agent 提交后继续等待
- `USER_INTERRUPT` —— 用户中断，Agent 关闭所有 pending 工具调用

HITL 交互的核心设计：Agent 在遇到需要确认的工具调用时，**不抛出异常也不返回结果**，而是 yield `RequireUserConfirmEvent` 后停在 await 点。调用方（Web UI、Console、上游 Agent）决定后把结果作为下一次 `reply()` 的输入传回来——同一个 Agent 实例、同一条上下文、循环从断点继续。

## ReAct Loop: The Core

`_reply_impl()` 是约 300 行的主循环，核心逻辑在一个 `while True` 里：

```python
while True:
    next_action = self._next_action(final_msg)

    match next_action:
        case Exit(...):         # 没有工具调用 + 已完成
            yield exit_msg
            return

        case Reasoning(...):    # 调用模型
            await self.compress_context()        # 先检查压缩
            async for evt in self._inject_runtime_state():
                yield evt
            async for evt in self._reasoning():  # 调模型、流式输出
                yield evt

        case Acting(...):       # 执行工具调用
            for batch in await self._batch_tool_calls(tool_calls):
                # 按 is_concurrency_safe 分 batch
                if batch.type == "concurrent":
                    async for evt in self._execute_concurrent_tool_calls(...):
                        yield evt
                else:
                    async for evt in self._execute_sequential_tool_calls(...):
                        yield evt
```

### Three Action Types

`_next_action()` 根据当前状态返回三种之一：

1. **Exit**：模型没有返回工具调用（纯文本回复），或迭代次数超过 `max_iters`，或收到中断信号
2. **Reasoning**：正常下一轮模型调用
3. **Acting**：模型返回了工具调用，需要执行

### Batch Tool Execution

模型一轮可能返回多个工具调用。`_batch_tool_calls()` 按工具的 `is_concurrency_safe` 属性分批——**安全的并发执行，有副作用的顺序执行**。同一批次内并发调用通过 `asyncio.gather(return_exceptions=True)` 并行跑，结果通过 `asyncio.Queue` 合并事件流。

顺序执行遇到 `RequireUserConfirmEvent` 或 `RequireExternalExecutionEvent` 时立即 break，后续调用在恢复后继续；并发执行时用户确认会导致整批的后续调用也停下来。

### Interruption

中断路径分两条：
- **`UserInterruptEvent` 主动触发**：Agent 先跑 `_close_unfinished_tool_calls()` 把所有 pending 的 ToolCall 标成 INTERRUPTED 并补 ToolResult，然后 yield 一条默认消息（`react_config.interruption_message`）
- **`asyncio.CancelledError` 被动捕获**：压缩过程被中断、模型调用超时等。`react_config.interruption_raise_cancelled_error` 决定是吞掉异常让循环正常结束还是 re-raise

### HITL State Machine

Agent 的 ToolCall 有完整的生命周期：

```
PENDING → ASKING → ALLOWED → FINISHED
                 → DENIED
                 → SUBMITTED → FINISHED
                 → INTERRUPTED（用户中断）
                 → ERROR（执行失败）
```

`_check_incoming_event()` 确保状态一致性——如果 Agent 正在等待 2 个工具的确认，只传回来 1 个结果会报错；传回来的工具 id 不在等待列表里也会报错。

## Middleware System

中间件是 AgentScope 最值得细看的设计。`MiddlewareBase` 定义了 **7 个 hook**，运行时自动检测子类实现了哪些（`is_implemented()` 用 `base_method is not sub_method` 判断），Agent 在构造时把它们按 hook 类型分到七个列表里。

七个 hook 分两种模式：

**Onion Pattern（6 个，有 before/after 语义）**：
- `on_reply` —— 拦截整个 reply 循环。**可以吞掉 ReplyEndEvent 强制多跑一轮**（不 yield 它），`_receive_reply_end` 标志位防止中间件无限套娃
- `on_reasoning` —— 拦截模型调用前后
- `on_acting` —— 拦截单个工具执行的纯 I/O 层（不包含权限检查、输入校验、context 写入）
- `on_check_permission` —— 拦截权限判定，middleware 可以替代引擎返回决策
- `on_model_call` —— 拦截底层 API 调用
- `on_compress_context` —— 拦截上下文压缩

**Transformer Pattern（1 个，串行管道）**：
- `on_system_prompt` —— 把 system_prompt 字符串改一下返回，每个 middleware 拿上一个的输出当输入

Onion hook 的签名统一是：
```python
async def on_xxx(self, agent, input_kwargs, next_handler):
    # before: agent=agent（可读写 agent 状态）
    async for item in next_handler(**input_kwargs):
        # after: yield 前可修改事件
        yield item
```

中间件链内部用递归构造执行器（`execute_chain`），和 Koa/Express 的洋葱模型写法一模一样。

## Permission System

权限系统由 `PermissionEngine` + `PermissionRule` + `PermissionDecision` 组成。五种模式覆盖了从最严格到最宽松的完整光谱：

| 模式 | 默认行为 | 典型场景 |
| :--- | :--- | :--- |
| `DEFAULT` | 非只读操作都 ASK | 日常使用，每步确认 |
| `EXPLORE` | 只读 ALLOW，修改 DENY | 探索代码库、浏览 |
| `ACCEPT_EDITS` | 工作目录内的编辑自动 ALLOW | 编码场景（Write/Edit 工作目录） |
| `BYPASS` | 除 DENY 规则外全部 ALLOW | 沙箱环境、全托管场景 |
| `DONT_ASK` | 所有 ASK 转成 DENY | 定时任务、后台无人值守 |

每个 mode 有独立的 `_check_<mode>` 方法，优先级链清晰：

```
deny_rules → ask_rules → read_only → tool.check_permissions → allow_rules → mode_fallback
```

**三个关键设计**：

1. **Safety ASK（bypass_immune）**：工具自己返回的 ASK 可以标记 `bypass_immune=True`，在 DEFAULT/ACCEPT_EDITS 模式下无法被 allow rule 覆盖。典型场景是 `Bash("rm -rf /")`——即使用户加了 `Bash:*` 的允许规则，安全 ASK 仍然会弹确认。BYPASS 模式主动跳过安全 ASK（因为"完全信任用户"），DONT_ASK 把安全 ASK 转成 DENY（因为"没人回答"）。

2. **suggested_rules**：每次 ASK 都生成建议规则（Bash 提取命令前缀、文件操作提取目录 glob），用户一键添加后下次同类调用自动放行。

3. **Concurrent batch 内的 ASK 去重**：并发执行多个工具时，同一批次的 `kept_rules` 列表累积已确认生成的 allow rule。后续工具的 ASK 如果已被某个 earlier rule 覆盖，就不再弹第二次——只对非安全 ASK 生效。

## Context Management

AgentScope 的上下文管理有三层机制，**全部在核心 Agent 类里**，不是中间件。

### ContextConfig

```python
ContextConfig(
    trigger_ratio=0.8,         # 触发硬压缩的 token 比例
    reserve_ratio=0.1,          # 压缩后保留的尾部上下文比例
    context_buffer_ratio=0.2,   # 缓冲区：提前注入"快到压缩了"的提示
    tool_result_limit=50000,    # 工具结果 token 上限，超过截断
    max_image_num=5,            # 上下文里最多保留的图片数
    compression_tool_enabled=False,  # 是否暴露 CompressContext 工具给 Agent
    compression_fallback_to_truncation=True,  # 压缩失败时降级为截断
)
```

`trigger_ratio` 最大 0.9，留出最后 10% 给压缩过程本身；`reserve_ratio` 不能 >= `trigger_ratio`——否则压缩完保留区就比整个窗口还大了。

### Structured Compression

压缩不是一把梭，而是结构化的。`SummarySchema` 定义了压缩产物的五个维度：

1. `task_overview` —— 用户核心请求与成功标准
2. `current_state` —— 已完成的工作（文件路径、关键输出）
3. `important_discoveries` —— 技术约束、决策理由、踩过的坑
4. `next_steps` —— 具体下一步动作
5. `context_to_preserve` —— 用户偏好、领域细节、已做的承诺

压缩提示词（`compression_prompt`）里特别强调了**时间锚定**（"today" 转绝对日期）、**指针解析**（不能写 "this file" 必须写完整路径）、**后台任务状态**（"我还在等哪个任务的结果"）——因为压缩后的摘要可能被再次压缩，所有引用必须自包含。

压缩产物通过 `summary_template` 格式化成 `<system-info>...</system-info>` 块，替换掉上下文里被压缩的消息，保存在 `AgentState.summary`。

### Runtime State Injection

`InjectionConfig` 控制每轮 reasoning 前注入的四个维度：

1. **Time**：当前时间（指定时区），首次 reply 或上次注入超过 `time_interval`（默认 0.5 小时）时触发
2. **Plan Tasks**：有 pending/in_progress 任务且上下文里没提过时触发（通过扫描 TaskCreate/TaskList 等工具调用或上次的 tasks injection 判断）
3. **Context Length**：reply 开始时 token 超过 `(trigger - buffer) * context_size` 触发。如果 `compression_tool_enabled=True` 且没在做任务，还会告诉 Agent "你可以主动调 CompressContext"
4. **Tool Error**：同一个工具 + 相同参数连续失败 `tool_retries_limit`（默认 3）次时，注入提示 "别再重试了，换个方式"

所有注入都通过 `HintBlock`（不是改 system prompt）实现，**故意这样做是为了让 prompt caching 继续生效**——system prompt 一 cache 就锁死了，而 HintBlock 每次追加到 context 尾部，不影响前缀缓存。

### Offloader

如果提供了 `Offloader`，压缩掉的上下文和超过 `max_image_num` 的旧图片会被写到 workspace（Daytona / Bubblewrap / 本地文件），原来的位置替换成 `<system-reminder>offloaded to /path</system-reminder>`——不是丢弃，而是换个地方放。

## Tool System

### Toolkit

`Toolkit` 是 Agent 可调用工具的唯一来源。构造时可以注册 Python 函数、MCP 连接、Skill。AgentScope 内置的工具集包括 Bash / Grep / Glob / Read / Write / Edit / Search / TaskCreate / TaskList 等。

工具的两个关键属性：
- `is_concurrency_safe` —— 能否安全并发执行（决定批处理策略）
- `is_read_only` —— 是否只读（权限系统的 fast path，只读调用永远 ALLOW）

### Compression Tool

`CompressContext` 是 AgentScope 自动注册的内置工具。Agent 可以主动调它来压缩——设计动机是「在任务边界处（比如读完文档、还没开始写代码）压缩，比跑着跑着被强制压缩更准」。这个工具的调用是 `PermissionDecision(ALLOW, bypass_immune=True)`，永远允许。

## Model Abstraction

`ChatModelBase` 是所有模型厂商的基类，子类只需实现 `_call_api()` 并可选覆盖：
- `_get_retryable_exceptions()` —— 声明 transient 错误类型用于重试
- `_get_disable_thinking_kwargs()` —— 给支持的厂商提供关闭 thinking 的参数
- `_get_structured_output_fallback_exceptions()` —— 声明结构化输出的兼容问题异常

### Structured Output Fallback

`generate_structured_output()` 是压缩、structured reply 等场景的基础。它不是单一策略，而是四级 fallback 链：

```
forced（强制 tool_choice）→ auto（自动）→ no_think（关 thinking + 强制 tool_choice）→ none（不强制）
```

每级内部还有重试循环（`max_retries`）。这个 fallback 的存在是因为不同厂商对 tool_choice + thinking 的组合支持不一致——有的开着 thinking 就不支持 forced tool_choice，有的刚好相反。

### Token Counting

`count_tokens()` 的实现简单到出乎意料：把所有 TextBlock/ThinkingBlock/ToolCallBlock/ToolResultBlock/HintBlock 里的文本拼起来，加上工具 JSON schema，**总字节数 / 4** 加一个 block 固定 2000 token。源码里明写了这是 quick estimate，子类可以覆盖。

## Pipeline & Agent Service

### Pipeline

`PipelineProtocol` 定义了 pipeline 与 Agent 相同的接口——`reply_stream()` 返回同样的事件流。Pipeline 本质上是**固化逻辑的多 Agent 编排器**：按预设顺序把消息喂给一串 Agent，适合流水线式任务（文档 → 提取 → 汇总）。Goal Pipeline 额外提供循环与 goal 检查。

### Agent Service

Agent Service 是 `examples/agent_service/` 里的 FastAPI 应用，完整功能包括：

- **多租户多会话**：SQL 存储（Alembic 迁移）+ Redis 消息总线
- **频道接入**：飞书 / Discord / DingTalk，自定义 Gateway + Routing
- **Hub 集成**：GitHub MCP Registry + ClawHub，浏览 → 安装到个人库 → 添加到工作区
- **团队编排**：Leader-Worker 模式 + 内置团队工具（AgentCreate / AgentInvite / TeamSay）
- **后台任务**：长时间运行的工具转入后台，完成后通过消息总线唤醒 Agent
- **调度**：定时任务 + Agent 唤醒（`wakeup_dispatcher`）
- **RAG 服务**：Blobs 存储 + 索引 Worker + Milvus / ES / MongoDB 向量后端
- **资源共享**：group / org 级别的模型、MCP、Skill、Workspace 共享

附带的 Web UI 是 React + Vite（`examples/web_ui/`），i18n 支持中英文。

## Comparison

### AgentScope vs LangChain / LangGraph

AgentScope 属于和 LangChain 同层的 Framework，但架构选择不同：

| 维度 | AgentScope | LangChain |
| :--- | :--- | :--- |
| Agent 设计 | 单一 `Agent` 类，内置全部能力 | BaseAgent 继承体系，ReActAgent / PlanExecuteAgent 等 |
| 中间件 | 7 hook 自动检测，onion + transformer 双通道 | Callback 机制（on_chain_start / on_tool_start 等），不区分 hook 位置 |
| 权限 | 核心组件，5 种 mode + 三级规则 + safety ASK | 无内置权限层，靠自定义 chain |
| 事件驱动 | 原生 AgentEvent 流式输出，ReplyStart → ReplyEnd 完整生命周期 | Callback 体系 + streaming 分开 |
| 上下文压缩 | 内置结构化压缩 + runtime injection + 主动 CompressContext 工具 | 需要自己实现 Memory 类（ConversationSummaryMemory 等） |
| 服务化 | 内置 FastAPI + Web UI + 多租户 | 无，靠自研或 LangSmith |

AgentScope 的选择是**把 Harness 层的能力直接做进 Framework 核心**——权限、压缩、运行时状态注入、offloader 都是 `Agent` 类的内置机制，不需要额外组件。这和本库 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 里说的「Runtime / Framework / Harness 三层」对照来看，AgentScope v2.0 实际上是**把 Framework 和 Harness 两层合并了**，而把 Runtime（图式状态、持久化、人工协作断点恢复）留给 Pipeline 和 Agent Service 层补全。

### AgentScope vs Coding Agents

和 [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode.md)、[Codex](/docs/CS/AI/LLM/Agent/Product/Codex.md)、[DSH](/docs/CS/AI/LLM/Agent/Product/DSH.md) 这些编程 Agent 比，AgentScope 的定位更基础——它不预设"用户是开发者、Agent 写代码"这种场景，而是提供一个可以包装任意模型、接入任意工具、通过中间件扩展行为的通用框架。编码场景只是其中一个 Toolkit（Bash / Grep / Read / Write / Edit）。

反过来说，如果要在 AgentScope 上搭一个 Coding Agent，需要自己加 Shell 执行环境（Bubblewrap / Daytona）、文件系统权限模型、PTY 支持这些东西——这些在 Claude Code / Codex 里是 Harness 内置的。AgentScope 给的是脚手架，不是成品。

## Component Design Analysis

上一节讲"有什么"，这一节讲"为什么这样设计"。每个组件都从**设计动机 → 取舍 → 关键实现细节**三个角度展开。

### Runtime Component Interaction: One ReAct Iteration

先给一张图，把一轮 ReAct 循环里所有组件怎么交互画出来。对照这张图读后文的组件分析最清晰：

```
  UserMsg ──→ Agent.reply(inputs)
                   │
                   ▼
          [middleware: on_reply chain]
                   │
          ┌────────▼────────┐
          │  _reply_impl()   │ ◀─── AgentState.reply_context 初始化
          │  ReAct 主循环    │
          └────────┬────────┘
                   │
    ┌─── cur_iter < max_iters? ───┐
    │  │                          │
    ▼  │  yes                     ▼ no
 Exit  │                  EXCEED_MAX_ITERS
    │  │                          │
    ▼  │  Reasoning path          ▼
    │  ├── compress_context()     │
    │  │     │                    │
    │  │     └── _limit_context_images()
    │  │     └── 计数 tokens
    │  │     └── LLM 生成 summary (structured_output)
    │  │     └── state.summary / state.context 替换
    │  │                          │
    │  ├── _inject_runtime_state()│
    │  │     │                    │
    │  │     └── HintBlock 追加到 state.context
    │  │     └── yield HintBlockEvent
    │  │                          │
    │  ├── _reasoning()           │
    │  │     │                    │
    │  │     ├── [mw: on_reasoning]
    │  │     ├── _prepare_model_input()
    │  │     │     ├── system prompt + on_system_prompt chain
    │  │     │     ├── state.context 全部 Msg
    │  │     │     └── toolkit.get_tool_schemas() (activated_groups)
    │  │     ├── ChatModelBase() ──── model._call_api()
    │  │     │     │                    ├── retry loop
    │  │     │     │                    └── _StreamAccumulator
    │  │     │     └── yield 各类 Block Event + ModelCallEndEvent
    │  │     └── _save_to_context() ──── state.context append AssistantMsg
    │  │                          │
    │  └── ToolCallBlock 返回? ─┐ │
    │         │                  │ │
    │      无 ─┤                  │ │
    │         │  纯文本回复       │ │
    │         ▼                  │ │
    │   生成 final AssistantMsg ──┤ │
    │         │                  │ │
    │         ▼                  │ │
    │   ReplyEndEvent ──── Exit  │ │
    │                              │ │
    │  Acting path                 │ │
    │  ├── _batch_tool_calls()    │ │
    │  │     │                    │ │
    │  │     └── is_concurrency_safe → concurrent / sequential batch
    │  │                          │ │
    │  └── _execute_tool_call()   │ │
    │        │                    │ │
    │        ├── toolkit.check_tool_available()
    │        ├── _json_loads_with_repair + jsonschema.validate
    │        ├── _check_permission()
    │        │     │              │ │
    │        │     ├── [mw: on_check_permission]
    │        │     └── PermissionEngine.check_permission()
    │        │           │        │ │
    │        │           └── mode 分发 (_check_default / _check_explore / ...)
    │        │               └── deny → ask → readonly → tool.rule → allow → default
    │        │                    │
    │        │              ASK? ─┼─── yield REQUIRE_USER_CONFIRM, loop park
    │        │               │          下次 reply(UserConfirmResultEvent) 恢复
    │        │            ALLOW ──┤
    │        │                    │
    │        ├── _acting()        │ │
    │        │     │              │ │
    │        │     ├── [mw: on_acting]  ← 只包 toolkit.call_tool()
    │        │     │     │        │ │
    │        │     │     └── Tool.__call__() ← ToolMiddlewareBase 洋葱
    │        │     │           │  │ │
    │        │     │           └── Tool.call()
    │        │     │              │ │
    │        │     └── yield ToolResult events
    │        │                    │ │
    │        └── ToolResultBlock 写入 state.context
    │                               │
    └─────────── loop back to cur_iter++ ────┘
```

这张图里可以看到几个核心事实：
- **AgentState 是所有组件的共享数据总线**——context、summary、reply_context、permission_context、tool_context、tasks_context、middle_context 七块数据，被 Agent / PermissionEngine / Toolkit / 所有 Middleware 共同读写
- **中间件在六个不同层级切入**——on_reply 包整个循环、on_reasoning 包模型调用、on_model_call 包底层 API、on_check_permission 包权限判定、on_acting 包工具执行（只包纯 I/O 层）、on_compress_context 包压缩
- **HITL 暂停是轻量的**——yield `RequireUserConfirmEvent` 后直接停在 `_reply_impl` 的 await 点，没有任何 cleanup 或状态保存；下次回来同一条 Agent 实例、同一个 state、循环从断点继续

### AgentState: The Unifying Data Container

`AgentState` 是一个**纯 Pydantic BaseModel**，六个字段全部是子 context：

```python
class AgentState(BaseModel):
    session_id: str                              # 会话级标识
    summary: str | list[TextBlock | DataBlock]   # 压缩后的摘要
    context: list[Msg]                           # 未压缩的对话上下文
    reply_context: ReplyContext                  # 当前 reply 的 reply_id / cur_iter / structured_schema
    permission_context: PermissionContext       # 权限规则 + mode
    tool_context: ToolContext                    # 文件缓存 + activated tool groups
    tasks_context: TaskContext                  # Plan 模式的任务列表
    middle_context: dict[str, Any]               # 中间件跨回复状态
```

**设计动机**：把所有需要跨回复、跨 HITL 断点保留的状态，装进一个可序列化的模型，而不是散落在 Agent 实例的各个属性里。AgentScope 的 FastAPI 服务需要把 Agent 持久化到 SQL（会话暂停、进程重启后恢复），一个 BaseModel 直接 `.model_dump()` + Alembic migration 就搞定了。

**关键取舍**：
- **不是分离的 Store/Repository**——AgentScope 没有 `ContextStore` / `PermissionStore` 这类类，六个子 context 就是直接嵌在一个模型里。好处是引用透明（`state.context`、`state.permission_context`），坏处是 state 对象会越来越大；但 AgentScope 的压缩机制（`trigger_ratio=0.8` 就动手）和 tool result truncation（`tool_result_limit=50000`）就是为了限制 state 的体量
- **middle_context 的 key 设计**——每个 middleware 实例用 `get_middleware_key()`（默认类名）注册自己的状态，budget middleware 在里面存 per-reply 的 token 计数。同一个 middleware 实例可以安全地被多个 Agent 共享（因为状态全在 state 里，不在实例里）
- **read_file_cache 的 LRU**——`ToolContext.read_file_cache` 是一个 list，文件工具重复读同一个文件时先查 cache（按 mtime 判过期），修改后 `_clear_unreserved_read_cache()` 只清压缩掉的路径。这个 cache 减少了模型决策后再次 `Read` 同一个文件的开销——典型场景是 Agent 读完 main.py → 让模型推理 → 又要读 main.py 的某行

### Dual Middleware: Agent-Level + Tool-Level

AgentScope 有两层独立的中间件系统，这不是巧合：

| 维度 | Agent 层 `MiddlewareBase` | Tool 层 `ToolMiddlewareBase` |
| :--- | :--- | :--- |
| 注册位置 | `Agent(middlewares=[...])` | `Tool(middlewares=[...])` |
| 洋葱层数 | 6 个 onion hook + 1 个 transformer | 仅 1 个 hook `on_tool_call` |
| `next_handler` 返回值 | AsyncGenerator（流事件） | AsyncGenerator[ToolChunk]（流 chunk） |
| 能访问什么 | `agent`（含 state）、`input_kwargs` | `tool`、`input_kwargs` |
| 状态存储 | `agent.state.middle_context` | 无内置约定 |
| 能否 offload 到后台 | 只有 `on_acting` 可以（因为只包纯 I/O 层） | 可以（Tool.call 本身就是 async generator） |

**设计动机**：两层中间件解决两个不同粒度的问题。Agent 层中间件处理"整个 Agent 的行为"——预算控制、RAG 注入、Tracing 观测——需要跨多轮 reasoning-acting 循环，需要能读/写 agent state。Tool 层中间件处理"单个工具的执行"——日志、重试、输出格式转换——粒度更细，而且 tool 可能被 Agent 层的 `Toolkit.call_tool()` 直接调到（甚至可能绕开 Agent 层中间件）。

**关键取舍**：
- **Tool 层中间件是 Tool 自己的属性**——这意味着同一个 `Bash` 工具实例共享它的中间件链。如果两个 Agent 共享同一个 Toolkit 里的 Bash 实例，它们也共享 Bash 的 middleware。AgentScope 默认让每个 Agent 构造自己的 Toolkit，所以这不是问题，但在多 Agent 协作场景（Agent Service 的 TeamCreate）里需要注意
- **`__call__` 始终返回 AsyncGenerator**——Tool.call 可以是 coroutine、asyncgen 或 sync gen，但 `__call__` 统一包装成 asyncgen 返回。这样 ToolMiddlewareBase 永远只和一种返回类型打交道，不需要处理多态

### Toolkit: Unified Registration + Dynamic Activation

`Toolkit` 把 Python 工具、MCP 工具、Skill 三件事**统一成 ToolBase 对象**，再挂进 `ToolGroup` 分组。这背后的设计是：

**动态工具集**：AgentScope 内置了两个 meta tool——`ResetTools`（激活/停用 tool group）和 `SkillViewer`（列出可用 Skill）。Agent 自己可以调这两个工具来动态改变它看到的工具集：

```python
class ResetTools(ToolBase):
    # input schema 动态生成——根据已注册的 tool_groups 决定哪些 group 可切
    # 执行时修改 Toolkit.activated_groups
    # 返回值被包装成 Jinja2 模板渲染的文本（激活了哪些 group、各 group 的 instructions）
```

这个设计让 Agent 可以**在运行时决定自己看到什么工具**——编码任务激活 bash/file tool group，调研任务激活 web/search group，而不是在构造 Agent 时一次性定死。

**MCP / Skill / Python 的统一入口**：
- MCP Client 在构造 Toolkit 时 list_tools()，返回的每个 tool 都被包装成 `ToolBase`（带 `is_mcp=True` + `mcp_name`）
- Skill 是纯 Markdown 文件夹，不是 Tool——Toolkit 把 Skill 的 description 收集起来，通过 `skill_instruction_template`（Jinja2）生成一段 prompt 注入到 system prompt，同时暴露 `SkillViewer` 让 Agent 主动读 skill 内容
- Python 工具直接继承 `ToolBase`，或用 `FunctionTool(func)` 包装一个 Python 函数

三种来源最后统一成 `Toolkit._get_available_tools()` 返回的 `dict[name, RegisteredTool]`——模型拿到的永远是同一套 JSON schema，不管工具是 MCP server 来的还是本地 Python 函数。

**一个 MCP 工具挂了不会拖垮整个 reply**：`Toolkit._get_available_tools()` 在注册 MCP client 的 tools 时，如果 `client.list_tools()` 抛异常，只是 `logger.warning` 然后跳过这个 client，**不会让整个 reply 崩溃**。设计动机在源码注释里写得很直白："一个过期 token 或宕机的 MCP server 不应该终止整个对话"。

### Event System: Why Typed Events Instead of Callbacks

AgentScope 的输出是 `AsyncGenerator[AgentEvent | Msg]`，每种事件都是带 type 标识的 Pydantic 模型（`EventType` 是 `StrEnum`）。这套设计和 LangChain 的 Callback 体系的核心差异：

| 维度 | AgentScope AgentEvent | LangChain Callback |
| :--- | :--- | :--- |
| 传输方式 | async generator yield | 同步 hook 调用 |
| 消费者 | 单一（上游），事件是串行流 | 多个 observer，回调可能乱序 |
| 与 Msg 重建 | `Msg.append_event()` 按 reply_id 归并 | 无原生重建 |
| HITL 协议 | `RequireUserConfirmEvent` + `UserConfirmResultEvent` 形成对 | 需要自定义 callback handler + Agent 状态管理 |

**设计动机**：AgentScope 的事件系统承担了两件事——① 流式输出给前端（Web UI、Console）；② HITL 暂停/恢复协议。`ReplyStartEvent` 和 `ReplyEndEvent` 成对出现，中间的所有事件都带 `reply_id`，让 `Msg.append_event()` 能把整个事件流重建回一条完整的 Msg。这个重建能力是 HITL 恢复的基础——前端可以把一个被暂停的事件流完整存下来，恢复时直接 replay 就能拿到同一条 Msg。

**`_receive_reply_end` 的反直觉设计**：Agent 层 middleware 的 `on_reply` 可以**故意吞掉** `ReplyEndEvent`（收到但不 yield），强制让 ReAct 循环多跑一轮。但这不是无限的——Agent 内部跟踪一个 `_receive_reply_end` flag 和 `made_progress` flag：如果 middleware 连续两次吞掉 ReplyEndEvent 且中间没有 reasoning/acting（即 cur_iter 没有增长、没有任何工具调用），会抛 RuntimeError。这个防套娃的逻辑写在 `_reply_impl` 的 Exit 分支里，是 AgentScope 少有的内置安全网。

### Agent + Four Config Objects

`Agent` 构造函数接收四个 Pydantic Config（`ModelConfig` / `ContextConfig` / `ReActConfig` / `InjectionConfig`），而不是一堆参数。这个设计带来三件事：

1. **自动校验**——`ContextConfig` 的 `trigger_ratio` 必须 > `reserve_ratio` 且 <= 0.9，`InjectionConfig.template` 必须包含 `{runtime_state}` 占位符。Pydantic validator 在构造时就挡住不合法配置
2. **可序列化**——四个 Config 加 `AgentState` 一起 `.model_dump()` 就是一份完整的 Agent 快照，方便持久化和恢复
3. **Config 组合而非继承**——LangChain 体系常见"子类覆盖一个 config 再继承另一个"，AgentScope 用组合，四个 Config 之间通过 `_validate_configs()` 检查跨对象不变量（比如 `injection_config.context_buffer_ratio` 已 deprecated，移到 `context_config`）

### Pipeline's Interface Segregation

`PipelineProtocol` 只有一个方法——`reply_stream()`，签名和 `Agent.reply_stream()` **完全相同**。这意味着 GoalPipeline（executor + verifier 循环）可以无缝替换 Agent 传给上游，Team Pipeline（leader 委派 worker）也一样。

这不是巧合——AgentScope 设计 Agent 和 Pipeline 时就把它们放在同一个抽象层：都是能"输入 Msg/Event、输出事件流"的东西。区别只是：Agent 内部是一次 ReAct 循环，Pipeline 内部是多次 Agent 调用的编排。

### GoalPipeline 的 Executor-Verifier 双 Agent 模式

`GoalPipeline` 的核心逻辑：

```python
async for event in executor.reply_stream(goal):
    yield event
    if isinstance(event, Msg) and event.id == executor.state.reply_id:
        executor_report = event
        break

verifier_input = UserMsg(name="user", content=[goal, executor_report])
verifier_result = await verifier.reply(verifier_input, structured_schema=_VerificationResult)

if verifier_result.structured_output.result == "pass":
    # Goal achieved
    yield ReplyEndEvent(...)
    break
elif verifier_result.structured_output.result == "impossible":
    # Goal impossible, stop
    yield ReplyEndEvent(finished_reason=ExceedMaxIters)
    break
else:
    # Fail with feedback → executor 下一轮
    pass
```

三个设计点值得单独记：
- **verifier_reset_context**——默认 True，每轮 verifier 从零开始，不累积上下文。动机是"让 verifier 每次只看 executor 的报告，不被之前轮次的历史影响"
- **_iters 存在实例上而非 reply_context 里**——HITL 恢复时，reply_context 会重建，但 GoalPipeline 实例的 `_iters` 不变。设计动机是"budget 不应该因为 HITL 恢复而重置"
- **impossible 结果**——三值枚举（pass / fail / impossible），impossible 让 executor 停止尝试而不是继续重试。这是比大多数 Agent 框架更精细的终止条件控制

### Service Layer: Multi-Tenant Agent Runtime

Core Agent 层是 AgentScope 的大脑，但它假设"Agent 实例存在、输入消息有人喂、状态有人存"。Service 层（`agentscope/app/`）补上这三块——把 `Agent` 包装成一个可以被多用户、多会话、多进程并发调用的在线服务。这一层的设计模式和 Core Agent 层完全不同，因为它解决的是分布式系统问题，不是推理问题。

#### MessageBus: Six Primitives Instead of Domain-Specific APIs

`MessageBus` 是整个 Service 层的神经中枢。AgentScope 没有定义 `InboxQueue` / `EventLog` / `WakeupSignal` 这类领域对象，而是把协调需求收敛成**六种消费语义原语**，每个原语对应一种数据生命周期：

| 原语模式 | 语义 | 典型用途 |
| :--- | :--- | :--- |
| **Mode A — drain queue** | 单一消费者、ack-on-read。每条 entry 被一个读者拿走后立即删除 | wakeup trigger queue、session inbox（HintBlock 投递） |
| **Mode C — replay log** | 多消费者、非破坏性读取、`max_len` 或 TTL 限长 | session event log（SSE late-join 补历史） |
| **Mode D — transient broadcast** | fire-and-forget，只有实时订阅者能收到 | wakeup signal、cancel broadcast、schedule lifecycle notify |
| **Mode E — distributed lock** | 集群级互斥，带心跳续租防止进程崩溃死锁 | session run 锁（同一 session 同时只有一个 ChatService.run 在跑） |
| **Mode F — registry map** | hash-keyed namespace，支持 CAS（compare-and-set）和 pop-exactly-once | background task 全局注册表、channel liveness 心跳 |

**设计动机**：把业务语义与传输层解耦。Service 层上层代码只管选原语 + 定义 key 命名约定（`MessageBusKeys` 静态类集中管理所有 key 格式），底层可以换成 Redis / NATS / InMemory 而不触动业务代码。`_base.py` 里那句"Counted broadcast is intentionally not exposed"尤其说明问题——想 fan-out 给 N 个成员？写时 fan-out（每个收件人 inbox push 一条 Mode A），不要让总线维护 consumer group 协调状态。总线保持简单，复杂性留给生产者。

**Mode C 的 replay-then-live 模式**是事件流 gap-free 读取的基础。`open_reply_stream()` 的两阶段读取——先 `log_read(max_count=SESSION_REPLAY_MAX_LEN)` 把最近 1000 条历史拉回来，再进入 `subscribe` 实时模式，用 entry_id 做去重——让消费者可以在 Agent 已经在跑之后才订阅（SSE endpoint 的典型场景），而不会错过任何事件。

#### Deployment Mode: Three Role-Separation Switches

`create_app()` 有三个布尔开关，把 Service 层拆成四种可独立部署的角色：

| 开关 | 关闭后谁接管 | 典型部署 |
| :--- | :--- | :--- |
| `enable_channel_worker=False` | 独立 channel worker 进程 | 每平台一个 bot 长连接，API 副本变成纯无状态 |
| `enable_scheduler=False` | 独立 scheduler owner 节点 | 单 owner 跑 APScheduler（jobstore 内存），其余节点只写 storage |
| `enable_index_worker=False` | 独立 index worker 进程 | API 副本只发布 index task，worker 进程消费并调 Milvus/ES |

**设计动机**：APScheduler 的 jobstore 是内存的——每个持有它的节点都会在 cron tick 时触发任务，多副本部署必然重复执行。Channel 长连接同理——飞书/DingTalk 一个 bot token 只能有一个活跃 WebSocket，每个 API 副本都持有连接要么浪费要么重复。把长连接、定时器、重活从 API 路径剥离出去，API 副本就可以纯粹水平扩展。

**一个值得注意的设计取舍**：三个开关关闭后，对应的 API 端点**仍然可用**——只是它们不做长连接、不持有定时器、不跑索引循环。API 层写 storage → 发 message_bus signal → owner 节点收到 signal 后 reconcile 自己的本地状态。这个 reconcile 模式（`ChannelLifecycleDispatcher.reconcile()` / `SchedulerManager.reconcile()` / IndexSweeper）统一了所有 owner 的状态同步机制。

#### WakeupDispatcher: Single Serial Consumer Per Process

每个进程只有一个 `WakeupDispatcher` asyncio task 消费全局 `wakeup_queue`。这不是效率选择（一条 64 条的 queue 用不上并发），而是**结构性保证**——从消息队列 drain 出来的 trigger 是串行处理的，每个 trigger 在 spawn ChatService.run 之前先 `is_locked(session_lock)` 检查 session 是否在跑，冲突时 backoff 0.1s 重入队。

这种设计让分布式 session 串行化**几乎没有竞争**：
- 正常流程：前一个 run 结束 → 释放 session lock → WakeupDispatcher 下一次 drain 看到 trigger → `try_lock` 成功 → spawn
- 竞态场景：trigger 入队时前一个 run 还没释放 lock → `is_locked` 返回 True → re-enqueue（不会丢）→ 下次 drain 再试

代码注释里写得直白："every run trigger funnels through this one serial consumer, which is what makes concurrent-spawn races structurally impossible"。分布式 lock 是保险，串行消费让锁几乎不会被竞态。

#### Channel Subsystem: Gateway (Data Plane) + Dispatcher (Control Plane) Split

Channel 子系统分成两个完全独立的组件：

**ChannelGateway（data plane，无状态）**：
- `process(event)` 是唯一入口，接收入站消息或确认卡片点击
- 消息路径：`resolve()` 路由 → `is_locked(session_lock)` 判定 → 活跃 session 写 inbox（HintBlock）/ 空闲 session enqueue wakeup
- 确认点击路径：`_resume()` 读 session state 找等待中的 tool_call → 恢复 parked run

**ChannelLifecycleDispatcher（control plane，持有长连接）**：
- 每进程一个，`_instances: dict[channel_id, ChannelInstance]` 持有所有本地长连接
- 两个 loop：`_listen()`（订阅 lifecycle 事件 reconcile）+ `_periodic()`（10s reconcile + heartbeat）
- reconcile 驱动 `_instances` 和 storage 里 enabled records 保持一致

**输出方向完全反向**：Agent 跑完后，事件直接发 message_bus；持有该 channel 长连接的 Dispatcher 通过 `open_reply_stream()` 订阅 session events → 调 channel client 发送 REST。Gateway 只入站，Dispatcher 只持有连接；两者通过 message_bus + storage 间接协作，没有直接调用。

#### Deterministic Channel Routing: uuid5 Session IDs

最精妙的一个设计：**Channel 路由不需要持久化映射表**。给定入站消息，`resolve()` 纯函数算出 `session_id`：

```python
_SESSION_NAMESPACE = uuid5(NAMESPACE_URL, "agentscope.channel.session")

session_id = uuid5(
    _SESSION_NAMESPACE,
    f"{record.id}:{binding.agent_id}:{scope_key}",
)
```

其中 `scope_key` 由 `SessionScope` 决定——`PER_CHAT` 是 chat_id，`PER_CHAT_USER` 是 `chat_id:user_id`。

**这个设计的后果**：
1. **多节点零协调**——任何节点收到同一条消息都会算出同一个 session_id，不需要路由查询
2. **幂等 session 创建**——`ChannelGateway._ensure_session()` 调 `storage.get_session(..., session_id)` 查存在不，不存在才 upsert；同一个 session_id 永远对应同一个 Agent + 同一个 scope
3. **删除安全**——session 被删后，下次同 chat 同 scope 的消息自动重新创建（UUID 稳定，不会 orphan 旧 session）

没有 Redis 映射表，没有 CRDT，没有中心路由服务——一个 uuid5 解决了分布式路由的核心问题。

#### Lifespan Pattern: AsyncExitStack with Reverse-Order Cleanup

整个 Service 层的资源生命周期由 `lifespan()` 中的一个 `AsyncExitStack` 统一管理。`storage → message_bus → workspace_manager → knowledge_base_manager → BlobStore → Hubs → BackgroundTaskManager → ChatRunRegistry → SchedulerManager → channel subsystem → ChatService → SessionService → WakeupDispatcher → CancelDispatcher → ChannelLifecycleDispatcher` 这串 enter 顺序，退出时按**逆序**关闭。

这个设计有两个好处：
1. **部分启动失败不会泄漏资源**——中间某个 `enter_async_context` 抛异常，AsyncExitStack 会自动关闭之前已经 enter 的所有资源
2. **依赖顺序自动正确**——`ChatRunRegistry` 必须在 `WakeupDispatcher` 之前 enter（Dispatcher 依赖 Registry spawn task），而 shutdown 时 Registry 在 Dispatcher 之后退出（Dispatcher 先停收 trigger，再 cancel 所有还在跑的 chat run）。代码里的 enter 顺序就是依赖图的拓扑排序，不需要额外文档

#### Summary: How Service Layer and Core Agent Layer Connect

两层之间的接口极其简单：Service 层不继承 Agent、不包装 Agent、甚至不 import Agent 的内部方法。唯一的接触点是：

1. **运行时装配**：`ChatService._run_impl()` 每次调用时从 storage 读 AgentRecord + SessionRecord → 组装 `Agent` 实例（模型、Toolkit、中间件链都来自 storage 配置 + workspace 派生）
2. **State 传递**：`AgentState` 在 Agent 构造时从 session 的持久化 state 加载；run 结束后写回 storage。Agent 本身不持久化，纯函数式
3. **Event 管道**：Agent 产出的事件流同时发布到 Mode C replay log（持久化）和 Mode D live broadcast（实时订阅），Service 层不拦截也不修改

这个边界设计意味着：Core Agent 层可以独立演进（比如加一个新的 middleware hook、换一种压缩算法），只要不破坏 `Agent.reply_stream()` 和 `AgentState` 的结构，Service 层不需要改一行代码。

## Links

- [Agent 目录](/docs/CS/AI/LLM/Agent/README.md)
- [Agent Theory](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md)
- [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)
- [Codex](/docs/CS/AI/LLM/Agent/Product/Codex.md)
- [DSH](/docs/CS/AI/LLM/Agent/Product/DSH.md)
- [LLM 应用开发框架](/docs/CS/AI/LangTools.md)

## References

- [AgentScope GitHub](https://github.com/agentscope-ai/agentscope)
- [AgentScope 文档](https://docs.agentscope.io/)
- [AgentScope: A Flexible yet Robust Multi-Agent Platform (arxiv 2402.14034)](https://arxiv.org/abs/2402.14034)
- [AgentScope 1.0: A Developer-Centric Framework for Building Agentic Applications (arxiv 2508.16279)](https://arxiv.org/abs/2508.16279)
