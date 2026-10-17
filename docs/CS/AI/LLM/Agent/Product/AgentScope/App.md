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
