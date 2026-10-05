## Introduction

njs（NGINX JavaScript）是 nginx 官方维护的一个 ECMAScript 解释器，以**两个动态模块**的形式提供：

- `ngx_http_js_module` —— 在 HTTP 请求处理链里执行 JS：内容生成、访问控制、访问日志变量、请求/响应头与响应体过滤；
- `ngx_stream_js_module` —— 在四层 stream 会话里执行 JS。

它和 OpenResty 的定位差别在于「边界」：njs 只覆盖 nginx 自身的阶段钩子（handler / filter / variable / periodic），语言是 ES5.1 严格模式为基线 + 部分 ES6+ 扩展的子集；而 OpenResty 是完整的 LuaJIT 运行时，能任意加载 C 扩展、跑复杂业务。**要做的只是「在 nginx 的框架内嵌一小段逻辑」时，njs 的代价远低于引入 OpenResty**。

两个模块都是动态模块，可以 `load_module` 挂到任意受支持的 nginx 上，**不需要重新编译 nginx**：

```nginx
# main 上下文，必须在 events 之前
load_module modules/ngx_http_js_module.so;
load_module modules/ngx_stream_js_module.so;
```

> [!WARNING]
> **1.31 时代最重要的一条变化：njs 自带的 `njs` 引擎已被弃用。**
> njs 1.0.0（2026-06-23）宣布「deprecating the njs engine in favor of QuickJS」，`js_engine` 的默认值却仍是 `njs`（见官方文档）。也就是说**默认配置跑在已弃用的引擎上**，新配置应显式选择 `qjs`。
> 另外 njs 1.0.1（2026-09-02）修了 `js_access` 的**访问控制绕过**（CVE-2026-18329，异步读请求体 continuation 抛异常时 nginx 会当作校验通过，该问题由 0.9.9 引入）——用 njs 做鉴权的部署必须确认版本不低于 1.0.1。

## 指令体系

按「作用」而不是按字母顺序看，njs 的指令分四类。

### 加载与作用域

| 指令 | 上下文 | 说明 |
| :-- | :-- | :-- |
| `js_import module.js;` / `js_import name from module.js;` | http, server, location | 标准写法（0.7.7 起支持 server/location 级）；用 `export default` 或具名导出 |
| `js_include file;` | http | **已废弃**（0.4.0 废弃、0.7.1 移除），见到就改 `js_import` |
| `js_path path;` | http, server, location | 追加模块搜索路径 |
| `js_preload_object name.json;` | http, server, location | 配置期预加载**不可变**对象，免去运行期解析 JSON 的开销 |
| `js_load_http_native_module path [as name];` | main | 加载原生共享库给 JS 调用，**仅 QuickJS 引擎** |

### 挂到请求处理链上

| 指令 | 生效位置 | 是否可异步 |
| :-- | :-- | :-- |
| `js_content module.func;` | CONTENT 阶段（等价于 `clcf->handler`） | 是 |
| `js_access module.func;` | ACCESS 阶段 | 是（可用 `r.subrequest()` / `ngx.fetch()` / `setTimeout()`） |
| `js_header_filter module.func;` | 响应头过滤链 | **否**，必须同步返回 |
| `js_body_filter module.func [buffer_type=string\|buffer];` | 响应体过滤链 | **否** |
| `js_set $var module.func [nocache];` | 变量取值时（懒执行） | **否** |
| `js_var $var [value];` | 声明可写变量 | —— |
| `js_periodic module.func [interval=] [jitter=] [worker_affinity=]` | location，在 worker 里周期执行 | 是 |

「是否可异步」这条边界是实际写代码时最容易踩的：**过滤器和 `js_set` 要求立即出结果**，所以里面不能 `await ngx.fetch()`；只有 `js_content` / `js_access` / `js_periodic` 能挂起等 IO。

### 共享状态与运行时

| 指令 | 默认值 | 说明 |
| :-- | :-- | :-- |
| `js_shared_dict_zone zone=name:size [timeout=] [type=string\|number] [evict] [state=file];` | —— | 跨 worker 共享的键值字典（http 上下文）；`state=file` 可把字典持久化到磁盘并在 reload/重启后恢复 |
| `js_engine njs \| qjs;` | `njs` | **选引擎；`njs` 已弃用，新配置用 `qjs`** |
| `js_context_reuse number;` | `128` | QuickJS 专属：可复用的 JS 上下文池大小 |

### Fetch API（模块内发起 HTTP 请求）

