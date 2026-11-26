## Introduction

从 v2.0.8 起，Agent Service 不再是 example，而是正式包 `src/agentscope/app/`。v2.0.11 为 **209 个文件 / 1.83 MB、12 个一级子目录**（`_manager/` `_router/` `_service/` `_tool/` `access/` `channel/` `hub/` `message_bus/` `middleware/` `rag/` `storage/` `workspace_manager/`；旧笔记的「八目录」漏了后四个）。它是一个基于 FastAPI 的多租户 Agent 运行时：多会话、频道接入、Hub 集成、团队编排、后台任务、定时调度与唤醒、RAG 服务、跨 owner 资源共享，v2.0.9 起还接上了 SOP 流程与实时语音会话。

> 版本基线：v2.0.11

本分册覆盖 **`create_app` 工厂与 17 个路由**、**`lifespan` 的 AsyncExitStack 生命周期**、**存储抽象（Redis + 异步 SQLAlchemy 双后端）**、**Hub 抽象（GitHub MCP + ClawHub Skill）**、**Workspace 隔离策略与沙箱后端**、以及 **跨 owner 资源访问策略**。Agent 主机制见 [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)，事件/Pipeline 见 [Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)，中间件/权限见 [Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)。

## create_app Factory

`create_app()`（`src/agentscope/app/_app.py`）是嵌入或独立运行 AgentScope 的入口。所有内置 router 自动注册；通过 `extra_middlewares` 追加自定义 FastAPI 中间件。核心依赖参数：

- `storage: StorageBase`（必填，生命周期由 lifespan 管理）
- `message_bus: MessageBus`（必填；与 `storage` **刻意解耦**——持久化后端如 SQL 可与传输后端 Redis 不同）
- `workspace_manager: WorkspaceManagerBase`（必填）
- 可选：`knowledge_base_manager` / `knowledge_parsers` / `knowledge_chunkers` / `blob_store` / `mcp_hubs` / `skill_hubs` / `resource_access_policy` / `channels` 等
- 关键字开关：`enable_index_worker` / `enable_channel_worker` / `enable_scheduler` / `download_secret`
- 扩展点：`extra_agent_middlewares` / `extra_agent_tools` / `custom_subagent_templates` / `custom_agent_cls`

三个必填依赖、三个布尔开关的默认值、以及「持久化后端与传输后端解耦」都直接写在签名里（`app/_app.py`）：

```python
def create_app(
    storage: StorageBase,
    message_bus: MessageBus,
    workspace_manager: WorkspaceManagerBase,
    knowledge_base_manager: KnowledgeBaseManagerBase | None = None,
    knowledge_parsers: list[ParserBase] | dict[str, ParserBase] | None = None,
    knowledge_chunkers: list[Type[ChunkerBase]] | None = None,
    blob_store: BlobStoreBase | None = None,
    enable_index_worker: bool = True,
    mcp_hubs: list[MCPHubBase] | None = None,
    skill_hubs: list[SkillHubBase] | None = None,
    *,
    enable_channel_worker: bool = True,
    enable_scheduler: bool = True,
    extra_credentials: list[Type[CredentialBase]] | None = None,
    extra_middlewares: list[FastAPIMiddleware] | None = None,
    extra_agent_middlewares: AgentMiddlewareFactory | None = None,
    extra_agent_tools: AgentToolFactory | None = None,
    custom_subagent_templates: list[SubAgentTemplate] | None = None,
    custom_agent_cls: Type[Agent] | None = None,
    resource_access_policy: ResourceAccessPolicyBase | None = None,
    channels: list[Type[ChannelBase]] | None = None,
    download_secret: str | None = None,
    realtime_ice_servers: list[dict[str, Any]] | None = None,
    title: str = "AgentScope",
    version: str = __version__,
    **kwargs: Any,
) -> FastAPI:
```

`message_bus` 的 docstring 把解耦理由写得很直白（同文件）：

```python
        message_bus (`MessageBus`):
            The live message bus used for cross-session inbox delivery
            and idle-session triggers. Required — the bus is intentionally
            decoupled from ``storage`` so the persistence backend (e.g.
            SQL) can differ from the transport backend (Redis). Its
            lifecycle is also managed by the app lifespan.
```

### The 17 Routers

`create_app` 在 `app/_app.py` 的循环里一次性 `include_router` **17 个**：`agent` / `chat` / `credential` / `health` / `hub` / `knowledge_base` / `mcp` / `schedule` / `session` / `skill` / `sop` / `workspace` / `model` / `realtime` / `tts_model` / `embedding_model` / `channel`。v2.0.8 是 15 个，新增的正是 `sop_router` 与 `realtime_router`，`_router/__init__.py` 的 `__all__` 同为 17 项。`_router/_schema/` 仍是共享 Pydantic 模型集合不是 router，只是 v2.0.11 里多了 `_sop.py` 与 `_realtime.py`。

`app/_app.py` 的注册循环：

```python
    # Built-in routers
    for router in (
        agent_router,
        chat_router,
        credential_router,
        health_router,
        hub_router,
        knowledge_base_router,
        mcp_router,
        schedule_router,
        session_router,
        skill_router,
        sop_router,
        workspace_router,
        model_router,
        realtime_router,
        tts_model_router,
        embedding_model_router,
        channel_router,
    ):
        app.include_router(router)
```

`app/_router/__init__.py` 的 `__all__`：

```python
__all__ = [
    "agent_router",
    "channel_router",
    "model_router",
    "realtime_router",
    "embedding_model_router",
    "tts_model_router",
    "chat_router",
    "credential_router",
    "health_router",
    "hub_router",
    "knowledge_base_router",
    "mcp_router",
    "schedule_router",
    "session_router",
    "skill_router",
    "sop_router",
    "workspace_router",
]
```

## Lifespan: AsyncExitStack

`lifespan`（`src/agentscope/app/_lifespan.py`）用单个 `AsyncExitStack` 进入所有带生命周期的资源，**关闭时逆序退出**，且中途某个资源 startup 抛错也不会泄漏（partial failure 安全）。进入顺序（即清理逆序的关键）：

```
storage → message_bus → workspace_manager → knowledge_base_manager(可选)
        → blob_store(可选) → 各 hub → BackgroundTaskManager
        → ChatRunRegistry → SchedulerManager
        → SOPService(唯一新增的 async ctx)
        → IndexTaskConsumer / IndexSweeper(可选)
        → WakeupDispatcher → CancelDispatcher → channel_dispatcher.lifespan()
```

