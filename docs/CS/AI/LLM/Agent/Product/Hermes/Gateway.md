## Introduction

消息网关让同一个 agent core 从 Telegram / Discord / Slack / WhatsApp / Signal / Email 等约 **27 个平台**对话，且跨平台连续。它还额外暴露 `api_server`（OpenAI 兼容 `/v1` 路由）、webhook 与 A2A 入口。本篇覆盖网关形态、双消息守卫、流式投递契约、`/login`、以及最棘手的 **profile scope**（多 profile 同进程服务）。机制总览见 [Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md)。

> 事实来源：`gateway/AGENTS.md`、`gateway/run.py`、`gateway/platforms/`。基线 main @ 2026-10-17。

## Shape

`gateway/run.py` 是 facade，各阶段拆进 `run_*.py`（startup / adapters / inbound / turn / busy / goals / notifications / shutdown …），会话在 `session*.py`，slash 处理在 `slash_commands_*.py` mixin，授权在 `authz_mixin.py`，适配器在 `platforms/<name>.py` 之上 `platforms/base.py`。`builtin_hooks/` 是「永远注册」的网关 hook 扩展点（当前不随仓发布）。

**关键坑**：网关**直接读用户 YAML raw**（`run.py` + `config.py`），不走 CLI 的 `DEFAULT_CONFIG` 加载器——CLI 看到但网关看不到的 key 说明你用错了加载器。每个适配器挑一个基础 toolset（Telegram → `"messaging"`）。slash 命令通过 `_command_handler_table` 按名查表，列在 `_IDLE_COMMANDS` 或 `_PLAIN_COMMANDS`（`run_busy.py`，运行中可用）；**绝不用 `if canonical == ...` 链**。

## Two Message Guards（两者都必须放行控制类命令）

Agent 运行中，入站消息依次过两道守卫：

1. **base 适配器**（`platforms/base.py`）：当 `session_key in self._active_sessions` 时，把它排进 `_pending_messages`。
2. **runner**（`run.py`/`run_busy.py`）：在抵达 `running_agent.interrupt()` 之前拦截 `/stop`、`/new`、`/queue`、`/status`、`/approve`、`/deny`。

任何必须在 Agent 阻塞时（如审批提示）触达 runner 的新命令，**必须同时绕过两道守卫并 inline 分发**——绝不可经 `_process_message_background()`（会与会话生命周期竞争）。

## Streaming Delivery Contract（stream-is-the-message 适配器）

带 `draft_stream_is_message = True` 的适配器（如 Slack 原生 streaming relay）每 turn 只保留**一条累积的原生流**，该流即最终消息。四条不变式，每条都来自一次线上「重复最终消息」事故（NS-658 canary ledger、hermes#85796 / gateway-gateway#210），违反任一条都会复现重复或冻结流：

1. **Draft 帧前缀稳定**：帧 N 必须是帧 N+1 的字符串前缀。绝不变异草稿（不做 fence 闭合、cursor 后缀、tool 边界处的 segment-state 重置、mrkdwn 转换）。非前缀帧会触发整快照重 append（"stacked copies"）。finalize 路径仍可变换真实终值。
2. **由消费者声明终值，适配器不猜**：`finish(final_text)` 携带完成的 `final_response`（verifier footer、完成说明都在内）。新的 post-stream 增强必须搭这个 payload——finalize 后变异 `final_response` 会重开 `delivered_final_matches` 不匹配 → 纠正性重复发送。
3. **临时发送带 `metadata["_interim_send"] = True`**：任何消费侧 `adapter.send()` 非 turn 终值（评论、segment 尾 flush）都必须设置，否则 seal-interception 会用 interim 文本封住实时流。Seal-interception 在**两道出口**（`send()` 与 `send_for_platform()`）都存在，新出口需同样的两次检查。
4. **以 edit 对账，绝不 plain send**：在已封流旁投递终值（排队 follow-up、带媒体的终值）时，先对消费者的 `message_id` 试 `edit_message`；仅当无可编辑消息才 plain `send()`。已封的原生流是普通消息——`chat.update` 可用（live-verified）。

契约测试：`tests/gateway/test_stream_final_contract.py`（mutation-checked）。Slack 真相：`chat.*Stream` 讲 STANDARD markdown 而非 mrkdwn；`stopStream.markdown_text` 是 APPEND；`startStream`/`stopStream` 是 Tier 2（~20/min）。

## Background Process Notifications

