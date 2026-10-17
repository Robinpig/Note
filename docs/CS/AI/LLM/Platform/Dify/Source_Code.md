## Introduction

这一篇是**代码地图**：仓库怎么分、关键包做什么、几个核心类与函数在哪、以及按什么顺序读最省力。静态结构见 [架构设计](/docs/CS/AI/LLM/Platform/Dify/Architecture.md)，运行时走向见 [链路设计](/docs/CS/AI/LLM/Platform/Dify/Pipeline.md)，产品与选型回到 [Dify](/docs/CS/AI/LLM/Platform/Dify.md)。

路径与行号取自 git tag `1.17.1`。

## Repository Map

Dify 已经不是「一个 Flask 应用」的单体仓库，而是多语言 monorepo（根目录有 `pnpm-workspace.yaml`、`vite.config.ts`、`Makefile`）：

| 顶层目录                  | 语言        | 内容                                                                    |
| :-------------------- | :-------- | :-------------------------------------------------------------------- |
| `api/`                | Python    | 服务端主体：Flask + Celery。笔记里 90% 的源码分析都在这                                |
| `web/`                | TypeScript | Next.js 前端（控制台 + WebApp）                                             |
| `packages/`           | TypeScript | 前端 monorepo 包：`dify-ui`、`contracts`、`dev-proxy`、`jotai-tanstack-form`、`nuqs-jotai` 等 |
| `dify-agent/`         | Python    | Agent V2 侧代码（含 `dify_agent.server.app`，对外 5050）                       |
| `dify-agent-runtime/` | Go        | `shellctl` 沙箱服务（对外 5004）、`runner`、`sanitize-pty`、`dify-agent-cli`     |
| `sdks/`               | 多语言      | 官方 SDK                                                                |
| `cli/`                | Python    | 命令行工具                                                                 |
| `docker/`             | YAML      | compose 编排与 `.env.example`                                            |
| `e2e/`                | TypeScript | 端到端测试                                                                 |

前端与 Python 侧由 pnpm workspace 统一；Python 侧用 uv（`uv.lock`），向量库等可插拔能力放在 `api/providers/` 下作为独立包。

### `api/` 的顶层包

```
api/
├── app.py                 进程入口：gevent monkey patch 时机 / db 命令分流
├── app_factory.py         create_app()：扩展按固定顺序初始化（30 个）
├── dify_app.py            class DifyApp(Flask)：只加类型标注
├── celery_entrypoint.py   Celery 侧 gevent patch，导出 celery
├── extensions/            Flask 扩展装配（ext_database / ext_redis / ext_storage / ext_celery ...）
├── controllers/           传输层（控制台 API / Service API / Web API）
├── services/              应用层（新服务禁止依赖 flask / models / repositories）
├── core/                  领域层（app / rag / workflow / plugin / agent / mcp / trigger ...）
├── models/                SQLAlchemy ORM
├── repositories/          仓储
├── tasks/                 Celery 任务（59 个顶层文件 + 5 个子包）
├── schedule/              beat 定时任务（14 个）
├── clients/               外部服务客户端（如 clients/agent_backend）
├── providers/             vdb 等可插拔 provider 包
├── machinery/             框架中立的 API 机制层
├── libs/                  共享库
├── migrations/            Alembic 迁移
└── .importlinter          分层契约（controllers → services → core → libs）
```

`app.py` 里有个容易忽略的细节：gevent 的 monkey patch **只在 `__main__` 分支里做**，`flask db` 迁移命令走 `is_db_command()` 分支绕过它：

```python
# api/app.py:11-20
if __name__ == "__main__":
    from gevent import monkey
    monkey.patch_all()
    import psycogreen.gevent as psycogreen_gevent
    from grpc.experimental import gevent as grpc_gevent
    grpc_gevent.init_gevent()
    psycogreen_gevent.patch_psycopg()
```

扩展初始化顺序有硬依赖（注释写在 `app_factory.py` 里）：`ext_storage` 早于 `ext_key_provider`（RSA 私钥从存储读），也早于 `ext_logstore`。

