## Introduction

nginx 在安全链路里通常是最外层的那一段：它先于业务代码接触请求，也先于业务代码被扫描和攻击。这篇笔记按**请求从外到内的顺序**整理 nginx 自身能做的防护，以及每项防护在源码里的真实语义。

先给一张分层图，后面每一节对应一层：

| 层 | 能做的事 | 主要手段 |
| :-- | :-- | :-- |
| 传输层 | 只允许安全协议、双向认证 | `ssl_protocols`、`ssl_verify_client`、`ssl_crl`（见 [TLS](/docs/CS/CN/nginx/tls.md)） |
| 连接层 | 限制连接数与速率、限制请求头/体大小与时间 | `limit_conn`、`limit_req`、`client_header_*`、`client_body_*` |
| 身份层 | IP 黑白名单、Basic 认证、外置鉴权 | `allow`/`deny`、`auth_basic`、`auth_request` |
| 内容层 | 防盗链、签名 URL、路径隔离、方法限制 | `valid_referers`、`secure_link`、`internal`、`limit_except` |
| 响应层 | 隐藏版本与内部信息 | `server_tokens`、`error_page`、响应头裁剪 |
| 外挂层 | 规则级攻击检测 | ModSecurity + CRS、Coraza、NAXSI |

> [!NOTE]
> 一条贯穿全篇的原则：**nginx 侧的安全配置是「减少暴露面」，不是「识别攻击」**。真正的攻击识别（SQL 注入、XSS、反序列化）需要规则引擎，nginx 只能做到把请求大小、速率、来源、协议约束住。

## Access Control: allow / deny

```nginx
location /admin/ {
    allow 10.0.0.0/8;
    allow 192.168.1.1;
    deny  all;
}
```

语义要点（都来自 `ngx_http_access_module.c`）：

- 规则**按书写顺序求值，第一条匹配的规则决定结果**，因此 `deny all;` 必须写在最后；
- 匹配发生在 **ACCESS 阶段**，用的是 `r->connection->sockaddr` —— 也就是**直连对端的地址**。位于 CDN / 负载均衡之后时，这里是代理的 IP，必须先用 `realip` 模块或 PROXY protocol 还原真实客户端地址（见 [stream](/docs/CS/CN/nginx/stream.md?id=proxy-protocol-two-directions-must-be-distinguished)）；
- 支持 IPv4、IPv6、CIDR、`unix:` 域套接字，IPv4-mapped IPv6 地址会被折回 IPv4 规则比较；
- `deny` 命中即返回 **403**。

### Semantics of satisfy

多个 ACCESS 阶段的检查器（`access`、`auth_basic`、`auth_request`）之间由 `satisfy` 决定组合方式：

| 值 | 含义 |
| :-- | :-- |
| `all`（**默认**，源码 `NGX_HTTP_SATISFY_ALL`） | 所有检查器都要通过 |
| `any` | 任一通过即放行 |

于是有两种典型组合：

```nginx
# 内网直连免密，外部走 Basic 认证
satisfy any;
allow 10.0.0.0/8;
deny  all;
auth_basic "restricted";
auth_basic_user_file /etc/nginx/htpasswd;
```

判定的细节在于**检查器的返回值语义**：ACCESS 阶段返回 `NGX_OK` 表示「授权通过，可以停止后续检查」，返回 `NGX_DECLINED` 表示「我不表态，交给下一个」——所以 `satisfy any` 才可能被 `allow` 提前放行。

另一个容易忽略的指令是 `auth_delay`（默认 `0`）：认证失败时强制延迟一段时间再回 401，用来抬高在线爆破的成本。

## Identity Layer: Three Types of Authentication

| 方式 | 适用 | 特点 |
| :-- | :-- | :-- |
| `auth_basic` | 内部工具、临时保护 | 账密存在文件里，凭据每次请求都发（必须走 HTTPS），无法登出 |
| `auth_request` | 对接公司统一鉴权、JWT/OAuth 校验 | 每请求一个子请求，鉴权逻辑可放在任意后端服务里 |
| 客户端证书（mTLS） | 服务间、IoT、强身份 | 在握手阶段完成，见 [TLS](/docs/CS/CN/nginx/tls.md) |

### auth_basic

```nginx
location /internal/ {
    auth_basic           "restricted";
    auth_basic_user_file /etc/nginx/conf.d/.htpasswd;
}
```

- 用户文件是 **htpasswd 格式**，由 `htpasswd`、`openssl passwd` 之类生成；
- 认证成功后 `$remote_user` 可用，适合写进日志与传给上游（`proxy_set_header X-User $remote_user;`）；
- `auth_basic off;` 可以在子 location 里关闭父级的继承——这个「用 off 覆盖继承」的写法是 nginx 的通用模式，很多指令都支持。