`terminal(background=true, notify_on_complete=true)` 在网关循环上挂一个 watcher（`run_notifications.py::arm_process_watcher`），完成时开一个新 turn；冗长度由 `display.background_process_notifications` 控制。注入需要 `admit_internal_event` 回执（handler 返回 None 不算接收）；被拒的入场会**退还**它声称的每个 batch sibling 而不消耗一次 attempt。本地 CLI/TUI/Desktop 会话把完成与 watch 事件接入与人类输入**同一**持久 FIFO（私有 launch 策略、`internal_notification` 显示 kind）；观察者永不拥有/消费那些 turn，被中断的已启动 turn 保持未知并暂停其 follower。

## `/login`（off-turn，仅配对 DM）

`GatewayLoginCommandsMixin` 拒绝真实配对 DM 之外的任何来源（ntfy、raft、a2a 对广播面报 `dm`），并绑定**整个安装**的 `providers.nous`——所以共享网关必须设 `allow_admin_from`。它在私有的单 worker `_login_executor`（**非**共享池）上 drain `anon_auth.run_sign_in`，每进程仅一次尝试，完成后驱逐仍在 `nous/welcome` 的 Agent，而非写 model override。

## Gateway vs Desktop Lifecycle

`hermes serve`（控制面，桌面派生的子进程）随 App 一起死——这是设计。但**消息网关（`gateway run`） survives the app**：serve 后端的 `/api/gateway/*` 端点以 detached 方式 spawn 它（`start_new_session` / `DETACHED_PROCESS`），所以 `before-quit` 的 SIGTERM 触不到它、bot 继续跑。已知的 breach 是 Windows shim-unlock teardown（`taskkill /T /F` 杀 venv-shim 持有者，#85265），本是为让更新推进，已被 #92091 的 `pause-for-update` 取代。**不要**通过把网关 re-parent 到 backend 来「修」网关随 App 死，**也不要**靠扩大 tree-kill 来「修」更新锁。网关把 `code_sha`/`code_version` 盖进 `gateway_state.json`（`status.py`），让 updater 能验证 fleet。

## Profile Scope（适配器、turn、以及 turn 之间的一切）

