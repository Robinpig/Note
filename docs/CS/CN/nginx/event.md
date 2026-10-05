## Introduction

事件模块是对内核 I/O 多路复用机制（[epoll](/docs/CS/OS/Linux/IO/epoll.md) 等）的封装：worker 在一个 `for(;;)` 循环里反复调用 `ngx_process_events_and_timers()`，由它调用具体事件模块的 `ngx_epoll_process_events` 收集就绪事件，再分发给各个 handler。整个 nginx 的"高并发"就建立在这样一个单线程循环上。

理解这个循环要回答五个问题：**连接对象从哪来**（连接池）、**事件怎么注册**（事件模块抽象）、**新连接怎么接**（accept 与惊群）、**延迟任务怎么排**（posted events 队列）、**时间从哪来**（定时器与缓存时间）。本文按这个顺序展开，进程模型部分见 [nginx](/docs/CS/CN/nginx/nginx.md)。

## 数据结构

### `ngx_event_t`

```c
// event/ngx_event.h（节选）
struct ngx_event_s {
    void            *data;             /* 通常指向宿主 ngx_connection_t */

    unsigned         write:1;          /* 写事件 */
    unsigned         accept:1;         /* 监听套接字的读事件 */

    unsigned         instance:1;       /* ★ 用于识别"陈旧事件"，见下文 */

    unsigned         active:1;         /* 已注册到 epoll */
    unsigned         ready:1;          /* 已就绪（epoll 返回过） */
    unsigned         timedout:1;
    unsigned         timer_set:1;      /* 挂在定时器红黑树上 */
    unsigned         delayed:1;        /* 被限流延迟（limit_req 用） */
    unsigned         pending_eof:1;    /* EPOLLRDHUP：对端半关闭 */
    unsigned         posted:1;         /* 已入 posted 队列 */
    unsigned         closed:1;
    unsigned         channel:1;        /* master↔worker 的 unix socket 通道 */
    unsigned         resolver:1;       /* resolver 内部连接 */
    unsigned         cancelable:1;     /* 不阻止 worker 优雅退出 */

    ngx_event_handler_pt  handler;     /* 事件回调 */
    ngx_rbtree_node_t     timer;       /* 定时器红黑树节点 */
    ngx_queue_t           queue;       /* posted 队列节点 */
    ...
};
```

`instance` 位是理解 epoll 封装的关键，后面专门讲。

### `ngx_connection_t`

一个连接对象包含两条 fd 之外的全部状态：读写事件、内存池、缓冲区、日志、以及 `data`（指向上层协议对象，如 `ngx_http_request_t`）。

连接不是按需 `malloc` 的，而是**启动时一次性分配好整个数组**，用空闲链表串起来：

```c
// event/ngx_event.c
#define DEFAULT_CONNECTIONS  512

cycle->connections = ngx_alloc(sizeof(ngx_connection_t) * cycle->connection_n, cycle->log);

rev = cycle->read_events;
for (i = 0; i < cycle->connection_n; i++) {
    rev[i].closed = 1;
    rev[i].instance = 1;            /* 读事件 instance 初值 = 1 */
}
wev = cycle->write_events;
for (i = 0; i < cycle->connection_n; i++) {
    wev[i].closed = 1;              /* 写事件 instance 初值 = 0 */
}

i = cycle->connection_n;
next = NULL;
do {
    i--;
    c[i].data = next;               /* 等价于 c[i].data = &c[i+1] */
    c[i].read = &cycle->read_events[i];
    c[i].write = &cycle->write_events[i];
    c[i].fd = (ngx_socket_t) -1;
    next = &c[i];
} while (i);

cycle->free_connections = next;     /* == &c[0] */
cycle->free_connection_n = cycle->connection_n;
```

**倒序**构造单向链表，头节点是 `c[0]`。分配时从头部取（`ngx_get_connection`），回收时头插（`ngx_free_connection`）。这意味着**新 accept 的连接总是拿到最近释放的那个连接对象**，对 CPU cache 友好。

