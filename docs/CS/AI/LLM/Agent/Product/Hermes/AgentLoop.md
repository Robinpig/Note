## Introduction

Hermes 的 agent 循环是**完全同步**的：`run_agent.py` 里的 `AIAgent` 是 facade，由若干 mixin 拼装（`agent/turn_facade.py`、`client_lifecycle.py`、`stream_delivery.py`、`session_persistence.py`、`compression_facade.py` …）。构造经 `agent/agent_init.py::init_agent`；一次 turn 是 `agent/conversation_loop.py::run_conversation`，由 `AIAgent.run_conversation` 在抢到会话 turn 租约（`turn_facade_lease.py`）后转发。

> 事实来源：`agent/AGENTS.md`、`agent/conversation_loop.py`、`agent/turn_*.py`。基线 main @ 2026-10-17。

## Facade and Construction

`AIAgent.__init__` 约 **60 个参数**（credentials / routing / callbacks / session context / budget / credential pool …），常触碰的子集：

- `base_url`、`api_key`、`provider`、`api_mode`（`"chat_completions" | "codex_responses" | …`）
- `model`（空 → 后续由 config/provider 解析）
- `max_iterations`（默认 **500**，与子代理共享）
- `enabled_toolsets` / `disabled_toolsets`
- `quiet_mode`、`save_trajectories`、`platform`（`"cli"` / `"telegram"` / …）
- `session_id`、`skip_context_files`、`skip_memory`、`credential_pool`

简单接口 `chat(message) -> str`；完整接口 `run_conversation(user_message, system_message=None, conversation_history=None, task_id=None) -> dict`，返回 `final_response` 与 `messages`。

## The Loop

核心是一个带中断检查、预算跟踪、一次 grace call 的同步循环：

```python
while (api_call_count < self.max_iterations and self.iteration_budget.remaining > 0) \
        or self._budget_grace_call:
    if self._interrupt_requested: break
    response = client.chat.completions.create(model=model, messages=messages, tools=tool_schemas)
    if response.tool_calls:
        for tc in response.tool_calls:
            messages.append(tool_result_message(handle_function_call(tc.name, tc.args, task_id)))
        api_call_count += 1
    else:
        return response.content
```

消息用 OpenAI 格式 `{"role": "system|user|assistant|tool", ...}`；推理内容存在 `assistant_msg["reasoning"]`。

## Turn Phases: 34 Sibling Files

每个迭代阶段拆成独立的 sibling，改某环节只动一个 ~600 行文件。grep `def X` 于 `agent/turn_*.py` 定位阶段。代表性阶段：

`turn_preflight*` → `turn_iteration_prep` → `turn_request_assembly` / `turn_api_request` → `turn_api_call` → `turn_api_error` → `turn_response_intake` / `turn_response_check` → `turn_empty_response` → `turn_tool_round` / `turn_tool_validation` → `turn_overflow` → `turn_truncation` → `turn_scripted_prelude`（工具调用前由提示词内建播放的 prompt）→ `turn_context_compaction` → `turn_recovery` / `turn_recovery_autorecover`（耗尽后 wait-and-retry 阶梯）→ `turn_retry_state` → `turn_stop_gates` → `turn_liveness` → `turn_usage` → `turn_final_response` → `turn_finalizer` → `turn_summary`。

**Agent 级工具**（`todo`、`memory` …）在 `handle_function_call()` 之前由 `agent/tool_executor.py` 经 `INLINE_TOOL_EXECUTORS` 表拦截（注册进表，不用 `if name == …` 链）；`tools/todo_tool.py` 是范式。

## Message-Flow Invariants

每条变更都按这两条评审：

- **Prompt 缓存不可破**：绝不改动历史上下文、切换 toolset、重载记忆或重建系统提示；系统提示在会话生命周期内**字节稳定**。唯一的上下文变更是压缩。任何必须中途注入的内容，都走**用户消息或工具结果**，绝不进系统提示——Skill 的 slash 命令（`agent/skill_commands.py`）以用户消息注入；子目录 `AGENTS.md` 提示（`agent/subdirectory_hints.py`）追加到工具结果（head+尾超出 `_MAX_HINT_CHARS = 32_000` 的部分被截断并记录日志，绝不排进 chat 状态告警）。
- **严格角色交替**：绝不连续两条同角色消息，绝不循环中途注入合成 user 消息。唯一例外是 `/steer`，作为工具结果之后的独立 user 行（`assistant(tool_calls) → tool → user` 在每条 provider 路径上都合法），且绝不涂抹到已持久化的 tool 行（append-only 持久化会使其与实时请求发散）。Cron 投递因此跑在独立会话。

