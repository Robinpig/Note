## Introduction

Redis是 多进程 + 多线程 混合并发模型

- 多进程: 子进程处理[持久化]() RDB/AOF
- 多线程: 主线程 + 后台线程 + IO线程





## 多进程

Redis 封装了 redisFork 函数用于子进程的创建

```c

/* purpose is one of CHILD_TYPE_ types */
int redisFork(int purpose) {
    if (isMutuallyExclusiveChildType(purpose)) {
        if (hasActiveChildProcess()) {
            errno = EEXIST;
            return -1;
        }

        openChildInfoPipe();
    }

    int childpid;
    long long start = ustime();
    if ((childpid = fork()) == 0) {
        /* Child */
    } else {
        /* Parent */
    }
    return childpid;
}
```





子进程触发条件

- rewriteAppendOnlyFileBackground
- rdbSaveToSlavesSockets
- rdbSaveBackground



LDB 和 MODULE 也会创建子进程




## 多线程



Redis 使用单线程模型进行设计 保证了每个操作的原子性，减少了线程创建的开销 也减少了线程的上下文切换和竞争 不需要考虑各种锁问题 同时能带来更好的可维护性，方便开发和调试

> It’s not very frequent that CPU becomes your bottleneck with Redis, as usually Redis is either memory or network bound.
> For instance, using pipelining Redis running on an average Linux system can deliver even 1 million requests per second, so if your application mainly uses O(N) or O(log(N)) commands, it is hardly going to use too much CPU.

如果这种吞吐量不能满足我们的需求，更推荐的做法是使用分片的方式将不同的请求交给不同的 Redis 服务器来处理，而不是在同一个 Redis 服务中引入大量的多线程操作

Redis 4.0后开始使用多线程 新版的 Redis 服务在执行一些命令时就会使用主处理线程之外的其他线程，例如 UNLINK、FLUSHALL ASYNC、FLUSHDB ASYNC 等非阻塞的删除操作

> However with Redis 4.0 we started to make Redis more threaded.
> For now this is limited to deleting objects in the background, and to blocking commands implemented via Redis modules.
> For the next releases, the plan is to make Redis more and more threaded.



Reids 6.0 版本增加了 IO线程



```c
// debug.c
void killThreads(void) {
    killMainThread();
    bioKillThreads();
    killIOThreads();
}
```



后台线程个数为 3 个（BIO_NUM_OPS），通过消息队列实现多线程的生产者和消费者工作方式 ——主线程生产，后台线程消费。

它主要执行三种类型操作：

1. 关闭文件。例如打开了 aof 和 rdb 这种大型的持久化文件，需要关闭。
2. aof 文件刷盘。aof 持久化方式，主线程定时将新增内容追加到 aof 文件，只将数据写入内核缓存，并没有将其刷入磁盘，这种阻塞耗时的脏活累活需要后台线程去做。
3. 释放体量大的数据。key-value 数据结构，主线程将 key 和 value 解除关系后，如果 value 很小的话，主线程实时释放，否则需要后台线程惰性释放