这段 docstring 与 `async with` 开头自证「单 stack + 逆序退出 + partial failure 安全 + ChatService/SessionService 内联」（`app/_lifespan.py`）：

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown of all application-wide resources.

    Every resource with a lifecycle is an async context manager and is
    entered through a single :class:`AsyncExitStack`. The stack tears
    them down in reverse order on shutdown — including when an entry
    later in the sequence raises during startup, so no resource leaks
    on partial failure.

    Service-layer ``ChatService`` and ``SessionService`` have no
    lifecycle of their own and are constructed inline.
    """
    storage = app.state.storage
    message_bus = app.state.message_bus
    workspace_manager = app.state.workspace_manager
    knowledge_base_manager = app.state.knowledge_base_manager
    blob_store = app.state.blob_store
    enable_index_worker = app.state.enable_index_worker
    enable_channel_worker = app.state.enable_channel_worker
    enable_scheduler = app.state.enable_scheduler
    resource_access_policy = app.state.resource_access_policy

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(storage)
        await stack.enter_async_context(message_bus)
        await stack.enter_async_context(workspace_manager)
```

旧笔记把 `ChatService` / `SessionService` 也列进 enter 顺序，其实二者**内联构造、不进 stack**（`app/_lifespan.py`）；v2.0.11 同样内联的还有 `ResourceAccessService`、`RealtimeService` 与 `WorkspaceService`。真正作为 async context 加进 `AsyncExitStack` 的新服务只有 `SOPService`：

```python
        # On the stack so its detached advances stop before storage closes.
        sop_service = await stack.enter_async_context(
            SOPService(
                storage=storage,
                workspace_manager=workspace_manager,
                message_bus=message_bus,
                chat=chat_service,
                session_service=app.state.session_service,
            ),
        )
```

几个值得记的点：

- **ChatService / SessionService 无自身生命周期**，内联构造（见上面 `app/_lifespan.py` 的 docstring）。
- **ChatRunRegistry 在 Wakeup/Cancel dispatcher 之前进入、最后退出**——这样 shutdown 时 dispatcher 先停、registry 最后取消残留的 chat-run 任务。源码注释（`app/_lifespan.py`）：

```python
        # Per-process registry of in-flight chat-run asyncio tasks.
        # Entered before the wake-up + cancel dispatchers so they can
        # share the same registry; exited last so its shutdown can
        # cancel any leftover runs after the dispatchers stop.
        chat_run_registry = await stack.enter_async_context(ChatRunRegistry())
        app.state.chat_run_registry = chat_run_registry
```

- **SchedulerManager 在 ChatService 之前构建并注入构造器**——它的 fire 路径改为「推 inbox + 经 bus 排队唤醒」，与 ChatService 解耦。源码注释（同文件）：

```python
        # Scheduler is independent of ChatService now (its fire path
        # pushes to inbox + enqueues wakeup via the bus), so we build it
        # before ChatService and inject it via the constructor.
        scheduler = await stack.enter_async_context(
            SchedulerManager(
                storage=storage,
                message_bus=message_bus,
                workspace_manager=workspace_manager,
                enabled=enable_scheduler,
            ),
        )
        app.state.scheduler_manager = scheduler
```

- **索引双模式**：`enable_index_worker=True` 在 API 进程内起 `IndexWorker`+`IndexTaskConsumer`（内存 bus 近乎免费）；`False` 则由独立进程 `python -m agentscope.app.rag.index_worker` 跑 consumer+worker。无论哪种，`IndexSweeper` 都在 API 进程跑——因为上传发生时只有 API 保证存活。源码注释（`app/_lifespan.py`）：

```python
            # * Embedded — ``enable_index_worker=True``: this lifespan
            #   additionally starts an :class:`IndexWorker` plus an
            #   :class:`IndexTaskConsumer` that subscribes to the same
            #   channel. The ``InMemoryMessageBus`` makes the round
            #   trip near-free; everything runs in one binary.
            #
            # * Dedicated — ``enable_index_worker=False``: this
            #   lifespan does NOT start a worker. One or more separate
            #   processes (``python -m agentscope.app.rag.index_worker``)
            #   run their own consumer + worker pair subscribed to the
            #   same channel.
            #
            # The sweeper STILL runs in the API process either way,
            # because the API is the only resource guaranteed to be
            # live whenever uploads happen — if the publish ever races
            # a worker restart the durable queue catches the task, and
            # if the queue write itself failed the sweeper eventually
            # re-enqueues from storage.
            if enable_index_worker:
                node_id = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
                worker = IndexWorker(
                    storage=storage,
                    blob_store=blob_store,
                    knowledge_base_manager=knowledge_base_manager,
                    parsers=app.state.knowledge_parsers,
                    chunkers=app.state.knowledge_chunkers,
                    node_id=node_id,
                )
                await stack.enter_async_context(
                    IndexTaskConsumer(
                        message_bus=message_bus,
                        worker=worker,
                    ),
                )

            sweeper = IndexSweeper(
                storage=storage,
                message_bus=message_bus,
            )
            await sweeper.start()
            stack.push_async_callback(sweeper.stop)
```

## StorageBase

`StorageBase`（`src/agentscope/app/storage/_base.py`）是存储抽象，覆盖 credential / mcp / skill / agent / session / schedule / channel / message / team / knowledge_base / knowledge_document 全套 Record。channel 方法默认 `raise NotImplementedError`（按后端能力选实现）。Record 类型：`AgentRecord` / `ChannelRecord` / `CredentialRecord` / `KnowledgeBaseRecord` / `KnowledgeDocumentRecord` / `KnowledgeDocumentStatus` / `MCPRecord` / `ScheduleRecord` / `SessionRecord` / `SessionConfig` / `SessionOrigin` / `SkillRecord` / `TeamRecord`。

v2.0.11 仍有两个后端：

- **`RedisStorage`**（`storage/_redis_storage.py`）——基于 Redis。
- **`AsyncSQLAlchemyStorage`**（`storage/_sql/_storage.py`）——异步 SQLAlchemy 2.0，支持 SQLite / Postgres / MySQL 任意方言；schema 由 Alembic 管理（`_sql/_alembic`），时间戳统一存 naive UTC（`_utcnow` 生成而非机器本地时间）。`Chunk` 的 `embedding` / `score` 不进 Record，而是拆成 promoted column（`_indexed_fields`）+ `payload` JSON，保证 dialect 中立与「无重复」往返不变量（`_sql/_mappers.py`）。

Blob 走独立的 `BlobStoreBase`（`app/rag/blob_store.py`），v2.0.11 提供 `LocalBlobStore`，S3 走同一抽象。

## HubBase

`HubBase`（`src/agentscope/app/hub/_base.py`）是 Hub 抽象，约束很硬：`hub_id` 必须匹配 `HUB_ID_PATTERN = re.compile(r"[a-zA-Z0-9_-]+")`，否则 `raise ValueError`。两类 Hub：

- **MCPHubBase**（`hub/_mcp/_base.py`）——从远端注册中心发现并装载 MCP server；v2.0.11 的实现类名是 `GitHubMCPHub`（`hub/_mcp/_github_hub.py`），旧笔记写的 `GitHubHub` 不准确。
- **SkillHubBase**（`hub/_skill/_base.py`）——发现并装载 skill；v2.0.11 的实现类名是 `ClawSkillHub`（`hub/_skill/_claw_hub.py`），旧笔记写的 `ClawHub` 不准确。

常量定义在 `app/hub/_base.py` 顶部：

```python
# A hub id is a path segment in the hub routes.
HUB_ID_PATTERN = re.compile(r"[a-zA-Z0-9_-]+")
```

构造时用 `fullmatch` 校验（`app/hub/_base.py`）：

```python
        if not HUB_ID_PATTERN.fullmatch(hub_id):
            raise ValueError(
                f"Hub id {hub_id!r} must match [a-zA-Z0-9_-]+ so it is "
                f"usable as a route path segment.",
            )
        self.hub_id = hub_id
```

`create_app` 里的 `_index_hubs`（`_app.py`）按 `hub_id` 建索引，重复 id 直接 `ValueError`——同一 kind 的 hub 必须 id 唯一，否则路由无法唯一定址（`app/_app.py`）：

```python
def _index_hubs(hubs: list | None, kind: str) -> dict:
    """Key the hubs by id, rejecting duplicates.
    ...
    Raises:
        `ValueError`:
            When two hubs of the same kind share an id, which would make
            them indistinguishable in the routes.
    """
    indexed: dict[str, HubBase] = {}
    for hub in hubs or []:
        if hub.hub_id in indexed:
            raise ValueError(
                f"Duplicate {kind} hub id {hub.hub_id!r}: hub ids must be "
                f"unique so routes address exactly one hub.",
            )
        indexed[hub.hub_id] = hub
    return indexed
```

> 上面片段里 docstring 的 Args / Returns 段与省略号处用 `...` 标注，其余为原样摘取。

## WorkspaceManager

`WorkspaceManagerBase`（`src/agentscope/app/workspace_manager/_base.py`）管 sandbox 后端编排，核心是 **`IsolationPolicy`**（`StrEnum`）：

| Policy | `assign_workspace_id` 行为 |
| :--- | :--- |
| `PER_SESSION`（默认否） | 每次新 session 发 fresh UUID |
| `PER_AGENT`（**默认**） | 复用该 agent 上一次 session 的 workspace id |
| `PER_USER` | 对 `user::` 做**确定性 BLAKE2b** 派生，同 user 跨 session 稳定 |

三档枚举与默认值（`app/workspace_manager/_base.py`）：

```python
class IsolationPolicy(StrEnum):
    """Workspace isolation grain for
    :meth:`WorkspaceManagerBase.assign_workspace_id`.
    """

    PER_SESSION = "per_session"
    PER_AGENT = "per_agent"
    PER_USER = "per_user"
```

```python
    def __init__(
        self,
        *,
        isolation: IsolationPolicy = IsolationPolicy.PER_AGENT,
    ) -> None:
```

`assign_workspace_id` 按 policy 三档逻辑决定 id（`app/workspace_manager/_base.py`）——`PER_USER` 走 BLAKE2b、`PER_AGENT` 在存储不可用时也退回确定性派生、否则复用既有绑定：

```python
        del session_id
        if self._isolation is IsolationPolicy.PER_USER:
            return hashlib.blake2b(
                f"user::{user_id}".encode("utf-8"),
                digest_size=8,
            ).hexdigest()
        if self._isolation is not IsolationPolicy.PER_AGENT:
            return await self._mint_workspace_id()

        if self._storage is None:
            return hashlib.blake2b(
                f"{user_id}::{agent_id}".encode("utf-8"),
                digest_size=8,
            ).hexdigest()
```

`bind_storage` / `get_workspace` / `close` / `close_all` 是其余抽象方法。

v2.0.8 的后端矩阵（`workspace_manager/`）：`LocalWorkspaceManager`（本地进程）、`DockerWorkspaceManager`、`KubernetesWorkspaceManager`、`DaytonaWorkspaceManager` / `E2BWorkspaceManager`（远端托管沙箱）、`BubblewrapWorkspaceManager`（源码注释警告**它不是网络沙箱**）、`OpenSandboxWorkspaceManager`、`AppleContainerWorkspaceManager`（macOS 原生容器）。公共基类 `SandboxedWorkspaceBase` 提供生命周期钩子、`_mcp_gateway_app.py` 网关启动、健康探测（`/health` 轮询，退避 0.1s→1.0s，超时 tail 日志）、清理。只有沙箱才有 MCP 网关——沙箱内的 MCP client 统一走网关代理（见 [AgentScope 的 Workspace and Sandbox](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md?id=workspace-and-sandbox) 的 BackendBase 三层划分）。

## ResourceAccessPolicy

跨 owner 资源共享由 `src/agentscope/app/access/` 管控：

- `ResourceKind`：`CREDENTIAL` / `AGENT` / `KNOWLEDGE_BASE`。
- `ResourcePermission`：`READ` / `EDIT`。
- `ResourceRef`：把 `(kind, owner, id)` 捆成一个引用。
- `ResourceAccessPolicyBase`：`list_accessible()` / `can_edit()`。
- **`DenyAllResourceAccessPolicy`**：默认**拒绝所有跨 owner 访问**——group / org 级共享必须显式配策略才放开。

两个枚举（`app/access/_policy.py`）：

```python
class ResourceKind(StrEnum):
    """Resource kinds that can be resolved through the access policy."""

    CREDENTIAL = "credential"
    """A stored credential record."""

    AGENT = "agent"
    """A stored agent configuration."""

    KNOWLEDGE_BASE = "knowledge_base"
    """A stored knowledge base."""
```

```python
class ResourcePermission(StrEnum):
    """Permission level granted for a referenced resource.
    ...
    ``EDIT`` implies ``READ``.
    """

    READ = "read"
    """Read/use access."""

    EDIT = "edit"
    """Read/use access plus mutation rights."""
```

默认策略直接返回空列表（同文件）：

```python
class DenyAllResourceAccessPolicy(ResourceAccessPolicyBase):
    """Default policy that denies all cross-owner resource access."""

    async def list_accessible(
        self,
        viewer_id: str,
        kind: ResourceKind,
        storage: StorageBase,
    ) -> list[ResourceRef]:
        """Return no cross-owner resources."""
        return []
```

`lifespan` 把它包进 `ResourceAccessService`（`_lifespan.py`），router 与运行时服务都经这一道 choke point 解析 credential / agent / knowledge base。

## Channel Adapters

`src/agentscope/app/channel/` 在 v2.0.8 已有**真实平台适配器**（非仅抽象层）：`Feishu`（飞书，`_feishu/`）、`Discord`（`_discord/`）、`DingTalk`（钉钉，`_dingtalk/`，含 `_card` / `_openapi` / `_tools`）。`ChannelBase` + `ChannelTypeRegistry` 是注册骨架；`ChannelClients` / `ChannelGateway` / `ChannelLifecycleDispatcher` 是连接与路由层。注意：**只有在 `channel_type_registry` 非空时才接线 channel 子系统**——否则 dispatcher 的 reconcile 会打到未实现 channel 方法的 storage 后端（`app/_lifespan.py`）。

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

- `enable_index_worker`（默认 `True`，`src/agentscope/app/_app.py`）——`False` 时索引循环挪到独立进程 `python -m agentscope.app.rag.index_worker`；`True` 时在 API 进程内起 `IndexWorker` + `IndexTaskConsumer`。（`enable_index_worker` 还会与 `knowledge_base_manager is not None` 做 AND，见 `app/_app.py`。）
- `enable_channel_worker`（默认 `True`，`src/agentscope/app/_app.py`）——`False` 时本进程不持有频道长连接，连接交给独立 channel worker；API 端点仍可用，只把「连接」移走。
- `enable_scheduler`（默认 `True`，`src/agentscope/app/_app.py`）——`False` 时本节点不持有 APScheduler 定时器，只写 storage 并 bus 通知 owner 节点。

三个开关落到 `app.state` 时的那几行（`app/_app.py`），可见 `enable_index_worker` 的 AND：

```python
    app.state.enable_index_worker = (
        enable_index_worker and knowledge_base_manager is not None
    )
    app.state.enable_channel_worker = enable_channel_worker
    app.state.enable_scheduler = enable_scheduler
```

三者关闭后对应 API 端点**仍然可用**：它们的实现改成「写 storage → 经 bus 排队唤醒」，真正的长连接/定时器/索引循环由 owner 节点 reconcile。这套 reconcile 模式统一在 `SchedulerManager.reconcile` / `ChannelLifecycleDispatcher.reconcile` / `IndexSweeper` 三处。注意 trunk 把这三个开关列在 `Agent Service` 一节，但**实际默认值都是 `True`（嵌入部署）**，只有横向扩展时才显式关掉其中某个。

## MessageBus: Five Primitives

`MessageBus`（`src/agentscope/app/message_bus/_base.py`）是整个 Service 层的神经中枢。trunk 称「六原语」，但 base 类的接口实际暴露**五族消费语义** + 一层 session/inbox/wakeup 业务 helper。base 类文档字符串自述「Three orthogonal modes are exposed」（A/C/D），但实现里还包含了分布式锁（E）与注册表（F）两族，共五族：

| 族 | 语义 | 抽象方法 | 典型用途 |
| :--- | :--- | :--- | :--- |
| **Mode A — drain queue** | 单消费者、ack-on-read，读走即删 | `queue_push` / `queue_drain` / `queue_delete` | wakeup 触发队列、session inbox（HintBlock 投递） |
| **Mode C — replay log** | 多消费者、非破坏性、`max_len`/`ttl` 限长 | `log_append` / `log_read` / `log_trim` | session event log（SSE late-join 补历史） |
| **Mode D — transient broadcast** | fire-and-forget，仅实时订阅者收到 | `publish` / `subscribe` | wakeup signal、cancel broadcast、schedule lifecycle notify |
| **Mode E — distributed lock** | 集群级互斥，带心跳续租 | `acquire_lock` / `is_locked` / `try_lock` / `unlock` | session run 锁（同 session 同时只有一个 `ChatService.run` 在跑） |
| **Mode F — registry map** | hash-keyed namespace，支持 CAS（`registry_set_if`）与 pop-exactly-once | `registry_set` / `registry_set_if` / `registry_pop` / `registry_del` / `registry_exists` / `registry_getall` / `registry_get` / `registry_drop` | background task 全局注册表、channel liveness 心跳 |

「三正交模式 + 不暴露 counted broadcast」出自 `app/message_bus/_base.py` 的模块 docstring：

```python
Three orthogonal modes are exposed:

============================  ===========================================
Mode A — drain queue          Mode C — replay log
``queue_push`` /              ``log_append`` /
``queue_drain``               ``log_read`` / ``log_trim``

Single-consumer, ack-on-read. Multi-consumer, externally bounded.
Each entry returned at most       Each reader tracks its own cursor;
once; storage drops it the        entries persist until trimmed,
moment it is read. TTL bounds     ``max_len`` truncates from the head,
orphaned data when the consumer   or TTL expires the whole key.
disappears.
============================  ===========================================

Mode D — transient broadcast: ``publish`` / ``subscribe``. Fire-and-forget
pub/sub; only currently-subscribed listeners receive a payload, no
history. Use for wake-up signals where missed-while-offline is fine.

Counted broadcast (one entry consumed by N distinct readers) is
intentionally not exposed as a primitive: in practice it requires
consumer-group coordination (Redis Streams' XREADGROUP/XACK semantics)
and adds substantial state. Producers wanting "fan out to N members"
should fan out at write time — push one entry per recipient inbox using
Mode A. The bus stays simple; deduplication is the producer's
responsibility.
```

base 类不碰任何业务 key —— 所有 key 格式集中在 `MessageBusKeys`（`src/agentscope/app/message_bus/_keys.py`）：`session_events` / `session_lock` / `wakeup_queue` / `wakeup_signal` / `bg_tasks` / `schedule_lifecycle` / `channel_liveness` / `channel_seen_chats`。下面这段自证 key 模板与 `SESSION_REPLAY_MAX_LEN` 常量（`app/message_bus/_keys.py`）：

```python
    # ------------------------------------------------------------------
    # Session event stream (replay log + live pub/sub)
    # ------------------------------------------------------------------

    _SESSION_EVENTS = "agentscope:session:events:{sid}"

    SESSION_REPLAY_MAX_LEN = 1000
    """Replay log length cap; older events are trimmed on append."""

    _SESSION_EVENT_CHECKPOINT = "agentscope:session:event_checkpoint:{sid}"
    _SESSION_EVENT_CHECKPOINT_LOCK = (
        "agentscope:session:event_checkpoint:lock:{sid}"
    )
    SESSION_EVENT_CURSOR_FIELD: Final = "cursor"
    SESSION_EVENT_CHECKPOINT_LOCK_TTL_SECS = 30
```

在此之上 base 类还提供了 session/inbox/wakeup/bg-task 业务 helper，把上面的原语组合成可复用能力：`session_run`（acquire lock → yield → trim log）、`session_is_running`、`session_publish_event`、`session_read_events`、`session_subscribe_events`、`inbox_push` / `inbox_drain`、`enqueue_wakeup` / `enqueue_input` / `dequeue_wakeups` / `subscribe_wakeup_signal`、`bg_task_register`。关键常量：`_SESSION_LOCK_KEY="agentscope:session:lock:{sid}"`、`_SESSION_REPLAY_MAX_LEN=1000`。

Redis 实现 `RedisMessageBus`（`src/agentscope/app/message_bus/_redis_message_bus.py`）把这五族映射到 Redis 数据结构：`queue_*` 用 Stream（`queue_push` / `queue_drain`）、`log_*` 用 Stream + `MAXLEN`（`log_append` / `log_read`）、`registry_*` 用 Hash（`registry_set_if` 的 CAS 走 Lua 脚本保证原子）、`acquire_lock` 的分布式锁带 `_heartbeat` 心跳续租（防进程崩溃死锁）、`publish`/`subscribe` 走 Redis pub/sub。base 类文档明确说**不暴露「counted broadcast」**——要 fan-out 给 N 个成员，生产者写时各自 push 一条 Mode A 到每个收件人 inbox，总线不维护 consumer group 状态。

> [!NOTE]
> trunk 把 Mode C 的「replay-then-live」描述为 `MessageBus.open_reply_stream`。**实际 v2.0.8 并不存在这个方法**——`open_reply_stream` 是 `src/agentscope/app/channel/_stream.py` 的一个**模块级 async 生成器函数**（被 `ChannelClients` 调用，见 `_clients.py`），不是 `MessageBus` 的成员。它先用 `bus.log_read(event_key, max_count=SESSION_REPLAY_MAX_LEN=1000)` 把最近 1000 条历史事件拉回，再进入 `bus.subscribe` 实时模式，用 `_entry_id` 做去重，遇到 terminal event（`REPLY_END` / `REQUIRE_USER_CONFIRM` / `REQUIRE_EXTERNAL_EXECUTION`，定义于 `_stream.py`）即停。消费者因此可在 run 已经开始后才订阅而不会漏事件。

`app/channel/_stream.py` 的 terminal event 集合与函数签名：

```python
_TERMINAL_EVENTS = frozenset(
    {
        EventType.REPLY_END,
        EventType.REQUIRE_USER_CONFIRM,
        EventType.REQUIRE_EXTERNAL_EXECUTION,
    },
)


async def open_reply_stream(
    bus: MessageBus,
    session_id: str,
) -> AsyncGenerator[dict, None]:
```

## WakeupDispatcher: Single Serial Consumer

`WakeupDispatcher`（`src/agentscope/app/_manager/_wakeup_dispatcher.py`）每进程**只有一个** asyncio task（`__aenter__` 里 `asyncio.create_task(self._loop(...))`）。`_loop` 订阅 `wakeup_signal` 频道，每次收到信号就 `queue_drain(wakeup_queue, max_count=64)` 一批，然后逐条 `_dispatch_one`。

模块 docstring 自证「单消费者 + 绝不丢 trigger」（`app/_manager/_wakeup_dispatcher.py`）：

```python
"""Single per-process dispatcher for all cross-session run triggers.

