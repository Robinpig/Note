## Introduction

中间件是 AgentScope 最值得细看的设计：它把「跨切面的横切逻辑」（预算、追踪、记忆、TTS、权限、提示词改写）全部收拢到 `MiddlewareBase` 的少数几个 hook 里，而不是散落在 `Agent` 主循环。`Agent` 在构造时按 `is_implemented()` 把中间件分派到 7 个列表，运行时沿洋葱链 / 转换器链调用。

本分册覆盖 **MiddlewareBase 的 7 个 hook 与分派机制**、**内置中间件家族**（预算 / TTS / 追踪 / 长期记忆三实现）、以及 **权限 DSL 的完整细节**（5 模式 × 4 行为、rule_content 语义、引擎 6 步判定、bypass_immune 安全 ASK）。Pipeline 与事件机制见 [Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)，应用层见 [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md)。

## MiddlewareBase: Seven Hooks

`MiddlewareBase`（`src/agentscope/middleware/_base.py:13`）定义 7 个 hook，**每个默认实现都 `raise RuntimeError`**——子类只覆盖需要的。运行时 `is_implemented(hook_name)`（`_base.py:55`）用 `base_method is not sub_method` 判断子类是否真的覆盖，构造时据此把中间件分进 7 个列表。

### Two Patterns

**Onion Pattern（6 个，有 before/after 语义）**——签名统一是 `async def on_xxx(self, agent, input_kwargs, next_handler)`，在 `next_handler(**input_kwargs)` 的 `async for` 前后插入逻辑：

| Hook | 拦截点 | 说明 |
| :--- | :--- | :--- |
| `on_reply` | 整个 reply 循环 | 可**吞掉 `ReplyEndEvent` 逼 Agent 多跑一轮**（不 yield 它，直到最终 `Msg` 逃出整条链才产出）；`_receive_reply_end` 标志防套娃；`INTERRUPTED` 的 end 不能被吞 |
| `on_reasoning` | 模型调用前后 | `input_kwargs` 含 `tool_choice` |
| `on_check_permission` | 单次工具调用的权限判定 | 可 `next_handler` 委托、替换、或不委托直接返回决策；拿到的是 `tool_call`/`tool`/`tool_input` 的**副本**，改副本不影响实际调用 |
| `on_acting` | 单个工具执行的纯 I/O 层 | **只包 `toolkit.call_tool`**；权限检查、输入校验、context 写入都在它外面，故可安全 offload 到后台任务（但 `is_state_injected=True` 的工具会并发改 state，需自护） |
| `on_model_call` | 底层模型 API 调用 | `input_kwargs` 含 `messages`/`tools`/`tool_choice`/`current_model`；返回 `ChatResponse` 或 `AsyncGenerator[ChatResponse]` |
| `on_compress_context` | 上下文压缩 | `input_kwargs` 含 `context_config`/`instructions` |

**Transformer Pattern（1 个，串行管道）**——`on_system_prompt(self, agent, current_prompt) -> str`（`_base.py:264`）：每个中间件拿上一个的输出当输入，依次改写 system prompt 字符串。

另外还有两个可选方法：`list_tools() -> list[ToolBase]`（默认 `[]`，中间件可向外暴露工具）和 `get_middleware_key() -> str`（默认类名，用于在 `AgentState.middle_context` 里存状态）。

## Concrete Middleware Family

### ReplyBudgetControlMiddleware

`src/agentscope/middleware/_budget.py:21`——按 reply 强制加权 token 预算：

```python
cost = input_token_weight * input_tokens + output_token_weight * output_tokens
```

- **状态全在 `agent.state.middle_context[middleware_key][reply_id]`**，实例本身无状态——所以同一中间件实例可安全共享给多个 Agent，且状态能跨 HITL 中断/恢复存活（`_budget.py:35-44`）。
- `on_reply`（`_budget.py:98`）：`ReplyStartEvent` 初始化计数器、`ModelCallEndEvent` 累加（数据来自 `ModelCallEndEvent` 的四个 token 字段）、`ReplyEndEvent` 清理。
- `on_reasoning`（`_budget.py:150`）：累计成本 ≥ `token_budget` 时，往末尾 assistant 消息 append 一条 `HintBlock`（提示「立刻收尾、不要再调工具」），并强制 `input_kwargs["tool_choice"] = ToolChoice(mode="none")`。

### TTSMiddleware

`src/agentscope/middleware/_tts_middleware.py`——文本转语音，两套路径：

- **非实时**：`TextBlockEnd` 触发 `synthesize`，整段合成后回传。
- **实时**：`TextBlockDelta` 触发 `push`，增量合成并推流；音频分片是 base64 PCM，沿用「先 decode 存 bytes、再一次性 encode」的 base64 拼接陷阱（见 [Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)）。

### TracingMiddleware

`src/agentscope/middleware/_tracing/_setup.py` + `_trace.py`——基于 OpenTelemetry，实现 `on_reply` / `on_model_call` / `on_acting`：

