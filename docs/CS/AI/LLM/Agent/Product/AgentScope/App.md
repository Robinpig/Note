## Introduction

从 v2.0.8 起，Agent Service 不再是 example，而是正式包 `src/agentscope/app/`（约 200 个文件、2MB 量级，与核心 Agent 层 270K 不是一个量级）。它是一个基于 FastAPI 的多租户 Agent 运行时：多会话、频道接入、Hub 集成、团队编排、后台任务、定时调度与唤醒、RAG 服务、跨 owner 资源共享。

本分册覆盖 **`create_app` 工厂与 15 个路由**、**`lifespan` 的 AsyncExitStack 生命周期**、**存储抽象（Redis + 异步 SQLAlchemy 双后端）**、**Hub 抽象（GitHub MCP + ClawHub Skill）**、**Workspace 隔离策略与沙箱后端**、以及 **跨 owner 资源访问策略**。Agent 主机制见 [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)，事件/Pipeline 见 [Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)，中间件/权限见 [Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)。

## create_app Factory

`create_app()`（`src/agentscope/app/_app.py:78`）是嵌入或独立运行 AgentScope 的入口。所有内置 router 自动注册；通过 `extra_middlewares` 追加自定义 FastAPI 中间件。核心依赖参数：

- `storage: StorageBase`（必填，生命周期由 lifespan 管理）
- `message_bus: MessageBus`（必填；与 `storage` **刻意解耦**——持久化后端如 SQL 可与传输后端 Redis 不同）
- `workspace_manager: WorkspaceManagerBase`（必填）
- 可选：`knowledge_base_manager` / `knowledge_parsers` / `knowledge_chunkers` / `blob_store` / `mcp_hubs` / `skill_hubs` / `resource_access_policy` / `channels` 等
- 关键字开关：`enable_index_worker` / `enable_channel_worker` / `enable_scheduler` / `download_secret`
- 扩展点：`extra_agent_middlewares` / `extra_agent_tools` / `custom_subagent_templates` / `custom_agent_cls`

### The 15 Routers

`create_app` 在 `_app.py:388-404` 的循环里一次性 `include_router` **15 个**：`agent` / `chat` / `credential` / `health` / `hub` / `knowledge_base` / `mcp` / `schedule` / `session` / `skill` / `workspace` / `model` / `tts_model` / `embedding_model` / `channel`。注意 `_router/` 目录下有 **16 个模块**——多出的 `_schema` 是共享响应 schema，不是 router。

## Lifespan: AsyncExitStack

`lifespan`（`src/agentscope/app/_lifespan.py:34`）用单个 `AsyncExitStack` 进入所有带生命周期的资源，**关闭时逆序退出**，且中途某个资源 startup 抛错也不会泄漏（partial failure 安全）。进入顺序（即清理逆序的关键）：

```
storage → message_bus → workspace_manager → knowledge_base_manager(可选)
        → blob_store(可选) → 各 hub → BackgroundTaskManager
        → ChatRunRegistry → SchedulerManager → ResourceAccessService
        → ChannelClients/ChannelService/CredentialBindingService/ChannelLifecycleDispatcher(可选)
        → ChatService → SessionService → WorkspaceService
        → KnowledgeBaseService + IndexTaskConsumer/IndexSweeper(可选)
        → WakeupDispatcher → CancelDispatcher → channel_dispatcher.lifespan()
```

几个值得记的点：

- **ChatService / SessionService 无自身生命周期**，内联构造（注释 `_lifespan.py:44`）。
- **ChatRunRegistry 在 Wakeup/Cancel dispatcher 之前进入、最后退出**——这样 shutdown 时 dispatcher 先停、registry 最后取消残留的 chat-run 任务（`_lifespan.py:81-85`）。
- **SchedulerManager 在 ChatService 之前构建并注入构造器**——它的 fire 路径改为「推 inbox + 经 bus 排队唤醒」，与 ChatService 解耦（`_lifespan.py:88-99`）。
- **索引双模式**：`enable_index_worker=True` 在 API 进程内起 `IndexWorker`+`IndexTaskConsumer`（内存 bus 近乎免费）；`False` 则由独立进程 `python -m agentscope.app.rag.index_worker` 跑 consumer+worker。无论哪种，`IndexSweeper` 都在 API 进程跑——因为上传发生时只有 API 保证存活（`_lifespan.py:192-250`）。

