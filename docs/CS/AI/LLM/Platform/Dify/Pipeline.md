## Introduction

这一篇拆 Dify 的**运行时链路**：一条请求从 HTTP 进来，经过哪些层，事件和数据往哪里流，异步部分交给谁。静态结构（进程、分层、存储、边界）见 [架构设计](/docs/CS/AI/LLM/Platform/Dify/Architecture.md)，具体类与函数签名见 [源码分析](/docs/CS/AI/LLM/Platform/Dify/Source_Code.md)。

一句话概括全貌：**Chat / Completion 走进程内线程 + 进程内队列；Workflow / Advanced-Chat 走 Celery + Redis Pub/Sub**。这两条路径的实现差别很大，混着读容易乱。

## Chat and Completion: In-Process Worker Thread

```
POST /v1/chat-messages (service_api)
   │  controllers/service_api/app/completion.py:325  class ChatApi.post
   ▼
AppGenerateService.generate(...)          services/app_generate_service.py:101
   │  :138 _run_with_guardrails   :170 _dispatch_generate
   ▼
ChatAppGenerator().generate(...)          core/app/apps/chat/app_generator.py
   │  :220 worker_with_context()  ← 包一层请求上下文
   │  :230 threading.Thread(target=worker_with_context).start()      ★ 进程内线程
   ▼  _generate_worker(...)              :246
ChatAppRunner().run(                      core/app/apps/chat/app_runner.py:34
      application_generate_entity, queue_manager,
      conversation, message, session)
   │
   ├─ 组装 prompt / 取 memory / 调模型（经 plugin daemon）
   │     每产出一段 → queue_manager.publish(QueueLLMChunkEvent / QueueTextChunkEvent ...)
   ▼
MessageBasedAppQueueManager._publish()    :30
   │  self._q.put(MessageQueueMessage(...))      ★ 进程内 queue.Queue
   ▼
queue_manager.listen() 生成器              base_app_queue_manager.py:76
   │  HTTP 层直接迭代 → SSE / blocking JSON
   ▼
客户端
```

三个容易踩错的点：

**1. 它不是 Celery。** 生成逻辑跑在 API 进程内的 `threading.Thread` 里（`chat/app_generator.py:230`、`completion/app_generator.py:209`）。这意味着：

- API 进程被 OOM kill 或重启 → 正在生成的请求直接断，没有重试
- 并发生成会占用 API 进程的 worker 连接（`SERVER_WORKER_CONNECTIONS` 默认只有 10）
- 水平扩容 API 副本不能靠「多起几个 worker」实现，得靠 LB

**2. Redis 在这条链路里只做两件小事**，不是数据通道：

```python
# core/app/apps/base_app_queue_manager.py:62
redis_client.setex(self._task_belong_cache_key, 1800, f"{user_prefix}-{self._user_id}")
```

即：把 `task_id → user_id` 的归属关系写进 Redis（TTL 1800s），以及 `_is_stopped()` 轮询停止标记。真正的事件流是进程内 `queue.Queue`。

**3. 停止是协作式的。** 用户在 UI 点「停止」只是写了个 flag，runner 一侧在循环里检查 flag 后自己退出，靠 `GenerateTaskStoppedError` 收尾（`workflow_entry.py:187-198` 专门 catch 它并静默结束）。

### 事件类型

`core/app/entities/queue_entities.py:17` 的 `QueueEvent` 是统一枚举，抽象基类是 `AppQueueEvent`：

| 类别      | 取值                                                                                          |
| :------ | :------------------------------------------------------------------------------------------ |
| 文本流    | `llm_chunk`、`text_chunk`、`reasoning_chunk`、`agent_message`、`agent_thought`、`message_replace` |
| 结束      | `message_end`、`advanced_chat_message_end`、`message_file`、`annotation_reply`                  |
| 工作流    | `workflow_started`、`workflow_succeeded`、`workflow_failed`、`workflow_partial_succeeded`       |
| 节点      | `node_started`、`node_succeeded`、`node_failed`、`node_exception`                              |
| 容器      | `iteration_start/next/completed`、`loop_start/next/completed`                               |
| 控制      | `error`、`ping`、`stop`、`retry`、`pause`、`retriever_resources`、`agent_log`                  |
| HITL    | `human_input_form_filled`、`human_input_form_timeout`                                      |

