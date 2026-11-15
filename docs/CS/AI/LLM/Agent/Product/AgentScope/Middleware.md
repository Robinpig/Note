## Introduction

中间件是 AgentScope 最值得细看的设计：它把「跨切面的横切逻辑」（预算、追踪、记忆、TTS、权限、提示词改写）全部收拢到 `MiddlewareBase` 的少数几个 hook 里，而不是散落在 `Agent` 主循环。`Agent` 在构造时按 `is_implemented()` 把中间件分派到 7 个列表，运行时沿洋葱链 / 转换器链调用。

本分册覆盖 **MiddlewareBase 的 7 个 hook 与分派机制**、**内置中间件家族**（预算 / TTS / 追踪 / 长期记忆三实现 / v2.0.9 新增的模型路由）、以及 **权限 DSL 的完整细节**（5 模式 × 4 行为、rule_content 语义、引擎 6 步判定、bypass_immune 安全 ASK）。Pipeline 与事件机制见 [Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)，应用层见 [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md)。

## MiddlewareBase: Seven Hooks

`MiddlewareBase`（`src/agentscope/middleware/_base.py`）定义 7 个 hook，**每个默认实现都 `raise RuntimeError`**——子类只覆盖需要的。类 docstring 把 6 个 onion hook 与 1 个 transformer hook 列全：

```python
class MiddlewareBase:  # pylint: disable=unused-argument
    """Base class for all middleware implementations.

    Middleware provides interception mechanisms at 7 key execution points
    in the Agent lifecycle:

    **Onion Pattern Hooks** (with before/after logic):
    - `on_reply`: Intercepts the entire reply process
    - `on_reasoning`: Intercepts the reasoning/model call phase
    - `on_check_permission`: Intercepts permission checking for a tool call
    - `on_acting`: Intercepts individual tool call execution
    - `on_model_call`: Intercepts the raw model API call
    - `on_compress_context`: Intercepts context compression

    **Transformer Pattern Hook** (sequential pipeline):
    - `on_system_prompt`: Transforms the system prompt string
```

运行时 `is_implemented(hook_name)` 用 `base_method is not sub_method` 判断子类是否真的覆盖，构造时据此把中间件分进 7 个列表。真实实现：

```python
    def is_implemented(self, hook_name: str) -> bool:
        """Check if a hook method is implemented in the subclass.

        Args:
            hook_name: Name of the hook method to check

        Returns:
            True if the hook is implemented (overridden), False otherwise
        """
        base_method = getattr(MiddlewareBase, hook_name, None)
        sub_method = getattr(type(self), hook_name, None)
        return base_method is not sub_method
```

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

**Transformer Pattern（1 个，串行管道）**——`on_system_prompt(self, agent, current_prompt) -> str`：每个中间件拿上一个的输出当输入，依次改写 system prompt 字符串。

另外还有两个可选方法：`list_tools() -> list[ToolBase]`（默认 `[]`，中间件可向外暴露工具）和 `get_middleware_key() -> str`（默认类名，用于在 `AgentState.middle_context` 里存状态）。二者的真实定义：

```python
    async def list_tools(self) -> list[ToolBase]:
        """List available tools provided by this middleware. Optional to
        implement.

        Returns:
            `list[ToolBase]`:
                A list of tools provided by this middleware.
        """
        return []

    async def get_middleware_key(self) -> str:
        """Get the unique key for this middleware, used to save middleware
        states in `AgentState` instances.

        Optionally, middleware classes can override this method to
        provide their own unique key.
        """
        return self.__class__.__name__
```

## Concrete Middleware Family

### ModelRouterMiddleware

`middleware/_model_router.py`（注意在 `agentscope.middleware` 而非 `app/middleware/`）是 v2.0.9 起新增的中间件，把 `classifier/` 的概率化决策接进 Agent。构造时校验 `ChatModelCandidate` 名唯一，并备一份 enum JSON schema 作兜底；`on_reply` 先存 `original_model`，在 `ReplyStartEvent` 时调 `_route()` 把决策写进 `agent.state.middle_context[key][reply_id]`，`finally` 每次都还原 `agent.model`。分类异常或未知候选则记 warning、保持原模型。所谓「HITL 恢复后路由不变」靠的是按 `reply_id` 读回旧决策**重新替换**，而不是模型对象没被换回去。完整展开见 Classifier 分册。`on_reply` 的真实源码把「存原模型 / 按 reply_id 读回 / finally 还原」写在一起：

