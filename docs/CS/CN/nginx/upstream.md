## Introduction

当 `location` 里写了 `proxy_pass`，nginx 就不再自己产生响应，而是把自己变成一个**客户端**去访问上游服务。这一整套机制叫 upstream，它是 nginx 作为反向代理/网关的核心：选哪台机器、连不上怎么办、上游慢怎么办、响应怎么传回客户端、连接能不能复用、响应能不能缓存。

本文按"由浅入深"组织：先用一段配置建立直觉，再拆数据结构与回调链，然后逐个讲算法与重试，最后是长连接、超时与调优。整体脉络见 [nginx](/docs/CS/CN/nginx/nginx.md)，缓存部分见 [Cache](/docs/CS/CN/nginx/cache.md)。

```nginx
upstream backend {
    server 10.0.0.1:8080 weight=3 max_fails=3 fail_timeout=10s;
    server 10.0.0.2:8080          max_fails=3 fail_timeout=10s;
    server 10.0.0.3:8080 backup;

    keepalive 64;
    keepalive_requests 1000;
    keepalive_timeout 60s;
}

server {
    location /api/ {
        proxy_pass http://backend;

        proxy_http_version 1.1;              # 1.29.7 起已是默认
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        proxy_connect_timeout 5s;            # 建连（含 TLS）
        proxy_send_timeout   30s;            # 两次写之间的间隔
        proxy_read_timeout   60s;            # 两次读之间的间隔

        proxy_next_upstream error timeout http_502 http_503;
        proxy_next_upstream_tries 3;
        proxy_next_upstream_timeout 10s;
    }
}
```

## 数据结构

### `ngx_http_upstream_t`：一次上游交互的全部状态

它挂在 `r->upstream` 上，既保存配置（超时、缓冲、重试策略），也保存运行期状态（peer、缓存、缓冲区、pipe）。关键的一组回调由具体协议模块（proxy / fastcgi / uwsgi / scgi / grpc）填充：

```c
// http/ngx_http_upstream.h（节选）
struct ngx_http_upstream_s {
    ngx_int_t  (*create_key)(ngx_http_request_t *r);            /* 计算 cache key */
    ngx_int_t  (*create_request)(ngx_http_request_t *r);        /* 构造发给上游的请求 */
    ngx_int_t  (*reinit_request)(ngx_http_request_t *r);        /* 重试前重置状态 */
    ngx_int_t  (*process_header)(ngx_http_request_t *r);        /* 解析响应头 */
    void       (*abort_request)(ngx_http_request_t *r);
    void       (*finalize_request)(ngx_http_request_t *r, ngx_int_t rc);
    ngx_int_t  (*rewrite_redirect)(ngx_http_request_t *r, ...); /* proxy_redirect */
    ngx_int_t  (*rewrite_cookie)(...);                          /* proxy_cookie_... */

    ngx_int_t  (*input_filter_init)(void *data);
    ngx_int_t  (*input_filter)(void *data, ssize_t bytes);      /* 协议解包 */

    ngx_peer_connection_t   peer;      /* 建连与选 peer */
    ngx_http_upstream_conf_t *conf;    /* 超时、缓冲、重试等配置 */
    ...
};
```

以 proxy 模块为例的赋值：

```c
// http/modules/ngx_http_proxy_module.c
u->create_request   = ngx_http_proxy_create_request;
u->reinit_request   = ngx_http_proxy_reinit_request;
u->process_header   = ngx_http_proxy_process_status_line;
u->finalize_request = ngx_http_proxy_finalize_request;
```

> `abort_request` 虽被多个模块赋值，但框架在 1.31.6 里**并没有任何调用点**——它是历史遗留钩子，别指望它会在请求中止时被回调。

### `ngx_peer_connection_t`：选 peer 与建连