### auth_request: Externalize Authorization

`auth_request` 在 ACCESS 阶段发起一个**子请求**去鉴权服务，然后按子请求的状态码决定主请求的命运。源码里的判定逻辑（`ngx_http_auth_request_handler`）非常明确：

| 子请求状态 | 主请求结果 |
| :-- | :-- |
| 2xx | 放行，继续执行后续阶段 |
| **401** | 返回 401，并把子请求的 `WWW-Authenticate` 头**复制**给客户端 |
| **403** | 返回 403 |
| 其他 | 返回 **500**，同时 error_log 记录 `auth request unexpected status: <n>` |

最后一行是排障关键词：**看到 500 而不是 401/403，先去看这个日志**——通常是鉴权服务返回了 3xx、404 或 502。

```nginx
location /api/ {
    auth_request     /auth;
    auth_request_set $user   $upstream_http_x_user;
    auth_request_set $tenant $upstream_http_x_tenant;

    proxy_set_header X-User   $user;
    proxy_set_header X-Tenant $tenant;
    proxy_pass http://backend;
}
```

`auth_request_set` 的价值在于：**子请求的响应头变量默认只存在于子请求里**，必须显式回填到主请求的变量才能供后面的 `proxy_set_header` 使用。这是「鉴权通过但上游拿不到用户信息」的常见原因。

> [!TIP]
> 鉴权服务的延迟会被**叠加**在每次请求上。要么给鉴权接口加缓存，要么用 `auth_request` 之外的手段（如 njs 的 `js_access` + `ngx.shared` 做本地令牌校验，见 [njs](/docs/CS/CN/nginx/njs.md)）。

## Content Layer: Hotlink Protection and Signed URL

### Hotlink Protection: valid_referers

```nginx
location ~* \.(jpg|png|mp4)$ {
    valid_referers none blocked server_names
                   *.example.com ~\.google\.;

    if ($invalid_referer) { return 403; }
}
```

| 写法 | 含义 |
| :-- | :-- |
| `none` | 完全没有 Referer 头（直接访问、部分客户端） |
| `blocked` | Referer 存在但被脱敏（如只剩 scheme） |
| `server_names` | 当前 server 的 `server_name` 集合 |
| `*.example.com` | 通配主机名 |
| `~正则` | 正则匹配 |
| `referer_hash_max_size` / `referer_hash_bucket_size` | 开启 `server_names` 时的匹配哈希表容量 |

**Referer 由客户端提供、可随意伪造**，所以它只能防「别人网站热链你的资源」，不能当访问控制。真正的资源保护要靠 `secure_link` 或带签名的 URL。

### Signed URL: Two Modes of secure_link

**模式一：新式（推荐），`secure_link` + `secure_link_md5`**

```nginx
location /download/ {
    secure_link            $arg_st;
    secure_link_md5        "$arg_e$uri secret";

    if ($secure_link = "") { return 403; }
    if ($secure_link = "0") { return 410; }   # 已过期
}
```

`$secure_link` 的取值来自源码（`ngx_http_secure_link_module.c`）：

| 值 | 含义 |
| :-- | :-- |
| `"1"` | 签名正确且未过期 |
| `"0"` | 签名正确但**已过期**（源码用 `expires && expires < ngx_time()` 判定） |
| 空（not_found） | 签名不匹配 |

因此可以给过期和伪造**两种不同的响应**（410 vs 403），这对 CDN 与下载站的用户体验很重要。`$secure_link_expires` 变量可把过期时间暴露出来。

**模式二：旧式，`secure_link_secret`**——把密钥拼进 URI 做 md5 前缀（`/prefix/hash/uri`），变量值为去掉前缀后的真实 URI。现在只建议在兼容老系统时使用。

笔记里特意分开写，是因为这两种模式**不能同时配**，且旧式在各类文章中常被当作「secure_link 的唯一用法」。

## Size and Time: The Most Effective Defense

多数「一轮就把服务打挂」的攻击，靠的不是漏洞而是**未设上限**。这几个默认值必须知道：