每次取出一个连接时，读写事件的 `instance` 会**同时翻转**：

```c
// core/ngx_connection.c
c->read->instance = !instance;
c->write->instance = !instance;
```

## 事件模块抽象

```c
typedef struct {
    ngx_str_t              *name;
    void                 *(*create_conf)(ngx_cycle_t *cycle);
    char                 *(*init_conf)(ngx_cycle_t *cycle, void *conf);
    ngx_event_actions_t     actions;      /* 十一个动作 */
} ngx_event_module_t;
```

`ngx_event_actions_t` 是可插拔的接口，epoll 的实现如下：

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

可选实现在 `ngx_event.c` 里声明为 extern，`use` 指令或编译期顺序决定用哪个：

```c
extern ngx_module_t ngx_kqueue_module;
extern ngx_module_t ngx_eventport_module;
extern ngx_module_t ngx_devpoll_module;
extern ngx_module_t ngx_epoll_module;
extern ngx_module_t ngx_select_module;
```

Linux 上 epoll 是最优解：`O(1)` 的就绪通知、支持 `EPOLLRDHUP`（对端关闭）与 `EPOLLEXCLUSIVE`（避免惊群）。

## worker 的事件初始化

`ngx_event_process_init()` 在每个 worker 启动时执行，是整个事件子系统的装配现场。

### accept mutex 的启用条件

```c
ccf = (ngx_core_conf_t *) ngx_get_conf(cycle->conf_ctx, ngx_core_module);
ecf = ngx_event_get_conf(cycle->conf_ctx, ngx_event_core_module);

if (ccf->master && ccf->worker_processes > 1 && ecf->accept_mutex) {
    ngx_use_accept_mutex = 1;
    ngx_accept_mutex_held = 0;
    ngx_accept_mutex_delay = ecf->accept_mutex_delay;
} else {
    ngx_use_accept_mutex = 0;
}

ngx_use_exclusive_accept = 0;
```

三个条件缺一不可：`master` 模式 + `worker_processes > 1` + `accept_mutex on`。而 **`accept_mutex` 自 1.11.3 起默认就是 `off`**：

```c
ngx_conf_init_value(ecf->multi_accept, 0);
ngx_conf_init_value(ecf->accept_mutex, 0);            /* ← 默认 off */
ngx_conf_init_msec_value(ecf->accept_mutex_delay, 500);
```

> [!WARNING]
> 大量中文资料仍写着"nginx 默认开启 accept mutex 来解决惊群"——这句在 1.11.3 之后是错的。现代 Linux 上 nginx 靠内核的 `EPOLLEXCLUSIVE` 避免惊群，`accept_mutex` 只是历史遗留的 fallback。

### 监听套接字如何注册进事件循环

这是最关键的一段，四种情况**互斥且有优先级**：

```c
#if (NGX_HAVE_REUSEPORT)
    if (ls[i].reuseport) {
        if (ngx_add_event(rev, NGX_READ_EVENT, 0) == NGX_ERROR) return NGX_ERROR;
        continue;                                    /* ① reuseport：每个 worker 独立 socket */
    }
#endif

    if (ngx_use_accept_mutex) {
        continue;                                    /* ② 有锁：先不注册，抢到锁再 enable */
    }

#if (NGX_HAVE_EPOLLEXCLUSIVE)
    if ((ngx_event_flags & NGX_USE_EPOLL_EVENT) && ccf->worker_processes > 1) {
        ngx_use_exclusive_accept = 1;
        if (ngx_add_event(rev, NGX_READ_EVENT, NGX_EXCLUSIVE_EVENT) == NGX_ERROR) {
            return NGX_ERROR;
        }
        continue;                                    /* ③ 无锁 + epoll + 多 worker（默认路径） */
    }
#endif

    if (ngx_add_event(rev, NGX_READ_EVENT, 0) == NGX_ERROR) return NGX_ERROR;  /* ④ 兜底 */
```