## StorageBase

`StorageBase`（`src/agentscope/app/storage/_base.py`）是存储抽象，覆盖 credential / mcp / skill / agent / session / schedule / channel / message / team / knowledge_base / knowledge_document 全套 Record。channel 方法默认 `raise NotImplementedError`（按后端能力选实现）。Record 类型：`AgentRecord` / `ChannelRecord` / `CredentialRecord` / `KnowledgeBaseRecord` / `KnowledgeDocumentRecord` / `KnowledgeDocumentStatus` / `MCPRecord` / `ScheduleRecord` / `SessionRecord` / `SessionConfig` / `SessionOrigin` / `SkillRecord` / `TeamRecord`。

v2.0.8 有两个后端：

- **`RedisStorage`**（`storage/_redis_storage.py`）——基于 Redis。
- **`AsyncSQLAlchemyStorage`**（`storage/_sql/_storage.py`）——异步 SQLAlchemy 2.0，支持 SQLite / Postgres / MySQL 任意方言；schema 由 Alembic 管理（`_sql/_alembic`），时间戳统一存 naive UTC（`_utcnow` 生成而非机器本地时间）。`Chunk` 的 `embedding` / `score` 不进 Record，而是拆成 promoted column（`_indexed_fields`）+ `payload` JSON，保证 dialect 中立与「无重复」往返不变量（`_sql/_mappers.py`）。

Blob 走独立的 `BlobStoreBase`（`app/rag/blob_store.py`），v2.0.8 提供 `LocalBlobStore`，S3 走同一抽象。

## HubBase

`HubBase`（`src/agentscope/app/hub/_base.py:10`）是 Hub 抽象，约束很硬：`hub_id` 必须匹配 `HUB_ID_PATTERN = re.compile(r"[a-zA-Z0-9_-]+")`，否则 `raise ValueError`（`_base.py:49`）。两类 Hub：

- **MCPHubBase**（`hub/_mcp/_base.py`）——从远端注册中心发现并装载 MCP server；v2.0.8 含 `GitHubHub`（`hub/_mcp/_github_hub.py`），从 GitHub 注册中心拉 MCP server。
- **SkillHubBase**（`hub/_skill/_base.py`）——发现并装载 skill；v2.0.8 含 `ClawHub`（`hub/_skill/_claw_hub.py`）。

`create_app` 里的 `_index_hubs`（`_app.py:49`）按 `hub_id` 建索引，重复 id 直接 `ValueError`——同一 kind 的 hub 必须 id 唯一，否则路由无法唯一定址。

## WorkspaceManager

`WorkspaceManagerBase`（`src/agentscope/app/workspace_manager/_base.py:28`）管 sandbox 后端编排，核心是 **`IsolationPolicy`**（`_base.py:18`，`StrEnum`）：

| Policy | `assign_workspace_id` 行为 |
| :--- | :--- |
| `PER_SESSION`（默认否） | 每次新 session 发 fresh UUID |
| `PER_AGENT`（**默认**） | 复用该 agent 上一次 session 的 workspace id |
| `PER_USER` | 对 `user::` 做**确定性 BLAKE2b** 派生，同 user 跨 session 稳定 |

`assign_workspace_id`（`_base.py:83`）按 policy 三档逻辑决定 id（`:95-132`）。`bind_storage` / `get_workspace` / `close` / `close_all` 是其余抽象方法。

