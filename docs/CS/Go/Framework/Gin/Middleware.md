# Gin Middleware

## Introduction

Gin 的中间件就是普通的 handler（`func(*gin.Context)`）。它不引入新概念，而是靠 `gin.Context` 上的 `Next()` / `Abort()` 把一串 handler 串成"洋葱"：每个中间件在自己调用 `c.Next()` 之前的代码是前置逻辑，之后的代码是后置逻辑。本章讲清执行模型、全局与分组挂载、内置中间件与自定义写法。

## The Onion Model

请求进入时，`c.handlers` 是一串 `[全局中间件..., 分组中间件..., 末端handler]`。执行由 `c.Next()` 驱动：

```go
func (c *Context) Next() {
    c.index++
    for c.index < len(c.handlers) {
        c.handlers[c.index](c)
        c.index++
    }
}
```

一个典型日志中间件：

```go
func Logger() gin.HandlerFunc {
    return func(c *gin.Context) {
        start := time.Now()
        c.Next()                       // 先把控制权交给后续 handler
        latency := time.Since(start)   // 后置：handler 跑完后才执行
        log.Printf("%s %s %v", c.Request.Method, c.Request.URL.Path, latency)
    }
}
```

`c.Next()` 是可重入的：handler 内部再调 `c.Next()` 只是继续推进 `index`。这意味着中间件可以包裹（wrap）下游逻辑，实现鉴权、耗时统计、panic 恢复等横切关注点。

## Abort

`c.Abort()` 把 `c.index` 置为 `len(c.handlers)`，使 `Next()` 的循环立即结束——**当前中间件调用 `Abort()` 之后的代码仍会执行，但后续尚未运行的 handler 不再执行**：

```go
func Auth() gin.HandlerFunc {
    return func(c *gin.Context) {
        if !valid(c) {
            c.AbortWithStatusJSON(401, gin.H{"error": "unauthorized"})
            return                            // 必须 return，否则本函数后续代码仍跑
        }
        c.Next()
    }
}
```

- `c.Abort()`：仅截断后续 handler，已注册的"后置"逻辑照常执行。
- `c.AbortWithStatus(code)` / `c.AbortWithStatusJSON(code, obj)`：截断并立即写响应。
- `c.IsAborted()`：查询是否已被截断。

> [!WARNING]
>
> `Abort` 不会终止当前函数的执行流——它只是阻止**后续** handler。忘记 `return` 会导致被 abort 的请求继续往下跑本函数剩余代码（以及该中间件在 `Next()` 之后的"后置"逻辑仍会执行）。这与很多人的直觉（"abort = 立刻退出"）不同。

## Global vs Group Middleware

- 全局：`r.Use(Logger(), Recovery())` —— 对所有路由生效。
- 分组级：`g := r.Group("/api"); g.Use(Auth())` —— 只对该分组及其子分组生效。

执行顺序：**全局 `r.Use` → 外层分组 `g.Use` → 内层分组 `g.Use` → 末端 handler**。嵌套分组的中间件逐层叠加，因此越深的分组会累积越多中间件。

## Built-in Middleware

`gin.Default()` 等价于 `gin.New()` 再 `Use(Logger(), Recovery())`：

- **Logger**：把每个请求的 method、path、状态码、耗时打印到 `gin.DefaultWriter`（默认 `os.Stdout`，可用 `gin.DefaultWriter = ...` 重定向到文件；v1.12.0 增加了彩色 latency、可跳过 query 字符串输出）。
- **Recovery**：`defer recover()` 捕获 handler 链中的 panic，阻止单个请求的 panic 拖垮整个 server；Debug 模式下向响应写入 500 与栈信息，Release 模式只写 500（不泄露栈）。v1.12.0 起 `http.ErrAbortHandler` 在被 recover 时不再作为错误上报。

> [!NOTE]
>
> 生产环境**务必 `gin.SetMode(gin.ReleaseMode)`**：否则 Recovery 会把 panic 栈返回给客户端，既泄露内部信息又徒增噪声。

## Custom Middleware

中间件就是一个返回 `gin.HandlerFunc` 的闭包，可携带配置与依赖：

```go
func RateLimit(rps int) gin.HandlerFunc {
    limiter := rate.NewLimiter(rate.Limit(rps), rps)
    return func(c *gin.Context) {
        if !limiter.Allow() {
            c.AbortWithStatusJSON(429, gin.H{"error": "too many requests"})
            return
        }
        c.Next()
    }
}
```

中间件里想跨 handler 传递数据，用 `c.Set(key, val)` / `c.Get(key)`（存在 `c.Keys` map 上），而不是包级全局变量。

## Links

- [Gin](/docs/CS/Go/Framework/Gin.md)
- [Architecture](/docs/CS/Go/Framework/Gin/Architecture.md)
- [Routing](/docs/CS/Go/Framework/Gin/Routing.md)
- [Hertz Middleware](/docs/CS/Go/Framework/Hertz/Middleware.md)

## References

- <https://github.com/gin-gonic/gin/blob/master/context.go>
- <https://pkg.go.dev/github.com/gin-gonic/gin#Engine.Use>