| 方案 | 机制 | 谁做负载均衡 | 代价 |
| :-- | :-- | :-- | :-- |
| `SO_REUSEPORT` | 每个 worker 一个独立 listen socket，内核按 4 元组哈希分发 | 内核 | reload 时旧 socket 关闭可能丢少量 SYN；连接迁移（QUIC）需要 eBPF 辅助 |
| `EPOLLEXCLUSIVE` | 所有 worker 监听同一个 fd，但只唤醒其中一个 | 内核（Linux 4.5+） | 早期实现偏向"第一个注册"的 worker，nginx 用定期重排修正 |
| `accept_mutex` | 用户态自旋锁，抢到锁才把 listen fd 加入 epoll | nginx | 抢锁有开销，且受 `accept_mutex_delay`（500ms）影响 |

三者优先级：`reuseport` > `accept_mutex` > `EPOLLEXCLUSIVE` > 普通注册。默认配置（无 reuseport、accept_mutex off、多 worker）走的是 ③。

`EPOLLEXCLUSIVE` 有个已知偏斜：内核通常只唤醒"最早把这个 fd 加入 epoll"的那个 worker，导致绝大部分连接落到第一个 worker。nginx 的补偿办法是**每 accept 16 次就重新注册一次**：

```c
/*
 * Linux with EPOLLEXCLUSIVE usually notifies only the process which
 * was first to add the listening socket to the epoll instance.  As
 * a result most of the connections are handled by the first worker
 * process.  To fix this, we re-add the socket periodically, so other
 * workers will get a chance to accept connections.
 */
if (c->requests++ % 16 != 0 && ngx_accept_disabled <= 0) return;

ngx_del_event(c->read, NGX_READ_EVENT, NGX_DISABLE_EVENT);
ngx_add_event(c->read, NGX_READ_EVENT, NGX_EXCLUSIVE_EVENT);
```

### 监听事件的 handler

```c
if (ls[i].reuseport && ls[i].worker != ngx_worker) continue;   /* 只管自己那一份 */

c = ngx_get_connection(ls[i].fd, cycle->log);
c->type = ls[i].type;
c->listening = &ls[i];
ls[i].connection = c;

rev = c->read;
rev->accept = 1;                      /* ★ 标记为 accept 事件，入队时走高优先队列 */

if (c->type == SOCK_STREAM) {
    rev->handler = ngx_event_accept;
#if (NGX_QUIC)
} else if (ls[i].quic) {
    rev->handler = ngx_quic_recvmsg;
#endif
} else {
    rev->handler = ngx_event_recvmsg;  /* UDP：recvmsg 批量收 */
}
```

### accept mutex 的抢锁与让出

```c
// event/ngx_event_accept.c
ngx_int_t
ngx_trylock_accept_mutex(ngx_cycle_t *cycle)
{
    if (ngx_shmtx_trylock(&ngx_accept_mutex)) {
        if (ngx_accept_mutex_held && ngx_accept_events == 0) return NGX_OK;

        if (ngx_enable_accept_events(cycle) == NGX_ERROR) {   /* 把所有 listen fd 加入 epoll */
            ngx_shmtx_unlock(&ngx_accept_mutex);
            return NGX_ERROR;
        }
        ngx_accept_events = 0;
        ngx_accept_mutex_held = 1;
        return NGX_OK;
    }

    if (ngx_accept_mutex_held) {                 /* 之前持有，现在丢了 */
        if (ngx_disable_accept_events(cycle, 0) == NGX_ERROR) return NGX_ERROR;
        ngx_accept_mutex_held = 0;
    }
    return NGX_OK;
}
```

另一个"让出"机制是 `ngx_accept_disabled`，它解决的是**单个 worker 连接快满了还拼命 accept** 的问题：

```c
// event/ngx_event_accept.c：每次成功 accept 后重新计算
ngx_accept_disabled = ngx_cycle->connection_n / 8 - ngx_cycle->free_connection_n;
```

空闲连接少于总数的 1/8 时该值 > 0，worker 就**放弃抢锁**，并且主循环每轮只给它减 1——于是它要等若干轮才能重新参与竞争，把新连接让给别的 worker。这是 nginx 在"没有全局视图"的情况下做负载均衡的土办法。

