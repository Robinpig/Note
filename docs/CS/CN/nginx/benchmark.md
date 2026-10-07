## Introduction

前面几篇（[Event](/docs/CS/CN/nginx/event.md)、[Upstream](/docs/CS/CN/nginx/upstream.md)、[Log](/docs/CS/CN/nginx/log.md)）的结论都是从源码读出来的。源码能告诉你「默认值是多少」「代码怎么走」，但**不能告诉你两件事**：一是某个配置项在真实负载下到底改变了什么，二是某些广为流传的说法虽然源码上成立、实测却没有意义。

本文用**自编译的 nginx 1.31.6 + ApacheBench** 做了 8 组对照实验，每组只改一个变量，并把**原始输出**贴出来。目的有两个：给前面几篇的源码结论补上实测证据，同时留下一份**可复现的实验脚本**——以后升级版本或换环境，重跑一遍就能检查结论是否还成立。

> [!WARNING]
> **本文所有数字都不代表生产性能。** 测试跑在 macOS（Darwin 15.8.1 / arm64）+ loopback 上，与 Linux 生产的网络栈、文件系统、epoll 实现完全不同。本文要的是**对照关系**（A 比 B 快多少、行为差异方向），不是绝对值。凡是把 loopback 数字当容量规划依据的做法都是错的——实验 8 就是专门用来证明这一点的反面教材。

### Test Environment and Reproduction Method

```bash
# 1. 取源码并编译（为避开 PCRE 依赖，关掉 rewrite 与 gzip 模块）
cd /tmp/ngx/nginx-1.31.6
./configure --prefix=/tmp/ngx/run \
    --without-http_rewrite_module --without-http_gzip_module \
    --with-http_stub_status_module --with-http_realip_module --with-http_v2_module
make -j4
```

环境：macOS 15.8.1 / arm64，nginx 1.31.6，ApacheBench 2.3，工具仅 `ab` + `curl`（**未装 wrk / h2load**，因此本文不含 HTTP/2、HTTP/3 与万级并发的测试）。

测试拓扑是一个 nginx 同时扮演两个角色：8081 当「上游服务器」，8080 当「被测前端」，再加 8082 专测 `keepalive_requests`：

```nginx
worker_processes  2;
error_log  /tmp/ngx/run/logs/error.log info;

events {
    worker_connections  1024;
}

http {
    default_type  text/plain;
    access_log    off;
    log_format  conn  '$connection $connection_requests $request_uri';

    limit_req_zone  $binary_remote_addr zone=req_plain:1m   rate=10r/s;
    limit_req_zone  $binary_remote_addr zone=req_nodelay:1m rate=10r/s;

    server {                                    # 上游
        listen 8081;
        access_log /tmp/ngx/run/logs/upstream.log conn;
        location = /small { alias /tmp/ngx/run/html/small.txt; }
    }

    upstream backend_ka   { server 127.0.0.1:8081; keepalive 32; }
    upstream backend_noka { server 127.0.0.1:8081; keepalive 0; }

    server {                                    # 被测前端
        listen 8080;
        location = /small { alias /tmp/ngx/run/html/small.txt; }
        location = /big-sf  { alias /tmp/ngx/run/html/big.bin; sendfile on;  }
        location = /big-nsf { alias /tmp/ngx/run/html/big.bin; sendfile off; }

        location = /lr-plain   { limit_req zone=req_plain   burst=40;         alias /tmp/ngx/run/html/small.txt; }
        location = /lr-nodelay { limit_req zone=req_nodelay burst=40 nodelay; alias /tmp/ngx/run/html/small.txt; }
        location = /upload     { client_max_body_size 1k; alias /tmp/ngx/run/html/small.txt; }

        location = /ka   { proxy_pass http://backend_ka/small;   proxy_http_version 1.1; proxy_set_header Connection ""; }
        location = /noka { proxy_pass http://backend_noka/small; proxy_http_version 1.1; proxy_set_header Connection ""; }

        location = /status { stub_status; }
    }

    server {                                    # 专测 keepalive_requests
        listen 8082;
        keepalive_timeout   65s;
        keepalive_requests  3;
        access_log /tmp/ngx/run/logs/buffered.log combined buffer=64k;
        location = /small { alias /tmp/ngx/run/html/small.txt; }
    }
}
```

