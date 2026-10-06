## Introduction

日志是 nginx 排障的第一现场，但 `log_format` 的行为细节经常被误解：`access_log` 不写参数时用的是哪套格式、`buffer=` 什么时候刷盘、`escape=json` 到底转义什么、为什么 stream 的 `access_log` 不给格式名直接启动失败。

本文覆盖：`log_format` 的编译机制、`access_log` 全参数与默认值、`error_log` 级别体系与 `--with-debug` 的真实关系、syslog、结构化 JSON。事实基于 **nginx 1.31.6** 源码。

## access_log 的默认行为

完全不写 `access_log` 时，nginx 会在配置合并阶段自动创建一条默认日志（`ngx_http_log_module.c:1324`）：

- 文件：`logs/access.log`（编译期 `--http-log-path` 决定）
- 格式：**`combined`**——`$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"`

`combined` 是**惰性编译**的：只有确实被用到时才在配置末尾编译成 ops 数组；自己定义了 `log_format` 且没引用 `combined`，它就不参与编译。

## log_format 的编译机制

`log_format` 只能写在 http 块（stream 有独立的同名指令），语法：

```
log_format name [escape=default|json|none] string ...;
```

指令在解析时把格式字符串**编译成 `ngx_http_log_op_t` 数组**（`ngx_http_log_compile_format()`，`ngx_http_log_module.c:1696`）：

1. 遇到 `$var`（或 `${var}`）→ 先查内建快路径表 `ngx_http_log_vars[]`，命中用专用 run 函数；否则取变量 index，并把该 index 记进 `flushes`（运行前强制刷新缓存）
2. 字面文本按长度分流：≤ `sizeof(uintptr_t)` 的用 `ngx_http_log_copy_short`——**把字节塞进 op->data 自身，零分配**；长文本用 `ngx_http_log_copy_long`

内建快路径变量（不经通用变量系统，更快）：`$pipe`、`$time_local`、`$time_iso8601`、`$msec`、`$request_time`、`$status`、`$bytes_sent`、`$body_bytes_sent`、`$request_length`。

运行时两趟循环：先对每个 op 调 `getlen()` 累加总长，`ngx_pnalloc` 一块精确大小的内存，再逐个 `run()` 渲染。日志行是**先算长度再拼**，没有截断和二次分配。

### 时间变量的精度

| 变量 | 格式 | 精度 |
| :-- | :-- | :-- |
| `$time_local` | `28/Sep/2026:12:00:00 +0800` | 秒（取缓存时间） |
| `$time_iso8601` | `2026-09-28T12:00:00+08:00` | 秒 |
| `$msec` | `1790577600.123` | **毫秒**，唯一的毫秒级时间变量 |
| `$request_time` | `0.123` 秒.毫秒 | 请求处理耗时 |

`$time_local` 取的是 `ngx_cached_http_log_time`（由 timer 每秒刷新的缓存），不是每请求实时 `gettimeofday`。要毫秒精度用 `$msec`。error_log 行首时间是另一种格式（`1970/09/28 12:00:00`，`ngx_cached_err_log_time`）。

## access_log 全参数

```
access_log path [format [buffer=size] [gzip[=level]] [flush=time] [if=condition]];
access_log off;
```

| 参数 | 默认 | 行为 |
| :-- | :-- | :-- |
| `buffer=` | **0（不缓冲，每条直接 write）** | 日志行先写进内存缓冲，缓冲不够才落盘 |
| `flush=` | 0 | 必须搭配 `buffer`，否则 EMERG `"no buffer is defined"`；到点强制刷盘 |
| `gzip[=level]` | 0 | 不带值时 level=1（`Z_BEST_SPEED`）；**自动启用 64K buffer**；未编 zlib 直接启动失败 |
| `if=` | 无 | complex value，**空串或恰好 `"0"` 跳过**，其它都记 |

约束：

- **带变量的路径不能配 `buffer`**（路径每次都可能不同）；syslog 目标同理
- 同一文件被多条 `access_log` 引用时，buffer/flush/gzip 参数必须完全一致，否则 EMERG `"already defined with conflicting parameters"`
- `access_log off` 后面**不能再跟任何参数**

