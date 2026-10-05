## Introduction

排障 nginx 的固定路径：**先看 access_log 的状态码分布，再到 error_log 找关键字，最后落到系统指标**。状态码告诉你「谁的问题」，error_log 关键字告诉你「什么问题」，本篇把两者整理成对照表，并给典型故障的处理剧本。

## nginx 特有状态码

nginx 自己定义的一组状态码（`src/http/ngx_http_request.h:114`），不会返回给客户端（除了 444 的行为效果），主要出现在日志里：

| 码 | 宏 | 含义 |
| :-- | :-- | :-- |
| **444** | `NGX_HTTP_CLOSE` | 不回响应直接断开连接（`return 444` 常用于丢弃扫描流量） |
| **494** | `NGX_HTTP_REQUEST_HEADER_TOO_LARGE` | 请求头过大（`large_client_header_buffers` 装不下） |
| **495** | `NGX_HTTPS_CERT_ERROR` | HTTPS：客户端证书校验失败 |
| **496** | `NGX_HTTPS_NO_CERT` | HTTPS：需要客户端证书但没提供 |
| **497** | `NGX_HTTP_TO_HTTPS` | 明文 HTTP 请求发到了 HTTPS 端口 |
| **499** | `NGX_HTTP_CLIENT_CLOSED_REQUEST` | **客户端在 nginx 回响应前主动断开**（典型：上游太慢，客户端/网关先超时） |

499 的触发点（`ngx_http_request.c:3347`）：`ngx_http_finalize_request(r, NGX_HTTP_CLIENT_CLOSED_REQUEST)`——读请求或等响应过程中发现 `read->eof` 且请求未完成。499 扎堆基本等于「上游慢」的旁证：客户端忍不了先走了。若不想要这个噪音，用 `log_format` 的 `if=` 或 `map $status` 过滤。

## 错误日志关键字对照表

每条都核实过 1.31.6 源码出处：

| error_log 关键字 | 出处 | 原因与方向 |
| :-- | :-- | :-- |
| `upstream prematurely closed connection while reading response header` | `ngx_http_upstream.c` | 上游**建连成功后**提前断开：上游进程崩了、上游对 keepalive 超时（RST）、长连接池拿到的死连接。检查上游日志与 `proxy_http_version`/keepalive 配置 |
| `no live upstreams while connecting to upstream` | `ngx_http_upstream.c` | 该 upstream 组里**所有节点都处于 fail 状态**（被动健康检查全踢）。检查是否 `max_fails=1` 太激进、后端是否真挂了 |
| `connect() failed (111: Connection refused) while connecting to upstream` | 同上（errno 拼接） | 上游端口没监听、进程挂了、防火墙 |
| `upstream timed out (110: Connection timed out)` | 同上 | connect 超时：上游不可达/过载；若发生在读响应阶段则是 `proxy_read_timeout` 不够 |
| `client intended to send too large body` | `ngx_http_request.c` | 413，`client_max_body_size` 不够 |
| `accept4() failed (24: Too many open files)` | `ngx_event_accept.c` | worker 的 fd 用尽。调 `worker_rlimit_nofile` 与 systemd `LimitNOFILE`，nginx 会主动暂停 accept 一段时间 |
| `bind() to 0.0.0.0:80 failed (98: Address already in use)` | `ngx_connection.c` | 端口被占：另一个 nginx、或 http 与 stream 配了同一端口（**`nginx -t` 不报这个错**，见 [stream 陷阱](/docs/CS/CN/nginx/stream.md?id=陷阱清单)） |
| `worker process exited on signal 11` | `ngx_process_cycle.c` | 段错误。开 core dump + `debug_points abort` 抓现场；常见嫌疑：第三方模块、动态模块签名不匹配 |
| `reconfiguring` / `signal process started` | `ngx_process.c` / `ngx_cycle.c` | 正常 reload 流程日志，不是错误 |
| `reopening logs` | `ngx_process_cycle.c` | USR1 日志重开，配合 logrotate |
| `SSL_do_handshake() failed (SSL:...)` | `ngx_event_openssl.c` | 握手失败：证书链不全、协议/套件不匹配、SNI 没选对 server |
| `could not allocate new session` / slab 相关 | `ngx_slab` | 共享内存 zone 满：调大 `ssl_session_cache`/`limit_req_zone`/`keys_zone` |
| `upstream sent too big header while reading response header` | `ngx_http_upstream.c` | 上游响应头超 `proxy_buffer_size`，调大它 |