```c
typedef struct {
    ngx_event_get_peer_pt    get;        /* 选一个 peer */
    ngx_event_free_peer_pt   free;       /* 归还（并报告成功/失败） */
    void                    *data;       /* 算法自己的状态（如 rr 的 tried 位图） */

    struct sockaddr  *sockaddr;
    socklen_t         socklen;
    ngx_str_t        *name;

    ngx_uint_t        tries;            /* 还能重试几次 */
    ngx_msec_t        start_time;       /* 第一次尝试的时间，用于 next_upstream_timeout */
    ...
} ngx_peer_connection_t;
```

这个结构是**可嵌套的**：upstream keepalive 模块会把 `get`/`free` 换成自己的版本，并把原来的函数指针保存在 `data` 里——典型的装饰器模式，见后文长连接池。

### 配置期与运行期的两级初始化

| 钩子 | 时机 | 作用 |
| :-- | :-- | :-- |
| `uscf->peer.init_upstream(cf, us)` | 解析 `upstream` 块时，**一次** | 构建 peers 数组、一致性哈希环等静态结构 |
| `us->peer.init(r, us)` | **每个请求**开始时 | 初始化每请求状态（如 `tried` 位图）、设置 `get`/`free` |

所以"负载均衡算法"的入口其实有两个：upstream 块里写了 `least_conn` 之类指令时，`init_upstream` 被替换成对应模块的；不写就是默认的 `ngx_http_upstream_init_round_robin`。

## 负载均衡算法

### 默认：平滑加权轮询（SWRR）

很多人以为 nginx 的轮询是 `i % n`，其实不是——它是**平滑加权轮询**，能让不同权重的节点均匀 interleaving，而不是"先连打权重高的那个"。

配置期做两件事（拆主组与 backup 组）：

```c
// http/ngx_http_upstream_round_robin.c
for (i = 0; i < us->servers->nelts; i++) {
    if (server[i].backup) continue;              /* backup 单独处理 */

    n += server[i].naddrs;                       /* 域名解析出几个地址就是几个 peer */
    w += server[i].naddrs * server[i].weight;
    if (!server[i].down) t += server[i].naddrs;
}

peers->single  = (n == 1);
peers->number  = n;
peers->weighted = (w != n);                      /* 有非 1 权重才走加权路径 */
peers->total_weight = w;
peers->tries   = t;                              /* 非 down 的 peer 数 */
```

核心选择逻辑：

```c
now = ngx_time();
for (peer = rrp->peers->peer, i = 0; peer; peer = peer->next, i++) {
    if (rrp->tried[n] & m) continue;                       /* 本次请求已试过 */
    if (peer->down) continue;
    if (peer->max_fails && peer->fails >= peer->max_fails
        && now - peer->checked <= peer->fail_timeout)      /* 处于"故障期" */
        continue;
    if (peer->max_conns && peer->conns >= peer->max_conns) continue;

    peer->current_weight += peer->effective_weight;        /* ① 累加 */
    total += peer->effective_weight;
    if (peer->effective_weight < peer->weight) {           /* ② 缓慢恢复 */
        peer->effective_weight++;
    }
    if (best == NULL || peer->current_weight > best->current_weight) {
        best = peer; p = i;                                /* ③ 取最大 */
    }
}
best->current_weight -= total;                             /* ④ 减去本轮 total */
```

要点：

- `total` 是**本轮参与竞选的 peer 的 effective_weight 之和**，不是配置里的 `total_weight`；
- 一个 `server` 若解析出 N 个地址，会展开成 N 个 peer，每个都继承同样的 weight；
- 失败降权在 `free` 回调里：`effective_weight -= weight / max_fails`（整数除法，`max_fails` 越大惩罚越轻），并缓慢 `++` 恢复；
- 主组全部不可用时，才切到 backup 组，并清空 `tried` 位图：

  ```c
  failed:
      if (peers->next) {                 /* 有 backup 组 */
          rrp->peers = peers->next;      /* 永久切换 */
          for (i = 0; i < n; i++) rrp->tried[i] = 0;
          rc = ngx_http_upstream_get_round_robin_peer(pc, rrp);
          if (rc != NGX_BUSY) return rc;
      }
      return NGX_BUSY;
  ```

