## Introduction

这一篇是**可直接抄改的配置片段集**：每个场景给出最小可工作配置，标注容易踩的默认值陷阱。原理不展开，需要的指向对应专题笔记。

## Classic Reverse Proxy (With Real Client IP)

```conf
server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_certificate     /etc/nginx/ssl/api.pem;
    ssl_certificate_key /etc/nginx/ssl/api.key;

    location / {
        proxy_pass http://backend;

        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

> [!WARNING]
> `proxy_set_header` 是**数组型指令，子块一旦出现就整体覆盖父块**（不继承未提到的那些）。只在 location 里写一条 `proxy_set_header Host xxx` 会把 http 级配置的其它 header 全部丢掉。原理见 [Configuration](/docs/CS/CN/nginx/config.md?id=array-type-directives-cross-layer-override-not-merge)。

`X-Forwarded-For` 是**追加**语义（`$proxy_add_x_forwarded_for` = 既有值 + 当前 IP），代理链上任何一环可伪造；信任边界内的第一个代理之后应改用 `realip` 模块 + PROXY protocol，见 [stream](/docs/CS/CN/nginx/stream.md?id=proxy-protocol-two-directions-must-be-distinguished)。

## Static-Dynamic Separation + SPA Frontend Routing

```conf
server {
    listen 80;
    root /srv/frontend/dist;

    # 静态资源：hash 文件名，长缓存
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # SPA：所有路由回退到 index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 后端 API
    location /api/ {
        proxy_pass http://backend;
    }
}
```

`try_files` 的最后一个参数是**内部重定向**的兜底；`immutable` 让浏览器连协商请求都不发。

## Cross-Origin (CORS)

```conf
location /api/ {
    # 简单请求
    add_header Access-Control-Allow-Origin  "https://app.example.com" always;
    add_header Access-Control-Allow-Credentials "true" always;

    # 预检请求：拦截 OPTIONS
    if ($request_method = OPTIONS) {
        add_header Access-Control-Allow-Origin  "https://app.example.com" always;
        add_header Access-Control-Allow-Credentials "true" always;
        add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS";
        add_header Access-Control-Allow-Headers "Authorization, Content-Type";
        add_header Access-Control-Max-Age 86400;
        return 204;
    }

    proxy_pass http://backend;
}
```

- `add_header` 同样是覆盖型数组，且**只在 200/201/204/206/301/302/303/304/307/308 返回**——错误响应要带 CORS 头必须加 `always`
- `Allow-Origin` 不要用 `*` 配合 `Credentials: true`（浏览器会拒绝）
- 域名动态时用 `map` 校验白名单再回填，不要直接回显 `Origin`

## WebSocket Reverse Proxy

```conf
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    location /ws/ {
        proxy_pass http://ws_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_read_timeout 300s;    # 默认 60s，空闲 WS 连接会被切
        proxy_send_timeout 300s;
    }
}
```

`proxy_read_timeout` 是最容易踩的：WS 长连接若 60s 无数据会被 nginx 断开（日志里 499/客户端重连风暴）。要么加心跳，要么调大超时。

## SSE（Server-Sent Events）

```conf
location /events/ {
    proxy_pass http://backend;
    proxy_http_version 1.1;

    proxy_buffering off;         # 关键：关缓冲，事件即时下发
    proxy_cache off;
    proxy_read_timeout 24h;      # 长连接

    add_header X-Accel-Buffering no;   # 后端也可发这个头关闭缓冲
}
```

`proxy_buffering off` 是 SSE 的全部关键——默认开启的响应缓冲会把事件攒够一包才发。gzip 也会拖慢 SSE（等缓冲），同理关闭。

## gRPC Reverse Proxy

```conf
server {
    listen 443 ssl;
    http2 on;                                 # 必须：否则 ALPN 不提供 h2

    location / {
        grpc_pass grpc://backend:50051;       # 明文上游；TLS 上游用 grpcs://

        # gRPC 的 idle/重试与 HTTP 不同
        grpc_read_timeout 300s;
        grpc_send_timeout 300s;
    }
}
```

- `grpc_pass` 要求**客户端到 nginx 是 HTTP/2**；`http2 on` 必须显式写，否则 ALPN 候选里没有 h2，客户端会退成 HTTP/1.1
- 上游是明文 h2c（Go gRPC 服务默认）用 `grpc://`，TLS 用 `grpcs://`
- 1.31.4 起，HTTP/2 与 gRPC 回源**总是**带 `:authority` 伪头（不再依赖 Host 头）
- **不需要**为了"大消息"配 `client_max_body_size 0`：HTTP/2 客户端不带 `Content-Length` 时该检查本就被跳过；而 `client_max_body_size` 也拦不住流式请求体。细节见 [gRPC](/docs/CS/CN/nginx/grpc.md)

