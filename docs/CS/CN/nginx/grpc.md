## Introduction

用 nginx 代理 gRPC，第一个要打破的直觉是：**`grpc_pass` 不是 `proxy_pass` 的一个参数，而是另一个 HTTP 客户端实现。**

`ngx_http_proxy_module` 写死的是 HTTP/1.x——请求行末尾直接拼 `" HTTP/1.0"` 或 `" HTTP/1.1"`，解析上游响应时也只会认 HTTP/1.x 状态行，遇到别的东西就报 `upstream sent no valid HTTP/1.0 header`。而 `ngx_http_grpc_module` 是一个**手写的 HTTP/2 客户端**：它自己发 HTTP/2 connection preface、自己发 SETTINGS、自己构造 `:method`/`:scheme`/`:path`/`:authority` 伪头、自己实现 HPACK 解码、自己处理 DATA 帧与 trailer。所以「把 `proxy_pass` 指到 gRPC 后端」这种做法在源码层面**不成立**。

第二个反直觉的点更关键：**nginx 并不理解 gRPC**。全源码 grep `grpc-status` 与 `grpc-message` **零命中**——它不解析 gRPC 的「1 字节压缩标志 + 4 字节长度」消息帧，也不解释状态码。gRPC 消息体对它来说只是 HTTP/2 DATA 帧里的不透明 payload，`grpc-status` 只是普通的 HTTP/2 **trailer**，被原样透传。所谓「nginx 支持 gRPC」，准确说法是「nginx 支持把 HTTP/2 双向流和 trailer 正确转发」。这一点决定了很多行为边界，后文会反复用到。

本文事实基于 **nginx 1.31.6** 源码（`src/http/modules/ngx_http_grpc_module.c`，5344 行）逐条核实。

### Quick Start

一个标准的 gRPC 反代（客户端侧 HTTP/2，上游 h2c 明文）：

```nginx
server {
    listen 443 ssl;
    http2  on;                       # 必须！否则 ALPN 不提供 h2，客户端会退到 HTTP/1.1
    ssl_certificate     /etc/nginx/cert.pem;
    ssl_certificate_key /etc/nginx/cert.key;

    location /helloworld.Greeter/ {
        grpc_pass grpc://127.0.0.1:50051;     # grpc:// = h2c；grpcs:// = h2/TLS
        grpc_read_timeout  3600s;             # 长流必须调大
        grpc_send_timeout  3600s;
        grpc_next_upstream  error timeout;
    }
}
```

`grpc_pass` 也支持 upstream 块、变量和 unix socket，用法与 `proxy_pass` 一致：

```nginx
upstream grpc_backend {
    server 10.0.0.11:50051;
    server 10.0.0.12:50051;
    keepalive 32;                    # 上游 HTTP/2 连接池复用
}

location /api/ {
    grpc_pass grpc://grpc_backend;
}
```

### Complete Directive Set and Defaults

`ngx_http_grpc_commands` 里共 **33 条**指令。整体分为两组——普通组与 `grpc_ssl_*` 组。

| 指令 | 默认值 | 说明 |
| :-- | :-- | :-- |
| `grpc_pass` | — | `grpc://` / `grpcs://` 前缀、变量、unix socket、upstream 块 |
| `grpc_connect_timeout` | **60s** | 与上游建连 |
| `grpc_read_timeout` | **60s** | 读上游响应；**长流要调大** |
| `grpc_send_timeout` | **60s** | 向上游写请求体 |
| `grpc_buffer_size` | **`ngx_pagesize`**（通常 4k） | 不是写死的 4k/8k，随页大小 |
| `grpc_next_upstream` | **`error timeout`** | 只这两项，**不含 `http_500` 等** |
| `grpc_next_upstream_tries` | `0`（不限） | |
| `grpc_next_upstream_timeout` | `0`（不限） | |
| `grpc_intercept_errors` | `off` | |
| `grpc_socket_keepalive` | `off` | |
| `grpc_socket_rcvbuf` / `grpc_socket_sndbuf` | `0`（内核默认） | 1.31.3 新增 |
| `grpc_bind` | — | |
| `grpc_set_header` / `grpc_pass_header` / `grpc_hide_header` / `grpc_ignore_headers` | — | 与 `proxy_*` 同名同义 |
| `grpc_ssl_*`（14 条） | 见下 | `grpc_ssl_session_reuse` 默认 **on**、`grpc_ssl_verify` 默认 **off**、`grpc_ssl_server_name` 默认 **off**、`grpc_ssl_verify_depth` 默认 **1**、`grpc_ssl_ciphers` 默认 **`DEFAULT`** |

