## Introduction

HTTP/3 是把 HTTP 语义搬到 **QUIC**（RFC 9000）之上的第三代 HTTP：传输层从 TCP 换成「UDP + 用户态可靠传输」，TLS 1.3 被内建进握手（RFC 9001），HTTP 的帧层变成 HTTP/3（RFC 9114）。

nginx 的实现在源码里分成两块，这个划分本身就说明了问题：

| 位置 | 内容 | 数量级 |
| :-- | :-- | :-- |
| `src/event/quic/` | **整套 QUIC 传输协议**：连接、流、包收发、ACK、丢包与拥塞控制、连接迁移、令牌、BPF 路由 | 30 个文件 |
| `src/http/v3/` | HTTP/3 语义层：QPACK 表、控制流、请求流解析、过滤模块 | 12 个文件 |

也就是说 nginx 没有把 QUIC 交给内核，而是**在 worker 里自己实现了可靠传输**——内核只负责 [UDP](/docs/CS/OS/Linux/net/UDP.md) 收发（`sendmsg`/`recvmsg` + `UDP_SEGMENT`），报文重组、ACK、重传、拥塞控制全在用户态。理解这一点，才能理解后面那些看起来奇怪的设计（为什么需要 eBPF、为什么没有 `backlog`、为什么 `listen ... quic` 与 `ssl` 互斥）。

模块自 **1.25.0** 引入，官方至今标注为 **experimental**：

- 不默认编译，需要 `--with-http_v3_module`；
- 依赖 OpenSSL ≥ 1.1.1，**0-RTT 需要 OpenSSL ≥ 3.5.1**（或 BoringSSL / LibreSSL / QuicTLS）；
- 1.29.1 之前，即使设了 `ssl_early_data`，用 OpenSSL 也无法启用 0-RTT；
- **不能在 Win32 平台构建**。

## Minimal Usable Configuration

官方示例的骨架（注意两行 `listen`）：

```nginx
http {
    log_format quic '$remote_addr - $remote_user [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent" "$http3"';

    access_log logs/access.log quic;

    server {
        # 为更好兼容性，官方建议 http/3 与 https 用同一端口
        listen 8443 quic reuseport;
        listen 8443 ssl;

        ssl_certificate     certs/example.com.crt;
        ssl_certificate_key certs/example.com.key;

        location / {
            # 用于对外宣告 HTTP/3 可用
            add_header Alt-Svc 'h3=":8443"; ma=86400';
        }
    }
}
```

三个必须记住的点：

1. **`quic` 与 `ssl` 必须写成两条 `listen`**。源码里 `listen ... quic` 与下列参数全部互斥，配在一起直接报错：`ssl`、`http2`、`backlog`、`fastopen`、`accept_filter`、`deferred`、`so_keepalive`、`proxy_protocol`、`multipath`。原因是 QUIC 的 TLS 在用户态完成，不需要 TCP 的 backlog/accept 机制，也不接受 PROXY protocol 与 TCP keepalive。
2. **`Alt-Svc` 不会自动添加**，必须自己 `add_header`。浏览器只有在见过 `Alt-Svc` 之后才会尝试 h3，所以「升级到 h3 慢」通常不是协议慢，而是宣告没做对。
3. **日志里用 `$http3` 判断协议**（取值 `h3` / `hq` / 空串），别想着复用 `$server_protocol`。

## Directives and Defaults

