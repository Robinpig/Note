## Introduction

[Caddy 2](https://caddyserver.com/) 是用 Go 编写的现代 Web 服务器、反向代理与负载均衡器，最大卖点是 **自动 HTTPS**：默认通过 ACME 协议（Let's Encrypt / ZeroSSL）自动申请、部署、续期 TLS 证书，几乎零配置即可获得可信 HTTPS。

版本与架构（2026-10）：当前稳定版 **2.11.x**；单二进制，Go netpoll + goroutine 并发，内存安全。性能低于 nginx/HAProxy（GC 与调度开销），self-hosting 与中小流量场景无感。HTTP/3（QUIC）为实验性支持。

配置有双形态：**Caddyfile**（人类友好、简洁）与 **JSON API**（程序化、支持热重载 `caddy reload`）。

## 自动 HTTPS 机制

Caddy 内置了完整的 ACME 客户端，站点名写进 Caddyfile 即触发签发：

```
app.example.com {
    reverse_proxy localhost:8080
}
```

- 前置条件只有两个：域名 DNS 指向本机、80/443 对外可达（ACME challenge）
- 本地测试用 `localhost` 会自动签**自签**证书，不依赖外网
- nginx 做到同等体验需要 certbot + 续期定时任务 + 续期后 reload 的完整编排；nginx 侧的手工流程见 [TLS](/docs/CS/CN/nginx/tls.md)

## 反代速览

```
api.example.com {
    handle_path /api/* {
        reverse_proxy backend:3000
    }
    handle {
        respond "Not Found" 404
    }
}
```

- WebSocket **自动处理** Upgrade，无需 nginx 那样的 `proxy_set_header Upgrade` 模板
- 2.11 起反代 HTTPS 上游时自动重写 Host 头，少一类「直连正常、过代理 404」的问题
- Docker 部署要挂 `data` 卷存证书，否则每次重启重新签发，会撞 Let's Encrypt 限频

## 与 nginx 的取舍

| 维度 | Caddy | nginx |
| :-- | :-- | :-- |
| HTTPS | 自动（ACME 内置） | certbot/自管 |
| 配置心智 | 站点块，极少指令 | 指令多、默认值多、覆盖规则细 |
| 性能 | 中等 | 高 |
| 细粒度控制（缓存/限流/日志） | 较弱或插件 | 强 |
| 生态复用 | Go 插件（xcaddy 编译） | C 模块 / OpenResty |

选型建议：内网服务、个人项目、不想管证书 → Caddy；高并发边缘、精细控制 → [nginx](/docs/CS/CN/nginx/nginx.md)；同类对比见 [compare](/docs/CS/CN/nginx/compare.md)。

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)
- [compare](/docs/CS/CN/nginx/compare.md) — 四代代理横评
- [TLS](/docs/CS/CN/nginx/tls.md) — 手工管理证书时的 nginx 侧事实

## References

- <https://caddyserver.com/docs/>
- <https://caddyserver.com/docs/caddyfile>