`grpc_ssl_*` 共 14 条，与 `proxy_ssl_*` **一一对应、无差集**：`session_reuse`、`protocols`、`ciphers`、`name`、`server_name`、`verify`、`verify_depth`、`trusted_certificate`、`crl`、`certificate`、`certificate_key`、`certificate_cache`、`password_file`、`conf_command`。回源 TLS 直接用这组，并用 `grpcs://` 前缀触发。

### Three Hardcoded Values Determine Behavior Boundaries

`ngx_http_grpc_create_loc_conf()` 里有一组以 `/* the hardcoded values */` 开头的赋值，它们**没有对应指令、不可配置**：

```c
/* the hardcoded values */
conf->upstream.buffering = 0;            /* 响应侧永不缓冲 */
conf->upstream.pass_request_body = 1;
conf->upstream.pass_trailers = 1;        /* trailer 一定透明转发 */
conf->upstream.pass_early_hints = 1;
conf->upstream.preserve_output = 1;
```

再叠加 `ngx_http_grpc_handler()` 里的：

```c
r->request_body_no_buffering = 1;        /* 请求体边收边转，不落盘不整体缓冲 */
```

四条合起来就是 gRPC 代理的行为基石：**请求与响应都是流式的，且不可关闭**。所以下面这些指令**根本不存在**：`grpc_request_buffering`、`grpc_buffering`、`grpc_pass_trailers`、`grpc_pass_request_body`、`grpc_limit_rate`、`grpc_cache`、`grpc_store`。想「先缓冲完请求再发上游」或「关掉 trailer」，在 grpc 模块里没有开关。

### How Upstream Request Is Constructed

`ngx_http_grpc_create_request()` 干的第一件事不是写请求行，而是发 HTTP/2 握手。它有一段静态数组，把 connection preface 和两帧预编码好直接拷过去：

```c
static u_char  ngx_http_grpc_connection_start[] =
    "PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"         /* connection preface */
    "\x00\x00\x12\x04\x00\x00\x00\x00\x00"     /* SETTINGS 帧 */
    "\x00\x01\x00\x00\x00\x00"                 /* HEADER_TABLE_SIZE */
    "\x00\x02\x00\x00\x00\x00"                 /* ENABLE_PUSH = 0 */
    "\x00\x04\x7f\xff\xff\xff"                 /* INITIAL_WINDOW_SIZE = 2^31-1 */
    "\x00\x00\x04\x08\x00\x00\x00\x00\x00"     /* WINDOW_UPDATE */
    "\x7f\xff\x00\x00";
```

两个细节值得注意：**禁用了服务端推送**（`ENABLE_PUSH=0`，代理场景不需要），以及**把初始窗口开到 `0x7fffffff`**——相当于告诉上游「别等了，我这边不受流控限制」，把窗口管理的复杂度留给自己的 `send_window` 计数。

随后按 HPACK 编码写四个伪头。`:scheme` 由 `u->ssl` 决定（`grpcs://` 才是 https），而 `:authority` 是**无条件写**的：

```c
*{ b->last++ = ngx_http_v2_inc_indexed(NGX_HTTP_V2_AUTHORITY_INDEX);
b->last = ngx_http_v2_write_value(b->last, host.data, host.len, tmp); }
```

这正是 1.31.4 那条变更的内容：

> Change: now HTTP/2 and gRPC requests to backends are always sent with the `:authority` pseudo-header, and HTTP/1.1 requests - with the `Host` header.

### How to Read Upstream Response

`ngx_http_grpc_process_header()` 是逐帧解析器，认 HEADERS / CONTINUATION / DATA / RST_STREAM / GOAWAY / WINDOW_UPDATE / SETTINGS / PING。在头部里，**只有 `:status` 伪头是合法的**，其它以 `:` 开头的一律判协议违规：