```python
        key = await self.get_middleware_key()
        original_model = agent.model
        # Before ReplyStartEvent, reply_id still names the previous reply
        new_reply = isinstance(input_kwargs["inputs"], (Msg, list))
        routed = agent.state.middle_context.get(key, {})
        agent.model = self._models.get(
            None if new_reply else routed.get(agent.state.reply_id),
            original_model,
        )
        try:
            async for event in next_handler(**input_kwargs):
                if isinstance(event, ReplyStartEvent):
                    name = await self._route(
                        self._latest_user_text(input_kwargs["inputs"]),
                    )
                    agent.state.middle_context[key] = {event.reply_id: name}
                    agent.model = self._models.get(name, original_model)
                yield event
        finally:
            agent.model = original_model
```

它和服务层 `app/middleware/_sop_step_middleware.py` 的 `SOPStepSubmitMiddleware` 是两类不同的硬约束中间件：前者改模型选择，后者吞 `ReplyEndEvent` 逼 Agent 交卷，见 SOP 分册。两者都**没有新增 hook**——`MiddlewareBase` 的 7 个 hook 从 v2.0.8 到 v2.0.11 零改动。

### ReplyBudgetControlMiddleware

`src/agentscope/middleware/_budget.py`——按 reply 强制加权 token 预算，加权公式是 `cost = input_token_weight * input_tokens + output_token_weight * output_tokens`。下面的 `on_reply` 真实源码既做累加，也把状态挂在 `middle_context[middleware_key][reply_id]`：

```python
        middleware_key = await self.get_middleware_key()

        async for event in next_handler(**input_kwargs):
            if isinstance(event, ReplyStartEvent):
                # Start counting for this reply, dropping the previous one.
                # Not cleaned on ReplyEndEvent: an outer middleware may
                # swallow it and the same reply then keeps spending tokens
                agent.state.middle_context[middleware_key] = {
                    event.reply_id: 0,
                }

            elif isinstance(event, ModelCallEndEvent):
                # Update the used tokens
                agent.state.middle_context[middleware_key][event.reply_id] += (
                    self.input_token_weight * event.input_tokens
                    + self.output_token_weight * event.output_tokens
                )

            yield event
```

- **状态全在 `agent.state.middle_context[middleware_key][reply_id]`**，实例本身无状态——所以同一中间件实例可安全共享给多个 Agent，且状态能跨 HITL 中断/恢复存活。
- `on_reply`：`ReplyStartEvent` 初始化计数器、`ModelCallEndEvent` 累加（数据来自 `ModelCallEndEvent` 的四个 token 字段）、`ReplyEndEvent` 清理。
- `on_reasoning`：累计成本 ≥ `token_budget` 时，往末尾 assistant 消息 append 一条 `HintBlock`（提示「立刻收尾、不要再调工具」），并强制 `input_kwargs["tool_choice"] = ToolChoice(mode="none")`。其 docstring 原话：

```python
        Before forwarding to the next handler, reads the accumulated weighted
        cost for the current reply from ``agent.state.middle_context``. If the
        budget is exhausted, appends a
        :class:`~agentscope.message.HintBlock` to the last assistant message
        in context (or creates a new
        :class:`~agentscope.message.AssistantMsg`) and overrides
        ``tool_choice`` to ``ToolChoice(mode="none")``, or, while a
        structured output is still owed, restricts it to the structured
        output tool.
```

### TTSMiddleware

`src/agentscope/middleware/_tts_middleware.py`——文本转语音，两套路径：

- **非实时**：`TextBlockEnd` 触发 `synthesize`，整段合成后回传。
- **实时**：`TextBlockDelta` 触发 `push`，增量合成并推流；音频分片是 base64 PCM，沿用 decode→concat→re-encode 的分片合并规则（v2.0.11 按 `block_id` 定位同 id 分片）（见 [Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)）。

### TracingMiddleware

`src/agentscope/middleware/_tracing/_setup.py` + `_trace.py`——基于 OpenTelemetry，实现 `on_reply` / `on_model_call` / `on_acting`：

- `_check_tracing_enabled`：未配置 tracer 时近乎零开销短路。
- reply span 作为下游 span 的 parent，但**不跨 `yield` 持有 current OTel context**（注释写明原因：`async generator` 可能被另一个 asyncio task 关闭，见 issue **#2076**）。
- 为外部执行的工具合成 `execute_tool` span，记录 HITL / external pending 状态。