## How Nodes Are Registered and Injected

这是 1.17 最值得学的一处设计。节点不是靠一张手写注册表，而是**扫包 + import 副作用自注册 + 构造函数注入**：

```python
# api/core/workflow/node_factory.py:112-136
def _import_node_package(package_name: str, *, excluded_modules=frozenset()) -> None:
    package = importlib.import_module(package_name)
    for _, module_name, _ in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        if module_name in excluded_modules:
            continue
        importlib.import_module(module_name)

@lru_cache(maxsize=1)
def register_nodes() -> None:
    _import_node_package("graphon.nodes")        # 通用节点
    _import_node_package("core.workflow.nodes")  # Dify 特有节点

def get_node_type_classes_mapping() -> Mapping[NodeType, Mapping[str, type[Node]]]:
    register_nodes()
    return Node.get_node_type_classes_mapping()
```

按 type + version 解析：

```python
# :139
def resolve_workflow_node_class(*, node_type, node_version, node_data=None) -> type[Node]:
    node_mapping = get_node_type_classes_mapping().get(node_type)
    ...
    # 历史 Agent 节点也用过 version=2，只有显式 kind 标记才算新版 Dify Agent
    if node_data is not None and node_type == BuiltinNodeTypes.AGENT \
       and node_version == "2" and not is_dify_agent_node_data(node_data):
        node_version = "1"
    node_class = node_mapping.get(node_version) or node_mapping.get(LATEST_VERSION)
```

那段版本纠偏注释很实在：旧 Agent 节点曾经用 `version=2` 表示工具参数格式，后来 V2 节点也叫 `2`，只能靠 `kind` 标记区分。这种「历史包袱用显式判别式兜住」的写法，比强行统一版本号安全。

`DifyNodeFactory` 用一张 `node_type → lambda` 的表决定每个节点注入什么依赖，例如 LLM 类节点：

```python
# :455 / :469 / :479
BuiltinNodeTypes.LLM:                 lambda: self._build_llm_compatible_node_init_kwargs(node_data),
BuiltinNodeTypes.QUESTION_CLASSIFIER: lambda: self._build_llm_compatible_node_init_kwargs(node_data),
BuiltinNodeTypes.PARAMETER_EXTRACTOR: lambda: self._build_llm_compatible_node_init_kwargs(node_data),
```

Agent V2 一次注入九个协作者（`_build_agent_node_init_kwargs`，`:550-581`）：`binding_resolver`、`runtime_request_builder`、`agent_backend_client`、`event_adapter`、`output_adapter`、`type_checker`、`failure_orchestrator`、`session_store`。其中 `agent_backend_client` 由工厂创建，带 `use_fake` / `fake_scenario` / `stream_read_timeout_seconds` / `stream_max_reconnects`。

## The Adapter Layer: node_runtime.py

`core/workflow/node_runtime.py`（约 1000 行）几乎是纯粹的**端口实现**，把 graphon 定义的 Protocol 一个个接到 Dify 的能力上：

| 类                                  | 实现的协议                                 | 作用                                |
| :--------------------------------- | :------------------------------------ | :-------------------------------- |
| `DifyPreparedLLM`                  | `LLMProtocol`                         | 把 `ModelInstance` 包装成引擎可调用的模型；含 `invoke_llm` / `invoke_llm_with_structured_output` / `get_llm_num_tokens` |
| `DifyPreparedPollingLLM`           | `LLMPollingCapableProtocol`           | 支持异步轮询的模型（长任务），并做配额结算 `_settle_polling_quota` |
| `DifyToolNodeRuntime`              | `ToolNodeRuntimeProtocol`             | 工具节点运行时：取运行时参数、invoke、用量统计、图标解析、异常映射 |
| `DifyFileReferenceFactory`         | `FileReferenceFactoryProtocol`        | 从任意 mapping 还原出文件引用                 |
| `DifyRetrieverAttachmentLoader`    | `RetrieverAttachmentLoaderProtocol`   | 按 segment_id 加载检索命中的附件                |
| `DifyPromptMessageSerializer`      | `PromptMessageSerializerProtocol`     | prompt message 序列化                    |
| `DifyHumanInputNodeRuntime`        | —（Dify 自有）                            | HITL 表单：创建、回填已提交数据、投递渠道、UI 展示控制       |