```c
if (ctx->name.len && ctx->name.data[0] == ':') {
    if (ctx->name.len != sizeof(":status") - 1
        || ngx_strncmp(ctx->name.data, ":status", sizeof(":status") - 1) != 0)
    {
        ngx_log_error(NGX_LOG_ERR, r->connection->log, 0,
                      "upstream sent invalid header \"%V: %V\"", ...);
        return NGX_HTTP_UPSTREAM_INVALID_HEADER;
    }
    ...
} else if (!ctx->status) {
    ngx_log_error(NGX_LOG_ERR, r->connection->log, 0,
                  "upstream sent no :status header");
    return NGX_HTTP_UPSTREAM_INVALID_HEADER;
}
```

上游重复发 `:status` 也会被拒（`upstream sent duplicate :status header`）。

> [!NOTE]
> **源码里有个极易误读的函数名**：`ngx_http_grpc_parse_fragment()`。看名字像是「解析 gRPC 消息分片」，实际它做的是 **HPACK 头块（header block fragment）解码**——处理 indexed header field（0x80）、literal with incremental indexing（0x40）、dynamic table size update（0x20）、literal never indexed（0x10），并把 **static table 索引上限写死为 61**。gRPC 的消息帧（压缩标志 + 长度 + payload）在 nginx 里**从不解码**。

响应侧的 `ngx_http_grpc_filter()` 做的是：把 DATA 帧 payload 直接挂到 `u->out_bufs` 往下游转发；维护 `recv_window`，低于 `NGX_HTTP_V2_MAX_WINDOW/4` 时补发 WINDOW_UPDATE（这就是双向流的背压机制，也是 grpc 模块唯一的流量控制手段）。

请求侧则由 `ngx_http_grpc_body_output_filter()` 把请求体切成 **16384 字节**（`NGX_HTTP_V2_DEFAULT_FRAME_SIZE = 1 << 14`）的 DATA 帧，同时递减 `ctx->send_window` 与 `ctx->connection->send_window`。

### trailer and TE: Why Client Must Use HTTP/2

gRPC 的状态码 `grpc-status` 只能放在 HTTP/2 的 **trailing HEADERS** 里——响应开始时状态还未知，不可能放在头里。所以 trailer 是协议必需，而 nginx 必须把它透传给下游（`pass_trailers = 1` 硬编码）。

接收侧：

```c
if (ctx->name.len && ctx->name.data[0] == ':') {
    ngx_log_error(NGX_LOG_ERR, r->connection->log, 0,
                  "upstream sent invalid trailer \"%V: %V\"", ...);
    return NGX_ERROR;
}
h = ngx_list_push(&u->headers_in.trailers);
...
if (rc == NGX_HTTP_PARSE_HEADER_DONE) {
    if (ctx->end_stream) { ctx->done = 1; break; }
    ngx_log_error(NGX_LOG_ERR, r->connection->log, 0,
                  "upstream sent trailer without end stream flag");
    return NGX_ERROR;
}
```

即：**trailer 帧必须带 END_STREAM**，否则视为协议违规。

发送侧，转发给上游的默认头表里 `TE` 的值是一个内部变量：

```c
{ ngx_string("TE"), ngx_string("$grpc_internal_trailers") },
```

`$grpc_internal_trailers` 只在**客户端自己的 `TE` 头里含 `trailers`** 时才返回 `"trailers"`，否则 `not_found`（即不发这个头）。而客户端侧 HTTP/2 解析更严——`src/http/v2/ngx_http_v2.c` 要求 `TE` 只能出现一次且值必须**恰好**是 `trailers`，否则 400。

**那为什么不能用 HTTP/1.1 客户端调 gRPC？** 根源在请求体解析：`ngx_http_parse_chunked(r, b, rb->chunked, 0)` 的最后一个参数是 `keep_trailers = 0`，也就是 **HTTP/1.1 客户端请求体里的 trailer 被解析后直接丢弃**。既然 trailer 进不来也发不出去，gRPC 的语义就不成立。这是「gRPC 必须走 HTTP/2」的源码级解释，而不是一句笼统的「HTTP/1.1 不支持流」。

### Client-Side Protocol Prerequisites