`ngx.fetch()` 是 njs 自己的 HTTP 客户端，不经过 nginx 的连接池，因此每个请求都会单独建连（`js_fetch_keepalive` 默认为 `0`，即关闭缓存）。相关指令及其默认值：

| 指令 | 默认值 |
| :-- | :-- |
| `js_fetch_buffer_size` | `16k` |
| `js_fetch_max_response_buffer_size` | `1m` |
| `js_fetch_timeout` | `60s` |
| `js_fetch_verify` | `on` |
| `js_fetch_verify_depth` | `100` |
| `js_fetch_protocols` | `TLSv1 TLSv1.1 TLSv1.2`（不含 TLSv1.3，需要时显式加） |
| `js_fetch_ciphers` | `HIGH:!aNULL:!MD5` |
| `js_fetch_keepalive` | `0` |
| `js_fetch_keepalive_requests` | `1000` |
| `js_fetch_keepalive_time` | `1h` |
| `js_fetch_keepalive_timeout` | `60s` |
| `js_fetch_trusted_certificate` / `js_fetch_proxy` | —— |

默认协议列表里没有 TLSv1.3、默认不做连接复用，这两条决定了「用 njs 调外部 API」的真实开销，需要时都得起手就配。

## 对象模型

### `r` —— 请求对象

HTTP 侧的处理器都接收一个 `r`：

| 类别 | 成员 |
| :-- | :-- |
| 读请求 | `r.method`、`r.uri`、`r.args`、`r.httpVersion`、`r.headersIn`、`r.remoteAddress`、`r.variables` |
| 写响应 | `r.headersOut`、`r.status`、`r.sendHeader()`、`r.send()`、`r.sendBuffer(data, flags)`、`r.finish()`、`r.return(status[, body])` |
| 流程控制 | `r.subrequest(uri[, opts][, callback])`（异步）、`r.internalRedirect()`、`r.decline()`（把判定交回 `satisfy`）、`r.done()`（结束过滤并放行当前数据块） |
| 其他 | `r.log(...)`、`r.warn()`、`r.error()`（写入 error_log） |

`r.decline()` 只在 `js_access` 里有意义：它表示「本次检查不表态」，把决定权交回 `satisfy any|all` 与其他 access 检查器。

### `s` 与 `ngx`

- `s`：仅 `js_periodic` 的处理器收到，是一个**周期性会话对象**；处理器仍可通过 `ngx` 访问全局能力。
- `ngx`：全局对象，含 `ngx.fetch()`、`ngx.log(level, ...)`、`ngx.shared.<zone名>`、`ngx.version` 等。

## VM 与作用域：一个反复咬人的细节

官方文档给出的模型是：**每个请求在第一次触发 JS 时创建一个 VM**，VM 从**当时生效的配置作用域**克隆，此后该请求内所有 JS 调用都复用这个 VM。

由此推出一个反直觉的结论：

```nginx
server {
    # 若在 server 级有 set/js_set 之类会先触发 JS 的指令
    js_set $early js_fn;      # 首次调用发生在 server 作用域

    location /api/ {
        js_import a from a.js;   # 这个 import 在本次请求里可能不可见
        js_content a.handler;
    }
}
```

因为 VM 已经绑定到 server 作用域的 import 集合，`location` 里 import 的模块在**该请求**中不可见。官方建议是：**把 `js_import` 统一放在共同父作用域（`http` 或 `server`）**，不要散落在 location 里。对 QuickJS 引擎，`js_context_reuse` 控制的是复用池大小（默认 128），一个上下文服务一个请求、用完归还池。

## 与 Lua / OpenResty 的选择

| 维度 | njs | OpenResty（LuaJIT） |
| :-- | :-- | :-- |
| 语言 | ECMAScript 子集（ES5.1 strict + 部分 ES6+） | Lua 5.1 + LuaJIT 扩展 |
| 接入方式 | `load_module` 动态模块，**不改 nginx** | 需要替换为 OpenResty 二进制（或编译 Lua 模块） |
| 生态 | 官方维护，`ngx.fetch()`、shared dict、WebCrypto（Ed25519/X25519、`crypto.randomUUID()` 自 0.9.7） | lua-resty-* 生态庞大（redis/mysql/json/协议库一应俱全） |
| 能做的扩展点 | nginx 既有阶段（content/access/header/body filter/variable/periodic） | 阶段 + 任意 C 模块 + FFI + cosocket 全 API |
| 适合 | 改头换面、签名校验、灰度路由、轻量聚合、限流计数 | 网关级业务逻辑、需要连各种后端存储 |

