## Introduction

nginx 的 TLS 相关指令有 30 多条，散落在 `http`、`server`、`stream` 三个上下文里，而且很多默认值与直觉相反——`ssl_session_cache` 默认不是 `off` 是 `none`，`ssl_session_tickets` 默认**开**着，而 TLS 1.3 的会话**根本不会进 `ssl_session_cache shared:`**。

本文按「握手时发生了什么 → 会话怎么复用 → 证书与客户端验证 → 回源 TLS → 安全陷阱」的顺序展开，把默认值一次性列表。事实基于 **nginx 1.31.6** 源码（`src/event/ngx_event_openssl.c`、`src/http/modules/ngx_http_ssl_module.c`、`src/stream/ngx_stream_ssl_module.c`）。

## Default Values Summary Table

最容易写错的部分先给全（默认值都从 `ngx_command_t` 的默认值代码处核实）：

| 指令 | 默认值 | 备注 |
| :-- | :-- | :-- |
| `ssl_protocols` | **TLSv1.2 TLSv1.3** | TLSv1/1.1 **没有被移除**，仍可显式开启，只是默认关 |
| `ssl_ciphers` | `HIGH:!aNULL:!MD5` | |
| `ssl_prefer_server_ciphers` | **off** | |
| `ssl_session_cache` | **none** | 不是 `off`：`none` 声明支持复用但不真存（兼容老 Outlook Express），`off` 才是彻底禁用 |
| `ssl_session_tickets` | **on** | |
| `ssl_session_timeout` | 5m | |
| `ssl_buffer_size` | 16k | 影响流式响应的 TTFB |
| `ssl_verify_client` | off | 可选 off/on/optional/optional_no_ca |
| `ssl_verify_depth` | 1 | |
| `ssl_ecdh_curve` | auto | |
| `ssl_early_data` | **off** | 0-RTT 默认不开 |
| `ssl_stapling` / `ssl_stapling_verify` | off / off | |
| `ssl_ocsp` | off（off/on/leaf） | http 侧 1.19.0 引入，**不是** 1.27+；stream 侧 1.27.2 |
| `ssl_certificate_compression` | off | 1.29.1 引入 |
| `ssl_reject_handshake` | off | 1.19.4 引入 |
| `ssl_conf_command` | 无 | 1.19.4 引入，透传 OpenSSL 配置 |

源码里**不存在**的指令（常见于网上教程，别写）：

- `ssl_send_timeout` —— 全树无此指令
- http 侧没有 `ssl_handshake_timeout` —— 它**只在 stream 模块**（默认 60s）；http 侧握手超时复用 `client_header_timeout`
- `ssl_engine` 只能写在 **main 块**（属于 `ngx_openssl_module`），不能进 server

## Handshake Flow: How Non-blocking Is Implemented

http 侧握手入口在 `ngx_http_request.c:675` 的 `ngx_http_ssl_handshake()`（注意是 request.c，不在 ssl 模块里）：

1. `recv(fd, buf, 1, MSG_PEEK)` 窥探首字节：`0x80`（SSLv2）或 `0x16`（TLS）判定为 TLS，否则当明文 HTTP 处理
2. `ngx_ssl_create_connection()` 挂 SSL 结构
3. `ngx_ssl_handshake(c)` 驱动 `SSL_do_handshake()`

非阻塞的关键在 `ngx_ssl_handshake()`（`ngx_event_openssl.c:2201`）：

- `SSL_do_handshake()` 返回 1 → 替换 `c->recv/send` 为 SSL 版本，`c->ssl->handshaked = 1`
- 返回 `SSL_ERROR_WANT_READ/WRITE` → 把 `c->read/write->handler` 换成 `ngx_ssl_handshake_handler`，返回 `NGX_AGAIN`

**没有 while 循环死等**——靠 epoll 事件反复重入，握手期间同一 worker 可以继续处理其它连接。握手未完成时挂的是 `client_header_timeout`。

### SNI Certificate Selection

`ngx_http_ssl_servername()`（`ngx_http_request.c:886`）通过 client_hello 回调触发：

1. 校验 Host → `ngx_http_find_virtual_server()` 找 `server{}`
2. 命中后 **`SSL_set_SSL_CTX()` 热切换证书上下文**，并同步 verify/verify_depth，强制加 `SSL_OP_NO_RENEGOTIATION`
3. 未命中不报错，落到 default server；如果该 server 配了 `ssl_reject_handshake`，发 `SSL_AD_UNRECOGNIZED_NAME` 致命告警

