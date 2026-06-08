## Introduction

一个简单的事件驱动编程库。

此文件（*networking.c*）定义了与客户端、主库和副本（在 Redis 中只是特殊客户端）的所有 I/O 函数：

* `createClient()` 分配并初始化一个新客户端。
* `addReply*()` 函数系列由命令实现使用，以将数据附加到客户端结构，该结构将作为给定命令的回复传输给客户端。
* `writeToClient()` 将输出缓冲区中待处理的数据传输给客户端，由*可写事件处理器* `sendReplyToClient()` 调用。
* `readQueryFromClient()` 是*可读事件处理器*，将从客户端读取的数据累积到查询缓冲区中。
* `processInputBuffer()` 是根据 Redis 协议解析客户端查询缓冲区的入口点。
  一旦命令准备好处理，它调用在 `server.c` 中定义的 `processCommand()` 以实际执行命令。
* `freeClient()` 释放、断开连接并移除客户端。

## EventLoop

由于各种[原因](http://groups.google.com/group/redis-db/browse_thread/thread/b52814e9ef15b8d0/)，Redis 使用自己的事件库。

`Redis` 需要对事件做整体抽象，于是定义了 `aeEventLoop` 结构。

定义在 `redis.c` 中的 `initServer` 函数初始化 [redisServer 结构](/docs/CS/DB/Redis/server.md?id=server) 变量的众多字段。
其中一个字段是 Redis 事件循环 `el`：

```c
aeEventLoop *el
```

`initServer` 通过调用在 `ae.c` 中定义的 `aeCreateEventLoop` 初始化 `server.el` 字段。`aeEventLoop` 的定义如下：

```c
typedef struct aeEventLoop {
    int maxfd;   /* 当前注册的最高文件描述符 */
    int setsize; /* 跟踪的最大文件描述符数量 */
    long long timeEventNextId;
    time_t lastTime;     /* 用于检测系统时钟偏移 */
    aeFileEvent *events; /* 注册的事件 */
    aeFiredEvent *fired; /* 触发的事件 */
    aeTimeEvent *timeEventHead;
    int stop;
    void *apidata; /* 用于轮询 API 特定数据 */
    aeBeforeSleepProc *beforesleep;
    aeBeforeSleepProc *aftersleep;
    int flags;
} aeEventLoop;
```

aeEventLoop 结构保存了一个 void *类型的万能指针 apidata，是用来保存轮询事件的状态的，也就是保存底层调用的多路复用库的事件状态。
关于 Redis 的多路复用库的选择，Redis 包装了常见的 select、epoll、evport、kqueue，他们在编译阶段，根据不同的系统选择性能最高的一个多路复用库作为 Redis 的多路复用程序的实现。
而且所有库实现的接口名称都是相同的，因此 Redis 多路复用程序底层实现是可以互换的。

包含此系统支持的最佳多路复用层。
以下应按性能降序排列。

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

`aeCreateEventLoop` 首先 `malloc` 分配 `aeEventLoop` 结构，然后调用 `ae_epoll.c:aeApiCreate`。

InitServer 中调用了 aeCreateEventLoop。

`aeApiCreate` `malloc` 分配 `aeApiState`，它有两个字段 —— `epfd` 保存了由 [`epoll_create`](http://man.cx/epoll_create(2)) 调用返回的 `epoll` 文件描述符；`events` 是由 Linux `epoll` 库定义的 `struct epoll_event` 类型。`events` 字段的用途稍后描述。

接下来是 `ae.c:aeCreateTimeEvent`。但在此之前，`initServer` 调用 `anet.c:anetTcpServer`，它创建并返回一个*监听描述符*。该描述符默认监听 *6379 端口*。返回的*监听描述符*存储在 `server.fd` 字段中。

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
    
    /* mask == AE_NONE 的事件不设置。因此用此值初始化向量。 */
    for (i = 0; i < setsize; i++)
        eventLoop->events[i].mask = AE_NONE;
    return eventLoop;
}
```

aeCreateEventLoop() 内部会调用 aeApiCreate()，根据不同平台支持选择调用 epoll、select 或者 kqueue 的 API，创建事件监听。

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

`ae.c:aeProcessEvents` 通过在事件循环上调用 `ae.c:aeSearchNearestTimer` 来查找即将在最短时间内到期的定时事件。
在我们的例子中，事件循环中只有一个由 `ae.c:aeCreateTimeEvent` 创建的定时器事件。

记住，`aeCreateTimeEvent` 创建的定时器事件现在可能已经超时，因为其过期时间设置为 1 毫秒。
由于定时器已过期，`tvp` `timeval` 结构变量的秒和微秒字段初始化为零。

`tvp` 结构变量与事件循环变量一起传递给 `ae_epoll.c:aeApiPoll`。

`aeApiPoll` 函数在 `epoll` 描述符上执行 [`epoll_wait`](http://man.cx/epoll_wait)，并用以下详细信息填充 `eventLoop->fired` 表：

- `fd`：现在可以根据 mask 值执行读/写操作的描述符。
- `mask`：现在可以在相应描述符上执行的读/写事件。

`aeApiPoll` 返回已准备好的此类文件事件的数量。
现在将上下文联系起来，如果有客户端请求连接，`aeApiPoll` 将会注意到并填充 `eventLoop->fired` 表，其中包含描述符为*监听描述符*且 mask 为 `AE_READABLE` 的条目。

现在，`aeProcessEvents` 调用注册为回调的 `redis.c:acceptHandler`。`acceptHandler` 在*监听描述符*上执行 `accept`，返回与客户端的*连接描述符*。
`redis.c:createClient` 通过调用 `ae.c:aeCreateFileEvent` 在*连接描述符*上添加文件事件，如下所示：

```c
if (aeCreateFileEvent(server.el, c->fd, AE_READABLE,
    readQueryFromClient, c) == AE_ERR) {
    freeClient(c);
    return NULL;
}
```

`c` 是 `redisClient` 结构变量，`c->fd` 是连接描述符。

接下来，`ae.c:aeProcessEvent` 调用 `ae.c:processTimeEvents`。

处理每个待处理的定时事件，然后处理每个待处理的文件事件（可能由刚处理的定时事件回调注册）。
不带特殊标志时，函数将休眠直到某个文件事件触发，或直到下一个定时事件发生（如果有）。

* 如果 flags 为 0，函数不做任何操作并返回。
* 如果 flags 设置了 AE_ALL_EVENTS，处理所有类型的事件。
* 如果 flags 设置了 AE_FILE_EVENTS，处理文件事件。
* 如果 flags 设置了 AE_TIME_EVENTS，处理定时事件。
* 如果 flags 设置了 AE_DONT_WAIT，函数在所有可以不等待就处理的事件处理完后立即返回。
* 如果 flags 设置了 AE_CALL_AFTER_SLEEP，调用 aftersleep 回调。
* 如果 flags 设置了 AE_CALL_BEFORE_SLEEP，调用 beforesleep 回调。

从内核取出就绪事件，根据事件的读写类型，分别进行回调处理相关业务逻辑。

```c
// ae.c
int aeProcessEvents(aeEventLoop *eventLoop, int flags)
{
    int processed = 0, numevents;

    /* 无事可做？立即返回 */
    if (!(flags & AE_TIME_EVENTS) && !(flags & AE_FILE_EVENTS)) return 0;

    /* 注意，只要想处理定时事件，
     * 即使没有文件事件要处理，我们也希望调用 select()，
     * 以便休眠直到下一个定时事件准备好触发。 */
    if (eventLoop->maxfd != -1 ||
        ((flags & AE_TIME_EVENTS) && !(flags & AE_DONT_WAIT))) {
        // ... 计算超时，调用 aeApiPoll ...
    }

    /* 检查定时事件 */
    if (flags & AE_TIME_EVENTS)
        processed += processTimeEvents(eventLoop);

    return processed; /* 返回已处理的文件/定时事件数 */
}
```

#### aeSearchNearestTimer

搜索第一个要触发的定时器。
此操作有助于知道 select 可以休眠多长时间而不会延迟任何事件。
如果没有定时器则返回 NULL。
注意，这是 O(N) 的，因为定时事件未排序。
可能的优化（目前 Redis 不需要，但是...）：

1. 按顺序插入事件，使最近的就成为头部。
   更好，但插入或删除定时器仍然是 O(N)。
2. 使用跳表使此操作为 O(1)，插入为 O(log(N))。

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
    // ...
}
```

### beforeSleep

每次 Redis 进入事件驱动库的主循环时，即在休眠等待就绪文件描述符之前，都会调用此函数。

注意：此函数（当前）从两个函数调用：

1. aeMain - 服务器主循环
2. processEventsWhileBlocked - 在 RDB/AOF 加载期间处理客户端

如果从 processEventsWhileBlocked 调用，我们不希望执行所有操作（例如，我们不想过期键），但需要执行某些操作。

最重要的是 freeClientsInAsyncFreeQueue，但我们也会调用一些其他低风险函数。

```c
void beforeSleep(struct aeEventLoop *eventLoop) {
    // ...
    /* 处理阻塞客户端的精确超时 */
    handleBlockedClientsTimeout();

    /* 事件循环后应尽快处理待处理的读取客户端 */
    handleClientsWithPendingReadsUsingThreads();

    /* 运行快速过期循环 */
    if (server.active_expire_enabled && server.masterhost == NULL)
        activeExpireCycle(ACTIVE_EXPIRE_CYCLE_FAST);

    /* 发送所有从库 ACK 请求 */
    if (server.get_ack_from_slaves) {
        // ...
    }

    /* 发送广播模式的客户端缓存失效消息 */
    trackingBroadcastInvalidationMessages();

    /* 将 AOF 缓冲区写入磁盘 */
    flushAppendOnlyFile(0);

    /* 处理具有待处理输出缓冲区的写入 */
    handleClientsWithPendingWritesUsingThreads();

    /* 关闭需要异步关闭的客户端 */
    freeClientsInAsyncFreeQueue();
}
```

### afterSleep

此函数在事件循环多路复用 API 返回后立即调用，控制权将很快通过调用不同的事件回调返回给 Redis。

```c
void afterSleep(struct aeEventLoop *eventLoop) {
    UNUSED(eventLoop);

    if (!ProcessingEventsWhileBlocked) {
        if (moduleCount()) moduleAcquireGIL();
    }
}
```

### processTimeEvents

`ae.processTimeEvents` 从 `eventLoop->timeEventHead` 开始遍历定时事件列表。

对于每个已到期的定时事件，`processTimeEvents` 调用注册的回调。
在这种情况下，它调用注册的唯一定时事件回调，即 `redis.c:serverCron`。
回调返回再次调用回调之前的时间（毫秒）。
此更改通过调用 `ae.c:aeAddMilliSeconds` 记录，将在 `ae.c:aeMain` while 循环的下一次迭代中处理。

```c
static int processTimeEvents(aeEventLoop *eventLoop) {
    // ...
}
```

如果系统时钟被调快，然后又调回正确值，定时事件可能以随机方式延迟。
通常这意味着计划的操作不会及时执行。

这里我们尝试检测系统时钟偏移，强制所有定时事件在此发生时尽快处理：**想法是尽早处理事件比无限期延迟更安全，实践也表明如此**。

## 多 I/O 线程

Redis 大多是单线程的，但某些线程操作如 UNLINK、慢 I/O 访问和其他操作在侧线程上执行。

现在也可以在多个 I/O 线程中处理 Redis 客户端套接字的读取和写入。由于尤其是写入很慢，通常 Redis 用户使用管道加速单核 Redis 性能，并生成多个实例以扩展规模。使用 I/O 线程可以轻松将 Redis 提速两倍，而无需使用管道或分片。

默认情况下，线程是禁用的，建议仅在至少 4 核或更多核的机器上启用，至少保留一个备用核。

使用超过 8 个线程不太可能有太大帮助。还建议仅在确实存在性能问题时使用线程 I/O，即 Redis 实例能够使用相当大比例的 CPU 时间，否则没有理由使用此功能。

例如，如果有四核机器，尝试使用 2 或 3 个 I/O 线程；如果有八核，尝试使用 6 个线程。启用 I/O 线程使用以下配置指令：

```
io-threads 4
```

将 io-threads 设置为 1 将仅使用主线程，与往常一样。启用 I/O 线程时，我们仅对写入使用线程，即对 write(2) 系统调用和将客户端缓冲区传输到套接字进行线程化。但也可以通过将以下配置指令设置为 yes 来启用读取和协议解析的线程化：

```
io-threads-do-reads no
```

通常，读取线程化没有太大帮助。

- **注意 1：** 此配置指令不能通过 CONFIG SET 在运行时更改。此外，此功能当前在启用 SSL 时不起作用。
- **注意 2：** 如果想使用 redis-benchmark 测试 Redis 加速效果，请确保也以线程模式运行基准测试本身，使用 --threads 选项匹配 Redis 线程数，否则不会注意到改进。

## 事件

```c
/* 文件事件结构 */
typedef struct aeFileEvent {
    int mask; /* AE_(READABLE|WRITABLE|BARRIER) 之一 */
    aeFileProc *rfileProc;
    aeFileProc *wfileProc;
    void *clientData;
} aeFileEvent;
```

rfileProc 和 wfileProc 成员分别为两个函数指针。

```c
typedef void aeFileProc(struct aeEventLoop *eventLoop, int fd, void *clientData, int mask);
```

当事件就绪时，我们需要知道文件事件的文件描述符还有事件类型才能对于锁定该事件，因此定义了 aeFiredEvent 结构统一管理。
时间事件表是一个链表，因为它有一个 next 指针域，指向下一个时间事件。
和文件事件一样，当时间事件所指定的事件发生时，也会调用对应的回调函数，结构成员 timeProc 和 finalizerProc 都是回调函数。

```c
typedef int aeTimeProc(struct aeEventLoop *eventLoop, long long id, void *clientData);
typedef void aeEventFinalizerProc(struct aeEventLoop *eventLoop, void *clientData);
```

### TimeEvent

```c
typedef struct aeTimeEvent {
    long long id; /* 时间事件标识符 */
    monotime when;
    aeTimeProc *timeProc;
    aeEventFinalizerProc *finalizerProc;
    void *clientData;
    struct aeTimeEvent *prev;
    struct aeTimeEvent *next;
    int refcount; /* 引用计数，防止在递归定时事件调用中释放定时事件 */
} aeTimeEvent;

/* 已触发的事件 */
typedef struct aeFiredEvent {
    int fd;
    int mask;
} aeFiredEvent;
```

## 事件

| 事件类型 | Socket 类型 | 回调方法 | 用途 |
| --- | --- | --- | --- |
| AE_READABLE | Listen | acceptTCPHandler | 连接 |
| AE_READABLE | connected | readQueryFromClient | 读取并执行 |
| AE_WRITABLE | connected | sendReplyToClient | 返回数据 |

### 实现

整个 I/O 多路复用模块抹平了不同平台上 I/O 多路复用函数的差异性，提供了相同的接口：

- static int aeApiCreate(aeEventLoop *eventLoop)
- static int aeApiResize(aeEventLoop *eventLoop, int setsize)
- static void aeApiFree(aeEventLoop *eventLoop)
- static int aeApiAddEvent(aeEventLoop *eventLoop, int fd, int mask)
- static void aeApiDelEvent(aeEventLoop *eventLoop, int fd, int mask)
- static int aeApiPoll(aeEventLoop *eventLoop, struct timeval *tvp)

因为各个函数所需要的参数不同，我们在每一个子模块内部通过一个 aeApiState 来存储需要的上下文信息。

## epoll

Redis 使用 ae 封装 [epoll](/docs/CS/OS/Linux/IO/epoll.md) 而不是使用 libevent。

aeApiCreate -> `epoll_create`

```c
static int aeApiCreate(aeEventLoop *eventLoop) {
    aeApiState *state = zmalloc(sizeof(aeApiState));
    if (!state) return -1;
    state->events = zmalloc(sizeof(struct epoll_event)*eventLoop->setsize);
    if (!state->events) {
        zfree(state);
        return -1;
    }
    state->epfd = epoll_create(1024); /* 1024 只是给内核的提示 */
    if (state->epfd == -1) {
        zfree(state->events);
        zfree(state);
        return -1;
    }
    eventLoop->apidata = state;
    return 0;
}
```

aeApiAddEvent -> `epoll_ctl`

```c
static int aeApiAddEvent(aeEventLoop *eventLoop, int fd, int mask) {
    // ...
}
```

aeApiDelEvent -> `epoll_ctl`

```c
static void aeApiDelEvent(aeEventLoop *eventLoop, int fd, int delmask) {
    // ...
}
```

aeApiPoll -> `epoll_wait`

通过 epoll_wait 从系统内核取出就绪文件事件，存储到 fired。

```c
static int aeApiPoll(aeEventLoop *eventLoop, struct timeval *tvp) {
    // ...
}
```

## kqueue

```c
typedef struct aeApiState {
    int kqfd;
    struct kevent *events;
} aeApiState;
```

kevent 定义在 event.h 源文件中。

```go
struct kevent {
	uintptr_t       ident;  /* 此事件的标识符 */
	int16_t         filter; /* 事件过滤器 */
	uint16_t        flags;  /* 通用标志 */
	uint32_t        fflags; /* 过滤器特定标志 */
	intptr_t        data;   /* 过滤器特定数据 */
	void            *udata; /* 不透明用户数据标识符 */
};
```

## select

```c
typedef struct aeApiState {
    fd_set rfds, wfds;
    fd_set _rfds, _wfds;
} aeApiState;
```

## 总结

| | epoll | kqueue | select | evport |
| --- | --- | --- | --- | --- |
| **aeApiCreate** | epoll_create | kevent | FD_ZERO | port_create |
| **aeApiAddEvent** | epoll_ctl | kevent | FD_SET | |
| **aeApiDelEvent** | epoll_ctl | kevent | FD_CLR | |
| **aeApiPoll** | epoll_wait | kevent | FD_ISSET | |

## 链接

- [Redis](/docs/CS/DB/Redis/Redis.md?id=struct)

## 参考

1. [Redis Event Library](https://redis.io/topics/internals-rediseventlib)