### ip_hash

按客户端 IP 哈希，做**会话保持**（同一 IP 总落到同一台）：

```c
switch (r->connection->sockaddr->sa_family) {
case AF_INET:
    iphp->addr = (u_char *) &sin->sin_addr.s_addr;
    iphp->addrlen = 3;                 /* ★ IPv4 只用前 3 字节，即按 /24 网段哈希 */
    break;
case AF_INET6:
    iphp->addr = (u_char *) &sin6->sin6_addr.s6_addr;
    iphp->addrlen = 16;                /* IPv6 用全部 16 字节 */
    break;
default:
    iphp->addr = ngx_http_upstream_ip_hash_pseudo_addr;   /* unix socket：3 字节 0 */
    iphp->addrlen = 3;
}
iphp->hash = 89;                       /* 初始种子 */

/* 逐字节：hash = (hash * 113 + addr[i]) % 6271 */
```

- 重试时 hash 是**迭代累加**的（保留上次结果再跑一遍），所以每次重试会落到不同 peer，上限 **20 次**，超限或 peer 数 < 2 就降级为轮询；
- **不支持 `backup`**（flags 里没有 `NGX_HTTP_UPSTREAM_BACKUP`）；
- 因为按 /24 哈希，同一个公司出口 NAT 后的用户会全部落到同一台，容易造成偏斜。

### hash / consistent hash

```nginx
upstream backend {
    hash $request_uri;              # 普通哈希（兼容 Cache::Memcached）
    # hash $request_uri consistent; # 一致性哈希（ketama）
    server a:8080 weight=2;
    server b:8080;
}
```

- 哈希函数只有 **crc32**（开源版没有 murmur 选项）；
- 普通哈希：`hash = (crc32(key) >> 16) & 0x7fff`，返回值落在 `[0, total_weight)` 后按权重线性扫描；失败时 `rehash`（把序号前缀进去再算一次），上限 20 次；
- 一致性哈希（ketama）：**每个权重单位 160 个虚拟点**（`weight=1` → 160 个点），环上的点按 `crc32(HOST '\0' PORT PREV_HASH)` 链式生成，排序后二分查找第一个 `hash >= key` 的点；节点全挂就顺移到环上下一个点（上限 20 次），再不行降级轮询；
- 一致性哈希的价值在于**节点增减时只迁移少量 key**，适合缓存类后端；
- **不支持 `backup`**。

### least_conn

选 `conns / weight` 最小的节点。源码用交叉相乘避免浮点：

```c
if (best == NULL || peer->conns * best->weight < best->conns * peer->weight) {
    best = peer; many = 0; p = i;
} else if (peer->conns * best->weight == best->conns * peer->weight) {
    many = 1;                          /* 平局：稍后在同比例节点间再跑一次 SWRR */
}
```

**支持 `backup`**。注意 `conns` 是**当前 worker 进程内**的并发数，不是全局——除非配了 `zone`（共享内存）把状态汇总起来。

### random

```nginx
upstream backend {
    random two least_conn;    # P2C：随机挑两个，取其中连接数更少的
}
```

- 1.15.1 引入；
- 加权随机用**前缀区间 + 二分**（`x = ngx_random() % total_weight`）；
- `two` 即 power of two choices，在分布式场景下比纯随机好得多，且不需要全局状态；
- **不支持 `backup`**。

### least_time（1.31.0 起开源）

```nginx
upstream backend {
    least_time header inflight;    # 按平均响应头时间选，inflight 表示计入在途请求
}
```

之前是 NGINX Plus 专有，1.31.0 合入开源版。它把每个 peer 的平均响应时间（到响应头 / 到最后一个字节）作为打分依据。

### sticky（1.29.6 起开源）

