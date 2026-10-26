# Middleware and Observability

本册讲 Kratos 的中间件体系与可观测性接入。中间件的**类型**极简、且与协议无关；真正有意思的是内置的两个稳定性中间件——限流是自研的 BBR（CPU 自适应），熔断是自研的 SRE breaker，都不是常见的令牌桶和 gobreaker。

## Middleware Contract

整个体系只用了三个类型（`middleware/middleware.go`）：

```go
type Handler func(ctx context.Context, req any) (any, error)

type Middleware func(Handler) Handler

func Chain(m ...Middleware) Middleware {
	return func(next Handler) Handler {
		for i := len(m) - 1; i >= 0; i-- {
			next = m[i](next)
		}
		return next
	}
}
```

`Chain` 是**倒序遍历**：`m[0]` 在最外层，所以注册顺序就是从前到后的执行顺序，符合直觉。

`any` 类型的 req/reply 是刻意的选择——同一个中间件能同时给 HTTP 和 gRPC 用。代价是要读协议相关信息得自己从 ctx 里取：

```go
if tr, ok := transport.FromServerContext(ctx); ok {
	tr.Kind()       // KindHTTP / KindGRPC
	tr.Operation()  // 全链路唯一的判定依据
	tr.RequestHeader().Get("x-user-id")
}
```

**`Operation()` 是中间件生态里最关键的一个值**：中间件匹配、熔断分组、日志埋点、Metrics label 全用它。HTTP 侧它是路径模板（`/helloworld.v1.Greeter/SayHello`），gRPC 侧是 `info.FullMethod`。

> [!WARNING]
>
> 回顾 [Transport_HTTP](/docs/CS/Go/Framework/Kratos/Transport_HTTP.md) 的提醒：`Router.Handle` **不会自动串联业务中间件**，只有 handler 显式调用 `ctx.Middleware(...)` 时才生效。`protoc-gen-go-http` 生成的 wrapper 会自动调用，手写路由则不会——表现为「中间件注册了却完全没跑」。

## Built-in Middlewares

| 包 | 入口函数 | 依赖 / 算法 |
| :-- | :-- | :-- |
| `logging` | `Server(logger)`、`Client(logger)` | 标准库 `log/slog` |
| `recovery` | `Recovery(opts...)` | 仅标准库；stack buffer `64<<10` |
| `ratelimit` | **只有 `Server(opts...)`** | **自研 BBR（CPU 自适应）** |
| `circuitbreaker` | **只有 `Client(opts...)`** | **自研 SRE breaker** |
| `validate` | `Validator(funcs...)` | duck-typing `Validate() error` |
| `metadata` | `Server(opts)`、`Client(opts)` | 头前缀透传 |
| `selector` | `Server(ms...)`、`Client(ms...)` → `Build()` | 按 operation 条件挂载 |

> [!NOTE]
>
> **限流只有 Server 端、熔断只有 Client 端**——这个分工与很多人的直觉相反。原因其实很自然：限流保护的是「自己别被打垮」，装在被调方（Server）入口；熔断保护的是「别调用已挂的下游」，装在调用方（Client）。所以这两个包各自只有一半。

### logging

v3 已经全面切到标准库 `log/slog`（这也是为什么 go.mod 要求 Go 1.25）。logger 传 nil 时退化为 `slog.Default()`。

### recovery

捕获 panic 并转成 `ErrUnknownRequest`。默认 stack buffer 是 `64<<10`（64 KiB）。可用 `WithHandler` 自定义处理逻辑、`WithLogger` 指定 logger。

### ratelimit：BBR

不是令牌桶，不是漏桶，是**参考 TCP BBR 的 CPU 自适应限流**。默认参数（`internal/ratelimit/bbr.go`）：

```go
opt := options{
	Window:       10 * time.Second,
	Bucket:       100,
	CPUThreshold: 800,   // 0~1000 标度，即 CPU 80%
}
```

