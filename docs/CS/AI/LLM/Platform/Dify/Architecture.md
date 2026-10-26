## Introduction

这一篇回答 Dify「**由哪些进程构成、代码分几层、数据落在哪、边界画在哪**」。动态行为（一次请求怎么流）在 [链路设计](/docs/CS/AI/LLM/Platform/Dify/Pipeline.md)，具体类与签名在 [源码分析](/docs/CS/AI/LLM/Platform/Dify/Source_Code.md)，产品视角的选型判断回到 [Dify](/docs/CS/AI/LLM/Platform/Dify.md)。

⚠️ 网上多数 Dify 架构文章还停留在 1.0 之前「Flask 单体 + 一堆 nodes 目录」的形态。1.17 的实际结构已经不是那样了——**工作流引擎的内核被抽成了独立 Python 包 `graphon`**，Dify 仓库里 `api/core/workflow/` 只剩适配层。不先接受这一点，照着旧文章去 `api/core/workflow/nodes/llm/` 找 LLM 节点会找不到。

## Version Baseline

所有路径与行号取自 git tag `1.17.1`（2026-09-10，写笔记时的最新 release），`main` 分支结构与之基本一致。

| 组件                      | 版本 / 镜像                                          | 出处                                       |
| :---------------------- | :---------------------------------------------- | :--------------------------------------- |
| Dify                    | `1.17.1`                                        | GitHub release                           |
| 工作流引擎内核 graphon        | `graphon==0.5.2`                                | `dify-agent/pyproject.toml` 的 `server` extra |
| 插件守护进程                  | `langgenius/dify-plugin-daemon:0.6.10-local`    | `docker/docker-compose.yaml`             |
| 代码沙箱                    | `langgenius/dify-sandbox:0.2.15`                | 同上                                       |
| Agent 后端                 | `langgenius/dify-agent-backend:1.17.1`          | 同上（Python + uvicorn，5050）                |
| Agent 本地沙箱               | `langgenius/dify-agent-local-sandbox:1.17.1`    | 同上（Go `shellctl serve`，5004）             |
| Go 工具链（dify-agent-runtime）| `go 1.26`                                       | `dify-agent-runtime/go.mod`              |

## Process Topology

```
   浏览器 / 第三方系统 / MCP 客户端
              │
              ▼
      ┌──────────────┐   80 / 443
      │    nginx     │─────────────────────────┐
      └──────┬───────┘                        │  /socket.io
             │                                ▼
             │                        ┌────────────────┐
             ▼                        │ api_websocket  │  profile: collaboration
      ┌──────────────┐                └────────────────┘
      │     api      │  :5001
      └──┬────────┬──┘
         │        │
         │        └──────────────┐ 入队
         ▼                       ▼
  ┌─────────────┐        ┌──────────────┐
  │   worker    │ Celery │ worker_beat  │ 定时
  └──────┬──────┘        └──────────────┘
         │
    ┌────┴───────────────────┐
    ▼                        ▼
┌──────────────┐      ┌──────────────┐
│ PostgreSQL   │      │    Redis    │  broker / 缓存 / Pub-Sub
│ (+ 可选向量库) │      └──────────────┘
└──────────────┘
    ▲                        ▲
    │                        │ :5002  :5003
┌───┴──────────┐      ┌─────┴────────────┐
│plugin_daemon │◀────▶│  agent_backend   │ :5050
└──────────────┘      └────────┬─────────┘
                               │ agent_sandbox_network
                               ▼
                        ┌──────────────┐
                        │ local_sandbox │ :5004  Go shellctl
                        └──────┬───────┘
                               │ agent_ssrf_proxy :3128（白名单出网）
                               ▼
```

### 一个镜像跑四种角色

`api`、`api_websocket`、`worker`、`worker_beat` 用的是**同一个镜像** `langgenius/dify-api:1.17.1`，compose 里都不写 `command`，靠 `MODE` 环境变量 + 镜像自带的 `/entrypoint.sh` 分派：