`DifyToolNodeRuntime` 里几个私有方法值得单独看，它们承担了「把 Dify 老的工具模型翻译成引擎新语义」的脏活：`_tool_from_handle`、`_binding_from_handle`、`_build_tool_runtime_spec`、`_is_workflow_tool_provider`、`_adapt_messages`、`_convert_message`、`_map_invocation_exception`。

## WorkflowEntry: Engine Assembly

`core/workflow/workflow_entry.py`（605 行）是 Dify 侧组装引擎的地方：

```python
# :103
def __init__(self, tenant_id, app_id, workflow_id, graph_config, graph: Graph,
             user_id, user_from, invoke_from, call_depth,
             variable_pool: VariablePool, graph_runtime_state: GraphRuntimeState,
             command_channel: CommandChannel | None = None,       # 默认 InMemoryChannel，:145
             response_stream_filter: ResponseStreamFilter | None = None):
```
```python
# :152-163
self.graph_engine = GraphEngine(
    workflow_id=workflow_id, graph=graph,
    graph_runtime_state=graph_runtime_state,
    command_channel=command_channel,
    config=GraphEngineConfig(
        min_workers=dify_config.GRAPH_ENGINE_MIN_WORKERS,
        max_workers=dify_config.GRAPH_ENGINE_MAX_WORKERS,
        scale_up_threshold=dify_config.GRAPH_ENGINE_SCALE_UP_THRESHOLD,
        scale_down_idle_time=dify_config.GRAPH_ENGINE_SCALE_DOWN_IDLE_TIME,
    ),
)
```
```python
# :187
def run(self) -> Generator[GraphEngineEvent, None, None]:
    try:
        yield from iter_dify_graph_engine_events(self.graph_engine, self._response_stream_filter)
    except GenerateTaskStoppedError:
        pass                                   # 用户主动停止：静默结束
    except Exception as e:
        logger.exception("Unknown Error when workflow entry running")
        yield GraphRunFailedEvent(error=str(e))
```

关键点：

- **worker 数是动态调整的**，`GraphEngineConfig` 给的是 `min_workers` / `max_workers` / 扩缩容阈值，引擎自己按负载伸缩——所以「并发跑多少分支」不是靠 Celery 并发度控制的
- **`command_channel` 默认为 `InMemoryChannel`**，即单进程内的暂停/恢复通道；跨进程恢复要靠分布式实现（`graphon.graph_engine.command_channels`）
- **开始节点不只 `START`**：`_START_NODE_TYPES = {START, DATASOURCE} ∪ TRIGGER_NODE_TYPES`（`:82-83`），这是 1.17 加了数据源与触发器节点之后的变化
- 除了 `run()`，还有 `single_step_run`（`:202`，单步调试）和 `run_free_node`（`:364`，游离节点测试）

## Variables

变量系统的三件套：

| 文件                             | 职责                                                                              |
| :----------------------------- | :------------------------------------------------------------------------------ |
| `variable_pool_initializer.py` | 只有两个函数：`add_variables_to_pool()` 与 `add_node_inputs_to_pool(node_id, inputs, aliases)`。后者会把同一份输入同时写进主 node_id 和若干别名，用于兼容改名/迁移 |
| `system_variables.py`          | `sys.` 前缀的系统变量：`SystemVariableKey`、`build_system_variables()`、`build_bootstrap_variables()`，以及一系列 `get_system_*` 读取器和 `preload_node_creation_variables()` |
| `variable_prefixes.py`         | 前缀常量，如 `ENVIRONMENT_VARIABLE_NODE_ID`                                              |

读取系统变量统一走 `_VariablePoolReader` Protocol（`get` / `get_by_prefix`），写入侧再叠加 `add`——**读写接口分开定义**，让「只读运行时状态」这类包装（graphon 的 `ReadOnlyGraphRuntimeStateWrapper`）能自然实现。