> [!NOTE]
> 一个实操经验：把 upstream 的 `access_log` 里记上 `$connection` 与 `$connection_requests`，就能**直接数出前端到底用了多少个上游连接、每个连接扛了多少请求**。这比抓包或看 `ss` 简单得多，是验证连接池行为最省事的办法，后文实验 3 就用它。

### Experiment 1: What `limit_req`'s `burst` and `nodelay` Actually Change

同一速率（`rate=10r/s`）、同一 `burst=40`，只差一个 `nodelay`：

```bash
ab -n 60 -c 10 http://127.0.0.1:8080/lr-nodelay
ab -n 60 -c 10 http://127.0.0.1:8080/lr-plain
```

| 配置 | 完成 | 非 2xx | 耗时 | 吞吐 | 平均响应 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| `burst=40 nodelay` | 60 | **19** | 0.009s | 6414 rps | 1.6 ms |
| `burst=40`（无 nodelay） | 60 | **0** | **5.901s** | **10.17 rps** | **983 ms** |

这张表把两个概念彻底分开了：

- **`burst` 是队列长度，不是"允许的超出量"**。它决定最多有多少个超出速率的请求可以「留在系统里」。
- **`nodelay` 决定队列里的请求是"等"还是"立即返回"**。有 `nodelay` 时，队列槽位被瞬间消费，第 41 个请求起直接 503——所以 19 个被拒、耗时 9ms。没有 `nodelay` 时，请求被**延迟**处理，实测吞吐恰好等于配置的 `rate`（10.17 rps ≈ 10r/s），一个都没被拒。

也就是说：**无 `nodelay` 的 `limit_req` 不是"限流拒绝"，而是"限速排队"**。它把压力转成延迟压在客户端身上。这一点在只做功能测试时几乎发现不了——用 `curl` 单发请求永远看不出区别，必须并发打才暴露。

那什么时候无 `nodelay` 也会 503？把并发从 10 拉到 60（一次性打满）：

```bash
ab -n 60 -c 60 http://127.0.0.1:8080/lr-plain
# Complete requests: 60 / Non-2xx responses: 19 / Time taken: 4.003s / 14.99 rps
```

队列（40 个）装不下的部分一样被拒。所以完整结论是：**并发小于 `burst` 时只延迟不拒绝；并发超过 `burst` 时才拒绝**。选 `burst` 的大小时，要按「你能接受多久的排队」来定，而不是「你愿意放多少漏」。

### Experiment 2: Benefits of Client Persistent Connection

```bash
ab -n 3000 -c 20 http://127.0.0.1:8080/small   # 每次新建连接
ab -k -n 3000 -c 20 http://127.0.0.1:8080/small # 长连接复用
```

| 模式 | 完成 | 耗时 | 吞吐 |
| :-- | :-- | :-- | :-- |
| HTTP/1.0 + 每请求新建连接 | 3000 | 0.093s | 32 233 rps |
| `-k` 长连接复用 | 3000 | 0.024s | **127 297 rps** |

**3.95 倍**，且在 `-k` 那一轮里 `Keep-Alive requests: 3000`——说明 3000 个请求全部复用了连接，一次都没重连。

这个差距几乎全部来自**连接建立成本**（`accept` + 分配 `ngx_connection_t` + 内核 socket 分配/回收）加上 TIME_WAIT 的堆积，跟请求本身的处理无关。它解释了两件事：

1. 为什么 `keepalive_timeout` 这类"连接层"参数在高并发下比"内容层"优化更敏感；
2. 为什么在反向代理场景里，**上游连接池与客户端长连接是两件独立但同样重要的事**——实验 3 马上量化后者。

### Experiment 3: Upstream Connection Pool (Also Confirming 1.29.7 Default Value Change)

用 upstream 日志里的 `$connection` 唯一值个数直接数连接：

```bash
: > logs/upstream.log && ab -n 100 -c 5 http://127.0.0.1:8080/noka
awk '{print $1}' logs/upstream.log | sort -u | wc -l     # 上游连接数
```

| 配置 | 上游连接数 | 单连接最大请求数 |
| :-- | :-- | :-- |
| `keepalive 0`（显式关闭） | **100** | 1 |
| `keepalive 32` | **7** | 22 |
| **不写 `keepalive` 指令** | **7** | 29 |

第三行是这次实验最重要的发现，而且是**意外得到**的：最初我把对照组写成「不写 `keepalive`」，跑出来 7 个连接——和 `keepalive 32` 几乎一样，对照失效了。

