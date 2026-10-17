## Introduction

这一篇是**代码地图**：仓库怎么分、每层放什么、关键类型与签名在哪、按什么顺序读最省力，以及想二次开发时该动哪些文件。静态结构见 [架构设计](/docs/CS/AI/LLM/Platform/Coze/Architecture.md)，运行时走向见 [链路设计](/docs/CS/AI/LLM/Platform/Coze/Pipeline.md)，产品视角回到 [Coze](/docs/CS/AI/LLM/Platform/Coze.md)。

路径与行号取自 git tag `v0.5.1`。

## Repository Map

```
coze-studio/
├── backend/        Go 服务端主体（笔记里绝大多数源码分析都在这）
├── frontend/       Rush.js monorepo：React 18 + TypeScript
├── docker/         compose 编排、nginx 配置、.env.example、atlas 迁移
├── idl/            Thrift IDL，hertz 代码生成的输入
├── common/         Rush 公共配置（config / autoinstallers / git-hooks / scripts）
├── helm/           Kubernetes Helm Chart
└── scripts/        构建与运维脚本
```

### backend/

```
backend/
├── main.go              进程入口：env → 日志 → application.Init → hertz
├── Dockerfile           alpine 3.22 + python3 + deno，产物 /app/opencoze
├── api/                 传输层（hertz 生成 + 手写）
│   ├── handler/coze/    按业务分组的 handler（agent_run / conversation / knowledge ...）
│   ├── router/          GeneratedRegister + 分组路由
│   ├── middleware/      ctx_cache / session / openapi_auth / request_inspector / i18n / host / log
│   └── model/           IDL 生成的请求响应结构（admin / app / conversation / passport ...）
├── application/         应用层：用例编排 + 依赖装配
│   ├── application.go   Init 三段式 + 17 个 crossdomain 契约注入
│   └── base/appinfra/   AppDependencies：全部基础设施实例
├── domain/              领域层（17 个域）
│   ├── workflow/        工作流（画布、schema、compose、节点、执行、持久化）
│   ├── agent/           singleagent（agentflow）
│   ├── knowledge/       RAG（processor / service / internal）
│   ├── plugin/          插件（entity / service / encrypt / conf）
│   ├── conversation/    会话与消息
│   ├── memory/          数据库与变量（Database / Variables 两个域服务）
│   └── ...              app / connector / prompt / search / user / upload / permission / openauth ...
├── infra/               基础设施：orm / cache / es / storage / eventbus / coderunner /
│                        embedding / document / checkpoint / sse / idgen / imagex / dynconf ...
├── crossdomain/         跨域契约：contract.go + impl/ + model/，17 个域各一份
├── bizpkg/              业务公共包：llm/modelbuilder（8 家厂商）、config、fileutil
├── pkg/                 通用库：logs / errorx / sonic / safego / ctxcache / i18n / kvstore ...
├── conf/                配置与模板（model / plugin / prompt / workflow / admin）
└── types/               常量与错误码（errno）
```

每个 domain 内部是同一套形状：`entity/`（实体与 VO）、`service/`（域服务实现）、`repository/` 或 `internal/repo/`（持久化接口与 DAL）、`internal/`（私有实现细节）。`internal/` 后面的东西外部不可见——这是 Go 包机制带来的天然边界，也是 Coze 敢把 workflow 拆这么细的原因。

### frontend/

Rush.js monorepo，135+ 包，四层依赖（`CLAUDE.md`）：

| 层 | 目录 | 内容 |
| :-- | :-- | :-- |
| level-1 | `packages/arch/` | 基础设施：i18n、logger、coze-design、web-context |
| level-2 | `packages/common/`、`components/`、`data/`、`foundation/` | 共享组件与能力 |
| level-3 | `packages/agent-ide/`、`workflow/`、`studio/`、`project-ide/`、`community/` | 功能域 |
| level-4 | `apps/coze-studio` | 主应用 |

技术栈：React 18 + TypeScript + Semi Design + Tailwind CSS + Zustand，构建用 Rsbuild（Rspack）。画布来自 FlowGram（`@flowgram-adapter/common`、`@coze-workflow/*`），即记忆里 [Coze.md](/docs/CS/AI/LLM/Platform/Coze.md) 提过的那个工作流画布引擎。

## Where to Start Reading

进程启动的顺序就是最好的阅读顺序：

```go
// backend/main.go:47-59
setCrashOutput()
loadEnv()               // .env 或 .env.${APP_ENV}
setLogLevel()
application.Init(ctx)   // ← 全部装配在这里
startHttpServer()
```