## AppRunner Family

`core/app/apps/` 按应用类型分目录，每个目录里通常有 `app_generator.py` + `app_runner.py`：

```
apps/
├── base_app_runner.py              共享工具方法（无 run()）
├── base_app_generator.py
├── base_app_queue_manager.py       PublishFrom / listen() / publish()
├── message_based_app_generator.py  _handle_response() + Redis 订阅 topic
├── message_based_app_queue_manager.py
├── workflow_app_runner.py          Workflow / Advanced-Chat 的执行入口
├── chat/  completion/  advanced_chat/  agent_chat/  agent_app/  pipeline/
└── task_pipeline/                  based_generate_task_pipeline 等
```

⚠️ **基类 `AppRunner` 没有 `run()`，也不是 ABC**（`base_app_runner.py:55`），它只是工具方法集合（`organize_prompt_messages`、`direct_output`、`_handle_invoke_result`、`moderation_for_inputs` 等）。各子类的 `run()` 签名**互不统一**：

```python
# chat/app_runner.py:34
def run(self, application_generate_entity, queue_manager, conversation, message, session)

# completion/app_runner.py:33
def run(self, application_generate_entity, queue_manager, message, session)

# workflow/app_runner.py:81
def run(self)                 # 其余状态从 self._workflow / 构造参数拿
```

所以不要指望通过基类抽象出统一的执行入口——想加新的应用形态，得照着现有某个 runner 抄一遍约定。

`apps/` 根上还挂着几个协调类（如 `execution_coordinator.py`、`draft_variable_saver.py`、`streaming_utils.py`），是 1.17 新增的横切能力：执行协调、草稿变量落库、流式工具函数。

## RAG Module Anatomy

```
core/rag/
├── datasource/        检索数据源抽象 + vdb provider（33 种 VectorType）
├── extractor/         文档抽取（PDF / Word / Notion / Web ...）
├── splitter/          切分（含父子分段）
├── cleaner/           文本清洗
├── embedding/         embedding 调用与缓存
├── rerank/            rerank 模型与加权分数两种模式
├── data_post_processor/  检索后处理（去重 + rerank）
├── retrieval/         dataset_retrieval（编排）、retrieval_methods（模式枚举）、router/
├── index_processor/   索引：工厂 + 基类 + 三种实现
├── docstore/          文档存储
├── summary_index/     摘要索引
├── pipeline/          RAG 管线编排（含 TenantIsolatedTaskQueue）
├── models/  entities/
```

索引侧的接口很干净（`index_processor_base.py:46`），七个抽象方法：`extract` / `transform` / `generate_summary_preview` / `load` / `clean` / `index` / `format_preview`，外加一个共享的 `_get_splitter()`。三种结构：

| `IndexStructureType`   | 值                    | Processor                     |
| :-------------------- | :------------------- | :--------------------------- |
| `PARAGRAPH_INDEX`     | `text_model`         | `ParagraphIndexProcessor`    |
| `QA_INDEX`            | `qa_model`           | `QAIndexProcessor`           |
| `PARENT_CHILD_INDEX`  | `hierarchical_model` | `ParentChildIndexProcessor`  |

检索侧的两层分工：

- `DatasetRetrieval`（`retrieval/dataset_retrieval.py`，2000+ 行）—— **编排层**：处理多数据集、元数据过滤、external/dify 来源拆分、组装 `DocumentContext`、回调来源信息。新入口 `knowledge_retrieval()`（`:155`）接受 `KnowledgeRetrievalRequest` 返回 `list[Source]`，比老的 `retrieve()`（`:392`）返回 tuple 更规整
- `RetrievalService`（`datasource/retrieval_service.py:93`）—— **执行层**：按 `retrieval_method` 分派到 `keyword_search` / `embedding_search` / `full_text_index_search`，用 `ThreadPoolExecutor(max_workers=RETRIEVAL_SERVICE_EXECUTORS)` 并行多路，再统一后处理

`DataPostProcessor`（`data_post_processor/data_post_processor.py:38`）是 rerank 的唯一入口，`invoke()` 里判断是否真跑 rerank：