v2.0.8 的后端矩阵（`workspace_manager/`）：`LocalWorkspaceManager`（本地进程）、`DockerWorkspaceManager`、`KubernetesWorkspaceManager`、`DaytonaWorkspaceManager` / `E2BWorkspaceManager`（远端托管沙箱）、`BubblewrapWorkspaceManager`（源码注释警告**它不是网络沙箱**）、`OpenSandboxWorkspaceManager`、`AppleContainerWorkspaceManager`（macOS 原生容器）。公共基类 `SandboxedWorkspaceBase` 提供生命周期钩子、`_mcp_gateway_app.py` 网关启动、健康探测（`/health` 轮询，退避 0.1s→1.0s，超时 tail 日志）、清理。只有沙箱才有 MCP 网关——沙箱内的 MCP client 统一走网关代理（见 [AgentScope 的 Workspace and Sandbox](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md?id=workspace-and-sandbox) 的 BackendBase 三层划分）。

## ResourceAccessPolicy

跨 owner 资源共享由 `src/agentscope/app/access/` 管控：

- `ResourceKind`：`CREDENTIAL` / `AGENT` / `KNOWLEDGE_BASE`。
- `ResourcePermission`：`READ` / `EDIT`。
- `ResourceRef`：把 `(kind, owner, id)` 捆成一个引用。
- `ResourceAccessPolicyBase`：`list_accessible()` / `can_edit()`。
- **`DenyAllResourceAccessPolicy`**：默认**拒绝所有跨 owner 访问**——group / org 级共享必须显式配策略才放开。

`lifespan` 把它包进 `ResourceAccessService`（`_lifespan.py:105`），router 与运行时服务都经这一道 choke point 解析 credential / agent / knowledge base。

## Channel Adapters

`src/agentscope/app/channel/` 在 v2.0.8 已有**真实平台适配器**（非仅抽象层）：`Feishu`（飞书，`_feishu/`）、`Discord`（`_discord/`）、`DingTalk`（钉钉，`_dingtalk/`，含 `_card` / `_openapi` / `_tools`）。`ChannelBase` + `ChannelTypeRegistry` 是注册骨架；`ChannelClients` / `ChannelGateway` / `ChannelLifecycleDispatcher` 是连接与路由层。注意：**只有在 `channel_type_registry` 非空时才接线 channel 子系统**——否则 dispatcher 的 reconcile 会打到未实现 channel 方法的 storage 后端（`_lifespan.py:122-162`）。

## Minimal create_app (Library Mode)

`create_app` 三个依赖是必填：`storage` / `message_bus` / `workspace_manager`，其余全可选。`storage` 与 `message_bus` **刻意解耦**——持久化后端（SQL）和传输后端（Redis）可以不同。一个最小可跑的库模式接线（SQLite + 本地 workspace）：

```python
from agentscope.app import create_app
from agentscope.app.storage._sql._storage import AsyncSQLAlchemyStorage
from agentscope.app.workspace_manager._local_workspace_manager import (
    LocalWorkspaceManager,
)
from agentscope.app.message_bus import InMemoryMessageBus   # 本地用；远程换 RedisMessageBus

storage = AsyncSQLAlchemyStorage("sqlite+aiosqlite:///./as.db")  # 首次进入惰性建表
workspace = LocalWorkspaceManager(basedir="./workspaces")          # PER_AGENT 隔离

app = create_app(
    storage=storage,
    message_bus=InMemoryMessageBus(),     # 传输后端；远程部署换 RedisMessageBus
    workspace_manager=workspace,
    # 可选：knowledge_base_manager / mcp_hubs / skill_hubs /
    #       channels / resource_access_policy / enable_scheduler ...
)
```