`if=` 不是 `if` 指令，是 complex value：

```conf
map $status $loggable {
    ~^[23]  0;          # 2xx/3xx 不记
    default 1;
}
access_log /var/log/nginx/error-requests.log combined if=$loggable;
```

### open_log_file_cache

按变量打开日志文件（如 `access_log /logs/$host/access.log`）每请求一次 `open()/close()` 很贵，缓存它：

```
open_log_file_cache max=N [inactive=time] [min_uses=N] [valid=time];
```

- **默认关闭**；`max` 是**必填项**，缺了 EMERG `"must have \"max\" parameter"`
- 其余默认：`inactive=10s`、`valid=60s`、`min_uses=1`
- 只对**含变量的路径**生效，静态路径直接写 fd

## error_log 级别体系

```
error_log file [level];        # 只能 main / http / server / location 等上下文逐级覆盖
```

级别全集（`src/core/ngx_log.c:75`）：`emerg < alert < crit < error < warn < notice < info < debug`。

- 只给文件不给级别时默认 **`error`**
- 允许多条 `error_log`，按级别从高到低插链表——**同一条日志可以同时进多个目标**
- `error_log stderr` 是特殊值（不是 `/dev/stderr`）
- `error_log syslog:...` 见下节；`error_log memory:size` 仅 `--with-debug` 编译可用（环形内存日志，测试用）

### --with-debug 的真实关系（最容易误解）

| 开关 | 作用 |
| :-- | :-- |
| `--with-debug`（**编译期**） | 打开 `NGX_DEBUG`，让所有 `ngx_log_debugN()` 宏有实际代码 |
| `error_log ... debug;`（**运行期**） | 只是运行期级别过滤的阈值 |

**不开 `--with-debug` 时，`ngx_log_debugN` 在预处理阶段就被替换成空**——就算配置里写 `error_log /path debug;` 也一条 debug 日志都不会产生。`debug_connection` 同样整体包在 `#if (NGX_DEBUG)` 里，不开 debug 编译连这个指令都不可用。

`debug_connection` 的用法（对指定 IP 的连接输出 debug 日志）：

```conf
events {
    debug_connection 10.0.0.5;
    debug_connection unix:;
}
```

细分 debug 级别（位掩码）：`debug_core/alloc/mutex/event/http/mail/stream`。

## 落盘方式：没有锁，裸 write

`ngx_log_error_core()`（`src/core/ngx_log.c:96`）的行为：

1. 格式化到**栈上** `errstr[NGX_MAX_ERROR_STR]`（时间 + `[级别]` + pid#tid + `*connection` + 消息 + errno）
2. 遍历 log 链表，逐个目标**裸 `write()`**（`O_APPEND` 打开的 fd），**没有用户态锁、没有缓冲**
3. ENOSPC 时记 `disk_full_time`，同一秒内跳过写（防日志风暴）
4. 级别过滤有两道：宏处的运行期短路（`if ((log)->log_level >= level)`，连格式化都不做）+ core 内部按每个目标的 level 过滤

原子性完全依赖 `O_APPEND` + 单次 `write()`，nginx 自己不保证多进程交错时的行完整性（实践中 Linux 上单条日志 ≤ 页大小是原子的）。

## syslog

```
error_log syslog:server=10.0.0.1:514,facility=local7,tag=nginx error;
access_log syslog:server=[2001:db8::1]:514,facility=local7,nohostname combined;
```

| 参数 | 默认 |
| :-- | :-- |
| `server=` | **必填**，缺了启动失败；默认端口 514 |
| `facility=` | `local7` |
| `severity=` | `info`（error_log 场景会被日志级别覆盖） |
| `tag=` | `nginx`（仅字母数字下划线，≤32 字符） |
| `nohostname` | 不加则输出带 hostname |

severity 拼写用 nginx 的习惯（`error`/`warn`），**不是** syslog 的 `err`/`warning`。实现在 `src/core/ngx_syslog.c`，走 UDP。

## stream 的日志：三处不同

