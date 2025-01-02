## Introduction


从 Redis 调试代码中，我们可以看到，Redis 线程主要分为 3 类：
1. 主线程：负责程序的主逻辑，当然也负责 IO。
2. 后台线程：延时回收耗时的系统资源。
3. 网络 IO 线程：Redis 6.0 版本增加的 IO 线程，利用多核资源，实现 IO 并发。

后台线程个数为 3 个（BIO_NUM_OPS），通过消息队列实现多线程的生产者和消费者工作方式 ——主线程生产，后台线程消费。
它主要执行三种类型操作：
1. 关闭文件。例如打开了 aof 和 rdb 这种大型的持久化文件，需要关闭。
2. aof 文件刷盘。aof 持久化方式，主线程定时将新增内容追加到 aof 文件，只将数据写入内核缓存，并没有将其刷入磁盘，这种阻塞耗时的脏活累活需要后台线程去做。
3. 释放体量大的数据。key-value 数据结构，主线程将 key 和 value 解除关系后，如果 value 很小的话，主线程实时释放，否则需要后台线程惰性释放



Multi I/O



**主要流程**：

1. 主线程负责接收建立连接请求，获取 `socket` 放入全局等待读处理队列；
2. 主线程通过轮询将可读 `socket` 分配给 IO 线程；
3. 主线程阻塞等待 IO 线程读取 `socket` 完成；
4. 主线程执行 IO 线程读取和解析出来的 Redis 请求命令；
5. 主线程阻塞等待 IO 线程将指令执行结果回写回 `socket`完毕；
6. 主线程清空全局队列，等待客户端后续的请求