落点对照上文：① `AsyncSQLAlchemyStorage(url)` 的 `__aenter__` 才建引擎、`create_tables=True` 时跑 `Base.metadata.create_all`，全新部署无需手动建库；时间戳统一存 naive UTC（`_utcnow` 生成）；② `LocalWorkspaceManager(basedir, isolation=PER_AGENT)` 的 workdir 从 `basedir/agent_id` 确定性重建，缓存 miss 时不需要查存储；③ 15 个 router 在 `create_app` 内部一次性 `include_router`，但只有当对应子系统被接线（如 `channel_type_registry` 非空、或传入 `mcp_hubs`）时才真正生效——否则 dispatcher 的 reconcile 会打到未实现该方法的 storage 后端而报错。生产部署建议 `agentscope[service]` + `agentscope[storage-sql]` + 远端 `WorkspaceManager`（Docker/K8s/Daytona/E2B）与 `RedisStorage` / `RedisMessageBus`。

## Packaging

依赖按组分包，核心包只依赖模型 SDK：

- `agentscope[service]` → FastAPI / uvicorn / APScheduler
- `agentscope[storage-sql]` → SQLAlchemy
- `agentscope[workspace-docker]` → aiodocker
- `agentscope[tools]` → 内置 `Grep` 需要的 `rg` 二进制，版本锁 `ripgrep>=14.1,<15`（15.x 只有部分平台的 wheel，其它平台回退 Rust sdist 无工具链会编译失败；远程沙箱在镜像内装 ripgrep，不走此 extra）

## Deployment Switches: Three Role-Separation Toggles

`create_app` 的三个布尔开关把 Service 层拆成可独立部署的角色，源码落点：

- `enable_index_worker`（默认 `True`，`src/agentscope/app/_app.py:86`）——`False` 时索引循环挪到独立进程 `python -m agentscope.app.rag.index_worker`；`True` 时在 API 进程内起 `IndexWorker` + `IndexTaskConsumer`。（`enable_index_worker` 还会与 `knowledge_base_manager is not None` 做 AND，见 `_app.py:366-368`。）
- `enable_channel_worker`（默认 `True`，`src/agentscope/app/_app.py:90`）——`False` 时本进程不持有频道长连接，连接交给独立 channel worker；API 端点仍可用，只把「连接」移走。
- `enable_scheduler`（默认 `True`，`src/agentscope/app/_app.py:91`）——`False` 时本节点不持有 APScheduler 定时器，只写 storage 并 bus 通知 owner 节点。

三者关闭后对应 API 端点**仍然可用**：它们的实现改成「写 storage → 经 bus 排队唤醒」，真正的长连接/定时器/索引循环由 owner 节点 reconcile。这套 reconcile 模式统一在 `SchedulerManager.reconcile` / `ChannelLifecycleDispatcher.reconcile` / `IndexSweeper` 三处。注意 trunk 把这三个开关列在 `Agent Service` 一节，但**实际默认值都是 `True`（嵌入部署）**，只有横向扩展时才显式关掉其中某个。

## MessageBus: Five Primitives

`MessageBus`（`src/agentscope/app/message_bus/_base.py:53`）是整个 Service 层的神经中枢。trunk 称「六原语」，但 base 类的接口实际暴露**五族消费语义** + 一层 session/inbox/wakeup 业务 helper。base 类文档字符串自述「Three orthogonal modes are exposed」（A/C/D），但实现里还包含了分布式锁（E）与注册表（F）两族，共五族：

| 族 | 语义 | 抽象方法（行号） | 典型用途 |
| :--- | :--- | :--- | :--- |
| **Mode A — drain queue** | 单消费者、ack-on-read，读走即删 | `queue_push:95` / `queue_drain:131` / `queue_delete:159` | wakeup 触发队列、session inbox（HintBlock 投递） |
| **Mode C — replay log** | 多消费者、非破坏性、`max_len`/`ttl` 限长 | `log_append:175` / `log_read:214` / `log_trim:244` | session event log（SSE late-join 补历史） |
| **Mode D — transient broadcast** | fire-and-forget，仅实时订阅者收到 | `publish:264` / `subscribe:284` | wakeup signal、cancel broadcast、schedule lifecycle notify |
| **Mode E — distributed lock** | 集群级互斥，带心跳续租 | `acquire_lock:327` / `is_locked:359` / `try_lock:373` / `unlock:395` | session run 锁（同 session 同时只有一个 `ChatService.run` 在跑） |
| **Mode F — registry map** | hash-keyed namespace，支持 CAS（`registry_set_if`）与 pop-exactly-once | `registry_set:403` / `registry_set_if:434` / `registry_pop:464` / `registry_del:482` / `registry_exists:495` / `registry_getall:511` / `registry_get:528` / `registry_drop:548` | background task 全局注册表、channel liveness 心跳 |

