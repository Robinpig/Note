## Introduction

nginx 的可扩展性几乎完全建立在模块上：编译期决定模块清单，运行期通过回调表驱动。但 nginx 模块的写法是出了名的「宏驱动」——`NGX_MODULE_V1`、`NGX_HTTP_MODULE`、`NGX_CONF_TAKE1`，不了解这些宏背后填充的是什么结构，照抄模板就只是抄模板。

本文讲清三件事：**模块在 nginx 里以什么结构存在**（`ngx_module_t` 与两级 ctx）、**指令如何接进配置系统**（`ngx_command_t` 位掩码）、**四类模块各怎么写**（content handler / 过滤器 / 变量 / upstream）。最后给可直接编译的最小骨架。事实基于 **nginx 1.31.6** 源码。

## ngx_module_t：一切模块的骨架

每个编译进 nginx 的模块最终都是一个 `ngx_module_t` 实例（`src/core/ngx_module.h:227`）：

```c
struct ngx_module_s {
    ngx_uint_t            ctx_index;   /* 同类模块内的序号 */
    ngx_uint_t            index;       /* 全局模块数组中的序号 */
    char                 *name;

    ngx_uint_t            spare0;
    ngx_uint_t            spare1;

    ngx_uint_t            version;     /* nginx_version */
    const char           *signature;   /* NGX_MODULE_SIGNATURE */

    void                 *ctx;         /* ngx_http_module_t 等 */
    ngx_command_t        *commands;
    ngx_uint_t            type;        /* NGX_HTTP_MODULE 等 */

    ngx_int_t           (*init_master)(ngx_log_t *log);
    ngx_int_t           (*init_module)(ngx_cycle_t *cycle);
    ngx_int_t           (*init_process)(ngx_cycle_t *cycle);
    ngx_int_t           (*init_thread)(ngx_cycle_t *cycle);
    void                (*exit_thread)(ngx_cycle_t *cycle);
    void                (*exit_process)(ngx_cycle_t *cycle);
    void                (*exit_master)(ngx_cycle_t *cycle);

    uintptr_t             spare_hook0;   /* 共 8 个 spare_hook */
    ...
};
```

字段说明：

- **`index` vs `ctx_index`**：`index` 是模块在全局 `ngx_modules[]` 数组中的位置；`ctx_index` 是模块在**同类模块**（所有 `NGX_HTTP_MODULE`）里的序号。HTTP 模块用 `ctx_index` 在 `main_conf[]/srv_conf[]/loc_conf[]` 数组里定位自己的那格。
- **`ctx`**：按 `type` 不同指向不同结构——HTTP 模块是 `ngx_http_module_t`，core 是 `ngx_core_module_t`，stream 是 `ngx_stream_module_t`。
- **生命周期回调的调用时机**：

| 回调 | 时机 | 典型用途 |
| :-- | :-- | :-- |
| `init_master` | — | **1.31.6 中从未被调用**（全树零引用） |
| `init_module` | master 完成配置解析、创建新 cycle 后（reload 也是） | 初始化共享内存之外的资源 |
| `init_process` | **每个 worker** fork 之后 | 初始化与本进程相关的资源（连接池、随机种子） |
| `init_thread` / `exit_thread` | — | **从未被调用**（nginx 基本单线程） |
| `exit_process` | worker 退出前 | 清理 |
| `exit_master` | master 退出前 | 清理共享资源 |

### NGX_MODULE_V1 与二进制兼容

写模块时开头那两行宏不是装饰：

```c
#define NGX_MODULE_V1                                                         \
    NGX_MODULE_UNSET_INDEX, NGX_MODULE_UNSET_INDEX,                           \
    NULL, 0, 0, nginx_version, NGX_MODULE_SIGNATURE

#define NGX_MODULE_V1_PADDING  0, 0, 0, 0, 0, 0, 0, 0
```

`NGX_MODULE_V1` 填充 `ctx_index/index`（启动时由 `ngx_preinit_modules()` 重新编号）、`name`（填 `ngx_module_names[i]`）、`spare0/1`、版本与签名。`NGX_MODULE_V1_PADDING` 补齐 8 个 `spare_hook`——**结构体长度必须与官方一致**，这是动态模块二进制兼容的基础。