**上下文文件**（`agent/prompt_builder.py`）只在启动时从 CWD 加载并设上限（`CONTEXT_FILE_MAX_CHARS` / 由上下文窗口动态推算的 `context_file_max_chars`）。绝不把安装树的 `AGENTS.md` 当项目上下文加载（PR #64611）；子目录提示拒绝工作目录外的路径，所以 `~/.codex/AGENTS.md` / `~/.claude/CLAUDE.md` 永不混入。

> 注意：`model_tools.py` 里的 `_last_resolved_tool_names` 是**进程全局**；`tools/delegate_tool.py::_run_single_child()` 在子代理执行前后 save/restore，读取方可能在子运行期间看到临时陈旧值。

## Compression: The Only Sanctioned Cache Break

两层（来自 `agent/AGENTS.md` § Compression）：

1. **网关会话卫生**——阈值 **85%**。
2. **agent `ContextCompressor`**——阈值 **50%**，可配置，支持 per-model 覆盖；provider 证明过溢后进入失败冷却。

算法：先剪旧工具结果（**不调 LLM**），再选边界，最后用 **auxiliary 压缩模型**生成结构化摘要。原地压缩保持单一稳定 session id；原生 Responses / Codex 压缩路径是 provider 特定的。卡住的摘要流在 `auxiliary.compression.fallback_chain` 上重试一次；重复卡住（已上冷却阶梯的 stall 类失败）以确定性兜底摘要走同一管线结束——**绝不**在 lease/fence 之外提交一次 prune。压缩是被批准的缓存破坏点，保持它是唯一的一个。

## Model and Provider Resolution

- 运行期 provider/model 解析与优先级：`agent/model_metadata.py` 持有上下文长度与能力；provider profiles 是**插件**（`plugins/model-providers/<name>/`，详见 [Extensions](/docs/CS/AI/LLM/Agent/Product/Hermes/Extensions.md)）。
- **Auxiliary（side-LLM）工作**——curator、vision、embedding、标题生成、session_search、压缩——经 `agent/auxiliary_client.py::_resolve_auto_route` 解析；每个任务可在 `config.yaml` 的 `auxiliary:` 下钉死自己的 `provider`/`model`/`base_url`/`reasoning_effort`。每次物理尝试都汇聚到 `_relay_sync_completion` / `_relay_async_completion` / `_relay_sync_stream`，由 `agent/auxiliary_hooks.py` 发出 `pre_auxiliary_call` / `post_auxiliary_call`（仅观察、fail-open，`aux_task` 集合）；主循环的 `pre/post_api_request` 事件**绝不为 aux 调用触发**（#79733）。

## i18n

`t(key)` 解析层级（插件包 → 用户覆盖 `<home>/locales/<lang>.yaml` → 内置 `locales/<lang>.yaml` → 同样的 `en` → 裸 key）；每层都是平铺点分 key，可部分覆盖。每 `(home, lang)` 合并一个 dict 并缓存；`reset_language_cache()` 在每次包注册与 `config set display.language` 时清空。`supported_languages()` 是实时集合（内置 ∪ 覆盖 ∪ 包），也是 `display.language` 校验与 `_normalize_lang` 接受的范围。

## Links

- [Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md)
- [Architecture](/docs/CS/AI/LLM/Agent/Product/Hermes/Architecture.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/Hermes/Tools.md)
- [Skills](/docs/CS/AI/LLM/Agent/Product/Hermes/Skills.md)
- [Memory](/docs/CS/AI/LLM/Agent/Product/Hermes/Memory.md)
- [Extensions](/docs/CS/AI/LLM/Agent/Product/Hermes/Extensions.md)

## References

- [Hermes Agent agent/AGENTS.md](https://github.com/NousResearch/hermes-agent/blob/main/agent/AGENTS.md)
- [Hermes Agent 上下文压缩与缓存文档](https://hermes-agent.nousresearch.com/docs/developer-guide/context-compression-and-caching)
- [Hermes Agent agent loop 文档](https://hermes-agent.nousresearch.com/docs/developer-guide/agent-loop)