base 类不碰任何业务 key —— 所有 key 格式集中在 `MessageBusKeys`（`src/agentscope/app/message_bus/_keys.py`）：`session_events:130` / `session_lock:144` / `wakeup_queue:203` / `wakeup_signal:208` / `bg_tasks:251` / `schedule_lifecycle:298` / `channel_liveness:337` / `channel_seen_chats:356`。

在此之上 base 类还提供了 session/inbox/wakeup/bg-task 业务 helper，把上面的原语组合成可复用能力：`session_run:590`（acquire lock → yield → trim log）、`session_is_running:606`、`session_publish_event:616`、`session_read_events:634`、`session_subscribe_events:651`、`inbox_push:710` / `inbox_drain:727`、`enqueue_wakeup:744` / `enqueue_input:767` / `dequeue_wakeups:792` / `subscribe_wakeup_signal:806`、`bg_task_register:823`。关键常量：`_SESSION_LOCK_KEY="agentscope:session:lock:{sid}":572`、`_SESSION_REPLAY_MAX_LEN=1000:576`。

Redis 实现 `RedisMessageBus`（`src/agentscope/app/message_bus/_redis_message_bus.py:48`）把这五族映射到 Redis 数据结构：`queue_*` 用 Stream（`queue_push:225` / `queue_drain:257`）、`log_*` 用 Stream + `MAXLEN`（`log_append:307` / `log_read:350`）、`registry_*` 用 Hash（`registry_set_if:434` 的 CAS 走 Lua 脚本保证原子）、`acquire_lock:628` 的分布式锁带 `_heartbeat:673` 心跳续租（防进程崩溃死锁）、`publish`/`subscribe:564` 走 Redis pub/sub。base 类文档明确说**不暴露「counted broadcast」**——要 fan-out 给 N 个成员，生产者写时各自 push 一条 Mode A 到每个收件人 inbox，总线不维护 consumer group 状态。

> [!NOTE]
> trunk 把 Mode C 的「replay-then-live」描述为 `MessageBus.open_reply_stream`。**实际 v2.0.8 并不存在这个方法**——`open_reply_stream` 是 `src/agentscope/app/channel/_stream.py:31` 的一个**模块级 async 生成器函数**（被 `ChannelClients` 调用，见 `_clients.py:203`），不是 `MessageBus` 的成员。它先用 `bus.log_read(event_key, max_count=SESSION_REPLAY_MAX_LEN=1000)` 把最近 1000 条历史事件拉回（`:93`），再进入 `bus.subscribe` 实时模式（`:57`），用 `_entry_id` 做去重（`:103-107`），遇到 terminal event（`REPLY_END` / `REQUIRE_USER_CONFIRM` / `REQUIRE_EXTERNAL_EXECUTION`，定义于 `_stream.py:22`）即停。消费者因此可在 run 已经开始后才订阅而不会漏事件。

## WakeupDispatcher: Single Serial Consumer

`WakeupDispatcher`（`src/agentscope/app/_manager/_wakeup_dispatcher.py:65`）每进程**只有一个** asyncio task（`__aenter__` 里 `asyncio.create_task(self._loop(...))`，`:125`）。`_loop` 订阅 `wakeup_signal` 频道，每次收到信号就 `queue_drain(wakeup_queue, max_count=64)` 一批（`:181-184`），然后逐条 `_dispatch_one`。

设计要点（与 trunk 一致，均经源码确认）：

