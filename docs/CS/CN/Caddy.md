## Introduction

[Caddy 2](https://caddyserver.com/) 是用 Go 编写的现代 Web 服务器、反向代理与负载均衡器，最大卖点是 **自动 HTTPS**：默认通过 ACME 协议（Let's Encrypt / ZeroSSL）自动申请、部署、续期 TLS 证书，几乎零配置即可获得可信 HTTPS。相比手工管理证书链的 Nginx，Caddy 把 TLS 生命周期完全自动化。

## 自动 HTTPS 机制

- Caddy 启动时为配置的域名自动向 CA 发起 ACME **HTTP-01 / TLS-ALPN-01** 挑战，验证域名控制权。
- 证书存入数据目录（默认 `$XDG_DATA_HOME/caddy`），到期前自动续期（OCSP  Stapling 默认开启）。
- 仅监听 `:80` 时会自动重定向到 `:443` 并补全 HTTPS。

## 配置形态

Caddy 提供两种配置入口：

- **Caddyfile**（人类友好）：声明式描述站点、反向代理、路由。
- **JSON 配置 API**（机器友好）：通过 `/config/` 端点运行时增删改，适合动态场景（如服务发现后自动写后端）。

```caddyfile
example.com {
    reverse_proxy localhost:8080 localhost:8081
    encode gzip zstd
    log
}
```

```yaml
# docker-compose 拉起（默认不自动开 https 需显式声明站点）
services:
  caddy:
    image: caddy
    restart: unless-stopped
    ports:
      - '80:80'
      - '443:443'
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
volumes:
  caddy_data:
```

## 反向代理与负载均衡

`reverse_proxy` 指令直接内置后端池与 `health_uri` 探活，支持 `lb_policy`（如 `round_robin`、`least_conn`、`ip_hash`）；还可做 `header` 增删、URI 重写、灰度路由，能力对标 Nginx 的 `proxy_pass` + `upstream`。

## 与 Nginx / HAProxy 的取舍

- **Nginx**：生态最成熟、模块最多，TLS 需手工配证书（或借助 certbot）；Caddy 在「开箱即 HTTPS」上更省心。
- **HAProxy**：专注 L4/L7 纯代理、连接数极高；Caddy 更偏向「Web 服务器 + 自动证书」，二者可在边缘分层部署。
- Caddy 的 Go 单二进制、无外部依赖，非常适合容器化与边缘小节点。

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)
- [TLS](/docs/CS/CN/TLS.md)
- [HTTPS](/docs/CS/CN/HTTP/HTTPS.md)
- [Computer Network](/docs/CS/CN/CN.md)

## References

- [Caddy Official Documentation](https://caddyserver.com/docs/)
- [Caddyfile Concepts](https://caddyserver.com/docs/caddyfile/concepts)