`NGX_MODULE_SIGNATURE` 是一串由 34 个 `0/1` 组成的字符串，记录编译时启用的特性（是否有 SSL、是否 IPv6、zlib……）。加载动态模块时逐位比对，不一致就报 `"module ... is not binary compatible"`。所以**动态模块必须与主二进制用同样的 configure 参数编译**。

## ngx_command_t：把指令接进配置系统

```c
typedef struct {
    ngx_str_t             name;
    ngx_uint_t            type;      /* 参数个数 + 出现的上下文，位掩码 */
    char               *(*set)(ngx_conf_t *cf, ngx_command_t *cmd, void *conf);
    ngx_uint_t            conf;      /* 配置层级偏移 */
    ngx_uint_t            offset;    /* 字段在 conf 结构体中的偏移 */
    void                 *post;      /* 后处理 */
} ngx_command_t;
```

`type` 位掩码由两部分 OR 起来：

- **参数个数**：`NGX_CONF_NOARGS`（0 个）、`NGX_CONF_TAKE1`…`TAKE7`、`NGX_CONF_TAKE12`（1 或 2 个）、`NGX_CONF_1MORE`（≥1）、`NGX_CONF_2MORE`、`NGX_CONF_BLOCK`（块指令）、`NGX_CONF_FLAG`（on/off）
- **允许出现的上下文**：`NGX_MAIN_CONF`、`NGX_HTTP_MAIN_CONF / SRV_CONF / LOC_CONF`、`NGX_HTTP_UPS_CONF`、`NGX_STREAM_MAIN_CONF / SRV_CONF / UPS_CONF` 等

`conf` 字段指明 conf 指针怎么算：`NGX_HTTP_MAIN_CONF_OFFSET`（取 main_conf）、`NGX_HTTP_SRV_CONF_OFFSET`、`NGX_HTTP_LOC_CONF_OFFSET`，或 0（配置存在别处）。`ngx_conf_handler()` 解析时会校验当前 `cf->cmd_type` 与指令 `type` 的匹配，不匹配直接报 `"directive ... is not allowed here"`——这就是你在错误位置写指令时看到的那条报错的来源。

以 `stub_status` 为例（`ngx_http_stub_status_module.c`）：

```c
static ngx_command_t  ngx_http_status_commands[] = {
    { ngx_string("stub_status"),
      NGX_HTTP_SRV_CONF|NGX_HTTP_LOC_CONF|NGX_CONF_NOARGS|NGX_CONF_TAKE1,
      ngx_http_set_stub_status,
      0,
      0,
      NULL },

      ngx_null_command
};

static char *
ngx_http_set_stub_status(ngx_conf_t *cf, ngx_command_t *cmd, void *conf)
{
    ngx_http_core_loc_conf_t  *clcf;

    clcf = ngx_http_conf_get_module_loc_conf(cf, ngx_http_core_module);
    clcf->handler = ngx_http_stub_status_handler;   /* 直接注册 content handler */

    return NGX_CONF_OK;
}
```

自带 `ngx_conf_set_*_slot` 系列现成回调可用：`set_flag_slot`、`set_str_slot`、`set_size_slot`、`set_msec_slot`、`set_num_slot`、`set_enum_slot`、`set_complex_value_slot` 等，绝大多数指令不用自己写 set 函数。

## HTTP 模块上下文：八个回调

HTTP 模块的 `ctx` 是 `ngx_http_module_t`（`src/http/ngx_http_config.h:24`）：

```c
typedef struct {
    ngx_int_t   (*preconfiguration)(ngx_conf_t *cf);
    ngx_int_t   (*postconfiguration)(ngx_conf_t *cf);

    void       *(*create_main_conf)(ngx_conf_t *cf);
    char       *(*init_main_conf)(ngx_conf_t *cf, void *conf);

    void       *(*create_srv_conf)(ngx_conf_t *cf);
    char       *(*merge_srv_conf)(ngx_conf_t *cf, void *prev, void *conf);

    void       *(*create_loc_conf)(ngx_conf_t *cf);
    char       *(*merge_loc_conf)(ngx_conf_t *cf, void *prev, void *conf);
} ngx_http_module_t;
```

