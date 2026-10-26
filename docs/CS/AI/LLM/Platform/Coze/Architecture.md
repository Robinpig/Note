## Introduction

这一篇回答 Coze Studio「**进程怎么起、代码分几层、数据落在哪、边界画在哪**」。运行时走向（一次请求怎么流）在 [链路设计](/docs/CS/AI/LLM/Platform/Coze/Pipeline.md)，包与签名的代码地图在 [源码分析](/docs/CS/AI/LLM/Platform/Coze/Source_Code.md)，产品与选型判断回到 [Coze](/docs/CS/AI/LLM/Platform/Coze.md)。

两个先要纠正的常见误解：

- **Coze Studio 不是微服务部署形态**。官方 `CLAUDE.md` 写的是 "DDD with microservices"，但 `docker/docker-compose.yml` 里后端只有一个 `coze-server` 容器、跑一个 Go 二进制 `/app/opencoze`、监听 `:8888`。DDD 体现在**代码分层**，不是进程拆分。
- **工作流引擎不是 Coze 自己写的图执行器**，而是架在字节 CloudWeGo 的 Eino 框架 `compose` 包之上（与 [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) 那套"模型决策 → 框架执行"是同一层东西，只是 Coze 把它做成了可视化数据流）：`domain/workflow/internal/compose/workflow.go:37` 直接把工作流定义成 `compose.Workflow[map[string]any, map[string]any]`。这一点决定了后面几乎所有实现细节的形状。

## Version Baseline

路径与行号取自 git tag `v0.5.1`（2026-02-05，写作时最新 release；`main` 结构基本一致）。

| 组件 | 版本 / 镜像 | 出处 |
| :-- | :-- | :-- |
| coze-studio | `v0.5.1` | GitHub release |
| Go | `1.24.0` | `backend/go.mod` |
| Hertz（HTTP 框架） | `v0.10.2` | `backend/go.mod` |
| Eino（编排框架） | `v0.4.8` | `backend/go.mod` |
| MySQL | `mysql:8.4.5` | `docker/docker-compose.yml:7` |
| Redis | `bitnamilegacy/redis:8.0` | `:84` |
| Elasticsearch | `bitnamilegacy/elasticsearch:8.18.0` | `:117` |
| Milvus（默认向量库） | `milvusdb/milvus:v2.5.10` | `:294` |
| NSQ（默认消息队列） | `nsqio/nsq:v1.2.1` | `:336` |
| MinIO（默认对象存储） | `minio/minio:RELEASE.2025-06-13T11-33-47Z-cpuv1` | `:204` |
| etcd（Milvus 依赖） | `bitnamilegacy/etcd:3.5` | `:257` |
| 运行时基础镜像 | `alpine:3.22.0` + python3 + deno | `backend/Dockerfile` |

## Process Topology

```
  浏览器 ──http://localhost:8888──▶ ┌──────────────┐
                                   │   coze-web   │  nginx :80
                                   └──────┬───────┘
                      静态资源 /          │ /api /v1-3 /admin
                      index.html          ▼
                                   ┌──────────────┐
                                   │ coze-server  │  :8888  单二进制 opencoze
                                   └──┬───┬───┬───┬───┬──┘
                                      │   │   │   │   │
        ┌─────────────────┐           │   │   │   │   └──▶ NSQ（事件总线）
        │      MySQL      │◀──────────┘   │   │   │        nsqd + nsqlookupd
        └─────────────────┘               │   │   │
        ┌─────────────────┐               │   │   └──────▶ MinIO（对象存储）
        │      Redis      │◀──────────────┘   │            /local_storage 反代
        └─────────────────┘                   │
        ┌─────────────────┐                   └──────────▶ Milvus + Elasticsearch
        │ etcd (for Milvus)│                              向量库 + 全文检索
        └─────────────────┘
```

`coze-server` 在 compose 里**没有 `ports` 映射**（被注释掉了，`:385-415`），对外只有 `coze-web` 一个入口。`docker/nginx/conf.d/default.conf` 的三条规则值得记住：

- `location ~ ^/(api|v[1-3]|admin)(/|$)` → `proxy_pass http://coze-server:8888`，`proxy_read_timeout 600s`（这一条是给 SSE 流式响应留的）；
- `location /local_storage/` → 反代 `minio:9000`，把对象存储藏在同源路径下；
- `sub_filter` 把响应体里的 `:8889` 和 `minio:9000` 改写成 `$http_host/local_storage`——否则前端拿到的文件 URL 会指向浏览器访问不到的内网地址。