`ping` 值得注意：runner 空闲时会周期性发 ping（`base_app_queue_manager.py:105`），既是保活也是给前端的「我还在跑」信号——长思考模型下没有它，客户端很容易误判超时。

## Workflow: GraphEngine and Layers

```
WorkflowAppRunner.run()                   core/app/apps/workflow/app_runner.py:81
   │
   ├─ 构建 Graph（graphon）+ 初始化 VariablePool / GraphRuntimeState
   │
   ├─ WorkflowEntry(...)                  :183
   │     graph_engine = GraphEngine(graph, graph_runtime_state,
   │                                command_channel, GraphEngineConfig(
   │                                  min_workers/max_workers/
   │                                  scale_up_threshold/scale_down_idle_time))
   │     graph_engine.layer(ExecutionLimitsLayer(max_steps, max_time))   :181
   │     graph_engine.layer(ObservabilityLayer())                        :185（开启 OTEL 时）
   │
   ├─ 追加 Dify 特有的 layers
   │     WorkflowPersistenceLayer                                       :212
   │     workflow agent workspace retirement layer                      :213
   │
   ▼
for event in workflow_entry.run():        :229
      self._handle_event(workflow_entry, event)
```

`WorkflowEntry.run()` 是**生成器**，事件经过一层过滤后才交给调用方：

```python
# core/workflow/workflow_entry.py:56
def iter_dify_graph_engine_events(engine, response_stream_filter=None):
    yield from filter_graph_events(
        engine.run(),
        context=GraphEventFilterContext.from_engine(engine),
        filters=[HumanInputFormEventFilter(form_repository=HumanInputFormSubmissionRepository()),
                 response_stream_filter or ResponseStreamFilter()],
    )
```

这个过滤器链是 1.17 的工程细节之一：**HITL 表单事件与「续跑时的历史事件」都在这里被裁剪**，使得同一个 runner 既能产出首跑事件流，也能产出暂停后恢复的事件流，而上层 `retrieve_events` 不用关心差异。

### 异步执行

Workflow / Advanced-Chat 走 Celery，链路是「先订阅，再投递」：

```python
# services/app_generate_service.py:264-278（Advanced-Chat）
def on_subscribe():
    workflow_based_app_execution_task.delay(payload_json)
generator.retrieve_events(AppMode.ADVANCED_CHAT, payload.workflow_run_id,
                          on_subscribe=on_subscribe)
```

- 任务：`tasks/app_generate/workflow_execute_task.py:472` 的 `workflow_based_app_execution_task`，队列 `workflow_based_app_execution`
- 回传：worker 侧 `topic.publish(payload.encode())`（`:439`），topic key 形如 `channel:{app_mode}:{workflow_run_id}`（`message_based_app_generator.py:307`）
- 终止事件：`workflow_finished`、`workflow_paused`（`:415`）——收到任一即关闭流
- 续跑：`resume_app_execution`（`:758`）

顺序很重要：**先建立订阅再投递任务**，否则 worker 跑得比订阅快就会丢事件。这是 Pub/Sub 做流式回传的经典坑。

## RAG Indexing Pipeline

```
上传文档
   │  controllers/.../document.py
   ▼
document_indexing_task(dataset_id, document_ids)      tasks/document_indexing_task.py:33  @shared_task(queue="dataset")
   │  租户隔离：:200 _document_indexing_with_tenant_queue → TenantIsolatedTaskQueue
   ▼
IndexingRunner.run(dataset_documents, session)        core/indexing_runner.py:81
   │
   ├─ IndexProcessorFactory(index_type).init_index_processor()   :110
   │     text_model   → ParagraphIndexProcessor
   │     qa_model     → QAIndexProcessor
   │     hierarchical_model → ParentChildIndexProcessor
   │
   ├─ _extract()   :448  → processor.extract(ExtractSetting) → 抽取文本/图片
   ├─ _transform() :847  → processor.transform(documents)
   │        ├── CleanProcessor.clean()          清洗
   │        ├── _get_splitter(...) → 切分（含父子分段）
   │        └── 写 doc_id / doc_hash 元数据
   └─ _load()      :643  → ThreadPoolExecutor + _process_chunk :744
             └── processor.load(dataset, documents, ...)
                    ├── HIGH_QUALITY → Vector(dataset).create(documents)        向量索引
                    │                  + create_multimodal(...)（多模态）
                    └── with_keywords → Keyword(dataset).add_texts(documents)   关键词索引
```

