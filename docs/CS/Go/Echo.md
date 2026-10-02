## Introduction

[Echo](https://echo.labstack.com/) 是 Labstack 出品的 Go 高性能、极简 Web 框架，定位与 [Gin](/docs/CS/Go/Framework/Gin.md) 接近：
在标准库 `net/http` 之上提供路由、中间件、参数绑定、统一错误处理等 Web 服务常用能力，API 风格轻量、文档友好。

```go
package main

import ("net/http"; "github.com/labstack/echo/v4")

func main() {
    e := echo.New()
    e.GET("/users/:id", func(c echo.Context) error {
        id := c.Param("id")                 // 路径参数
        return c.JSON(http.StatusOK, map[string]string{"id": id})
    })
    e.Logger.Fatal(e.Start(":8080"))
}
```

## Routing

- 路由基于高性能 radix tree（类似 httprouter 的实现思路），静态、参数 `:id`、通配 `*` 可共存。
- 支持路由分组 `e.Group("/api/v1")`，组上挂独立中间件与前缀，便于按版本/模块组织。
- REST 动词方法齐全：`GET/POST/PUT/PATCH/DELETE`，静态文件服务、WebSocket 也内建。

## Middleware

中间件是 `func(next echo.HandlerFunc) echo.HandlerFunc` 的责任链，洋葱模型（前置逻辑 → next → 后置逻辑）：

```go
e.Use(middleware.Logger(), middleware.Recover(), middleware.CORS())
g := e.Group("/admin")
g.Use(middleware.BasicAuth(auth))   // 只对该组生效
```

官方提供 Logger、Recover、Gzip、CORS、JWT、BasicAuth、RateLimiter、RequestID、Timeout 等常用中间件，也可自定义。
这套「核心 + 中间件链」与 Java 侧 Servlet Filter / Netty ChannelPipeline 是同一种横切逻辑组织方式。

## Binding and Validation

- `c.Bind(&u)` 根据 `Content-Type` 把 JSON/XML/Form 绑定到结构体；
- 通过标签 `json`/`form`/`query`/`param` 做字段映射；
- 校验接 validator（Echo v4 默认不内置强校验，通常集成 go-playground/validator，在结构体标签上声明规则）；
- 统一错误处理：Handler 返回的 error 交给 `e.HTTPErrorHandler`，可集中转成一致的 JSON 错误响应。

## Echo vs Gin

| 维度 | Echo | Gin |
| --- | --- | --- |
| 路由 | radix tree | httprouter 衍生 radix tree |
| Context | 自有 `echo.Context` 接口 | `gin.Context` 具体类型 |
| 中间件 | 洋葱式，函数签名清晰 | 洋葱式，c.Next() 控制 |
| 生态/采用 | 文档干净，中小项目常用 | 国内采用更广、中间件生态更大 |
| 性能 | 高，二者同档 | 高，部分压测互有胜负 |

两者在性能与核心能力上已非常接近，选型更多看团队熟悉度与周边生态；若只需要标准库级能力，Go 1.22+ 增强的 `net/http`（路由模式、方法匹配）也能省掉框架依赖。

## Links

- [Gin](/docs/CS/Go/Framework/Gin.md)
- [Go net](/docs/CS/Go/net.md) — 底层 net/http
- [Go](/docs/CS/Go/Go.md)

## References

1. [Echo Guide](https://echo.labstack.com/guide)
2. [labstack/echo (GitHub)](https://github.com/labstack/echo)
