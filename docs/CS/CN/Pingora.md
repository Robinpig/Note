## Introduction

[Pingora](https://github.com/cloudflare/pingora) 是 Cloudflare 开源的 **Rust 网络服务框架**（Apache-2.0），用于构建快速、可靠、可编程的代理与网关。它支撑着 Cloudflare CDN 每秒数千万级别的请求，2024 年初开源。

版本现状（2026-10）：**0.9.0**（2026-09-09 发布）——注意它仍然是 **0.x 的框架**，**不提供开箱即用的服务器二进制**；你用 Rust 实现 `ProxyHttp` trait 写出自己的代理再编译。价值主张是「内存安全地替代 C/C++ 写的代理服务」，定位与 nginx/Caddy 这类现成产品完全不同。

## Core Features

- **异步 Rust**：多线程 tokio 运行时，HTTP/1 与 HTTP/2 端到端代理（HTTP/3 计划中，0.9 未含）
- **TLS 后端可选**：OpenSSL、BoringSSL、s2n-tls、rustls（实验）
- **多线程无惊群**：线程间共享监听，连接均匀分配，冷连接转移——不需要 nginx 的 accept mutex / EPOLLEXCLUSIVE 那套演进（对照见 [Event](/docs/CS/CN/nginx/event.md)）
- **优雅升级**：不中断连接地换版本（类似 nginx 热升级的 fd 传递，但内置在框架里）
- **可编程**：请求/响应各阶段都有回调 trait，负载均衡策略（含 Ketama 一致性哈希）可插拔
- **配套子 crate**：`pingora-proxy`（代理逻辑）、`pingora-load-balancing`、`pingora-ketama`、`pingora-memory-cache`（TinyUfo 算法）、`pingora-timeout`

## Minimal Proxy Skeleton

```rust
use async_trait::async_trait;
use pingora::prelude::*;

fn main() {
    let mut server = Server::new(None).unwrap();
    server.bootstrap();

    let mut proxy = http_proxy_service(&server.configuration, MyGateway);
    proxy.add_tcp("0.0.0.0:8080");

    server.add_service(proxy);
    server.run_forever();
}

struct MyGateway;

#[async_trait]
impl ProxyHttp for MyGateway {
    type CTX = ();

    fn new_ctx(&self) -> Self::CTX {}

    async fn upstream_peer(
        &self, _session: &mut Session, _ctx: &mut Self::CTX,
    ) -> Result<Box<HttpPeer>> {
        let peer = Box::new(HttpPeer::new("10.0.0.11:8000", false, "".to_string()));
        Ok(peer)
    }
}
```

nginx 做同样的事是几行配置；Pingora 是几百行起步的框架——换来的是任意业务逻辑直接嵌进代理层（鉴权、改写、路由），不必受配置语言表达力限制。

## Comparison with nginx

| 维度 | Pingora | nginx |
| :-- | :-- | :-- |
| 形态 | 框架（写代码） | 服务器（写配置） |
| 语言/内存安全 | Rust，无 UB | C，靠开发纪律 |
| 并发模型 | 多线程 tokio | 多进程 + epoll |
| 动态配置 | 代码定义（可做 API 化） | 静态文件 + reload |
| 扩展 | Rust trait，编译期类型检查 | C 模块 / Lua（OpenResty） |
| 适用 | 自研网关/边缘、内存安全优先 | 通用 Web 服务器/反代 |

结论：Pingora **不是 nginx 的 drop-in 替代**——它是给「要自研代理、且愿意维护 Rust 代码」的团队的框架。同类对比与选型见 [compare](/docs/CS/CN/nginx/compare.md)。

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)
- [compare](/docs/CS/CN/nginx/compare.md) — 四代代理横评
- [Event](/docs/CS/CN/nginx/event.md) — 惊群问题的进程/线程解法对照

## References

- <https://github.com/cloudflare/pingora>
- <https://blog.cloudflare.com/pingora-open-source/>