- **必须显式 `http2 on;`（或 `listen ... http2`）**。`ngx_http_ssl_module` 的 ALPN 候选默认是 `NGX_HTTP_ALPN_PROTOS = "\x08http/1.1\x08http/1.0\x08http/0.9"`——**不含 h2**；只有 `h2scf->enable || hc->addr_conf->http2` 成立时，才会把 `NGX_HTTP_V2_ALPN_PROTO`（`"\x02h2"`）插到候选最前面。忘了这一条，客户端 ALPN 协商不到 h2，会静默退化成 HTTP/1.1。
- **h2c 只支持 prior knowledge**：非 SSL socket 上若首包是 `"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"` 就直接切到 HTTP/2。**不支持 HTTP/1.1 Upgrade 到 h2c**（全源码无该分支）。
- **上游永远是 HTTP/2**。`grpc_pass` 不带前缀时即 h2c；`grpcs://` 才是 h2/TLS。没有「上游走 HTTP/1.1」的选项——这也是为什么它不能直接代理普通 HTTP 后端。

### Request Body Limit: An Easy Place to Slip

`client_max_body_size` 的检查发生在核心阶段，依据是 `content_length_n`。而**HTTP/2 客户端如果不带 `Content-Length`**（gRPC 流式请求的常态），`content_length_n` 为 `-1`，**检查被直接跳过**。

所以：**典型的 gRPC 请求不受 `client_max_body_size` 约束**。想限制大消息，得靠上游应用自己或 `client_body_buffer_size` 之类的间接手段。HTTP/1.1 chunked 上传则仍会逐块累计检查，两者行为不同。

### Retry: Why gRPC Rarely Retries

通用重试决策在 `ngx_http_upstream_next()` 里，有一行专门为 gRPC 这类场景设的闸门：

```c
if (u->request_sent
    && (r->method & (NGX_HTTP_POST|NGX_HTTP_LOCK|NGX_HTTP_PATCH)))
{
    ft_type |= NGX_HTTP_UPSTREAM_FT_NON_IDEMPOTENT;
}
if (u->peer.tries == 0
    || ((u->conf->next_upstream & ft_type) != ft_type)
    || (u->request_sent && r->request_body_no_buffering)   /* ← gRPC 恒命中 */
    || (timeout && ngx_current_msec - u->peer.start_time >= timeout))
{
    ngx_http_upstream_finalize_request(r, u, status);
    return;
}
```

因为 grpc 模块把 `request_body_no_buffering` 硬编码为 1，**只要请求已开始发送（`u->request_sent`），就直接 finalize，不再换后端**。加上 gRPC 请求基本都是 POST（命中 `NON_IDEMPOTENT`），可行情况只剩「连接建立前就失败」。

再叠加 `grpc_next_upstream` 默认只有 `error timeout`，结论很清楚：**gRPC 的重试基本只在建连阶段发生**。想在应用层做重试，应该交给 gRPC 客户端自己的 retry policy，而不是 nginx。

### Timeout Matrix

| 指令 | 作用方向 | 语义 |
| :-- | :-- | :-- |
| `grpc_connect_timeout` | 建连 | 默认 60s |
| `grpc_send_timeout` | 客户端→上游 | 向上游写时静默超时；**客户端流式长期不发消息会撞它** |
| `grpc_read_timeout` | 上游→客户端 | 读上游时静默超时；**服务端流式长期不下发消息会撞它** |
| `grpc_next_upstream_timeout` | 重试窗口 | 默认 0（不限） |

要特别注意：**nginx 没有 gRPC 心跳（HTTP/2 PING）逻辑**。任何「该方向上持续有字节」都会重置定时器，但一旦某个方向静默超过对应超时，连接立刻断开。长连接双向流（比如语音/推送类）必须把这两个超时显式调大，否则会被 60s 默认值悄悄掐断。

### Troubleshooting: Log Keywords

grpc 模块自带的错误日志非常细（`upstream sent ...` 系列有 60 多条），按现象归类：