### Long-Term Memory: Three Implementations

三者都实现 `on_system_prompt`，但**只有 Agentic 与 ReMe 实现 `on_reasoning`**：Mem0 没有该 hook，它在 `on_reply` 里同步 `await` 检索、在 `ReplyStartEvent` 时注入。而且真正决定工具是否暴露的是 `list_tools()`，不是提示词。

> 记忆的完整分层（短期压缩 / 长期中间件 / 服务层持久化）、hook 矩阵与纠偏已拆到 [Memory 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)，本节只保留中间件侧的定位。三者差异在「记忆存哪、谁写、暴露什么工具」：

| 中间件 | 后端 | 暴露工具 | 谁写回 | 隔离 |
| :--- | :--- | :--- | :--- | :--- |
| `AgenticMemoryMiddleware` | 文件系统 Markdown + `MEMORY.md` 索引 | **无记忆工具**（Agent 用 `Write` 自我管理） | Agent 自己 | 目录 |
| `Mem0Middleware` | mem0（OSS / Platform 双路，AgentScope chat+embedding 适配器） | `search_memory` + `add_memory`（`agent_control`/`both` 模式） | `_async_add_with_fallback` 两级回退 | mem0 后端 |
| `ReMeMiddleware` | 进程内嵌入 ReMe 应用（`_build_app` 懒加载） | `memory_search`（`agent_control`/`both`） | **所有 mode 自动写回**（`auto_memory`，无 add 工具） | 按 `agent.state.session_id` |

- `Mem0Middleware`：`mode: Literal["static_control","agent_control","both"] = "both"` 的默认值；纯 `agent_control` 时 `on_reply` 透传（旧笔记写的一条断言只是注释）；`list_tools()` 在非 `static_control` 模式返回工具。`_async_add_with_fallback` 的两级回退（`infer=True` → 空则 `infer=False`）**只服务 `add_memory` 工具**；每轮自动写回走 `_dispatch_write` → `_async_add`，没有回退。隔离键是 `user_id` + 可选 `agent_id`，**没有 `run_id`**。
- `ReMeMiddleware`：模型在构造时固定（注释明写 never taken from an agent），按 `session_id` 分桶；`mode` 只决定「是否暴露 `memory_search` 工具」，而「每轮回复后写回」由 `_AUTO_MEMORY_JOB` 在 `on_reply` 的 `finally` 里**所有 mode** 无条件触发，写回的是本轮增量，没有 add 工具。
- `AgenticMemoryMiddleware`：`on_system_prompt` 追加指令 + 有界 `MEMORY.md`，`on_reply` 起异步检索，`on_reasoning` 注入 hint；**没有记忆工具**，Agent 用 `Write` 主动管理记忆文件（`DEFAULT_MEMORY_INSTRUCTIONS`）。所谓「检索」其实是 **LLM 选文件**（`generate_structured_output`），无向量、无 BM25；4 类 frontmatter `type` 只是提示词规范，运行时唯一作用是 manifest 的 `[type]` 前缀。

`MEMORY.md` 是有界索引（`FILENAME_MEMORY_MD`；默认 `memory_max_tokens=4000`），超限时 `_truncate_if_needed` 按前缀切并追加 `<<<TRUNCATED>>>` + `Read offset` 提示。`Parameters` 共 **8 个字段**：除 `retrieval_async=True` / `retrieval_max_files=200` / `retrieval_max_tokens_per_md=2000` / `retrieval_max_tokens_per_frontmatter=256` 外，还有 `memory_instructions` / `retrieval_model` / `retrieval_instructions`；构造还需必填 `workdir`，`backend` 接受 `BackendBase`，默认 `LocalBackend()`。

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

- **`PermissionMode`**（`_types.py`）：`DEFAULT` / `ACCEPT_EDITS` / `EXPLORE` / `BYPASS` / `DONT_ASK` 五值，覆盖从最严格到最宽松的完整光谱。真实枚举值：

```python
    DEFAULT = "default"
    ACCEPT_EDITS = "accept_edits"
    EXPLORE = "explore"
    BYPASS = "bypass"
    DONT_ASK = "dont_ask"
```

- **`PermissionBehavior`**（`_decision.py`）：`ALLOW` / `DENY` / `ASK` / `PASSTHROUGH` 四值。真实枚举值：