```python
def invoke(self, query, documents, score_threshold, top_n, query_type):
    if self.rerank_runner:
        documents = self.rerank_runner.run(query, documents, score_threshold, top_n, query_type)
```

`rerank_runner` 由 `RerankRunnerFactory.create_rerank_runner()` 按 `RerankMode`（`reranking_model` / `weighted_score`）创建。注意 `retrieval_service.py:910` 那句补偿逻辑：**如果没跑 rerank 但配了 `score_threshold`，会退回按向量分数过滤**——否则阈值就静默失效了。

## Events and Queue Data Structures

`core/app/entities/queue_entities.py` 定的是链路上的「通用语言」：

| 类型                        | 行号   | 说明                                                    |
| :------------------------ | :--- | :---------------------------------------------------- |
| `QueueEvent`              | 17   | 事件名枚举（约 32 个取值），涵盖文本流 / 节点 / 容器 / 控制 / HITL |
| `AppQueueEvent`           | 57   | 抽象基类，只有一个 `event: QueueEvent` 字段                   |
| `QueueStopEvent`          | 486  | 带 `StopBy`（`:491`）：USER_MANUAL / ANNOTATION_REPLY / OUTPUT_MODERATION / INPUT_MODERATION |
| `QueueErrorEvent`         | 469  | 错误事件                                                  |
| `QueuePingEvent`          | 478  | 保活                                                    |
| `QueueWorkflowPausedEvent`| 582  | 暂停（HITL）                                             |
| `QueueMessage`            | 555  | 信封：`task_id` / `app_mode` / `event`                 |
| `MessageQueueMessage`     | 565  | 加 `message_id` / `conversation_id`                    |
| `WorkflowQueueMessage`    | 574  | 工作流专用信封                                              |

`AppQueueManager`（`base_app_queue_manager.py:50`）提供 `listen()` 生成器与 `publish(event, PublishFrom)`，其中 `PublishFrom`（`:45`）区分事件来自应用管理层还是任务管线——**这个字段存在的意义是让「停止」这类控制事件有明确的来源归属**，避免误判。

## Recommended Reading Order

想搞清楚「一条工作流怎么跑起来」，按这个顺序读，每一步只引入前一步已出现的东西：

1. `api/app.py` → `api/app_factory.py` —— 进程怎么起、扩展什么顺序
2. `api/docker/entrypoint.sh` —— 一个镜像怎么分饰 api / worker / beat
3. `api/controllers/service_api/app/completion.py` —— 对外入口长什么样
4. `api/services/app_generate_service.py` —— 调度与分流
5. `api/core/app/apps/chat/app_generator.py` —— **关键岔路口**：进程内线程
6. `api/core/app/entities/queue_entities.py` —— 事件词汇表（后面所有代码都靠它）
7. `api/core/app/apps/chat/app_runner.py` —— 真正执行
8. `api/core/workflow/workflow_entry.py` → `node_factory.py` → `node_runtime.py` —— 工作流引擎（先整体后细节）
9. `api/core/rag/index_processor/` 与 `api/core/rag/retrieval/` —— RAG 两阶段
10. `langgenius/graphon` —— 节点实现在这里，Dify 仓库里找不到

## Links

- [LLM](/docs/CS/AI/LLM/LLM.md)
- [RAG](/docs/CS/AI/RAG.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [Dify 架构设计](/docs/CS/AI/LLM/Platform/Dify/Architecture.md)
- [LLM 应用开发平台](/docs/CS/AI/LLM/Platform/Platform.md)

## References

1. [Dify 开源仓库](https://github.com/langgenius/dify)
2. [langgenius/graphon](https://github.com/langgenius/graphon)
3. [Dify 后端 AGENTS.md（贡献指引）](https://github.com/langgenius/dify/blob/main/api/AGENTS.md)
4. [import-linter 文档](https://import-linter.readthedocs.io/)
5. [Celery 官方文档](https://docs.celeryq.dev/)
6. [OpenDAL 文档](https://opendal.apache.org/)
