## Introduction

> [!NOTE]
> 版本基线 **Redis 8.10.2**；本页机制若与其他版本口径冲突，以 [Redis 版本基线](/docs/CS/DB/Redis/Redis.md?id=version-baseline) 为准。

一个简单的事件驱动编程库。



这个文件（*networking.c*）定义了与客户端、主节点、副本之间的全部 I/O 函数（在 Redis 里，主与副本都只是特殊的客户端）：

* `createClient()` 分配并初始化一个新客户端。
* `addReply*()` 系列函数由命令实现调用，把数据追加到客户端结构上，最终作为某条命令的应答发给客户端。
* `writeToClient()` 把输出缓冲里待发的数据发给客户端，由*可写事件处理器* `sendReplyToClient()` 调用。
* `readQueryFromClient()` 是*可读事件处理器*，把从客户端读到的数据累积进 query buffer。
* `processInputBuffer()` 是解析入口：按 Redis 协议解析客户端的 query buffer；命令就绪后调用定义在 `server.c` 里的 `processCommand()` 真正执行命令。
* `freeClient()` 负责释放、断开并移除一个客户端。

## EventLoop

由于种种[原因](http://groups.google.com/group/redis-db/browse_thread/thread/b52814e9ef15b8d0/)，Redis 用的是自己的事件库。

`Redis` 需要对事件做整体抽象，于是定义了 `aeEventLoop` 结构。

定义在 `redis.c` 里的 `initServer` 负责初始化 [redisServer 结构](/docs/CS/DB/Redis/server.md?id=server) 的众多字段，其中一个字段就是事件循环 `el`：

```c
aeEventLoop *el
```

`initServer` 通过调用 `ae.c` 里的 `aeCreateEventLoop` 来初始化 `server.el`。`aeEventLoop` 的定义如下：

```c
typedef struct aeEventLoop {
    int maxfd;   /* highest file descriptor currently registered */
    int setsize; /* max number of file descriptors tracked */
    long long timeEventNextId;
    time_t lastTime;     /* Used to detect system clock skew */
    aeFileEvent *events; /* Registered events */
    aeFiredEvent *fired; /* Fired events */
    aeTimeEvent *timeEventHead;
    int stop;
    void *apidata; /* This is used for polling API specific data */
    aeBeforeSleepProc *beforesleep;
    aeBeforeSleepProc *aftersleep;
    int flags;
} aeEventLoop;
```

aeEventLoop结构保存了一个void *类型的万能指针apidata，是用来保存轮询事件的状态的，也就是保存底层调用的多路复用库的事件状态，
关于 Redis 的多路复用库的选择，Redis 包装了常见的 select epoll evport kqueue，他们在编译阶段，根据不同的系统选择性能最高的一个多路复用库作为 Redis 的多路复用程序的实现，
而且所有库实现的接口名称都是相同的，因此 Redis 多路复用程序底层实现是可以互换的

```c
/* Include the best multiplexing layer supported by this system.
 * The following should be ordered by performances, descending. */
```

```c
// ae.c
#ifdef HAVE_EVPORT
#include "ae_evport.c"
#else
    #ifdef HAVE_EPOLL
    #include "ae_epoll.c"
    #else
        #ifdef HAVE_KQUEUE
        #include "ae_kqueue.c"
        #else
        #include "ae_select.c"
        #endif
    #endif
#endif


```

### aeCreateEventLoop

`aeCreateEventLoop` first `malloc`s `aeEventLoop` structure then calls `ae_epoll.c:aeApiCreate`.

InitServer 中调用了 aeCreateEventLoop

`aeApiCreate` 会为 `aeApiState` 分配内存，它有两个字段：`epfd` 存放 [`epoll_create`](http://man.cx/epoll_create\(2)) 返回的 `epoll` 文件描述符，`events` 是 Linux `epoll` 库定义的 `struct epoll_event`。`events` 字段的用法后面再讲。

下一步是 `ae.c:aeCreateTimeEvent`。但在那之前，`initServer` 已经调用过 `anet.c:anetTcpServer`，它创建并返回一个*监听描述符*（listening descriptor），默认监听 *6379* 端口，返回值存在 `server.fd` 字段里。

```c
aeEventLoop *aeCreateEventLoop(int setsize) {
    aeEventLoop *eventLoop;
    int i;

    if ((eventLoop = zmalloc(sizeof(*eventLoop))) == NULL) goto err;
    eventLoop->events = zmalloc(sizeof(aeFileEvent)*setsize);
    eventLoop->fired = zmalloc(sizeof(aeFiredEvent)*setsize);
    if (eventLoop->events == NULL || eventLoop->fired == NULL) goto err;
    eventLoop->setsize = setsize;
    eventLoop->lastTime = time(NULL);
    eventLoop->timeEventHead = NULL;
    eventLoop->timeEventNextId = 0;
    eventLoop->stop = 0;
    eventLoop->maxfd = -1;
    eventLoop->beforesleep = NULL;
    eventLoop->aftersleep = NULL;
    eventLoop->flags = 0;
    
    if (aeApiCreate(eventLoop) == -1) goto err;
    
    /* Events with mask == AE_NONE are not set. So let's initialize the vector with it. */
    for (i = 0; i < setsize; i++)
        eventLoop->events[i].mask = AE_NONE;
    return eventLoop;
}
```

aeCreateEventLoop() 内部会调用 aeApiCreate()，根据不同平台支持选择调用epoll、select 或者 kqueue 的 API，创建事件监听



#### aeApiCreate

```c
static int aeApiCreate(aeEventLoop *eventLoop) {
    aeApiState *state = zmalloc(sizeof(aeApiState));

    if (!state) return -1;
    state->events = zmalloc(sizeof(struct kevent)*eventLoop->setsize);
    if (!state->events) {
        zfree(state);
        return -1;
    }
    state->kqfd = kqueue();
    if (state->kqfd == -1) {
        zfree(state->events);
        zfree(state);
        return -1;
    }
    eventLoop->apidata = state;
    return 0;
}
```

### processEvents

`ae.c:aeProcessEvents` 会在事件循环上调用 `ae.c:aeSearchNearestTimer`，找出最快到期（等待时间最短）的时间事件。
本例中事件循环里只有这一个时间事件，由 `ae.c:aeCreateTimeEvent` 创建。

要记得，`aeCreateTimeEvent` 创建的这个时间事件此刻多半已经到期了——它的超时只有 1 毫秒。
既然时间事件已经到期，`tvp` 这个 `timeval` 结构变量的秒与微秒字段都被置为 0。

`tvp` 连同事件循环一起传给 `ae_epoll.c:aeApiPoll`。

`aeApiPoll` 在 `epoll` 描述符上做一次 [`epoll_wait`](http://man.cx/epoll_wait)，并把结果填进 `eventLoop->fired` 表：

- `fd`：现在可以按 mask 做读/写操作的描述符。
- `mask`：该描述符上现在可以执行的读/写事件。

`aeApiPoll` 返回就绪文件事件的个数。放回上下文看：如果有客户端请求连接，`aeApiPoll` 就会察觉，并在 `eventLoop->fired` 里填一项——描述符是那个*监听描述符*，mask 是 `AE_READABLE`。

随后 `aeProcessEvents` 调用注册为回调的 `redis.c:acceptHandler`；`acceptHandler` 对*监听描述符*执行 `accept`，拿到与客户端之间的*已连接描述符*。
`redis.c:createClient` 再通过 `ae.c:aeCreateFileEvent` 在这个*已连接描述符*上挂一个文件事件，如下：

```c
if (aeCreateFileEvent(server.el, c->fd, AE_READABLE,
    readQueryFromClient, c) == AE_ERR) {
    freeClient(c);
    return NULL;
}
```

`c` 是 `redisClient` 结构变量，`c->fd` 就是那个已连接的描述符。

接着 `ae.c:aeProcessEvent` 会调用 `ae.c:processTimeEvents`。

`aeProcessEvents` 的语义（源码注释）：先处理所有到期的时间事件，再处理所有就绪的文件事件（文件事件也可能刚被前面处理的时间事件回调注册出来）。
没有特殊 flags 时，函数会一直睡眠，直到某个文件事件触发、或下一个时间事件到期（如果有）。

* flags 为 0：什么都不做，直接返回。
* 置 `AE_ALL_EVENTS`：处理所有类型的事件。
* 置 `AE_FILE_EVENTS`：处理文件事件。
* 置 `AE_TIME_EVENTS`：处理时间事件。
* 置 `AE_DONT_WAIT`：尽快返回，把所有不需要等待就能处理的事件处理完。
* 置 `AE_CALL_AFTER_SLEEP`：调用 aftersleep 回调。
* 置 `AE_CALL_BEFORE_SLEEP`：调用 beforesleep 回调。

从内核取出就绪事件，根据事件的读写类型，分别进行回调处理相关业务逻辑

```c
// ae.c
int aeProcessEvents(aeEventLoop *eventLoop, int flags)
{
    int processed = 0, numevents;

    /* Nothing to do? return ASAP */
    if (!(flags & AE_TIME_EVENTS) && !(flags & AE_FILE_EVENTS)) return 0;

    /* Note that we want call select() even if there are no
     * file events to process as long as we want to process time
     * events, in order to sleep until the next time event is ready
     * to fire. */
    if (eventLoop->maxfd != -1 ||
        ((flags & AE_TIME_EVENTS) && !(flags & AE_DONT_WAIT))) {
        int j;
        aeTimeEvent *shortest = NULL;
        struct timeval tv, *tvp;

        if (flags & AE_TIME_EVENTS && !(flags & AE_DONT_WAIT))
            shortest = aeSearchNearestTimer(eventLoop);
        if (shortest) {
            long now_sec, now_ms;

            aeGetTime(&now_sec, &now_ms);
            tvp = &tv;

            /* How many milliseconds we need to wait for the next
             * time event to fire? */
            long long ms =
                (shortest->when_sec - now_sec)*1000 +
                shortest->when_ms - now_ms;

            if (ms > 0) {
                tvp->tv_sec = ms/1000;
                tvp->tv_usec = (ms % 1000)*1000;
            } else {
                tvp->tv_sec = 0;
                tvp->tv_usec = 0;
            }
        } else {
            /* If we have to check for events but need to return
             * ASAP because of AE_DONT_WAIT we need to set the timeout
             * to zero */
            if (flags & AE_DONT_WAIT) {
                tv.tv_sec = tv.tv_usec = 0;
                tvp = &tv;
            } else {
                /* Otherwise we can block */
                tvp = NULL; /* wait forever */
            }
        }

        if (eventLoop->flags & AE_DONT_WAIT) {
            tv.tv_sec = tv.tv_usec = 0;
            tvp = &tv;
        }

        if (eventLoop->beforesleep != NULL && flags & AE_CALL_BEFORE_SLEEP)
            eventLoop->beforesleep(eventLoop);

        /* Call the multiplexing API, will return only on timeout or when
         * some event fires. */
        numevents = aeApiPoll(eventLoop, tvp);

        /* After sleep callback. */
        if (eventLoop->aftersleep != NULL && flags & AE_CALL_AFTER_SLEEP)
            eventLoop->aftersleep(eventLoop);

        for (j = 0; j < numevents; j++) {
            aeFileEvent *fe = &eventLoop->events[eventLoop->fired[j].fd];
            int mask = eventLoop->fired[j].mask;
            int fd = eventLoop->fired[j].fd;
            int fired = 0; /* Number of events fired for current fd. */

            /* Normally we execute the readable event first, and the writable
             * event laster. This is useful as sometimes we may be able
             * to serve the reply of a query immediately after processing the
             * query.
             *
             * However if AE_BARRIER is set in the mask, our application is
             * asking us to do the reverse: never fire the writable event
             * after the readable. In such a case, we invert the calls.
             * This is useful when, for instance, we want to do things
             * in the beforeSleep() hook, like fsynching a file to disk,
             * before replying to a client. */
            int invert = fe->mask & AE_BARRIER;

            /* Note the "fe->mask & mask & ..." code: maybe an already
             * processed event removed an element that fired and we still
             * didn't processed, so we check if the event is still valid.
             *
             * Fire the readable event if the call sequence is not
             * inverted. */
            if (!invert && fe->mask & mask & AE_READABLE) {
                fe->rfileProc(eventLoop,fd,fe->clientData,mask);
                fired++;
                fe = &eventLoop->events[fd]; /* Refresh in case of resize. */
            }

            /* Fire the writable event. */
            if (fe->mask & mask & AE_WRITABLE) {
                if (!fired || fe->wfileProc != fe->rfileProc) {
                    fe->wfileProc(eventLoop,fd,fe->clientData,mask);
                    fired++;
                }
            }

            /* If we have to invert the call, fire the readable event now
             * after the writable one. */
            if (invert) {
                fe = &eventLoop->events[fd]; /* Refresh in case of resize. */
                if ((fe->mask & mask & AE_READABLE) &&
                    (!fired || fe->wfileProc != fe->rfileProc))
                {
                    fe->rfileProc(eventLoop,fd,fe->clientData,mask);
                    fired++;
                }
            }

            processed++;
        }
    }
    /* Check time events */
    if (flags & AE_TIME_EVENTS)
        processed += processTimeEvents(eventLoop);

    return processed; /* return the number of processed file/time events */
}
```

#### aeSearchNearestTimer

查找下一个即将到期的时间事件：这个操作用来判断 select 可以睡多久而不耽误任何事件；没有任何定时器时返回 NULL。
由于时间事件是无序存放的，这是 O(N) 的。可能的优化（Redis 目前还不需要）：

1. 按到期顺序插入，使最近的就是表头——好一些，但插入与删除仍是 O(N)。
2. 用跳表，使这个操作 O(1)、插入 O(log(N))。

```c
static aeTimeEvent *aeSearchNearestTimer(aeEventLoop *eventLoop)
{
    aeTimeEvent *te = eventLoop->timeEventHead;
    aeTimeEvent *nearest = NULL;

    while(te) {
        if (!nearest || te->when_sec < nearest->when_sec ||
                (te->when_sec == nearest->when_sec &&
                 te->when_ms < nearest->when_ms))
            nearest = te;
        te = te->next;
    }
    return nearest;
}
```

#### aeApiPoll

```c
// ae_kqueue.c
static int aeApiPoll(aeEventLoop *eventLoop, struct timeval *tvp) {
    aeApiState *state = eventLoop->apidata;
    int retval, numevents = 0;

    if (tvp != NULL) {
        struct timespec timeout;
        timeout.tv_sec = tvp->tv_sec;
        timeout.tv_nsec = tvp->tv_usec * 1000;
        retval = kevent(state->kqfd, NULL, 0, state->events, eventLoop->setsize,
                        &timeout);
    } else {
        retval = kevent(state->kqfd, NULL, 0, state->events, eventLoop->setsize,
                        NULL);
    }

    if (retval > 0) {
        int j;

        numevents = retval;
        for(j = 0; j < numevents; j++) {
            int mask = 0;
            struct kevent *e = state->events+j;

            if (e->filter == EVFILT_READ) mask |= AE_READABLE;
            if (e->filter == EVFILT_WRITE) mask |= AE_WRITABLE;
            eventLoop->fired[j].fd = e->ident;
            eventLoop->fired[j].mask = mask;
        }
    }
    return numevents;
}
```

### beforeSleep

每次 Redis 进入事件库的主循环、准备睡眠等待就绪的文件描述符之前，都会调用这个函数。

注意：目前它被两个函数调用：

1. `aeMain` —— 服务器主循环。
2. `processEventsWhileBlocked` —— 在加载 RDB/AOF 期间继续服务客户端。

如果调用方是 `processEventsWhileBlocked`，就不能做全部动作（例如不该让 key 过期），但仍要做其中一部分。
最重要的是 `freeClientsInAsyncFreeQueue`，此外还调用一些低风险函数。

```c
void beforeSleep(struct aeEventLoop *eventLoop) {
    UNUSED(eventLoop);

    /* Just call a subset of vital functions in case we are re-entering
     * the event loop from processEventsWhileBlocked(). Note that in this
     * case we keep track of the number of events we are processing, since
     * processEventsWhileBlocked() wants to stop ASAP if there are no longer
     * events to handle. */
    if (ProcessingEventsWhileBlocked) {
        uint64_t processed = 0;
        processed += handleClientsWithPendingReadsUsingThreads();
        processed += tlsProcessPendingData();
        processed += handleClientsWithPendingWrites();
        processed += freeClientsInAsyncFreeQueue();
        server.events_processed_while_blocked += processed;
        return;
    }

    /* Handle precise timeouts of blocked clients. */
    handleBlockedClientsTimeout();

    /* We should handle pending reads clients ASAP after event loop. */
    handleClientsWithPendingReadsUsingThreads();

    /* Handle TLS pending data. (must be done before flushAppendOnlyFile) */
    tlsProcessPendingData();

    /* If tls still has pending unread data don't sleep at all. */
    aeSetDontWait(server.el, tlsHasPendingData());

    /* Call the Redis Cluster before sleep function. Note that this function
     * may change the state of Redis Cluster (from ok to fail or vice versa),
     * so it's a good idea to call it before serving the unblocked clients
     * later in this function. */
    if (server.cluster_enabled) clusterBeforeSleep();
```

Run a fast expire cycle.

```c
    if (server.active_expire_enabled && server.masterhost == NULL)
        activeExpireCycle(ACTIVE_EXPIRE_CYCLE_FAST);

    /* Unblock all the clients blocked for synchronous replication
     * in WAIT. */
    if (listLength(server.clients_waiting_acks))
        processClientsWaitingReplicas();

    /* Check if there are clients unblocked by modules that implement
     * blocking commands. */
    if (moduleCount()) moduleHandleBlockedClients();

    /* Try to process pending commands for clients that were just unblocked. */
    if (listLength(server.unblocked_clients))
        processUnblockedClients();

    /* Send all the slaves an ACK request if at least one client blocked
     * during the previous event loop iteration. Note that we do this after
     * processUnblockedClients(), so if there are multiple pipelined WAITs
     * and the just unblocked WAIT gets blocked again, we don't have to wait
     * a server cron cycle in absence of other event loop events. See #6623. */
    if (server.get_ack_from_slaves) {
        robj *argv[3];

        argv[0] = createStringObject("REPLCONF",8);
        argv[1] = createStringObject("GETACK",6);
        argv[2] = createStringObject("*",1); /* Not used argument. */
        replicationFeedSlaves(server.slaves, server.slaveseldb, argv, 3);
        decrRefCount(argv[0]);
        decrRefCount(argv[1]);
        decrRefCount(argv[2]);
        server.get_ack_from_slaves = 0;
    }

    /* Send the invalidation messages to clients participating to the
     * client side caching protocol in broadcasting (BCAST) mode. */
    trackingBroadcastInvalidationMessages();

    /* Write the AOF buffer on disk */
    flushAppendOnlyFile(0);

    /* Handle writes with pending output buffers. */
    handleClientsWithPendingWritesUsingThreads();

    /* Close clients that need to be closed asynchronous */
    freeClientsInAsyncFreeQueue();

    /* Before we are going to sleep, let the threads access the dataset by
     * releasing the GIL. Redis main thread will not touch anything at this
     * time. */
    if (moduleCount()) moduleReleaseGIL();
}
```







### afterSleep

```c
/* This function is called immadiately after the event loop multiplexing
 * API returned, and the control is going to soon return to Redis by invoking
 * the different events callbacks. */
void afterSleep(struct aeEventLoop *eventLoop) {
    UNUSED(eventLoop);

    if (!ProcessingEventsWhileBlocked) {
        if (moduleCount()) moduleAcquireGIL();
    }
}
```

### processTimeEvents

`ae.processTimeEvents` 从 `eventLoop->timeEventHead` 开始遍历时间事件链表。

对每个已到期事件，`processTimeEvents` 调用其注册的回调；
这里调用的正是唯一注册过的那个时间事件回调——`redis.c:serverCron`。
回调返回「下次再被调用需要等待的毫秒数」，
这个改动通过 `ae.c:aeAddMilliSeconds` 记录，会在 `ae.c:aeMain` 主循环的下一次迭代中被处理。

```c
static int processTimeEvents(aeEventLoop *eventLoop) {
    int processed = 0;
    aeTimeEvent *te;
    long long maxId;
    time_t now = time(NULL);
```

如果系统时钟被拨到未来、又被调回正确值，时间事件就可能被打乱延后。
通常意味着本该按计划执行的操作没能及时跑起来。

这里的做法是检测时钟跳变：一旦发生就强制所有时间事件尽快处理——**早处理比无限期拖着更安全，实践也支持这一点**。
```c
    if (now < eventLoop->lastTime) {
        te = eventLoop->timeEventHead;
        while(te) {
            te->when_sec = 0;
            te = te->next;
        }
    }
    eventLoop->lastTime = now;

    te = eventLoop->timeEventHead;
    maxId = eventLoop->timeEventNextId-1;
    while(te) {
        long now_sec, now_ms;
        long long id;

        /* Remove events scheduled for deletion. */
        if (te->id == AE_DELETED_EVENT_ID) {
            aeTimeEvent *next = te->next;
            /* If a reference exists for this timer event,
             * don't free it. This is currently incremented
             * for recursive timerProc calls */
            if (te->refcount) {
                te = next;
                continue;
            }
            if (te->prev)
                te->prev->next = te->next;
            else
                eventLoop->timeEventHead = te->next;
            if (te->next)
                te->next->prev = te->prev;
            if (te->finalizerProc)
                te->finalizerProc(eventLoop, te->clientData);
            zfree(te);
            te = next;
            continue;
        }

        /* Make sure we don't process time events created by time events in
         * this iteration. Note that this check is currently useless: we always
         * add new timers on the head, however if we change the implementation
         * detail, this check may be useful again: we keep it here for future
         * defense. */
        if (te->id > maxId) {
            te = te->next;
            continue;
        }
        aeGetTime(&now_sec, &now_ms);
        if (now_sec > te->when_sec ||
            (now_sec == te->when_sec && now_ms >= te->when_ms))
        {
            int retval;

            id = te->id;
            te->refcount++;
            retval = te->timeProc(eventLoop, id, te->clientData);
            te->refcount--;
            processed++;
            if (retval != AE_NOMORE) {
                aeAddMillisecondsToNow(retval,&te->when_sec,&te->when_ms);
            } else {
                te->id = AE_DELETED_EVENT_ID;
            }
        }
        te = te->next;
    }
    return processed;
}
```

## Multiple IO

Redis 基本是单线程的，但某些操作已经走了线程：UNLINK、异步刷盘与 AOF fsync、惰性释放等，此外还有一块专门负责加载与计算校验和的线程。

现在还可以把客户端 socket 的读写放到不同的 IO 线程里处理。由于写操作尤其慢，Redis 用户通常靠 pipelining 提升单核性能、靠多开实例做扩展；用上 IO 线程后，不必 pipelining 也不必给实例分片，就能轻松拿到约 2 倍提速。

线程默认关闭。建议只在 4 核以上、且能留出至少一个空闲核心的机器上开启。

超过 8 个线程通常没什么收益。也建议只在真的遇到性能问题、且 Redis 实例确实吃掉了相当大比例 CPU 时间时才启用线程化 IO，否则这个特性没有意义。

比如 4 核机器试 2~3 个 IO 线程，8 核机器试 6 个。开启方式是配置指令：

```
io-threads 4
```

把 `io-threads` 设为 1 就等于照旧只用主线程。启用 IO 线程后，默认只对「写」做线程化——即把 `write(2)` 系统调用与「把客户端缓冲写进 socket」挪到线程里；也可以通过下面的指令把读与协议解析也线程化：

```
io-threads-do-reads no
```

通常对读做线程化帮助不大。

- **NOTE 1：** 该配置项不能用 `CONFIG SET` 动态修改；并且开启 SSL 时这个特性目前不可用。
- **NOTE 2：** 想用 redis-benchmark 验证提速，记得压测本身也要用 `--threads` 开多线程、且线程数与 Redis 侧对齐，否则看不到差异。

## File and Time Events




```c
/* File event structure */
typedef struct aeFileEvent {
    int mask; /* one of AE_(READABLE|WRITABLE|BARRIER) */
    aeFileProc *rfileProc;
    aeFileProc *wfileProc;
    void *clientData;
} aeFileEvent;
```


rfileProc 和 wfileProc 成员分别为两个函数指针，他们的原型为

```c

typedef void aeFileProc(struct aeEventLoop *eventLoop, int fd, void *clientData, int mask);
```

当事件就绪时，我们需要知道文件事件的文件描述符还有事件类型才能对于锁定该事件，因此定义了 aeFiredEvent 结构统一管理：
时间事件表是一个链表，因为它有一个 next 指针域，指向下一个时间事件。
和文件事件一样，当时间事件所指定的事件发生时，也会调用对应的回调函数，结构成员 timeProc 和 finalizerProc 都是回调函数，函数原型如下：函数指针与回调函数详解


```c
typedef int aeTimeProc(struct aeEventLoop *eventLoop, long long id, void *clientData);
typedef void aeEventFinalizerProc(struct aeEventLoop *eventLoop, void *clientData);
```





### TimeEvent

```c
typedef struct aeTimeEvent {
    long long id; /* time event identifier. */
    monotime when;
    aeTimeProc *timeProc;
    aeEventFinalizerProc *finalizerProc;
    void *clientData;
    struct aeTimeEvent *prev;
    struct aeTimeEvent *next;
    int refcount; /* refcount to prevent timer events from being
  		   * freed in recursive time event calls. */
} aeTimeEvent;
```

/* A fired event */
```c
typedef struct aeFiredEvent {
    int fd;
    int mask;
} aeFiredEvent;
```


## Events
| Event Type  | Socket Type | Callback Method     | For              |
| ------------- | ------------- | --------------------- | ------------------ |
| AE_READABLE | Listen      | acceptTCPHandler    | connect          |
| AE_READABLE | connected   | readQueryFromClient | read and execute |
| AE_WRITABLE | connected   | sendReplyToClient   | Return data      |

### Implementations


整个 I/O 多路复用模块抹平了不同平台上 I/O 多路复用函数的差异性，提供了相同的接口：

```c
/* 整个 aeApi* 层在每个后端里提供同名接口（各模块内部用 aeApiState 存上下文） */
    static int aeApiCreate(aeEventLoop *eventLoop)
    static int aeApiResize(aeEventLoop *eventLoop, int setsize)
    static void aeApiFree(aeEventLoop *eventLoop)
    static int aeApiAddEvent(aeEventLoop *eventLoop, int fd, int mask)
    static void aeApiDelEvent(aeEventLoop *eventLoop, int fd, int mask)
    static int aeApiPoll(aeEventLoop *eventLoop, struct timeval *tvp)
```

因为各个函数所需要的参数不同，我们在每一个子模块内部通过一个 aeApiState 来存储需要的上下文信息


## epoll

Redis 用自研的 ae 包装 [epoll](/docs/CS/OS/Linux/IO/epoll.md)，而不是引入 libevent。

aeApiCreate->`epoll_create`

```c
static int aeApiCreate(aeEventLoop *eventLoop) {
    aeApiState *state = zmalloc(sizeof(aeApiState));

    if (!state) return -1;
    state->events = zmalloc(sizeof(struct epoll_event)*eventLoop->setsize);
    if (!state->events) {
        zfree(state);
        return -1;
    }
    state->epfd = epoll_create(1024); /* 1024 is just a hint for the kernel */
    if (state->epfd == -1) {
        zfree(state->events);
        zfree(state);
        return -1;
    }
    eventLoop->apidata = state;
    return 0;
}
```

aeApiAddEvent->`epoll_ctl`

```c
static int aeApiAddEvent(aeEventLoop *eventLoop, int fd, int mask) {
    aeApiState *state = eventLoop->apidata;
    struct epoll_event ee = {0}; /* avoid valgrind warning */
    /* If the fd was already monitored for some event, we need a MOD
     * operation. Otherwise we need an ADD operation. */
    int op = eventLoop->events[fd].mask == AE_NONE ?
            EPOLL_CTL_ADD : EPOLL_CTL_MOD;

    ee.events = 0;
    mask |= eventLoop->events[fd].mask; /* Merge old events */
    if (mask & AE_READABLE) ee.events |= EPOLLIN;
    if (mask & AE_WRITABLE) ee.events |= EPOLLOUT;
    ee.data.fd = fd;
    if (epoll_ctl(state->epfd,op,fd,&ee) == -1) return -1;
    return 0;
}
```

aeApiDelEvent -> `epoll_ctl`

```c
static void aeApiDelEvent(aeEventLoop *eventLoop, int fd, int delmask) {
    aeApiState *state = eventLoop->apidata;
    struct epoll_event ee = {0}; /* avoid valgrind warning */
    int mask = eventLoop->events[fd].mask & (~delmask);

    ee.events = 0;
    if (mask & AE_READABLE) ee.events |= EPOLLIN;
    if (mask & AE_WRITABLE) ee.events |= EPOLLOUT;
    ee.data.fd = fd;
    if (mask != AE_NONE) {
        epoll_ctl(state->epfd,EPOLL_CTL_MOD,fd,&ee);
    } else {
        /* Note, Kernel < 2.6.9 requires a non null event pointer even for
         * EPOLL_CTL_DEL. */
        epoll_ctl(state->epfd,EPOLL_CTL_DEL,fd,&ee);
    }
}
```

aeApiPoll ->`epoll_wait`

通过 epoll_wait 从系统内核取出就绪文件事件 存储到 fired

```c
static int aeApiPoll(aeEventLoop *eventLoop, struct timeval *tvp) {
    aeApiState *state = eventLoop->apidata;
    int retval, numevents = 0;

    retval = epoll_wait(state->epfd,state->events,eventLoop->setsize,
            tvp ? (tvp->tv_sec*1000 + tvp->tv_usec/1000) : -1);
    if (retval > 0) {
        int j;

        numevents = retval;
        for (j = 0; j < numevents; j++) {
            int mask = 0;
            struct epoll_event *e = state->events+j;

            if (e->events & EPOLLIN) mask |= AE_READABLE;
            if (e->events & EPOLLOUT) mask |= AE_WRITABLE;
            if (e->events & EPOLLERR) mask |= AE_WRITABLE|AE_READABLE;
            if (e->events & EPOLLHUP) mask |= AE_WRITABLE|AE_READABLE;
            eventLoop->fired[j].fd = e->data.fd;
            eventLoop->fired[j].mask = mask;
        }
    }
    return numevents;
}
```

## kqueue

```c
typedef struct aeApiState {
    int kqfd;
    struct kevent *events;
} aeApiState;
```

kevent 定义在 event.h 源文件中

```go
struct kevent {
	uintptr_t       ident;  /* identifier for this event */
	int16_t         filter; /* filter for event */
	uint16_t        flags;  /* general flags */
	uint32_t        fflags; /* filter-specific flags */
	intptr_t        data;   /* filter-specific data */
	void            *udata; /* opaque user data identifier */
};
```











```c
static int aeApiCreate(aeEventLoop *eventLoop) {
    aeApiState *state = zmalloc(sizeof(aeApiState));

    if (!state) return -1;
    state->events = zmalloc(sizeof(struct kevent)*eventLoop->setsize);
    if (!state->events) {
        zfree(state);
        return -1;
    }
    state->kqfd = kqueue();
    if (state->kqfd == -1) {
        zfree(state->events);
        zfree(state);
        return -1;
    }
    eventLoop->apidata = state;
    return 0;
}
```

aeApiDelEvent -> kevent

```c
static void aeApiDelEvent(aeEventLoop *eventLoop, int fd, int mask) {
    aeApiState *state = eventLoop->apidata;
    struct kevent ke;

    if (mask & AE_READABLE) {
        EV_SET(&ke, fd, EVFILT_READ, EV_DELETE, 0, 0, NULL);
        kevent(state->kqfd, &ke, 1, NULL, 0, NULL);
    }
    if (mask & AE_WRITABLE) {
        EV_SET(&ke, fd, EVFILT_WRITE, EV_DELETE, 0, 0, NULL);
        kevent(state->kqfd, &ke, 1, NULL, 0, NULL);
    }
}
```

## select

```c
typedef struct aeApiState {
    fd_set rfds, wfds;
    fd_set _rfds, _wfds;
} aeApiState;
```

## Summary


|                   | epoll        | kqueue | select   | evport      |
| ------------------- | -------------- | -------- | ---------- | ------------- |
| **aeApiCreate**   | epoll_create | kevent | FD_ZERO  | port_create |
| **aeApiAddEvent** | epoll_ctl    | kevent | FD_SET   |             |
| **aeApiDelEvent** | epoll_ctl    | kevent | FD_CLR   |             |
| **aeApiPoll**     | epoll_wait   | kevent | FD_ISSET |             |
|                   |              |        |          |             |
|                   |              |        |          |             |

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)
- [Concurrency](/docs/CS/DB/Redis/Concurrency.md)

## References

1. [Redis Event Library](https://redis.io/topics/internals-rediseventlib)