| 指令 | 默认值 | 作用 |
| :-- | :-- | :-- |
| `client_max_body_size` | `1m` | 请求体上限，超出 → **413**；上传接口记得调，其余接口别乱调 |
| `client_body_buffer_size` | `2 * page_size`（通常 8k） | 请求体在内存里缓冲的大小，超出后落盘到 `client_body_temp_path` |
| `client_header_buffer_size` | `1k` | 单个请求头的初始缓冲 |
| `large_client_header_buffers` | `4 8k` | 大请求头（uri + 单个 header）的缓冲；**单个 header 超过 8k 会 414/400** |
| `max_headers` | `1000`（1.31.0 新增） | 请求头条目数量上限，防「海量小 header」型攻击 |
| `client_header_timeout` | `60s` | 读完整请求头的超时 |
| `client_body_timeout` | `60s` | 读请求体的超时（两次读之间） |
| `send_timeout` | `60s` | 向客户端写响应的超时（两次写之间） |
| `keepalive_timeout` | `75s` | 空闲长连接保持时间 |
| `limit_rate` / `limit_rate_after` | 不限 | 响应速率限制（对下载场景） |
| `reset_timedout_connection` | `off` | 超时后是否直接 RST 并丢弃缓冲，防「僵尸连接」占内存 |
| `lingering_close` | `on`（`lingering_time` 30s、`lingering_timeout` 5s） | 关闭前尝试读完客户端剩余数据 |

### Slow Attack (Slowloris / Slow POST)

原理都是「每次只送一点点，让服务端为这条连接长时间保活」。对应的防线：

```nginx
# 头部慢：client_header_timeout 管住
client_header_timeout 10s;

# 正文慢：client_body_timeout 管住，并限制缓冲落盘
client_body_timeout 10s;
client_max_body_size 10m;
client_body_buffer_size 128k;

# 连接数维度：单 IP 并发连接上限
limit_conn_zone $binary_remote_addr zone=perip:10m;
limit_conn perip 20;

# 速率维度：漏桶 + burst/nodelay
limit_req_zone $binary_remote_addr zone=req:10m rate=10r/s;
limit_req zone=req burst=20 nodelay;
limit_req_status 429;      # 默认 503
limit_conn_status 429;     # 默认 503
```

两个提示：

- `limit_req` / `limit_conn` 的**默认状态码都是 503**，对客户端（和监控）不友好，建议统一改成 429；
- `limit_req_dry_run` 可以先「只记录不拦截」，用来观察真实阈值再上线规则。

漏桶参数（`burst` / `nodelay` / `delay=`）的详细语义见 [nginx 的限流一节](/docs/CS/CN/nginx/nginx.md?id=rate-limiting-and-throttling)。

## Response Layer: Say Less

### server_tokens

源码里 `server_tokens` 只有三个取值，`off` 的**确切效果容易被误解**：

```c
static u_char ngx_http_server_string[]       = "Server: nginx" CRLF;
static u_char ngx_http_server_full_string[]  = "Server: " NGINX_VER CRLF;
static u_char ngx_http_server_build_string[] = "Server: " NGINX_VER_BUILD CRLF;
```

| 值 | 实际发出的头 |
| :-- | :-- |
| `on`（默认） | `Server: nginx/1.31.6` |
| `build` | `Server: nginx/1.31.6 <编译信息>` |
| `off` | `Server: nginx` |

也就是说 **`off` 只是去掉版本号，`Server` 头依然存在**（错误页脚注里的版本也会消失）。想彻底不发这个头，得用 `more_set_headers`（headers-more 模块）或改源码。

### Other Information Leakage Points

- 默认错误页底部会打印 `nginx` 与版本，`server_tokens off` 会一并处理；
- `X-Powered-By`、`X-AspNet-Version` 之类来自上游，需要在 nginx 侧裁掉：`proxy_hide_header X-Powered-By;`；
- `$upstream_addr`、`$upstream_status` 等变量写进响应头等于暴露内网拓扑，别随手 `add_header` 回传。

## Path and File: Two Classic Traps

### Path Traversal of root + alias

只要配置写成 `alias` 少一个斜杠，就可能让 `..` 逃出目录：

```nginx
# 错误：/files/../etc/passwd 会拼成 /var/wwwetc/passwd 或更糟
location /files {
    alias /var/www/files/;
}

# 正确：location 与 alias 的结尾斜杠一一对应
location /files/ {
    alias /var/www/files/;
}
```

相关默认值：`merge_slashes on`（合并重复斜杠，配合规范化路径）、`disable_symlinks off`（默认允许跟随软链接，敏感目录建议 `disable_symlinks on;`）、`internal`（把 location 标记为只能内部跳转/子请求访问，用于保护 `/status`、`/auth` 这类端点）。

### Spoofing and Method Limiting

```nginx
# 只允许必要方法
limit_except GET HEAD {
    deny all;
}

# 反代场景：把上游不认识的 OPTIONS/TRACE 直接掐掉
if ($request_method !~ ^(GET|HEAD|POST|PUT|DELETE|OPTIONS)$) {
    return 405;
}
```

`limit_except` 里的 `allow`/`deny` 语法与 ACCESS 阶段一致，但**只能写在 location 内**。

## Add-on Layer: WAF

