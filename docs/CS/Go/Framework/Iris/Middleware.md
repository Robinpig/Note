# Iris Middleware

## Introduction

Iris 的中间件类型与其它框架一致（`func(ctx iris.Context)`），但它把"挂在哪一层"拆得远比 Gin 细：除了常规的 `Use`，还有 `UseRouter`（连 404 都跑）、`UseGlobal`（无视注册顺序）、`Done`（响应写出后的收尾）。多出来的这几层不是装饰——CORS 挂错层就会在 404 上失效，压缩挂错层就会漏掉错误响应。

本文基于 tag **v12.2.11**。

## Handler Chain Mechanics

```go
type Handler  func(*Context)   // context/handler.go:127
type Handlers []Handler        // context/handler.go:132
```

控制流原语（均在 `context/context.go`）：

| 方法 | 位置 | 行为 |
| :-- | :-- | :-- |
| `ctx.Next()` | :670-685 | 若已停止则直接返回；否则 `currentHandlerIndex+1` 执行下一个 |
| `ctx.StopExecution()` | :751-760 | 置 `proceeded`，index 设为 `-1`（可重复调用，有保护） |
| `ctx.IsStopped()` | :764 | 即 `index == -1` |
| `ctx.EndRequest()` | :239-247 | 响应写出后由框架自动调用：按状态码触发错误码 handler 再 flush |
| `ctx.Do(handlers)` | :525-531 | **替换**整条链并从 0 执行（不是追加） |

链构造工具：`JoinHandlers`（`handler.go:351`）、`UpsertHandlers`（`:373`，按 handler 名去重替换）、`CopyHandlers`（`:392`）、`NewConditionalHandler`（`:319`）。

## Mount Points and Execution Order

`core/router/api_builder.go` 里的注册方法：

| 方法 | 位置 | 作用域 | 顺序敏感性 |
| :-- | :-- | :-- | :-- |
| `UseRouter` | :1255 | 主路由**之前**，404/405 也执行 | 顺序敏感 |
| `UseGlobal` | :1332 | 全部路由（含 party、subdomain、error handler） | **顺序无关**，永远前置 |
| `Use` | :1308 | 当前 Party 及其子路由 | 顺序敏感，必须写在路由注册之前 |
| `UseOnce` | :1316 | 同 `Use` 但去重 | — |
| `Done` | :1350 | 响应写出后的收尾 | 逆序 |
| `DoneGlobal` | :1365 | 全局收尾 | — |
| `UseError` | :1294 | 错误处理链 | — |

权威顺序来自源码里那份专门的顺序测试（`core/router/router_handlers_order_test.go:292`）：

```
#1 .WrapRouter
#2 .UseRouter
#3 .UseGlobal
#4 .Use
#5 Main Handler
```

`WrapRouter`（`core/router/router.go:305`）在最外层，能在 trie 匹配前改写 `http.ResponseWriter` / `*http.Request`。

```go
app := iris.New()
app.UseRouter(routerWrapperLogger)   // 所有请求，含 404
app.UseGlobal(iris.Compression)      // 无论写在哪都最先
api := app.Party("/api", auth)       // 分组中间件
api.Get("/x", h)
app.Done(cleanup)                    // 响应后收尾
```

> [!TIP]
>
> 判断该用哪一层的经验规则：**必须在 404 上生效**（CORS、访问日志、recover）→ `UseRouter`；**必须盖住所有路由且不关心注册先后**（压缩）→ `UseGlobal`；**只服务已注册的业务路由**（鉴权、限流）→ `Use`。

## Built-in Middleware Packages

`middleware/` 下 17 个子包（`accesslog` 等），入口构造如下：