```nginx
upstream backend {
    sticky cookie srv_id expires=1h domain=.example.com path=/;
    # sticky route $route;                     # 基于 route 参数
    # sticky learn create=$upstream_cookie_sid lookup=$cookie_sid zone=sessions:1m;
    server a:8080 route=a;
    server b:8080 route=b;
}
```

会话保持的三种实现：cookie（nginx 自己下发）、route（从请求里取）、learn（从上游响应的 cookie 里学习）。此前属于 NGINX Plus，1.29.6 进入开源版；随之一同开源的还有 `server ... route=` 与 `server ... drain`（优雅摘流量）。

### 算法对照

| 指令 | 依据 | 会话保持 | backup | 状态来源 |
| :-- | :-- | :-- | :-- | :-- |
| （默认） | 平滑加权轮询 | 否 | ✅ | 每 worker |
| `ip_hash` | 客户端 IP /24（v4） | 是 | ❌ | 无状态 |
| `hash` | 任意变量的 crc32 | 是 | ❌ | 无状态 |
| `hash ... consistent` | ketama 一致性哈希 | 是 | ❌ | 无状态 |
| `least_conn` | `conns/weight` | 否 | ✅ | 每 worker（或 zone） |
| `least_time` | 平均响应时间 | 否 | ✅ | 每 worker（或 zone） |
| `random two` | 随机两个取优 | 否 | ❌ | 每 worker |
| `sticky` | cookie / route / learn | 是 | 视算法 | zone（learn 模式） |

## server 指令参数

```c
// http/ngx_http_upstream.c
weight = 1;
max_conns = 0;
max_fails = 1;
fail_timeout = 10;
```

| 参数 | 默认 | 说明 |
| :-- | :-- | :-- |
| `weight=N` | 1 | 权重 |
| `max_fails=N` | **1** | fail_timeout 窗口内失败多少次就标记为不可用 |
| `fail_timeout=T` | **10s** | 既是"失败计数窗口"，也是"被标记后隔离多久" |
| `max_conns=N` | 0（不限） | 并发连接上限，达到就跳过该 peer（`conns >= max_conns`） |
| `backup` | — | 备用，仅主组全挂时启用（需算法支持） |
| `down` | — | 永久标记为不可用（用于优雅摘除） |
| `drain` | — | 1.29.6 起：不再接收新会话，但已有会话继续（配合 sticky） |
| `route=S` | — | 1.29.6 起：sticky route 用的标识，最长 32 字符 |
| `resolve` | — | 运行时用 resolver 重新解析域名（需配 `zone`） |
| `service=N` | — | 配合 DNS SRV 记录（需 `resolve` + `zone`） |
| `slow_start` | — | ❌ **开源版没有**，只是二进制兼容的占位字段 |

> `max_fails=1` 的默认值非常激进：**一次**失败就把节点摘掉 10 秒。上游偶尔抖动时会看到节点频繁进出，生产上建议改成 `max_fails=3 fail_timeout=10s`（甚至更长窗口 + 更大阈值）。

## 失败判定与重试

### 失败类型（ft_type）

```c
// http/ngx_http_upstream.h
#define NGX_HTTP_UPSTREAM_FT_ERROR            0x0002   /* 连接/读写错误 */
#define NGX_HTTP_UPSTREAM_FT_TIMEOUT          0x0004   /* connect/send/read 超时 */
#define NGX_HTTP_UPSTREAM_FT_INVALID_HEADER   0x0008   /* 上游响应头不合法 */
#define NGX_HTTP_UPSTREAM_FT_HTTP_500         0x0010
#define NGX_HTTP_UPSTREAM_FT_HTTP_502         0x0020
#define NGX_HTTP_UPSTREAM_FT_HTTP_503         0x0040
#define NGX_HTTP_UPSTREAM_FT_HTTP_504         0x0080
#define NGX_HTTP_UPSTREAM_FT_HTTP_403         0x0100
#define NGX_HTTP_UPSTREAM_FT_HTTP_404         0x0200
#define NGX_HTTP_UPSTREAM_FT_HTTP_429         0x0400
#define NGX_HTTP_UPSTREAM_FT_UPDATING         0x0800   /* 缓存正在后台更新 */
#define NGX_HTTP_UPSTREAM_FT_BUSY_LOCK        0x1000   /* 没抢到 cache lock */
#define NGX_HTTP_UPSTREAM_FT_MAX_WAITING      0x2000
#define NGX_HTTP_UPSTREAM_FT_NON_IDEMPOTENT   0x4000   /* 非幂等方法且请求已发出 */
#define NGX_HTTP_UPSTREAM_FT_NOLIVE           0x40000000
#define NGX_HTTP_UPSTREAM_FT_OFF              0x80000000
```