```bash
# api/docker/entrypoint.sh
MODE=worker) exec celery -A celery_entrypoint.celery worker -P ${WORKER_POOL} ... -Q ${DEFAULT_QUEUES}
MODE=beat)   exec celery -A app.celery beat
MODE=job)    exec flask "$@"          # 一次性运维命令，如 create-tenant
其他)        exec gunicorn ... app:socketio_app
```

`api` 与 `api_websocket` 都落在最后那个「其他」分支上，**不是两个不同命令**，差异只在 worker 参数与开关：

| 服务             | 差异                                                                                                     |
| :------------- | :----------------------------------------------------------------------------------------------------- |
| `api`          | `SERVER_WORKER_AMOUNT` 默认 1、`GUNICORN_TIMEOUT` 默认 200、带 healthcheck、带 `PLUGIN_*` 与 `AGENT_BACKEND_*` 环境变量 |
| `api_websocket`| `API_WEBSOCKET_WORKER_CONNECTIONS` 默认 1000、`GUNICORN_TIMEOUT` 默认 360、`profiles: [collaboration]`、无 healthcheck、`depends_on` 里没有 `agent_backend` |

也就是说：WebSocket 长连接是**默认关闭**的一个可选服务，nginx 通过 `NGINX_SOCKET_IO_UPSTREAM` 指过去。

### Celery 队列清单

队列**不是**在代码里用 `task_queues` 声明的，而是 `api/docker/entrypoint.sh` 里的一个逗号分隔字符串，经 `-Q ${DEFAULT_QUEUES}` 传给 worker：

```
api_token, dataset, dataset_summary, priority_dataset, priority_pipeline, pipeline, mail,
ops_trace, app_deletion, app_rbac, plugin, workflow_storage, conversation, workflow,
schedule_poller, schedule_executor, triggered_workflow_dispatcher, trigger_refresh_publisher,
trigger_refresh_executor, retention, workflow_based_app_execution
```

- Cloud 版（`:38`）把 `workflow` 拆成 `workflow_professional, workflow_team, workflow_sandbox`
- 覆盖优先级：`CELERY_WORKER_QUEUES` > `CELERY_QUEUES` > 版本默认值
- 代码侧大多直接写字面量，例如 `tasks/document_indexing_task.py:32` 的 `@shared_task(queue="dataset")`、`tasks/app_generate/workflow_execute_task.py:42` 的 `WORKFLOW_BASED_APP_EXECUTION_QUEUE`

## The Engine Split: graphon Is the Kernel

这是 1.17 架构上最重要的事实。`api/core/workflow/` 目录下**已经没有** LLM / Code / HTTP / Tool / Iteration / Loop 这些节点的实现了——`nodes/` 里只剩 9 个目录，全是 Dify 特有或新版的东西：`agent`、`agent_v2`、`datasource`、`human_input`、`knowledge_index`、`knowledge_retrieval`、`trigger_plugin`、`trigger_schedule`、`trigger_webhook`。

通用节点来自外部包 `graphon`：

```python
# api/core/workflow/node_factory.py:60
from graphon.enums import BuiltinNodeTypes, NodeType
from graphon.nodes.base.node import Node
from graphon.nodes.code.entities import CodeLanguage
from graphon.nodes.http_request import build_http_request_config
from graphon.nodes.llm.entities import LLMNodeData
```

于是 `api/` 这一侧的职责变成**「把 Dify 的租户、模型、文件、工具、计费、HITL 接到 graphon 定义的 Protocol 上」**，而不是自己执行节点：

| graphon 提供            | Dify 侧的实现（`core/workflow/`）                                                       |
| :-------------------- | :----------------------------------------------------------------------------- |
| `LLMProtocol`         | `node_runtime.DifyPreparedLLM`、`DifyPreparedPollingLLM`                          |
| `ToolNodeRuntimeProtocol` | `node_runtime.DifyToolNodeRuntime`                                            |
| `FileReferenceFactoryProtocol` | `node_runtime.DifyFileReferenceFactory`                                 |
| `RetrieverAttachmentLoaderProtocol` | `node_runtime.DifyRetrieverAttachmentLoader`                           |
| `PromptMessageSerializerProtocol` | `node_runtime.DifyPromptMessageSerializer`                              |
| `ModelRuntime`        | `plugin/impl/model_runtime.PluginModelRuntime`（再转发给 `PluginModelClient`）     |
| `GraphEngine` / Layers | `workflow_entry.WorkflowEntry` 负责组装                                        |
| `VariablePool`        | `variable_pool_initializer` + `system_variables` 负责灌入                        |

