# Gin Extensions and Ecosystem

## Introduction

Gin 刻意保持内核精简——路由、中间件、绑定、渲染之外几乎不内置。HTTP 客户端、OpenAPI 文档、CORS、Session 等能力都来自 `gin-contrib` 与社区库。本章梳理常用扩展，并点明 Gin 与 Hertz 在"客户端/代码生成"上的关键差异。

## gin-contrib

`gin-contrib` 是官方背书（同组织维护）的扩展集合，常用成员：

| 仓库 | 能力 |
| :-- | :-- |
| `gin-contrib/cors` | 跨域 CORS 中间件（注意历史 CVE-2019-25211 通配 origin 问题，已修） |
| `gin-contrib/sessions` | 基于 `gorilla/sessions` 的 Cookie/Redis Session |
| `gin-contrib/gzip` | 响应 Gzip 压缩 |
| `gin-contrib/static` | 静态文件服务（也可直接用标准库 `http.FileServer`） |
| `gin-contrib/zap` / `gin-contrib/logger` | 接入 Zap / 结构化日志 |
| `gin-contrib/pprof` | 挂载 `net/http/pprof` 调试端点 |
| `gin-contrib/secure` | 安全响应头（HSTS、X-Frame-Options 等） |
| `gin-contrib/requestid` | 注入/透传请求 ID |
| `gin-contrib/opentelemetry` / `gin-contrib/prometheus` | 可观测性（Trace / Metrics） |
| `gin-contrib/authz` | 基于 Casbin 的鉴权 |
| `gin-contrib/jwt` | JWT 鉴权（另有社区 `gin-jwt`） |
| `gin-contrib/sentry` | 接入 Sentry 错误收集 |

## OpenAPI / Swagger

- `swaggo/gin-swagger` + `swaggo/swag`：用结构体/handler 上的注解生成 `swagger.json`，再挂载 `gin-swagger` UI。
- 标准 `net/http` 的 OpenAPI 工具也可直接套在 `r.Handler()` 上。

## HTTP Client

> [!NOTE]
>
> **Gin 不自带 HTTP 客户端。** 需要从 Gin 服务向外发请求时，直接用标准库 `net/http.Client`，或更顺手的 [go-resty](/docs/CS/Go/Framework/go-resty.md)。这与 Hertz 自带 `host/standard/load balancing` 三模式 HTTP client 形成对比——Hertz 把客户端也纳入框架，Gin 则坚持"服务端框架"定位。

## Compared with Hertz

| 能力 | Gin | Hertz |
| :-- | :-- | :-- |
| 自带 HTTP 客户端 | 无（用 `net/http` / go-resty） | 有（host/standard/load balancing） |
| 代码生成 | 无官方生成器 | `hz`（Thrift/Protobuf → handler/router/model） |
| 中间件生态 | gin-contrib + 社区，量大且老 | hertz-contrib，较新但增长快 |
| 默认 JSON 引擎 | `encoding/json` | bytedance/sonic |
| 底层网络库 | 标准库 `net/http` | Netpoll（可切 Go Net） |

## When to Choose Gin

- 选 Gin：要最轻量、与 `net/http` 语义最贴近、生态最成熟、团队最熟悉；REST API / 微服务 / BFF 层都适用。
- 不选 Gin：需要内置 HTTP 客户端与 IDL 脚手架、追求极致吞吐且能接受 fasthttp 血统——此时看 [Hertz](/docs/CS/Go/Framework/Hertz.md)；或中小服务直接用 Go 1.22+ 增强后的 `net/http` 省掉框架依赖。

## Links

- [Gin](/docs/CS/Go/Framework/Gin.md)
- [Hertz](/docs/CS/Go/Framework/Hertz.md)
- [go-resty](/docs/CS/Go/Framework/go-resty.md)
- [Echo](/docs/CS/Go/Echo.md)

## References

- <https://github.com/gin-contrib>
- <https://github.com/swaggo/gin-swagger>
- <https://github.com/gin-gonic/gin/blob/master/README.md>