机制：后台 goroutine 每 **500ms** 采样一次 CPU，衰减系数 `decay = 0.95`；数据源是 `runtime/metrics` 的 `/cpu/classes/total:cpu-seconds` 与 `/cpu/classes/idle:cpu-seconds`。CPU 超过阈值时按窗口内的 RT 与 QPS 反算最大允许的并发，**超过则直接拒绝**。

这个设计的价值在于：**保护的是整个进程的 CPU，而不是某个接口的 QPS**。比固定 QPS 限流更能应对「某个慢查询把 CPU 打满拖垮全站」这类故障。

### circuitbreaker：SRE

实现在 `internal/circuitbreaker/sre.go`，用 Google SRE 手册的公式——按 request 数与 failureRatio 计算丢弃概率，`k` 系数决定曲线的陡峭程度。默认：

```go
opt := options{
	failureRatio: 0.5,
	request:      20,
	bucket:       10,
	window:       3 * time.Second,
}
```

按 operation 分组（用 `internal/group.NewGroup`），互不影响。可用 `WithBreakerFactory` 整体替换。

两个细节：

- **本地拒绝时也会 `breaker.MarkFailed()`**。初看反直觉，但注释说明了意图：让丢弃比例继续升高，避免频繁抖动。
- **只有 `IsInternalServer` / `IsServiceUnavailable` / `IsGatewayTimeout` 判为失败**。业务层 4xx 不算失败，与上面 eWMA 的错误判定口径一致。

### metadata

做跨服务的 metadata 透传。Server 端默认前缀 `["x-md-"]`，Client 端默认前缀 `["x-md-global-"]`——即 Server 会把入站请求里 `x-md-` 开头的头存入 ctx，Client 再把 `x-md-global-` 开头的透传给下游。这是实现分布式链路里「用户身份一路透传」的标准手法。

### selector

**注意这个包和 `selector/` 负载均衡包完全无关**（名字撞车）。它的作用是「**按条件挂载中间件**」：

```go
srv.Use(selector.Server(
	selector.Regex(`/helloworld\.v1\..*/Public.*`), jwt.Server(...),
	selector.Prefix("/admin"), auth.Server(...),
).Build())
```

匹配依据同样是 `info.Operation()`。

> [!WARNING]
>
> `Regex` 的实现是 `r.FindString(operation) == operation`——要求**整串匹配**，而不是「包含即可」。写 `/admin` 想匹配 `/admin/list` 会失败（得用 `Prefix` 或完整 pattern）。另外编译失败的正则会被**静默丢弃**，不报错也不生效。

## Custom Middleware

写一个中间件的模板：

```go
func Metrics() middleware.Middleware {
	return func(handler middleware.Handler) middleware.Handler {
		return func(ctx context.Context, req any) (reply any, err error) {
			start := time.Now()
			reply, err = handler(ctx, req)   // 必须在中间调用 next
			duration := time.Since(start)

			var code int
			if err != nil {
				code = errors.Code(err)
			}
			metrics.Record(transport.FromServerContext(ctx), duration, code)
			return
		}
	}
}
```

注册位置：`http.NewServer(http.Middleware(m...))` 或 `srv.Use("/", m...)`。前者是默认链（对所有 operation 生效）。

> [!WARNING]
>
> HTTP 与 gRPC 的 ServerOption 里 **`Middleware()` 是覆盖而非追加**（内部是 `m.defaults = ms` 赋值）。连续调用两次只有最后一次生效。要追加请用实例方法 `srv.Use(selector, m...)`。

## Contrib Middlewares

`contrib/middleware/` 下只有两个，但都是高频刚需：

| 模块 | 依赖 | 入口 |
| :-- | :-- | :-- |
| `jwt` | **`github.com/golang-jwt/jwt/v5 v5.3.1`** | `Server(keyFunc, opts...)`、`Client(keyProvider, opts...)` |
| `validate` | **`buf.build/go/protovalidate v1.2.0`** | `ProtoValidate()` |

