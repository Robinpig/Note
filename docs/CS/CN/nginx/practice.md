## Introduction

nginx 笔记的其它几篇讲的是「配置怎么写、代码怎么跑」，这一篇讲「线上怎么改」：不中断服务的配置变更、摘流量、灰度发布、容器与 Kubernetes 部署。

有一个绕不开的时代背景要先说：**Kubernetes 社区的 Ingress NGINX 控制器已于 2026 年 3 月正式退役**（2025-11-11 官宣，Best-effort 维护至 2026-03），如果你在 K8s 里用着它，迁移已经从「可选项」变成「必答题」。本文最后一节展开。

## Graceful Shutdown and Zero-Downtime Change

### Essence of reload (Review)

`nginx -s reload` → master 收 SIGHUP → reread 配置 → `ngx_init_cycle()` 里**新 cycle 直接继承旧 cycle 的监听 fd** → spawn 新 worker、通知旧 worker 优雅退出。全程监听不断，存量连接由旧 worker 处理完。细节见 [nginx 的 Reload 与热升级](/docs/CS/CN/nginx/nginx.md?id=reload-configuration-replacement-without-service-interruption)。

### QUIT and worker_shutdown_timeout

旧 worker 的退出流程：关监听 socket → 处理完存量连接（`ngx_quit` 状态）→ 退出。问题在于存量连接可能永远不结束（长轮询、WebSocket、上传中），于是有：

```conf
worker_shutdown_timeout 30s;
```

- **1.11.11 引入**（2017-03），无默认值（不设则无限等）
- 到点后 nginx **强制关闭剩余连接**（走 `ngx_close_connection`），保证 reload/quit 有确定的完成时间

`TERM`（立刻退出）与 `QUIT`（优雅退出）的区别见 [信号表](/docs/CS/CN/nginx/nginx.md?id=signal-table)。

### Drain Traffic: down and drain

滚动发布时先把节点摘出负载池，让存量会话自然结束：

```conf
upstream app {
    server 10.0.0.11:8080 down;      # 立即不再接新请求
    server 10.0.0.12:8080 drain;     # 不接新会话，存量会话继续
}
```

- `down`：源码里置 `us->down = NGX_HTTP_UPSTREAM_FAILED`，选择 peer 时直接跳过
- `drain`：置 `NGX_HTTP_UPSTREAM_DRAINING`，**依赖 sticky 会话**（源码在 `#if (NGX_HTTP_UPSTREAM_STICKY)` 块里）——带会话的请求还能路由到它，新会话不再进入。1.29.6 起进开源版
- 只想临时摘除时，`down` 是配置级操作，需要 reload；运行时摘除要用 API（Plus）或 upstream zone + 动态模块

## Health Check: Open Source Version Only Passive

**开源 nginx 没有 `health_check` 指令**（http 和 stream 都没有，源码里的 `health_check:1` 位只是给 Plus/第三方预留的）。开源版的手段是被动健康检查：

```conf
upstream app {
    server 10.0.0.11:8080 max_fails=3 fail_timeout=30s;
}
```

被动检查的语义与局限：

- `max_fails=1`（默认）相当激进——**一次 connect 失败就把节点踢出 10 秒**（`fail_timeout` 默认 10s）
- 判「失败」的是**连接层事件**：connect 超时、connect 拒绝等。**上游返回 500 不算失败**（除非 `proxy_next_upstream` 里写了 `http_500`，那影响的是本次重试，不累计 max_fails）
- 被动意味着：第一个撞上坏节点的用户要当一次「探针」

主动健康检查的替代方案：

| 方案 | 说明 |
| :-- | :-- |
| NGINX Plus `health_check` | 商业版，定时主动探测 |
| tengine `ngx_http_upstream_check_module` | 阿里系补丁，需重编译 |
| 外部探针（Keepalived/consul/负载均衡器） | 探活结果通过改配置或 DNS 生效 |
| upstream zone + 动态 upstream | 配合服务发现（consul-template 等）热更新 |