后端进程本身的启动顺序（`backend/main.go`）：

```go
// backend/main.go:47-59
setCrashOutput()          // debug.SetCrashOutput → crash.log
loadEnv()                 // godotenv: .env 或 .env.${APP_ENV}
setLogLevel()
application.Init(ctx)     // 装配全部基础设施与领域服务
startHttpServer()         // hertz，默认 :8888
```

`MAX_REQUEST_BODY_SIZE` 默认 `1024*1024*200`（200 MiB，`:65`），但 compose 的 `.env.example:4` 给的是 `1073741824`（1 GiB）——上传大文件/大知识库时实际生效的是后者。中间件顺序有硬约束（`:93-101`）：`ContextCacheMW` 必须第一、`RequestInspectorMW` 必须第二、`I18nMW` 必须在 `SessionAuthMW` 之后（否则拿不到用户语种）。

## Layering: api → application → domain → infra, with crossdomain

```
backend/
├── api/           传输层：hertz 生成的 handler / router / middleware / model（IDL: idl/*.thrift）
├── application/   应用层：用例编排与依赖装配（Init 三段式）
├── domain/        领域层：agent / workflow / knowledge / plugin / conversation / memory ...
├── infra/         基础设施：orm / cache / es / storage / eventbus / coderunner / embedding ...
├── crossdomain/   跨域契约：打破 domain 之间的循环依赖
├── bizpkg/        业务公共包：llm 模型构建、config、文件工具
└── pkg/           通用库：logs / errorx / sonic / safego / i18n ...
```

依赖方向单向向下，**唯一例外是 `crossdomain/`**。这是 Coze 这版代码里最有辨识度的一处设计：`domain/workflow` 要调 `domain/plugin`，`domain/plugin` 也可能要回调 workflow，Go 不允许循环 import，于是把「跨域调用」抽成契约包：

```go
// backend/crossdomain/workflow/impl/workflow.go:33-45
var defaultSVC crossworkflow.Workflow

type impl struct {
    DomainSVC workflow.Service
}

func InitDomainService(c workflow.Service) crossworkflow.Workflow {
    defaultSVC = &impl{DomainSVC: c}
    return defaultSVC
}
```

`application.Init`（`backend/application/application.go:123`）在最后统一把 17 个契约的实现灌进去：

```go
// backend/application/application.go:151-168（节选）
crosspermission.SetDefaultSVC(permissionImpl.InitDomainService(basicServices.permissionSVC.DomainSVC))
crossplugin.SetDefaultSVC(pluginImpl.InitDomainService(primaryServices.pluginSVC.DomainSVC, infra.OSS))
crossworkflow.SetDefaultSVC(workflowImpl.InitDomainService(primaryServices.workflowSVC.DomainSVC))
crossagent.SetDefaultSVC(singleagentImpl.InitDomainService(complexServices.singleAgentSVC.DomainSVC))
```

与 [Dify](/docs/CS/AI/LLM/Platform/Dify/Architecture.md) 用 import-linter 把分层钉成契约、并逐条登记 90 多条存量违规的做法相比，Coze 走的是另一条路：**用运行时单例 + 显式装配顺序规避编译期循环**。代价是契约包容易膨胀（每个域都要写一份 `contract.go` 和 `impl/`），收益是没有"初始化顺序不确定"这类隐藏 bug——因为顺序就写在一个函数里。

### 三段式装配

`Init` 把服务分成三批，批与批之间是严格依赖：

| 批次 | 内容 | 依赖 |
| :-- | :-- | :-- |
| `initBasicServices`（`:183`） | upload / openauth / prompt / modelmgr / connector / user / template / permission | 只依赖 infra |
| `initPrimaryServices`（`:214`） | plugin / memory / knowledge / workflow / shortcutcmd | 依赖 basic |
| `initComplexServices`（`:249`） | singleagent / app / search / conversation | 依赖 primary |

workflow 拿到的依赖写在 `toWorkflowServiceComponents()`（`:313-329`）：IDGen、DB、Cache、TOS、ImageX、Database 域、Variables 域、Plugin 域、Knowledge 域、事件通知、**`checkpoint.NewRedisStore`**、**`CodeRunner`**、内置 ChatModel。最后两个正是"工作流能中断恢复"和"代码节点能执行"的物质基础。

## Storage

### MySQL：主库，schema 用 Atlas 管理