去源码里找原因，`ngx_http_upstream_keepalive_init_main_conf()` 给出了答案：

```c
if (kcf->max_cached == 0) {
    continue;                       /* 只有显式写 keepalive 0 才跳过包装 */
}
...
if (kcf->max_cached == NGX_CONF_UNSET_UINT) {
    kcf->local = 1;
    kcf->max_cached = 32;           /* 未配置时的默认池大小 */
}
```

再对 CHANGES 确认，这是 1.29.7 的变更：

> Change: now the `keepalive` directive in the `upstream` block is enabled by default.

**结论：在 1.31.6 上，"不写 `keepalive`"不等于"关闭上游长连接"**——默认就是开启的、池大小 32，而且默认带 `local = 1`。想真正关掉必须显式 `keepalive 0`。

这条对升级排查很关键：从老版本（≤1.29.6）升上来的配置，上游连接数会**悄悄从「每请求一个」变成「几十个并发复用」**。好处是吞吐改善，副作用是：后端如果按「连接数」做限流、或者依赖「请求结束即连接断开」的假设，行为会变；另外长连接会让上游的连接保持时间变长，`keepalive_timeout`（默认 60s）与后端自身的空闲超时要对齐。

### Experiment 4: Actual Boundary of `keepalive_requests`

`keepalive_requests 3;`，然后用 `curl` 在同一条连接上连发 4 个请求：

```bash
curl -sv -o /dev/null http://127.0.0.1:8082/small http://127.0.0.1:8082/small \
                       http://127.0.0.1:8082/small http://127.0.0.1:8082/small
```

实测输出（节选）：

```
* Connected to 127.0.0.1 port 8082
< Connection: keep-alive
* Connection #0 to host 127.0.0.1 left intact
* Re-using existing connection with host 127.0.0.1
< Connection: keep-alive
* Connection #0 to host 127.0.0.1 left intact
* Re-using existing connection with host 127.0.0.1
< Connection: close                      ← 第 3 个请求，服务端宣告不再复用
* Closing connection
* Connected to 127.0.0.1 port 8082        ← 第 4 个请求，必须新建连接
< Connection: keep-alive
* Connection #1 to host 127.0.0.1 left intact
```

语义非常干净：**第 `keepalive_requests` 个请求的响应里带 `Connection: close`，连接在该请求完成后关闭，第 N+1 个请求必须重连**。「关闭」的时机是**响应之后**，不是第 N 个请求前——所以不会丢请求。

顺带一个 1.19.10 的默认值事实：`keepalive_requests` 的默认值从 100 改成了 **1000**。压测时如果看到吞吐在某一点突然掉台阶，先查这个值。

### Experiment 5: Boundary of `client_max_body_size`

`client_max_body_size 1k;`

```bash
head -c 2048 /dev/zero | curl -s -o /dev/null -w "%{http_code}\n" -X POST --data-binary @- http://127.0.0.1:8080/upload
head -c  512 /dev/zero | curl -s -o /dev/null -w "%{http_code}\n" -X POST --data-binary @- http://127.0.0.1:8080/upload
```

```
2048 字节 -> 413
 512 字节 -> 405
```

`413` 是预期内的。有意思的是 `512` 返回的不是 413 而是 **405**——说明请求体大小检查通过之后才轮到方法检查（该 location 只能 GET 静态文件）。这条小实验的价值在于确认**检查点在链路上的位置**：大小限制发生在 CONTENT 阶段之前，所以哪怕 location 根本没有处理 POST 的能力，超大请求体也会先被 413 拦下。

再配合 [grpc](/docs/CS/CN/nginx/grpc.md) 里那条源码结论一起看：HTTP/2 客户端不带 `Content-Length` 时 `content_length_n = -1`，检查被跳过。所以 **`client_max_body_size` 并不是一道能覆盖所有协议的防线**。

### Experiment 6: Real Behavior of Connection Pool Exhaustion

把 `worker_connections` 压到 16，再打 60 并发：

```bash
ab -n 200 -c 60 http://127.0.0.1:8080/small
```

```
Complete requests:      200
Failed requests:        0
```

**一个请求都没失败**，error.log 里只多出一条警告：

```
[warn] 16 worker_connections are not enough, reusing connections
```

