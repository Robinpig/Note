## Introduction

这一篇回答 Coze Studio「**一次请求怎么流**」：画布上的一张图如何变成可执行对象、执行时事件怎么回流到前端、Agent 与 RAG 各走哪条路。静态结构见 [架构设计](/docs/CS/AI/LLM/Platform/Coze/Architecture.md)，代码地图见 [源码分析](/docs/CS/AI/LLM/Platform/Coze/Source_Code.md)，产品视角回到 [Coze](/docs/CS/AI/LLM/Platform/Coze.md)。

贯穿全篇的一条主线：**Coze 的"编排"基本不自己实现，而是把画布翻译成 Eino 的图**。理解了翻译的每一步，剩下的都是 Eino 的语义。

基线 `v0.5.1`。

## From Canvas to Runnable

工作流在库里存的是前端画布 JSON（`entity/vo/canvas.go`，存在 `workflow` 表的 `canvas` 字段）。执行前必须完成一次转换：

```
canvas JSON（前端 FlowGram 产物）
   │  sonic.Unmarshal → *vo.Canvas
   ▼
adaptor.CanvasToWorkflowSchema(ctx, c)          domain/workflow/internal/canvas/adaptor/to_schema.go
   │  → *schema.WorkflowSchema（Nodes / Connections / Hierarchy / CompositeNodes）
   ▼
compose.NewWorkflow(ctx, sc, opts...)           internal/compose/workflow.go:83
   │  ├─ AddCompositeNode / AddNode             :198 / :203
   │  ├─ resolveDependencies → compose.FieldMapping
   │  └─ Compile → compose.Runnable[map[string]any, map[string]any]
   ▼
Runner.Invoke / Stream                          :160-175
```

三个容易看漏的点：

1. **输入输出统一是 `map[string]any`**（`workflow.go:37`）。类型约束不写在 Go 泛型里，而是靠 schema 里的 `TypeInfo` 在 `ConvertInputs` 阶段做（`nodes.ConvertInputs(ctx, input, wf.Inputs(), ...)`），转换失败会返回 warnings 而不是直接报错。
2. **Entry / Exit 是隐式节点**。`wf.input` 取 Entry 节点的 OutputTypes，`wf.output` 取 Exit 节点的 InputTypes（`:111-114`）；画布上的"开始/结束"只是 UI 约定。
3. **循环、批处理这类"容器节点"是 CompositeNode**，内部会编译成一个子 `Runnable` 再挂到父节点上（`getInnerWorkflow`，`:331`），父子之间通过 `carryOvers`（`:195`）传递字段。

### 字段映射怎么算出来的

画布上"节点 B 的某个输入引用节点 A 的某个输出"，在 Eino 里是 `compose.FieldMapping`。`resolveDependencies`（`:625`）负责把引用关系翻译成映射，其中 `arrayDrillDown`（`:543`）处理"引用数组里的某个元素"这类下钻路径——这是可视化编排里最容易出错的一块，因为一个连线可能对应多条实际映射。

## Three Execution Modes

`domain/workflow/service/executable_impl.go` 提供三种入口，共用前半段（取版本 → 转 schema → 建 workflow → 转换输入），差别在最后一步：

| 入口 | 行号 | 行为 | 使用场景 |
| :-- | :-- | :-- | :-- |
| `SyncExecute` | `:52` | `wf.SyncRun` 阻塞跑完，等 `lastEvent` 通道收尾，返回完整 `WorkflowExecution` | 调试、API 同步调用 |
| `AsyncExecute` | `:208` | 只返回 `executeID`，中间结果不实时吐出，调用方轮询 `GetExecution` | 批处理、长任务 |
| `StreamExecute` | `:451` | 用 `schema.Pipe` 建一条缓冲为 10、元素为 `*entity.Message` 的流管道 → `wf.AsyncRun` → 返回 `*schema.StreamReader[*entity.Message]` | 对话、ChatFlow、画布实时调试 |

`StreamExecute` 的写法很典型（`:544-556`）：

