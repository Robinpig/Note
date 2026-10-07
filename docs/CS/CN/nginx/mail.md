## Introduction

nginx 的代码树里有**三套并列的代理框架**：`http{}` 做七层、`stream{}` 做四层，还有一套几乎没人提的 `mail{}`——代理 SMTP / POP3 / IMAP。它默认不编译，要显式 `--with-mail`；文档少、示例少、第三方模块少，属于典型的「存在但边缘」。

但它的架构价值恰恰在于「不像 nginx」：`http` 与 `stream` 都是「配置 + 阶段/内容处理链」的**通用引擎**（可插拔 handler、phase 数组、变量体系），而 `mail` 是**三个写死的协议状态机 + 一个把认证外包给外部 HTTP 服务的反向代理**。源码里 `src/mail/` 全目录 grep `_phase` / `run_phases` **零命中**——它连阶段引擎都没有，所有分支都编译进 `switch (s->mail_state)`。

理解这一点，就能理解它为什么用的人少：nginx 自己**不读任何口令、不投递、不存储邮件**，它只能「认证 + 转发」，而认证必须由你自己写一个 HTTP 后端来接。没有那个后端，mail 配置直接报错起不来。

本文基于 **nginx 1.31.6** 源码（`src/mail/` 共 17 个文件、10795 行）逐条核实。

> [!WARNING]
> 本文多处结论与流传说法相反，其中最典型的是：`auth_http` 的响应**根本不看 HTTP 状态码**（源码里解析状态行的函数直接把 `HTTP/...` 读到 CRLF 丢掉），行为**只由 `Auth-Status` 响应头决定**。

### Quick Start

mail 模块默认**不编译**，配置它需要：

```bash
./configure --with-mail --with-mail_ssl_module    # TLS 还要 mail_ssl
```

一个最小的 SMTP 认证代理（`auth_http` 是**必需**的，缺失时配置直接报错）：

```nginx
mail {
    server_name  mail.example.com;
    auth_http    http://127.0.0.1:9000/auth;      # 唯一认证入口，不可省
    auth_http_timeout 5s;
    max_errors   5;

    server {
        listen     25;
        protocol   smtp;                          # 不写则按端口自动识别
        smtp_auth  login plain;
        proxy      on;
        proxy_timeout 1m;
    }
}
```

认证流程是：客户端连上 → nginx 与它完成 SMTP 的 EHLO/AUTH 协商 → nginx 把凭据用一个 HTTP 请求发给 `auth_http` → 后端返回 `Auth-Status: OK` 与上游地址 → nginx 拿这组凭据登录真实邮件服务器，之后纯字节对拷。

### Module Map and Compile Switches

| 文件 | 职责 |
| :-- | :-- |
| `ngx_mail.c` | 配置解析、`listen` 处理、把 `ls->handler` 指向 `ngx_mail_init_connection` |
| `ngx_mail_handler.c` | 连接入口、会话建立、SSL、命令读取、收尾、日志 |
| `ngx_mail_{smtp,pop3,imap}_handler.c` | 三个协议的状态机 |
| `ngx_mail_{smtp,pop3,imap}_module.c` | 各协议的指令与默认值 |
| `ngx_mail_auth_http_module.c` | **核心**：把认证委派给 HTTP 服务 |
| `ngx_mail_proxy_module.c` | 认证成功后的上游连接与双向对拷 |
| `ngx_mail_ssl_module.c` | mail 侧 TLS（含 `starttls`） |
| `ngx_mail_realip_module.c` | 只处理 PROXY protocol 来源改写 |

编译开关在 `auto/options`：`MAIL=NO`（**默认关**）、`MAIL_SSL=NO`，而 `MAIL_POP3/IMAP/SMTP=YES` 表示协议子模块默认全开。所以 `--with-mail` 是最小要求，TLS 另加 `--with-mail_ssl_module`；也可以 `--without-mail_pop3_module` 之类单独裁掉协议。

mail 与 http/stream 共享的只有 core 层设施——`ngx_mail.h` 的 include 就四行：`ngx_config.h` / `ngx_core.h` / `ngx_event.h` / `ngx_event_connect.h`。也就是说它复用 `ngx_connection_t`、`ngx_event_t`、内存池、`ngx_cycle_t`、`ngx_listening_t`、`ngx_resolver_t`、`ngx_ssl_t`，但**不共享** conf 结构、阶段数组、变量引擎与 rewrite。