## Canary Release

### split_clients: Roll Out by Ratio

```conf
split_clients "${remote_addr}${http_user_agent}" $variant {
    10%     v2;
    *       v1;
}

server {
    ...
    location / {
        proxy_pass http://backend_$variant;
    }
}
```

实现要点（`ngx_http_split_clients_module.c:91`）：

- 哈希算法是 **`ngx_murmur_hash2`**（不是 crc32），对 key 求值后落在 32 位空间
- 每个 percent 区间是哈希值域的一段，**同一 key 永远落在同一桶**（可复现，sticky 灰度）
- `*` 表示剩余全部；`percent=0` 的桶会兜底接住剩余（源码 `hash < percent || percent == 0`）
- key 里通常混入 `$remote_addr`——按 IP 灰度，同一用户视角一致

### Whitelist + Combination by Ratio

生产灰度的标准形态：内部账号先全量，外部按比例：

```conf
geo $internal {
    default         0;
    10.0.0.0/8      1;
}

map "$internal:${http_cookie}" $upstream_v {
    ~^1:            backend_v2;         # 内网直接进 v2
    ~:gray=1        backend_v2;         # 命中灰度 cookie
    default         "";                 # 交给 split_clients
}

split_clients "${remote_addr}" $ratio_v {
    5%      backend_v2;
    *       backend_v1;
}

map $upstream_v $backend {
    ""      $ratio_v;                   # 白名单没中 → 按比例
    default $upstream_v;
}
```

变体间要共享会话时，配合 upstream 的 `sticky`（1.29.6 开源）或 `hash $cookie_sid consistent`。

## Containerized Deployment

### Official Image

`nginx:alpine` / `nginx:1.31.6` 的关键约定：

- 入口 `nginx -g daemon off;`（前台运行，配合容器 PID 1 信号模型）
- 主配置 `/etc/nginx/nginx.conf`，`conf.d/*.conf` 被 include
- 官方镜像的 entrypoint 支持 **模板替换**：把配置放到 `/etc/nginx/templates/*.template`，启动时对 `$(envsubst)` 变量做替换输出到 `conf.d/`，只替换 `NGINX_ENVSUBST_FILTER` 匹配 / `NGINX_ENVSUBST_<VAR>_SUFFIX` 指定的变量
- `nginx -s reload` 在容器里**只影响同容器的进程**；配置变更的标准做法是重建容器（不可变基础设施），或 sidecar/agent 推配置
- 收到 SIGTERM 时 nginx 默认走「快退出」（等价 TERM 信号）——容器滚动更新要快速排空连接，可以监听 `QUIT`：`nginx -s quit`

### nginx-unprivileged

非 root 变体：监听端口改为 8080/8443，写路径改 `/tmp`，PID 文件与缓存目录都在用户可写位置。K8s 里 `runAsNonRoot: true` 的场景用它，代价是权限受限（不能绑 80，需要 Service/端口映射）。

## Kubernetes: Ingress NGINX Retired

### Conclusion First

- **`ingress-nginx`（kubernetes/ingress-nginx）已于 2026 年 3 月退役**：2025-11-11 由 SIG Network 与安全响应委员会官宣，2026-01-29 Steering Committee 再次强调；此后**不再有任何版本、bugfix 或安全补丁**，仓库转只读
- 背景数据：Datadog 调研约 **50% 的云原生环境**在用 ingress-nginx，但项目长期只有 1~2 人在业余时间维护；「通过 snippets 注解注入任意 nginx 配置」这类灵活性成为无法收敛的安全债
- 曾计划的后继者 **InGate 未达成熟，一并退役**
- 官方迁移建议：**Gateway API**（Ingress 的现代替代）或第三方 Ingress 控制器

### Avoid Mixing the Two nginx ingress Instances