`proxy_next_upstream` 的默认值是 **`error timeout`**，可选值就是上表的字面量（`http_500`、`http_502`、`http_503`、`http_504`、`http_403`、`http_404`、`http_429`、`invalid_header`、`non_idempotent`、`updating`、`off`）。

> 注意 `http_404` 也可以被当作"失败"来重试——在"上游滚动发布导致短暂 404"的场景下有用，但通常不该打开，因为它会把正常业务的 404 放大 N 倍打到所有节点。

### 重试状态机

```c
// http/ngx_http_upstream.c
if (u->peer.sockaddr) {
    if (ft_type == NGX_HTTP_UPSTREAM_FT_HTTP_403
        || ft_type == NGX_HTTP_UPSTREAM_FT_HTTP_404)
    { state = NGX_PEER_NEXT; }        /* 403/404 不计入 fails，只是换一个 */
    else { state = NGX_PEER_FAILED; }
    u->peer.free(&u->peer, u->peer.data, state);
    u->peer.sockaddr = NULL;
}

/* 请求已发出且是非幂等方法 → 标记 NON_IDEMPOTENT */
if (u->request_sent && (r->method & (NGX_HTTP_POST|NGX_HTTP_LOCK|NGX_HTTP_PATCH))) {
    ft_type |= NGX_HTTP_UPSTREAM_FT_NON_IDEMPOTENT;
}

if (u->peer.tries == 0                                              /* 试完了 */
    || ((u->conf->next_upstream & ft_type) != ft_type)              /* 策略不允许 */
    || (u->request_sent && r->request_body_no_buffering)            /* 请求体无法重放 */
    || (timeout && ngx_current_msec - u->peer.start_time >= timeout))/* 总超时 */
{
    ngx_http_upstream_finalize_request(r, u, status);
    return;
}
ngx_http_upstream_connect(r, u);      /* 换下一个 peer 重来 */
```

四个"不重试"条件里，第二个最容易被忽略：位掩码必须**全部命中**，而 `NON_IDEMPOTENT` 已被并入 `ft_type`——所以 **POST 请求默认不重试**，除非显式写 `proxy_next_upstream ... non_idempotent;`。这是防止重复下单的保护，不要盲目打开。

tries 计数：

- `u->peer.tries` 初始值 = 主组非 down peer 数 + backup 组 peer 数（`ngx_http_upstream_tries(p)`）；
- 每次 `free` 时 `--`；
- `proxy_next_upstream_tries N` 可以把它压小（默认 0 = 不限制）；
- 状态码触发的重试判定用的是 `u->peer.tries > 1`（进入 `next()` 时当前 peer 还占着一次，所以是 `> 1` 而不是 `> 0`）。

### 主动 vs 被动健康检查

> [!WARNING]
> nginx **开源版没有主动健康检查**。所有"节点是否健康"的判定都来自真实请求的失败。