`BaseIndexProcessor` 是抽象接口，七个抽象方法：`extract`、`transform`、`generate_summary_preview`、`load`、`clean`、`index`、`format_preview`。索引结构三种（`IndexStructureType`：`text_model` / `qa_model` / `hierarchical_model`），档位两种（`IndexTechniqueType`：`economy` / `high_quality`）。

一个容易误解的设计：**高质量索引下 `with_keywords` 会被置为 `False`**（`paragraph_index_processor.py:146`）——向量索引建立后不再额外建关键词索引，走的是向量检索（必要时 rerank），而不是「关键词 + 向量各查一遍」。混合检索是否发生由检索阶段的 `search_method` 决定，不是索引阶段。

## RAG Retrieval Pipeline

```
知识检索节点 / 引用归属
   │
   ▼
DatasetRetrieval.retrieve(...)            core/rag/retrieval/dataset_retrieval.py:392
   │  新入口：knowledge_retrieval(...)    :155（走 KnowledgeRetrievalRequest → list[Source]）
   │  _on_query()                         :1087
   ▼
RetrievalService.retrieve(                core/rag/datasource/retrieval_service.py:97
      retrieval_method, dataset_id, query,
      top_k, score_threshold, reranking_model, reranking_mode, weights,
      document_ids_filter, attachment_ids)
   │
   ├─ 元数据过滤（document_ids_filter / attachment_ids）
   │
   ├─ KEYWORD_SEARCH        → keyword_search()            :271
   ├─ 支持语义（SEMANTIC / HYBRID）→ embedding_search()   :303
   ├─ 支持全文（FULL_TEXT / HYBRID） → full_text_index_search() :412
   │      （各路内部各自 rerank 一次）
   │
   ├─ HYBRID 统一后处理                    :881-909
   │      _deduplicate_documents()
   │      DataPostProcessor.invoke(query, documents, score_threshold, top_n, query_type)
   │           └── rerank_runner.run(...)  ← RerankModel 或 WeightedScore
   │
   └─ 阈值补偿：若没跑 rerank 但有 score_threshold，按向量分数过滤  :910
```

检索模式四种（`retrieval_methods.py:4`）：`semantic_search`、`full_text_search`、`hybrid_search`、`keyword_search`。选择逻辑在 `dataset_retrieval.py:737-740`：

```python
if selected_dataset.indexing_technique == IndexTechniqueType.ECONOMY:
    retrieval_method = RetrievalMethod.KEYWORD_SEARCH
else:
    retrieval_method = retrieval_model_config["search_method"]
```

**经济型索引只能是关键词检索**——这是常被忽略的一条硬约束。想要语义检索就得用高质量索引（要 embedding 成本）。

rerank 有两种模式（`RerankMode`）：`reranking_model`（接 rerank 模型）与 `weighted_score`（加权分数融合）。介入点在混合检索合并之后，但**单路检索里也各自跑一次**。

结果组装在 `dataset_retrieval.py:512` 之后：先按 `provider` 把 `dify` 与 `external` 两类文档分开，dify 侧经 `format_retrieval_documents()` 规整（有 answer 拼 `question:/answer:`，有 summary 拼摘要），最后 `hit_callback.return_retriever_resource_info()` 把来源信息抛给上层做引用展示。

## Agent: Two Generations Side by Side

### 旧 Agent：策略在运行时决定

`core/agent/entities.py:78-79` 定义两种策略：`chain-of-thought`（`CotAgentRunner`）与 `function-calling`（`FunctionCallAgentRunner`）。选择不是配置死的，而是在 `agent_chat/app_runner.py:196` 按模型 schema 特性自动升级：

```python
if {ModelFeature.MULTI_TOOL_CALL, ModelFeature.TOOL_CALL}.intersection(model_schema.features or []):
    agent_entity.strategy = AgentEntity.Strategy.FUNCTION_CALLING
```

即：**模型支持 tool call 就用 Function Calling，否则退回 ReAct（CoT）**。CoT 又按模型是 CHAT 还是 COMPLETION 再分 `CotChatAgentRunner` / `CotCompletionAgentRunner`。最大迭代 `max_iteration: int = 10`。

