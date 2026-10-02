## Introduction

事件模块是对内核 I/O 多路复用机制（[epoll](/docs/CS/OS/Linux/IO/epoll.md) 等）的封装，worker 在事件循环中调用 `ngx_epoll_process_events` 处理网络事件。


```c
// event/ngx_event.h
typedef struct {
    ngx_str_t              *name;

    void                 *(*create_conf)(ngx_cycle_t *cycle);
    char                 *(*init_conf)(ngx_cycle_t *cycle, void *conf);

    ngx_event_actions_t     actions;
} ngx_event_module_t;
```

epoll

```c

static ngx_event_module_t  ngx_epoll_module_ctx = {
    &epoll_name,
    ngx_epoll_create_conf,               /* create configuration */
    ngx_epoll_init_conf,                 /* init configuration */

    {
        ngx_epoll_add_event,             /* add an event */
        ngx_epoll_del_event,             /* delete an event */
        ngx_epoll_add_event,             /* enable an event */
        ngx_epoll_del_event,             /* disable an event */
        ngx_epoll_add_connection,        /* add an connection */
        ngx_epoll_del_connection,        /* delete an connection */
    #if (NGX_HAVE_EVENTFD)
        ngx_epoll_notify,                /* trigger a notify */
    #else
        NULL,                            /* trigger a notify */
    #endif
        ngx_epoll_process_events,        /* process the events */
        ngx_epoll_init,                  /* init the events */
        ngx_epoll_done,                  /* done the events */
    }
};
```

## init

ngx_event_process_init

```c
static ngx_int_t
ngx_event_process_init(ngx_cycle_t *cycle)
{

    ngx_use_accept_mutex;
    
    ngx_queue_init(&ngx_posted_accept_events);
    ngx_queue_init(&ngx_posted_next_events);
    ngx_queue_init(&ngx_posted_events);
    
    
    ngx_event_timer_init
    
    
    
}
```


```c
// event/ngx_event.c
#define DEFAULT_CONNECTIONS  512


extern ngx_module_t ngx_kqueue_module;
extern ngx_module_t ngx_eventport_module;
extern ngx_module_t ngx_devpoll_module;
extern ngx_module_t ngx_epoll_module;
extern ngx_module_t ngx_select_module;
```



## process

ngx_epoll_process_events






## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)
- [epoll](/docs/CS/OS/Linux/IO/epoll.md)
- [Processes 知识地图](/docs/CS/OS/Linux/proc/README.md)