后果有两个，一好一坏：

- **好**：内核可以独立于平台演进，也能被单独使用——graphon 支持 `graphon.dsl.loads()` 直接导入 Dify 的工作流 DSL 在无 Dify 的 Runtime 上跑（第三方已验证过这条路径）。这意味着 Dify 的画布事实上成了一种**可移植的工作流 DSL 编辑器**。
- **坏**：想读懂或调试一条工作流的执行语义，光 clone `langgenius/dify` 不够，得同时看 `langgenius/graphon`。旧版常见的「节点 → 变量池 → 下一个节点」在 Dify 仓库里已经看不全了。

## Layering: controllers → services → core → libs

`api/.importlinter` 用 import-linter 把分层固化成可执行契约：

```ini
[importlinter:contract:backend-layers]
name = Backend modules follow the transport, application, domain, and shared-library layers
type = layers
layers =
    controllers
    services
    core
    libs
unmatched_ignore_imports_alerting = error
```

即**只允许单向依赖**。有意思的是注释里那句 `Migration baseline: keep every exception exact`——`ignore_imports` 逐条登记了 90 多条存量违规（如 `core.workflow.node_runtime -> services`、`core.rag.retrieval.dataset_retrieval -> services.feature_service`、`services.account_service -> controllers`），并且用 `error` 级别保证**这个列表只减不增**。这是很务实的重构手法：不假装代码是干净的，而是先把现状钉死再慢慢还债。

其余契约是 `forbidden` 型：

- 只有密钥 provider 抽象能直接 `import libs.rsa`，其余模块必须通过间接依赖
- `machinery` 包不得依赖 `controllers / extensions / flask / models / sqlalchemy / werkzeug`（框架中立的机制层）
- 约 25 个应用服务（`services/*_service`）被禁止碰框架与持久化：`controllers / extensions / flask / models / repositories / sqlalchemy / werkzeug` 全在黑名单里

## Storage

### PostgreSQL：主库里没有向量列

这点值得专门澄清。主库 `dify` 的 ORM（`api/models/dataset.py`）里**没有任何 `vector` 类型列，也没有 `CREATE EXTENSION vector`**；`embeddings` 表存的是 pickle 序列化后的二进制：

```python
# api/models/dataset.py
class Embedding(TypeBase):
    embedding: Mapped[bytes] = mapped_column(BinaryData, nullable=False)

    def set_embedding(self, embedding_data: list[float]):
        self.embedding = pickle.dumps(embedding_data, protocol=pickle.HIGHEST_PROTOCOL)
```

pgvector 的正确身份是：**33 个可选 `VectorType` 之一**（`api/core/rag/datasource/vdb/vector_type.py`），实现放在独立的 provider 包 `api/providers/vdb/vdb-pgvector/`，在 compose 里是独立服务（`image: pgvector/pgvector:pg16`，`profiles: [pgvector]`）。

说「Dify 默认用 Postgres 上的 pgvector 存向量」只对一半——**默认元数据库是 Postgres，向量库是另一件事**，自部署时生产上更常见的是接 Milvus / Weaviate / Qdrant 这类独立向量库，靠 `vector_backend_registry` 注册进来。

### Redis：四种用途