`application.Init` 的三段（`:123`）分别是 `appinfra.Init` → `initBasicServices` → `initPrimaryServices` → `initComplexServices` → 注入 crossdomain。`appinfra.Init`（`base/appinfra/app_infra.go:69`）逐个 new 出 `AppDependencies`（`:50-65`）里的 16 个成员，注释里明确写了 `config.Init` 依赖 MySQL + IDGen + OSS——**基础设施之间也有依赖顺序**，改这块要照注释来。

## Workflow Domain Anatomy

```
domain/workflow/
├── interface.go / component_interface.go   对外契约与组件接口
├── entity/            实体：workflow.go / node_meta.go / message.go / interrupt_event.go
│   └── vo/            canvas.go、node.go、workflow_info.go、meta.go ...（前端契约）
├── service/           域服务：service_impl.go(2187 行)、executable_impl.go(1111)、
│                      as_tool_impl.go、conversation_impl.go、global_handler.go
└── internal/
    ├── canvas/        adaptor/to_schema.go（画布 → schema）、convert/、validate/
    ├── schema/        workflow_schema.go、node_schema.go、branch_schema.go、node_builder.go
    ├── compose/       workflow.go(894)、node_runner.go(968)、state.go(729)、
    │                  workflow_run.go、field_fill.go、stream.go、workflow_tool.go
    ├── nodes/         21 个节点实现（见下表）
    ├── execute/       callback.go(1390)、event_handle.go、context.go、collect_token.go
    └── repo/          repository.go、cancel_signal_store.go、execute_history_store.go、
                       interrupt_event_store.go、dal/
```

### 节点清单（21 个）

`internal/nodes/` 下每个目录一个节点类型：

| 分类 | 节点 |
| :-- | :-- |
| 模型与生成 | `llm`、`intentdetector`、`qa` |
| 数据与逻辑 | `code`、`textprocessor`、`json`、`selector`、`variableassigner`、`variableaggregator` |
| 集成 | `plugin`、`httprequester`、`database`、`knowledge`、`subworkflow` |
| 控制流 | `entry`、`exit`、`batch`、`loop`、`receiver`、`emitter`、`conversation` |

### 节点是怎么被"注册"的

Coze 没有节点注册表，而是**接口判别**（`internal/compose/node_builder.go:66-99`）：

```go
nb, ok := s.Configs.(schema.NodeBuilder)
if ok {
    n, err := nb.Build(ctx, s, schema.WithWorkflowSchema(sc), schema.WithInnerWorkflow(inner))
    return toNode(s, n), nil
}

switch s.Type {
case entity.NodeTypeLambda:      return &Node{Lambda: s.Lambda}, nil
case entity.NodeTypeSubWorkflow: ...
default: panic("node schema's Configs does not implement NodeBuilder")
}
```

即：**新节点的 Config 只要实现 `schema.NodeBuilder` 就能被构建**，否则直接 panic——一个故意"响亮失败"的设计，避免静默走空实现。

节点能力本身按接口细分（`internal/nodes/node.go:35-130`），按需组合：

| 接口 | 行号 | 语义 |
| :-- | :-- | :-- |
| `InvokableNode` / `InvokableNodeWOpt` | `:35` / `:44` | 一次性调用 |
| `StreamableNode` / `StreamableNodeWOpt` | `:54` / `:63` | 流式输出 |
| `CollectableNode` / `WOpt` | `:74` / `:85` | 收集式输出（如批处理） |
| `TransformableNode` / `WOpt` | `:95` / `:108` | 纯转换 |
| `CallbackInputConverted` / `CallbackOutputConverted` | `:116` / `:123` | 回调数据改写 |
| `Initializer` | `:127` | 初始化钩子 |

另有 `RegisterNodeAdaptor` / `RegisterBranchAdaptor`（`:167` / `:179`）两处**真正的注册表**，用于画布 schema 的适配转换（不是执行）。

对比 [Dify](/docs/CS/AI/LLM/Platform/Dify/Source_Code.md)：Dify 是扫包 + import 副作用自注册 + 工厂注入；Coze 是接口判别 + panic。前者灵活但依赖隐式副作用，后者显式但新增节点必须实现 Build。

## Key Types and Signatures