注意是**一条**，不是几十条——因为这条警告有每秒最多一次的节流。源码在 `ngx_drain_connections()`（`src/core/ngx_connection.c`）：

```c
if (cycle->free_connection_n > cycle->connection_n / 16
    || cycle->reusable_connections_n == 0)
{
    return;                              /* 空闲连接还够，直接返回 */
}

if (cycle->connections_reuse_time != ngx_time()) {
    cycle->connections_reuse_time = ngx_time();
    ngx_log_error(NGX_LOG_WARN, cycle->log, 0,
                  "%ui worker_connections are not enough, reusing connections",
                  cycle->connection_n);   /* 每秒最多一条 */
}

c = NULL;
n = ngx_max(ngx_min(32, cycle->reusable_connections_n / 8), 1);

for (i = 0; i < n; i++) {
    ...
    c->close = 1;
    c->read->handler(c->read);            /* 关闭空闲的长连接，把槽位腾出来 */
}
```

**"reusing connections" 的真实含义不是"复用"，而是"回收"**：nginx 会**主动踢掉一批空闲的 keepalive 连接**（每次 `max(min(32, 可回收数/8), 1)` 个）来给新连接腾位置。触发条件是空闲连接跌破总数的 1/16。

这带来两个实用结论：

1. 看到 `worker_connections are not enough`，**不代表请求失败**——它意味着一批客户端的长连接被服务端单方面关闭了。客户端如果没有重连逻辑，会看到 `Connection reset`；有重连逻辑则只是多一次握手。
2. **这条日志是"连接池水位"的告警，不是"错误"**。它真正的调优信号是：要么加大 `worker_connections`，要么缩短 `keepalive_timeout` 让空闲连接早点释放。

### Experiment 7: When `access_log buffer` Flushes to Disk

在 8082 上配 `access_log ... combined buffer=64k;`，发 5 个请求：

```bash
for i in 1 2 3 4 5; do curl -s -o /dev/null http://127.0.0.1:8082/small; done
wc -c < logs/buffered.log     # -> 0
nginx -s reload
wc -c < logs/buffered.log     # -> 440
```

**5 个请求发完，日志文件是 0 字节**；执行一次 `reload` 之后变成 440 字节、5 行都在。

这就是「日志为什么是空的」的完整答案：`buffer=` 让 nginx 把日志攒在用户态内存里，攒满 64k 才写盘；`reload`（以及 `USR1`、退出）会触发日志重开与 flush。这也是为什么**缓冲日志不适合做实时监控数据源**——必须配 `flush=` 定一个时间上界：

```nginx
access_log /var/log/nginx/access.log combined buffer=64k flush=1s;
```

排查此类问题的经验：先看日志有没有内容，再看**是不是被 buffer 攒着**——用 `flush=` 或临时 `buffer=0` 就能区分「没产生日志」和「日志还没落盘」。

### Experiment 8: `sendfile` Shows No Benefit on loopback

512KB 静态文件，`-n 500 -c 20`，`sendfile on` 与 `off` 对照，连跑三轮消掉预热效应：

```bash
for round in 1 2 3; do
  for loc in big-sf big-nsf; do ab -n 500 -c 20 http://127.0.0.1:8080/$loc; done
done
```

| 轮次 | `sendfile on` | `sendfile off` |
| :-- | :-- | :-- |
| 1（含冷启动） | 7963 rps | 11480 rps |
| 2 | 11580 rps | 12130 rps |
| 3 | 11653 rps | 11982 rps |

**预热之后两者基本重合**（11.6k vs 12.0k，差异在噪声范围内）。

这条"负面结论"比正面结论更有教学价值，它说明了三件事：

1. **`sendfile` 的收益来自省掉「内核页缓存 → 用户态缓冲区 → socket 缓冲区」的拷贝**。而 loopback 的包不经过网卡，数据本来就只在内存里走一遍，拷贝的成本被摊薄到测不出来。
2. **macOS 与 Linux 的实现不同**，macOS 的 `sendfile` 语义与 Linux 的零拷贝并不等价；用 macOS 的数字论证 Linux 的 `sendfile` 收益是不成立的。
3. **对照组的第一轮会被冷启动污染**（7963 vs 后续 11.5k），单轮实验很容易得出反向结论。**任何压测至少跑三轮，并且丢掉第一轮。**