| 现象 | 关键字 | 多半原因 |
| :-- | :-- | :-- |
| 502 | `upstream sent invalid header` / `no :status header` / `invalid http2 table index` / `unexpected http2 frame` | 上游不是真 HTTP/2，或 HPACK/伪头不合规 |
| 502 | `upstream sent invalid trailer` / `trailer without end stream flag` | 上游 trait 帧协议违规 |
| 502 | `upstream sent frame for closed stream` / `prematurely closed stream` | 上游提前 RST_STREAM / 断裂 |
| 502 | `upstream rejected request with error %ui` / `goaway with error %ui` | 上游返回的 HTTP/2 错误码 |
| 504 | 无特殊日志，只有超时 | `grpc_read_timeout` / `grpc_send_timeout` 静默超时 |
| 502 | `upstream violated stream/connection flow control` | 上游突破流控窗口，属协议违规 |

> [!WARNING]
> 有一个流传很广的「常见日志」**在源码里不存在**：`upstream sent unsupported protocol version`（全树 grep 零命中），别写进排查表。
> 另外，如果服务端日志里出现疑似 gRPC 错误信息，那**不是 nginx 产生的**——nginx 不认识 `grpc-status`，它只会把 trailer 原样透传。此时应去看上游应用日志或直接用 `grpcurl` 验证后端。

### Relationship with proxy Module

三个模块是**三份独立源码**，但共享同一个上游配置结构 `ngx_http_upstream_conf_t`：

| 模块 | 协议 | 文件 |
| :-- | :-- | :-- |
| `ngx_http_proxy_module.c` | HTTP/1.x | 5469 行 |
| `ngx_http_grpc_module.c` | HTTP/2 | 5344 行 |
| `ngx_http_proxy_v2_module.c` | HTTP/2（通用 h2 代理） | 4314 行 |

grpc 与 proxy_v2 的函数名去掉前缀后大量同名（`parse_frame` / `parse_header` / `parse_fragment` / `create_request` / `send_window_update` / `parse_rst_stream`…），本质是同一套 HTTP/2 上游实现的两次演进——属**复制粘贴式演进**，维护上要留意两者的差异是刻意的还是漏改的。

### Pitfall List

1. **忘了 `http2 on`**。ALPN 不提供 h2，客户端静默退到 HTTP/1.1，然后各种 gRPC 语义问题接踵而来。
2. **以为 `proxy_pass` 能代 gRPC**。proxy 只懂 HTTP/1.x，做不到。
3. **想配 `grpc_request_buffering` / `grpc_buffering`**。不存在，两种缓冲都恒为 off。
4. **期待 `grpc_next_upstream http_500` 生效**。默认不含，而且应用级错误其实藏在 `grpc-status` trailer 里——nginx 看不到。
5. **用 `grpc-status != 0` 去触发 `error_page` 或重试**。做不到，nginx 不解析这个 trailer。
6. **长连接流用默认 60s 超时**。服务端流/双向流会被静默切断。
7. **指望 `client_max_body_size` 拦住大 gRPC 消息**。无 `Content-Length` 时该检查被跳过。
8. **上游用 HTTP/1.1 后端接 `grpc_pass`**。grpc 模块只发 HTTP/2，上游必须支持 h2c 或 h2。
9. **把 h2c 的 Upgrade 方式当可用路径**。只支持 prior knowledge。
10. **调试时不必猜**：直接用 `grpcurl -plaintext -v` 打后端，再用 `curl --http2-prior-knowledge` 区分是客户端还是上游问题。

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)
- [HTTP](/docs/CS/CN/nginx/HTTP.md) — 11 阶段与过滤链，`grpc_pass` 挂在 CONTENT 阶段
- [Upstream](/docs/CS/CN/nginx/upstream.md) — 负载均衡与重试状态机
- [HTTP/3](/docs/CS/CN/nginx/http3.md) — 面向客户端的另一个 HTTP 版本
- [TLS](/docs/CS/CN/nginx/tls.md) — 客户端侧 ALPN 与回源 TLS
- [Troubleshooting](/docs/CS/CN/nginx/troubleshooting.md) — 502/504 排查流程

## References

- <https://nginx.org/en/docs/http/ngx_http_grpc_module.html>
- <https://nginx.org/en/docs/http/ngx_http_v2_module.html>
- <https://nginx.org/en/docs/http/ngx_http_upstream_module.html>
- <https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-HTTP2.md>
- <https://github.com/fullstorydev/grpcurl>