```c
if (ngx_use_accept_mutex) {
    if (ngx_accept_disabled > 0) {
        ngx_accept_disabled--;              /* 唯一递减点：主循环每轮减 1 */
    } else {
        ...
    }
}
```

## epoll 封装

### 初始化

```c
ep = epoll_create(cycle->connection_n / 2);     /* size 参数内核已忽略，仅历史兼容 */
...
if (nevents < epcf->events) {
    if (event_list) ngx_free(event_list);
    event_list = ngx_alloc(sizeof(struct epoll_event) * epcf->events, cycle->log);
}
nevents = epcf->events;                          /* 只增不减 */
```

`epoll_events` 默认 **512**，即一次 `epoll_wait` 最多取回 512 个事件；没取完的下一轮继续（epoll 是 LT 语义下的"贪心"模式，nginx 标了 `NGX_USE_GREEDY_EVENT`）。

### 注册事件与 instance 位

```c
ee.events = events | (uint32_t) flags;
ee.data.ptr = (void *) ((uintptr_t) c | ev->instance);     /* ★ instance 编码进 ptr 最低位 */
```

因为 `ngx_connection_t` 是按数组对齐分配的，指针最低位恒为 0，可以借来存 1 bit 信息。它的用途是识别**陈旧事件**：

> 场景：同一个 connection 对象被回收后又分配给新 fd；此时 epoll 里可能还残留着旧 fd 的事件。当这批事件被 `epoll_wait` 取回时，ptr 里编码的 instance 与当前 `ev->instance` 不一致，就能判断"这是旧 fd 的事件，丢弃"。

```c
if ((flags & NGX_EXCLUSIVE_EVENT) && (NGX_HAVE_EPOLLEXCLUSIVE && NGX_HAVE_EPOLLRDHUP)) {
    events &= ~EPOLLRDHUP;      /* EPOLLEXCLUSIVE 与 EPOLLRDHUP 不能同时用 */
}
```

### 处理事件

```c
events = epoll_wait(ep, event_list, (int) nevents, timer);

if (flags & NGX_UPDATE_TIME || ngx_event_timer_alarm) {
    ngx_time_update();                       /* 缓存时间在这里刷新 */
}

for (i = 0; i < events; i++) {
    c = event_list[i].data.ptr;
    instance = (uintptr_t) c & 1;
    c = (ngx_connection_t *) ((uintptr_t) c & (uintptr_t) ~1);
    rev = c->read;

    if (c->fd == -1 || rev->instance != instance) {
        /* the stale event from a file descriptor that was just closed in this iteration */
        continue;                            /* 陈旧事件：跳过 */
    }

    revents = event_list[i].events;

    if (revents & (EPOLLERR|EPOLLHUP)) {
        revents |= EPOLLIN|EPOLLOUT;         /* 出错时强制唤醒读写，让上层能看到错误 */
    }

    if ((revents & EPOLLIN) && rev->active) {
#if (NGX_HAVE_EPOLLRDHUP)
        if (revents & EPOLLRDHUP) {
            rev->pending_eof = 1;            /* 对端半关闭 */
        }
#endif
        rev->ready = 1;
        rev->available = -1;

        if (flags & NGX_POST_EVENTS) {
            queue = rev->accept ? &ngx_posted_accept_events : &ngx_posted_events;
            ngx_post_event(rev, queue);
        } else {
            rev->handler(rev);
        }
    }
    /* 写事件同理 */
}
```

三个设计点：

1. **`EPOLLERR|EPOLLHUP` 被强制补上读写事件**，保证任何错误都会被至少一个 handler 处理，不会静默丢连接；
2. **`revents & EPOLLIN` 之外还要 `rev->active`**，避免处理已被删除的事件；
3. **`POST_EVENTS` 模式**：持锁期间不立即执行 handler，而是入队延后执行——这样锁的持有时间只覆盖"收集事件"，不覆盖"处理请求"。

## accept 流程