### Session Model

每个连接对应一个 `ngx_mail_session_t`（`ngx_mail.h:188`）。与 http 的 `ngx_http_request_t` 相比，它出奇地扁平——**没有三协议联合体**，所有字段共用：

```c
typedef struct {
    uint32_t                signature;   /* "MAIL" */
    ngx_connection_t       *connection;
    ngx_str_t               out;         /* 待发缓冲（协议回包都写这里） */
    ngx_buf_t              *buffer;
    void                  **ctx;         /* 每模块上下文数组 */
    void                  **main_conf;
    void                  **srv_conf;
    ngx_resolver_ctx_t     *resolver_ctx;
    ngx_mail_proxy_ctx_t   *proxy;
    ngx_uint_t              mail_state;  /* 状态机当前位置 */

    unsigned                ssl:1;
    unsigned                protocol:3;  /* POP3=0 / IMAP=1 / SMTP=2 */
    unsigned                blocked:1;
    unsigned                quit:1;
    unsigned                auth_method:3;
    unsigned                auth_wait:1;

    ngx_str_t               login;       /* 不是 auth_user */
    ngx_str_t               passwd;
    ngx_str_t               salt;        /* APOP / CRAM-MD5 挑战 */
    ngx_str_t               tag;         /* IMAP 的 a001 类标签 */
    ngx_str_t               host;        /* 客户端反查主机名（SMTP 用） */
    ngx_str_t               smtp_helo, smtp_from, smtp_to;
    ngx_str_t               cmd;
    ngx_uint_t              command, errors, login_attempt;
    /* 命令解析用 */
    ngx_uint_t              state, literal_len;
    u_char                 *tag_start, *cmd_start, *arg_start;
} ngx_mail_session_t;
```

注意几个容易写错的点：登录名/密码字段叫 `login`/`passwd`（**不是** `auth_user`/`auth_passwd`），发件收件叫 `smtp_from`/`smtp_to`，认证方式是一个 3 位位域 `auth_method` 而非 `method`，而 `addr_conf` 只是连接入口的**局部变量**（用来挑出 `ctx->main_conf/srv_conf`），并不存在 session 里。客户端证书也不落在 session 上，只在组装 `auth_http` 请求时用 `ngx_ssl_get_*` 临时取出。

**协议不是运行期协商出来的，而是配置期按端口决定的**。`ngx_mail_core_module.c:352` 遍历所有 mail 模块，把 `protocol->port[]` 与该 `listen` 的端口比对，命中就把它设为 `cscf->protocol`：

```c
for (i = 0; module->protocol->port[i]; i++) {
    if (module->protocol->port[i] == u.port) {
        cscf->protocol = module->protocol;
        break;
    }
}
```

三个协议的默认端口表是：SMTP `{25, 465, 587}`、POP3 `{110, 995}`、IMAP `{143, 993}`。端口只是「自动识别」的线索，不是保留位——在任意端口上显式写 `protocol smtp;` 一样能跑。运行期只是 `s->protocol = cscf->protocol->type;`。

连接建立流程（`ngx_mail_handler.c`）：

1. `ngx_mail_init_connection()` 从 `c->listening->servers` 里按本地地址找出 `addr_conf`，分配 session，`c->data = s`，把连接日志 handler 换成 `ngx_mail_log_error`；
2. 若该 `listen` 开了 `proxy_protocol`，`rev->handler = ngx_mail_proxy_protocol_handler`（先 `recv(MSG_PEEK)` + `ngx_proxy_protocol_read()` 剥离 PROXY 头，再跑 realip），否则直接进 `ngx_mail_init_session_handler`；
3. `ngx_mail_init_session_handler()` 里只有一句话的分支：`s->ssl` 为真则先 `ngx_mail_ssl_init_connection()` 做握手，否则直接 `ngx_mail_init_session()`；
4. `ngx_mail_init_session()` 分配 ctx 数组、把写 handler 设为 `ngx_mail_send`，然后 `cscf->protocol->init_session(s, c)` 进入具体协议状态机。