`ssl_certificate` 支持多条指令（`set_str_array_slot`），**天然支持 ECDSA + RSA 双证书**，OpenSSL 按客户端能力挑选。1.15.9 起 `ssl_certificate` 支持变量（在 cert callback 里逐个求值路径再加载）。

### ALPN

`ngx_http_ssl_alpn_select()` 在 `http2 on` 时选 `h2`，否则 `http/1.1`；QUIC 监听选 `h3`。握手完成后用 `SSL_get0_alpn_selected()` 判定是否转入 HTTP/2。

## Session Reuse: Two Tables, TLS 1.3 Only Recognizes ticket

会话复用有两条路径，实现完全不同：

### session cache (ID Reuse)

`ssl_session_cache shared:SSL:10m;` 在共享内存里维护 红黑树（按 session id 的 CRC32 索引）+ expire 队列（`ngx_ssl_session_cache_t`，`ngx_event_openssl.h:187`）。插入、查找、过期清理全部在 `ngx_shmtx_lock` 内——**没有任何 volatile**，可见性靠锁（`volatile` 只用于时间缓存）。

关键行为（`ngx_ssl_new_session()`，`ngx_event_openssl.c:4384`）：

```c
#if (NGX_SSL_TLSv1_3 ...定义省略)
    if (SSL_version(ssl_conn) == TLS1_3_VERSION
        && SSL_session_reused(ssl_conn) == 0)
    {
        return 0;    /* TLS 1.3 且 tickets 开启：不进共享缓存 */
    }
#endif
```

**TLS 1.3 会话不进 `ssl_session_cache shared:`**——TLS 1.3 规范推荐 ticket 方式，nginx 直接跳过。所以 TLS 1.3 下配大 `shared:` zone 是空转。

### session tickets

`ssl_session_tickets` 默认 on。ticket key 的管理是陷阱重灾区：

- 加密**只用 `key[0]`**；解密遍历全部 3 个 key 尝试
- 非 `key[0]` 解密成功时返回 2 让 OpenSSL **重新签发**——这就是平滑轮换机制
- 自动轮换（`ngx_ssl_rotate_ticket_keys()`）**仅当用了共享 session cache**（1.23.2 起）
- **跨进程**：配了 `shared:` 后 key 存在共享内存，各 worker 一致；**跨重启不行**——key 是启动时 `RAND_bytes` 生成的，nginx 重启后所有已发 ticket 全部失效，客户端被迫完整握手
- 要跨重启保持一致，必须显式配 `ssl_session_ticket_key` 文件（48 字节 = AES-128，80 字节 = AES-256）

> [!WARNING]
> 「配了 `ssl_session_cache shared:` 就万事大吉」是错的：TLS 1.3 靠 ticket，ticket 靠 key 存活；不配 `ssl_session_ticket_key` 文件，每次 reload/重启都会制造一波全量重握手。

### 0-RTT（early data）

`ssl_early_data on`（默认 off）开启 TLS 1.3 0-RTT。**重放风险是真实的**：0-RTT 数据无防重放保证，攻击者可截获并重放请求。常见做法是只对幂等读开启，或配合 `proxy_add_header` 传 `$ssl_early_data` 让后端感知。

## Certificate and Client Verification

- `ssl_verify_client on|optional|optional_no_ca` + `ssl_client_certificate`（CA 信任链）+ `ssl_verify_depth`（默认 1）
- 客户端证书变量：`$ssl_client_s_dn`、`$ssl_client_issuer_dn`、`$ssl_client_serial`、`$ssl_client_verify`（`SUCCESS:...` 或 `FAILED:...`）、`$ssl_client_cert`（PEM，带 tab 缩进）
- `ssl_crl` 校验吊销列表；`ssl_ocsp on|leaf` 是 OCSP 方式的客户端证书校验（把客户端证书拿去 OCSP 查询）
- 无有效证书端口兜底：`ssl_reject_handshake on` 可直接拒绝握手（常用于 default server 显式拒绝未知 SNI）

### OCSP Stapling (Server Certificate)

`ssl_stapling on` 让 nginx 缓存 OCSP 响应并在握手中装订，客户端无需自行查询 CA：

