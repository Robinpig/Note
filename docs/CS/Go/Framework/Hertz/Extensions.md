# Hertz Extensions

## Introduction

Hertz 本体只交付「核心框架 + 代码生成 + 客户端」，把「电池」交给社区组织 **hertz-contrib**——截至 2026 年该组织下有 37+ 个扩展仓库，覆盖注册发现、可观测性、鉴权、协议等。此外 Hertz 自带日志抽象 `hlog`，可插拔到 zap / logrus 等实现。理解 Hertz 的扩展面，本页聚焦三块：**hertz-contrib 生态、hlog 日志、可观测性**。

> [!WARNING]
>
> 标准库 `net/http` 的中间件**不能**以原签名直接挂到 Hertz 的中间件链上——二者 handler 签名不同（Hertz 的 `func(ctx, *RequestContext)` vs `net/http` 的 `func(http.ResponseWriter, *http.Request)`）。复用标准库 handler 需经 Hertz 的 adapter，或直接改用 hertz-contrib 里的同名实现（如 hertz-contrib/cors 对应 gorilla/cors 的语义）。

## hertz-contrib Ecosystem

按用途归类（仓库名即能力）：

| 类别 | 代表仓库 | 能力 |
| :-- | :-- | :-- |
| 注册发现 | registry（nacos / consul / etcd / eureka / polaris / servicecomb / zookeeper / redis） | 服务注册与发现，配合 Client 的 load balancing client |
| 可观测性 | obs-opentelemetry、monitor-prometheus、pprof、sentry、tracer（opentracing） | Metric / Logger / Tracing 开箱集成，或接入既有监控 |
| 鉴权安全 | jwt、keyauth、basicauth、casbin、secure、csrf、cors | 令牌校验、访问控制、跨域、安全头 |
| 传输/协议 | http2、websocket、etag、autotls | HTTP/2（ALPN）、WebSocket、ETag、Let's Encrypt |
| 限流 | limiter（基于 bbr 算法） | 自适应限流 |
| 其它 | requestid、sessions、gzip、i18n、lark、opensergo | 请求 ID、会话、压缩、国际化、飞书回调 |

这些扩展都通过 `server.WithXXX` 选项或 `h.Use(...)` 中间件接入，与服务端中间件链完全一致，不侵入业务代码。

## hlog Logging

`pkg/common/hlog` 是 Hertz 的日志抽象，提供 `hlog.Info / Warn / Error / Fatal` 等接口与 `hlog.SetLogger(...)` 切换实现。默认实现足够开发期使用；生产环境通常替换为 zap / logrus 等结构化日志实现（由 hertz-contrib/logger-* 提供），统一日志格式与采样策略。

```go
import "github.com/cloudwego/hertz/pkg/common/hlog"

hlog.Infof("handled path=%s", ctx.Request.URI().Path())
```

`hlog` 也服务于内置的中间件（如 access log）与 client 中间件，因此切换 logger 实现会同时影响框架内部日志输出——这也是为什么 Production 环境值得尽早把 logger 定下来。

## Observability

Hertz 的可观测性以 **obs-opentelemetry** 为核心：一条集成即可同时拿到 Metric、Logger、Tracing，且开箱可用（自动埋点 handler 耗时、状态码、调用链路）。此外：

- **pprof**：通过 hertz-contrib/pprof 暴露 `/debug/pprof`，配合 Go 原生的 `pprof` / `trace` 做性能剖析（见 [Go Tool](/docs/CS/Go/Tool.md)）。
- **Prometheus**：monitor-prometheus 暴露 `/metrics`，接入既有 Prometheus + Grafana。
- **Tracing**：除 OpenTelemetry 外，tracer 仓库提供基于 OpenTracing 的旧链路方案。

这三块与 CloudWeGo 全家桶（Kitex / Netpoll）的观测体系对齐，微服务里 Hertz 与 Kitex 的链路可以接到同一条 trace 上。

## Links

- [Hertz](/docs/CS/Go/Framework/Hertz.md)
- [Middleware](/docs/CS/Go/Framework/Hertz/Middleware.md)
- [Client](/docs/CS/Go/Framework/Hertz/Client.md)
- [Code Generation](/docs/CS/Go/Framework/Hertz/Code_Generation.md)

## References

- <https://github.com/hertz-contrib>
- <https://github.com/cloudwego/hertz/tree/main/pkg/common/hlog>
- <https://github.com/hertz-contrib/obs-opentelemetry>
- <https://www.cloudwego.io/docs/hertz/tutorials/observability/