| 回调 | 时机 | 典型用途 |
| :-- | :-- | :-- |
| `preconfiguration` | 解析 http{} **之前**，最先 | **注册变量**（必须在这里，才有机会被后续指令引用） |
| `postconfiguration` | http{} 解析完，所有模块各调一次 | **挂阶段 handler / 过滤器**（此时其它模块都已就位） |
| `create_main_conf` | 每模块一次 | 分配本模块 http 级配置结构体 |
| `init_main_conf` | 所有 create 完后 | 设置默认值 |
| `create_srv_conf` / `merge_srv_conf` | 每个 server{} | server 级配置与三层合并 |
| `create_loc_conf` / `merge_loc_conf` | 每个 location{}（含继承） | location 级配置与合并 |

合并规则见 [Configuration](/docs/CS/CN/nginx/config.md)：只在 `conf->xxx == NGX_CONF_UNSET` 时继承 `prev`，用 `ngx_conf_merge_value` 系列宏。

stream 模块上下文是它的子集：只有 main/srv 两级，没有 loc。

## 四类模块写法

### 1. content handler（处理请求）

两种挂法：

- **`clcf->handler = my_handler;`**（在指令回调里，如上面的 `stub_status`）——一个 location 只能有一个
- **在 `postconfiguration` 里往 `cmcf->phases[NGX_HTTP_..._PHASE].handlers` push**——可叠加、可多模块共存，见 [HTTP 的阶段机制](/docs/CS/CN/nginx/HTTP.md)

### 2. 过滤模块（改响应）

过滤链是**编译期静态链表**，注册就是头插：

```c
/* src/http/modules/ngx_http_not_modified_filter_module.c:260 */
static ngx_int_t
ngx_http_not_modified_filter_init(ngx_conf_t *cf)
{
    ngx_http_next_header_filter = ngx_http_top_header_filter;
    ngx_http_top_header_filter = ngx_http_not_modified_header_filter;

    return NGX_OK;
}
```

放在 `postconfiguration` 里调用。链尾固定是 `ngx_http_write_filter`，所以 **`--add-module` 的顺序决定你的 filter 在链里的位置**（越晚注册越靠外，越先看到响应头）。body filter 同理（`ngx_http_top_body_filter` / `ngx_http_next_body_filter`）。

### 3. 注册变量

```c
static ngx_int_t
ngx_http_my_module_preconfiguration(ngx_conf_t *cf)
{
    ngx_http_variable_t  *var;

    var = ngx_http_add_variable(cf, &ngx_str("my_var"), NGX_HTTP_VAR_CHANGEABLE);
    if (var == NULL) {
        return NGX_ERROR;
    }
    var->get_handler = ngx_http_my_var_get;
    var->data = 0;

    return NGX_OK;
}
```

**必须在 `preconfiguration`**：变量的 index 在配置解析阶段就被指令引用（`ngx_http_get_variable_index()`），太晚注册会让引用它的指令解析失败。flags 见 [Configuration 的变量一节](/docs/CS/CN/nginx/config.md?id=变量)。

### 4. upstream 模块（对接上游）

一个上游协议模块（如 proxy/fastcgi/memcached）要填 `ngx_http_upstream_t` 的一组回调，**1.31.6 中实际被调用的有五个**：

| 回调 | 作用 |
| :-- | :-- |
| `create_request` | 拼上游请求（r->upstream->request_bufs） |
| `reinit_request` | 重试换 peer 后重置请求状态 |
| `process_header` | 解析上游响应头，返回 `NGX_OK`（头完成）/ `NGX_AGAIN`（还要读）/ `NGX_HTTP_UPSTREAM_INVALID_HEADER` |
| `finalize_request` | 收尾 |
| `input_filter` | 解析响应 body（可选） |