一句话：**OpenResty 能做 njs 的一切，反过来不成立**；njs 的价值是「不换发行版、不动编译参数，往配置里塞一段 JS」。

## 实战片段

### 用 `js_set` 打一个可观测变量

```nginx
load_module modules/ngx_http_js_module.so;

http {
    js_import main from /etc/nginx/js/main.js;

    js_set $req_id   main.reqId;
    log_format json escape=json '{"req_id":"$req_id","uri":"$uri","status":$status}';

    server {
        access_log /var/log/nginx/access.json json;
    }
}
```

```javascript
// /etc/nginx/js/main.js
function reqId(r) {
    return r.variables.request_id || r.variables.request_id_hex || "-";
}
export default { reqId };
```

注意 `js_set` 是**同步**的，不要在 `reqId` 里做网络调用。

### 用 `js_access` 做签名校验（可异步）

```javascript
async function check(r) {
    const sig = r.headersIn['X-Signature'];
    if (!sig) return r.return(401, 'no signature\n');

    const body = await r.readRequestText();      // 0.9.9 起可用
    const resp = await ngx.fetch('http://authz/internal/verify', {
        method: 'POST',
        body: JSON.stringify({ uri: r.uri, sig, body }),
    });

    if (resp.status !== 200) return r.return(403, 'denied\n');
    r.headersOut['X-User'] = await resp.text();
    r.return(200);
}
export default { check };
```

```nginx
location /api/ {
    js_access main.check;
    proxy_pass http://backend;
}
```

> [!TIP]
> njs 1.0.1 修的正是这类代码路径上的绕过：当异步读请求体的 continuation 抛异常或产生未处理的 rejection 时，旧版本会让请求**当作校验通过**继续向下走。用 `js_access` 做鉴权时，务必把版本升到 ≥ 1.0.1，并且**所有异常分支都要显式 `r.return(4xx)`**。

### 共享字典做计数

```nginx
http {
    js_shared_dict_zone zone=limits:1m timeout=60s type=number state=/var/cache/nginx/limits.state;
}
```

```javascript
function hit(r) {
    const z = ngx.shared.limits;
    const n = z.incr(r.variables.remote_addr, 1);
    if (n === undefined) { z.set(r.variables.remote_addr, 1); }
    return n ?? 1;
}
```

相比之下 `limit_req` 是 C 实现的漏桶、精度与性能都更好；shared dict 适合放「自定义维度的计数」或轻量状态。

## 常见坑

1. **默认引擎 `njs` 已弃用**——新配置写 `js_engine qjs;`；`js_context_reuse`、`js_load_http_native_module` 只在 QuickJS 下有效。
2. **location 级 `js_import` 可能"看不见"**——VM 绑定首次生效的配置作用域；import 统一放 `http`/`server`。
3. **过滤器和 `js_set` 不能异步**——`js_body_filter` / `js_header_filter` / `js_set` 里用 `await` 或 `setTimeout` 属于误用。
4. **`js_content` 与 `proxy_pass` 是同一阶段的两个 handler**——CONTENT 阶段只允许一个生效，别指望「JS 改完再代理」，那要用 `js_access` + `proxy_pass`，或 `js_header_filter` + `proxy_pass`。
5. **`ngx.fetch()` 默认不复用连接、默认不含 TLSv1.3**——高频调用要么开 `js_fetch_keepalive`，要么改用 `proxy_pass` / `auth_request`。
6. **`js_include` 已被移除**（0.7.1），老文章里的写法会直接起不来。
7. **shared dict 的 `state=file` 要落盘**——容器里注意挂载路径与写权限，否则 reload 后计数清零。
8. **njs 无法替代 WAF 级规则集**——复杂正则与规则引擎是 ModSecurity/Coraza 的活，见 [security](/docs/CS/CN/nginx/security.md)。

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)
- [HTTP](/docs/CS/CN/nginx/HTTP.md)
- [Configuration](/docs/CS/CN/nginx/config.md)
- [OpenResty](/docs/CS/CN/nginx/OpenResty.md)
- [security](/docs/CS/CN/nginx/security.md)

## References

1. [Module ngx_http_js_module](https://nginx.org/en/docs/http/ngx_http_js_module.html)
2. [Module ngx_stream_js_module](https://nginx.org/en/docs/stream/ngx_stream_js_module.html)
3. [njs 变更记录（Changes with njs）](https://nginx.org/en/docs/njs/changes.html)
4. [nginx 官方新闻（含 njs 版本与安全公告）](https://nginx.org/en/2026.html)
5. [njs 参考手册](https://nginx.org/en/docs/njs/reference.html)
