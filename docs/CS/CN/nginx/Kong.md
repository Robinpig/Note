## Introduction

Kong 是基于 [OpenResty](/docs/CS/CN/nginx/OpenResty.md) 的 API 网关：请求进来先过 nginx，再由 `lua-nginx-module` 挂载的插件链处理（认证、限流、日志、转发）。Kong 不是 nginx 的 fork——它分发 OpenResty（已含 lua-nginx-module），自己的核心（`kong` 库）就是运行在 OpenResty 里的 Lua 应用。

架构关键点（Kong 3.x）：

- **数据面（proxy）与控制面（admin API）分离**：`kong proxy` 处理流量，`kong admin`（默认 8001/8444）做配置管理
- **配置存储**：传统模式用 PostgreSQL（DB-backed），**DB-less 模式**（Kong 1.1 起默认推荐）用声明式 YAML `kong db-less`，配置即文件——与不可变部署/容器/声明式管道更契合
- **混合部署（hybrid）**：Kong 2.0 起 control plane 与 data plane 分节点部署，CP 把配置推给 DP（内存里跑，不再直连数据库）
- **Kong Konnect / Enterprise**：托管控制面 + 免费数据面的商业形态

## 核心概念

| 概念 | 含义 | 对应 nginx 概念 |
| :-- | :-- | :-- |
| Service | 上游服务的抽象（host/port/protocol） | upstream 块 |
| Route | 流量入口匹配（path/host/method） | location（但不嵌套，可跨 Service） |
| Plugin | 挂在 Service/Route/global 上的处理单元 | 模块 + 阶段 handler |
| Consumer | 调用方身份（API key/JWT 主体） | — |
| Upstream/Target | 负载均衡目标与策略（round-robin 等） | upstream + server |

请求流：`Route 匹配 → 插件链（access）→ Service 转发 → 插件链（header_filter/body_filter/log）`。插件链的执行顺序按 Kong 的优先级表，同一插件挂在 global + route 时 route 优先（除非配置了 consumer 级）。

## 插件体系

插件就是一个实现了固定回调的 Lua 模块，回调对应 OpenResty 的 `*_by_lua` 阶段：

```lua
-- kong/plugins/hello/handler.lua（骨架）
local BasePlugin = require "kong.plugins.base_plugin"

local HelloHandler = BasePlugin:extend()
HelloHandler.PRIORITY = 1000        -- 执行优先级，越大越先（access 阶段）
HelloHandler.VERSION = "1.0.0"

function HelloHandler:new()
  HelloHandler.super.new(self, "hello")
end

function HelloHandler:access(conf)
  HelloHandler.super.access(self)
  kong.response.set_header("X-Hello", "world")
end

return HelloHandler
```

常用官方插件（3.x）：`key-auth`/`jwt`/`oauth2`（认证）、`rate-limiting`/`response-ratelimiting`（限流）、`proxy-cache`（缓存）、`cors`、`prometheus`（指标）、`http-log`/`tcp-log`（日志外发）。

自定义插件需要把目录加进 `KONG_PLUGINS` 与 `KONG_LUA_PACKAGE_PATH`，DB-less 模式还需在声明式配置里声明。

## 最小运行示例

Kong 3.x 的 DB-less 起步（替代旧版 PostgreSQL 三容器栈）：

```yml
# docker-compose.yml
services:
  kong:
    image: kong:3.9
    environment:
      KONG_DATABASE: "off"                    # DB-less 模式
      KONG_DECLARATIVE_CONFIG: /kong/kong.yml
      KONG_PROXY_LISTEN: "0.0.0.0:8000, 0.0.0.0:8443 ssl"
      KONG_ADMIN_LISTEN: "127.0.0.1:8001"
      KONG_PROXY_ACCESS_LOG: /dev/stdout
      KONG_PROXY_ERROR_LOG: /dev/stderr
    volumes:
      - ./kong.yml:/kong/kong.yml:ro
    ports:
      - "8000:8000"
      - "8443:8443"
```

```yaml
# kong.yml（声明式配置）
_format_version: "3.0"
services:
  - name: example
    url: http://httpbin.org
    routes:
      - name: example-route
        paths: ["/api"]
    plugins:
      - name: rate-limiting
        config:
          minute: 100
          policy: local
```

## 与 nginx 原生能力的取舍

| 需求 | 用 Kong | 直接 nginx |
| :-- | :-- | :-- |
| 静态反代、静态资源 | 杀鸡用牛刀 | ✅ |
| 认证体系（多协议：key/JWT/OAuth2 可插拔） | ✅ | 需自己写 auth_request + 后端 |
| 插件级限流、按 consumer 限流 | ✅ | limit_req 按 key，无 consumer 概念 |
| 动态路由/服务发现 | ✅（admin API 热更） | resolver + zone（受限） |
| 极致性能、稳定压倒一切 | 插件链有 Lua 开销 | ✅ |
| 复用现有 nginx 运维经验 | 概念要重学（Service/Route） | ✅ |

本质：Kong 用一层 Lua 插件链换来了「API 生命周期管理」的抽象，代价是每请求多一跳 Lua 执行。流量入口纯静态、无认证诉求的场景，nginx 原生配置更直接。

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md) — 底层进程与事件模型
- [OpenResty](/docs/CS/CN/nginx/OpenResty.md) — Kong 插件运行的 Lua 平台
- [Upstream](/docs/CS/CN/nginx/upstream.md) — nginx 原生负载均衡的对照
- [Container](/docs/CS/Container/Container.md) — 部署形态（Docker/K8s）

## References

- <https://docs.konghq.com/gateway/latest/>
- <https://github.com/Kong/kong>