## 典型故障剧本

### 502：upstream prematurely closed

出现顺序通常是：上线后 502 激增 → error_log 里 `previously closed` → 大概率是 **upstream keepalive 拿到了已被上游关掉的连接**（上游的 keepalive timeout 比 nginx 短，或中间 LB 空闲超时更短）。排查顺序：

1. 上游是否真实存活（`curl` 直打）
2. 上游 keepalive 空闲超时 vs nginx `keepalive_timeout`（upstream 块内）
3. 中间是否有 LB/防火墙静默 RST 空闲连接
4. 若集中在 reload 后瞬间：新 worker 起来前旧 worker 已关监听，重试参数兜底

### 499 扎堆 + 504

`$upstream_response_time` 分布长尾 → 上游慢。区分三种慢：`$upstream_connect_time` 大 = 建連慢（握手/网络）；`$upstream_header_time` 大 = 上游处理慢；两者都小但 `$request_time` 大 = nginx 自己的收发慢（缓冲、限速、网络）。

### Too many open files

```bash
# 看 worker 实际限制
cat /proc/$(pgrep -o nginx)/limits | grep open
# 看 nginx 消耗
ls /proc/$(pgrep -o nginx)/fd | wc -l
```

公式：`worker_rlimit_nofile ≥ worker_connections × 2 + 常规开销`（客户端连接 + 上游连接各占一份，还有日志/缓存 fd）。改完 reload 生效；systemd 环境同时改 `LimitNOFILE`。

### worker exited on signal 11（段错误）

```bash
ulimit -c unlimited
sysctl -w kernel.core_pattern=/tmp/core.%p
# nginx.conf
worker_rlimit_core  100m;
working_directory   /tmp;
debug_points abort;      # 到达错误点就 abort 生成 core，便于 gdb 挂载
```

先怀疑顺序：动态模块签名（configure 参数变过）→ 第三方模块 → 官方 bug（查 CHANGES 是否已修复版本）。

### 段错误之外的「配置不生效」

大量「不报错但不生效」属于语义性陷阱，索引页在 [Configuration 的陷阱清单](/docs/CS/CN/nginx/config.md?id=陷阱清单)：数组型指令覆盖、变量缓存、`if` 的 weirdness 等。确认配置真实生效用 `nginx -T`（展开全部 include 后的完整配置）。

## 诊断命令速查

```bash
nginx -t                      # 语法检查（不检查端口占用！）
nginx -T                      # 输出展开后的完整配置
nginx -s reload|quit|reopen   # HUP/QUIT/USR1
ss -tanp | grep :443 | awk '{print $1}' | sort | uniq -c   # 连接状态分布
ss -tan state established '( dport = :8080 )' | wc -l      # 上游连接数
curl -s 127.0.0.1/stub_status  # Active connections / accepted / handled / requests / Reading Writing Waiting
```

`stub_status` 三个数字的关系：`Reading + Writing` 是正在处理的，`Waiting` 是空闲长连接。`Waiting` 高不是问题（keepalive 正常表现），`Active` 贴着 `worker_connections` 才要处理。

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md) — Debug 一节：编译期与运行期开关
- [Log](/docs/CS/CN/nginx/log.md) — 日志机制与结构化输出
- [Upstream](/docs/CS/CN/nginx/upstream.md) — 重试状态机与超时矩阵
- [Practice](/docs/CS/CN/nginx/practice.md) — 变更与发布的预防性操作
- [stream](/docs/CS/CN/nginx/stream.md) — 四层侧的错误语义
- [security](/docs/CS/CN/nginx/security.md)

## References

- <https://nginx.org/en/docs/debugging_log.html>
- <https://nginx.org/en/docs/http/ngx_http_stub_status_module.html>