| 指令 | 上下文 | 默认值 | 说明 |
| :-- | :-- | :-- | :-- |
| `http3 on \| off` | http, server | **`on`** | 启用 HTTP/3 协商。默认是开，但**只有 `listen ... quic` 的 server 才真的用到**；要彻底禁用就显式 `off` |
| `http3_hq on \| off` | http, server | `off` | 启用 HTTP/0.9 over QUIC（`hq`），仅用于 QUIC 互操作测试 |
| `http3_max_concurrent_streams n` | http, server | `128` | 单连接最大并发请求流数；同时也是 `max_blocked_streams` 与 QUIC 双向流上限的取值来源 |
| `http3_stream_buffer_size size` | http, server | `64k` | 读写 QUIC 流所用缓冲区大小 |
| `quic_active_connection_id_limit n` | http, server | `2` | 服务端保存的**客户端**连接 ID 上限（QUIC transport parameter） |
| `quic_retry on \| off` | http, server | `off` | 启用地址验证：发 `Retry` / `NEW_TOKEN`、校验 `Initial` 中的令牌。防放大攻击，代价是多一次 RTT |
| `quic_gso on \| off` | http, server | `off` | 用 UDP_SEGMENT 做批量发送优化（仅 Linux） |
| `quic_host_key file` | http, server | —— | 加密无状态重置与地址验证令牌的密钥；**不配则每次 reload 随机生成，旧令牌全部失效** |
| `quic_bpf on \| off` | main | `off` | 用 eBPF 做 QUIC 包路由，支持连接迁移；**仅 Linux 5.7+** |

`quic_host_key` 与 `quic_bpf` 这两条最容易被忽略：前者影响 reload 后已签发令牌的存活，后者是连接迁移能不能工作的前置条件。

## How QUIC Connections Look in nginx

`ngx_quic_connection_t`（`src/event/quic/ngx_event_quic_connection.h`）的字段基本对应 RFC 9000 的概念模型：

```c
struct ngx_quic_connection_s {
    uint32_t                    version;

    ngx_quic_path_t            *path;

    ngx_queue_t                 sockets;
    ngx_queue_t                 paths;          /* 迁移可能产生多条路径 */
    ngx_queue_t                 client_ids;
    ngx_queue_t                 free_sockets;
    ngx_queue_t                 free_paths;
    ngx_queue_t                 free_client_ids;

    ngx_uint_t                  nsockets;
    ngx_uint_t                  nclient_ids;
    uint64_t                    max_retired_seqnum;
    uint64_t                    client_seqnum;
    uint64_t                    server_seqnum;
    uint64_t                    path_seqnum;

    ngx_quic_tp_t               tp;             /* 本端 transport parameters */
    ngx_quic_tp_t               ctp;            /* 对端 transport parameters */

    ngx_quic_send_ctx_t         send_ctx[NGX_QUIC_SEND_CTX_LAST];
    ngx_quic_keys_t           *keys;
    ngx_quic_conf_t           *conf;

    ngx_event_t                 push;
    ngx_event_t                 pto;            /* Probe Timeout：丢包检测 */
    ngx_event_t                 close;
    ngx_event_t                 path_validation;
    ngx_event_t                 key_update;
    ...
    ngx_quic_congestion_t       congestion;
};
```

几个值得注意的地方：

- **`send_ctx[]` 而不是一条发送队列**。QUIC 按加密层级分开发送上下文（Initial / Handshake / 0-RTT / Application），每个上下文有自己的包号空间、自己的「待发 / 已发待 ACK」队列和 crypto 数据流。这是 HTTP/2 的 TCP 单一序列完全不同的地方：**某个包丢了只阻塞它所在的上下文**。
- **`paths` 与 `client_ids` 是队列**。连接迁移就是「同一条连接新增/切换 path」；`client_seqnum` / `server_seqnum` 用于 `NEW_CONNECTION_ID` 与 `RETIRE_CONNECTION_ID` 的序号管理，连接 ID 最大长度 `NGX_QUIC_CID_LEN_MAX = 20`。
- **定时器是一组 `ngx_event_t`**：`push`（有数据要发）、`pto`（探测定时器，等价于丢包重传的触发点）、`close`、`path_validation`、`key_update`（密钥更新）。它们挂在 nginx 原有的定时器红黑树上，与 TCP 的超时重传完全不同的实现路径。
- **拥塞控制内置**：`ngx_quic_congestion_t` 里有 `ssthresh`、`w_max`、`w_est`、`w_prior`、`k` 这些字段，是典型的 **CUBIC** 状态量；`in_flight` / `window` 与 `mtu` 决定发送窗口。这也意味着 QUIC 的拥塞行为完全由 nginx 决定，不受内核 net.ipv4.tcp_congestion_control 影响。
- **连接对象挂在连接上**：`ngx_connection_t` 上有 `quic:1` 位标志与 `ngx_quic_stream_t *quic` 字段，QUIC 流复用 nginx 的 connection 抽象，所以 HTTP/3 的请求仍然走同一套 `ngx_http_request_t` 生命周期，只是底层连接不是 socket。