```go
sr, sw := schema.Pipe[*entity.Message](10)

cancelCtx, executeID, opts, _, err := compose.NewWorkflowRunner(wfEntity.GetBasic(), workflowSC, config,
    compose.WithInput(inStr), compose.WithStreamWriter(sw)).Prepare(ctx)

wf.AsyncRun(cancelCtx, input, opts...)

return sr, nil
```

即：**执行在后台 goroutine，写端交给引擎，读端立刻返回给 handler**，handler 再用 `infra/sse` 把 `*entity.Message` 推成 SSE 帧。缓冲区只有 10，慢消费会反压到节点执行。

三种模式共用的前缀逻辑里还有两件事：ChatFlow 要回填历史轮次（`handleHistory`，`:495`）、应用级工作流在 release 模式下要校验发布版本（`checkApplicationWorkflowReleaseVersion`，`:473`）。

## Events and Callbacks

引擎侧不认识 Coze 的事件，Coze 也不改引擎——中间靠 **Eino 的 `callbacks.Handler`** 桥接。`internal/execute/callback.go` 实现三个 handler：

| Handler | 行号 | 挂在哪 | 产出 |
| :-- | :-- | :-- | :-- |
| `WorkflowHandler` | `:75` | 图（含子工作流，`:89`） | 工作流级 start / end / error / 中断 |
| `NodeHandler` | `:117` | 每个节点 | 节点 start / end / error / 流式增量 |
| `ToolHandler` | `:133` | 工具调用 | function_call / tool_response / tool_error |

它们把回调转成 `*Event`（`internal/execute/event.go:46`）推进 `chan<- *Event`，事件类型共 15 个（`event.go:27-44`）：

```
workflow_start / workflow_success / workflow_failed / workflow_cancel
workflow_interrupt / workflow_resume
node_start / node_end / node_end_streaming / node_error
node_streaming_input / node_streaming_output
function_call / tool_response / tool_streaming_response / tool_error
```

流式输出有两种处理路径（`callback.go:1068` / `:1102`）：`nonIncrementalEndProcessor` 与 `incrementalEndProcessor`，区别在于节点输出是"整块给"还是"按 chunk 累积"。前者用于代码节点这类一次性产出，后者用于 LLM 流式——对应前端上"打字机效果"与"一次性弹出"的差异。

`Event` 上还挂着三类业务信息：`Token`（`TokenInfo`，token 计费来源）、`InterruptEvents`（中断点）、`Answer`（增量文本）。

## Interrupt and Resume

Coze 支持"工作流跑到某个节点暂停、等用户输入、再继续"，实现完全依赖 Eino 的 checkpoint：

- 是否启用：`sc.RequireCheckpoint()` 决定，Agent 侧则是**只要有工具就强制开启**（`agent_flow_builder.go:162` 的 `requireCheckpoint = true`）；
- 存储：`compose.WithCheckPointStore(...)`，工作流用 `workflow2.GetRepository()`（`workflow.go:145`），Agent 用 `conf.CPStore`；底层是 Redis（`infra/checkpoint/redis.go`）；
- 恢复：`crossdomain/workflow` 暴露 `WithResumeToolWorkflow(resumingEvent, resumeData, allInterruptEvents)` 生成 `compose.Option`，下次执行时带上；
- 判错：`SyncExecute` 里先 `einoCompose.ExtractInterruptInfo(err)`——**中断是以 error 形式抛出的**，能提取出中断信息就不算失败（`:140`）。

中断点存 `interrupt_event_store.go`，触发问答节点或需要用户确认的工具调用时，前端拿到 `workflow_interrupt` 事件 + `InterruptEvents` 列表，用户回答后带着 `resumeData` 再调一次执行接口。

## The Agent Path

单 Agent（智能体）走得是**另一条图**，不是工作流：`domain/agent/singleagent/internal/agentflow/agent_flow_builder.go:60` 的 `BuildAgent`。

