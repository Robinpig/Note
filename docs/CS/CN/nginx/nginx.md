## Introduction

[nginx [engine x]](https://nginx.org/en/) is an HTTP and reverse proxy server, a mail proxy server, and a generic TCP/UDP proxy server, originally written by Igor Sysoev.


### Install NGINX

[Installing NGINX and NGINX Plus](https://docs.nginx.com/nginx/admin-guide/installing-nginx/)


Dockerfile
```dockerfile
FROM dockerproxy.cn/ubuntu:22.04

EXPOSE 80

RUN apt-get update 
RUN apt install -y init perl wget vim gcc libxslt1-dev libxml2-dev zlib1g-dev libpcre3-dev libbz2-dev libssl-dev make systemd

RUN cd /usr/src && wget https://nginx.org/download/nginx-1.22.0.tar.gz && tar -xf nginx-1.22.0.tar.gz && rm -f nginx-1.22.0.tar.gz
RUN cd /usr/src && wget http://labs.frickle.com/files/ngx_cache_purge-2.3.tar.gz && tar -xf ngx_cache_purge-2.3.tar.gz && rm -f ngx_cache_purge-2.3.tar.gz
RUN cd /usr/src/nginx-1.22.0 && wget https://github.com/openssl/openssl/releases/download/openssl-3.0.7/openssl-3.0.7.tar.gz && tar -xf openssl-3.0.7.tar.gz && rm -f openssl-3.0.7.tar.gz
RUN rm -f /usr/src/ngx_cache_purge-2.3.tar.gz
RUN mkdir /usr/local/nginx

RUN cd /usr/src/nginx-1.22.0 && ./configure  \
    --conf-path=/etc/nginx/nginx.conf  --prefix=/usr/local/nginx \
    --error-log-path=/var/log/nginx/error.log --http-log-path=/var/log/nginx/access.log \
    --pid-path=/run/nginx.pid \
    --with-cc-opt="-static -static-libgcc" \
    --with-ld-opt="-static" --with-cpu-opt=generic --with-pcre \
    --with-mail --with-ipv6 --with-poll_module --with-select_module \
    --with-select_module --with-poll_module \
    --with-http_ssl_module --with-http_realip_module \
    --with-http_v2_module \
    --with-http_addition_module --with-http_sub_module --with-http_dav_module \
    --with-http_flv_module --with-http_mp4_module --with-http_gunzip_module \
    --with-http_gzip_static_module --with-http_auth_request_module \
    --with-http_random_index_module --with-http_secure_link_module \
    --with-http_degradation_module --with-http_stub_status_module \
    --with-mail --with-mail_ssl_module --with-openssl=./openssl-3.0.7 \
    --add-module=../ngx_cache_purge-2.3  \
    && make && make install \
	&& ln -s /usr/local/nginx/sbin/nginx /usr/local/sbin/


COPY nginx.service /lib/systemd/system

RUN systemctl enable nginx.service
```


nginx.service
```shell
[Unit]
Description=The NGINX HTTP and reverse proxy server
After=syslog.target network.target remote-fs.target nss-lookup.target

[Service]
Type=forking
PIDFile=/run/nginx.pid
ExecStartPre=/usr/local/sbin/nginx -t
ExecStart=/usr/local/sbin/nginx
ExecReload=/bin/kill -s HUP $MAINPID
ExecStop=/bin/kill -s QUIT $MAINPID
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```


```shell
docker build -t nginx:1.22.0 .

docker run --rm --name nginx-builder -p 80:80  -itd --privileged nginx:1.22.0 /usr/sbin/init /bin/sh -c systemctl start nginx

```

需要的一些依赖环境
```shell
gcc pcre pcre-devel zlib zlib-devel openssl openssl-devel
```

> 下载路径https://nginx.org/download/
> 
```shell
# download source code && tar
wget https://nginx.org/download/nginx-1.27.0.tar.gz

./configure --prefix=/usr/local/nginx  --with-http_ssl_module --with-http_v2_module --with-stream
vim objs/Makefile
# 修改优化选项 -O ==> -O0
# CFLAGS = -pipe -O0 -W -Wall -Wpointer-arith -Wno-unused-parameter -Werror -g

# 重新编译安装
make && make install
```


```shell
gdb /usr/local/nginx/sbin/nginx
# 设置 gdb 调试子进程模式。
set follow-fork-mode child
set detach-on-fork off
# 设置断点
b ngx_event_accept
# 运行
r
```
telnet
```shell
telnet 127.0.0.1 80

```



## Architecture

Src packages:

- core   
- event  
- http   
- mail   
- misc   
- os     
- stream


<div style="text-align: center;">

![nginx's architecture](./img/architecture.png)

</div>

<p style="text-align: center;">
Fig.1. nginx's architecture.
</p>

Architecture and scalability
- One master and several worker processes; worker processes run under an unprivileged user;
- Flexible configuration;
- Reconfiguration and upgrade of an executable without interruption of the client servicing;
- Support for kqueue (FreeBSD 4.1+), epoll (Linux 2.6+), /dev/poll (Solaris 7 11/99+), event ports (Solaris 10), select, and poll;
- The support of the various kqueue features including EV_CLEAR, EV_DISABLE (to temporarily disable events), NOTE_LOWAT, EV_EOF, number of available data, error codes;
- The support of various epoll features including EPOLLRDHUP (Linux 2.6.17+, glibc 2.8+) and EPOLLEXCLUSIVE (Linux 4.5+, glibc 2.24+);
- sendfile (FreeBSD 3.1+, Linux 2.2+, macOS 10.5+), sendfile64 (Linux 2.4.21+), and sendfilev (Solaris 8 7/01+) support;
- File AIO (FreeBSD 4.3+, Linux 2.6.22+);
- DIRECTIO (FreeBSD 4.4+, Linux 2.4+, Solaris 2.6+, macOS);
- Accept-filters (FreeBSD 4.1+, NetBSD 5.0+) and TCP_DEFER_ACCEPT (Linux 2.4+) support;
- 10,000 inactive HTTP keep-alive connections take about 2.5M memory;
- Data copy operations are kept to a minimum.

### process model
NGINX uses a predictable process model that is tuned to the available hardware resources:

- The master process performs the privileged operations such as reading configuration and binding to ports, and then creates a small number of child processes (the next three types).
- The cache loader process runs at startup to load the disk‑based cache into memory, and then exits. It is scheduled conservatively, so its resource demands are low.
- The cache manager process runs periodically and prunes entries from the disk caches to keep them within the configured sizes.
- The worker processes do all of the work! They handle network connections, read and write content to disk, and communicate with upstream servers.

The NGINX configuration recommended in most cases – running one worker process per CPU core – makes the most efficient use of hardware resources. You configure it by setting the parameter on the directive:autoworker_processes

When an NGINX server is active, only the worker processes are busy. 
Each worker process handles multiple connections in a nonblocking fashion, reducing the number of context switches.

Each worker process is single‑threaded and runs independently, grabbing new connections and processing them. 
The processes can communicate using shared memory for shared cache data, session persistence data, and other shared resources.





一旦master进程接收到重新加载配置的信号，它将检查新配置文件的语法是否正确，并尝试应用其中提供的配置。

- 如果成功，master进程将启动新的worker进程，并发送消息给旧的worker进程，要求他们shutdown 旧的worker进程在接收到关闭命令后，停止接受新的连接，直到所有之前已经接受的连接全部处理完为止。之后，旧的worker进程退出
- 否则，master进程将回滚所做的更改，并继续使用旧配置。



nginx的master进程的进程ID，默认情况下，放在nginx.pid文件中，该文件所在的目录一般是/usr/local/nginx/logs 或者 /var/run


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
   - ngx_open_listening_sockets
 - ngx_master_process_cycle
   - ngx_start_worker_processes
     - ngx_worker_process_cycle
       - ngx_process_events_and_timers
   - ngx_start_cache_manager_processes 
   - ngx_init_cycle
   
### master cycle

```c

void
ngx_master_process_cycle(ngx_cycle_t *cycle)
{
    char              *title;
    u_char            *p;
    size_t             size;
    ngx_int_t          i;
    ngx_uint_t         n, sigio;
    sigset_t           set;
    struct itimerval   itv;
    ngx_uint_t         live;
    ngx_msec_t         delay;
    ngx_listening_t   *ls;
    ngx_core_conf_t   *ccf;

    sigemptyset(&set);
    sigaddset(&set, SIGCHLD);
    sigaddset(&set, SIGALRM);
    sigaddset(&set, SIGIO);
    sigaddset(&set, SIGINT);
    sigaddset(&set, ngx_signal_value(NGX_RECONFIGURE_SIGNAL));
    sigaddset(&set, ngx_signal_value(NGX_REOPEN_SIGNAL));
    sigaddset(&set, ngx_signal_value(NGX_NOACCEPT_SIGNAL));
    sigaddset(&set, ngx_signal_value(NGX_TERMINATE_SIGNAL));
    sigaddset(&set, ngx_signal_value(NGX_SHUTDOWN_SIGNAL));
    sigaddset(&set, ngx_signal_value(NGX_CHANGEBIN_SIGNAL));

    if (sigprocmask(SIG_BLOCK, &set, NULL) == -1) {
        ngx_log_error(NGX_LOG_ALERT, cycle->log, ngx_errno,
                      "sigprocmask() failed");
    }

    sigemptyset(&set);


    size = sizeof(master_process);

    for (i = 0; i < ngx_argc; i++) {
        size += ngx_strlen(ngx_argv[i]) + 1;
    }

    title = ngx_pnalloc(cycle->pool, size);
    if (title == NULL) {
        /* fatal */
        exit(2);
    }

    p = ngx_cpymem(title, master_process, sizeof(master_process) - 1);
    for (i = 0; i < ngx_argc; i++) {
        *p++ = ' ';
        p = ngx_cpystrn(p, (u_char *) ngx_argv[i], size);
    }

    ngx_setproctitle(title);


    ccf = (ngx_core_conf_t *) ngx_get_conf(cycle->conf_ctx, ngx_core_module);

    ngx_start_worker_processes(cycle, ccf->worker_processes,
                               NGX_PROCESS_RESPAWN);
    ngx_start_cache_manager_processes(cycle, 0);

    ngx_new_binary = 0;
    delay = 0;
    sigio = 0;
    live = 1;

    for ( ;; ) {
        if (delay) {
            if (ngx_sigalrm) {
                sigio = 0;
                delay *= 2;
                ngx_sigalrm = 0;
            }

            itv.it_interval.tv_sec = 0;
            itv.it_interval.tv_usec = 0;
            itv.it_value.tv_sec = delay / 1000;
            itv.it_value.tv_usec = (delay % 1000 ) * 1000;

            if (setitimer(ITIMER_REAL, &itv, NULL) == -1) {
                ngx_log_error(NGX_LOG_ALERT, cycle->log, ngx_errno,
                              "setitimer() failed");
            }
        }

        sigsuspend(&set);

        ngx_time_update();

        if (ngx_reap) {
            ngx_reap = 0;
            ngx_log_debug0(NGX_LOG_DEBUG_EVENT, cycle->log, 0, "reap children");

            live = ngx_reap_children(cycle);
        }

        if (!live && (ngx_terminate || ngx_quit)) {
            ngx_master_process_exit(cycle);
        }

        if (ngx_terminate) {
            if (delay == 0) {
                delay = 50;
            }

            if (sigio) {
                sigio--;
                continue;
            }

            sigio = ccf->worker_processes + 2 /* cache processes */;

            if (delay > 1000) {
                ngx_signal_worker_processes(cycle, SIGKILL);
            } else {
                ngx_signal_worker_processes(cycle,
                                       ngx_signal_value(NGX_TERMINATE_SIGNAL));
            }

            continue;
        }

        if (ngx_quit) {
            ngx_signal_worker_processes(cycle,
                                        ngx_signal_value(NGX_SHUTDOWN_SIGNAL));

            ls = cycle->listening.elts;
            for (n = 0; n < cycle->listening.nelts; n++) {
                if (ngx_close_socket(ls[n].fd) == -1) {
                    ngx_log_error(NGX_LOG_EMERG, cycle->log, ngx_socket_errno,
                                  ngx_close_socket_n " %V failed",
                                  &ls[n].addr_text);
                }
            }
            cycle->listening.nelts = 0;

            continue;
        }

        if (ngx_reconfigure) {
            ngx_reconfigure = 0;

            if (ngx_new_binary) {
                ngx_start_worker_processes(cycle, ccf->worker_processes,
                                           NGX_PROCESS_RESPAWN);
                ngx_start_cache_manager_processes(cycle, 0);
                ngx_noaccepting = 0;

                continue;
            }

            ngx_log_error(NGX_LOG_NOTICE, cycle->log, 0, "reconfiguring");

            cycle = ngx_init_cycle(cycle);
            if (cycle == NULL) {
                cycle = (ngx_cycle_t *) ngx_cycle;
                continue;
            }

            ngx_cycle = cycle;
            ccf = (ngx_core_conf_t *) ngx_get_conf(cycle->conf_ctx,
                                                   ngx_core_module);
            ngx_start_worker_processes(cycle, ccf->worker_processes,
                                       NGX_PROCESS_JUST_RESPAWN);
            ngx_start_cache_manager_processes(cycle, 1);

            /* allow new processes to start */
            ngx_msleep(100);

            live = 1;
            ngx_signal_worker_processes(cycle,
                                        ngx_signal_value(NGX_SHUTDOWN_SIGNAL));
        }

        if (ngx_restart) {
            ngx_restart = 0;
            ngx_start_worker_processes(cycle, ccf->worker_processes,
                                       NGX_PROCESS_RESPAWN);
            ngx_start_cache_manager_processes(cycle, 0);
            live = 1;
        }

        if (ngx_reopen) {
            ngx_reopen = 0;
            ngx_log_error(NGX_LOG_NOTICE, cycle->log, 0, "reopening logs");
            ngx_reopen_files(cycle, ccf->user);
            ngx_signal_worker_processes(cycle,
                                        ngx_signal_value(NGX_REOPEN_SIGNAL));
        }

        if (ngx_change_binary) {
            ngx_change_binary = 0;
            ngx_log_error(NGX_LOG_NOTICE, cycle->log, 0, "changing binary");
            ngx_new_binary = ngx_exec_new_binary(cycle, ngx_argv);
        }

        if (ngx_noaccept) {
            ngx_noaccept = 0;
            ngx_noaccepting = 1;
            ngx_signal_worker_processes(cycle,
                                        ngx_signal_value(NGX_SHUTDOWN_SIGNAL));
        }
    }
}
```

### worker cycle


```c

static void
ngx_start_worker_processes(ngx_cycle_t *cycle, ngx_int_t n, ngx_int_t type)
{
    ngx_int_t      i;
    ngx_channel_t  ch;

    ngx_memzero(&ch, sizeof(ngx_channel_t));

    ch.command = NGX_CMD_OPEN_CHANNEL;

    for (i = 0; i < n; i++) {

        ngx_spawn_process(cycle, ngx_worker_process_cycle,
                          (void *) (intptr_t) i, "worker process", type);

        ch.pid = ngx_processes[ngx_process_slot].pid;
        ch.slot = ngx_process_slot;
        ch.fd = ngx_processes[ngx_process_slot].channel[0];

        ngx_pass_open_channel(cycle, &ch);
    }
}
```
create worker process

worker progress set ngx_channel = ngx_processes[s].channel[1];

invoke [fork](/docs/CS/OS/Linux/processes.md/id=fork)

```c

ngx_pid_t
ngx_spawn_process(ngx_cycle_t *cycle, ngx_spawn_proc_pt proc, void *data,
    char *name, ngx_int_t respawn)
{
    u_long     on;
    ngx_pid_t  pid;
    ngx_int_t  s;

    if (respawn >= 0) {
        s = respawn;

    } else {
        for (s = 0; s < ngx_last_process; s++) {
            if (ngx_processes[s].pid == -1) {
                break;
            }
        }

        if (s == NGX_MAX_PROCESSES) {
            ngx_log_error(NGX_LOG_ALERT, cycle->log, 0,
                          "no more than %d processes can be spawned",
                          NGX_MAX_PROCESSES);
            return NGX_INVALID_PID;
        }
    }


    if (respawn != NGX_PROCESS_DETACHED) {

        /* Solaris 9 still has no AF_LOCAL */

        if (socketpair(AF_UNIX, SOCK_STREAM, 0, ngx_processes[s].channel) == -1)
        {
            ngx_log_error(NGX_LOG_ALERT, cycle->log, ngx_errno,
                          "socketpair() failed while spawning \"%s\"", name);
            return NGX_INVALID_PID;
        }

        ngx_log_debug2(NGX_LOG_DEBUG_CORE, cycle->log, 0,
                       "channel %d:%d",
                       ngx_processes[s].channel[0],
                       ngx_processes[s].channel[1]);

        if (ngx_nonblocking(ngx_processes[s].channel[0]) == -1) {
            ngx_log_error(NGX_LOG_ALERT, cycle->log, ngx_errno,
                          ngx_nonblocking_n " failed while spawning \"%s\"",
                          name);
            ngx_close_channel(ngx_processes[s].channel, cycle->log);
            return NGX_INVALID_PID;
        }

        if (ngx_nonblocking(ngx_processes[s].channel[1]) == -1) {
            ngx_log_error(NGX_LOG_ALERT, cycle->log, ngx_errno,
                          ngx_nonblocking_n " failed while spawning \"%s\"",
                          name);
            ngx_close_channel(ngx_processes[s].channel, cycle->log);
            return NGX_INVALID_PID;
        }

        on = 1;
        if (ioctl(ngx_processes[s].channel[0], FIOASYNC, &on) == -1) {
            ngx_log_error(NGX_LOG_ALERT, cycle->log, ngx_errno,
                          "ioctl(FIOASYNC) failed while spawning \"%s\"", name);
            ngx_close_channel(ngx_processes[s].channel, cycle->log);
            return NGX_INVALID_PID;
        }

        if (fcntl(ngx_processes[s].channel[0], F_SETOWN, ngx_pid) == -1) {
            ngx_log_error(NGX_LOG_ALERT, cycle->log, ngx_errno,
                          "fcntl(F_SETOWN) failed while spawning \"%s\"", name);
            ngx_close_channel(ngx_processes[s].channel, cycle->log);
            return NGX_INVALID_PID;
        }

        if (fcntl(ngx_processes[s].channel[0], F_SETFD, FD_CLOEXEC) == -1) {
            ngx_log_error(NGX_LOG_ALERT, cycle->log, ngx_errno,
                          "fcntl(FD_CLOEXEC) failed while spawning \"%s\"",
                           name);
            ngx_close_channel(ngx_processes[s].channel, cycle->log);
            return NGX_INVALID_PID;
        }

        if (fcntl(ngx_processes[s].channel[1], F_SETFD, FD_CLOEXEC) == -1) {
            ngx_log_error(NGX_LOG_ALERT, cycle->log, ngx_errno,
                          "fcntl(FD_CLOEXEC) failed while spawning \"%s\"",
                           name);
            ngx_close_channel(ngx_processes[s].channel, cycle->log);
            return NGX_INVALID_PID;
        }

        ngx_channel = ngx_processes[s].channel[1];

    } else {
        ngx_processes[s].channel[0] = -1;
        ngx_processes[s].channel[1] = -1;
    }

    ngx_process_slot = s;

    /** fork **/
    pid = fork();

    switch (pid) {

    case -1:
        ngx_log_error(NGX_LOG_ALERT, cycle->log, ngx_errno,
                      "fork() failed while spawning \"%s\"", name);
        ngx_close_channel(ngx_processes[s].channel, cycle->log);
        return NGX_INVALID_PID;

    case 0:
        ngx_parent = ngx_pid;
        ngx_pid = ngx_getpid();
        proc(cycle, data);
        break;

    default:
        break;
    }

    ngx_log_error(NGX_LOG_NOTICE, cycle->log, 0, "start %s %P", name, pid);

    ngx_processes[s].pid = pid;
    ngx_processes[s].exited = 0;

    if (respawn >= 0) {
        return pid;
    }

    ngx_processes[s].proc = proc;
    ngx_processes[s].data = data;
    ngx_processes[s].name = name;
    ngx_processes[s].exiting = 0;

    switch (respawn) {

    case NGX_PROCESS_NORESPAWN:
        ngx_processes[s].respawn = 0;
        ngx_processes[s].just_spawn = 0;
        ngx_processes[s].detached = 0;
        break;

    case NGX_PROCESS_JUST_SPAWN:
        ngx_processes[s].respawn = 0;
        ngx_processes[s].just_spawn = 1;
        ngx_processes[s].detached = 0;
        break;

    case NGX_PROCESS_RESPAWN:
        ngx_processes[s].respawn = 1;
        ngx_processes[s].just_spawn = 0;
        ngx_processes[s].detached = 0;
        break;

    case NGX_PROCESS_JUST_RESPAWN:
        ngx_processes[s].respawn = 1;
        ngx_processes[s].just_spawn = 1;
        ngx_processes[s].detached = 0;
        break;

    case NGX_PROCESS_DETACHED:
        ngx_processes[s].respawn = 0;
        ngx_processes[s].just_spawn = 0;
        ngx_processes[s].detached = 1;
        break;
    }

    if (s == ngx_last_process) {
        ngx_last_process++;
    }

    return pid;
}
```

ngx_worker_process_cycle
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
void
ngx_process_events_and_timers(ngx_cycle_t *cycle)
{

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


### signal



## Configuration

### config



p


// core/ngx_conf_file.c
ngx_conf_parse

ngx_conf_handler


## Tuning

enable coredump
```config
worker_rlimit_core 500m
worker_directory /tmp
```

```shell
gdb /usr/sbin/nginx <core file>
```

## Links

- [Computer Network](/docs/CS/CN/CN.md)


## References

1. [](https://www.aosabook.org/en/nginx.html)
2. [Inside NGINX: How We Designed for Performance & Scale](https://www.nginx.com/blog/inside-nginx-how-we-designed-for-performance-scale/)