**没有 `ngx_mail_handler()`、没有 `ngx_mail_core_run_phases()`、没有 `ngx_mail_finalize_session()`**——这些都是按 http/stream 的习惯推想出来的名字，源码里不存在。收尾是 `ngx_mail_close_connection()`（SSL shutdown → 计数减 → `ngx_destroy_pool`）与 `ngx_mail_session_internal_server_error()`。

### Three Protocol State Machines

三套状态枚举各自独立（`ngx_mail.h:136-178`），命名是**小写前缀** `ngx_smtp_*` / `ngx_pop3_*` / `ngx_imap_*`（命令码才是大写的 `NGX_SMTP_HELO` 之类）：

```c
typedef enum {
    ngx_smtp_start = 0, ngx_smtp_auth_login_username,
    ngx_smtp_auth_login_password, ngx_smtp_auth_plain,
    ngx_smtp_auth_cram_md5, ngx_smtp_auth_external,
    ngx_smtp_helo, ngx_smtp_helo_xclient, ngx_smtp_helo_auth,
    ngx_smtp_helo_from, ngx_smtp_xclient, ngx_smtp_xclient_from,
    ngx_smtp_xclient_helo, ngx_smtp_xclient_auth,
    ngx_smtp_from, ngx_smtp_to
} ngx_smtp_state_e;
```

SMTP 的主干是 `ngx_mail_smtp_auth_state()` 里一个 `switch (s->mail_state)`，再嵌一层 `switch (s->command)` 分发 HELO/EHLO/AUTH/MAIL/RCPT/STARTTLS/QUIT。POP3 与 IMAP 同构（`ngx_mail_pop3_auth_state` / `ngx_mail_imap_auth_state`），只是命令集不同。读命令统一走 `ngx_mail_read_command()` → `protocol->parse_command`，认证成功一律 `NGX_DONE` → `ngx_mail_auth()` → `ngx_mail_auth_http_init()`。

各协议的问候语与错误回包也**各不相同**，这是最容易写错表格的地方：

| 场景 | SMTP | POP3 | IMAP |
| :-- | :-- | :-- | :-- |
| 问候语 | `220 <server_name> ESMTP ready` | `+OK POP3 ready` | `* OK IMAP4 ready` |
| 内部错误 | `451 4.3.2 Internal server error` | `-ERR internal server error` | `* BAD internal server error` |
| 证书错误 | `421 4.7.1 SSL certificate error` | `-ERR SSL certificate error` | `* BYE SSL certificate error` |
| 缺必需证书 | `421 4.7.1 No required SSL certificate` | `-ERR No required SSL certificate` | `* BYE No required SSL certificate` |
| 登录失败（默认） | `535 5.7.0 <msg>` | `-ERR <msg>` | `<tag> NO <msg>` |

只有 **SMTP 的问候语带 `server_name`**；POP3 的问候语是固定字符串，IMAP 也是。`server_name` 未配时取 `cf->cycle->hostname`。

认证方法的可选值三协议并不通用：

- `smtp_auth`：`plain` / `login` / `cram-md5` / `external` / `none`，**默认 `plain + login`**。注意 `apop` **只在 POP3 有**。
- `pop3_auth`：`plain` / `apop` / `cram-md5` / `external`（**没有 `login`、没有 `none`**），默认 `plain`；但源码里有个特殊处理——只要启用了 `plain`，就会自动补上 `login`。
- `imap_auth`：`plain` / `login` / `cram-md5` / `external`，默认 `plain`。

其它默认值：`smtp_client_buffer` / `imap_client_buffer` 均为 `ngx_pagesize`，`smtp_greeting_delay` 为 `0`，`pop3_capabilities` 默认 `TOP USER UIDL`，`imap_capabilities` 默认 `IMAP4 IMAP4rev1 UIDPLUS`。

### auth_http: Outsource Authentication

这是 mail 模块里唯一有真正设计感的部分。`auth_http <url>` 只接受 **http**（源码里只剥 `http://` 前缀，不认 https），默认端口 80，支持 AF_UNIX。

nginx 发出的请求是**固定格式的 `GET`**（无 body），由 `ngx_mail_auth_http_create_request()` 逐行拼出。可出现的头如下：

