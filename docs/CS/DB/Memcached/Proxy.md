## Introduction

1.6.0 起 Memcached 引入**内建 Lua Proxy**——不再只是一个纯缓存节点，还可以充当一个**可配置的代理层**。它的核心思路是：每个 worker 线程上跑一个独立的 Lua VM，客户端命令进来后，你可以用 Lua 脚本决定这个命令怎么处理——是直接读本地缓存，还是转发到某个后端 Memcached 集群，或者做读写穿透到另一类数据源。

这使得 Memcached 可以同时做三件事：**本地缓存 + 代理路由 + 轻量聚合**，把之前需要单独部署 Twemcache / Twemproxy 的场景压进一个进程。

### Deployment Models

Proxy 有两种典型用法：

1. **Sidecar / Single-Instance Proxy**：应用连本机 Memcached（配置了 proxy），proxy 在 Lua 里根据 key 前缀或命名空间把请求路由到不同的后端缓存集群。这让应用不需要改客户端就实现了缓存分片逻辑。
2. **Cluster Frontdoor**：Memcached proxy 实例作为整个缓存集群的统一入口，内部把请求分发给多台后端 Memcached 服务器。后端拓扑对应用透明。

## Architecture

### Lua VM per Worker

每个 worker 线程有自己独立的 Lua VM：

- Lua VM 之间**不共享数据**——每个 worker 维护自己的路由和 pool 配置副本。
- 配置加载时由 Configuration Thread 负责把 `mcp_config_pools` 返回的 pool 描述**跨 VM 拷贝**到每个 worker。
- 请求处理时 Lua 脚本**只在 worker 线程内执行**，不会跨线程调度。

### Request Flow

```
Client 命令
   ↓
Worker 线程收到请求（本地缓存 or 转发）
   ↓
执行 Lua request hook（如果配置了）
   ↓
路由到本地缓存 or 某个 backend pool
   ↓
后端 Memcached 处理请求
   ↓
响应回 client
```

### Backend Connection Modes

后端连接有两种模式（`pool iothread = true|false`）：

| 模式 | 行为 |
| :-- | :-- |
| `iothread = false` | 每个 worker 线程与每个 backend 维护独立 TCP 连接，worker 直接发请求 |
| `iothread = true` | 所有 worker 共享一个后台 IO thread，IO thread 批量把请求合并到同一连接发出，socket 数量显著减少 |

默认 `iothread = false`，性能更好但连接数多。大规模集群推荐 `iothread = true`。

### Request Batching

Proxy 对同一客户端的多个请求做**客户端批处理**：一次 `read()` 读出 socket buffer 里所有可用请求，逐个启动。如果多个请求被路由到不同后端，它们被并行发出后**等待所有后端都返回**才统一响应客户端。这意味着「首字节延迟 = 最慢后端响应时间」，适合后端速度相近的场景。

对**后端连接**则用**双向流式**：多个客户端发往同一后端的请求被合并成一个 `write()`，响应流式回传，不等待 batch 完成。

## Lua Configuration API

### `mcp_config_pools()`

在配置文件中定义，返回一个 pool 列表。每个 pool 可以关联一组 backend 服务器：

```lua
function mcp_config_pools()
    local backends = { "cache1:11211", "cache2:11211", "cache3:11211" }
    local pool = mcp.pool({ backends = backends })
    return { mypool = pool }
end
```

### `mcp_config_routes(pools)`

每个 worker VM 加载时执行一次，定义路由规则：

```lua
function mcp_config_routes(pools)
    mcp.route("get foo/*", function(req)
        return mcp.proxy(pools.mypool, req)
    end)
    mcp.route("set bar/*", function(req)
        -- 读写穿透到另一数据源
        local v = some_fallback_lookup(req.key)
        if v then
            req:set_value(v)
            return mcp.hit(req)
        end
        return mcp.proxy(pools.mypool, req)
    end)
end
```

### Key Hooks

`mcp.route` 支持通配符和模式匹配，Lua 回调可以：

| 返回值 | 含义 |
| :-- | :-- |
| `mcp.hit(req)` | 本地缓存命中（set 后直接返回，不转发） |
| `mcp.miss(req)` | 本地 MISS |
| `mcp.proxy(pool, req)` | 转发到后端 pool |
| `req:set_value(data)` | 在 Lua 里设置返回值 |
| `req:cache_key(new_key)` | 重写 key（比如加前缀/去前缀） |

### Proxy Commands

Proxy 还暴露了管理命令：

| 命令 | 含义 |
| :-- | :-- |
| `mcp.pools` | 列出当前配置的所有 pool |
| `mcp.backends <pool>` | 列出某 pool 的后端服务器及状态 |
| `mcp.limit <pool> <limit>` | 动态调整某 pool 的并发请求上限 |
| `mcp.reload` | 重新加载 Lua 配置（不会丢失已在处理的请求） |

## When to Use vs. When Not

### 适合

- 应用要做缓存分片但不想引入 Twemcache 等额外组件。
- 需要在缓存层做简单的读写穿透逻辑。
- 需要给不同应用或命名空间隔离缓存。

### 不适合

- 需要复杂聚合（JOIN、跨 key 排序）——Lua 里做这些很慢。
- 需要强一致的分布式事务——Memcached proxy 不提供。
- 缓存性能极度敏感——Lua hook 会引入额外微秒级延迟。

## Links

- [Memcached](/docs/CS/DB/Memcached.md)
- [Protocol](/docs/CS/DB/Memcached/Protocol.md)
- [Distributed](/docs/CS/DB/Memcached/Distributed.md)

## References

1. [Memcached Documentation — Internal Architecture](http://docs.memcached.org/features/proxy/arch/) — 官方内建 proxy 架构文档
2. [Memcached GitHub — proxy/](https://github.com/memcached/memcached/tree/master/proxy) — proxy 源码