1. **Celery broker + result backend** —— `CELERY_BROKER_URL=redis://...:6379/1`，`CELERY_BACKEND=redis`，`CELERY_RESULT_BACKEND` 直接复用 broker URL
2. **缓存 / 分布式锁 / hash / zset** —— `RedisClientWrapper` 统一加 `REDIS_KEY_PREFIX`，`lock()` 用于并发控制
3. **Pub/Sub 广播通道** —— 多 gunicorn worker 之间转发流式响应，三种实现可选（普通 / 分片 / streams）：
   ```python
   # extensions/ext_redis.py
   def get_pubsub_broadcast_channel() -> BroadcastChannelProtocol:
       if dify_config.PUBSUB_REDIS_CHANNEL_TYPE == "sharded":
           return ShardedRedisBroadcastChannel(_pubsub_redis_client)
       if dify_config.PUBSUB_REDIS_CHANNEL_TYPE == "streams":
           return StreamsBroadcastChannel(...)
       return RedisBroadcastChannel(_pubsub_redis_client)
   ```
4. **agent_backend 独占 db 2** —— `DIFY_AGENT_REDIS_URL: redis://:...@redis:6379/2`，与 api 侧的 db 0 / Celery 的 db 1 分开

连接形态支持 standalone / Sentinel / Cluster，可选 RESP3 客户端缓存、SSL 与指数退避重试。

### 对象存储

`STORAGE_TYPE` 决定实现，共 13 种 backend：`aliyun-oss`、`azure-blob`、`baidu-obs`、`clickzetta-volume`、`google-storage`、`huawei-obs`、`local`、`oci-storage`、`opendal`、`s3`、`tencent-cos`、`volcengine-tos`、`supabase`。

`local` 与 `opendal` 最终都落到 `OpenDALStorage`（前者 scheme 固定为 `fs`）。

扩展初始化顺序有硬依赖：`ext_storage` 必须在 `ext_key_provider` 之前（RSA 私钥是从对象存储里读的），也早于 `ext_logstore`。

## Plugin Boundary

`api` 与 `plugin_daemon` 之间是**HTTP（httpx），不是 gRPC**：

```python
# api/core/plugin/impl/base.py:178-184
url = plugin_daemon_inner_api_baseurl / path
prepared_headers["X-Api-Key"] = dify_config.PLUGIN_DAEMON_KEY
self._inject_trace_headers(prepared_headers)   # ENABLE_OTEL 时注入 traceparent
```

- 连接：`http://plugin_daemon:5002`，keepalive 50 / 最大 100 的 httpx 连接池
- 鉴权：固定 `X-Api-Key: ${PLUGIN_DAEMON_KEY}`，每次调用带 `X-Plugin-ID`
- 响应信封：`PluginDaemonBasicResponse[T]`，`code != 0` 时解析成 `PluginDaemonError` 再映射为具体异常；流式按行解析并剥掉 `data:` 前缀
- 路径安全校验：长度 ≤ 4096、URL-decode 深度 ≤ 8、禁止 `..`
- **反向调用**：plugin_daemon 回调 api 走 `DIFY_INNER_API_URL/KEY`，`/files` 是数据面、`/inner/api` 是企业控制面，两者与 `/health` 都不参与 license 门禁

模型端点集中在 `api/core/plugin/impl/model.py`（`PluginModelClient`），包括 `plugin/{tenant}/dispatch/llm/invoke`、`.../text_embedding/invoke`、`.../rerank/invoke` 等；`impl/model_runtime.py` 不是 HTTP 客户端，而是 graphon `ModelRuntime` 协议的适配器，内部再转发给 `PluginModelClient`。

## Agent Sandbox Boundary

1.17 的 Agent V2 引入了两个新进程，容易搞混：

| 服务               | 语言           | 端口     | 角色                                              |
| :--------------- | :----------- | :----- | :---------------------------------------------- |
| `agent_backend`  | Python FastAPI | 5050   | Agent V2 的**控制面**：接 run 请求、编排、转发事件（来自 `dify-agent/`）      |
| `local_sandbox`  | Go            | 5004   | 执行面：`shellctl serve`，跑 shell / 文件操作（来自 `dify-agent-runtime/`） |

`dify-agent-runtime` 的 `cmd/` 下有五个二进制：`shellctl`、`sanitize-pty`、`runner-exit`、`dify-agent-cli`、`runner`。沙箱隔离用的是 **Landlock**（Linux ≥ 5.13）：