`abort_request` 在 1.31.6 里**只有赋值、从未被调用**，是个死钩子——网上教程说「客户端中断时调用 abort_request」在当前源码不成立，别照写。

调用次序：`ngx_http_upstream_create()` → `ngx_http_read_client_request_body()`（或直接）→ `ngx_http_upstream_init()` → `create_request` → 连接 peer → `process_header` → `input_filter`。

自定义负载均衡算法实现 `ngx_http_upstream_peer_t` 的 `init / get / free`（平滑加权轮询的源码见 [Upstream](/docs/CS/CN/nginx/upstream.md)），最短范本是 `ngx_http_upstream_random_module.c`。

## 编译接入

### config 脚本

第三方模块目录里放一个 `config` shell 脚本，`configure --add-module=/path` 会 source 它。现代写法（`auto/module`）需要设置这些变量：

```bash
# config
ngx_addon_name=ngx_http_hello_module

# 模块清单（动态模块可以有多个名字）
ngx_module_name=ngx_http_hello_module
ngx_module_type=HTTP
ngx_module_srcs="$ngx_addon_dir/ngx_http_hello_module.c"
ngx_module_incs="$ngx_addon_dir"
ngx_module_deps=
ngx_module_libs=
ngx_module_order=

. auto/module
```

- `ngx_module_type` 取值：`HTTP`、`HTTP_FILTER`（过滤模块）、`HTTP_AUX_FILTER`、`STREAM`、`MAIL`、`MISC` 等。filter 类型不设 `ngx_module_order` 时默认插到 `ngx_http_copy_filter_module` 之后（`auto/module:16-22`）
- `ngx_module_link` 由 configure 自动置 `YES`（静态）或 `DYNAMIC`（`--add-dynamic-module`）
- filter 模块的链上顺序可以用 `ngx_module_order` 显式指定

### 静态 vs 动态

| 方式 | configure | 加载 |
| :-- | :-- | :-- |
| 静态 | `--add-module=/path` | 编译进二进制，启动即生效 |
| 动态 | `--add-dynamic-module=/path` | 生成 `.so`，配置里 `load_module modules/ngx_http_hello_module.so;` |

动态模块受 `NGX_MODULE_SIGNATURE` 约束：主二进制重新 configure 后，所有 `.so` 必须用相同参数重编。**reload 换动态模块版本时，新老二进制签名不一致会直接加载失败**，这比协议变更更容易踩。

## 最小骨架：可直接编译

### hello handler 模块

```c
#include <ngx_config.h>
#include <ngx_core.h>
#include <ngx_http.h>

static ngx_int_t ngx_http_hello_handler(ngx_http_request_t *r);
static char *ngx_http_hello(ngx_conf_t *cf, ngx_command_t *cmd, void *conf);

static ngx_command_t  ngx_http_hello_commands[] = {
    { ngx_string("hello"),
      NGX_HTTP_LOC_CONF|NGX_CONF_NOARGS,
      ngx_http_hello,
      0, 0, NULL },
      ngx_null_command
};

static ngx_http_module_t  ngx_http_hello_module_ctx = {
    NULL,                                  /* preconfiguration */
    NULL,                                  /* postconfiguration */
    NULL,                                  /* create main conf */
    NULL,                                  /* init main conf */
    NULL,                                  /* create server conf */
    NULL,                                  /* merge server conf */
    NULL,                                  /* create loc conf */
    NULL                                   /* merge loc conf */
};

ngx_module_t  ngx_http_hello_module = {
    NGX_MODULE_V1,
    &ngx_http_hello_module_ctx,            /* module context */
    ngx_http_hello_commands,               /* module directives */
    NGX_HTTP_MODULE,                       /* module type */
    NULL,                                  /* init master */
    NULL,                                  /* init module */
    NULL,                                  /* init process */
    NULL,                                  /* init thread */
    NULL,                                  /* exit thread */
    NULL,                                  /* exit process */
    NULL,                                  /* exit master */
    NGX_MODULE_V1_PADDING
};

static ngx_int_t
ngx_http_hello_handler(ngx_http_request_t *r)
{
    ngx_chain_t    out;
    ngx_buf_t     *b;
    ngx_str_t      body = ngx_string("hello, world\n");

    if (!(r->method & (NGX_HTTP_GET|NGX_HTTP_HEAD))) {
        return NGX_HTTP_NOT_ALLOWED;
    }

    b = ngx_calloc_buf(r->pool);
    if (b == NULL) {
        return NGX_HTTP_INTERNAL_SERVER_ERROR;
    }

    b->memory = 1;
    b->pos = body.data;
    b->last = body.data + body.len;

    out.buf = b;
    out.next = NULL;

    r->headers_out.content_type_len = sizeof("text/plain") - 1;
    ngx_str_set(&r->headers_out.content_type, "text/plain");
    r->headers_out.content_length_n = body.len;

    if (ngx_http_send_header(r) == NGX_ERROR) {
        return NGX_ERROR;
    }

    return ngx_http_output_filter(r, &out);
}

static char *
ngx_http_hello(ngx_conf_t *cf, ngx_command_t *cmd, void *conf)
{
    ngx_http_core_loc_conf_t  *clcf;

    clcf = ngx_http_conf_get_module_loc_conf(cf, ngx_http_core_module);
    clcf->handler = ngx_http_hello_handler;

    return NGX_CONF_OK;
}
```