- **串行消费**：所有 run trigger 只走这一个消费者，分布式 `session_lock` 是保险；正常流程里锁几乎不会被竞态（docstring `:8-10`）。
- **`is_locked` 检查**：`_dispatch_one` 在 spawn 前 `is_locked(session_lock)` 判定（`:275`），锁被占则该 trigger `_schedule_retry`（backoff `_RESUME_RETRY_BACKOFF_SECS=0.1`，`:62`）后重入队（`:355`，最终 `enqueue_run_trigger`，`:391`），**绝不丢弃**。
- **orphan guard**：spawn 前 `storage.get_session(...)` 查存在性（`:300`），session 已删则投放一条 `ReplyEndEvent(ERROR)` 让前端快速失败，而非让 `ChatService.run` 崩溃。
- trigger 分三类（`src/agentscope/app/message_bus/_keys.py:33-51`）：`wake`（idle session 唤醒，`input_msg=None`）、`resume`（parked HITL 投递结果）、`message`（真实用户 `Msg` 新轮次）；后两者携带 input，锁冲突时一律重排。

## SchedulerManager: In-Memory APScheduler with Reconcile

`SchedulerManager`（`src/agentscope/app/_manager/_scheduler/_scheduler_manager.py:33`）拥有**内存版** `AsyncIOScheduler`（`from apscheduler.schedulers.asyncio import AsyncIOScheduler`，`:90`）。之所以不能多副本持有：`jobstore` 在内存，每个副本都会在每个 cron tick 触发任务。

- **fire 路径与 `ChatService` 解耦**：`_build_trigger` 触发的 coroutine 不直调 `ChatService.run`，而是把 schedule prompt 包装成 `HintBlock`（带 `<scheduled-task>` XML 标签，`:289-302`）经 `deliver_to_inbox` 投到目标 session inbox，再 `enqueue` 一个 wakeup（`:303-309`）。于是 wakeup 由任意节点的 `WakeupDispatcher` 接手——与 channel 消息、team / 后台工具结果走同一条投递链路。
- **reconcile 是真相同步机制**：`reconcile:421` 读 `storage.list_all_schedules()`，把本地 job set 驱动到与「enabled records」一致（增缺的、删 gone 的、`updated_at` 变动的重建，`:437-453`）。`_listen:457` 订阅 `schedule_lifecycle` 通知即时 reconcile，`_periodic:482` 每 `RECONCILE_INTERVAL_SECS=60` 秒（`55`）自愈一次丢失的通知。`notify_changed:398` 只 publish 一条通知（丢了最多等一个周期）。
- **校验**：`validate_schedule:331` 要求 5 段 cron 表达式、非空 IANA timezone、且 `ended_at > started_at`；`CronTrigger.from_crontab` 不可用（吞掉 start/end 窗口），见 `:339-386`。`misfire_grace_time=300` 防止错过窗口的任务静默丢失（`:509`）。

## Channel Routing: Deterministic uuid5 Sessions

Channel 路由**不需要持久化映射表**。`resolve`（`src/agentscope/app/channel/_routing.py:41`）是纯函数：给定入站 `ChannelEvent` 与 `ChannelRecord`，先从 `bindings` 取第一个匹配的（`:55-59`），再算 `scope_key`，最后用 uuid5 得出 `session_id`。

```python
# channel/_routing.py:18
_SESSION_NAMESPACE = uuid5(NAMESPACE_URL, "agentscope.channel.session")

# channel/_routing.py:63-73
if binding.session_scope is SessionScope.PER_CHAT_USER:
    scope_key = f"{event.chat_id}:{event.channel_user_id}"
else:
    scope_key = event.chat_id
session_id = str(uuid5(
    _SESSION_NAMESPACE,
    f"{record.id}:{binding.agent_id}:{scope_key}",
))
```

后果与 trunk 一致：多节点零协调（任何节点算出同一 `session_id`）、幂等创建（`_gateway._ensure_session` 查存在不才 upsert）、删除安全（删后同 chat 同 scope 自动重建）。

