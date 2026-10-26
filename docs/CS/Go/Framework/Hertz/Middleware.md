# Hertz Middleware

## Introduction

Hertz 的中间件与 handler **共用同一签名** `func(c context.Context, ctx *app.RequestContext)`，因此中间件本质上就是一个「包了 `ctx.Next(c)` 的 handler」。它通过 `ctx.Next(c)` 把控制权交回链中的下一个节点；**不调用 `Next` 即短路**（如鉴权失败直接返回，后续 handler 不再执行）。这是典型的洋葱模型（前置逻辑 → next → 后置逻辑），与 gin/echo 的中间件组织方式同源，Java 侧对应 Servlet Filter 与 Netty `ChannelPipeline` 的横切逻辑组织。

## Registration and Execution Order

中间件有两级注册点，执行顺序为 **全局 → 分组 → handler**：

```go
h := server.Default()
h.Use(recovery, accessLog, requestID)     // 全局中间件：所有路由生效

api := h.Group("/api")
api.Use(authMiddleware)                   // 分组中间件：仅 /api 及其子路由生效

api.GET("/me", meHandler)
```

- 全局 `h.Use(mws...)`：对整个引擎生效。
- 分组 `g.Use(mws...)`：只对挂载在该组下的路由生效，且叠加在全局之后。
- 短路：在中间件里直接 `ctx.Abort()` 或 `return` 而不调用 `ctx.Next(c)`，可阻止链继续向下；`ctx.Abort()` 显式标记「链已终止」。

> [!NOTE]
>
> 中间件**前置代码在 `ctx.Next(c)` 之前执行，后置代码在其之后执行**——这正是洋葱模型的「进」与「出」。想要在响应写回后做统计 / 日志，把逻辑放在 `Next` 之后。

## Built-in Middleware

`server.Default()` 已默认内置两个最常用的中间件：

- **Recovery**：把 handler 内的 panic 兜底成 500 响应，避免单请求 panic 拖垮整个服务（fasthttp 血统下这点尤其重要，否则可能击穿连接）。
- **AccessLog**：请求访问日志。

其它常用内置/官方中间件由 `hertz-contrib` 提供（见 [Extensions](/docs/CS/Go/Framework/Hertz/Extensions.md)）：JWT、KeyAuth、BasicAuth、CORS、CSRF、Secure、Gzip、RequestID、Sessions、Casbin、限流等。

## Custom Middleware

一个记录耗时的自定义中间件示例（展示前置 / 后置的洋葱结构）：

```go
func timingMiddleware() app.HandlerFunc {
    return func(c context.Context, ctx *app.RequestContext) {
        start := time.Now()              // 前置：进入链
        ctx.Next(c)                      // 交还控制权给下一个节点
        cost := time.Since(start)         // 后置：响应已生成
        hlog.Infof("path=%s cost=%s", ctx.Request.URI().Path(), cost)
    }
}

func authMiddleware() app.HandlerFunc {
    return func(c context.Context, ctx *app.RequestContext) {
        if !valid(ctx.GetHeader("Authorization")) {
            ctx.AbortWithStatusJSON(401, utils.H{"error": "unauthorized"})
            return                       // 不调用 Next → 短路
        }
        ctx.Next(c)
    }
}
```

要点：

- 中间件返回 `app.HandlerFunc`，内部闭包写前置/后置与 `ctx.Next(c)`。
- 需要短路时调用 `ctx.AbortWithStatusJSON` / `ctx.Abort()` 并 `return`。
- 想在上下文中跨中间件传递数据，用 `ctx.Set(key, val)` / `ctx.Get(key)`（存在 `*RequestContext` 上，受对象池复用纪律约束——异步场景记得拷贝）。

## Client Middleware

Hertz 的 HTTP 客户端同样支持中间件（见 [Client](/docs/CS/Go/Framework/Hertz/Client.md)），通过 `client.WithMiddleware` 注册，签名与服务端一致，可用于统一注入鉴权头、重试、链路追踪等横切逻辑。

## Links

- [Hertz](/docs/CS/Go/Framework/Hertz.md)
- [Routing](/docs/CS/Go/Framework/Hertz/Routing.md)
- [Extensions](/docs/CS/Go/Framework/Hertz/Extensions.md)
- [Gin](/docs/CS/Go/Framework/Gin.md)

## References

- <https://github.com/cloudwego/hertz>
- <https://www.cloudwego.io/docs/hertz/tutorials/basic-feature/middleware/>
- <https://github.com/hertz-contrib>