```c
// event/ngx_event_accept.c（简化）
if (!(ngx_event_flags & NGX_USE_KQUEUE_EVENT)) {
    ev->available = ecf->multi_accept;      /* 默认 0 */
}

do {
    if (ev->available) { ... }

#if (NGX_HAVE_ACCEPT4)
    if (use_accept4) {
        s = accept4(lc->fd, &sa.sockaddr, &socklen, SOCK_NONBLOCK);
    } else
#endif
    {
        s = accept(lc->fd, &sa.sockaddr, &socklen);
    }

    if (s == (ngx_socket_t) -1) {
        if (err == NGX_EAGAIN) return;                        /* 队列空了，正常退出 */
        if (err == NGX_ECONNABORTED) { if (ev->available) continue; return; }
        if (err == NGX_EMFILE || err == NGX_ENFILE) {         /* fd 用尽 */
            ngx_disable_accept_events(cycle, 1);              /* 暂停 accept */
            if (ngx_use_accept_mutex) {
                ngx_accept_mutex_held = 0;
                ngx_accept_disabled = 1;                      /* 让出一段时间 */
            } else {
                ngx_add_timer(ev, ecf->accept_mutex_delay);
            }
            return;
        }
        ...
    }

    ngx_accept_disabled = ngx_cycle->connection_n / 8 - ngx_cycle->free_connection_n;

    c = ngx_get_connection(s, ev->log);
    if (c == NULL) { ngx_close_socket(s); return; }

    ...
    ls->handler(c);            /* → ngx_http_init_connection / ngx_stream_init_connection */

    if (ngx_event_flags & NGX_USE_KQUEUE_EVENT) ev->available--;

} while (ev->available);
```

要点：

- **`accept4()`** 一步完成 accept + 设非阻塞（省一次 `fcntl`）；若内核不支持（`ENOSYS`）会运行期降级为 `accept()` 并把 `ngx_inherited_nonblocking` 置 0；
- **`multi_accept` 默认 off**，即每轮只 accept 一个连接。打开后（非 kqueue 路径 `ev->available` 不递减）会一直 accept 到 `EAGAIN`——连接突发时更快，但可能让某个 worker 一次吃掉整个 accept 队列；
- **`EMFILE` 的处理很典型**：不是崩溃，而是关闭监听事件 + 暂停 accept 一段时间（500ms）。日志里的 `accept4() failed (24: Too many open files)` 就是这个分支，此时提高 `worker_rlimit_nofile` 才是正解；
- `ls->handler` 是分派点：HTTP 指向 `ngx_http_init_connection`，stream 指向 `ngx_stream_init_connection`。

## posted events 队列

nginx 有三个队列，用于把"事件收集"与"事件处理"解耦：

```c
ngx_queue_init(&ngx_posted_accept_events);   /* accept 事件：最高优先，先处理 */
ngx_queue_init(&ngx_posted_next_events);     /* 下一轮优先处理 */
ngx_queue_init(&ngx_posted_events);          /* 普通读写事件 */
```

主循环里的顺序是刻意的：

```c
ngx_event_process_posted(cycle, &ngx_posted_accept_events);   /* 先把新连接接进来 */
if (ngx_accept_mutex_held) ngx_shmtx_unlock(&ngx_accept_mutex); /* 尽早释放锁 */
if (delta) ngx_event_expire_timers();                          /* 定时器 */
ngx_event_process_posted(cycle, &ngx_posted_events);           /* 再处理普通事件 */
```

即：**先 accept、再解锁、再跑定时器、最后处理读写**。这最大化了 accept 的吞吐，也把锁的持有时间压到最短。

### eventfd：跨线程唤醒

`ngx_epoll_notify()` 通过一个专用 eventfd 让阻塞在 `epoll_wait()` 的循环被唤醒：

```c
static ngx_int_t
ngx_epoll_notify(ngx_event_handler_pt handler)
{
    static uint64_t inc = 1;
    notify_event.data = handler;
    if ((size_t) write(notify_fd, &inc, sizeof(uint64_t)) != sizeof(uint64_t)) {
        return NGX_ERROR;
    }
    return NGX_OK;
}
```