### header filter 模块

```c
static ngx_http_output_header_filter_pt  ngx_http_next_header_filter;

static ngx_int_t
ngx_http_hello_header_filter(ngx_http_request_t *r)
{
    ngx_table_elt_t  *h;

    h = ngx_list_push(&r->headers_out.headers);
    if (h == NULL) {
        return NGX_ERROR;
    }
    ngx_str_set(&h->key, "X-Hello");
    ngx_str_set(&h->value, "1");
    h->next = NULL;                        /* 1.23.0 起同名字段是链表，必须置 NULL */

    return ngx_http_next_header_filter(r);
}

static ngx_int_t
ngx_http_hello_filter_init(ngx_conf_t *cf)
{
    ngx_http_next_header_filter = ngx_http_top_header_filter;
    ngx_http_top_header_filter = ngx_http_hello_header_filter;
    return NGX_OK;
}
```

（把 `ngx_http_hello_filter_init` 填进 ctx 的 `postconfiguration` 即可。）

## 陷阱清单

1. **`init_master` / `init_thread` / `exit_thread` 不会被调用**，填 `NULL` 即可——很多教程还煞有介事地介绍 init_master，1.31.6 全树零引用。
2. **`abort_request` 是死钩子**，只赋值不调用。
3. **`headers_out` 里同名字段从 1.23.0 起是链表**（`ngx_table_elt_t` 加了 `next`），push 进 `headers` 后忘记 `h->next = NULL` 会随机崩溃。
4. **变量必须注册在 preconfiguration**，postconfiguration 里注册会晚于配置解析。
5. **动态模块与主程序 configure 参数必须一致**，否则 `NGX_MODULE_SIGNATURE` 逐位比对失败直接拒载。
6. **filter 的注册顺序就是 add-module 顺序**，写 filter 时先确认自己想站在链的哪一层（越靠外越先处理响应头）。
7. **`ngx_conf_merge_*` 只在子级为 UNSET 时继承**，数组型配置（`ngx_array_push`）是覆盖不是合并——模块作者与配置使用者都会被这条咬。

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md) — Module 一节有模块生命周期总览
- [Configuration](/docs/CS/CN/nginx/config.md) — 配置合并与变量系统
- [HTTP](/docs/CS/CN/nginx/HTTP.md) — 阶段机制与过滤链
- [Upstream](/docs/CS/CN/nginx/upstream.md) — 负载均衡算法的 peer 接口
- [Memory](/docs/CS/CN/nginx/memory.md) — 模块配置结构体所在的内存池
- [njs](/docs/CS/CN/nginx/njs.md)

## References

- <https://nginx.org/en/docs/dev/development_guide.html>
- <https://nginx.org/en/docs/dirindex.html>