nginx 生态里的三套主流方案，定位差异很大：

| 方案 | 形态 | 规则模型 | 适合 |
| :-- | :-- | :-- | :-- |
| ModSecurity v3 + OWASP CRS | `libmodsecurity` + `nginx` connector，动态模块 | 黑名单 + 异常评分（`SecRule`） | 需要成熟规则集、合规要求 |
| Coraza | Go 实现的 WAF 引擎，可作为 nginx 模块/独立代理 | 兼容 ModSecurity 规则（SecLang） | 不想引入 C 依赖、要可移植 |
| NAXSI | 原生 nginx 模块 | 白名单（未知字符/模式即拦） | 简单站点、强输入约束 |

ModSecurity 一侧的当前版本（2026-10 核实）：

- 引擎 `libmodsecurity` **3.0.16**，connector **1.0.4**；
- 规则集 OWASP CRS **4.29.0**（2026-09-24），LTS 为 **4.25.1**；
- **CRS 3.3.x 的支持窗口在 2026 Q3 关闭**，新部署不要再选 3.x 分支；
- 镜像方案（`owasp/modsecurity-crs:nginx`）省去编译，但 tag 是浮动的，生产应固定版本号。

上线流程必须是**两段式**：先 `SecRuleEngine DetectionOnly` 观察一段时间，把误杀规则加进排除列表，再切 `SecRuleEngine On`。直接开拦截是 WAF 落地的头号翻车点。

另外注意 WAF 在链路上的**位置**：它看到的是 nginx 已经解析过的请求，因此它不能替代 nginx 自身的大小/速率限制；反过来，如果 WAF 部署在 nginx 之后（比如保护上游应用），前面对客户端的限流仍要由 nginx 承担。

## An Easily Overlooked Risk: Don't Configure Yourself as an Open Proxy

nginx 1.31.0 引入了 `ngx_http_tunnel_module`（`tunnel_pass`），把 HTTP 正向代理/CONNECT 隧道能力做进了官方模块。这带来一类新的事故模式：**配置里出现一个没有访问控制的转发 location，就等于对公网开放了一个代理**——攻击者用它跳板、隐藏来源、消耗带宽。

任何 `tunnel_pass`、`proxy_pass` 到外部域名、或 `resolver` + 变量拼 URL 的配置，都应配 `allow`/`deny` 或 `auth_request` 收口。

## Common Pitfalls

1. **`deny all;` 写在 `allow` 之前**——后面的规则永远不会被求值。
2. **在代理后面用 `allow`/`deny` 判断客户端 IP**——拿到的是代理 IP，必须先配 `realip`。
3. **以为 `server_tokens off` 会去掉 `Server` 头**——只去版本，头还在。
4. **`auth_request` 返回 500**——去看 error_log 的 `auth request unexpected status`，一般是鉴权服务返回了非 2xx/401/403。
5. **子请求里的变量在上游看不到**——必须 `auth_request_set` 回填。
6. **改了 `limit_req_status` 却没改 `limit_conn_status`**，或者反过来；两者默认都是 503。
7. **`client_max_body_size` 全局改大**——上传接口单独放开，其他 location 保持默认。
8. **`large_client_header_buffers` 调大但不看 `connection_pool_size`**——源码强制前者 size ≥ 后者，否则启动报错。
9. **`secure_link` 与 `secure_link_secret` 同时配**——两种模式互斥，必须选一种。
10. **用 WAF 替代应用层校验**——规则集是概率性的，参数化查询、输出编码这些基本功仍然要做。

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)
- [Configuration](/docs/CS/CN/nginx/config.md)
- [TLS](/docs/CS/CN/nginx/tls.md)
- [Upstream](/docs/CS/CN/nginx/upstream.md)
- [njs](/docs/CS/CN/nginx/njs.md)
- [Troubleshooting](/docs/CS/CN/nginx/troubleshooting.md)

## References

1. [Module ngx_http_access_module](https://nginx.org/en/docs/http/ngx_http_access_module.html)
2. [Module ngx_http_auth_request_module](https://nginx.org/en/docs/http/ngx_http_auth_request_module.html)
3. [Module ngx_http_secure_link_module](https://nginx.org/en/docs/http/ngx_http_secure_link_module.html)
4. [Module ngx_http_referer_module](https://nginx.org/en/docs/http/ngx_http_referer_module.html)
5. [ModSecurity-nginx connector](https://github.com/owasp-modsecurity/ModSecurity-nginx)
6. [OWASP Core Rule Set](https://coreruleset.org/)
7. [nginx 源码：src/http/ngx_http_header_filter_module.c、modules/ngx_http_*](https://nginx.org/download/nginx-1.31.6.tar.gz)