- 默认从证书里的 OCSP URL 拉取；`ssl_stapling_responder` 可覆盖，`ssl_stapling_file` 指定本地缓存文件（reload 不丢）
- `ssl_stapling_verify on` 校验 OCSP 响应签名（需要 `ssl_trusted_certificate` 提供 issuer 链）
- 与 `ssl_ocsp` 的区别：**stapling 服务自己的证书，`ssl_ocsp` 校验客户端的证书**

## Origin TLS: proxy_ssl_*

| 指令 | 默认值 | 说明 |
| :-- | :-- | :-- |
| `proxy_ssl_session_reuse` | **on** | 但见下方说明 |
| `proxy_ssl_protocols` | TLSv1.2 TLSv1.3 | |
| `proxy_ssl_ciphers` | **`DEFAULT`** | 与 `ssl_ciphers`（`HIGH:!aNULL:!MD5`）**不同** |
| `proxy_ssl_server_name` | **off** | 默认不发 SNI，需要时手动开 |
| `proxy_ssl_verify` | **off** | **默认不校验上游证书**，公网回源建议开 |
| `proxy_ssl_verify_depth` | 1 | |
| `proxy_ssl_name` | upstream 的 Host | SNI 与证书校验的名字 |
| `proxy_ssl_certificate` | 无 | 客户端证书（mTLS 回源），1.21.0 起支持变量 |

上游 session 复用的作用域：`proxy_ssl_session_reuse on` 时 session 存在 **peer 结构体**里——

- 无 `zone`：`peer->ssl_session` 是 worker 内的指针，**每 worker 一份，不跨进程**
- 有 `zone`：`i2d_SSL_SESSION()` 序列化后进共享内存 slab，**跨 worker 共享**

所以「多 worker 都想复用上游会话」必须给 upstream 配 `zone`。session 大小上限 8192 字节（`NGX_SSL_MAX_SESSION_SIZE`），超限直接不存。

## Differences on stream Side

| 能力 | http | stream |
| :-- | :-- | :-- |
| TLS 终止（`ngx_stream_ssl_module`） | ✅ | ✅ 需 `--with-stream_ssl_module` |
| 不解密分流（`ssl_preread`） | ❌ | ✅，见 [stream](/docs/CS/CN/nginx/stream.md) |
| `ssl_handshake_timeout` | ❌ | ✅ 默认 60s |
| `ssl_alpn`（强制协商 ALPN） | ❌ | ✅ 1.21.4 起 |
| `ssl_buffer_size` / `ssl_early_data` | ✅ | ❌ |
| 其余指令 | — | 基本一致（stapling/ocsp 1.27.2 起进入 stream） |

## Security Pitfalls

1. **CVE-2026-90439**（1.31.6 修复，2026-09-15）：OpenSSL ≤ 3.5.0 + HTTP/3 配置下 worker 堆溢出。缓解：升级 1.31.6+，或 OpenSSL > 3.5.0，或关闭 HTTP/3。
2. **CVE-2026-40701**（1.31.0 修复）：`ssl_ocsp` 开启时 DNS 响应处理 use-after-free。
3. **ticket key 不持久化**：每次重启全量作废，见上文。
4. **`proxy_ssl_verify` 默认 off**：出公网的上游不校验证书等于明文传输信任模型。
5. **`ssl_prefer_server_ciphers` 默认 off**：由客户端选套件。TLS 1.3 下这条指令无意义（1.3 套件协商方式不同）。
6. **TLSv1/1.1 未移除**：显式写 `ssl_protocols TLSv1;` 仍然生效，安全基线要自己写死 `TLSv1.2 TLSv1.3`。

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md) — TLS/HTTP2/HTTP3 概览
- [stream](/docs/CS/CN/nginx/stream.md) — 不解密的 SNI 分流
- [Upstream](/docs/CS/CN/nginx/upstream.md) — 回源连接管理
- [Log](/docs/CS/CN/nginx/log.md) — `$ssl_*` 变量进日志
- [HTTP/3](/docs/CS/CN/nginx/http3.md)
- [gRPC](/docs/CS/CN/nginx/grpc.md) — `grpc_ssl_*` 回源 TLS

## References

- <https://nginx.org/en/docs/http/ngx_http_ssl_module.html>
- <https://nginx.org/en/docs/stream/ngx_stream_ssl_module.html>
- <https://wiki.openssl.org/index.php/TLS1.3>
