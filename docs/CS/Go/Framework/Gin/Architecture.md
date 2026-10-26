# Gin Architecture

## Introduction

Gin 的核心是 `gin.Engine`——一个把路由、中间件、配置、`gin.Context` 池全部收拢在一起的对象。理解 Gin，本质上是理解 Engine 如何**作为 `http.Handler` 被 `net/http` 托管**，以及每个请求如何在 `gin.Context` 上流动。本章拆解 Engine 的结构、请求生命周期、`gin.Context` 池化复用与运行模式。

## Engine and http.Handler

`gin.Engine` 实现了标准库的 `http.Handler` 接口，所以它可以直接交给 `http.ListenAndServe`：

```go
type Engine struct {
    RouterGroup                 // 内嵌的 root 分组，承载 r.GET/POST 与 r.Use
    trees            methodTrees // 每个 HTTP method 一棵 radix tree
    pool             sync.Pool   // *gin.Context 对象池
    handlers         HandlersChain // 全局中间件（来自 engine.Use）
    // ... 模式、重定向策略、受信代理等字段
}
```

```go
func (engine *Engine) ServeHTTP(w http.ResponseWriter, req *http.Request) {
    c := engine.allocateContext()      // 从 pool 取 Context
    c.writermem.reset(w)
    c.Request = req
    c.reset()
    engine.handleHTTPRequest(c)        // 路由匹配 + handler 链执行
    c.writermem.WriteHeaderNow()
    engine.releaseContext(c)           // 放回 pool
}
```

> [!NOTE]
>
> 这正是 "Gin 是 `net/http` 的薄封装" 的含义：`*http.Request` 与 `http.ResponseWriter` 原样透传给 `gin.Context`，Gin 只是在其上叠加了路由匹配与中间件链，最终仍由标准库完成 TCP 监听、TLS、连接管理。

## Request Lifecycle

`handleHTTPRequest` 是请求处理的心脏，三步完成路由命中与执行：

1. 按 `req.Method` 从 `trees` 取出对应的 `methodTree`（如 GET 树、POST 树）。
2. 用 `req.URL.Path` 在 radix tree 上查找匹配的 `node`，拿到 `handlers` 链（含全局中间件 + 分组中间件 + 末端 handler）。
3. 把 `handlers` 注入 `c.handlers`，置 `c.index = -1`，调用 `c.Next()` 依次执行；执行完毕后写回响应。

```go
func (c *Context) Next() {
    c.index++
    for c.index < len(c.handlers) {
        c.handlers[c.index](c)   // 当前 handler 内部可再调 c.Next()
        c.index++
    }
}
```

`c.Next()` 的 `index` 推进机制是中间件"洋葱模型"的底层支撑：中间件在调用 `c.Next()` 之前的代码是"前置"，之后的代码是"后置"（详见 [Middleware](/docs/CS/Go/Framework/Gin/Middleware.md)）。

## Context Pooling

每个请求都会新建并丢弃一个 `gin.Context`，而高并发下 Context 的频繁分配/GC 压力很大。Gin 用 `sync.Pool` 复用：

- 请求到达时 `engine.allocateContext()` 从 `pool` 取；若池空则 `pool.New` 构造新的。
- 请求处理完 `releaseContext(c)` 放回池中。

> [!WARNING]
>
> `sync.Pool` 不是缓存：放入的对象在逻辑上已被"删除"，只是物理内存尚在，最多存活两轮 GC，期间若被取用即可复用。因此**不要在 handler 返回后持有 `gin.Context` 或其字段的引用**（如把 `c` 塞进 goroutine 不传值），否则可能读到被复用的脏数据。需要跨 goroutine 传值时，用 `c.Copy()` 得到一份与池无关的副本，或显式拷贝所需字段。

## Starting the Server

| 方法 | 说明 |
| :-- | :-- |
| `r.Run()` | `http.ListenAndServe(":8080", r)`，默认 `:8080` |
| `r.Run(addr)` | 指定监听地址 |
| `r.RunTLS(addr, cert, key)` | 启用 HTTPS |
| `r.RunUnix(file)` | 监听 Unix socket |
| `r.RunFd(fd)` | 接管已打开的文件描述符（如 systemd socket activation；v1.12.0 修复其 `os.File` 泄漏） |
| `r.Handler()` | 返回实现了 `http.Handler` 的 Engine 自身，便于嵌入已有 `http.Server` 或 `http.ServeMux` |

典型生产写法是不用 `Run`，而是把 `r` 塞进 `&http.Server{Handler: r}` 以自定义 `ReadTimeout` / `Shutdown`：

```go
srv := &http.Server{Addr: ":8080", Handler: r}
srv.ListenAndServe()
```

## Run Modes

Gin 有三种运行模式，由环境变量 `GIN_MODE` 或 `gin.SetMode` 控制：

| 模式 | 常量 | 行为 |
| :-- | :-- | :-- |
| Debug（默认） | `gin.DebugMode` | 打印路由注册信息、Recovery 打印完整 panic 栈、模板加载改动能热感知 |
| Release | `gin.ReleaseMode` | 关闭 debug 输出、Recovery 不再向响应写栈；**生产务必设此模式** |
| Test | `gin.TestMode` | 抑制多余输出，便于测试 |

`gin.IsDebugging()` 可查询当前是否 Debug。`gin.SetMode(gin.ReleaseMode)` 应在 `main` 早期调用；也可 `GIN_MODE=release ./app`。

## Links

- [Gin](/docs/CS/Go/Framework/Gin.md)
- [Routing](/docs/CS/Go/Framework/Gin/Routing.md)
- [Middleware](/docs/CS/Go/Framework/Gin/Middleware.md)
- [Go net](/docs/CS/Go/net.md)

## References

- <https://github.com/gin-gonic/gin/blob/master/gin.go>
- <https://pkg.go.dev/github.com/gin-gonic/gin#Engine>
- <https://github.com/julienschmidt/httprouter>