```c

void *bioProcessBackgroundJobs(void *arg) {
    bio_job *job;
    unsigned long worker = (unsigned long) arg;
    sigset_t sigset;

    /* Check that the worker is within the right interval. */
    serverAssert(worker < BIO_WORKER_NUM);

    redis_set_thread_title(bio_worker_title[worker]);

    redisSetCpuAffinity(server.bio_cpulist);

    makeThreadKillable();

    pthread_mutex_lock(&bio_mutex[worker]);
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
        if (listLength(bio_jobs[worker]) == 0) {
            pthread_cond_wait(&bio_newjob_cond[worker], &bio_mutex[worker]);
            continue;
        }
        /* Get the job from the queue. */
        ln = listFirst(bio_jobs[worker]);
        job = ln->value;
        /* It is now possible to unlock the background system as we know have
         * a stand alone job structure to process.*/
        pthread_mutex_unlock(&bio_mutex[worker]);

        /* Process the job accordingly to its type. */
        int job_type = job->header.type;

        if (job_type == BIO_CLOSE_FILE) {
            if (job->fd_args.need_fsync &&
                redis_fsync(job->fd_args.fd) == -1 &&
                errno != EBADF && errno != EINVAL)
            {
                serverLog(LL_WARNING, "Fail to fsync the AOF file: %s",strerror(errno));
            }
            if (job->fd_args.need_reclaim_cache) {
                if (reclaimFilePageCache(job->fd_args.fd, 0, 0) == -1) {
                    serverLog(LL_NOTICE,"Unable to reclaim page cache: %s", strerror(errno));
                }
            }
            close(job->fd_args.fd);
        } else if (job_type == BIO_AOF_FSYNC || job_type == BIO_CLOSE_AOF) {
            /* The fd may be closed by main thread and reused for another
             * socket, pipe, or file. We just ignore these errno because
             * aof fsync did not really fail. */
            if (redis_fsync(job->fd_args.fd) == -1 &&
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
                atomicSet(server.fsynced_reploff_pending, job->fd_args.offset);
            }

            if (job->fd_args.need_reclaim_cache) {
                if (reclaimFilePageCache(job->fd_args.fd, 0, 0) == -1) {
                    serverLog(LL_NOTICE,"Unable to reclaim page cache: %s", strerror(errno));
                }
            }
            if (job_type == BIO_CLOSE_AOF)
                close(job->fd_args.fd);
        } else if (job_type == BIO_LAZY_FREE) {
            job->free_args.free_fn(job->free_args.free_args);
        } else if ((job_type == BIO_COMP_RQ_CLOSE_FILE) ||
                   (job_type == BIO_COMP_RQ_AOF_FSYNC) ||
                   (job_type == BIO_COMP_RQ_LAZY_FREE)) {
            bio_comp_item *comp_rsp = zmalloc(sizeof(bio_comp_item));
            comp_rsp->func = job->comp_rq.fn;
            comp_rsp->arg = job->comp_rq.arg;

            /* just write it to completion job responses */
            pthread_mutex_lock(&bio_mutex_comp);
            listAddNodeTail(bio_comp_list, comp_rsp);
            pthread_mutex_unlock(&bio_mutex_comp);

            if (write(job_comp_pipe[1],"A",1) != 1) {
                /* Pipe is non-blocking, write() may fail if it's full. */
            }
        } else {
            serverPanic("Wrong job type in bioProcessBackgroundJobs().");
        }
        zfree(job);

        /* Lock again before reiterating the loop, if there are no longer
         * jobs to process we'll block again in pthread_cond_wait(). */
        pthread_mutex_lock(&bio_mutex[worker]);
        listDelNode(bio_jobs[worker], ln);
        bio_jobs_counter[job_type]--;
        pthread_cond_signal(&bio_newjob_cond[worker]);
    }
}
```



o-threads 线程配置，redis.conf 配置文件默认是不开放的，默认只有一个主线程在工作

如果开放多线程配置 那么 IO 处理线程默认共有 4 个，包括主线程

```

# redis.conf

# 配置多线程处理线程个数，默认 4。
# io-threads 4
#
# 多线程是否处理读事件，默认关闭。
# io-threads-do-reads no

```







默认开启多线程 IO 方式：

线程个数：主线程 + 3 个后台线程 + 3 个 IO 线程 = 7 个线程。

进程个数：主进程 + 1 个子进程 = 2 进程。



默认开启多线程 IO 后，经过统计线程共有 7 个，子进程有 1 个。理论上 CPU 的核心最少得 8 个, Redis 跑起来才能发挥最佳性能。



由于其它 jemalloc 库也会创建两个线程 所以 CPU核心需要多一些



开启 CPU 亲缘性设置，Redis QPS 可以提升15%

> [Redis 如何绑定 CPU](https://www.yisu.com/zixun/672271.html)



## Links

- [Redis](/docs/CS/DB/Redis/Redis.md?id=struct)

## References

1. [[Redis] 浅析 Redis 并发模型](https://wenfh2020.com/2023/12/25/redis-multi-thread/)