```
                    ┌──────────────────┐
   START ──────────▶│ personaRender    │  Jinja2 渲染人设（extractJinja2Placeholder）
        │           └────────┬─────────┘
        ├──────────▶ promptVariables ────────┐
        │                                    ▼
        ├──────────▶ knowledgeRetriever → knowledgeRetrieverPack   ┌──────────────┐
        │                                    │                     │ promptTemplate│ ChatTemplate
        └──────────▶ toolsPreRetriever ──────┴────────────────────▶│  (chatPrompt)│
                                                                   └──────┬───────┘
                                                                          ▼
                                              ┌───────────────────────────────────────┐
                                              │ agentNode                             │
                                              │  有工具 → react.NewAgent 导出子图      │
                                              │  无工具 → AddChatModelNode 裸模型      │
                                              └───────────────┬───────────────────────┘
                                                              ▼
                                             （可选）suggestGraph → END
```

几处设计值得注意：

- **有工具才走 ReAct**：`isReActAgent` 为真时用 `react.NewAgent(...).ExportGraph()` 把 ReAct 子图挂进主图（`:171-187`），并且**校验模型的 function call 能力**，不支持就直接报错而不是降级（`:164`）；
- **四条并行支路都从 START 出发**，汇聚到 `promptTemplate`，靠 `compose.WithNodeTriggerMode(compose.AllPredecessor)`（`:275`）保证"所有前驱完成才触发"——这就是 Coze 的 fan-in 语义；
- **工具来源有四类**：插件工具、工作流转成的工具（`ToolFromWorkflow`）、数据库工具、Agent 变量工具；其中"工作流作为 Agent 的工具"是 Coze 的一个特色能力（`WorkflowAsModelTool`）；
- **工具返回直达**：`ToolReturnDirectly` 允许某些工具的结果跳过模型直接返回给用户；
- **建议问题（suggest）** 是一条独立可选子图 `newSuggestGraph`，挂在 agentNode 之后。

运行侧 `AgentRunner.StreamExecute`（`agent_flow_runner.go:67`）负责把 `*AgentEvent` 流出去，`PreHandlerReq`（`:182`）做输入预处理：多模态能力探测（`isSupportImage/File/Audio/Video`）、历史裁剪、本地文件转 base64 等。

## RAG: Indexing and Retrieval

### 索引（异步，事件驱动）

```
上传/创建文档
   │  DocProcessor: BeforeCreate → BuildDBModel → InsertDBModel → Indexing
   ▼
KnowledgeEventProducer（NSQ）
   ▼
knowledgeSVC.HandleMessage            service/event_handle.go:51
   ├─ indexDocuments / indexDocument  :118 / :155
   ├─ processDocumentParsing          :261  解析（PARSER_TYPE: builtin / paddleocr；OCR: ve / paddleocr）
   ├─ processDocumentChunks           :378  切片
   ├─ convertToSlices → storeSlicesInDB      :488 / :551
   ├─ indexSlicesInSearchStores       :639  embedding → 写入 searchstore（Milvus / ES / OceanBase / VikingDB）
   └─ finalizeDocumentIndexing / setDocumentStatus  :402 / :703
```

表格类文档走单独分支（`handleTableDocument`，`:363`），之后可以走 NL2SQL 检索。

### 检索（同步，Eino Chain）

`service/retrieve.go:54` 的 `Retrieve` 本身就是一条 Eino 链：

```go
chain := compose.NewChain[*RetrieveContext, []*knowledgeModel.RetrieveSlice]()
parallelNode := compose.NewParallel().
    AddLambda("vectorRetrieveNode", vectorRetrieveNode).
    AddLambda("esRetrieveNode", EsRetrieveNode).
    AddLambda("nl2SqlRetrieveNode", Nl2SqlRetrieveNode).
    AddLambda("passRequestContext", passRequestContextNode)

r, _ := chain.
    AppendLambda(rewriteNode).        // query rewrite（messages2query，可带对话历史）
    AppendParallel(parallelNode).     // 三路召回并行
    AppendLambda(reRankNode).         // rerank（vikingdb 或 rrf）
    AppendLambda(packResult).         // 打包成 RetrieveSlice
    Compile(ctx)
```

结构上是标准的「改写 → 多路召回 → 重排 → 打包」，与 [RAG](/docs/CS/AI/RAG.md) 里的通用管线一致；特别之处是**把 NL2SQL 当成一路普通召回**，和向量、全文并列——表格知识库因此能直接用自然语言查。