| 头 | 条件 | 说明 |
| :-- | :-- | :-- |
| `Host` | 总是 | AF_UNIX 时为 `localhost` |
| `Auth-Method` | 总是 | `plain` / `apop` / `cram-md5` / `external` / `none` |
| `Auth-User` / `Auth-Pass` | 总是 | 经 `ngx_mail_auth_http_escape` 转义 |
| `Auth-Salt` | APOP / CRAM-MD5 且 salt 非空 | 挑战值 |
| `Auth-Protocol` | 总是 | `smtp` / `pop3` / `imap` |
| `Auth-Login-Attempt` | 总是 | 本连接第几次尝试 |
| `Client-IP` / `Client-Host` | 后者需反查成功 | 反查失败填 `[UNAVAILABLE]` / `[TEMPUNAVAIL]` |
| `Proxy-Protocol-Addr` / `-Port` / `-Server-Addr` / `-Server-Port` | 连接来自 PROXY protocol 时 | 真实四元组 |
| `Auth-SMTP-Helo` / `-From` / `-To` | `Auth-Method: none` 时 | |
| `Auth-SSL` / `-Protocol` / `-Cipher` | 走了 TLS | |
| `Auth-SSL-Verify` / `-Subject` / `-Issuer` / `-Serial` / `-Fingerprint` | `ssl_verify_client` 开启时 | |
| `Auth-SSL-Cert` | `auth_http_pass_client_cert on` | **头名是 `Auth-SSL-Cert`，不是 `X-Client-Cert`** |
| 自定义行 | `auth_http_header` | 原样附加 |

响应侧**只认这些头，其余一律忽略**：

| 响应头 | 语义 |
| :-- | :-- |
| `Auth-Status: OK` | 认证通过，继续处理其它头 |
| `Auth-Status: WAIT` | 稍后重试（置 `s->auth_wait`，睡完 `Auth-Wait` 秒后重跑认证） |
| `Auth-Status: <其它值>` | 该值直接作为错误消息回给客户端 |
| `Auth-Server` | 上游地址（**必需**，缺失即 internal error，没有默认值） |
| `Auth-Port` | 上游端口（1..65535，同样必需） |
| `Auth-User` / `Auth-Pass` | 覆盖客户端提交的凭据（做账号映射用） |
| `Auth-Wait` | 秒数；为 0 则立即断开，否则延迟后重试 |
| `Auth-Error-Code` | 覆盖 SMTP 的错误码前缀（默认 `535 5.7.0`） |

**HTTP 状态码完全不参与决策**。负责读状态行的是 `ngx_mail_auth_http_ignore_status_line()`——名字就说明了态度：把 `HTTP/...` 读到 CRLF 丢掉，既不解析也不分支。所以「返回 401 就拒绝、返回 500 就重试」这类设计**在 mail 里行不通**，后端必须老老实实按 `Auth-Status` 协议应答。

`auth_http_timeout` 默认 **60000 ms**，`auth_http_pass_client_cert` 默认 **off**。另外 `resolver` 指令**不是给 `auth_http` 用的**——`auth_http` 的地址在配置期由 `ngx_parse_url` 解析完成；`resolver` 只被 SMTP 用，作用是把客户端 IP 反查成 `Client-Host`。

### Proxy and Forwarding

认证通过后进入 `ngx_mail_proxy_init()`：建立到上游的连接，然后按协议把凭据「再登一次」（POP3 发 `USER`/`PASS`、IMAP 发 `LOGIN`、SMTP 发 `AUTH PLAIN`），成功后统一切到 `ngx_mail_proxy_handler()` 做双向 `recv/send` 对拷。

指令与默认值：

| 指令 | 默认 | 说明 |
| :-- | :-- | :-- |
| `proxy` | `off` | ⚠️ 值是**只写不读**的——全目录只有赋值点，没有读取点，实际是**历史遗留 / no-op** |
| `proxy_timeout` | **24 小时** | 认证完成后客户端方向的静默超时 |
| `proxy_buffer` | `ngx_pagesize` | 不是固定 4k/4k，随页大小 |
| `proxy_pass_error_message` | `off` | 开则把上游非法应答原样转发给客户端 |
| `xclient` | **`on`** | SMTP 专用，向上游发 `XCLIENT ADDR=... LOGIN=... NAME=...` |
| `proxy_smtp_auth` | `off` | 向上游发 `AUTH PLAIN` |
| `proxy_protocol` | `off` | 给上游发 PROXY protocol，值可为 `off`/`on`/`v2` |

