# Transport HTTP

本册讲 Kratos 的 HTTP 服务端实现（`transport/http`）。它**不是**自研网络层：结论很直接：Kratos 的 HTTP Server 直接站在 **[gorilla/mux](https://github.com/gorilla/mux) v1.8.1** 与标准库 `net/http` 之上，`Server.router` 的类型就是 `*mux.Router`，没有额外的路由算法。真正属于 Kratos 自己的是**路由之上的那一层**：统一的 `Transport` 上下文注入、请求绑定分发、中间件匹配、错误编码。

## Server Structure

```go
type Server struct {
	*http.Server
	lis         net.Listener
	tlsConf     *tls.Config
	endpoint    *url.URL
	err         error
	network     string
	address     string
	timeout     time.Duration
	filters     []FilterFunc
	middleware  matcher.Matcher
	decVars     DecodeRequestFunc
	decQuery    DecodeRequestFunc
	decBody     DecodeRequestFunc
	enc         EncodeResponseFunc
	ene         EncodeErrorFunc
	strictSlash bool
	router      *mux.Router
}
```

`NewServer` 的默认值（`transport/http/server.go`）：

```go
srv := &Server{
	network:     "tcp",
	address:     ":0",
	timeout:     1 * time.Second,
	middleware:  matcher.New(),
	decVars:     DefaultRequestVars,
	decQuery:    DefaultRequestQuery,
	decBody:     DefaultRequestDecoder,
	enc:         DefaultResponseEncoder,
	ene:         DefaultErrorEncoder,
	strictSlash: true,
	router:      mux.NewRouter(),
}
```

> [!WARNING]
>
> 两个默认值值得警惕：**address 默认是 `":0"`**（随机端口，生产环境必须显式 `Address`），**timeout 默认只有 1 秒**。这个 1s 会在 `filter()` 里变成 `context.WithTimeout`，所有 handler 默认只有 1 秒的 ctx 预算，超时的请求会被下层的 ctx 取消。慢接口务必显式调 `Timeout(...)`。

另外 `NotFoundHandler` 与 `MethodNotAllowedHandler` 的默认值都是 **`http.DefaultServeMux`**——不是 Kratos 自己的 handler，也不是 Go 标准库默认的 404 页。

嵌入的 `*http.Server` 只显式设置了 `Handler` 和 `TLSConfig` 两个字段，`ReadTimeout` / `WriteTimeout` / `IdleTimeout` / `MaxHeaderBytes` 全部保持零值。

## Routing

路由注册走的是「构建器」模式而不是直接在 Server 上堆方法：

| API | 位置 | 作用 |
| :-- | :-- | :-- |
| `srv.Route(prefix, filters...)` | `server.go` | 创建一个带路径前缀/过滤器的 `Router` 构建器 |
| `r.Group(prefix, filters...)` | `router.go` | 子分组，`path.Join` 拼接前缀，filters 从父继承 |
| `r.Handle(method, path, h, filters...)` | `router.go` | 核心注册；`method == "*"` 表示不限方法 |
| `r.GET` / `POST` / `PUT` / `PATCH` / `DELETE` / `HEAD` / `OPTIONS` / `CONNECT` / `TRACE` | `router.go` | `Handle` 的语法糖 |
| `srv.Handle` / `HandlePrefix` / `HandleFunc` / `HandleHeader` | `server.go` | 直接操作底层 mux，**绕开 Router 与 filters** |
| `srv.Use(selector, m...)` | `server.go` | 按 selector 注册业务中间件 |
| `srv.WalkRoute(fn)` | `server.go` | 遍历 mux 树产出 `RouteInfo{Method, Path}` |
| `srv.WalkHandle(fn)` | `server.go` | 遍历 mux 树产出 handler |

路由 handler 的签名是 Kratos 特有的 `func(ctx http.Context) error`——返回一个 error 就够了，编码和写状态码由外层处理：

```go
r.GET("/hello/:name", func(ctx http.Context) error {
	var in HelloRequest
	if err := ctx.BindQuery(&in); err != nil {
		return err
	}
	return ctx.Result(200, &HelloReply{Message: "hi " + in.Name})
})
```

`method == "*"` 的用法在代码生成里很常见：`protoc-gen-go-http` 生成的注册函数一律走 `r.Handle("GET", ...)` 之类确切方法，但如果 proto 里写了 `custom` 且 kind 为空，就会退化成任意方法。

> [!WARNING]
>
> `WalkHandle` 有个反直觉的行为：它传出的 handler 是 **`s.ServeHTTP`（整个 server），而不是该路由的真实 handler**（`server.go`）。如果想按路由做文档导出或鉴权扫描，得用 `WalkRoute` 拿 `Method`/`Path`，别用 `WalkHandle`。

## Two Middleware Chains

这是 Kratos HTTP 侧最容易搞混的地方：**它有两套完全不同的中间件**。

**(A) `FilterFunc` —— HTTP 原生中间件**

```go
type FilterFunc func(http.Handler) http.Handler

func FilterChain(filters ...FilterFunc) FilterFunc {
	return func(next http.Handler) http.Handler {
		for i := len(filters) - 1; i >= 0; i-- {
			next = filters[i](next)
		}
		return next
	}
}
```

倒序串联，`filters[0]` 在最外层。看到的就是标准的 `http.Handler`，可以用整个 net/http 生态。

**(B) `middleware.Middleware` —— 业务中间件**

```go
type Handler func(ctx context.Context, req any) (any, error)
type Middleware func(Handler) Handler
```

这套与协议无关，同一个中间件能同时给 HTTP 和 gRPC 用。它通过 `srv.Use(selector, m...)` 注册进一个 `matcher.Matcher`，按 operation 做匹配（默认链始终生效，再叠加精确匹配或最长前缀匹配，`*` 结尾按前缀算）。

### 执行顺序

一次请求的完整链路：

1. `http.Server.Handler` → 全局 `FilterChain(srv.filters...)`；
2. mux 路由匹配；
3. mux 中间件 `srv.filter()`：**按 timeout 建带超时的 ctx**，从 `mux.CurrentRoute` 取出路径模板（`/user/123` → `/user/{id}`），构造 `Transport` 并 `transport.NewServerContext`；
4. 路由级 `FilterChain(r.filters...)` → `FilterChain(filters...)`；
5. `wrapper` 调 `h(ctx)`，若返回 error 则交给 `srv.ene`。

> [!WARNING]
>
> **业务中间件不会自动生效。** `Router.Handle` 里不会去串联 `srv.middleware`；只有当 handler 内部显式调用 `ctx.Middleware(h)` 时，注册的业务中间件才被套上去。这正是 `protoc-gen-go-http` 生成的 wrapper 要做的事：
>
> ```go
> h := ctx.Middleware(func(ctx context.Context, req interface{}) (interface{}, error) {
> 	return srv.SayHello(ctx, req.(*HelloRequest))
> })
> out, err := h(ctx, &in)
> ```
>
> 后果很实际：**手工 `HandleFunc` 注册的原生 handler 完全没有中间件保护**（没有 recovery、没有 logging、没有 jwt）。手写 HTTP 路由时这是个隐形安全漏洞，务必要么走生成的 wrapper，要么自己在 Filter 层补齐。

## Binding and Rendering

三个可替换的函数钩子定义在 `codec.go`：

```go
type DecodeRequestFunc func(*http.Request, any) error
type EncodeResponseFunc func(http.ResponseWriter, *http.Request, any) error
type EncodeErrorFunc func(http.ResponseWriter, *http.Request, error)
```

Server 上其实是**四个绑定点**，三个来源各管一段：

| 来源 | Server 字段 | 默认实现 | 对应的 Context 方法 |
| :-- | :-- | :-- | :-- |
| path 变量 | `decVars` | `DefaultRequestVars` | `ctx.BindVars(v)` |
| query | `decQuery` | `DefaultRequestQuery` | `ctx.BindQuery(v)` |
| body | `decBody` | `DefaultRequestDecoder` | `ctx.Bind(v)` |
| form | —（`req.ParseForm()`） | — | `ctx.BindForm(v)` |

**没有 `BindHeader`。** `ctx.Header()` 只返回 `c.req.Header` 让你自己读，不提供结构体绑定。生成代码里 header 变量要靠 hand-written 提取。

path 变量与 form 走的是同一个 codec：`encoding.GetCodec("form")`，底层依赖 `github.com/go-playground/form/v4 v4.3.0`，字段标签默认取 `json`——也就是说 **Pb 生成的 struct 用它绑定时，认的是 `json` tag 而不是 `protobuf` tag**。

### Codec 选择

```go
func CodecForRequest(r *http.Request, name string) (encoding.Codec, bool) {
	for _, accept := range r.Header[name] {
		codec := encoding.GetCodec(httputil.ContentSubtype(accept))
		if codec != nil {
			return codec, true
		}
	}
	return encoding.GetCodec("json"), false
}
```

解码看 `Content-Type`，编码看 `Accept`。两侧行为不对称：解码时找不到对应 codec 会返回 **400**；编码时找不到就**静默回退 json**。

Content-Type 识别取的是 `/` 与 `;` 之间的子串（`internal/httputil/http.go`），写出时固定拼成 `application/<name>`。所以注册了 `json` / `proto` / `protojson` / `xml` / `yaml` / `form` 六个 codec 就对应六个 MIME，其中 `protojson` 区别于 `json` 的关键在于它要求 `proto.Message` 且默认 `EmitUnpopulated=true`、`DiscardUnknown=true`。

## Error Encoding

`DefaultErrorEncoder` 的行为极其简单——直接把 `errors.Error` 的 **`Code` 字段当成 HTTP 状态码写出去**：

```go
// transport/http/codec.go
w.WriteHeader(int(se.Code))
```

这点很重要：**Kratos 的 `errors.Error.Code` 存的是 HTTP 状态码，不是 gRPC code，也不是业务自定义码**。业务级错误语义靠 `Reason` 字段承载（一个字符串常量），gRPC code 只在跨协议转换时才由 `ToGRPCCode` 算出来。完整映射表与其中的不对称陷阱见 [Errors_and_Validation](/docs/CS/Go/Framework/Kratos/Errors_and_Validation.md)。

`DefaultErrorEncoder` 里还有两个分支：实现了 `Redirector` 接口的错误会被转成重定向（v3.0.0 新增 `feat(transport/http): support redirect errors in default error encoder`，即 #3783），`httpbody.HttpBody` 响应有专门的短路路径。

## ServerOption Reference

全部 17 个 ServerOption（`server.go`）：

| Option | 默认 | 说明 |
| :-- | :-- | :-- |
| `Network(string)` | `"tcp"` | |
| `Address(string)` | `":0"` | 生产必须显式指定 |
| `Endpoint(*url.URL)` | nil | 非空则不自动推导 |
| `Timeout(d)` | **1s** | 作用于每次请求的 ctx |
| `Middleware(m...)` | 空 | 注册进 matcher |
| `Filter(f...)` | nil | 原生 http 中间件 |
| `RequestVarsDecoder(f)` | `DefaultRequestVars` | path |
| `RequestQueryDecoder(f)` | `DefaultRequestQuery` | query |
| `RequestDecoder(f)` | `DefaultRequestDecoder` | **只覆盖 body** |
| `ResponseEncoder(f)` | `DefaultResponseEncoder` | |
| `ErrorEncoder(f)` | `DefaultErrorEncoder` | |
| `TLSConfig(*tls.Config)` | nil | 非 nil 时 `Endpoint()` scheme 变 `https://` |
| `StrictSlash(bool)` | **true** | 尾斜杠严格模式 |
| `Listener(net.Listener)` | nil | 非空则跳过 `net.Listen` |
| `PathPrefix(string)` | 无 | 会 **替换** `s.router` 为 subrouter |
| `NotFoundHandler(h)` | `http.DefaultServeMux` | |
| `MethodNotAllowedHandler(h)` | `http.DefaultServeMux` | |

> [!WARNING]
>
> `Middleware()` 和 `Filter()` 都是**覆盖而非追加**：前者最终落到 `m.defaults = ms` 赋值，后者是 `o.filters = filters` 赋值。连着写两次 `Middleware(a)`、`Middleware(b)`，只有 `b` 生效。要追加请改用实例方法 `srv.Use(selector, m...)`。
>
> 另有一个拼写陷阱：想换 body 之外的解码器，要用 `RequestVarsDecoder` / `RequestQueryDecoder`，`RequestDecoder` 只管 body。

## Lifecycle

```go
func (s *Server) Start(ctx context.Context) error {
	if err := s.listenAndEndpoint(); err != nil {
		return err
	}
	s.BaseContext = func(net.Listener) context.Context { return ctx }
	log.Info("[HTTP] server listening", "addr", s.lis.Addr().String())
	var err error
	if s.tlsConf != nil {
		err = s.ServeTLS(s.lis, "", "")
	} else {
		err = s.Serve(s.lis)
	}
	if !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
}
```

- `listenAndEndpoint()` 先用 `net.Listen` 拿端口，再用 `host.Extract` 把 `":0"` 这样的占位解析成**本机第一个私有 IP + 实际端口**写进 endpoint（会跳过 `0.0.0.0`、`[::]`、`::`）——这就是注册中心里那个可路由地址的来源。
- `Stop` 先 `Shutdown(ctx)`，只有传入的 ctx 已经到期/被取消时才降级为 `Close()` 强制关闭，属标准优雅关机。
- `Endpoint()` 的 scheme 由 `endpoint.Scheme("http", s.tlsConf != nil)` 决定：有 TLS 是 `https://`，否则 `http://`。

v3 新增的能力集中在流式：`transport/http/stream.go` 提供了 SSE（服务端流式）与 WebSocket（客户端流式）支持，并把流式 ctx 用 `context.WithoutCancel` **与请求超时解绑**——长连接流不该被 1s 的请求超时打断。同时 `ServerStream` 新增了 `SetReadDeadline` / `SetWriteDeadline`（release note #3843）。

## Links

- [Kratos](/docs/CS/Go/Framework/Kratos.md)
- [Architecture](/docs/CS/Go/Framework/Kratos/Architecture.md)
- [Transport_gRPC](/docs/CS/Go/Framework/Kratos/Transport_gRPC.md)
- [Errors_and_Validation](/docs/CS/Go/Framework/Kratos/Errors_and_Validation.md)
- [Protobuf_and_Codegen](/docs/CS/Go/Framework/Kratos/Protobuf_and_Codegen.md)

## References

- <https://github.com/gorilla/mux>
- <https://pkg.go.dev/github.com/go-kratos/kratos/v3/transport/http>
- <https://go-kratos.dev/docs/component/transport/http>