JWT 的实现用的是 **golang-jwt/jwt v5**，不是 square/go-jose 也不是 lestrrat。选项有 `WithSigningMethod`、`WithClaims`、`WithTokenHeader`、`WithParserOptions`（v3.0.0 新增，#3803）。Authorization 头以 `Bearer` 前缀解析，配 `NewContext` / `FromContext` 取用。

校验层的分工详见 [Errors_and_Validation](/docs/CS/Go/Framework/Kratos/Errors_and_Validation.md)。

## Observability

### contrib/otel

三个子包：`log/`、`metrics/`、`tracing/`。版本是 OTel **v1.43.0** 系列。

| 子包 | 内容 |
| :-- | :-- |
| `log/log.go` | `otel.NewHandler(name)` —— slog handler bridge（`contrib/bridges/otelslog v0.18.0`） |
| `tracing/` | `tracer.go`、`span.go`、`metadata.go`、`statshandler.go`（gRPC stats handler 形态的 tracing） |
| `metrics/` | `metrics.go`、`otel.go` |

> [!WARNING]
>
> **`contrib/otel` 的 go.mod 里不含任何 exporter**——没有 otlptrace/otlpmetric，也没有 stdout/prometheus。它只有 sdk / trace / metric / log 与 otelslog。**exporter 必须由你自己装配**，以为 import 了它就能出数据是常见的误判。

### Tracing How It Works

链路追踪靠 metadata 透传，与 Zipkin 这类系统对接时的关键字段可以看 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md)：Kratos 的 tracing 走的是标准 W3C traceparent 语义，通过 `metadata` 中间件的前缀机制跨服务传递，`x-md-global-` 前缀的自定义 baggage 会一路透传。

`tracing/statshandler.go` 提供的是 gRPC stats handler 形态的接入点与上面的中间件链路不同，它挂在 grpc 层的 stats 采集上，能拿到比中间件更底层的连接与消息事件。

## Errortracker

`contrib/errortracker/` 下一个：`sentry`（`github.com/getsentry/sentry-go v0.46.2`）。用于把 panic 与错误自动上报 Sentry。

## Full Contrib Map

`contrib/` 根共 9 个子目录，完整清单：

| 目录 | 内容 |
| :-- | :-- |
| `registry` | consul / discovery / etcd / eureka / kubernetes / nacos / polaris / servicecomb / zookeeper（9 个） |
| `config` | apollo / consul / etcd / kubernetes / nacos / polaris（6 个） |
| `middleware` | jwt / validate（2 个） |
| `transport` | mcp（1 个） |
| `encoding` | json / msgpack（2 个） |
| `otel` | log / metrics / tracing（3 个） |
| `polaris` | 单模块：`registry.go`、`config.go`、`router.go`、`ratelimit.go`、`limiter.go` |
| `opensergo` | 单模块，依赖 `opensergo/opensergo-go` |
| `errortracker` | sentry（1 个） |

其中 `contrib/transport/mcp` 值得单独一提：它是 **Model Context Protocol**（AI Agent 工具协议）的服务端适配，实现基于 `github.com/mark3labs/mcp-go v0.54.0`。做法是把 MCP server 包装成一个 Kratos `transport.Server`：

```go
srv := tm.NewServer("mcp-server", "v1.0.0", tm.Address(":8000"), tm.Middleware(...))
srv.AddTool(tool, helloHandler)
app := kratos.New(kratos.Name("mcp"), kratos.Server(srv))
```

也就是说 MCP 服务可以复用 Kratos 的生命周期管理与中间件体系。这是 Kratos 往 AI 场景延伸的一步。

## Links

- [Kratos](/docs/CS/Go/Framework/Kratos.md)
- [Architecture](/docs/CS/Go/Framework/Kratos/Architecture.md)
- [Transport_HTTP](/docs/CS/Go/Framework/Kratos/Transport_HTTP.md)
- [Errors_and_Validation](/docs/CS/Go/Framework/Kratos/Errors_and_Validation.md)
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md)

## References

- <https://go-kratos.dev/docs/component/middleware/overview>
- <https://github.com/golang-jwt/jwt>
- <https://opentelemetry.io/docs/languages/go/>