`proxy_protocol`（**发**给上游）与 `listen ... proxy_protocol`（**收**客户端给的）是两个不同指令，别混。发送实现 `ngx_mail_proxy_send_proxy_protocol()` 要求一次性写完全部头，否则报错。

### TLS

mail 的 TLS 有一个 http 没有的指令：**`starttls`**，三态 `off` / `on` / `only`：

- `off`：不支持 `STARTTLS`/`STLS`（按明文跑，或只接受 `listen ... ssl` 的隐式 TLS）；
- `on`：广告 `STARTTLS` 能力，客户端可选择升级；
- `only`：必须先 `STARTTLS` 才允许认证。

其余 ssl 指令与 http 侧同名同义：`ssl_certificate`、`ssl_certificate_key`、`ssl_password_file`、`ssl_certificate_compression`、`ssl_dhparam`、`ssl_ecdh_curve`、`ssl_protocols`、`ssl_ciphers`、`ssl_prefer_server_ciphers`、`ssl_session_cache`、`ssl_session_tickets`、`ssl_session_ticket_key`、`ssl_session_timeout`（默认 300）、`ssl_verify_client`、`ssl_verify_depth`（默认 1）、`ssl_client_certificate`、`ssl_trusted_certificate`、`ssl_crl`、`ssl_conf_command`。

**mail 侧缺失的（与 http/stream 对比）**：

- 无 `ssl_stapling*`——**OCSP stapling 在 mail 里不存在**；
- 无 `ssl_reject_handshake`、无 `ssl_buffer_size`、无 `ssl_handshake_timeout`、无 `ssl_early_data`；
- **无 `ssl_preread`**（那是 stream 的独立模块）、无 `ssl_alpn` 指令；
- **无任何 SSL 变量**（`$ssl_*` 一个都没有，mail 连变量引擎都没有）；
- `ssl_certificate` 虽支持多证书，但不支持按变量动态取。

ALPN 由协议自身的 `protocol->alpn` 给出（`"\x04smtp"` / `"\x04pop3"` / `"\x04imap"`），选择逻辑硬编码在 `ngx_mail_ssl_alpn_select()` 里，不可配。

### realip and max_errors

`ngx_mail_realip_module` 只提供一条指令 `set_real_ip_from`。它**没有** `real_ip_header`、也没有 `real_ip_recursive`（http 侧都有），因为 mail 只认 PROXY protocol 这一个来源：`c->proxy_protocol` 非空且源地址落在 CIDR 内才改写 `c->sockaddr`/`addr_text`，**不支持 `X-Forwarded-For`**。

`max_errors` 默认 **5**，是 mail 唯一的防暴破内建机制：命令解析失败（`NGX_MAIL_PARSE_INVALID_COMMAND`）时 `s->errors++`，达到阈值打日志 `client sent too many invalid commands` 并置 `s->quit = 1`。**真正的登录失败重试控制在 `auth_http` 后端手里**（靠 `Auth-Wait` 与 `Auth-Status: WAIT`）。

### Logs: mail Has No Access Log

`src/mail/` 目录下**没有 log 模块**，没有 `access_log`、没有 `log_format`、也没有任何变量。唯一的日志指令是 **`error_log`**（默认继承 `cf->cycle->new_log`）。

请求级日志由 `ngx_mail_log_error()` 拼装，格式固定为：

```
while <动作>, client: <ip>, server: <addr>[, login: "..."][, upstream: ...]
```

所以要统计「谁在什么时候登录了几个邮箱」，只能从后端 `auth_http` 服务自己记，或者解析 error_log。

### Systematic Differences from http / stream

| 维度 | http | stream | mail |
| :-- | :-- | :-- | :-- |
| 调度模型 | 11 阶段 phase 引擎 | 7 阶段 | **协议状态机（无阶段）** |
| 内容路由 | `location` + `server_name` 五层匹配 | 只有 `listen` | 只有 `listen` + `protocol` |
| 变量体系 | 完整（`$remote_addr`…） | 独立一套 | **没有** |
| rewrite | 有 | 无 | 无 |
| 访问日志 | `access_log` | `access_log`（须显式格式名） | **无（只有 error_log）** |
| 认证 | auth_basic / auth_request / JWT | 无 | **只能 auth_http 外置** |
| 端口复用 | 可与 stream 冲突（`-t` 不报） | 同左 | **必须独占**（独立 listen 解析，不合并） |
| 编译 | 默认开 | `--with-stream` | `--with-mail` |
| upstream | 完整算法族 | 另一套实现 | **无 upstream 概念**，单上游由 auth_http 指定 |