唯一的使用者是**线程池**：`aio threads` 场景下文件 IO 在线程池里完成，完成后用 `ngx_notify()` 唤醒主线程继续处理。注意它与 `NGX_HAVE_FILE_AIO` 用的 `ngx_eventfd` 是**两个不同的 fd**。

## 定时器

所有定时器挂在一棵红黑树上，key 是**绝对毫秒时间戳**：

```c
// event/ngx_event_timer.c
ngx_rbtree_init(&ngx_event_timer_rbtree, &ngx_event_timer_sentinel,
                ngx_rbtree_insert_timer_value);
```

主循环用最左节点的到期时间算出 `epoll_wait` 的 timeout：

```c
timer = ngx_event_find_timer();      /* 最近还有多久到期，无定时器则 NGX_TIMER_INFINITE */
(void) ngx_process_events(cycle, timer, flags);
if (delta) ngx_event_expire_timers();  /* 只有时间真的跨了毫秒才检查 */
```

红黑树保证 O(log n) 插入/删除/取最小；`ngx_event_expire_timers()` 每次从最左节点开始摘，直到遇到未到期的为止。

### timer_resolution

默认 `timer_resolution` 为 0，即 epoll 超时完全由最近的定时器决定。设置后 nginx 会用 `setitimer(ITIMER_REAL)` 周期性发 `SIGALRM`：

```c
if (ngx_timer_resolution && !(ngx_event_flags & NGX_USE_TIMER_EVENT)) {
    sa.sa_handler = ngx_timer_signal_handler;      /* 只做一件事：ngx_event_timer_alarm = 1 */
    sigaction(SIGALRM, &sa, NULL);

    itv.it_interval.tv_sec  = ngx_timer_resolution / 1000;
    itv.it_interval.tv_usec = (ngx_timer_resolution % 1000) * 1000;
    setitimer(ITIMER_REAL, &itv, NULL);
}
```

此时主循环把 `timer` 设为 `NGX_TIMER_INFINITE`，靠 `SIGALRM` 打断 `epoll_wait`（返回 `EINTR`）来推进时间。代价是固定的信号开销，收益是时间精度更可控——一般不需要配。

## 缓存时间

nginx 不每次调用 `gettimeofday()`，而是**缓存时间**，只在事件循环的关键点刷新：

```c
// core/ngx_times.c
/*
 * The time may be updated by signal handler or by several threads.
 * The time update operations are rare and require to hold the ngx_time_lock.
 * The time read operations are frequent, so they are lock-free and get time
 * values and strings from the current slot.
 */
#define NGX_TIME_SLOTS   64
```

有 6 组缓存数组，每组都是 `[NGX_TIME_SLOTS]`：时间值、error log 时间串、HTTP 时间串、访问日志时间串、ISO8601 串、syslog 串。写者写满一个新 slot 后用屏障 + 原子切换指针发布，**读者完全无锁**；只有在读者被抢占超过 64 秒的极端情况下才可能读到被覆写的数据。

刷新时机：

| 触发源 | 函数 |
| :-- | :-- |
| 任意信号入口 | `ngx_time_sigsafe_update()`（不调用非 async-signal-safe 的 `localtime()`） |
| `epoll_wait` 返回后 | `ngx_time_update()` |
| master 从 `sigsuspend` 唤醒 | `ngx_time_update()` |
| 线程池任务完成 | `ngx_time_update()` |

实践含义：**同一批事件内的所有请求共享同一个时间戳**，所以 `$time_iso8601` 的精度是"事件循环粒度"；`ngx_current_msec`（单调时钟）每次 `ngx_time_update()` 都会刷新，而格式化后的时间字符串**每秒才更新一次**。

## 阻塞 IO 与线程池

事件循环最怕阻塞。`sendfile` 在大文件上仍可能占用 worker 很久，nginx 提供了两个对策：