```python
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    PASSTHROUGH = "passthrough"
```

### Rule and Its Content Semantics

`PermissionRule`（`_rule.py`）：`tool_name` / `rule_content` / `behavior` / `source`。**`rule_content` 的语义随工具类型变化**（由 `tool.match_rule` 决定，引擎只做分发）：

- `Bash`：命令**子串 / 前缀通配**匹配（如 `git:*`）。
- `Write` / `Read` / `Edit`：**glob** 匹配文件路径。
- 其它工具：通用模式匹配（或仅工具名级别）。

`Engine.add_rule` 按 behavior 把规则分桶进 `allow_rules` / `deny_rules` / `ask_rules`（都按 `tool.name` 建字典）。真实实现：

```python
        if rule.behavior == PermissionBehavior.ALLOW:
            if rule.tool_name not in self.context.allow_rules:
                self.context.allow_rules[rule.tool_name] = []
            self.context.allow_rules[rule.tool_name].append(rule)
        elif rule.behavior == PermissionBehavior.DENY:
            if rule.tool_name not in self.context.deny_rules:
                self.context.deny_rules[rule.tool_name] = []
            self.context.deny_rules[rule.tool_name].append(rule)
        elif rule.behavior == PermissionBehavior.ASK:
            if rule.tool_name not in self.context.ask_rules:
                self.context.ask_rules[rule.tool_name] = []
            self.context.ask_rules[rule.tool_name].append(rule)
```

### Context

`PermissionContext`（`_context.py`）：`mode` / `working_directories` / `allow_rules` / `deny_rules` / `ask_rules`（按 tool name 分桶）。真实字段定义：

```python
    mode: PermissionMode = PermissionMode.DEFAULT
    """The current permission mode."""

    working_directories: dict[str, AdditionalWorkingDirectory] = Field(
        default_factory=dict,
    )
    """Additional directories allowed for file operations, keyed by path."""

    allow_rules: dict[str, list[PermissionRule]] = Field(default_factory=dict)
    """Rules that allow tool execution, keyed by tool name."""

    deny_rules: dict[str, list[PermissionRule]] = Field(default_factory=dict)
    """Rules that deny tool execution, keyed by tool name."""

    ask_rules: dict[str, list[PermissionRule]] = Field(default_factory=dict)
    """Rules that require user confirmation, keyed by tool name."""
```

### Decision

`PermissionDecision`（`_decision.py`）：`behavior` / `message` / `decision_reason` / `updated_input` / `suggested_rules` / **`bypass_immune: bool = False`**。`bypass_immune` 是安全 ASK 的关键开关。真实字段：

```python
    behavior: PermissionBehavior
    """The permission behavior decision."""

    message: str
    """Human-readable message describing the decision."""

    decision_reason: str | None = None
    """Optional explanation for why this decision was made."""

    updated_input: dict[str, Any] | None = None
    """Optional modified input data (e.g., sanitized paths)."""

    suggested_rules: list[PermissionRule] | None = None
    """Optional list of suggested permission rules for user to apply."""

    bypass_immune: bool = False
```

### Engine: Dispatch and Per-Mode Evaluation

`PermissionEngine.check_permission` 按 `mode` 分发到 `_check_<mode>`。真实分发：

```python
        mode = self.context.mode
        if mode == PermissionMode.DEFAULT:
            return await self._check_default(tool, tool_input)
        if mode == PermissionMode.EXPLORE:
            return await self._check_explore(tool, tool_input)
        if mode == PermissionMode.ACCEPT_EDITS:
            return await self._check_accept_edits(tool, tool_input)
        if mode == PermissionMode.BYPASS:
            return await self._check_bypass(tool, tool_input)
        if mode == PermissionMode.DONT_ASK:
            return await self._check_dont_ask(tool, tool_input)
        raise ValueError(f"Unknown permission mode: {mode}")
```

以 `_check_default` 为基准，六步优先级链在其 docstring 里写死：

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

`_check_default` docstring 里的原始六步：

```python
        1. Deny rules → DENY
        2. Ask rules → ASK (with suggestions)
        3. Read-only fast path → ALLOW
        4. ``tool.check_permissions``:
            - ALLOW / DENY → returned as-is
            - Safety ASK (bypass-immune) → returned with suggestions; cannot
              be overridden by allow rules
            - Non-safety ASK / PASSTHROUGH → continue
        5. Allow rules → ALLOW
        6. Default → ASK (with suggestions)
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

1. **Safety ASK（`bypass_immune`）**——工具自己返回的 ASK 可标 `bypass_immune=True`。`_is_safety_ask` 判定 `behavior==ASK and bypass_immune`，真实 return：

```python
        return (
            decision.behavior == PermissionBehavior.ASK
            and decision.bypass_immune
        )
