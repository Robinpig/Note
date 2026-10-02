## Introduction

HAProxy（High Availability Proxy）是一款高性能的 **TCP/HTTP 负载均衡器与反向代理**，以事件驱动、单进程、非阻塞的架构著称，能在单核上处理数十万级并发连接，广泛用于 L4/L7 流量分发与高可用接入层。与 Nginx 自带 Web 服务器能力不同，HAProxy 更纯粹地聚焦「代理」本身。

## 架构模型

HAProxy 采用 **event-driven + single process** 模型：一个进程（可绑定多核 worker）通过 epoll/kqueue 监听所有 socket，避免线程上下文切换与锁竞争。配合 `nbproc` / `nbthread`（新版统一用 `nbthread`）做多核扩展。

配置由若干 **proxy 段** 组成，核心三类：

- `defaults`：公共默认值，被 frontend/backend 继承。
- `frontend`：面向客户端的监听端，绑定 `bind ip:port` 并声明 `mode tcp|http`，通过 `acl` + `use_backend` 做路由。
- `backend`：后端服务器池，`server` 指令列出真实节点与权重；`balance` 指定调度算法。
- `listen`：frontend + backend 合一的简写段（适合纯 TCP 转发）。

```haproxy
frontend http_in
    bind *:80
    mode http
    acl is_api path_beg /api
    use_backend api_srv if is_api
    default_backend web_srv

backend web_srv
    mode http
    balance roundrobin
    server s1 10.0.0.1:8080 check
    server s2 10.0.0.2:8080 check
```

## 调度算法

`balance` 可选（部分需 `option httpchk` 配合）：

- `roundrobin`：加权轮询，默认且最常用，支持运行时调整权重。
- `leastconn`：最少连接优先，适合长连接（如 MySQL、WebSocket）。
- `source`：按客户端源 IP 哈希，近似会话保持（节点变动会重映射）。
- `uri` / `url_param`：按请求 URI / 参数哈希，用于缓存亲和。
- `first`：依次填满权重最高的节点，适合省电场景。

## 健康检查与会话保持

- **健康探测**：`server ... check` 开启 TCP 层探活；`option httpchk GET /health` 升级为 HTTP 层探测，`inter` / `rise` / `fall` 控制频率与阈值。
- **会话保持**：`cookie` 注入（HTTP 模式）或 `stick-table`（跨进程共享，基于源 IP/端口做表项跟踪），比 `source` 算法更精准且对扩缩容更友好。

## 与 LVS / Nginx 的取舍

- **LVS**：纯 L4（IPVS），转发性能极致、无应用层解析，但无 URL 路由/重写能力。
- **Nginx**：L7 反向代理 + 完整 Web 服务器，配置生态成熟；HAProxy 在纯粹代理场景的连接数、健康检查粒度、stick-table 上更专业。
- 实践中常组合：LVS 做 L4 入口 → HAProxy/Nginx 做 L7，或 HAProxy 前置 Nginx 做 TLS 终结与负载均衡。

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)
- [Load Balance](/docs/CS/CN/Load%20Balance.md)
- [TCP](/docs/CS/CN/TCP/TCP.md)
- [TLS](/docs/CS/CN/TLS.md)
- [Computer Network](/docs/CS/CN/CN.md)

## References

- [HAProxy Documentation](https://docs.haproxy.org/)
- [The HAProxy Configuration Manual](https://docs.haproxy.org/2.8/configuration.html)
