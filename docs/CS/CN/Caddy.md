## 简介

[Caddy 2](https://caddyserver.com/) 是一个用 Go 编写的强大、企业级、开源 Web 服务器，支持自动 HTTPS。

## 构建

vim docker-compose.yaml
```yaml
services:
  caddy:
    image: caddy
    restart: unless-stopped
    ports:
      - '80:80'
```
`docker compose up -d` 拉起容器 默认不开启https

## 链接

- [计算机网络](/docs/CS/CN/CN.md)
- [nginx](/docs/CS/CN/nginx/nginx.md)