| | 开源 nginx | NGINX Plus / Tengine / 第三方模块 |
| :-- | :-- | :-- |
| 机制 | 被动：`max_fails` + `fail_timeout` | 主动：定期发探测请求（HTTP/TCP），独立判定状态 |
| 优点 | 零额外流量 | 能在无人访问时提前摘除故障节点 |
| 缺点 | 只有真实请求失败才知道；`max_fails=1` 时抖动敏感 | 需要额外配置/模块 |

开源版的可行替代：

- 把 `max_fails` 调到合理值（3~5），`fail_timeout` 拉长（10~30s）；
- 用 `zone` + 脚本定期调用 `ngx_http_upstream_zone` 暴露的状态（Plus 才有 API）；
- 外部探活 + 动态改配置 + reload（粗暴但有效）；
- 用 OpenResty + lua-resty-upstream-healthcheck，或改用 Tengine。

## upstream 长连接

HTTP/1.1 的长连接能省掉大量 TIME_WAIT 与握手开销。nginx 侧由 `ngx_http_upstream_keepalive_module` 实现，做法是**装饰器的装饰器**：

1. 配置期（`init_main_conf`）把 `us->peer.init` 换成 `ngx_http_upstream_init_keepalive_peer`，并保存原来的：

   ```c
   kcf->original_init_peer = uscfp[i]->peer.init;
   uscfp[i]->peer.init = ngx_http_upstream_init_keepalive_peer;
   ```
2. 每请求初始化时再换掉 `get`/`free`，并保存原函数：

   ```c
   kcf->original_init_peer(r, us);                    /* 先跑原算法初始化 */
   kp->original_get_peer  = r->upstream->peer.get;
   kp->original_free_peer = r->upstream->peer.free;
   r->upstream->peer.get  = ngx_http_upstream_get_keepalive_peer;
   r->upstream->peer.free = ngx_http_upstream_free_keepalive_peer;
   ```
3. `get` 时**先问负载均衡器选 peer**，再在空闲池里按 `sockaddr` 精确匹配找可复用连接；命中返回 `NGX_DONE`（复用），没命中返回 `NGX_OK`（照常新建）；
4. `free` 时若一切正常（未失败、未超时、`u->keepalive` 为真、请求体已发完、进程未退出）就放回池中，池满则**淘汰队尾最老的连接**；并给这条连接挂上 `keepalive_timeout` 的定时器，handler 用 `recv(MSG_PEEK)` 探活，对端已关闭就立即回收。

关键参数（1.31.6）：

| 指令 | 默认 | 说明 |
| :-- | :-- | :-- |
| `keepalive N` | **1.29.7 起默认启用，默认 32** | 每个 worker 的空闲连接上限 |
| `keepalive_requests` | 1000 | 单条连接最多服务多少请求 |
| `keepalive_time` | 1h | 单条连接最长存活时间 |
| `keepalive_timeout` | 60s | 空闲多久后关闭 |
| `keepalive ... local` | 1.29.7 起新增 | 只复用同一 `proxy_*` 配置块建立的连接 |

> [!TIP]
> 1.29.7 是一个分水岭：此前 upstream keepalive **默认关闭**，且必须同时写 `proxy_http_version 1.1;` 与 `proxy_set_header Connection "";`。1.29.7 起 `keepalive` 默认开启、`proxy_http_version` 默认 1.1、`Connection` 头不再默认发送——**老配置里那行 `proxy_set_header Connection "";` 现在是多余的**，留着反而可能干扰 HTTP/1.1 语义。升级前请核对版本。

## 超时矩阵

超时是最容易被"拍脑袋"配置的部分，它们各自管的是完全不同的时间段：

| 指令 | 默认 | 管的是 |
| :-- | :-- | :-- |
| `proxy_connect_timeout` | **60s** | 与上游建连（含 TCP 握手，TLS 握手另算） |
| `proxy_send_timeout` | **60s** | 两次成功写操作之间的**间隔**（不是总时长） |
| `proxy_read_timeout` | **60s** | 两次成功读操作之间的**间隔**（很多人误以为是"总响应时间"） |
| `proxy_next_upstream_timeout` | 0（不限） | 从第一次尝试算起，重试的总时间预算 |
| `resolver_timeout` | 30s | DNS 查询 |
| upstream `keepalive_timeout` | 60s | 空闲上游连接 |