## Rate Limiting (Combined with Whitelist)

```conf
# 定义：以客户端真实 IP 为 key，10MB 状态区，速率 10 r/s
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
limit_conn_zone $binary_remote_addr zone=perip:10m;

geo $whitelist {
    default 0;
    10.0.0.0/8  1;          # 内网不限
}

map $whitelist $limit_key {
    1       "";              # 白名单 key 为空 = 不限流
    0       $binary_remote_addr;
}

limit_req_zone $limit_key zone=api_g:10m rate=10r/s;

server {
    location /api/ {
        limit_req  zone=api_g burst=20 nodelay;
        limit_conn perip 10;
        limit_req_status 429;          # 默认 503，REST 语义用 429
        limit_conn_status 429;
        proxy_pass http://backend;
    }
}
```

漏桶参数（`burst`/`nodelay`/`delay=`）的语义见 [nginx 的限流一节](/docs/CS/CN/nginx/nginx.md?id=rate-limiting-and-throttling)；原理（excess 计算、LRU）在源码层的拆解见 [Cache 的共享内存一节](/docs/CS/CN/nginx/cache.md)。

## Hotlink Protection (Referer + Signed URL)

```conf
# 简单：Referer 白名单
location ~* \.(jpg|png|mp4)$ {
    valid_referers none blocked server_names *.example.com;
    if ($invalid_referer) {
        return 403;
    }
}

# 严格：签名 URL（防爬虫不防转发，Referer 可伪造）
location /files/ {
    secure_link $arg_sig,$arg_exp;
    secure_link_md5 "$secure_link_expires$uri my-secret";

    if ($secure_link = "") { return 403; }        # 签名错
    if ($secure_link = "0") { return 410; }       # 签名对但过期
}
```

生成侧（对应 `secure_link_md5` 的拼接顺序）：

```bash
EXP=$(($(date +%s) + 3600))
SIG=$(echo -n "${EXP}/files/video.mp4 my-secret" | openssl md5 -binary | base64 | tr '+/' '-_' | tr -d '=')
```

## Cache Reverse Proxy

```conf
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=page:50m
                 max_size=10g inactive=7d use_temp_path=off;

server {
    location / {
        proxy_cache page;
        proxy_cache_key "$scheme$request_method$host$request_uri";

        proxy_cache_valid 200 302 10m;
        proxy_cache_valid 404      1m;
        proxy_cache_use_stale error timeout updating http_500 http_502;
        proxy_cache_background_update on;
        proxy_cache_lock on;

        add_header X-Cache-Status $upstream_cache_status;
        proxy_pass http://backend;
    }
}
```

七种缓存状态与击穿防护（cache lock 三参数）见 [Cache](/docs/CS/CN/nginx/cache.md)。

## Canary and A/B

见 [Practice 的灰度发布一节](/docs/CS/CN/nginx/practice.md?id=canary-release)：`split_clients`（murmur2 可复现分桶）+ `map`（cookie 白名单）组合模板。

## Production server Template (Combines All Above)

```conf
server {
    listen 443 ssl http2;
    server_name app.example.com;

    # TLS 见 tls.md：1.2/1.3、OCSP、会话复用
    ssl_certificate     /etc/nginx/ssl/app.pem;
    ssl_certificate_key /etc/nginx/ssl/app.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    # 安全响应头
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    # 上传限制
    client_max_body_size 20m;
    client_body_timeout  15s;

    # 日志（JSON 结构化见 log.md）
    access_log /var/log/nginx/app.log json_combined;

    location /api/ {
        limit_req zone=api_g burst=20 nodelay;
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 5s;
        proxy_read_timeout 30s;
    }

    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location / {
        try_files $uri /index.html;
    }
}
```

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md) — 各机制的总纲
- [config](/docs/CS/CN/nginx/config.md) — 继承与覆盖规则（配置不生效先看这里）
- [tls](/docs/CS/CN/nginx/tls.md) — TLS 指令与默认值
- [cache](/docs/CS/CN/nginx/cache.md) — 缓存状态机
- [practice](/docs/CS/CN/nginx/practice.md) — 变更与发布流程
- [security](/docs/CS/CN/nginx/security.md)

## References

- <https://nginx.org/en/docs/http/ngx_http_proxy_module.html>
- <https://nginx.org/en/docs/http/ngx_http_secure_link_module.html>