## Multi-worker and Connection Migration: Why eBPF Is Needed

HTTP/1.1 与 HTTP/2 下，一个 TCP 连接由内核按四元组哈希分给某个 worker，之后**永远属于那个 worker**。QUIC 不同：客户端可以在连接存续期间换 IP/端口（连接迁移），而 **QUIC 连接的身份是 Connection ID，不是四元组**。

于是「哪个包该交给哪个 worker」不能靠四元组解决。nginx 的答案是 eBPF：

```c
/* src/event/quic/ngx_event_quic_bpf.c */
if (ls[i].quic && ls[i].reuseport) {
    ...
}
```

- 建一张 `BPF_MAP_TYPE_SOCKHASH` 映射，键取 Connection ID 的 **cookie**，值是对应的 UDP socket；
- 把 eBPF 程序通过 `SO_ATTACH_REUSEPORT_EBPF` 挂到监听 socket 的 reuseport 组上，由内核在分发数据包时就按 Connection ID 选定 socket（也即选定 worker）；
- 热升级时用环境变量 `NGINX_BPF_MAPS` 把 map 的 fd 传给新 master（与监听 fd 通过 `NGINX` 环境变量传递是同一套思路，见 [nginx 的 Reload 与热升级](/docs/CS/CN/nginx/nginx.md?id=reload-configuration-replacement-without-service-interruption)）。

所以 `quic_bpf on` 不只是性能开关，**它是连接迁移能正确工作的关键**：没有它，迁移过的连接的数据包可能落到错误的 worker。

> [!WARNING]
> 连接迁移也是攻击面。1.31.0 修了 CVE-2026-40460：处理连接迁移时，新 QUIC 流可能在地址验证之前就收到新的客户端地址，造成**地址伪造**。同一版本还加了「限制 QUIC 无状态重置包的大小与速率」。1.31.6 进一步规定：**在 SSL 连接中收到的 QUIC transport parameters 扩展一律忽略**（`Change`），避免两套传输参数来源互相干扰。

## 0-RTT and Address Validation

| 机制 | 开启方式 | 代价 |
| :-- | :-- | :-- |
| 地址验证（Retry / NEW_TOKEN） | `quic_retry on` | 首次连接多一次 RTT，换掉放大攻击风险 |
| 0-RTT（early data） | `ssl_early_data on` + OpenSSL ≥ 3.5.1 | **有重放风险**：0-RTT 数据可被攻击者录制后重放 |

0-RTT 的可用性与 OpenSSL 版本强绑定（1.29.1 之前用 OpenSSL 根本开不起来），且 `quic_host_key` 不配置时 reload 会让已下发的令牌失效，「0-RTT 时通时不通」往往就是这里。

对 0-RTT 的正确态度是**只放行幂等操作**：nginx 提供 `$ssl_early_data` 变量，可以把「这是重放过的早期数据」这个事实传给上游：

```nginx
proxy_set_header Early-Data $ssl_early_data;
```

上游据此对 0-RTT 请求做限制（例如拒绝 POST、只允许读接口）。这与 HTTP/1.1 时代的 TLS 会话复用不是一回事，不能套用旧结论。

## Security and Version Baseline

HTTP/3 是 nginx 近两年 CVE 的集中区，选版本时值得单独看：

| 版本 | 内容 |
| :-- | :-- |
| 1.31.6（2026-09-15） | **CVE-2026-90439**：HTTP/3 + OpenSSL ≤ 3.5.0 时 worker 可能出现堆缓冲区溢出 |
| 1.31.2 | CVE-2026-42530：`ngx_http_v3_module` 的 use-after-free |
| 1.31.0 | CVE-2026-40460：HTTP/3 连接迁移导致的地址伪造 |

实践结论：**开 HTTP/3 就必须跟到最新的 mainline/stable 补丁版本**，并且同时升级 OpenSSL —— 1.31.6 的这枚 CVE 同时涉及 nginx 与 OpenSSL 两侧。