| 子包 | 入口 | 用途 |
| :-- | :-- | :-- |
| `accesslog` | `New(io.Writer) *AccessLog`（accesslog.go:266），另有 `File:325`/`FileUnbuffered:332` | 结构化访问日志，支持 broker 订阅 |
| `basicauth` | `New(opts Options) context.Handler`（basicauth.go:191） | HTTP Basic 认证（**是 `Options` 不是 `Config`**） |
| `cors` | `New() *CORS`（cors.go:100），链式后 `.Handler()` | 跨域 |
| `grpc` | `New(grpcServer http.Handler) router.WrapperFunc`（grpc.go:22） | gRPC-over-HTTP 分流包装器 |
| `hcaptcha` | `New(secret string, options ...Option)`（hcaptcha.go:82） | hCaptcha 校验 |
| `jwt` | `NewSigner(alg, key, maxAge)`（signer.go:36）/ `NewVerifier(alg, key, validators...)`（verifier.go:89） | JWT 签发与校验 |
| `logger` | `New(cfg ...Config) context.Handler`（logger.go:26） | 轻量请求日志 |
| `methodoverride` | `New(opt ...Option) router.WrapperFunc`（methodoverride.go:191） | 用 `_method` 参数/头覆写 HTTP 方法 |
| `modrevision` | `New(opts Options)`（modrevision.go:44） | 静态资源 revision 去缓存 |
| `monitor` | `New(opts Options) *Monitor`（monitor.go:55） | 指标看板 / dataframe 输出 |
| `pprof` | `New() context.Handler`（pprof.go:46） | 原生 pprof 端点 |
| `rate` | `Limit(limit float64, burst int, options ...Option)`（rate.go:114） | 令牌桶限流 |
| `recaptcha` | `New(secret string)`（recaptcha.go:44） | reCAPTCHA 校验 |
| `recover` | `New() context.Handler`（recover.go:20） | panic 恢复 |
| `requestid` | `New(generator ...Generator)`（requestid.go:64） | 请求 ID（默认 UUID4） |
| `rewrite` | `New(opts Options) (*Engine, error)`（rewrite.go:99） | 重定向 / 主子域名改写 |

根包 `aliases.go` 另暴露四个缓存与压缩相关的别名：

```go
iris.Compression            // aliases.go:359，普通 Handler，需 app.Use / UseRouter
iris.Cache     = cache.Handler       // aliases.go:480
iris.NoCache   = cache.NoCache       // aliases.go:489
iris.StaticCache = cache.StaticCache // aliases.go:504
```

> [!WARNING]
>
> 根包**没有** `iris.Recovery` 这个别名——recover 中间件在 `middleware/recover` 子包（`recover.New()`），另有 `x/errors.RecoveryHandler`（handler 名 `iris.errors.recover`）。写 `iris.Recovery` 会编译失败。

## Recovery Behavior

`iris.New()` **不自动启用 recover**；只有 `iris.Default()` 会注册 `app.UseRouter(recover.New())`（`iris.go:176`）。

panic 后的处理（`middleware/recover/recover.go`）：

1. 收集调用栈与整条 handler 链的 `file:line`，包装成 `PanicRecoveryError`（`:34-84`）。
2. 主流程 `ctx.StopWithPlainError(500, err)`，并以 `Logger().Warn` 输出（`:22-27`）。
3. 若 ctx 已 `StopExecution`、或已被其它 recover 恢复，则直接返回 nil（`:35-45`）。
4. 业务侧用 `ctx.IsRecovered()`（`context/context.go:6397`）判断是否发生过恢复。

## Access Log

```go
ac := accesslog.New(os.Stdout)   // accesslog.go:266
ac.SetFormatter(&accesslog.JSON{Indent: "  "})   // 也支持 CSV / Template  (:670)
ac.SetRequestHeaders("User-Agent", "X-Request-Id")
ac.AddFields(func(ctx *context.Context) []accesslog.Field { ... })  // :695
defer ac.Close()                  // :518

app.UseRouter(ac.Handler)         // Handler:716，官方推荐挂点
```

也可以订阅实时日志流：`ac.Broker().NewListener()` 拿到 `LogChan`（`broker.go:82`），用于把访问日志接到自己的管道里。

## Writing Custom Middleware

```go
func timing(ctx iris.Context) {
    start := time.Now()
    ctx.Next()                                  // 执行后续 handler
    ctx.Header("X-Elapsed", time.Since(start).String())
}

func mustAuth(ctx iris.Context) {
    if ctx.GetHeader("Authorization") == "" {
        ctx.StopWithStatus(iris.StatusUnauthorized)  // 停止执行，不写 body
        return
    }
    ctx.Next()
}
```

`StopWithStatus` / `StopWithText` / `StopWithJSON` / `StopWithError` 是 Iris 提供的"停止 + 写响应"组合方法，比 `StopExecution()` 后再手写响应更常用。

## Links

- [Iris](/docs/CS/Go/Framework/Iris.md)
- [Iris Architecture](/docs/CS/Go/Framework/Iris/Architecture.md)
- [Iris Routing](/docs/CS/Go/Framework/Iris/Routing.md)
- [Iris Sessions and Authentication](/docs/CS/Go/Framework/Iris/Sessions_and_Auth.md)
- [Gin Middleware](/docs/CS/Go/Framework/Gin/Middleware.md)

## References

- <https://github.com/kataras/iris/blob/main/middleware/README.md>
- <https://github.com/kataras/iris/blob/main/core/router/router_handlers_order_test.go>
- <https://github.com/kataras/iris/blob/main/context/handler.go>
- <https://github.com/kataras/iris/blob/main/middleware/recover/recover.go>
- <https://github.com/kataras/iris/blob/main/middleware/accesslog/accesslog.go>
