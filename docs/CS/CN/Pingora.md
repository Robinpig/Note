## 简介

[Pingora](https://github.com/cloudflare/pingora) 是一个 Rust 框架，用于构建快速、可靠且可编程的网络系统。

**特性亮点**：
- 异步 Rust：快速且可靠
- HTTP 1/2 端到端代理
- 基于 OpenSSL 或 BoringSSL 的 TLS
- gRPC 和 WebSocket 代理
- 优雅重载（Graceful reload）
- 可定制的负载均衡和故障转移策略
- 支持多种可观测性工具

与 nginx 的对比

- nginx 多进程模型隔离 -- CPU 核心、连接复用 | Pingora 在多线程之间共享连接以减少 TCP 和 TLS 握手
- 其他特性：
- 安全性：Rust

| | nginx | Pingora |
| -- | -- | -- |
| 进程模型 | 多进程 | 多线程 |

## 链接

- [nginx](/docs/CS/CN/nginx//nginx.md)
- [HTTP](/docs/CS/CN/HTTP/HTTP.md)

## 参考文献

1. [Open sourcing Pingora: our Rust framework for building programmable network services](https://blog.cloudflare.com/pingora-open-source)
2. [How we built Pingora, the proxy that connects Cloudflare to the Internet](https://blog.cloudflare.com/zh-cn/how-we-built-pingora-the-proxy-that-connects-cloudflare-to-the-internet-zh-cn/)