`infra/orm/impl/mysql` 给一个 `*gorm.DB`，领域层各自的 `internal/dal` 用 gorm gen 的 query/model 访问。schema 迁移不放在 Go 里，而是 `docker/atlas/` 下的 Atlas 配置（`make sync_db` / `make dump_db`）。连接池三个参数从环境变量读：`MYSQL_MAX_IDLE_CONNS` / `MYSQL_MAX_OPEN_CONNS` / `MYSQL_CONN_MAX_LIFETIME`。

### Redis：四种用途

1. **缓存** —— `infra/cache`（`cache.Cmdable` 抽象，可用 miniredis 做测试）
2. **ID 生成** —— `idgen.New(deps.CacheCli)`，ID 生成器建立在 Redis 之上（`app_infra.go:80`）
3. **工作流 checkpoint** —— `checkpoint.NewRedisStore`，`infra/checkpoint/redis.go`（另有 `mem.go` 用于单机/测试）
4. **取消信号** —— `domain/workflow/internal/repo/cancel_signal_store.go`，另起 goroutine 每 `200ms` 轮询一次（`internal/execute/consts.go:29`）

### 向量与检索：ES 和向量库是两件事

`VECTOR_STORE_TYPE=milvus`（`.env.example:116`）决定向量落在哪，实现有四种：`elasticsearch` / `milvus` / `oceanbase` / `vikingdb`（`infra/document/searchstore/impl/`）。ES 同时承担两类角色：全文检索通道（`esRetrieveNode`）和 Milvus 之外的备选向量库。

Embedding 与 Rerank 是独立可替换的：

| 能力 | 默认 | 可选实现 |
| :-- | :-- | :-- |
| Embedding | `ark`（火山方舟，`EMBEDDING_TYPE`） | openai / ollama / gemini / http 自定义 |
| Rerank | 空 → 回退 `rrf` | `vikingdb` / `rrf` |
| 文档解析 | `builtin` | `paddleocr` 等 |
| OCR | `ve`（火山） | `paddleocr` |

### 对象存储：三种后端

`STORAGE_TYPE` 取 `minio`（默认）/ `tos`（火山）/ `s3`。上传组件本身还有一层开关 `FILE_UPLOAD_COMPONENT_TYPE=storage`。

> [!WARNING]
>
> 上表钉的 `minio/minio:RELEASE.2025-06-13T11-33-47Z-cpuv1` 属于已停更的 MinIO 社区版：官方镜像 `minio/minio` 与 `minio/mc` 已于 2026-09-11 从 Docker Hub 删除，该 tag 如今拉不到。沿用同一份 compose 时可换成社区维护 fork [Silo](/docs/CS/Distributed/Silo.md)（`pgsty/silo`，S3 协议与 `xl.meta` 磁盘格式兼容、drop-in 替换、继续收 CVE 修复）。

## Event Bus

`infra/eventbus` 定义 Producer / Consumer，实现按 `COZE_MQ_TYPE` 分派五种：`nsq`（默认）/ `kafka` / `rmq`（RocketMQ）/ `pulsar` / `nats`（`infra/eventbus/impl/eventbus.go:52-60`）。

后端持有三个逻辑 producer（`app_infra.go:100-116`）：`ResourceEventProducer`（资源变更，驱动索引与搜索同步）、`AppEventProducer`（应用/项目事件）、`KnowledgeEventProducer`（知识库异步处理）。消费侧统一 `RegisterConsumer(nameServer, topic, group, handler, opts...)`。

对于自部署，NSQ 的意义是**零依赖地把"知识库异步切片入索引"这类长任务从请求链路里摘出去**；换成 Kafka 只需要改环境变量，不改代码。

## Code Sandbox: The Default Is Not What You Think

代码节点有两条执行路径（`infra/coderunner/impl/impl.go:31-55`）：

| 模式 | 实现 | 隔离性 |
| :-- | :-- | :-- |
| `sandbox` | `deno run --allow-* jsr:@langchain/pyodide-sandbox@0.0.4`，Python 跑在 WASM 里 | 有：权限白名单 + 内存上限 + 超时 |
| 其它任何值（含空） | `direct.NewRunner()`：`os/exec` 直接起本机 `python3` | **无**：与 coze-server 同进程宿主权限 |