- RW：`$HOME` + job 工作目录（同时作为 `TMPDIR/TMP/TEMP`）
- RO + 可执行：`/usr /bin /sbin /lib /lib64 /etc /proc /opt/dify-agent-tools /opt/homebrew /snap`
- 其余：`/tmp`、其它 agent home、`/var`、`/srv` —— 拒绝

Home Snapshots 通过 `POST /v1/snapshot/save`（tar + zstd 流）和 `POST /v1/snapshot/restore` 实现，restore 侧用 `os.Root` 防路径穿越，zstd window 上限 64 MiB。

### 三条网段各自隔离什么

| 网段                              | 成员                                                       | 隔离含义                                                             |
| :------------------------------ | :------------------------------------------------------- | :--------------------------------------------------------------- |
| `ssrf_proxy_network` (internal) | api、api_websocket、worker、worker_beat、plugin_daemon、**sandbox**、ssrf_proxy | `sandbox` **只挂在这条网**上，不在 `default`，直连不到 db / redis / api；出网只能经 `ssrf_proxy:3128` |
| `local_sandbox_proxy_network` (internal) | **仅** local_sandbox + agent_ssrf_proxy             | local_sandbox 出网被强制走 Squid，白名单只放行 `agent_backend:/agent-stub/` 与 `api:5001/files/*` |
| `agent_sandbox_network` (internal) | **仅** local_sandbox + agent_backend                    | 控制通道：`http://local_sandbox:5004`                                   |

调用链是 `api:5001 → agent_backend:5050 → local_sandbox:5004`。

⚠️ compose 文件里有一段很诚实的注释：**local_sandbox 能通过 shellctl 通道访问 agent backend，这是已知限制**——Agent runtime 会遵守 `HTTP(S)_PROXY`，但 shellctl 通道本身仍意味着任意代码执行可达。所以别把 agent_backend 当成可信边界。

**E2B 与 local_sandbox 是 `DIFY_AGENT_RUNTIME_BACKEND` 的两种互斥后端**：`local`（默认，走 Go shellctl 容器）vs `e2b`（云沙箱，模板 `difys-default-team/dify-agent-local-sandbox`，由 `dify-agent-runtime/docker/sync-e2b-template.sh` 同步）。`docker-compose.e2b.yaml` 里 `local_sandbox` 被挪到了 `local-agent-sandbox` profile 下。

## Why This Matters

- **想改工作流执行语义**（并行度、重试、变量作用域）→ 去 graphon，不在 Dify 仓库。先看 `workflow_entry.py` 怎么装引擎，再顺着 `graphon.graph_engine` 往下读。
- **想接私有模型或内部系统** → 写插件，不用 fork 核心。插件可贡献工具、模型、节点类型与 UI 扩展。
- **最大的攻击面是沙箱出网**。Code 节点一旦能随意出网就等于 SSRF 通道，出网白名单和 `ssrf_proxy` 的 ACL 是要盯的配置。
- **1.16 → 1.17 是破坏性升级**（Agent V2），按官方迁移说明走并先备份数据卷；别指望原地 `compose pull` 就能过。
- **向量库是可替换的**。别把「Dify 的向量存储」和「Postgres」绑死，生产选型时二者分开评估。

## Links

- [LLM](/docs/CS/AI/LLM/LLM.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [Redis](/docs/CS/DB/Redis/Redis.md)
- [向量数据库](/docs/CS/DB/Concept/vector.md)

## References

1. [Dify 开源仓库](https://github.com/langgenius/dify)
2. [Dify 1.17.1 Release](https://github.com/langgenius/dify/releases/tag/1.17.1)
3. [langgenius/graphon：Python 图执行引擎](https://github.com/langgenius/graphon)
4. [Dify 文档：Self-hosted deployment](https://docs.dify.ai/en/getting-started/install-self-hosted)
5. [Dify 插件开发文档](https://docs.dify.ai/en/plugins/quick-start/develop-plugins)
6. [Landlock LSM](https://landlock.io/)
7. [E2B 官方文档](https://e2b.dev/docs)