| 类型 / 函数 | 位置 | 说明 |
| :-- | :-- | :-- |
| `type workflow = compose.Workflow[map[string]any, map[string]any]` | `compose/workflow.go:37` | Coze 工作流 = Eino Workflow，IO 都是宽松 map |
| `NewWorkflow(ctx, sc *schema.WorkflowSchema, opts ...WorkflowOption)` | `:83` | 建图 + 加节点 + Compile |
| `WithIDAsName` / `WithMaxNodeCount` / `WithParentRequireCheckpoint` | `:64` / `:77` / `:71` | 编译选项 |
| `(*Workflow).AsyncRun` / `SyncRun` | `:160` / `:173` | 执行入口 |
| `adaptor.CanvasToWorkflowSchema(ctx, *vo.Canvas)` | `canvas/adaptor/to_schema.go` | 画布 → schema |
| `SyncExecute` / `AsyncExecute` / `StreamExecute` | `service/executable_impl.go:52/208/451` | 三种执行模式 |
| `Event` / `EventType`（15 个） | `execute/event.go:46` / `:27` | 链路上的通用语言 |
| `WorkflowHandler` / `NodeHandler` / `ToolHandler` | `execute/callback.go:75/117/133` | Eino callbacks → Coze Event |
| `ExecuteTool` | `plugin/service/exec_tool.go:45` | 插件工具执行 |
| `Retrieve`（Eino Chain） | `knowledge/service/retrieve.go:54` | RAG 检索 |
| `HandleMessage`（事件消费） | `knowledge/service/event_handle.go:51` | RAG 索引 |
| `BuildAgent` / `AgentRunner.StreamExecute` | `agentflow/agent_flow_builder.go:60` / `agent_flow_runner.go:67` | Agent 图构建与运行 |
| `AppDependencies`（16 个成员） | `application/base/appinfra/app_infra.go:50` | 全部基础设施 |
| `Runner interface`（coderunner） | `infra/coderunner/` | 代码节点执行，`direct` / `sandbox` 两实现 |

## Extension Points

想改什么，动哪里：

| 目标 | 落点 |
| :-- | :-- |
| 加一个新节点类型 | `internal/nodes/<name>/` 实现 `schema.NodeBuilder` + 在 `entity/node_meta.go` 注册元信息 + 前端 `packages/workflow/` 加画布节点 |
| 加一家模型厂商 | `bizpkg/llm/modelbuilder/<vendor>.go` + `conf/model/template/` 加 YAML 模板 |
| 换向量库 | `infra/document/searchstore/impl/<name>/` + `VECTOR_STORE_TYPE` |
| 换消息队列 | `infra/eventbus/impl/<name>/` + `COZE_MQ_TYPE` |
| 加领域间调用 | `crossdomain/<domain>/contract.go` + `impl/`，并在 `application.Init` 里 `SetDefaultSVC` |
| 改执行语义（并发、重试） | 不在本仓库，在 Eino `compose` |
| 加 API | `idl/*.thrift` → hertz 生成 → `api/handler/coze/` |

## Recommended Reading Order

1. `backend/main.go` —— 进程怎么起、中间件顺序
2. `backend/application/base/appinfra/app_infra.go` —— 16 个基础设施怎么 new
3. `backend/application/application.go:123` —— 三段式装配与 crossdomain 注入
4. `backend/domain/workflow/service/executable_impl.go:52` —— `SyncExecute` 是理解全流程最短的一条路径
5. `backend/domain/workflow/internal/canvas/adaptor/to_schema.go` —— 画布怎么变成 schema
6. `backend/domain/workflow/internal/compose/workflow.go:83` —— schema 怎么变成 Eino 图（**核心**）
7. `backend/domain/workflow/internal/compose/node_builder.go` —— 节点怎么被构建
8. `backend/domain/workflow/internal/nodes/llm/llm.go:1145` —— 一个具体节点长什么样
9. `backend/domain/workflow/internal/execute/callback.go` —— 事件怎么回流
10. `backend/domain/agent/singleagent/internal/agentflow/agent_flow_builder.go:60` —— Agent 是另一条图

读完这十步之后，再去 `infra/` 下挑自己关心的存储/沙箱/消息实现看，会轻松很多——它们都只是接口实现，不带业务语义。

## Links

- [LLM](/docs/CS/AI/LLM/LLM.md)
- [RAG](/docs/CS/AI/RAG.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [Coze 架构设计](/docs/CS/AI/LLM/Platform/Coze/Architecture.md)
- [LLM 应用开发平台](/docs/CS/AI/LLM/Platform/Platform.md)
- [Golang](/docs/CS/Go/Go.md)

## References

1. [Coze Studio 开源仓库](https://github.com/coze-dev/coze-studio)
2. [Coze Studio backend README](https://github.com/coze-dev/coze-studio/blob/main/backend/README.md)
3. [CloudWeGo Eino](https://github.com/cloudwego/eino)
4. [CloudWeGo Hertz 代码生成工具 hz](https://www.cloudwego.io/docs/hertz/tutorials/toolkit/)
5. [Rush.js monorepo 文档](https://rushjs.io/)
6. [Rsbuild 文档](https://rsbuild.dev/)
7. [FlowGram 工作流画布引擎](https://github.com/bytedance/flowgram.ai)
