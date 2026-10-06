## Introduction

OpenResty 把 LuaJIT 嵌进 nginx（核心是 `lua-nginx-module`），让 nginx 从「配置驱动的静态服务器」变成「Lua 编程的应用平台」。它的性能来源是一个关键设计：**Lua API 全部基于事件回调实现非阻塞**——`ngx.location.capture`、cosocket 这些看起来是同步阻塞的调用，底层全是 nginx 的 epoll 事件，一个 worker 可以同时挂起成千上万个「暂停中的 Lua 协程」。

版本对齐关系（2026-10）：最新发布 **1.31.1.1**（基于 nginx 1.31.1 mainline）与 **1.29.2.5**（基于 stable 1.29.2，含 CVE 回移植）。OpenResty 不是 nginx 的 fork——对核心的补丁大多已回流官方。

本文覆盖：执行阶段挂载、cosocket、共享字典、FFI 与性能陷阱。nginx 本体机制见 [nginx](/docs/CS/CN/nginx/nginx.md)。

## 执行阶段：Lua 怎么挂进 11 个阶段

`lua-nginx-module` 把 nginx 的阶段机制（见 [HTTP](/docs/CS/CN/nginx/HTTP.md)）映射成一组 `*_by_lua` 指令，每个都是「在该阶段执行一段 Lua」：

| 指令 | 挂载阶段 | 典型用途 |
| :-- | :-- | :-- |
| `init_by_lua` | master 启动 | 预加载模块（只执行一次，fork 前共享） |
| `init_worker_by_lua` | 每个 worker 启动 | 定时器、后台任务 |
| `ssl_client_hello_by_lua` | ClientHello 阶段 | 动态控制 TLS 握手（选证书/拒绝） |
| `set_by_lua` | rewrite | 计算一个变量 |
| `rewrite_by_lua` | REWRITE | 改写 URI/参数、访问控制 |
| `access_by_lua` | ACCESS | 认证、限流、灰度判断 |
| `content_by_lua` | CONTENT | 生成响应（替代 proxy_pass 等） |
| `balancer_by_lua` | 上游选 peer | 自定义负载均衡（与 upstream zone 配合） |
| `header_filter_by_lua` | header 过滤链 | 改响应头 |
| `body_filter_by_lua` | body 过滤链 | 改响应体（可能被多次调用） |
| `log_by_lua` | LOG | 采集指标、自定义日志 |
| `timer.at` | （任意时刻） | 非阻塞定时任务，本质是 epoll 定时器 |

理解挂载阶段就能回答大多数「为什么我的 Lua 不执行/执行了两次」：`body_filter` 会被 chunked 分块反复调用；`set_by_lua` 是惰性求值（变量被读时才跑）。

每个请求内的 Lua 跑在 **LuaJIT 协程**里。`ngx.sleep`、cosocket 的读写都会 yield 挂起整个协程并释放 worker——这就是「同步写法、异步执行」的机制。

## cosocket：非阻塞 socket 的 Lua 化

cosocket（coroutine + socket）把 nginx 的事件 socket 包装成 Lua 对象：

```lua
local redis = require "resty.redis"
local red = redis:new()
red:set_timeout(1000)                       -- ms
local ok, err = red:connect("127.0.0.1", 6379)
if not ok then
    ngx.log(ngx.ERR, "connect failed: ", err)
    return ngx.exit(502)
end
red:set("k", "v")
red:set_keepalive(10000, 100)               -- 放回连接池
```

关键语义：

- **API 形式同步，执行非阻塞**：`connect/send/receive` 内部 yield，事件循环继续处理其它请求
- **连接池**：`set_keepalive()` 不是关闭，是放回 per-worker 池；**池不跨 worker**（每 worker 独立），和 nginx upstream 的 `keepalive` 一样
- **`set_keepalive` 的前提**：响应读干净才能复用，读一半就丢弃的连接不能进池
- UDP、Unix domain socket、TLS 都支持
- cosocket **不能**在 `init_by_lua` 里用（那时还没事件循环），只能在请求阶段和 `ngx.timer` 里用

`ngx.location.capture` 是另一种「子请求」形式（走 nginx 内部 HTTP 栈，能复用 proxy_pass/缓存），与 cosocket 的取舍：需要 nginx 特性（缓存、location 匹配）用 capture，需要裸协议（Redis/Memcached）用 cosocket。

## 共享内存：lua_shared_dict 与 worker 间状态

```conf
http {
    lua_shared_dict my_cache 10m;
    lua_shared_dict locks 1m;
}
```

```lua
local cache = ngx.shared.my_cache
local ok, err = cache:add("key", "val", 60)        -- 60s 过期，不存在才设
cache:set("key", "val", 60)
local v, err = cache:get("key")
cache:delete("key")
```

- 底层就是 nginx 共享内存 + slab 分配器（见 [Memory](/docs/CS/CN/nginx/memory.md)），带过期与 LRU 淘汰
- **跨 worker 一致**；但每次操作都有锁开销，高频读写用它反而慢——热数据先 worker 本地缓存（`lua-resty-lrucache`），`shared_dict` 做跨 worker 的低频同步层
- `add`/`incr` 是原子的，适合做计数器、分布式锁（配合 `resty.lock` 防缓存击穿）

## FFI 与性能陷阱

LuaJIT 的 FFI 可以直接调 C 库，OpenResty 生态大量用它绕过 table/字符串的转换开销。但性能陷阱明确：

1. **不要在热路径 `ngx.re.*`（PCRE）**：能用 Lua 自带 `string.find`（LuaJIT 可字节码化）就别用正则
2. **大字符串拼接**：用 LuaJIT 的 `string.buffer`（1.21.4.1 起内置），别用 `..` 连接器堆大字符串
3. **阻塞调用是禁区**：`os.execute`、`io.*`、sleep 库——都会卡住整个 worker。唯一的「阻塞」出口是 `ngx.run_worker_thread`（1.21.4.1 起）或外部服务
4. **Lua GC 抖动**：长连接高 QPS 下 GC 停顿明显，常规手段是调 GC 步长、控制每请求的 table 产生量
5. **热加载**：`reload` 后 Lua 虚拟机整个重建，`init_by_lua` 重新执行；`lua_code_cache off` 只用于开发，生产必开

`resty` 命令行（`resty -e 'print("hi")'`）可以直接跑脚本，方便测试 API 语义。

## 生态与关联

| 层 | 项目 | 说明 |
| :-- | :-- | :-- |
| 平台 | OpenResty | nginx + LuaJIT + lua-nginx-module + resty 库 |
| 网关 | [Kong](/docs/CS/CN/nginx/Kong.md) | 基于 OpenResty 的 API 网关，插件即 Lua 模块 |
| WAF | Coraza / lua-resty-waf | OpenResty 生态的 WAF 实现 |
| 云原生网关 | APISIX | 基于 OpenResty，etcd 存配置，控制面独立 |

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md) — 事件模型与阶段机制
- [HTTP](/docs/CS/CN/nginx/HTTP.md) — `*_by_lua` 挂载的阶段语义
- [Memory](/docs/CS/CN/nginx/memory.md) — `lua_shared_dict` 的底层
- [Kong](/docs/CS/CN/nginx/Kong.md) — OpenResty 之上的网关

## References

- <https://openresty.org/>
- <https://github.com/openresty/lua-nginx-module>
- <https://github.com/openresty/lua-resty-redis>