## Boundary with stream, HTTP/2

- **stream 侧不支持 QUIC**：`src/stream/` 下没有 quic / v3 相关实现。也就是说 **UDP 上的 HTTP/3 只能由 `http` 模块的 v3 提供**，`stream` 的 UDP 代理只是普通的数据报转发。别指望用 `stream` 给 QUIC 做四层代理再交给后端 `http`，那需要真正的 QUIC 感知转发。
- **HTTP/2 与 HTTP/3 可以同时开**：同端口上 `listen 443 ssl; listen 443 quic reuseport;`，前者承载 h2/h1.1，后者承载 h3；用 `$server_protocol` 与 `$http3` 分别观测。
- **`http3_hq` 只在互操作测试里有意义**，生产不要开。

## Debugging and Observability

```nginx
log_format h3 '$remote_addr $http3 $server_protocol $status '
              '$request_time $bytes_sent "$request"';
```

- `$http3` 是判断连接是否真的走了 QUIC 的唯一官方变量；
- 客户端侧用 `curl --http3 -v https://example.com/`（需要支持 h3 的 curl）或浏览器 DevTools 的 Protocol 列；
- 抓包看 UDP 443 是否有流量，是最直接的「到底有没有走 QUIC」验证；
- error_log 里 `quic` 开头的告警（如连接 ID 相关、令牌校验失败）通常指向 `quic_host_key` 与 `quic_retry` 的配置问题。

## Common Pitfalls

1. **`listen ... quic` 与 `ssl`/`http2`/`backlog`/`proxy_protocol` 等写在同一行**——配置直接报错，必须拆成两条 `listen`。
2. **忘了 `add_header Alt-Svc`**——客户端永远不知道 h3 可用，测出来「h3 没生效」。
3. **`http3 on` 是默认值**，但只在 quic 监听上生效；反过来在纯 TCP 站点看到 `http3 on` 不用惊讶。
4. **`quic_host_key` 不配**——每次 reload 随机生成，旧令牌失效，0-RTT/地址验证行为随之抖动。
5. **`quic_bpf` 只在 Linux 5.7+ 有效**，容器里可能因缺少 BPF 权限而静默退化为「所有 worker 都能收到包」。
6. **`http3_max_concurrent_streams` 默认 128**，高并发小请求场景会比 h2 更早触顶，需要与 `http3_stream_buffer_size` 一起调。
7. **UDP 侧没有 `listen backlog` 可调**，内核 UDP 接收缓冲需要系统级参数调整，容量规划不能照搬 TCP。
8. **把 h3 当作「性能银弹」**——它优化的是建连与丢包恢复，不是吞吐；对短连接密集的场景收益最大，对已有长连接的大文件传输可能不如 h2。
9. **只升级 nginx 不升级 OpenSSL**——1.31.6 的 CVE 修的是两侧的组合问题。

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)
- [HTTP](/docs/CS/CN/nginx/HTTP.md)
- [TLS](/docs/CS/CN/nginx/tls.md)
- [Event](/docs/CS/CN/nginx/event.md)
- [stream](/docs/CS/CN/nginx/stream.md)
- [gRPC](/docs/CS/CN/nginx/grpc.md) — 上游 HTTP/2 与客户端 HTTP/2 的区别

## References

1. [Module ngx_http_v3_module](https://nginx.org/en/docs/http/ngx_http_v3_module.html)
2. [nginx CHANGES（1.31.x 安全公告与变更）](https://nginx.org/en/CHANGES)
3. [RFC 9000 — QUIC: A UDP-Based Multiplexed and Secure Transport](https://datatracker.ietf.org/doc/html/rfc9000)
4. [RFC 9001 — Using TLS to Secure QUIC](https://datatracker.ietf.org/doc/html/rfc9001)
5. [RFC 9114 — HTTP/3](https://datatracker.ietf.org/doc/html/rfc9114)
6. [ngx_http_ssl_module — ssl_early_data](https://nginx.org/en/docs/http/ngx_http_ssl_module.html#ssl_early_data)