## Channel Subsystem: Gateway (Data Plane) + Dispatcher (Control Plane)

Channel 子系统按数据面/控制面拆成两个独立组件，与 trunk 叙述吻合：

- **`ChannelGateway`（数据面，无状态）** —— `src/agentscope/app/channel/_gateway.py:46`。`process(event):67` 是唯一入口，分流到 `_handle_decision`（卡片点击，`:88` → `_resume:154` → `resume_after_decision`）与 `_handle_message`（消息，`:184` → `resolve` 算出 `agent_id/session_id`，`:198`，并在有 `chat_id` 时 `registry_set(channel_seen_chats, ...):200`）。**只入站**：活跃 session 写 inbox（HintBlock）/ 空闲 session enqueue wakeup，确认点击则读 session state 找等待中的 tool_call 恢复 parked run。
- **`ChannelLifecycleDispatcher`（控制面，持有长连接）** —— `src/agentscope/app/channel/_dispatcher.py:54`。每节点一个，`_instances: dict[channel_id, ChannelInstance]:77` 持有所有本地长连接。`lifespan:82` 先 `reconcile` 再起两个 loop：`_listen:187`（订阅 lifecycle 事件 reconcile）+ `_periodic:204`（每 `LIVENESS_REFRESH_SECS=10:41` 做 reconcile + 心跳）。`reconcile:101` 让 `_instances` 与 storage 里 enabled records 对齐；`_publish_status:217` 把 liveness 通过 bus 广播（API 副本无 dispatcher，只能从 bus 读状态）。

输出方向完全反向：Agent 跑完事件直接发 bus，持有该 channel 长连接的 Dispatcher 经 `open_reply_stream`（`channel/_stream.py:31`）订阅 session events → 调 channel client 发 REST。**Gateway 只入站、Dispatcher 只持有连接**，两者经 bus + storage 间接协作，无直接调用。

## Storage Backends: RedisStorage vs AsyncSQLAlchemyStorage

v2.0.8 两套后端均实现 `StorageBase`（`src/agentscope/app/storage/_base.py`）：

- **`RedisStorage`** —— `src/agentscope/app/storage/_redis_storage.py:53`。基于 Redis，记录带 TTL 语义（`_set_with_ttl:194` / `_refresh_key_ttl:199`），适合高吞吐、可过期的会话/凭证/工具类记录。注意它与 `RedisMessageBus` 是**两个独立 Redis 客户端**——storage 管持久化、bus 管传输，正是 `create_app` 里「`storage` 与 `message_bus` 刻意解耦」的来源。
- **`AsyncSQLAlchemyStorage`** —— `src/agentscope/app/storage/_sql/_storage.py:90`。异步 SQLAlchemy 2.0，支持 SQLite / Postgres / MySQL 任意方言；`__aenter__:162` 时惰性 `Base.metadata.create_all`（`:207`），全新部署无需手动建库。时间戳统一存 **naive UTC**——`_utcnow:67` 生成、`_to_naive_utc:79` 归一（注释见 `_sql/_storage.py:11-16`），保证跨时区可比且不与 aware 时间混用。`Chunk` 的 `embedding` / `score` 不进扁平 Record，而是拆成 promoted column（`_indexed_fields`）+ `payload` JSON（mapper 在 `storage/_sql/_mappers.py`），保证 dialect 中立与「无重复」往返不变量。

Blob 走独立 `BlobStoreBase`（`src/agentscope/app/rag/blob_store.py`），v2.0.8 提供 `LocalBlobStore`（默认 `./blobs`），S3 走同一抽象。

## Hub Implementations: GitHubHub and ClawHub

Hub 抽象与 trunk 一致，源码落点细化：