真实的 `sendfile` 收益要在「大文件 + 真实网卡 + 高并发」下才明显，机制层面的分析见 [零拷贝](/docs/CS/OS/Linux/ZeroCopy.md) 与 [I/O 模型总览](/docs/CS/OS/Linux/IO/IO.md)。

### Methodology: What This Kind of Load Test Can and Cannot Conclude

从上面 8 组实验可以提炼出一套判断标准：

**可以信的结论**（对照关系、行为方向）：

- 同一环境下 A 与 B 的相对差异（实验 1、2、3、7、8 的表格）
- 行为**边界与语义**：什么时候 503、第几个请求断连、日志什么时候落盘（实验 1、4、5、6、7）——这类结论跨平台成立，因为它们由源码逻辑决定
- 默认值是否生效（实验 3 证实了 1.29.7 之后上游 keepalive 默认开启）

**不能信的结论**：

- **绝对吞吐数字**。macOS + loopback 与 Linux + 网卡没有可比性，本文的 12 万 rps 不能拿去做容量规划。
- **未经预热、未重复的单项对比**。实验 8 第一轮会给出完全相反的结论。
- **把 loopback 的结论外推到网络场景**。零拷贝、`tcp_nopush`、`tcp_nodelay`、大包/小包、延迟类指标在 loopback 上全部失效。
- **用 `ab` 测 HTTP/2 与 HTTP/3**。`ab` 只支持 HTTP/1.0/1.1，测 h2/h3 必须用 `h2load`；TLS 握手与 ALPN 相关的结论也必须用能协商 ALPN 的客户端才测得到。

**工具建议**：`ab` 适合做本文这种「单变量、看行为」的对照；做容量测试换 `wrk`（HTTP/1.1 高并发）或 `h2load`（HTTP/2、HTTP/3、支持 ALPN）；要测延迟分布（p95/p99）用 `wrk` 的 `--latency` 或 `hdrhistogram`。**压测工具本身经常先成为瓶颈**——本文 `ab` 在 12 万 rps 时已经在吃力了。

### Conclusion Quick Reference

| 配置项 | 实测行为 | 一句话建议 |
| :-- | :-- | :-- |
| `limit_req burst` | 并发 < burst 只延迟不拒绝 | 按「可接受的排队时长」定 burst |
| `limit_req nodelay` | 超出 burst 立即 503，耗时从秒级降到毫秒级 | 不想让客户端等就加，但要接受 503 |
| 客户端 keepalive | 吞吐 3.95×（本环境） | 高并发下优先调连接层参数 |
| upstream `keepalive` | **默认已开启（1.29.7+，池 32）** | 升级后留意上游连接数突变，要关得写 `keepalive 0` |
| `keepalive_requests` | 第 N 个请求响应后断连，不丢请求 | 默认 1000；吞吐掉台阶先查它 |
| `client_max_body_size` | 检查在 CONTENT 阶段之前；HTTP/2 无 CL 时被跳过 | 不能当唯一防线 |
| `worker_connections` 不足 | **不失败**，回收空闲长连接 + 每秒一条 warn | 看到告警查 `keepalive_timeout` 与连接池水位 |
| `access_log buffer=` | 攒满才落盘，reload 才 flush | 配 `flush=1s`，否则不能做实时监控 |
| `sendfile` | loopback 上测不出差异 | 收益要在真实网卡 + 大小文件场景测 |

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)
- [Event](/docs/CS/CN/nginx/event.md) — 连接池、`accept`、`ngx_accept_disabled` 的实现
- [Upstream](/docs/CS/CN/nginx/upstream.md) — 上游连接池与 `keepalive` 指令
- [Log](/docs/CS/CN/nginx/log.md) — `access_log` 缓冲与 flush 的完整参数
- [Practice](/docs/CS/CN/nginx/practice.md) — 生产环境的调优与变更流程
- [零拷贝](/docs/CS/OS/Linux/ZeroCopy.md) — `sendfile` 的机制与真实收益场景

## References

- <https://nginx.org/en/docs/http/ngx_http_limit_req_module.html>
- <https://nginx.org/en/docs/http/ngx_http_core_module.html>
- <https://nginx.org/en/docs/http/ngx_http_log_module.html>
- <https://nginx.org/en/docs/http/ngx_http_upstream_module.html>
- <https://httpd.apache.org/docs/2.4/programs/ab.html>
- <https://github.com/wg/wrk>
- <https://nghttp2.org/documentation/h2load-howto.html>