- `_check_tracing_enabled`：未配置 tracer 时近乎零开销短路。
- reply span 作为下游 span 的 parent，但**不跨 `yield` 持有 current OTel context**（注释写明原因：`async generator` 可能被另一个 asyncio task 关闭，见 issue **#2076**，`_trace.py:165-171`）。
- 为外部执行的工具合成 `execute_tool` span（`_trace.py:173-195`），记录 HITL / external pending 状态。

### Long-Term Memory: Three Implementations

三者都实现 `on_system_prompt`（改写提示词暴露/隐藏工具）与 `on_reply`/`on_reasoning`（启动异步检索、注入结果），差异在「记忆存哪、谁写、暴露什么工具」：

| 中间件 | 后端 | 暴露工具 | 谁写回 | 隔离 |
| :--- | :--- | :--- | :--- | :--- |
| `AgenticMemoryMiddleware` | 文件系统 Markdown + `MEMORY.md` 索引 | **无记忆工具**（Agent 用 `Write` 自我管理） | Agent 自己 | 目录 |
| `Mem0Middleware` | mem0（OSS / Platform 双路，AgentScope chat+embedding 适配器） | `search_memory` + `add_memory`（`agent_control`/`both` 模式） | `_async_add_with_fallback` 两级回退 | mem0 后端 |
| `ReMeMiddleware` | 进程内嵌入 ReMe 应用（`_build_app` 懒加载） | `memory_search`（`agent_control`/`both`） | **所有 mode 自动写回**（`auto_memory`，无 add 工具） | 按 `agent.state.session_id` |

- `Mem0Middleware`（`_mem0/_middleware.py:86`）：`mode: Literal["static_control","agent_control","both"] = "both"`；纯 `agent_control` 时 `on_reply` 是 no-op（`_mem0/_middleware.py:294`）；`list_tools()` 在非 `static_control` 模式返回工具（`_mem0/_middleware.py:401`）。
- `ReMeMiddleware`（`_reme/_middleware.py:88`）：模型在构造时固定（不取自 agent），按 `session_id` 隔离；`mode` 只决定「是否暴露 `memory_search` 工具」，而「每轮回复后写回」在所有 mode 都发生（`_reme/_middleware.py:15-17`）。
- `AgenticMemoryMiddleware`（`_agentic_memory/_middleware.py:359`）：`on_system_prompt` 追加指令 + 有界 `MEMORY.md`，`on_reply` 起异步检索，`on_reasoning` 注入 hint；4 类 frontmatter（`user`/`feedback`/`project`/`reference`）；**没有记忆工具**，Agent 用 `Write` 主动管理自己的记忆文件。

### Custom Middleware

`MiddlewareBase` 的每个 hook 默认实现都 `raise RuntimeError`，子类只覆盖需要的——构造时 `is_implemented(hook_name)` 用 `base_method is not sub_method` 探测，把中间件分派进 7 个列表。两种模式各给一个最小实现：

```python
from agentscope.middleware import MiddlewareBase
from agentscope.agent import Agent

# 1. 洋葱模式：on_reply / on_reasoning 等在 next_handler() 前后插入逻辑
class LoggingMiddleware(MiddlewareBase):
    async def on_reasoning(self, agent, input_kwargs, next_handler):
        print(f"[before reasoning] {agent.name}")
        async for event in next_handler():
            yield event
        print(f"[after reasoning] {agent.name}")

# 2. 转换器模式：on_system_prompt 拿上一个输出当输入，改写 system prompt
class DateStampMiddleware(MiddlewareBase):
    def on_system_prompt(self, agent, current_prompt: str) -> str:
        from datetime import date
        return f"{current_prompt}\n\n今天的日期是 {date.today().isoformat()}。"

agent = Agent(
    name="a", system_prompt="你是助手。", model=...,
    middlewares=[LoggingMiddleware(), DateStampMiddleware()],
)
```

两个落点：① `on_reply` 是唯一能**吞掉 `ReplyEndEvent` 逼 Agent 多跑一轮**的 hook——只要不 yield 它、直到最终 `Msg` 逃出整条链才产出；但 `INTERRUPTED` 的 end 不能被吞（见 `ReplyBudgetControlMiddleware` 的 `on_reply` 用法）；② `on_system_prompt` 是串行管道，多个中间件依次改写同一字符串，所以是给 system prompt 注入「日期 / 角色约束 / 记忆指令」的标准位置——三个长期记忆中间件都靠它暴露/隐藏工具。自定义中间件与内置中间件地位相同，都经 `is_implemented` 分派，没有优先级冲突问题。

## Permission DSL

权限系统与 Agent 主循环解耦，由 `PermissionEngine` + `PermissionRule` + `PermissionDecision` + `PermissionContext` 四个类组成（均在 `src/agentscope/permission/`）。

### Mode and Behavior