One asyncio task per process. Subscribes to the shared trigger signal
channel and drains the durable trigger queue on each signal. It is the
**sole** site that spawns :meth:`ChatService.run` into the shared
:class:`ChatRunRegistry`, which is what makes concurrent-spawn races
(two writers contending for one session's run slot → a spurious "already
has an active chat run" 409) structurally impossible: every run trigger
funnels through this one serial consumer.
...
No kind is ever dropped. A trigger whose session still holds its run
lock is re-queued after a short backoff until the lock frees, then
spawned.
"""
```

> 上面 docstring 中间关于三种 `kind` 的说明段用 `...` 标注省略。

`__aenter__` 里那个唯一的 task（同文件）：

```python
        ready = asyncio.Event()
        self._task = asyncio.create_task(
            self._loop(ready),
            name="wakeup-dispatcher",
        )
        await ready.wait()
        await self._drain_and_dispatch()
        return self
```

设计要点（与 trunk 一致，均经源码确认）：

- **串行消费**：所有 run trigger 只走这一个消费者，分布式 `session_lock` 是保险；正常流程里锁几乎不会被竞态（见上面 docstring）。
- **`is_locked` 检查**：`_dispatch_one` 在 spawn 前 `is_locked(session_lock)` 判定，锁被占则该 trigger `_schedule_retry`（backoff `_RESUME_RETRY_BACKOFF_SECS=0.1`）后重入队（最终 `enqueue_run_trigger`），**绝不丢弃**。重试退避常量（同文件）：

```python
# Delay before re-queuing a trigger whose target session still holds
# its run lock. Short enough to feel instant to the user, long enough
# to avoid a hot re-enqueue loop while the lock is held.
_RESUME_RETRY_BACKOFF_SECS = 0.1
```

- **orphan guard**：spawn 前 `storage.get_session(...)` 查存在性，session 已删则投放一条 `ReplyEndEvent(ERROR)` 让前端快速失败，而非让 `ChatService.run` 崩溃。
- trigger 分三类（`src/agentscope/app/message_bus/_keys.py`）：`wake`（idle session 唤醒，`input_msg=None`）、`resume`（parked HITL 投递结果）、`message`（真实用户 `Msg` 新轮次）；后两者携带 input，锁冲突时一律重排。三个常量（`app/message_bus/_keys.py`）：

```python
    WAKEUP_KIND_WAKE: Final = "wake"
    """Trigger kind: wake an *idle* session to drain pending inbox
    content. The dispatcher spawns the run with ``input_msg=None`` and
    skips the session entirely while it is already running."""

    WAKEUP_KIND_RESUME: Final = "resume"
    """Trigger kind: resume a session parked on an awaiting tool call by
    feeding it a human-in-the-loop result. The dispatcher spawns the run
    with the carried ``input`` event and — unlike ``wake`` — must *not*
    drop the entry while the session is running; it re-queues until the
    parked run releases its lock."""

    WAKEUP_KIND_MESSAGE: Final = "message"
    """Trigger kind: start a new turn from a genuine user ``Msg`` (e.g. an
    inbound channel message). The dispatcher spawns the run with the
    carried message as ``input_msg`` so it is persisted and reasoned over
    as a real user turn. Like ``resume`` (and unlike ``wake``) it carries
    input, so it is re-queued rather than dropped while the session is
    running."""
```

## SchedulerManager: In-Memory APScheduler with Reconcile

`SchedulerManager`（`src/agentscope/app/_manager/_scheduler/_scheduler_manager.py`）拥有**内存版** `AsyncIOScheduler`（`from apscheduler.schedulers.asyncio import AsyncIOScheduler`）。之所以不能多副本持有：`jobstore` 在内存，每个副本都会在每个 cron tick 触发任务。

类 docstring 自证「fire 路径解耦 + 单节点持有定时器 + reconcile 为真相同步」（`app/_manager/_scheduler/_scheduler_manager.py`）：

```python
class SchedulerManager:
    """The cron scheduler manager, responsible for managing scheduled-task
    lifecycle within the agent service.

    The manager owns both the in-memory APScheduler instance and the trigger
    logic that fires scheduled tasks. Triggers do not call ``ChatService``
    directly; instead they push a :class:`HintBlock` to the target session's
    inbox and enqueue a wakeup, so that the application-wide
    :class:`WakeupDispatcher` (running on any process) picks up the work.
    This keeps the scheduler decoupled from ``ChatService`` and makes the
    fire path consistent with team / background-tool result delivery.

    The timers themselves are held by **one** node — APScheduler's
    jobstore is in-memory, so every node holding them fires every cron
    tick, and a schedule runs once per replica. Which node owns them is
    a deployment choice (``create_app(enable_scheduler=...)``), so
    writers cannot register a job in-process: they persist the record
    and call :meth:`notify_changed`, and the owner reconciles its jobs
    against storage. Storage is the source of truth; the notification
    only makes the owner look sooner than its periodic reconcile would.
    """
```

周期常量与内存调度器实例（同文件）：

```python
    RECONCILE_INTERVAL_SECS = 60
    """How often the owner re-reads storage regardless of
    notifications, so a dropped one costs at most one interval."""
```

```python
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        self._storage = storage
        self._message_bus = message_bus
        self._workspace_manager = workspace_manager
        self._enabled = enabled
        self._scheduler = AsyncIOScheduler()
```

- **fire 路径与 `ChatService` 解耦**：`_build_trigger` 触发的 coroutine 不直调 `ChatService.run`，而是把 schedule prompt 包装成 `HintBlock`（带 `<scheduled-task>` XML 标签）经 `deliver_to_inbox` 投到目标 session inbox，再 `enqueue` 一个 wakeup。于是 wakeup 由任意节点的 `WakeupDispatcher` 接手——与 channel 消息、team / 后台工具结果走同一条投递链路。
- **reconcile 是真相同步机制**：`reconcile` 读 `storage.list_all_schedules()`，把本地 job set 驱动到与「enabled records」一致（增缺的、删 gone 的、`updated_at` 变动的重建）。`_listen` 订阅 `schedule_lifecycle` 通知即时 reconcile，`_periodic` 每 `RECONCILE_INTERVAL_SECS=60` 秒自愈一次丢失的通知。`notify_changed` 只 publish 一条通知（丢了最多等一个周期）。
- **校验**：`validate_schedule` 要求 5 段 cron 表达式、非空 IANA timezone、且 `ended_at > started_at`；`CronTrigger.from_crontab` 不可用（吞掉 start/end 窗口）。`misfire_grace_time=300` 防止错过窗口的任务静默丢失。

## Channel Routing: Deterministic uuid5 Sessions

Channel 路由**不需要持久化映射表**。`resolve`（`src/agentscope/app/channel/_routing.py`）是纯函数：给定入站 `ChannelEvent` 与 `ChannelRecord`，先从 `bindings` 取第一个匹配的，再算 `scope_key`，最后用 uuid5 得出 `session_id`。

固定命名空间常量（`app/channel/_routing.py`）：

```python
# Fixed namespace so derived session ids are stable across processes and
# restarts. Do not change — it would orphan every existing session.
_SESSION_NAMESPACE = uuid5(NAMESPACE_URL, "agentscope.channel.session")
```

`resolve` 末尾的 `scope_key` 与 uuid5 计算（同文件）：

```python
    # Session scope projects the (chat_id, user_id) pair; PER_CHAT is
    # naturally per-user for a DM (its chat has only that user).
    if binding.session_scope is SessionScope.PER_CHAT_USER:
        scope_key = f"{event.chat_id}:{event.channel_user_id}"
    else:
        scope_key = event.chat_id

    session_id = str(
        uuid5(
            _SESSION_NAMESPACE,
            f"{record.id}:{binding.agent_id}:{scope_key}",
        ),
    )
    return binding.agent_id, session_id, binding.session_scope
```

后果与 trunk 一致：多节点零协调（任何节点算出同一 `session_id`）、幂等创建（`_gateway._ensure_session` 查存在不才 upsert）、删除安全（删后同 chat 同 scope 自动重建）。

## Channel Subsystem: Gateway (Data Plane) + Dispatcher (Control Plane)

Channel 子系统按数据面/控制面拆成两个独立组件，与 trunk 叙述吻合：

- **`ChannelGateway`（数据面，无状态）** —— `src/agentscope/app/channel/_gateway.py`。`process(event)` 是唯一入口，分流到 `_handle_decision`（卡片点击 → `_resume` → `resume_after_decision`）与 `_handle_message`（消息 → `resolve` 算出 `agent_id/session_id`，并在有 `chat_id` 时 `registry_set(channel_seen_chats, ...)`）。**只入站**：活跃 session 写 inbox（HintBlock）/ 空闲 session enqueue wakeup，确认点击则读 session state 找等待中的 tool_call 恢复 parked run。
- **`ChannelLifecycleDispatcher`（控制面，持有长连接）** —— `src/agentscope/app/channel/_dispatcher.py`。每节点一个，`_instances: dict[channel_id, ChannelInstance]` 持有所有本地长连接。`lifespan` 先 `reconcile` 再起两个 loop：`_listen`（订阅 lifecycle 事件 reconcile）+ `_periodic`（每 `LIVENESS_REFRESH_SECS=10` 做 reconcile + 心跳）。`reconcile` 让 `_instances` 与 storage 里 enabled records 对齐；`_publish_status` 把 liveness 通过 bus 广播（API 副本无 dispatcher，只能从 bus 读状态）。

「只入站」的契约写在模块 docstring 里（`app/channel/_gateway.py`）：

```python
"""ChannelGateway — inbound-only orchestration (data plane).

``process(event, channel)`` is the single entry point for both inbound
messages and confirmation-card clicks. It is deliberately thin:

- a **message** is routed to an ``(agent_id, session_id)`` and delivered
  as run input (a user turn when the session is idle, or an inbox hint
  when a reply is already in flight) — then the gateway returns;
- a **card click** takes the parked request and resumes the run.

The gateway does **not** collect or send the reply. Output flows the
other way: a channel-bound run emits an outbound signal, and the
:class:`~agentscope.app.channel.ChannelLifecycleDispatcher` (on the node
hosting the channel) subscribes to the run's event stream and streams
the reply back — so scheduled / background runs reach the channel too,
not just inbound messages.
"""
```

控制面「只持有连接、状态走 bus」的 docstring 与两个 loop（`app/channel/_dispatcher.py`）：

```python
"""ChannelLifecycleDispatcher — reconcile running instances with storage.

One per node. Storage is the source of truth; this dispatcher makes the
node's live channel set match the enabled records, driven by lifecycle
notifications and a periodic sweep (which also self-heals lost
notifications and refreshes the status heartbeat).

It answers no queries. With the connections in a dedicated worker the
API replicas have no dispatcher to ask, so status is published to the
bus and read from there instead.

Holding the connections is all it does. A reply never comes back here:
delivery is plain REST, so the node running the agent builds its own
client and sends it directly.
"""
```

```python
LIVENESS_REFRESH_SECS = 10
```

```python
    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Start reconcile/heartbeat loops; stop all instances on exit."""
        await self.reconcile()
        await self._publish_status()
        self._tasks = [
            asyncio.create_task(self._listen(), name="channel-lifecycle"),
            asyncio.create_task(self._periodic(), name="channel-heartbeat"),
        ]
```

输出方向完全反向：Agent 跑完事件直接发 bus，持有该 channel 长连接的 Dispatcher 经 `open_reply_stream`（`channel/_stream.py`）订阅 session events → 调 channel client 发 REST。**Gateway 只入站、Dispatcher 只持有连接**，两者经 bus + storage 间接协作，无直接调用。

## Storage Backends: RedisStorage vs AsyncSQLAlchemyStorage

v2.0.11 两套后端均实现 `StorageBase`（`src/agentscope/app/storage/_base.py`）：

- **`RedisStorage`** —— `src/agentscope/app/storage/_redis_storage.py`。基于 Redis，记录带 TTL 语义（`_set_with_ttl` / `_refresh_key_ttl`），适合高吞吐、可过期的会话/凭证/工具类记录。注意它与 `RedisMessageBus` 是**两个独立 Redis 客户端**——storage 管持久化、bus 管传输，正是 `create_app` 里「`storage` 与 `message_bus` 刻意解耦」的来源。
- **`AsyncSQLAlchemyStorage`** —— `src/agentscope/app/storage/_sql/_storage.py`。异步 SQLAlchemy 2.0，支持 SQLite / Postgres / MySQL 任意方言；`__aenter__` 时惰性 `Base.metadata.create_all`，全新部署无需手动建库。时间戳统一存 **naive UTC**——`_utcnow` 生成、`_to_naive_utc` 归一（注释见 `_sql/_storage.py`），保证跨时区可比且不与 aware 时间混用。`Chunk` 的 `embedding` / `score` 不进扁平 Record，而是拆成 promoted column（`_indexed_fields`）+ `payload` JSON（mapper 在 `storage/_sql/_mappers.py`），保证 dialect 中立与「无重复」往返不变量。

naive UTC 的两个函数（`app/storage/_sql/_storage.py`）：

```python
def _utcnow() -> datetime:
    """Current time as a naive UTC timestamp.

    Uses UTC rather than the machine-local ``datetime.now()`` so
    timestamps stay comparable across nodes in a distributed
    deployment; the ``tzinfo`` is stripped so the value round-trips
    through the naive ``DateTime`` columns without mixing aware/naive
    datetimes.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalise *dt* to a naive UTC timestamp.

    Aware datetimes are converted to UTC; naive datetimes are assumed
    to be in the machine-local zone — the project-wide convention for
    ``datetime.now()`` — and re-anchored to UTC.  Either way the result
    is tz-naive so it matches the values produced by :func:`_utcnow`.
    """
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
```

Blob 走独立 `BlobStoreBase`（`src/agentscope/app/rag/blob_store.py`），v2.0.11 提供 `LocalBlobStore`（默认 `./blobs`），S3 走同一抽象；`app/storage/__init__.py` 另加了 `__getattr__` 懒加载 SQL 后端：

```python
def __getattr__(name: str) -> object:
    """Lazily load the optional SQL backend on first attribute access.

    Keeps ``import agentscope.app.storage`` cheap — ``StorageBase``,
    ``RedisStorage`` and the record models never need SQLAlchemy — while
    still exposing ``AsyncSQLAlchemyStorage`` from this package for
    callers that do ``from agentscope.app.storage import
    AsyncSQLAlchemyStorage``. SQLAlchemy is imported only at that point.
    """
    if name == "AsyncSQLAlchemyStorage":
        from ._sql import AsyncSQLAlchemyStorage as _AsyncSQLAlchemyStorage

        return _AsyncSQLAlchemyStorage
    raise AttributeError(
        f"module 'agentscope.app.storage' has no attribute {name!r}",
    )
```

## Hub Implementations: GitHubMCPHub and ClawSkillHub

Hub 抽象与 trunk 一致，源码落点细化：

- **`HUB_ID_PATTERN`** = `re.compile(r"[a-zA-Z0-9_-]+")`（`src/agentscope/app/hub/_base.py`），`HubBase` 构造时 `fullmatch` 校验，否则 `ValueError`。`create_app._index_hubs`（`src/agentscope/app/_app.py`）按 `hub_id` 建索引，重复 id 直接 `ValueError`——同一 kind 的 hub 必须 id 唯一，否则路由无法唯一定址。
- **`GitHubMCPHub`（MCPHubBase 首实现，v2.0.11 类名）** —— `src/agentscope/app/hub/_mcp/_github_hub.py`。`DEFAULT_BASE_URL = "https://api.mcp.github.com"`，`hub_id` 默认 `"github"`、`base_url` 默认同上。`_request` 是带鉴权的 HTTP 客户端，`_to_card` 把远端条目转成 `MCPCard`。
- **`ClawSkillHub`（SkillHubBase 首实现，v2.0.11 类名）** —— `src/agentscope/app/hub/_skill/_claw_hub.py`。`DEFAULT_BASE_URL = "https://clawhub.ai"`，`hub_id` 默认 `"clawhub"`。`_request` / `download` 走 ClawHub HTTP API，`_to_card` 转 `SkillCard`。

两个实现类的默认常量与默认值（`app/hub/_mcp/_github_hub.py`）：

```python
DEFAULT_BASE_URL = "https://api.mcp.github.com"
```

```python
class GitHubMCPHub(MCPHubBase):
    """An MCP hub backed by GitHub's MCP registry.
    ...
    """

    def __init__(
        self,
        hub_id: str = "github",
        display_name: str = "GitHub MCP Registry",
        description: str = "MCP servers published to GitHub's registry.",
        icon_url: str
        | None = "https://avatars.githubusercontent.com/u/9919?s=64",
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
```

（`app/hub/_skill/_claw_hub.py`）：

```python
DEFAULT_BASE_URL = "https://clawhub.ai"
```

```python
class ClawSkillHub(SkillHubBase):
    """A skill hub backed by the ClawHub registry.
    ...
    """

    def __init__(
        self,
        hub_id: str = "clawhub",
        display_name: str = "ClawHub",
        description: str = "The ClawHub public skill registry.",
        icon_url: str | None = "https://openclaw.ai/favicon.svg",
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_token: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
```

> 上面两个类的 docstring 里的用法示例段用 `...` 标注省略，其余为原样摘取。

两个 hub 都是「从远端注册中心发现并装载」的 HTTP 客户端，无本地状态；`hub` router 把「发现 / 装载 / 列出」暴露成 HTTP 端点。

> [!NOTE]
> `DenyAllResourceAccessPolicy` 在 `src/agentscope/app/access/_policy.py`（`ResourceAccessPolicyBase` 在同类文件，`list_accessible` / `can_edit` 为抽象方法），`create_app` 默认装它（`_app.py`），再包进 `ResourceAccessService`（`_lifespan.py`）。它与 `PermissionEngine` 的「工具级 allow / deny / ask」是**两条独立链路**：前者是 Service 层跨 owner 资源共享策略，后者是 Agent 侧权限 DSL。旧笔记曾把这个 NOTE 写成「与主干冲突」，实际主干的归位一直是对的。

## New Subsystems Present in v2.0.11

旧版分册整节断言 SOP / Classifier / AskUser / TUI「本树不存在」，那是把 v2.0.8 的目录快照当成了当前版本。逐 tag `git cat-file -e` 核对后，v2.0.11 的真实情况是：

| 能力 | 位置 | 引入版本 | 说明 |
| :--- | :--- | :--- | :--- |
| SOP 核心 | **顶层 `src/agentscope/sop/`**（`__init__ / _engine / _schema / _state`） | v2.0.9 | `app/sop/` 确实仍不存在——旧笔记找错了目录层级 |
| SOP 服务层 | `app/_service/_sop.py`、`app/_tool/_sop_submit.py`、`app/middleware/_sop_step_middleware.py` | v2.0.9 | `SOPService` 是 lifespan 中唯一新增的 async ctx |
| SOP 存储与路由 | `app/storage/_model/_sop.py`、`0004_sops.py`、`app/_router/_sop.py` | v2.0.9 | 表 `sops` / `sop_runs`，`/sop` 前缀 11 个端点 |
| Classifier | **顶层 `src/agentscope/classifier/`** | v2.0.9 | `app/classifier/` 同样不存在，找错层级 |
| AskUser | `tool/_builtin/_ask_user.py`、`tool/_base.py` 的 `metadata_schema` | v2.0.9 | 外部执行契约，`is_external_tool=True` |
| TUI | **顶层 `src/agentscope/tui/`** | v2.0.9 | 与 `app/` 无关，本来就不该在 app 树里找 |
| ASR | **顶层 `src/agentscope/asr/`** | v2.0.11 | 全包 8 文件；app 层无 asr 路由，只经 credential 模型发现暴露 |

**版本归属的双重错误**：旧笔记不仅说它们「不存在」，还说它们是 v2.0.10 新增——实际是 **v2.0.9**；真正属于 v2.0.10 的是 WebRTC transport / session / 路由，属于 v2.0.11 的是 `asr/`。这些子系统的逐文件事实已拆到 SOP / Classifier / VoiceStack / TUI 四分册，本分册只保留服务层接触点。

另外两处服务层描述需要在 v2.0.11 口径下精化：`open_reply_stream()`（`app/channel/_stream.py`）函数体**没有 `yield`**，是 `return _read(...)` 的 async 函数；replay 起点是**持久化 checkpoint `since`** 而非「最近 1000 条」。`app/channel/_stream.py` 的收尾几行：

```python
    try:
        await asyncio.wait_for(ready.wait(), timeout=_SUBSCRIBE_TIMEOUT_SECS)
        cursor = await bus.registry_get(
            MessageBusKeys.session_event_checkpoint(session_id),
            MessageBusKeys.SESSION_EVENT_CURSOR_FIELD,
        )
    except BaseException:
        feeder_task.cancel()
        raise
    return _read(bus, event_key, queue, feeder_task, cursor)
```

`_read` 里 replay 的 `since` 参数（同文件）：

```python
        for entry_id, evt in await bus.log_read(
            event_key,
            since=after,
            max_count=MessageBusKeys.SESSION_REPLAY_MAX_LEN,
        ):
```

`MessageBus` 五原语 A/C/D/E/F 在 `_base.py` 上一行未改，但 `MessageBusKeys` 新增了 checkpoint、SOP 三层锁（`sop_lock` / `sop_run_lock` / `sop_dispatch`）、projection 与 interrupt channel 等 key（`app/message_bus/_keys.py`）。

## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)
- [Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)
- [AgentLoop](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentLoop.md) / [SOP](/docs/CS/AI/LLM/Agent/Product/AgentScope/SOP.md) / [Classifier](/docs/CS/AI/LLM/Agent/Product/AgentScope/Classifier.md) / [VoiceStack](/docs/CS/AI/LLM/Agent/Product/AgentScope/VoiceStack.md) / [TUI](/docs/CS/AI/LLM/Agent/Product/AgentScope/TUI.md) / [Memory](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)

## References

- [AgentScope v2.0.11 — app/_app.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/app/_app.py)
- [AgentScope v2.0.11 — app/_lifespan.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/app/_lifespan.py)
- `src/agentscope/app/storage/_base.py` / `_redis_storage.py` / `_sql/_storage.py`
- `src/agentscope/app/hub/_base.py` / `_mcp/_github_hub.py` / `_skill/_claw_hub.py`
- `src/agentscope/app/message_bus/_base.py` / `_keys.py`
- `src/agentscope/app/workspace_manager/_base.py`
- `src/agentscope/app/access/_policy.py`
- `src/agentscope/app/channel/`