| | ingress-nginx | NGINX Ingress Controller |
| :-- | :-- | :-- |
| 仓库 | `kubernetes/ingress-nginx` | `nginxinc/kubernetes-ingress` |
| 维护方 | Kubernetes 社区 | F5/nginx 官方 |
| 现状 | **2026-03 退役** | 活跃；同时提供 Ingress 与 **NGINX Gateway Fabric**（Gateway API 实现） |
| 配置方式 | Ingress 资源 + annotations | ConfigMap + 自定义 CRD（VirtualServer 等） |

自查是否还在用退役项目：

```bash
kubectl get pods --all-namespaces -l app.kubernetes.io/name=ingress-nginx
```

### Migration Path

1. **Gateway API**（`gateway.networking.k8s.io`）：HTTPRoute/GRPCRoute，角色分离（GatewayClass/Gateway 由平台管、Route 由业务管），是官方推荐方向
2. **NGINX Gateway Fabric**（F5）：Gateway API 的 nginx 实现，迁移成本最低
3. **Traefik Proxy 3.7**（2026-05 GA）：内置 **ingress-nginx provider**，直接读现有 Ingress 与 annotations 并翻译成 Traefik 路由——支持 **85 条 ingress-nginx 注解（覆盖 90%+）**，连 `configuration-snippet` / `server-snippet` / `auth-snippet` 都做了**白名单解析**（把片段解析成结构化配置，而不是原样模板注入，避开了当年 ingress-nginx 的安全债），并支持接入 ModSecurity 保留 WAF 行为。就「注释兼容」而言，它是目前最接近 drop-in 的选项
4. 其它 Ingress 控制器：HAProxy Ingress、Envoy Gateway、Apache APISIX Ingress 2.2 等（K8s 文档有清单）

要点：**除 Traefik 的注解兼容路径外，没有真正的 drop-in 替代**——snippets 注解、rewrite annotations 一般要按新语法重写，官方明确提示迁移需要规划与工程时间。选型与各家现状对照见 [Compare 的网关一节](/docs/CS/CN/nginx/compare.md?id=gateway-and-ingress-side-traefik--apisix--kong--higress)。

## systemd Deployment Key Points

```ini
[Service]
Type=notify
ExecStartPre=/usr/sbin/nginx -t -c /etc/nginx/nginx.conf
ExecStart=/usr/sbin/nginx -c /etc/nginx/nginx.conf
ExecReload=/usr/sbin/nginx -s reload
KillSignal=SIGQUIT          # systemd stop 走优雅退出
TimeoutStopSec=30s          # 与 worker_shutdown_timeout 对齐
LimitNOFILE=65535
```

- `KillSignal=SIGQUIT` 让 `systemctl stop` 变成优雅下线；`TimeoutStopSec` 到点 systemd 发 SIGKILL
- `LimitNOFILE` 要覆盖 `worker_connections × 2` 的需求（见 [Event 的调优清单](/docs/CS/CN/nginx/event.md?id=tuning-checklist)）
- 日志：nginx 自己写文件（见 [Log](/docs/CS/CN/nginx/log.md)），不要套 `StandardOutput=`；要进 journald 就把 `error_log stderr` + `access_log /dev/stdout`

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md) — reload 与热升级的源码细节
- [Upstream](/docs/CS/CN/nginx/upstream.md) — 负载均衡与重试
- [Troubleshooting](/docs/CS/CN/nginx/troubleshooting.md) — 变更出问题后的排障
- [TLS](/docs/CS/CN/nginx/tls.md) — 证书轮换的会话影响
- [Log](/docs/CS/CN/nginx/log.md) — 日志落盘与滚动
- [security](/docs/CS/CN/nginx/security.md)

## References

- <https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/>
- <https://kubernetes.io/blog/2026/01/29/ingress-nginx-statement/>
- <https://gateway-api.sigs.k8s.io/>
- <https://docs.nginx.com/nginx-gateway-fabric/>