### Agent V2：跨进程调用

V2 节点（`nodes/agent_v2/agent_node.py:80`，`version() == "2"`）不再在 Dify 进程里跑循环，而是通过注入的 `agent_backend_client` 调 `agent_backend` 服务：

```python
create_response = self._agent_backend_client.create_run(runtime_request.request)     # :319
for public_event in self._agent_backend_client.stream_events(...):                    # :528
    ...
public_event = self._agent_backend_client.cancel_run_and_wait(...)                    # :625
```

客户端由 `node_factory` 注入（`node_factory.py:550-581`），同时注入的还有 `binding_resolver`、`runtime_request_builder`、`event_adapter`、`output_adapter`、`type_checker`、`failure_orchestrator`、`session_store`——**这是一个教科书式的构造函数注入**，节点本身几乎不含 Dify 业务逻辑，全部靠外部拼装。好处是可测（有 `FakeAgentBackendRunClient`），代价是看一个节点的行为要跳七八个文件。

V2 还带 `use_fake` 开关（`AGENT_BACKEND_USE_FAKE` + `AGENT_BACKEND_FAKE_SCENARIO`），可以在不启沙箱的情况下跑通链路——调试时很省事。

## Queues and Schedules

Celery 队列（自托管默认值，来自 `api/docker/entrypoint.sh:41`）：

```
api_token, dataset, dataset_summary, priority_dataset, priority_pipeline, pipeline,
mail, ops_trace, app_deletion, app_rbac, plugin, workflow_storage, conversation,
workflow, schedule_poller, schedule_executor, triggered_workflow_dispatcher,
trigger_refresh_publisher, trigger_refresh_executor, retention,
workflow_based_app_execution
```

几点实用判断：

- `dataset` 与 `priority_dataset`、`pipeline` 与 `priority_pipeline` 是**成对出现的优先级队列**，忙的时候可以单独给高优队列多起 worker
- `workflow` 在 Cloud 版拆成 `workflow_professional / workflow_team / workflow_sandbox`，做多租户隔离
- `workflow_based_app_execution` 专供 Workflow / Advanced-Chat 的异步执行，是**流式链路的入口队列**，它积压 = 用户看到请求卡住不返回首个 token，要单独盯
- `retention`、`app_deletion` 这类是后台数据清理，积压不致命但会让磁盘慢慢涨

定时任务在 `api/schedule/`（14 个），由 `ext_celery.py:300` 的 `beat_schedule` 注册。典型：

| 任务                            | 频率                                    |
| :---------------------------- | :------------------------------------ |
| `clean_embedding_cache_task`  | 每 N 天 02:00                            |
| `clean_unused_datasets_task` | 每 N 天 03:00                            |
| `clean_messages`             | 每 N 天 04:00                            |
| `clean_workflow_runs_task`   | 每天 00:00                              |
| `check_upgradable_plugin_task` | 每 15 分钟                               |
| `workflow_schedule_task`      | 每 `WORKFLOW_SCHEDULE_POLLER_INTERVAL`   |
| `human_input_form_timeout`    | 每 `HUMAN_INPUT_TIMEOUT_TASK_INTERVAL`   |
| `datasets-queue-monitor`      | 每 `QUEUE_MONITOR_INTERVAL`（默认 30 分钟） |

自建时最该先确认的是 `clean_messages` 与 `clean_workflow_runs_task` 的保留天数——消息和工作流运行记录是最容易把 Postgres 撑爆的两张表。

## Links

- [LLM](/docs/CS/AI/LLM/LLM.md)
- [RAG](/docs/CS/AI/RAG.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)
- [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)

## References

1. [Dify 开源仓库](https://github.com/langgenius/dify)
2. [langgenius/graphon](https://github.com/langgenius/graphon)
3. [Dify 工作流文档](https://docs.dify.ai/en/guides/workflow)
4. [Dify 知识库文档](https://docs.dify.ai/en/guides/knowledge-base)
5. [Celery 官方文档](https://docs.celeryq.dev/)
6. [Amazon Bedrock AgentCore 上跑 Dify DSL 的实践记录](https://aws.amazon.com/cn/blogs/china/amazon-bedrock-agentcore-practice-validation/)
