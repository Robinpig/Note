## Introduction

[nginx [engine x]](https://nginx.org/en/) is an HTTP and reverse proxy server, a mail proxy server, and a generic TCP/UDP proxy server, originally written by Igor Sysoev.


[Installing NGINX and NGINX Plus](https://docs.nginx.com/nginx/admin-guide/installing-nginx/)


## Architecture

Src packages:

- core   
- event  
- http   
- mail   
- misc   
- os     
- stream


## Struct


### queue

```c

typedef struct ngx_queue_s  ngx_queue_t;

struct ngx_queue_s {
    ngx_queue_t  *prev;
    ngx_queue_t  *next;
};


#define ngx_queue_init(q)                                                   
    (q)->prev = q;                                                          
    (q)->next = q
```

insert

```c
#define ngx_queue_insert_head(h, x)                                           
    (x)->next = (h)->next;                                                    
    (x)->next->prev = x;                                                      
    (x)->prev = h;                                                            
    (h)->next = x


#define ngx_queue_insert_after   ngx_queue_insert_head


#define ngx_queue_insert_tail(h, x)                                           
    (x)->prev = (h)->prev;                                                    
    (x)->prev->next = x;                                                      
    (x)->next = h;                                                            
    (h)->prev = x


#define ngx_queue_head(h)                                                     
    (h)->next
```


### rbtree


### radix tree

```c
// core/ngx_radix_tree.h
typedef struct ngx_radix_node_s  ngx_radix_node_t;

struct ngx_radix_node_s {
    ngx_radix_node_t  *right;
    ngx_radix_node_t  *left;
    ngx_radix_node_t  *parent;
    uintptr_t          value;
};


typedef struct {
    ngx_radix_node_t  *root;
    ngx_pool_t        *pool;
    ngx_radix_node_t  *free;
    char              *start;
    size_t             size;
} ngx_radix_tree_t;
```

## Module


```c

struct ngx_module_s {
    ngx_uint_t            ctx_index;
    ngx_uint_t            index;

    char                 *name;

    ngx_uint_t            spare0;
    ngx_uint_t            spare1;

    ngx_uint_t            version;
    const char           *signature;

    void                 *ctx; // module ctx
    ngx_command_t        *commands;
    ngx_uint_t            type;

    ngx_int_t           (*init_master)(ngx_log_t *log);

    ngx_int_t           (*init_module)(ngx_cycle_t *cycle);

    ngx_int_t           (*init_process)(ngx_cycle_t *cycle);
    ngx_int_t           (*init_thread)(ngx_cycle_t *cycle);
    void                (*exit_thread)(ngx_cycle_t *cycle);
    void                (*exit_process)(ngx_cycle_t *cycle);

    void                (*exit_master)(ngx_cycle_t *cycle);

    uintptr_t             spare_hook0;
    uintptr_t             spare_hook1;
    uintptr_t             spare_hook2;
    uintptr_t             spare_hook3;
    uintptr_t             spare_hook4;
    uintptr_t             spare_hook5;
    uintptr_t             spare_hook6;
    uintptr_t             spare_hook7;
};
```

core

```c
static ngx_core_module_t  ngx_core_module_ctx = {
    ngx_string("core"),
    ngx_core_module_create_conf,
    ngx_core_module_init_conf
};

typedef struct {
    ngx_str_t             name;
    void               *(*create_conf)(ngx_cycle_t *cycle);
    char               *(*init_conf)(ngx_cycle_t *cycle, void *conf);
} ngx_core_module_t;
```

http

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


### Load Balance

#### default
```nginx
# default
upstream real_serer{
	server 192.168.1.100:8000;
    server 192.168.1.100:8001;
}
```
#### weight
```nginx
# weight
upstream real_serer{
	server 192.168.1.100:8000 weight=1;
    server 192.168.1.100:8001 weight=2;
}
```
#### ip hash
```nginx
# ip_hash
upstream bakend {  
    ip_hash;  
    server 192.168.0.1:8000;  
    server 192.168.0.1:8001;  
} 
```
#### fair
```nginx
# fair
upstream bakend {  
    server 192.168.0.1:8000;  
    server 192.168.0.1:8001; 
    fair;
} 
```
#### uri hash
```nginx
# url hash
upstream bakend {  
    server 192.168.0.1:8000;  
    server 192.168.0.1:8001; 
    hash $request_uri;  
    hash_method crc32; 
} 
```

consistent hash

一致性hash就是创建出n个虚拟节点，n个虚拟节点构成一个环，从n个虚拟节点中，挑选出一些节点当成真实的upstream server节点。构成一个每次将计算得到的hash%n，得到请求分配的虚拟节点的位置c，从位置c顺时针移动，获得离c最近的真实upstream server节点

```nginx
# url hash
upstream bakend {  
  	consistent_hash $request_uri;
    server 192.168.0.1:8000;  
    server 192.168.0.1:8001; 
} 
```

fail retry

```nginx
# weight
upstream real_serer{
	server 192.168.1.100:8000 weight=1 max_fails=2 fail_timeout=60s;
  server 192.168.1.100:8001 weight=2 max_fails=2 fail_timeout=60s;
}

```



limit

limit_req_zone

```nginx

http {
  	# leaky bucket not set burst 
    limit_req_zone $binary_remote_addr zone=one:10m rate=1r/s; 
    server {
        location /search/ {
      			# token bucket set burst
            limit_req zone=one burst=5 nodelay;
        }
}  
```



limit_conn_zone, need **ngx_http_limit_conn_module**

```nginx
  limit_conn_zone $binary_remote_addr zone=addr:10m;

  server {
      location /download/ {
              limit_conn addr 1;
      }
  }
```

白名单 黑名单

### Cache


### ssl

```shell
mkdir /etc/cert

cd /etc/cert/

openssl genrsa -out yh.com.key 2048

openssl req -new -key yh.com.key -out yh.com.csr

Country Name (2 letter code) [XX]:
State or Province Name (full name) []:
Locality Name (eg, city) [Default City]:
Organization Name (eg, company) [Default Company Ltd]:
Organizational Unit Name (eg, section) []:
Common Name (eg, your name or your server's hostname) []:
Email Address []:
A challenge password []:
An optional company name []:

openssl x509 -req -days 3650 -in yh.com.csr -signkey yh.com.key -out yh.com.crt

```


## main

main
 - ngx_time_init
 - ngx_regex_init
 - ngx_log_init
 - ngx_create_pool
 - ngx_os_init
 - ngx_init_cycle
   - ngx_conf_parse
 - ngx_master_process_cycle
   - ngx_start_worker_processes
     - ngx_worker_process_cycle
       - ngx_process_events_and_timers
   - ngx_start_cache_manager_processes 
   - ngx_init_cycle
    

### worker cycle

```c

static void
ngx_worker_process_cycle(ngx_cycle_t *cycle, void *data)
{
    ngx_int_t worker = (intptr_t) data;

    ngx_process = NGX_PROCESS_WORKER;
    ngx_worker = worker;

    ngx_worker_process_init(cycle, worker);

    ngx_setproctitle("worker process");

    for ( ;; ) {

        if (ngx_exiting) {
            if (ngx_event_no_timers_left() == NGX_OK) {
                ngx_log_error(NGX_LOG_NOTICE, cycle->log, 0, "exiting");
                ngx_worker_process_exit(cycle);
            }
        }

        ngx_log_debug0(NGX_LOG_DEBUG_EVENT, cycle->log, 0, "worker cycle");

        ngx_process_events_and_timers(cycle);

        if (ngx_terminate) {
            ngx_log_error(NGX_LOG_NOTICE, cycle->log, 0, "exiting");
            ngx_worker_process_exit(cycle);
        }

        if (ngx_quit) {
            ngx_quit = 0;
            ngx_log_error(NGX_LOG_NOTICE, cycle->log, 0,
                          "gracefully shutting down");
            ngx_setproctitle("worker process is shutting down");

            if (!ngx_exiting) {
                ngx_exiting = 1;
                ngx_set_shutdown_timer(cycle);
                ngx_close_listening_sockets(cycle);
                ngx_close_idle_connections(cycle);
            }
        }

        if (ngx_reopen) {
            ngx_reopen = 0;
            ngx_log_error(NGX_LOG_NOTICE, cycle->log, 0, "reopening logs");
            ngx_reopen_files(cycle, -1);
        }
    }
}
```

#### process_events_and_timers

```c
// 
void
ngx_process_events_and_timers(ngx_cycle_t *cycle)
{
    ngx_uint_t  flags;
    ngx_msec_t  timer, delta;

    if (ngx_timer_resolution) {
        timer = NGX_TIMER_INFINITE;
        flags = 0;

    } else {
        timer = ngx_event_find_timer();
        flags = NGX_UPDATE_TIME;
    }

    if (ngx_use_accept_mutex) {
        if (ngx_accept_disabled > 0) {
            ngx_accept_disabled--;

        } else {
            if (ngx_trylock_accept_mutex(cycle) == NGX_ERROR) {
                return;
            }

            if (ngx_accept_mutex_held) {
                flags |= NGX_POST_EVENTS;

            } else {
                if (timer == NGX_TIMER_INFINITE
                    || timer > ngx_accept_mutex_delay)
                {
                    timer = ngx_accept_mutex_delay;
                }
            }
        }
    }

    if (!ngx_queue_empty(&ngx_posted_next_events)) {
        ngx_event_move_posted_next(cycle);
        timer = 0;
    }

    delta = ngx_current_msec;

    (void) ngx_process_events(cycle, timer, flags);

    delta = ngx_current_msec - delta;

    ngx_log_debug1(NGX_LOG_DEBUG_EVENT, cycle->log, 0,
                   "timer delta: %M", delta);

    ngx_event_process_posted(cycle, &ngx_posted_accept_events);

    if (ngx_accept_mutex_held) {
        ngx_shmtx_unlock(&ngx_accept_mutex);
    }

    if (delta) {
        ngx_event_expire_timers();
    }

    ngx_event_process_posted(cycle, &ngx_posted_events);
}
```

#### ngx_process_events

ngx_event_actions_t see [Event](/docs/CS/CN/nginx/event.md)

## Configuration

// core/ngx_conf_file.c
ngx_conf_parse

ngx_conf_handler




## Links

- [Computer Network](/docs/CS/CN/CN.md)