推论：

- `proxy_read_timeout` 的语义是"读间隔"，所以**上游持续缓慢输出数据（如流式响应）不会超时**，只有完全静默 60s 才会。长轮询/SSE 场景要调大它；
- 想把"上游总耗时"限制住，靠 `proxy_next_upstream_timeout` 而不是 `read_timeout`；
- 默认值 60s 对内网服务往往过长：一个上游 hang 住会同时占用一个 worker 连接 60 秒，连接数不够时很快雪崩。内网建议 `connect 2-5s`、`read 10-30s`。
- `proxy_connect_timeout` 覆盖的是**握手阶段**：nginx 把上游 socket 设为非阻塞后调 `connect()`，拿到 `EINPROGRESS` 就注册写事件等 `EPOLLOUT`，而不是阻塞在 `connect()` 上——机制见 [socket](/docs/CS/OS/Linux/net/socket.md)。服务端一侧的监听队列（`listen ... backlog=` 与 `net.core.somaxconn`）如何造成连接堆积、SYN 队列与 accept 队列如何分工，见 [TCP 连接建立](/docs/CS/OS/Linux/net/TCP/Connection_Setup.md)。

## 缓冲

```nginx
location /api/ {
    proxy_buffering        on;              # 默认开
    proxy_buffer_size      16k;             # 响应头缓冲（默认 1 页）
    proxy_buffers          8 16k;           # 响应体缓冲（默认 8 页）
    proxy_busy_buffers_size 32k;            # 已就绪可发给客户端的上限
    proxy_max_temp_file_size 1g;            # 超出缓冲后落盘上限（默认）
    proxy_temp_path        /var/tmp/nginx/proxy;

    proxy_request_buffering on;             # 默认开：先把客户端请求体收完再发上游
    client_body_buffer_size 16k;            # 超出则落临时文件
    client_max_body_size    20m;
}
```

- `proxy_buffering on`：nginx 尽快把上游响应读进缓冲区，读完立即释放上游连接，然后按客户端的速度慢慢发。**这是反向代理的推荐配置**——否则慢客户端会一直占着上游连接。
- `proxy_buffering off`：同步透传，上游 → nginx → 客户端几乎同时。适合 SSE、流式输出、大文件下载，代价是上游连接被客户端速度绑架。
- `proxy_request_buffering on`：先把请求体收完再发上游。好处是上游不被慢客户端拖住，而且**请求可以重放**（这也是 `proxy_request_buffering off` 时无法重试的原因之一，源码里 `r->request_body_no_buffering` 会直接禁止重试）。
- 上传大文件时 `client_body_buffer_size` 不够会落盘，注意 `proxy_temp_path` 所在磁盘的容量与 IO。

## resolver 与动态 upstream

写死 IP 不利于弹性伸缩，但把域名直接写进 `server` 只会在**启动时解析一次**。要运行时解析：

```nginx
http {
    resolver 10.0.0.2 valid=30s ipv6=off;

    upstream backend {
        zone backend_zone 1m;                  # 共享内存，跨 worker 共享状态
        server backend.internal:8080 resolve;  # 运行时按 valid 周期重新解析
    }
}
```

- `resolve` 必须配 `zone`，否则报错；
- `zone` 还把 `conns`、`fails` 等状态从"每 worker"变成"全局"，让 `least_conn` / `max_conns` / 故障判定更准确；
- 域名解析发生在独立的 resolver 进程/事件里，不会阻塞 worker；
- Kubernetes 场景：Pod IP 变化频繁，`resolve` + 短 `valid` 是常见组合，但要注意 DNS 本身的可用性。

## 调优与排查

**必配**

