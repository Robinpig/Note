## Introduction

[Caddy 2](https://caddyserver.com/) is a powerful, enterprise-ready, open source web server with automatic HTTPS written in Go.


## Build

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




## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [nginx](/docs/CS/CN/nginx/nginx.md)