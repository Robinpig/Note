# Hertz Client

## Introduction

Hertz 不只是服务端框架——它在 `pkg/app/client` 下自带一个 **HTTP 客户端**，与服务端共享同一套 `*app.RequestContext` 模型与中间件机制。这让「同进程内既做 HTTP 服务又发 HTTP 调用」的场景可以复用同一套上下文语义（超时、透传、中间件），不必在 `net/http.Client` 与框架之间来回转换。

与 gin/echo 对照：gin/echo 通常只提供服务端，发请求直接用标准库 `net/http`；Hertz 把客户端一并纳入框架，并提供面向微服务的「带服务发现 / 负载均衡」的客户端形态。

## Client Modes

Hertz 客户端有三种模式，通过 `client.NewClient(opts...)` 的选项切换：

| 模式 | 说明 | 适用 |
| :-- | :-- | :-- |
| host client（默认） | 按 host 做 DNS 缓存与连接池，复用连接 | 绝大多数直连下游的场景 |
| standard client | 把底层 transport 委托给标准库 `net/http` 的 transport | 需要兼容标准库行为 / 调试 |
| load balancing client | 配合 resolver + loadbalancer，按服务名做服务发现与负载均衡 | 微服务间调用（对接 hertz-contrib/registry） |

```go
import "github.com/cloudwego/hertz/pkg/app/client"

c, err := client.NewClient()                       // 默认 host client
if err != nil { panic(err) }

status, body, err := c.Get(context.Background(), nil, "http://example.com/api")
// status: 响应状态码；body: []byte；err: 网络/协议错误
```

- host client 默认带连接池与 keep-alive，重复请求同 host 复用 TCP 连接，降低握手开销。
- load balancing client 把「服务名 → 实例地址」的解析交给 resolver，再由负载均衡策略选一个实例，是 Hertz 在微服务网格里取代裸 `net/http` 的关键形态。

## Client Middleware

客户端复用与服务端一致的 `app.HandlerFunc` 签名，通过 `client.WithMiddleware` 注册：统一注入鉴权头、重试、链路追踪、耗时统计等横切逻辑，与服务端中间件写法完全相同（见 [Middleware](/docs/CS/Go/Framework/Hertz/Middleware.md)）。

```go
c, _ := client.NewClient(
    client.WithMiddleware(authInjector, retryMiddleware),
)
```

## Request Building

除了 `c.Get/Post`，Hertz 客户端也支持携带请求体、头、查询参数，并把响应反序列化到结构体：

```go
req, _ := protocol.NewRequest("POST", "http://example.com/api", bytes.NewReader(payload))
req.Header.SetMethod("POST")
req.SetBody(payload)

resp := app.NewResponse()
err := c.Do(context.Background(), req, resp)
// resp.Body() 取响应体字节；resp.StatusCode() 取状态码
```

`protocol.NewRequest` 与 `app.NewResponse` 复用了服务端协议层的对象，因此客户端与服务端在「请求 / 响应」这一层共用同一套零拷贝缓冲与对象池模型。

## Hertz Client vs net/http.Client

| 维度 | Hertz client | net/http.Client |
| :-- | :-- | :-- |
| 上下文模型 | 复用 `*app.RequestContext` / 协议层对象 | `*http.Request` / `*http.Response` |
| 中间件 | 内建（与服务端同签名） | 需手动在 Transport / 调用处包 |
| 服务发现 | load balancing client 原生支持 | 需外接（如 consul/api） |
| 性能 | host client 连接池 + 零拷贝 | 标准连接池 |
| 生态 | 通过 hertz-contrib 扩展 | 全 Go 生态通用 |

一句话：**单进程内已经用了 Hertz 服务端，发下游请求优先用 Hertz client**（共享上下文与中间件）；若是独立的小工具或需要最大生态兼容，标准库 `net/http` 仍是更省心的选择。

## Links

- [Hertz](/docs/CS/Go/Framework/Hertz.md)
- [Architecture](/docs/CS/Go/Framework/Hertz/Architecture.md)
- [Extensions](/docs/CS/Go/Framework/Hertz/Extensions.md)

## References

- <https://github.com/cloudwego/hertz>
- <https://www.cloudwego.io/docs/hertz/tutorials/client/>
- <https://github.com/cloudwego/hertz/tree/main/pkg/app/client>