mail 的 `listen` 参数也更少：只有 `bind` / `backlog` / `rcvbuf` / `sndbuf` / `ipv6only` / `multipath` / `ssl` / `so_keepalive` / `proxy_protocol`——**没有 `reuseport`、没有 `udp`、没有 `fastopen`、没有 `deferred`**。

> [!NOTE]
> 同一 `addr:port` 若同时被 http/stream 与 mail 声明，mail 侧的 listen 不参与 http/stream 的 server 合并，双方各自 `bind()`，最终在 `ngx_open_listening_sockets()` 阶段以 `EADDRINUSE` 失败（`nginx -t` 不会拦下这个冲突）。**mail 端口必须独占。**

### Pitfall List

1. **没配 `auth_http` 就直接 `nginx -t` 报错**。这是硬约束，不是建议——mail 没有本地用户库的概念。
2. **指望 `auth_http` 后端用 HTTP 状态码表达结果**。源码忽略状态码，必须用 `Auth-Status` 头。返回 401/500 一律被当成「认证失败但没给消息」，最终走向 internal error。
3. **忘返 `Auth-Server` + `Auth-Port`**。两者任一缺失都报 internal error，没有「默认上游」这回事。
4. **`proxy on` / `proxy off` 以为能开关代理**。该值被写进配置结构后**从未被读取**，是死配置。
5. **在 `smtp_auth` 里写 `apop`**，或在 `pop3_auth` 里写 `login`/`none`——都不是合法值，`nginx -t` 会拒绝。
6. **以为 mail 有 `access_log`**。没有，登录审计必须由 `auth_http` 后端负责。
7. **想在 mail 里用 `ssl_preread` 或 OCSP stapling**。都不存在。
8. **把 `listen ... proxy_protocol` 和 `proxy_protocol on` 当同一件事**。前者收、后者发，方向相反。
9. **以为 `resolver` 会影响 `auth_http` 地址解析**。不会，那是配置期 `ngx_parse_url` 干的；`resolver` 只用于 SMTP 的客户端反查。
10. **忘了 `max_errors` 的实际语义**。它数的是「非法命令」，不是「登录失败」，别拿它当防撞库闸门。

### When It's Worth Using

一句话判断：**你已经在 MTA / IMAP 服务前面，需要一个「先查后端、再转发」的 POP3/IMAP/SMTP 前置层，且已经有 HTTP 鉴权服务**——这时 mail 模块很合适（尤其 IMAP/POP3 前面做统一鉴权 + 分片选后端）。

反之，只要你想做任何一件 nginx 原生不支持的事（会话保持的特殊策略、per-user 限速、审计日志、动态证书、OCSP），它立刻就会变成负担。这也是它在现实中长期被 HAProxy（四层也能做，且日志与观测更强）或直接在 MTA 层做鉴权取代的技术原因。

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)
- [stream](/docs/CS/CN/nginx/stream.md) — 另一种「平行实现」，对照看差异
- [Configuration](/docs/CS/CN/nginx/config.md) — http 的配置体系与变量（mail 全都没有）
- [TLS](/docs/CS/CN/nginx/tls.md) — http 侧 TLS 全貌
- [Log](/docs/CS/CN/nginx/log.md) — 为什么 mail 只有 error_log
- [Troubleshooting](/docs/CS/CN/nginx/troubleshooting.md) — 日志关键字与状态码

## References

- <https://nginx.org/en/docs/mail/ngx_mail_core_module.html>
- <https://nginx.org/en/docs/mail/ngx_mail_auth_http_module.html>
- <https://nginx.org/en/docs/mail/ngx_mail_proxy_module.html>
- <https://nginx.org/en/docs/mail/ngx_mail_ssl_module.html>
- <https://nginx.org/en/docs/mail/ngx_mail_smtp_module.html>
- <https://nginx.org/en/docs/mail/ngx_mail_imap_module.html>