![](https://mmbiz.qpic.cn/mmbiz_png/EoJib2tNvVtficyIzKOicibvLa33THndmjqmSibCy8KnXf0ZE3WRyWAfCUSgicDfaictMhgySliaQ7f4nvfqdecoNKJX6A/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)


io-threads 线程配置，redis.conf 配置文件默认是不开放的，默认只有一个线程在工作，这个线程就是 主线程。
如果开放多线程配置，io-threads 4 那么 IO 处理线程默认共有 4 个，包括主线程。也就是说，新增的 IO 线程有 3 个。
默认开启多线程 IO 方式：
线程个数：主线程 + 3 个后台线程 + 3 个 IO 线程 = 7 个线程。
进程个数：主进程 + 1 个子进程 = 2 进程。
当然可以根据实际需要设置 IO 线程个数。
默认 开启多线程 IO 后，经过统计线程共有 7 个，子进程有 1 个。理论上 CPU 的核心最少得 8 个, Redis 跑起来才能发挥最佳性能。
Redis 默认使用自带的第三方内存库：jemalloc，它也会创建线程

IO 线程默认不开放 读 操作，因为 Redis 作为数据缓存服务，一般它读入数据量是非常小的，写出数据量却非常大。


```
# redis.conf

# 配置多线程处理线程个数，默认 4。
# io-threads 4
#
# 多线程是否处理读事件，默认关闭。
# io-threads-do-reads no
```


```c
// config.c
standardConfig static_configs[] = {
    ...
    /* Single threaded by default */
    createIntConfig("io-threads", NULL, \
        DEBUG_CONFIG | IMMUTABLE_CONFIG, 1, 128, \
        server.io_threads_num, 1, INTEGER_CONFIG, NULL, NULL),
    ...
}
```


- 如果没开启多线程，那么 Redis 只会使用主线程处理网络 IO，主线程单线程处理网络 IO 是串行的。
- 为了保证主逻辑处理方式整体不变，多线程 IO 工作方式，不允许同时并发读写操作，同一时刻只允许读或只允许写。
- 如果开启了多线程，而且等待处理的 client 数量很少，新增的网络 IO 线程会被挂起，仍然使用主线程工作；否则启用多线程工作，将等待的 clients，平均分配给多个线程（主线程+新增线程）并行处理。
- 任务分配完以后，主线程将处理自己的任务，并等待新增线程都处理完任务后，才会执行下一个步骤的其它操作，这样做的目的是为了保证整体逻辑串行；不因为引入多线程处理方式改变了原来的主逻辑，尽力将多线程并行逻辑的影响减少到最小

Redis 6.0 引入 IO 多线程后，增加了处理器亲和性的设置功能


```config
io-threads-do-reads yes
io-threads 4
```

4 核的机器建议设置为 2 或 3 个线程，8核的建议设置为 6 个线程，线程数一定要小于机器核数。

Redis 的多线程网络模型实际上并不是一个标准的 `Multi-Reactors/Master-Workers`模型。

Redis 的多线程方案中，I/O 线程任务仅仅是通过 socket 读取客户端请求命令并解析，却没有真正去执行命令。

所有客户端命令最后还需要回到主线程去执行，因此对多核的利用率并不算高，而且每次主线程都必须在分配完任务之后忙轮询等待所有 I/O 线程完成任务之后才能继续执行其他逻辑。





```c
// bio.h
/* Background job opcodes */
#define BIO_CLOSE_FILE    0 /* Deferred close(2) syscall. */
#define BIO_AOF_FSYNC     1 /* Deferred AOF fsync. */
#define BIO_LAZY_FREE     2 /* Deferred objects freeing. */
#define BIO_NUM_OPS       3
```

```c
// bio.c
/* This structure represents a background Job. It is only used locally to this
 * file as the API does not expose the internals at all. */
struct bio_job {
    time_t time; /* Time at which the job was created. */
    /* Job specific arguments.*/
    int fd; /* Fd for file based background jobs */
    lazy_free_fn *free_fn; /* Function that will free the provided arguments */
    void *free_args[]; /* List of arguments to be passed to the free function */
};
```

job queue

```c


static pthread_t bio_threads[BIO_NUM_OPS];
static pthread_mutex_t bio_mutex[BIO_NUM_OPS];
static pthread_cond_t bio_newjob_cond[BIO_NUM_OPS];
static pthread_cond_t bio_step_cond[BIO_NUM_OPS];
static list *bio_jobs[BIO_NUM_OPS];
```

The following array is used to hold the number of pending jobs for every OP type. This allows us to export the
bioPendingJobsOfType() API that is useful when the main thread wants to perform some operation that may involve objects
shared with the background thread. The main thread will just wait that there are no longer jobs of this type to be
executed before performing the sensible operation. This data is also useful for reporting.

```c

static unsigned long long bio_pending[BIO_NUM_OPS];
```

called by [InitServerLast](/docs/CS/DB/Redis/start.md?id=InitServerLast)

pthread_create

invoke `bioProcessBackgroundJobs`

```c

/* Initialize the background system, spawning the thread. */
void bioInit(void) {
    pthread_attr_t attr;
    pthread_t thread;
    size_t stacksize;
    int j;

    /* Initialization of state vars and objects */
    for (j = 0; j < BIO_NUM_OPS; j++) {
        pthread_mutex_init(&bio_mutex[j],NULL);
        pthread_cond_init(&bio_newjob_cond[j],NULL);
        pthread_cond_init(&bio_step_cond[j],NULL);
        bio_jobs[j] = listCreate();
        bio_pending[j] = 0;
    }

    /* Set the stack size as by default it may be small in some system */
    pthread_attr_init(&attr);
    pthread_attr_getstacksize(&attr,&stacksize);
    if (!stacksize) stacksize = 1; /* The world is full of Solaris Fixes */
    while (stacksize < REDIS_THREAD_STACK_SIZE) stacksize *= 2;
    pthread_attr_setstacksize(&attr, stacksize);

    /* Ready to spawn our threads. We use the single argument the thread
     * function accepts in order to pass the job ID the thread is
     * responsible of. */
    for (j = 0; j < BIO_NUM_OPS; j++) {
        void *arg = (void*)(unsigned long) j;
        if (pthread_create(&thread,&attr,bioProcessBackgroundJobs,arg) != 0) {
            serverLog(LL_WARNING,"Fatal: Can't initialize Background Jobs.");
            exit(1);
        }
        bio_threads[j] = thread;
    }
}
```

```c

void *bioProcessBackgroundJobs(void *arg) {
    struct bio_job *job;
    unsigned long type = (unsigned long) arg;
    sigset_t sigset;

    /* Check that the type is within the right interval. */
    if (type >= BIO_NUM_OPS) {
        serverLog(LL_WARNING,
            "Warning: bio thread started with wrong type %lu",type);
        return NULL;
    }

    switch (type) {
    case BIO_CLOSE_FILE:
        redis_set_thread_title("bio_close_file");
        break;
    case BIO_AOF_FSYNC:
        redis_set_thread_title("bio_aof_fsync");
        break;
    case BIO_LAZY_FREE:
        redis_set_thread_title("bio_lazy_free");
        break;
    }

    redisSetCpuAffinity(server.bio_cpulist);

    makeThreadKillable();

    pthread_mutex_lock(&bio_mutex[type]);
    /* Block SIGALRM so we are sure that only the main thread will
     * receive the watchdog signal. */
    sigemptyset(&sigset);
    sigaddset(&sigset, SIGALRM);
    if (pthread_sigmask(SIG_BLOCK, &sigset, NULL))
        serverLog(LL_WARNING,
            "Warning: can't mask SIGALRM in bio.c thread: %s", strerror(errno));

    while(1) {
        listNode *ln;

        /* The loop always starts with the lock hold. */
        if (listLength(bio_jobs[type]) == 0) {
            pthread_cond_wait(&bio_newjob_cond[type],&bio_mutex[type]);
            continue;
        }
        /* Pop the job from the queue. */
        ln = listFirst(bio_jobs[type]);
        job = ln->value;
        /* It is now possible to unlock the background system as we know have
         * a stand alone job structure to process.*/
        pthread_mutex_unlock(&bio_mutex[type]);

        /* Process the job accordingly to its type. */
        if (type == BIO_CLOSE_FILE) {
            close(job->fd);
        } else if (type == BIO_AOF_FSYNC) {
            /* The fd may be closed by main thread and reused for another
             * socket, pipe, or file. We just ignore these errno because
             * aof fsync did not really fail. */
            if (redis_fsync(job->fd) == -1 &&
                errno != EBADF && errno != EINVAL)
            {
                int last_status;
                atomicGet(server.aof_bio_fsync_status,last_status);
                atomicSet(server.aof_bio_fsync_status,C_ERR);
                atomicSet(server.aof_bio_fsync_errno,errno);
                if (last_status == C_OK) {
                    serverLog(LL_WARNING,
                        "Fail to fsync the AOF file: %s",strerror(errno));
                }
            } else {
                atomicSet(server.aof_bio_fsync_status,C_OK);
            }
        } else if (type == BIO_LAZY_FREE) {
            job->free_fn(job->free_args);
        } else {
            serverPanic("Wrong job type in bioProcessBackgroundJobs().");
        }
        zfree(job);

        /* Lock again before reiterating the loop, if there are no longer
         * jobs to process we'll block again in pthread_cond_wait(). */
        pthread_mutex_lock(&bio_mutex[type]);
        listDelNode(bio_jobs[type],ln);
        bio_pending[type]--;

        /* Unblock threads blocked on bioWaitStepOfType() if any. */
        pthread_cond_broadcast(&bio_step_cond[type]);
    }
}

```

create job

```c

void bioCreateFsyncJob(int fd) {
    struct bio_job *job = zmalloc(sizeof(*job));
    job->fd = fd;

    bioSubmitJob(BIO_AOF_FSYNC, job);
}


void bioSubmitJob(int type, struct bio_job *job) {
    job->time = time(NULL);
    pthread_mutex_lock(&bio_mutex[type]);
    listAddNodeTail(bio_jobs[type],job);
    bio_pending[type]++;
    pthread_cond_signal(&bio_newjob_cond[type]);
    pthread_mutex_unlock(&bio_mutex[type]);
}
```

lazy free

```c

void bioCreateLazyFreeJob(lazy_free_fn free_fn, int arg_count, ...) {
    va_list valist;
    /* Allocate memory for the job structure and all required
     * arguments */
    struct bio_job *job = zmalloc(sizeof(*job) + sizeof(void *) * (arg_count));
    job->free_fn = free_fn;

    va_start(valist, arg_count);
    for (int i = 0; i < arg_count; i++) {
        job->free_args[i] = va_arg(valist, void *);
    }
    va_end(valist);
    bioSubmitJob(BIO_LAZY_FREE, job);
}
```

```c

struct redisServer {
  /* Lazy free */
    int lazyfree_lazy_eviction;
    int lazyfree_lazy_expire;
    int lazyfree_lazy_server_del;
    int lazyfree_lazy_user_del;
    int lazyfree_lazy_user_flush;
    // ...
    }
```

```config
// redis.conf
lazyfree-lazy-eviction no
lazyfree-lazy-expire no
lazyfree-lazy-server-del no
replica-lazy-flush no
```

Return the amount of work needed in order to free an object. 

- The return value is not always the actual number of allocations the object is composed of, but a number proportional to it. 
- For strings the function always returns 1. 
- For aggregated objects represented by hash tables or other data structures the function just returns the number of elements the object is composed of. 
- Objects composed of single allocations are always reported as having a single item even if they are actually logical composed of multiple elements. 
- For lists the function returns the number of elements in the quicklist representing the list.
```c
// lazyfree.c


/* Delete a key, value, and associated expiration entry if any, from the DB.
 * If there are enough allocations to free the value object may be put into
 * a lazy free list instead of being freed synchronously. The lazy free list
 * will be reclaimed in a different bio.c thread. */
#define LAZYFREE_THRESHOLD 64

size_t lazyfreeGetFreeEffort(robj *key, robj *obj) {
    if (obj->type == OBJ_LIST) {
        quicklist *ql = obj->ptr;
        return ql->len;
    } else if (obj->type == OBJ_SET && obj->encoding == OBJ_ENCODING_HT) {
        dict *ht = obj->ptr;
        return dictSize(ht);
    } else if (obj->type == OBJ_ZSET && obj->encoding == OBJ_ENCODING_SKIPLIST){
        zset *zs = obj->ptr;
        return zs->zsl->length;
    } else if (obj->type == OBJ_HASH && obj->encoding == OBJ_ENCODING_HT) {
        dict *ht = obj->ptr;
        return dictSize(ht);
    } else if (obj->type == OBJ_STREAM) {
        size_t effort = 0;
        stream *s = obj->ptr;

        /* Make a best effort estimate to maintain constant runtime. Every macro
         * node in the Stream is one allocation. */
        effort += s->rax->numnodes;

        /* Every consumer group is an allocation and so are the entries in its
         * PEL. We use size of the first group's PEL as an estimate for all
         * others. */
        if (s->cgroups && raxSize(s->cgroups)) {
            raxIterator ri;
            streamCG *cg;
            raxStart(&ri,s->cgroups);
            raxSeek(&ri,"^",NULL,0);
            /* There must be at least one group so the following should always
             * work. */
            serverAssert(raxNext(&ri));
            cg = ri.data;
            effort += raxSize(s->cgroups)*(1+raxSize(cg->pel));
            raxStop(&ri);
        }
        return effort;
    } else if (obj->type == OBJ_MODULE) {
        moduleValue *mv = obj->ptr;
        moduleType *mt = mv->type;
        if (mt->free_effort != NULL) {
            size_t effort  = mt->free_effort(key,mv->value);
            /* If the module's free_effort returns 0, it will use asynchronous free
             memory by default */
            return effort == 0 ? ULONG_MAX : effort;
        } else {
            return 1;
        }
    } else {
        return 1; /* Everything else is a single allocation. */
    }
}
```


```c
int dbAsyncDelete(redisDb *db, robj *key) {
    /* Deleting an entry from the expires dict will not free the sds of
     * the key, because it is shared with the main dictionary. */
    if (dictSize(db->expires) > 0) dictDelete(db->expires,key->ptr);

    /* If the value is composed of a few allocations, to free in a lazy way
     * is actually just slower... So under a certain limit we just free
     * the object synchronously. */
    dictEntry *de = dictUnlink(db->dict,key->ptr);
    if (de) {
        robj *val = dictGetVal(de);

        /* Tells the module that the key has been unlinked from the database. */
        moduleNotifyKeyUnlink(key,val);

        size_t free_effort = lazyfreeGetFreeEffort(key,val);

        /* If releasing the object is too much work, do it in the background
         * by adding the object to the lazy free list.
         * Note that if the object is shared, to reclaim it now it is not
         * possible. This rarely happens, however sometimes the implementation
         * of parts of the Redis core may call incrRefCount() to protect
         * objects, and then call dbDelete(). In this case we'll fall
         * through and reach the dictFreeUnlinkedEntry() call, that will be
         * equivalent to just calling decrRefCount(). */
        if (free_effort > LAZYFREE_THRESHOLD && val->refcount == 1) {
            atomicIncr(lazyfree_objects,1);
            bioCreateLazyFreeJob(lazyfreeFreeObject,1, val);
            dictSetVal(db->dict,de,NULL);
        }
    }

    /* Release the key-val pair, or just the key if we set the val
     * field to NULL in order to lazy free it later. */
    if (de) {
        dictFreeUnlinkedEntry(db->dict,de);
        if (server.cluster_enabled) slotToKeyDel(key->ptr);
        return 1;
    } else {
        return 0;
    }
}



/* Free an object, if the object is huge enough, free it in async way. */
void freeObjAsync(robj *key, robj *obj) {
    size_t free_effort = lazyfreeGetFreeEffort(key,obj);
    if (free_effort > LAZYFREE_THRESHOLD && obj->refcount == 1) {
        atomicIncr(lazyfree_objects,1);
        bioCreateLazyFreeJob(lazyfreeFreeObject,1,obj);
    } else {
        decrRefCount(obj);
    }
}
```

compare with dbSyncDelete
```c
// db.c

/* Delete a key, value, and associated expiration entry if any, from the DB */
int dbSyncDelete(redisDb *db, robj *key) {
    /* Deleting an entry from the expires dict will not free the sds of
     * the key, because it is shared with the main dictionary. */
    if (dictSize(db->expires) > 0) dictDelete(db->expires,key->ptr);
    dictEntry *de = dictUnlink(db->dict,key->ptr);
    if (de) {
        robj *val = dictGetVal(de);
        /* Tells the module that the key has been unlinked from the database. */
        moduleNotifyKeyUnlink(key,val);
        dictFreeUnlinkedEntry(db->dict,de);
        if (server.cluster_enabled) slotToKeyDel(key->ptr);
        return 1;
    } else {
        return 0;
    }
}
```
Empty the slots-keys map of Redis CLuster by **creating a new empty one and freeing the old one**.
```c
// db.c
void slotToKeyFlush(int async) {
    rax *old = server.cluster->slots_to_keys;

    server.cluster->slots_to_keys = raxNew();
    memset(server.cluster->slots_keys_count,0,
           sizeof(server.cluster->slots_keys_count));
    freeSlotsToKeysMap(old, async);
}
```


Empty a Redis DB asynchronously. What the function does actually is to **create a new empty set of hash tables and scheduling the old ones for lazy freeing**. 
```c
void emptyDbAsync(redisDb *db) {
    dict *oldht1 = db->dict, *oldht2 = db->expires;
    db->dict = dictCreate(&dbDictType,NULL);
    db->expires = dictCreate(&dbExpiresDictType,NULL);
    atomicIncr(lazyfree_objects,dictSize(oldht1));
    bioCreateLazyFreeJob(lazyfreeFreeDatabase,2,oldht1,oldht2);
}
```