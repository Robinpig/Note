## Introduction

> [!NOTE]
> 版本基线（2026-10-21 经 GitHub releases API 核实）：最新 release 为 **0.9.0**（2026-09-09 发布）。项目仍处 0.x，官方明言 pre-1.0 阶段 API 稳定性不做保证。

[Pingora](https://github.com/cloudflare/pingora) 是 Cloudflare 用 **Rust** 写的可编程 HTTP 代理框架（Apache-2.0）：2022 年 9 月首次对外披露时日请求量已超 1 万亿，2024 年 2 月正式开源，替代了 Cloudflare 原先基于 nginx 的代理基础设施，如今支撑其每秒 4000 万级（README 口径 40M+）的互联网请求。同流量对比旧服务，官方口径是 CPU 约省 70%、内存约省 67%。

它有两个与 nginx 截然不同的个性：

- **多线程，而非事件循环单线程**：tokio 多线程运行时加 work stealing，连接池跨线程共享，没有 nginx 按 worker 进程各自维护连接池、进程越多复用率越劣化的问题
- **无配置文件**：官方原话 "Pingora is a library and toolset, not an executable binary"——Rust 代码即配置，你用 `ProxyHttp` trait 写出自己的代理再编译，拿不到开箱即用的服务器二进制

价值主张是「内存安全地替代 C/C++ 写的代理服务」，定位与 nginx/Caddy 这类现成产品完全不同。

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
- [Caddy](/docs/CS/CN/Caddy.md)

## References

- [cloudflare/pingora](https://github.com/cloudflare/pingora)
- [Pingora releases](https://github.com/cloudflare/pingora/releases)
- [Cloudflare Blog - Open sourcing Pingora](https://blog.cloudflare.com/pingora-open-source/)
- [Cloudflare Blog - How we built Pingora, the proxy that connects Cloudflare to the Internet](https://blog.cloudflare.com/how-we-built-pingora-the-proxy-that-connects-cloudflare-to-the-internet/)