1. `proxy_http_version 1.1;`（1.29.7 前必须显式写）+ upstream `keepalive`，能显著降低上游 TIME_WAIT 与握手延迟；
2. 显式设置三个超时，别用 60s 默认值；
3. `proxy_next_upstream` 明确写出要重试的条件，别让它意外重试 POST；
4. `max_fails` 从默认的 1 调大；
5. 给上游组配 `zone`，让状态跨 worker 一致。

**日志排查**

```nginx
log_format up '$remote_addr rt=$request_time uct="$upstream_connect_time" '
              'urt="$upstream_response_time" uaddr="$upstream_addr" '
              'status=$status ustatus=$upstream_status tries=$upstream_tries';
```

- `$upstream_addr`：**多个地址用逗号分隔**就说明发生了重试，这是发现上游抖动最快的信号；
- `$upstream_response_time` 多个值对应每次尝试；
- `$upstream_status` 出现 `502` 且 `$upstream_addr` 为空 → 通常是**根本没选中可用 peer**（全部被标记为 failed / DNS 失败）；
- 出现 `upstream prematurely closed connection` → 上游在响应完整返回前关闭了连接（常见于上游超时设置比 nginx 短）；
- 出现 `no live upstreams while connecting to upstream` → 所有 peer 都在 fail_timeout 隔离期内。

**常见坑**

1. **`proxy_pass` 里的主机名在 upstream 里改了不生效**：`proxy_pass http://backend;` 只在启动时解析 upstream 名到 `ngx_http_upstream_srv_conf_t`，改 IP 需要 `resolve` 或 reload。
2. **`proxy_set_header Host` 不写会透传 upstream 名**：默认 `Host` 是 `proxy_pass` 里写的那个名字（`backend`），多数上游会因此匹配不到虚拟主机。同时别忘了 `Connection` 与 `X-Forwarded-For`。
3. **reload 会重置 upstream 的失败计数与共享内存状态**（`zone` 会重建）。
4. **`max_conns` 是每 worker 的**（没有 zone 时），8 个 worker 配 `max_conns=10` 实际是 80。
5. **重试会放大流量**：`proxy_next_upstream_tries 0`（不限）在上游整体缓慢时会把 QPS 放大到 peer 数倍，务必设上限。
6. **grpc / websocket 场景**：`grpc_pass` 用独立的 `ngx_http_grpc_module`；WebSocket 需要显式升级头：

   ```nginx
   location /ws/ {
       proxy_http_version 1.1;
       proxy_set_header Upgrade $http_upgrade;
       proxy_set_header Connection "upgrade";   /* 注意：1.29.7 后 Connection 不再默认发送 */
       proxy_read_timeout 3600s;
       proxy_pass http://backend;
   }
   ```

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)
- [Cache](/docs/CS/CN/nginx/cache.md) — upstream 与缓存的交界
- [HTTP](/docs/CS/CN/nginx/HTTP.md) — upstream 作为 content handler 如何被挂载
- [Configuration](/docs/CS/CN/nginx/config.md) — `proxy_pass` 的 URI 替换规则
- [gRPC](/docs/CS/CN/nginx/grpc.md) — 另一套上游协议与它的重试限制
- [Benchmark](/docs/CS/CN/nginx/benchmark.md) — 上游连接池与重试的实测对照

## References

1. [Module ngx_http_upstream_module](https://nginx.org/en/docs/http/ngx_http_upstream_module.html)
2. [Module ngx_http_proxy_module](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)
3. [Module ngx_http_upstream_keepalive_module](https://nginx.org/en/docs/http/ngx_http_upstream_keepalive_module.html)
4. [NGINX Load Balancing — HTTP Load Balancer](https://docs.nginx.com/nginx/admin-guide/load-balancer/http-load-balancer/)
5. [nginx 源码：src/http/ngx_http_upstream.c、ngx_http_upstream_round_robin.c](https://nginx.org/download/nginx-1.31.6.tar.gz)