```

在 `DEFAULT`/`ACCEPT_EDITS` 下它**无法被 allow rule 覆盖**（典型：`Bash("rm -rf /")` 即使用户加了 `Bash:*` 允许规则仍弹确认）。`BYPASS` 主动跳过安全 ASK（「完全信任用户」），`DONT_ASK` 用 `_convert_ask_to_deny` 把 ASK 转 DENY 并保留 `suggested_rules` 供后续排查，其真实 return：

```python
        return PermissionDecision(
            behavior=PermissionBehavior.DENY,
            message=(
                f"Permission denied for {tool.name} "
                f"(dont_ask mode - ASK converted to DENY, "
                f"user not available)"
            ),
            decision_reason=(
                f"DONT_ASK mode converted ASK to DENY. "
                f"Original reason: {ask_decision.decision_reason}"
            ),
            suggested_rules=ask_decision.suggested_rules,
        )
```

2. **`suggested_rules`**——每次 ASK 都经 `_generate_suggestions` 委托 `tool.generate_suggestions`：Bash 提取命令前缀（如 `npm run:*`）、文件操作提取目录 glob（`src/**`）、其它生成精确匹配。用户一键添加后下次同类调用自动放行。

3. **`read_only` fast path**——`_check_read_only_fast_path` 抽成**单一共享 helper**，保证五个 mode 对只读调用的处理永不漂移。docstring 写明这正是历史 bug 的来源：

```python
        """Read-only fast path shared by every mode.

        A read-only invocation has no side effects, so it is auto-allowed
        in every :class:`PermissionMode`. Keeping this in a single helper
        (rather than re-inlining it per mode) guarantees the modes cannot
        drift apart on read-only handling — the exact divergence that
        previously left ``DEFAULT`` and ``DONT_ASK`` without a read-only
        fast path while ``ACCEPT_EDITS`` / ``EXPLORE`` had one.
```

### Onion Construction: execute_chain

`Agent.__init__` 在构造时按 `is_implemented()` 把中间件分进 7 个列表：`_reply_middlewares` / `_reasoning_middlewares` / `_check_permission_middlewares` / `_acting_middlewares` / `_model_call_middlewares` / `_system_prompt_middlewares` / `_compress_context_middlewares`。真实源码：

```python
        # ====================================================================
        # Filter middlewares by implemented hooks (only once)
        middlewares = middlewares or []
        self._reply_middlewares = [
            _ for _ in middlewares if _.is_implemented("on_reply")
        ]
        self._reasoning_middlewares = [
            _ for _ in middlewares if _.is_implemented("on_reasoning")
        ]
        self._check_permission_middlewares = [
            _ for _ in middlewares if _.is_implemented("on_check_permission")
        ]
        self._acting_middlewares = [
            _ for _ in middlewares if _.is_implemented("on_acting")
        ]
        self._model_call_middlewares = [
            _ for _ in middlewares if _.is_implemented("on_model_call")
        ]
        self._system_prompt_middlewares = [
            _ for _ in middlewares if _.is_implemented("on_system_prompt")
        ]
        self._compress_context_middlewares = [
            _ for _ in middlewares if _.is_implemented("on_compress_context")
        ]

        # Set when a `ReplyEndEvent` escapes the reply middleware chain; the
        # reply loop only exits after the event is delivered (not swallowed)
        self._receive_reply_end: bool = False
```

六个 onion hook 各自在对应的 Agent 方法里**就地构造一个 `execute_chain` 递归函数**——不是一个统一的调度器，而是每处嵌套定义。以 `on_acting` 为例：`execute_chain(index)` 递归，`index >= len(middlewares)` 时调用 `_acting_impl` 收尾，否则取 `self._acting_middlewares[index]`，把 `input_kwargs` 交给 `mw.on_acting(agent=self, input_kwargs=..., next_handler=...)`，而 `next_handler` 内部再 `execute_chain(index+1, ...)`。这写法与 Koa/Express 洋葱模型完全一致——`next_handler(**)` 被调用前是「before」，await 其后 yield 是「after」。`on_model_call` 返回 `ChatResponse` 或 async-generator、`on_compress_context` 返回 `None`、`on_reply` 同理，只是收尾调用与返回类型不同。`agent/_agent.py` 里 `on_acting` 的递归定义（下面这段之后紧接着把 `next_handler` 作为关键字参数传给 `mw.on_acting(...)`）：

```python
            async def execute_chain(
                index: int = 0,
                tool_call: ToolCallBlock = tool_call,
            ) -> AsyncGenerator:
                if index >= len(self._acting_middlewares):
                    async for item in self._acting_impl(tool_call):
                        yield item
                else:
                    mw = self._acting_middlewares[index]
                    input_kwargs = {"tool_call": tool_call}

                    async def next_handler(**kwargs: Any) -> AsyncGenerator:
                        async for item in execute_chain(
                            index + 1,
                            **{**input_kwargs, **kwargs},
                        ):
                            yield item

                    async for item in mw.on_acting(
                        agent=self,
                        input_kwargs=input_kwargs,
```

唯一的 transformer——`on_system_prompt`——不走递归，而是 `Agent._get_system_prompt` 里一段顺序循环：`for mw in self._system_prompt_middlewares: result = await mw.on_system_prompt(self, result)`，每个中间件拿上一次的输出当输入。真实源码：

```python
        result = "\n".join(prompt)

        # Apply system_prompt middlewares sequentially (transformer pattern)
        for mw in self._system_prompt_middlewares:
            result = await mw.on_system_prompt(self, result)

        return result
```

### TTSMiddleware: Audio Event Injection

`TTSMiddleware`（`src/agentscope/middleware/_tts_middleware.py`）只在 `on_reply` 拦截，把推理产出的文本块合成语音并注入 `DATA_BLOCK_*` 音频事件。它累积 `TextBlockDeltaEvent` 里的增量文本，分两路：

- **实时**（`tts.realtime=True`）：每个 delta 立即 `tts.push(delta)`，产出音频增量马上 emit。
- **非实时**：在 `TextBlockEndEvent` 时，整段 `text_buffer` 调 `tts.synthesize(text)` 一次性合成。

实时分支的真实源码：

```python
                if isinstance(evt, TextBlockDeltaEvent):
                    text_buffer += evt.delta
                    if self.tts.realtime and evt.delta:
                        tts_res = await self.tts.push(evt.delta)
                        async for audio_evt in self._emit_chunk(
                            agent,
                            tts_res,
                            audio_block_id,
                            audio_media_type,
                        ):
                            if isinstance(audio_evt, DataBlockStartEvent):
                                audio_block_id = audio_evt.block_id
                                audio_media_type = audio_evt.media_type
                            yield audio_evt
```

每段音频由一个稳定的 `audio_block_id` 串起：`_emit_chunk` 在首个 chunk 时 yield `DataBlockStartEvent`、之后每个 chunk yield `DataBlockDeltaEvent`，`DataBlockDeltaEvent.data` 是**增量** base64 PCM，整段音频 = 所有 delta 解码后按 `block_id` 拼接。`on_reply` 在 `TextBlockEndEvent` 收尾时补 `DataBlockEndEvent` 并重置 `audio_block_id`。这正是 AgentScope 流式 DataBlock 分片合并规则的又一处实例（见 [Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)）。

### TracingMiddleware: Span Mechanics

`TracingMiddleware`（`src/agentscope/middleware/_tracing/_trace.py`）基于 OpenTelemetry，实现 `on_reply` / `on_model_call` / `on_acting`。tracer 由 `_get_tracer()`（`_tracing/_setup.py`）以 name `"agentscope"` + 包版本创建，未配置 tracer 时近乎零开销短路。

reply span 作为下游 span 的 parent，但**不跨 `yield` 持有 current OTel context**——只在推进 `next_handler` 的同一 `__anext__` 步内 `attach`/`detach`（注释指向 issue **#2076**：async generator 可能被另一个 asyncio task 关闭，token 必须在创建它的 context 里 detach）。对外部执行的工具，它在 reply 开头为 `ExternalExecutionResultEvent.execution_results` 合成 `execute_tool` span，带 `GEN_AI_OPERATION_NAME` / `GEN_AI_TOOL_CALL_ID` / `GEN_AI_TOOL_NAME` 等属性，并标 `AGENTSCOPE_IS_EXTERNAL_EXECUTION=True`，记录 HITL / external pending 状态。这两处设计都落在 `on_reply` 的同一段源码里：

```python
        # Keep the reply span as parent for downstream spans, but do NOT hold
        # it as the current OTel context across ``yield`` boundaries.  The
        # context is only attached while advancing ``next_handler`` and is
        # detached again within the same ``__anext__`` step, so the token is
        # always detached in the context it was created in even when this
        # async generator is closed from another asyncio task (issue #2076).
        span_context = otel_trace.set_span_in_context(span)

        # Synthetic execute_tool spans for externally executed tools
        event_arg = input_kwargs.get("inputs")
        if isinstance(event_arg, ExternalExecutionResultEvent):
            for result in event_arg.execution_results:
                tool_attrs: dict[str, Any] = {
                    SpanAttributes.GEN_AI_OPERATION_NAME: (
                        OperationNameValues.EXECUTE_TOOL
                    ),
                    SpanAttributes.GEN_AI_TOOL_CALL_ID: result.id,
                    SpanAttributes.GEN_AI_TOOL_NAME: result.name,
                    SpanAttributes.AGENTSCOPE_IS_EXTERNAL_EXECUTION: (True),
                    **common_attrs,
                }
```

三者各自一个子目录：`_agentic_memory/`（单 `_middleware.py`）、`_mem0/`（`_middleware.py` + `_agentscope_adapter.py` 的 chat/embedding 适配器 + `_tools.py` + `_utils.py`）、`_reme/`（`_middleware.py` + `_config.py` 的 15 个具名 job + `_tools.py` + `_utils.py`，`_build_app` 懒加载）。目录布局与打包 extras 的逐文件事实见 Memory 分册。

### Permission: Field Semantics and Cross-Owner Policy

`PermissionContext`（`src/agentscope/permission/_context.py`）除 `mode` 外还含 `working_directories: dict[str, AdditionalWorkingDirectory]`（每项 `path` + `source`，供 `ACCEPT_EDITS` 判定「目标是否落在工作目录内」），以及按 tool name 分桶的 `allow_rules` / `deny_rules` / `ask_rules`。

`PermissionDecision`（`src/agentscope/permission/_decision.py`）除了 `behavior` / `message` / `decision_reason` / `suggested_rules` / `bypass_immune`，还有 `updated_input: dict | None`——工具可借它回传「已净化的输入」（如规整后的路径），引擎与 Agent 据此执行而非原始输入。

> [!NOTE]
> `DenyAllResourceAccessPolicy` 在 `src/agentscope/app/access/_policy.py`（`ResourceAccessPolicyBase` 也在同文件），`create_app` 默认装它，再包进 `ResourceAccessService`。它与 `PermissionEngine` 的「工具级 allow / deny / ask」是**两条独立链路**：前者是 Service 层跨 owner 资源共享策略，后者是 Agent 侧权限 DSL。完整事实见 App 分册。其类定义：

```python
class DenyAllResourceAccessPolicy(ResourceAccessPolicyBase):
    """Default policy that denies all cross-owner resource access."""
```

## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)
- [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md)
- [权限理论](/docs/CS/AI/LLM/Agent/Theory/Permission.md)
- [AgentLoop](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentLoop.md) / [Classifier](/docs/CS/AI/LLM/Agent/Product/AgentScope/Classifier.md) / [SOP](/docs/CS/AI/LLM/Agent/Product/AgentScope/SOP.md) / [Memory](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)

## References

- [AgentScope v2.0.11 — middleware/_model_router.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/middleware/_model_router.py)
- [AgentScope v2.0.11 — middleware/_longterm_memory/](https://github.com/agentscope-ai/agentscope/tree/v2.0.11/src/agentscope/middleware/_longterm_memory)
- `src/agentscope/middleware/_base.py`
- `src/agentscope/middleware/_budget.py`
- `src/agentscope/middleware/_tts_middleware.py`
- `src/agentscope/middleware/_tracing/_setup.py` / `_trace.py`
- `src/agentscope/middleware/_longterm_memory/`（`_agentic_memory` / `_mem0` / `_reme`）
- `src/agentscope/permission/_engine.py` / `_rule.py` / `_decision.py` / `_context.py` / `_types.py`
- `src/agentscope/app/access/_policy.py`（跨 owner 资源访问策略，`DenyAllResourceAccessPolicy`）
