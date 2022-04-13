## Introduction

This file defines all the I/O functions with clients, masters and replicas
(which in Redis are just special clients):

* `createClient()` allocates and initializes a new client.
* the `addReply*()` family of functions are used by command implementations in order to append data to the client structure, that will be transmitted to the client as a reply for a given command executed.
* `writeToClient()` transmits the data pending in the output buffers to the client and is called by the *writable event handler* `sendReplyToClient()`.
* `readQueryFromClient()` is the *readable event handler* and accumulates data read from the client into the query buffer.
* `processInputBuffer()` is the entry point in order to parse the client query buffer according to the Redis protocol. Once commands are ready to be processed, it calls `processCommand()` which is defined inside `server.c` in order to actually execute the command.
* `freeClient()` deallocates, disconnects and removes a client.



For various [reasons](http://groups.google.com/group/redis-db/browse_thread/thread/b52814e9ef15b8d0/) Redis uses its own event library.

Redis implements its own event library. The event library is implemented in `ae.c`.

`initServer` function defined in `redis.c` initializes the numerous fields of the `redisServer` structure variable. One such field is the Redis event loop `el`:

```c
aeEventLoop *el
```

`initServer` initializes `server.el` field by calling `aeCreateEventLoop` defined in `ae.c`. The definition of `aeEventLoop` is below:

```c
typedef struct aeEventLoop
{
    int maxfd;
    long long timeEventNextId;
    aeFileEvent events[AE_SETSIZE]; /* Registered events */
    aeFiredEvent fired[AE_SETSIZE]; /* Fired events */
    aeTimeEvent *timeEventHead;
    int stop;
    void *apidata; /* This is used for polling API specific data */
    aeBeforeSleepProc *beforesleep;
} aeEventLoop;
```

### Use the best first

```c
// ae.c

/* Include the best multiplexing layer supported by this system.
 * The following should be ordered by performances, descending. */
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

## Multiple IO

Redis is mostly single threaded, however there are certain threaded operations such as UNLINK, slow I/O accesses and other things that are performed on side threads.

Now it is also possible to handle Redis clients socket reads and writes in different I/O threads. Since especially writing is so slow, normally Redis users use pipelining in order to speed up the Redis performances per core, and spawn multiple instances in order to scale more. Using I/O threads it is possible to easily speedup two times Redis without resorting to pipelining nor sharding of the instance.

By default threading is disabled, we suggest enabling it only in machines that have at least 4 or more cores, leaving at least one spare core.

Using more than 8 threads is unlikely to help much. We also recommend using threaded I/O only if you actually have performance problems, with Redis instances being able to use a quite big percentage of CPU time, otherwise there is no point in using this feature.

So for instance if you have a four cores boxes, try to use 2 or 3 I/O threads, if you have a 8 cores, try to use 6 threads. In order to enable I/O threads use the following configuration directive:
```
io-threads 4
```

Setting io-threads to 1 will just use the main thread as usual. When I/O threads are enabled, we only use threads for writes, that is to thread the write(2) syscall and transfer the client buffers to the socket. However it is also possible to enable threading of reads and protocol parsing using the following configuration directive, by setting it to yes:

```
io-threads-do-reads no
```

Usually threading reads doesn't help much.
- **NOTE 1:** This configuration directive cannot be changed at runtime via CONFIG SET. Aso this feature currently does not work when SSL is enabled.
- **NOTE 2:** If you want to test the Redis speedup using redis-benchmark, make sure you also run the benchmark itself in threaded mode, using the --threads option to match the number of Redis threads, otherwise you'll not be able to notice the improvements.



## Events



```c
/* File event structure */
typedef struct aeFileEvent {
    int mask; /* one of AE_(READABLE|WRITABLE|BARRIER) */
    aeFileProc *rfileProc;
    aeFileProc *wfileProc;
    void *clientData;
} aeFileEvent;
```





### Summaries of Events



| Event Type  | Socket Type | Callback Method     | For              |
| ----------- | ----------- | ------------------- | ---------------- |
| AE_READABLE | Listen      | acceptTCPHandler    | connect          |
| AE_READABLE | connected   | readQueryFromClient | read and execute |
| AE_WRITABLE | connected   | sendReplyToClient   | Return data      |



## epoll

Redis use ae wrap epoll rather than use libevent

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




## Summary



|                   | epoll        | kqueue | select   | evport      |
| ----------------- | ------------ | ------ | -------- | ----------- |
| **aeApiCreate**   | epoll_create | kevent | FD_ZERO  | port_create |
| **aeApiAddEvent** | epoll_ctl    | kevent | FD_SET   |             |
| **aeApiDelEvent** | epoll_ctl    | kevent | FD_CLR   |             |
| **aeApiPoll**     | epoll_wait   | kevent | FD_ISSET |             |
|                   |              |        |          |             |
|                   |              |        |          |             |



## References

1. [Redis Event Library](https://redis.io/topics/internals-rediseventlib)

