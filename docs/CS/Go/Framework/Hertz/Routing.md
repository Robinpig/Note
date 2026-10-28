# Hertz Routing

## Introduction

Hertz 的路由建立在一棵 **radix tree（前缀压缩 trie）** 上，思路与 httprouter 同源（gin 的 httprouter 衍生实现也属这一类）。同一棵树里同时容纳三类节点：静态段、参数段 `:name`、通配段 `*path`，并在注册时计算优先级，使得请求到来时以最少比较命中正确 handler。

路由层是 Hertz 四层架构里的第二层，位于应用层 handler 之下、协议层之上——协议层解析出 HTTP method 与 path 后，交给 router 的 radix tree 匹配，命中后把上下文交给对应 handler 与中间件链。

## Route Types and Priority

三种路径段的语义与匹配优先级（从高到低）：

| 类型 | 写法 | 示例 | 说明 |
| :-- | :-- | :-- | :-- |
| 静态段 | 普通路径 | `/users/new` | 优先级最高，精确匹配 |
| 参数段 | `:name` | `/users/:id` | 单段通配，匹配一个路径片段 |
| 通配段 | `*` | `/files/*path` | 贪婪匹配剩余全部路径，通常用于静态资源 |

**优先级规则**：当多条规则都能匹配同一个 URL 时，静态段优先于参数段，参数段优先于通配段。例如同时注册 `/users/new` 与 `/users/:id`，请求 `GET /users/new` 命中静态规则——这与 httprouter 的「静态优先」一致。参数段与通配段不能在同一位置冲突（如 `/users/:id` 与 `/users/*path` 在同一父节点下会因歧义在**注册期 panic**），注册顺序不影响最终优先级，优先级由段类型决定。

## Method Registration

Hertz 提供全套 REST 动词，handler 签名统一为 `func(c context.Context, ctx *app.RequestContext)`：

```go
h.GET("/users/:id", func(c context.Context, ctx *app.RequestContext) {
    id := ctx.Param("id")             // 取参数段
    ctx.String(200, "user %s", id)
})
h.POST("/users", createUser)
h.PUT("/users/:id", updateUser)
h.DELETE("/users/:id", deleteUser)
h.PATCH("/users/:id", patchUser)
h.HEAD("/health", health)
h.OPTIONS("/users", options)
h.Any("/echo", echoHandler)           // 匹配任意方法
```

参数取用 API（均在 `*app.RequestContext` 上）：

- `ctx.Param("id")`：路径参数段。
- `ctx.Query("q")` / `ctx.DefaultQuery("q", "default")`：URL query。
- `ctx.PostForm("f")` / `ctx.FormValue("f")`：表单字段。
- `ctx.GetHeader("X-Token")`：请求头。
- `ctx.Cookie("sid")`：Cookie。

## Route Groups

分组用于给「同一前缀 + 同一批中间件」的路由批量收口，避免每条路由重复挂中间件：

```go
v1 := h.Group("/api/v1")              // 分组前缀
v1.Use(authMiddleware)                // 仅对该组生效的中间件
v1.GET("/orders", listOrders)
v1.GET("/orders/:id", getOrder)

admin := h.Group("/admin")
admin.Use(adminAuth, auditLog)        // 分组级中间件链
admin.POST("/users", createAdminUser)
```

分组上的中间件在**全局中间件之后、具体 handler 之前**执行，优先级为：全局 `h.Use` → 分组 `g.Use` → handler。嵌套分组会逐层叠加中间件。

## Static Files and Templates

- 静态资源：`h.Static("/assets", "./public")` 把本地目录映射到 URL 前缀；`h.StaticFile("/favicon.ico", "./favicon.ico")` 映射单文件。
- 模板渲染：`h.LoadHTMLGlob("./views/*.html")` 或 `h.LoadHTMLFiles(...)` 加载模板后，handler 内 `ctx.HTML(200, "index.tmpl", data)` 渲染。
- 直连未注册路径：Hertz 提供 `h.NoRoute` / `h.NoMethod` 注册兜底 handler，用于 404 / 405 的自定义响应。

## Links

- [Hertz](/docs/CS/Go/Framework/Hertz.md)
- [Middleware](/docs/CS/Go/Framework/Hertz/Middleware.md)
- [Binding and Rendering](/docs/CS/Go/Framework/Hertz/Binding_Rendering.md)
- [Gin](/docs/CS/Go/Framework/Gin.md)
- [Echo](/docs/CS/Go/Echo.md)

## References

- <https://github.com/cloudwego/hertz>
- <https://www.cloudwego.io/docs/hertz/tutorials/basic-feature/routing/>
- <https://github.com/julienschmidt/httprouter>
