## Introduction

[go-resty](https://resty.dev/) 是 Go 生态里一款以「好用」为目标的 RESTful HTTP 客户端库，构建在标准库 `net/http` 之上。
标准库 `http.Client` 足够强大但样板代码多（手动构造 request、设置 header、编解码 body、关 resp.Body），go-resty 用链式 API 把这些常见动作收进一个 Client，降低调用成本。

## Client and Request

通常先建一个可复用的 Client（内部复用连接池，类似标准库应复用 `http.Client`），在其上设置 baseURL、公共 header、超时：

```go
client := resty.New().
    SetBaseURL("https://api.example.com").
    SetTimeout(10 * time.Second).
    SetHeader("Authorization", "Bearer "+token)

// Get/Post 等，SetResult 直接反序列化
var user User
resp, err := client.R().
    SetPathParam("id", "123").
    SetResult(&user).                 // 按 Content-Type 自动 JSON 解码
    Get("/users/{id}")
```

- POST/PUT 用 `SetBody(u)`，传入结构体时默认按 JSON 编码并设置 Content-Type；
- 查询参数 `SetQueryParam`/`SetQueryParams`、表单 `SetFormData`、路径参数 `SetPathParam`；
- 请求/响应可用 `SetResult`/`SetError` 直接绑定到结构体，少写手写 `json.Unmarshal`。

## Retry and Middleware

- **重试**：`SetRetryCount(n)`、`SetRetryWaitTime`、`SetRetryMaxWaitTime`，并可用 `AddRetryCondition` 自定义「什么响应算可重试」（如网络错误、429/5xx）；重试默认带指数退避。
- **钩子/中间件**：`OnBeforeRequest`、`OnAfterResponse`、`OnError` 可统一注入鉴权、日志、链路追踪 header、指标埋点——横切逻辑集中在 Client 上，而非每个调用点重复。
- 也支持代理、TLS、Cookie、多部分上传、basic auth/oauth token 自动刷新等常见客户端需求。

## When to Use

| 场景 | 选择 |
| --- | --- |
| 追求最少依赖、需求简单 | 标准库 `net/http` |
| 大量 REST 调用、想要链式 API/自动编解码/重试/钩子 | go-resty |
| 已在大框架生态内 | 随框架自带 client（如 Hertz/微服务框架的 RPC 客户端） |

注意：go-resty 是**客户端**库，不提供服务端路由；服务端 Web 框架对应 [Gin](/docs/CS/Go/Framework/Gin.md)/[Echo](/docs/CS/Go/Echo.md)。
重试要注意与写操作的幂等性配合（非幂等 POST 盲目重试可能重复下单），这是所有 HTTP 重试客户端的共性问题，不是 go-resty 独有。

## Links

- [Golang](/docs/CS/Go/Go.md)
- [Go net](/docs/CS/Go/net.md)
- [Gin](/docs/CS/Go/Framework/Gin.md) / [Echo](/docs/CS/Go/Echo.md)

## References

1. [go-resty 官方文档](https://resty.dev/)
2. [go-resty (GitHub)](https://github.com/go-resty/resty)