## Tool and Plugin Execution

插件工具的执行在 `domain/plugin/service/exec_tool.go:45` 的 `ExecuteTool`，全部围绕 OpenAPI 3 的 schema 展开：

1. `buildToolExecutor`（`:138`）按插件状态取实现：草稿态（`getDraftAgentPluginInfo`）/ 线上态（`getOnlineAgentPluginInfo`）/ 工作流插件（`:351`）/ 调试态（`:440`）；
2. `acquireAccessTokenIfNeed`（`:96`）处理 OAuth：拿不到或过期就换 token；
3. HTTP 调用后 `processResponse`（`:680`）按 OpenAPI response schema 裁剪字段；
4. 响应不合规时按策略处理，三种（`InvalidRespProcessStrategy`）：`ReturnRaw`（原样返回）、`ReturnErr`（报错）、`ReturnDefault`（填默认值）——这是 Coze 对"第三方 API 不守约定"的兜底设计。

工具调用在链路上以 `function_call` / `tool_response` 事件呈现，与 [MCP](/docs/CS/AI/LLM/Protocol/MCP.md) 那套"工具声明 + 调用 + 回填"是同一个模型，只是 Coze 用 OpenAPI 而非 MCP schema 描述工具。

## End-to-End: A Chat Turn

把上面几块串起来，一次「用户在 Coze 应用里发一句话」的完整走向：

1. 浏览器 SSE 连到 `/api/...`，nginx 反代到 `coze-server:8888`（read timeout 600s）；
2. hertz 中间件链取出会话与用户（`SessionAuthMW` → `I18nMW`），handler 调到 conversation 域；
3. conversation 通过 crossdomain 契约拿到 singleagent 域服务；
4. `BuildAgent` 编译图：人设渲染 + 变量装配 + 知识检索（chain 三路召回 + rerank）+ 工具预检索并行；
5. 有工具 → ReAct 子图循环；工具调用触发 `ExecuteTool`（HTTP + OAuth），需要确认则中断并等用户；
6. 每个节点/工具的事件经三个 callback handler 转成 `*Event` → `*entity.Message` → SSE 帧；
7. 结束时 token 用量与执行记录落库（`execute_history_store`），可通过 `GetExecution` 回放。

## Why This Matters

- **调试一条跑歪的工作流，先看 schema 而不是节点代码**：多数问题是 `CanvasToWorkflowSchema` 阶段字段映射算错（尤其是数组下钻），节点本身没问题。
- **`map[string]any` 意味着类型错误在运行期才暴露**，而且常常只是 warning。生产上应对关键输入做显式校验。
- **中断能力依赖 Redis checkpoint**：自部署如果 Redis 不可靠，Agent 的多轮工具调用会恢复失败。
- **流式管道的缓冲只有 10**：前端消费慢会反压到 LLM 节点，表现为"生成变慢"，不是模型问题。
- **知识库检索是同步的、索引是异步的**：文档刚上传完查不到是正常的，看 `document` 表状态与 NSQ 消费情况。

## Links

- [LLM](/docs/CS/AI/LLM/LLM.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [RAG](/docs/CS/AI/RAG.md)
- [Tool Use](/docs/CS/AI/LLM/Protocol/Tools.md)
- [Coze 架构设计](/docs/CS/AI/LLM/Platform/Coze/Architecture.md)
- [LLM 应用开发平台](/docs/CS/AI/LLM/Platform/Platform.md)

## References

1. [Coze Studio 开源仓库](https://github.com/coze-dev/coze-studio)
2. [CloudWeGo Eino：compose 编排文档](https://www.cloudwego.io/docs/eino/)
3. [Eino ReAct Agent](https://www.cloudwego.io/docs/eino/core_modules/flow_integration_components/react_agent/)
4. [Server-Sent Events 规范](https://html.spec.whatwg.org/multipage/server-sent-events.html)
5. [OpenAPI Specification 3.0](https://spec.openapis.org/oas/v3.0.3)