stream 有自己的 log 模块（`src/stream/ngx_stream_log_module.c`），用法类似但有硬差异：

1. **没有内建 `combined` 格式**
2. **`access_log` 必须显式给格式名**——只写路径启动时报 EMERG `"log format is not specified"`
3. **不配 `access_log` 就完全没有日志**（http 会兜底创建默认日志，stream 不会）

可用变量是 stream 变量集（`$remote_addr`、`$bytes_sent`、`$bytes_received`、`$session_time`、`$status`、`$upstream_addr`、`$upstream_session_time`、`$ssl_preread_server_name` 等），**http 的 `$request`、`$http_*` 在 stream 里不存在**，见 [stream](/docs/CS/CN/nginx/stream.md)。

## 结构化 JSON

`escape=json` 只负责**转义变量值**（引号、反斜杠、控制字符），**不帮你加引号和花括号**——JSON 骨架要自己拼：

```conf
log_format json_combined escape=json
    '{'
        '"time":"$time_iso8601",'
        '"remote_addr":"$remote_addr",'
        '"request":"$request",'
        '"status":$status,'                       # 数字字段不加引号
        '"body_bytes_sent":$body_bytes_sent,'
        '"request_time":$request_time,'
        '"upstream_addr":"$upstream_addr",'
        '"upstream_response_time":"$upstream_response_time",'
        '"ua":"$http_user_agent"'
    '}';
```

> [!TIP]
> 数字型字段（`$status`、`$request_time`）不加引号，让下游解析为数字；可能缺失的字符串字段要给默认值（用 `map` 或 `set`），否则 `escape=json` 会输出空串造成 `"key":` 后面悬空。

对比 `escape=default`：它把 `"`、`\`、控制字符以及**所有 ≥0x80 的字节**转义成 `\xXX`——这就是中文 UA 在默认日志里变成 `\xE4\xBD\xA0` 的原因。不想转义用 `escape=none`（自担注入风险）。

另外两个容易混淆的东西：

- **1.31.5 的 `ngx_http_json_module` 不是日志模块**：它的指令是 `json_set $var $source path`（从**任意变量持有的 JSON 文档**里按路径抽字段成新变量，`json_max_depth` 默认 32）。变量名自己起，没有 `$json_` 前缀约定。它的产物可以被 log_format 引用，但用途是「解析变量里的 JSON」。
- 日志里出现 `0.000`/`-` 的 upstream 字段：`$upstream_response_time` 多值时逗号分隔（重试每个 upstream 一段），`-` 表示该阶段未发生。

## 排障向的日志变量

| 变量 | 用途 |
| :-- | :-- |
| `$request_time` | nginx 自身处理总耗时（含收发 body） |
| `$upstream_response_time` | 上游耗时（多值 = 多次重试），与 `$request_time` 的差 ≈ nginx 开销 |
| `$upstream_connect_time` | 与上游建连耗时（TLS 时含握手）——暴涨说明握手/网络问题 |
| `$upstream_header_time` | 收到响应头耗时——大说明上游慢，但不至于超时 |
| `$upstream_addr` | 实际走过的 upstream 列表，排查重试 |
| `$upstream_cache_status` | HIT/MISS/EXPIRED/STALE…，见 [Cache](/docs/CS/CN/nginx/cache.md) |
| `$request_id` | 32 位十六进制请求 ID（1.11.0 起），可传给上游做全链路追踪 |

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md) — 可观测性概览
- [Cache](/docs/CS/CN/nginx/cache.md) — `$upstream_cache_status` 的七个值
- [Upstream](/docs/CS/CN/nginx/upstream.md) — `$upstream_*` 变量的产生过程
- [stream](/docs/CS/CN/nginx/stream.md) — stream 日志的差异
- [Troubleshooting](/docs/CS/CN/nginx/troubleshooting.md) — 日志关键字到原因的对照
- [njs](/docs/CS/CN/nginx/njs.md)

## References

- <https://nginx.org/en/docs/http/ngx_http_log_module.html>
- <https://nginx.org/en/docs/stream/ngx_stream_log_module.html>
- <https://nginx.org/en/docs/ngx_core_module.html#error_log>
