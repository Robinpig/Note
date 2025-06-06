## Introduction



worker进程会在一个for循环语句里反复调用事件模块检测网络事件。当事件模块检测到某个客户端发起的TCP请求时（接收到SYN包），将会为它建立TCP连接，成功建立连接后根据nginx.conf文件中的配置会交由HTTP框架处理
HTTP框架会试图接收完整的HTTP头部，并在接收到完整的HTTP头部后将请求分发到具体的HTTP模块中处理

这种分发策略是多样化的，其中最常见的是根据请求的URI和nginx.conf里location配置项的匹配度来决定如何分发

HTTP模块在处理请求的结束时，大多会向客户端发送响应，此时会自动地依次调用所有的HTTP过滤模块，每个过滤模块可以根据配置文件决定自己的行为
例如，gzip过滤模块根据配置文件中的gzip on|off来决定是否压缩响应。

HTTP处理模块在返回时会将控制权交还给HTTP框架，如果在返回前设置了subrequest，那么HTTP框架还会继续异步地调用适合的HTTP模块处理子请求

## init

ngx_http_init_connection

```c
// 
void
ngx_http_init_connection(ngx_connection_t *c)
{
 // ...   
 rev->handler = ngx_http_wait_request_handler;
    c->write->handler = ngx_http_empty_handler;
    
}
```

ngx_http_process_connection

## handler

ngx_http_wait_request_handler  
 - ngx_http_process_request_line 
 - ngx_http_read_request_header 
 - ngx_http_parse_request_line 
 - ngx_http_process_request


### process request

```c
void
ngx_http_process_request(ngx_http_request_t *r)
{
    // ...
    c->read->handler = ngx_http_request_handler;
    c->write->handler = ngx_http_request_handler;
    r->read_event_handler = ngx_http_block_reading;

    ngx_http_handler(r);
}
```

```c
void
ngx_http_handler(ngx_http_request_t *r)
{
    ngx_http_core_main_conf_t  *cmcf;

    r->connection->log->action = NULL;

    if (!r->internal) {
        switch (r->headers_in.connection_type) {
        case 0:
            r->keepalive = (r->http_version > NGX_HTTP_VERSION_10);
            break;

        case NGX_HTTP_CONNECTION_CLOSE:
            r->keepalive = 0;
            break;

        case NGX_HTTP_CONNECTION_KEEP_ALIVE:
            r->keepalive = 1;
            break;
        }

        r->lingering_close = (r->headers_in.content_length_n > 0
                              || r->headers_in.chunked);
        r->phase_handler = 0;

    } else {
        cmcf = ngx_http_get_module_main_conf(r, ngx_http_core_module);
        r->phase_handler = cmcf->phase_engine.server_rewrite_index;
    }

    r->valid_location = 1;
    
    // zip

    r->write_event_handler = ngx_http_core_run_phases;
    ngx_http_core_run_phases(r);
}
```
### return

rewrite "return" call ngx_http_send_response

```c

static ngx_command_t  ngx_http_rewrite_commands[] = {

    { ngx_string("return"),
      NGX_HTTP_SRV_CONF|NGX_HTTP_SIF_CONF|NGX_HTTP_LOC_CONF|NGX_HTTP_LIF_CONF
                       |NGX_CONF_TAKE12,
      ngx_http_rewrite_return,
      NGX_HTTP_LOC_CONF_OFFSET,
      0,
      NULL }
      
      }
```

ngx_http_rewrite_return -> ngx_http_script_return_code

ngx_http_send_response
- ngx_http_send_header
- ngx_http_output_filter
  - ngx_http_top_body_filter
- ngx_http_write_filter
- ngx_http_finalize_request
- ngx_http_run_posted_requests





## 流量拷贝

将生产环境的流量拷贝到预上线环境或测试环境，这样做有很多好处，比如：

- 可以验证功能是否正常，以及服务的性能；
- 用真实有效的流量请求去验证，又不用造数据，不影响线上正常访问；
- 这跟灰度发布还不太一样，镜像流量不会影响真实流量；
- 可以用来排查线上问题；
- 重构，假如服务做了重构，这也是一种测试方式



为了实现流量拷贝，Nginx提供了`ngx_http_mirror_module`模块

> 如果安装的nginx中没有`ngx_http_mirror_module` 需要从源码开始make

```nginx
location / {
    mirror /mirror;
    proxy_pass http://backend;
}

location = /mirror {
    internal;
    proxy_pass http://test_backend$request_uri;
}
```

如果请求体被镜像，那么在创建子请求之前会先读取请求体 设置如下配置关闭读取

```nginx
location / {
    mirror_request_body off;
}

location = /mirror {
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header X-Original-URI $request_uri;
}
```










## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)