- **`PermissionMode`**（`_types.py`）：`DEFAULT` / `ACCEPT_EDITS` / `EXPLORE` / `BYPASS` / `DONT_ASK` 五值，覆盖从最严格到最宽松的完整光谱。
- **`PermissionBehavior`**（`_decision.py`）：`ALLOW` / `DENY` / `ASK` / `PASSTHROUGH` 四值。

### Rule and Its Content Semantics

`PermissionRule`（`_rule.py`）：`tool_name` / `rule_content` / `behavior` / `source`。**`rule_content` 的语义随工具类型变化**（由 `tool.match_rule` 决定，引擎只做分发）：

- `Bash`：命令**子串 / 前缀通配**匹配（如 `git:*`）。
- `Write` / `Read` / `Edit`：**glob** 匹配文件路径。
- 其它工具：通用模式匹配（或仅工具名级别）。

`Engine.add_rule`（`_engine.py:49`）按 behavior 把规则分桶进 `allow_rules` / `deny_rules` / `ask_rules`（都按 `tool.name` 建字典）。

### Context

`PermissionContext`（`_context.py`）：`mode` / `working_directories` / `allow_rules` / `deny_rules` / `ask_rules`（按 tool name 分桶）。

### Decision

`PermissionDecision`（`_decision.py`）：`behavior` / `message` / `decision_reason` / `updated_input` / `suggested_rules` / **`bypass_immune: bool = False`**。`bypass_immune` 是安全 ASK 的关键开关。

### Engine: Dispatch and Per-Mode Evaluation

`PermissionEngine.check_permission`（`_engine.py:77`）按 `mode` 分发到 `_check_<mode>`。以 `_check_default`（`_engine.py:117`）为基准，六步优先级链：

```
1. Deny rules        → DENY
2. Ask rules         → ASK（附 suggested_rules）
3. Read-only fast path → ALLOW（_check_read_only_fast_path，全 mode 共享）
4. tool.check_permissions:
     ALLOW / DENY      → 原样返回
     safety ASK（bypass_immune）→ 原样返回（allow rules 无法覆盖）
     non-safety ASK / PASSTHROUGH → 继续
5. Allow rules       → ALLOW
6. Mode fallback     → ASK（附 suggested_rules）
```

各 mode 的差异（全部确认自 `_engine.py`）：

| Mode | 第 4 步是否查 tool | 第 5 步 allow rules | 第 6 步 fallback |
| :--- | :--- | :--- | :--- |
| `DEFAULT` | 查（safety ASK 免疫） | 查 | ASK |
| `EXPLORE` | **不查**（只读保证不可被规则让出） | **不查** | **DENY**（修改一律拒） |
| `ACCEPT_EDITS` | 查（工作目录内编辑由 tool 自 ALLOW） | 查 | ASK |
| `BYPASS` | 查，但**任何 ASK（含 bypass-immune 安全 ASK）都跳过** | 查 | **ALLOW** |
| `DONT_ASK` | 查；safety ASK → DENY | 查 | **DENY**（不变量：永不返回 ASK） |

### Three Key Designs

1. **Safety ASK（`bypass_immune`）**——工具自己返回的 ASK 可标 `bypass_immune=True`。`_is_safety_ask`（`_engine.py:633`）判定 `behavior==ASK and bypass_immune`。在 `DEFAULT`/`ACCEPT_EDITS` 下它**无法被 allow rule 覆盖**（典型：`Bash("rm -rf /")` 即使用户加了 `Bash:*` 允许规则仍弹确认）。`BYPASS` 主动跳过安全 ASK（「完全信任用户」），`DONT_ASK` 用 `_convert_ask_to_deny`（`_engine.py:593`）把 ASK 转 DENY 并保留 `suggested_rules` 供后续排查。

2. **`suggested_rules`**——每次 ASK 都经 `_generate_suggestions`（`_engine.py:812`）委托 `tool.generate_suggestions`：Bash 提取命令前缀（如 `npm run:*`）、文件操作提取目录 glob（`src/**`）、其它生成精确匹配。用户一键添加后下次同类调用自动放行。

3. **`read_only` fast path**——`_check_read_only_fast_path`（`_engine.py:659`）抽成**单一共享 helper**，保证五个 mode 对只读调用的处理永不漂移（这正是历史 bug 的来源：曾出现 `DEFAULT`/`DONT_ASK` 缺 fast path 而 `ACCEPT_EDITS`/`EXPLORE` 有的不一致）。

## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)
- [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md)
- [权限理论](/docs/CS/AI/LLM/Agent/Theory/Permission.md)

## References

- `src/agentscope/middleware/_base.py`
- `src/agentscope/middleware/_budget.py`
- `src/agentscope/middleware/_tracing/_trace.py`
- `src/agentscope/middleware/_longterm_memory/`（`_agentic_memory` / `_mem0` / `_reme`）
- `src/agentscope/permission/_engine.py` / `_rule.py` / `_decision.py` / `_context.py` / `_types.py`