- **`HUB_ID_PATTERN`** = `re.compile(r"[a-zA-Z0-9_-]+")`（`src/agentscope/app/hub/_base.py:7`），`HubBase` 构造时 `fullmatch` 校验，否则 `ValueError`（`:49`）。`create_app._index_hubs`（`src/agentscope/app/_app.py:49`）按 `hub_id` 建索引，重复 id 直接 `ValueError`——同一 kind 的 hub 必须 id 唯一，否则路由无法唯一定址。
- **`GitHubHub`（MCPHubBase 首实现）** —— `src/agentscope/app/hub/_mcp/_github_hub.py`。`DEFAULT_BASE_URL = "https://api.mcp.github.com":29`，`hub_id` 默认 `"github"`（构造器 `:110`，`base_url` 默认同 `:133`）。`_request:165` 是带鉴权的 HTTP 客户端，`_to_card:299` 把远端条目转成 `MCPCard`。
- **`ClawHub`（SkillHubBase 首实现）** —— `src/agentscope/app/hub/_skill/_claw_hub.py`。`DEFAULT_BASE_URL = "https://clawhub.ai":33`，`hub_id` 默认 `"clawhub"`（`:88`）。`_request:220` / `download:277` 走 ClawHub HTTP API，`_to_card:456` 转 `SkillCard`。

两个 hub 都是「从远端注册中心发现并装载」的 HTTP 客户端，无本地状态；`hub` router 把「发现 / 装载 / 列出」暴露成 HTTP 端点。

> [!WARNING]
> **与主干 AgentScope.md 的冲突点**：主干「Permission System」一节将 `DenyAllResourceAccessPolicy` 的逐文件事实指向 **Middleware 分册（权限）**，并称其在「跨 owner 访问」处由权限引擎处理。但 v2.0.8 **真实位置是 `src/agentscope/app/access/_policy.py:153`**（`ResourceAccessPolicyBase` 在 `:79`，`list_accessible` / `can_edit` 为其抽象方法），**不在任何 permission / 中间件包里**。`create_app` 默认装 `DenyAllResourceAccessPolicy()`（`_app.py:302-304`），再包进 `ResourceAccessService`（`_lifespan.py`）。本分册「ResourceAccessPolicy」一节已正确归位到 `app/access/`，与源码一致；主干的指针应理解为「权限 DSL 的 5 模式 × 4 行为」在 Middleware 分册，而「跨 owner 资源共享策略」是 Service 层独立子系统，二者不混。

## SOP and Classifier: Absent in v2.0.8

trunk 的「Version Delta: v2.0.8 → v2.0.10」一节把 **SOP / Classifier / AskUser Tool / TUI** 标为「超出 v2.0.8」的新子系统。本分册以 v2.0.8 为基准，逐目录核实：

- `src/agentscope/app/sop/` —— **不存在**（本树 `ls` 无此目录）。
- `src/agentscope/app/classifier/` —— **不存在**。
- `src/agentscope/app/middleware/_sop_step_middleware.py` —— **不存在**。
- `app/_service/_sop.py`、`tool/_builtin/_ask_user.py`、`src/agentscope/tui/` 等均为 v2.0.9 / v2.0.10 才加入（仓库另有 `v2.0.9` / `v2.0.10` tag，其 commit 历史含 `feat(classifier)`、`feat(sop)` 等）。

因此本文档**不收录** SOP / Classifier / AskUser / TUI 的任何事实；它们属于 v2.0.10+ 分册范畴，强行写入会与 v2.0.8 源码不符。主干「Service Layer」一节对 `sop/` 的描述应读作「后续版本前瞻」，不应回灌到本分册。

## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)
- [Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)

## References

- `src/agentscope/app/_app.py` / `_lifespan.py`
- `src/agentscope/app/storage/_base.py` / `_redis_storage.py` / `_sql/_storage.py`
- `src/agentscope/app/hub/_base.py` / `_mcp/_github_hub.py` / `_skill/_claw_hub.py`
- `src/agentscope/app/workspace_manager/_base.py`
- `src/agentscope/app/access/_policy.py`
- `src/agentscope/app/channel/`