- **每入站事件一个身份，先 canonicalize**：`gateway/session_identity.py::resolve_identity` 一次性回答「哪个 bot 收到 / 谁可准入 / 跑在哪」，并把冻结的 `RoutingIdentity` 钉在 source 上（wire-invisible）。每个 ingress 路径在派生 key **之前**调用 canonicalize seam——适配器侧（`platforms/base.py::_canonicalize`）与 runner 侧（`run_adapters.py::_canonicalize`）。未解析身份在 multiplexing 下（路由到无人服务的 profile）在首个 seam 以单条 WARNING 丢弃，**绝不** keyed 进 `agent:main`。`transport_profile` ≠ `runtime_profile` 是常态（共享 bot → 路由卫星）。
- **Intake vs delivery 适配器**：`authz_mixin.py::_intake_adapter_for(source)` 是**收到**事件的 bot（live transport ref → relay socket → identity 的 `transport_profile`），管 intake 策略；`_delivery_adapter_for(source)` 是**应答**的 bot。绝不为 source 读 `self.adapters[platform]`；绝不加第三个 resolver。
- **身份跨进程存活**：`SessionEntry.transport_profile`（路由索引 + `sessions.transport_profile`，可空，由 `SCHEMA_SQL` 对账）把收到 bot 持久化在 key 命名空间旁；任何从持久状态复活会话的路径都经 `_restored_source` 重钉 `RoutingIdentity`，`_delivery_adapter_for` 据此投递或落空（绝不靠启发式回退默认 bot）。
- **Token 锁**：用唯一凭证（bot token / API key）连接的适配器在 `connect()`/`start()` 调 `acquire_scoped_lock()`、在 `disconnect()`/`stop()` 调 `release_scoped_lock()`（来自 `gateway.status`），两个 profile 不能共享一个凭证。
- **Multiplex 下 profile 范围的 env 读取必须 fail-closed——绝不借用 `os.environ`**：`agent/secret_scope.py`；未 scope 的默认 profile 路径（`UnscopedSecretError`）与单 profile 部署保留 `os.environ` 读（那里它本就是该 profile 自己的值）。所有 profile 级 env 配置——凭证（`app_secret`、tokens）**与**授权（`FEISHU_ALLOWED_USERS`、各平台 `ALLOW_ALL_USERS`、`GATEWAY_ALLOW_ALL_USERS`、`group_policy`、`allow_bots`）——都走 scope-aware 读取（`gateway.platforms._shared.get_scoped_secret` 是唯一实现；适配器 import 为 `_get_scoped_secret`）。scope 已装 + multiplex active → scoped miss 返回**默认**，**绝不** `os.environ`（否则泄漏的 allowlist 会跳过 allow-all 检查并静默拒绝每个次级 profile 发送者，#86905）。`tests/gateway/test_shared_platform_boilerplate.py` 断言每个插件的 `_env_enablement` 只经它读。
- **Scope 按 profile 活动绑定，非按 turn**：`run.py::_profile_runtime_scope(home)` 包裹路由的 turn（`run_turn.py::_profile_scope_for_source`）；同一绑定包裹每个触碰 session home、密钥或终端 scope 却无 turn 在栈上的路径：release 与 eviction、shutdown、post-turn 媒体投递、deferred callback、notifier、outbound webhook。原因：在 launch scope 下 flush 的 eviction 会把次级 profile 的记忆写进默认 profile 的 store，静默地。
- **`api_server` 每请求重建 agent，但不重建 memory provider**：适配器绕过 `TurnRunner` 与 agent cache（per-request callback、model route、ephemeral prompt），所以 `platforms/api_server_memory_sessions.py` 把每个 session 已初始化的 `MemoryManager` 停在请求间（exclusive check-out in `_create_agent`，turn 的 `finally` check-in，按 profile home + `agent.session_id` 键；idle/LRU eviction 在所属 home 下 shutdown），`AIAgent(memory_manager=...)` 接纳它而无需二次 provider init。否则上一 turn 排队的 recall 到不了下一请求（#120116）。
- **`multiplex_profiles: false` 不是「永不 scope」**：原生托管房间服务第二个 profile 时会在网关进程内（adapters 接好之后）翻转进程级守卫（`tui_gateway/launch_profile_policy.py::activate_multi_profile_hosting`）；每个独立入口点随后经 `run_turn.py::_standalone_scoped` 绑 launch profile 自己的 scope（`.env` over 激活时冻结的 env，绝不 `.env`-only 重建，也绝不 live `os.environ`）。
- **Hook 与 observer 按被服务 profile 注册**：`builtin_hooks/`、`agent/shell_hooks.py::register_from_config`、生命周期 observer 在 startup 与 profile 增/删时各 profile 的 scope 下准备；idempotence key 含 profile，且 `hooks/` 路径 call 期解析（模块常量会冻到首个 importer）。Shell hooks 也在每次本地 session create/resume 经 `session_policy.refresh_profile_hooks` → `shell_hooks.sync_from_config` 重新同步（唯一会移除的调用方）。
- **Unserved 要报告，绝不静默**：共享 ingress 平台（Relay）只在默认 profile 跑；次级启用的会在 connect 路径记一次 remedy 与 runtime status（`run_adapters.py::_note_unserved_secondary_platform`）。WhatsApp bridge 按 profile：配对的次级拿自己的适配器与端口（`plugins/platforms/whatsapp/bridge_ownership.py`），未配对的报 `whatsapp_unpaired`，次级绝不 adopt 或 signal 一个其 pidfile（pid + 启动时间 + 端口）不能识别的 bridge。

## Tests

`tests/gateway/`。适配器测试用 fake transport 走真实投递路径；**绝不**对硬编码的平台列表或命令计数断言。Session-key 与守卫行为是不变量，值得测；平台 API 怪癖属于 connector 注释 + 测试，不入正文。

## Links

- [Hermes](/docs/CS/AI/LLM/Agent/Product/Hermes/Hermes.md)
- [Architecture](/docs/CS/AI/LLM/Agent/Product/Hermes/Architecture.md)
- [AgentLoop](/docs/CS/AI/LLM/Agent/Product/Hermes/AgentLoop.md)
- [Memory](/docs/CS/AI/LLM/Agent/Product/Hermes/Memory.md)
- [Extensions](/docs/CS/AI/LLM/Agent/Product/Hermes/Extensions.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/Hermes/Tools.md)

## References

- [Hermes Agent gateway/AGENTS.md](https://github.com/NousResearch/hermes-agent/blob/main/gateway/AGENTS.md)
- [Hermes Agent 网关内部文档](https://hermes-agent.nousresearch.com/docs/developer-guide/gateway-internals)
- [Hermes Agent 消息平台文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/gateway)