```nginx
location /video/ {
    sendfile       on;
    sendfile_max_chunk 2m;      # 单次最多发 2MB，剩下的下一轮继续
    aio            threads;     # 1.7.11+：把阻塞的文件 IO 交给线程池
    directio       8m;          # 大于 8m 的文件走 O_DIRECT（配合 aio）
    output_buffers 1 128k;
}
```

```nginx
thread_pool default threads=16 max_queue=65536;
```

线程池完成 IO 后通过 `ngx_notify()`（eventfd）唤醒主线程。注意 **aio threads 只覆盖文件 IO**，DNS 解析在独立的 resolver 进程，其它阻塞（如数据库访问）在 nginx 里只能靠 OpenResty 的 cosocket 或改用上游服务。

## 与内核的对应关系

| nginx 行为 | 内核机制 |
| :-- | :-- |
| `ngx_epoll_init` / `process_events` | [epoll](/docs/CS/OS/Linux/IO/epoll.md) `epoll_create` / `epoll_wait` |
| `ngx_event_accept` | [accept4()](/docs/CS/OS/Linux/net/socket.md)（`SOCK_NONBLOCK`），监听队列长度受 `net.core.somaxconn` 限制 |
| `ngx_disable_accept_events` on EMFILE | fd 上限（`ulimit -n`、`fs.file-max`） |
| 惊群规避 | `SO_REUSEPORT` / `EPOLLEXCLUSIVE` / 用户态 `accept_mutex`，见 [惊群](/docs/CS/OS/Linux/proc/thundering_herd.md) |
| `sendfile` / `aio` / `directio` | [零拷贝](/docs/CS/OS/Linux/ZeroCopy.md)、`io_submit`、`O_DIRECT` |
| `ngx_time_update` 时间缓存 | [timer](/docs/CS/OS/Linux/timer.md) —— 用户态自建时间缓存，避免每请求一次 `gettimeofday` 系统调用 |
| worker 创建 | [fork](/docs/CS/OS/Linux/proc/process.md?id=fork) |
| reload / 热升级 | [信号](/docs/CS/OS/Linux/proc/signal.md) + [exec](/docs/CS/OS/Linux/proc/process.md?id=exec) |

## 调优清单

```nginx
events {
    use epoll;                 # Linux 上通常可省略
    worker_connections 10240;  # 记住：反向代理时每个客户端连接消耗 2 个
    multi_accept on;           # 新连接突发场景建议开
    # accept_mutex off;        # 1.11.3 起已是默认，无需再写
}

http {
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
}
```

- 想用 `SO_REUSEPORT`：`listen 80 reuseport;`（注意 reload 丢连接的风险）；
- 连接数估算：`worker_processes × worker_connections ÷ 2`（反向代理）；
- fd 上限：`worker_rlimit_nofile` 要 ≥ `worker_connections × 2`，并同步 `ulimit -n`；
- 监听队列：`listen 80 backlog=65535;` 配合 `net.core.somaxconn`；
- 不要开 `timer_resolution` 除非确有必要；
- 大文件：`sendfile_max_chunk` 防止单连接独占 worker。

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)
- [epoll](/docs/CS/OS/Linux/IO/epoll.md)
- [Processes 知识地图](/docs/CS/OS/Linux/proc/README.md)
- [惊群](/docs/CS/OS/Linux/proc/thundering_herd.md)
- [HTTP](/docs/CS/CN/nginx/HTTP.md)
- [内核协同链路](/docs/CS/OS/Linux/Architecture.md)

## References

1. [nginx 源码：src/event/ngx_event.c、ngx_event_accept.c、modules/ngx_epoll_module.c](https://nginx.org/download/nginx-1.31.6.tar.gz)
2. [Module ngx_core_module — worker_connections](https://nginx.org/en/docs/ngx_core_module.html#worker_connections)
3. [Module ngx_event_core_module](https://nginx.org/en/docs/ngx_core_module.html)
4. [Inside NGINX: How We Designed for Performance & Scale](https://www.nginx.com/blog/inside-nginx-how-we-designed-for-performance-scale/)
5. [The C10K problem](http://www.kegel.com/c10k.html)