`.env.example:263` 给的是 `CODE_RUNNER_TYPE="sandbox"`，所以官方 compose 部署落到沙箱路径；但**代码里的 `default` 分支是无隔离的 direct**。任何自己拼环境变量、漏配或改错的部署，都会静默退化成"工作流里的 Python 直接跑在服务器上"——这正是记忆里那条「sysctl 存在 ≠ 它还生效」的同族坑，判断实际行为要看 `switch` 的 default 分支，而不是看示例配置写了什么。

沙箱侧的细节（`infra/coderunner/impl/script/sandbox.py`）：

- 命令形如 `deno run --allow-env=... --allow-net=... --v8-flags=--experimental-wasm-stack-switching,--max-old-space-size=<MB> jsr:@langchain/pyodide-sandbox@0.0.4 --code <用户代码>`
- 六种权限：`AllowEnv` / `AllowRead` / `AllowWrite` / `AllowNet` / `AllowRun` / `AllowFFI`，`AllowRead`/`AllowWrite` 未显式配置时默认放行 `node_modules`
- 与 Go 侧通过 fd 3 / fd 4 传 JSON（`os.fdopen(3,"wb")` / `os.fdopen(4,"rb")`），超时靠 `subprocess.run(timeout=...)`
- **不支持 JavaScript**（`sandbox/runner.go` 里 `if request.Language == coderunner.JavaScript { return nil, fmt.Errorf("js not supported yet") }`）

镜像里预装了 deno 并做了预热（`Dockerfile` 的 `RUN deno run -A jsr:@langchain/pyodide-sandbox -c "print('Hello, World')"`），否则首次执行要现拉 WASM 包。

## Model Access

模型接入集中在 `bizpkg/llm/modelbuilder`，按厂商一个文件：`ark.go`（火山方舟，默认）、`openai.go`、`claude.go`、`deepseek.go`、`qwen.go`、`gemini.go`、`ollama.go`、`builtin.go`。两个层次区分开：

- **业务模型** —— 用户在「模型管理」里配的，走 `modelmgr`，存 MySQL + 对象存储；
- **内置模型** —— `BUILTIN_CM_TYPE`，指工作流/Agent 内部要用的那一个（如意图判断、query rewrite），环境变量里单独配 `BUILTIN_CM_ARK_API_KEY` 之类。

Eino 的组件来自 `github.com/cloudwego/eino-ext/components/{model,embedding}/*`，所以新增一家厂商通常是"加一个 modelbuilder + 在 conf 里加一份 YAML 模板"，而不是改引擎。

## Why This Matters

- **想改工作流执行语义**（并行度、重试、字段映射）→ 不在 Coze 仓库，在 Eino 的 `compose` 包。先读 `internal/compose/workflow.go` 怎么把 schema 翻译成 `compose.Workflow`，再顺着 Eino 往下。
- **想接私有模型** → 走 `modelbuilder` + 模型 YAML 模板，或做成插件（OpenAPI schema），都不用 fork 引擎。
- **最大的攻击面是代码节点**。自部署第一件事是确认 `CODE_RUNNER_TYPE` 真的是 `sandbox`，并且收紧 `AllowNet` / `AllowRun`；退化到 direct 就等于把服务器的 python3 交给了画布。
- **想扩展异步能力** → 事件总线换 Kafka/RocketMQ/Pulsar 只改 `COZE_MQ_TYPE`，消费端代码不动。
- **向量库与 ES 是两条独立选型**：默认 Milvus 存向量、ES 做全文，二者都可换，别把"知识库检索"理解成单一存储。

## Links

- [LLM](/docs/CS/AI/LLM/LLM.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [RAG](/docs/CS/AI/RAG.md)
- [Milvus](/docs/CS/DB/vector.md)
- [Redis](/docs/CS/DB/Redis/Redis.md)
- [MinIO（默认对象存储）](/docs/CS/Distributed/MinIO.md)

## References

1. [Coze Studio 开源仓库](https://github.com/coze-dev/coze-studio)
2. [Coze Studio v0.5.1 Release](https://github.com/coze-dev/coze-studio/releases/tag/v0.5.1)
3. [CloudWeGo Eino：LLM 应用编排框架](https://github.com/cloudwego/eino)
4. [CloudWeGo Hertz：HTTP 框架](https://github.com/cloudwego/hertz)
5. [jsr:@langchain/pyodide-sandbox](https://jsr.io/@langchain/pyodide-sandbox)
6. [Milvus 官方文档](https://milvus.io/docs)
7. [NSQ 官方文档](https://nsq.io/)
8. [Atlas：数据库 schema 管理](https://atlasgo.io/)
