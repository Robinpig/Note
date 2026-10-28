# Gin Routing

## Introduction

Gin 的路由建立在一组 **radix tree（前缀压缩 trie）** 上，思路源自 [httprouter](https://github.com/julienschmidt/httprouter)（gin 早期直接搬运 httprouter 的 tree 实现，后独立维护于 `tree.go`）。每个 HTTP method 一棵独立的树，树里同时容纳静态段、参数段 `:name` 与通配段 `*path`，注册时计算优先级，使请求以最少比较命中正确 handler。

路由层位于 Engine 之内：协议层（标准库 `net/http`）解析出 method 与 path 后，交给对应 method 的 radix tree 匹配，命中后把 handler 链交给 `gin.Context` 执行（见 [Architecture](/docs/CS/Go/Framework/Gin/Architecture.md)）。

## Route Types and Priority

| 类型 | 写法 | 示例 | 说明 |
| :-- | :-- | :-- | :-- |
| 静态段 | 普通路径 | `/users/new` | 优先级最高，精确匹配 |
| 参数段 | `:name` | `/users/:id` | 单段通配，匹配一个路径片段 |
| 通配段 | `*path` | `/files/*path` | 贪婪匹配剩余全部路径，常用于静态资源 |

**优先级规则**：同一位置能匹配多条规则时，静态段 > 参数段 > 通配段。例如同时注册 `/users/new` 与 `/users/:id`，请求 `GET /users/new` 命中静态规则。

**冲突即 panic**：参数段与通配段在同一父节点下互斥（如 `/users/:id` 与 `/users/*path`），或重复注册完全相同的静态路由，都会在**注册期 panic**——这是 Gin 的有意设计，宁可启动失败也不让歧义路由悄悄生效。注册顺序不影响最终优先级，优先级由段类型决定。

## Method Registration

全套 REST 动词，handler 签名统一为 `func(c *gin.Context)`：

```go
r.GET("/users/:id", func(c *gin.Context) {
    id := c.Param("id")          // 路径参数段
    c.String(200, "user %s", id)
})
r.POST("/users", createUser)
r.PUT("/users/:id", updateUser)
r.DELETE("/users/:id", deleteUser)
r.PATCH("/users/:id", patchUser)
r.HEAD("/health", health)
r.OPTIONS("/users", options)
r.Any("/echo", echoHandler)          // 匹配任意 method
r.Handle("MKCOL", "/dav", mkcol)     // 自定义 method
```

参数取用 API（均在 `*gin.Context` 上）：

- `c.Param("id")`：路径参数段。
- `c.Query("q")` / `c.DefaultQuery("q", "d")`：URL query。
- `c.PostForm("f")` / `c.FormValue("f")`：表单字段。
- `c.GetHeader("X-Token")` / `c.Request.Header.Get(...)`：请求头。
- `c.Cookie("sid")`：Cookie。
- `c.GetRawData()`：原始 body 字节。

## Route Groups

分组给"同一前缀 + 同一批中间件"的路由批量收口，避免每条路由重复挂中间件，且**可无限嵌套而不损失性能**：

```go
v1 := r.Group("/api/v1")
v1.Use(authMiddleware)                 // 仅对该组生效
v1.GET("/orders", listOrders)
v1.GET("/orders/:id", getOrder)

admin := r.Group("/admin")
admin.Use(adminAuth, auditLog)         // 分组级中间件链
admin.POST("/users", createAdminUser)
```

中间件执行顺序为：全局 `engine.Use` → 各层分组 `g.Use`（由外到内）→ 末端 handler。嵌套分组会逐层叠加中间件（详见 [Middleware](/docs/CS/Go/Framework/Gin/Middleware.md)）。

## Redirect and Trailing Slash

Engine 有几个影响路由匹配的可选开关（构造 Engine 后改字段，或 `gin.New()` 后用选项函数）：

- `RedirectTrailingSlash`（默认 `true`）：`/users/` 自动重定向到 `/users`（反之亦然，视注册情况）。
- `RedirectFixedPath`（默认 `true`）：对 `/USER/FOO` 做大小写不敏感、去多余斜杠的修正后重定向。
- `HandleMethodNotAllowed`（默认 `false`）：开启后，路径存在但 method 不匹配时返回 405 而非 404。
- `ForwardedByClientIP`、`RemoteIPHeaders`、`TrustedProxies`：影响 `c.ClientIP()` 的取值（v1.12.0 修正了多 `X-Forwarded-For` 值的处理）。

> [!WARNING]
>
> `RedirectTrailingSlash` / `RedirectFixedPath` 通过 301/308 重定向实现。如果前端/网关对重定向敏感（如某些 SPA 路由或严格 CSP），建议显式注册带/不带斜杠的两条路由，而非依赖自动重定向。

## Fallback Handlers

- `r.NoRoute(handler)`：没有匹配路由时的兜底（常用于返回自定义 404 或 SPA 回退页）。
- `r.NoMethod(handler)`：路径匹配但 method 不支持时的兜底（配合 `HandleMethodNotAllowed` 使用）。
- `r.NoRoute` 也可承载静态文件兜底：`r.NoRoute(gin.WrapH(http.FileServer(http.Dir("static"))))`。

## Embedding

`r.Handler()` 返回 Engine 自身（`http.Handler`），因此 Gin 可以嵌入任意 `net/http` 体系：挂在 `http.ServeMux` 子树、作为 `http.Server.Handler`、或配合 `http.FileServer` 提供静态资源，而不必用 Gin 自带的 `r.Static`。

## Links

- [Gin](/docs/CS/Go/Framework/Gin.md)
- [Architecture](/docs/CS/Go/Framework/Gin/Architecture.md)
- [Middleware](/docs/CS/Go/Framework/Gin/Middleware.md)
- [Echo](/docs/CS/Go/Echo.md)
- [Hertz Routing](/docs/CS/Go/Framework/Hertz/Routing.md)

## References

- <https://github.com/gin-gonic/gin/blob/master/tree.go>
- <https://pkg.go.dev/github.com/gin-gonic/gin#Engine.GET>
- <https://github.com/julienschmidt/httprouter>
