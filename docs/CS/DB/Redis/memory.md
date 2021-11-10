## Introduction
use `INFO memory`:
```
- used_memory
  - process memory
  - data memory
  - buffer memory
    - client buffer
      - client buffer for connections
      - slaves client connections
      - pub/sub connections  
    - copy buffer
    - AOF buffer
- fragmentation
```

mem_fragmentation_ratio usually 1.03

if > 1, is fragmentation
< 1, using swap

fragmentation by 

- usually using append setrange
- delete lots of expire keys


Redis is compiled and linked against libc malloc by default, with the exception of `jemalloc` being the default on Linux systems. This default was picked because `jemalloc` has proven to have **fewer fragmentation problems** than `libc` malloc.

small: << 8byte
big : << 4KB
huge : << 4MB

## maxMemory

evict policy:
```c
//server.h

/* Redis maxmemory strategies. Instead of using just incremental number
 * for this defines, we use a set of flags so that testing for certain
 * properties common to multiple policies is faster. */
#define MAXMEMORY_FLAG_LRU (1<<0)
#define MAXMEMORY_FLAG_LFU (1<<1)
#define MAXMEMORY_FLAG_ALLKEYS (1<<2)
#define MAXMEMORY_FLAG_NO_SHARED_INTEGERS \
    (MAXMEMORY_FLAG_LRU|MAXMEMORY_FLAG_LFU)

#define MAXMEMORY_VOLATILE_LRU ((0<<8)|MAXMEMORY_FLAG_LRU)
#define MAXMEMORY_VOLATILE_LFU ((1<<8)|MAXMEMORY_FLAG_LFU)
#define MAXMEMORY_VOLATILE_TTL (2<<8)
#define MAXMEMORY_VOLATILE_RANDOM (3<<8)
#define MAXMEMORY_ALLKEYS_LRU ((4<<8)|MAXMEMORY_FLAG_LRU|MAXMEMORY_FLAG_ALLKEYS)
#define MAXMEMORY_ALLKEYS_LFU ((5<<8)|MAXMEMORY_FLAG_LFU|MAXMEMORY_FLAG_ALLKEYS)
#define MAXMEMORY_ALLKEYS_RANDOM ((6<<8)|MAXMEMORY_FLAG_ALLKEYS)
#define MAXMEMORY_NO_EVICTION (7<<8)
```

[redisObject](/docs/CS/DB/Redis/redisDb.md?id=redisObject) has `lru:LRU_BITS` and [update access time](/docs/CS/DB/Redis/redisDb.md?id=updateLFU)

```c
// server.h
typedef struct redisObject {
    unsigned lru:LRU_BITS; /* LRU time (relative to global lru_clock) or
                            * LFU data (least significant 8 bits frequency
                            * and most significant 16 bits access time). */
    // ...
} robj;
```



1000 ms

### performEvictions

Check that memory usage is within the current "maxmemory" limit.  If over "maxmemory", attempt to free memory by evicting data (if it's safe to do so).

It's possible for Redis to suddenly be significantly over the "maxmemory" setting.  This can happen if there is a large allocation (like a hash table resize) or even if the "maxmemory" setting is manually adjusted.  Because of this, it's important to evict for a managed period of time - otherwise Redis would become unresponsive while evicting.

The goal of this function is to improve the memory situation - not to immediately resolve it.  In the case that some items have been evicted but the "maxmemory" limit has not been achieved, an aeTimeProc will be started which will continue to evict items until memory limits are achieved or
nothing more is evictable.

This should be called before execution of commands.  If EVICT_FAIL is returned, commands which will result in increased memory usage should be rejected.

Returns:
- EVICT_OK       - memory is OK or it's not possible to perform evictions now
- EVICT_RUNNING  - memory is over the limit, but eviction is still processing
- EVICT_FAIL     - memory is over the limit, and there's nothing to evict

```c
int performEvictions(void) {
    if (!isSafeToPerformEvictions()) return EVICT_OK;

    int keys_freed = 0;
    size_t mem_reported, mem_tofree;
    long long mem_freed; /* May be negative */
    mstime_t latency, eviction_latency;
    long long delta;
    int slaves = listLength(server.slaves);
    int result = EVICT_FAIL;

    if (getMaxmemoryState(&mem_reported,NULL,&mem_tofree,NULL) == C_OK)
        return EVICT_OK;

    if (server.maxmemory_policy == MAXMEMORY_NO_EVICTION)
        return EVICT_FAIL;  /* We need to free memory, but policy forbids. */

    unsigned long eviction_time_limit_us = evictionTimeLimitUs();

    mem_freed = 0;

    latencyStartMonitor(latency);

    monotime evictionTimer;
    elapsedStart(&evictionTimer);

    while (mem_freed < (long long)mem_tofree) {
        int j, k, i;
        static unsigned int next_db = 0;
        sds bestkey = NULL;
        int bestdbid;
        redisDb *db;
        dict *dict;
        dictEntry *de;

        if (server.maxmemory_policy & (MAXMEMORY_FLAG_LRU|MAXMEMORY_FLAG_LFU) ||
            server.maxmemory_policy == MAXMEMORY_VOLATILE_TTL)
        {
            struct evictionPoolEntry *pool = EvictionPoolLRU;

            while(bestkey == NULL) {
                unsigned long total_keys = 0, keys;

                /* We don't want to make local-db choices when expiring keys,
                 * so to start populate the eviction pool sampling keys from
                 * every DB. */
                for (i = 0; i < server.dbnum; i++) {
                    db = server.db+i;
                    dict = (server.maxmemory_policy & MAXMEMORY_FLAG_ALLKEYS) ?
                            db->dict : db->expires;
                    if ((keys = dictSize(dict)) != 0) {
                        evictionPoolPopulate(i, dict, db->dict, pool);
                        total_keys += keys;
                    }
                }
                if (!total_keys) break; /* No keys to evict. */

                /* Go backward from best to worst element to evict. */
                for (k = EVPOOL_SIZE-1; k >= 0; k--) {
                    if (pool[k].key == NULL) continue;
                    bestdbid = pool[k].dbid;

                    if (server.maxmemory_policy & MAXMEMORY_FLAG_ALLKEYS) {
                        de = dictFind(server.db[pool[k].dbid].dict,
                            pool[k].key);
                    } else {
                        de = dictFind(server.db[pool[k].dbid].expires,
                            pool[k].key);
                    }

                    /* Remove the entry from the pool. */
                    if (pool[k].key != pool[k].cached)
                        sdsfree(pool[k].key);
                    pool[k].key = NULL;
                    pool[k].idle = 0;

                    /* If the key exists, is our pick. Otherwise it is
                     * a ghost and we need to try the next element. */
                    if (de) {
                        bestkey = dictGetKey(de);
                        break;
                    } else {
                        /* Ghost... Iterate again. */
                    }
                }
            }
        }

        /* volatile-random and allkeys-random policy */
        else if (server.maxmemory_policy == MAXMEMORY_ALLKEYS_RANDOM ||
                 server.maxmemory_policy == MAXMEMORY_VOLATILE_RANDOM)
        {
            /* When evicting a random key, we try to evict a key for
             * each DB, so we use the static 'next_db' variable to
             * incrementally visit all DBs. */
            for (i = 0; i < server.dbnum; i++) {
                j = (++next_db) % server.dbnum;
                db = server.db+j;
                dict = (server.maxmemory_policy == MAXMEMORY_ALLKEYS_RANDOM) ?
                        db->dict : db->expires;
                if (dictSize(dict) != 0) {
                    de = dictGetRandomKey(dict);
                    bestkey = dictGetKey(de);
                    bestdbid = j;
                    break;
                }
            }
        }

        /* Finally remove the selected key. */
        if (bestkey) {
            db = server.db+bestdbid;
            robj *keyobj = createStringObject(bestkey,sdslen(bestkey));
            propagateExpire(db,keyobj,server.lazyfree_lazy_eviction);
            /* We compute the amount of memory freed by db*Delete() alone.
             * It is possible that actually the memory needed to propagate
             * the DEL in AOF and replication link is greater than the one
             * we are freeing removing the key, but we can't account for
             * that otherwise we would never exit the loop.
             *
             * Same for CSC invalidation messages generated by signalModifiedKey.
             *
             * AOF and Output buffer memory will be freed eventually so
             * we only care about memory used by the key space. */
            delta = (long long) zmalloc_used_memory();
            latencyStartMonitor(eviction_latency);
            if (server.lazyfree_lazy_eviction)
                dbAsyncDelete(db,keyobj);
            else
                dbSyncDelete(db,keyobj);
            latencyEndMonitor(eviction_latency);
            latencyAddSampleIfNeeded("eviction-del",eviction_latency);
            delta -= (long long) zmalloc_used_memory();
            mem_freed += delta;
            server.stat_evictedkeys++;
            signalModifiedKey(NULL,db,keyobj);
            notifyKeyspaceEvent(NOTIFY_EVICTED, "evicted",
                keyobj, db->id);
            decrRefCount(keyobj);
            keys_freed++;

            if (keys_freed % 16 == 0) {
                /* When the memory to free starts to be big enough, we may
                 * start spending so much time here that is impossible to
                 * deliver data to the replicas fast enough, so we force the
                 * transmission here inside the loop. */
                if (slaves) flushSlavesOutputBuffers();

                /* Normally our stop condition is the ability to release
                 * a fixed, pre-computed amount of memory. However when we
                 * are deleting objects in another thread, it's better to
                 * check, from time to time, if we already reached our target
                 * memory, since the "mem_freed" amount is computed only
                 * across the dbAsyncDelete() call, while the thread can
                 * release the memory all the time. */
                if (server.lazyfree_lazy_eviction) {
                    if (getMaxmemoryState(NULL,NULL,NULL,NULL) == C_OK) {
                        break;
                    }
                }

                /* After some time, exit the loop early - even if memory limit
                 * hasn't been reached.  If we suddenly need to free a lot of
                 * memory, don't want to spend too much time here.  */
                if (elapsedUs(evictionTimer) > eviction_time_limit_us) {
                    // We still need to free memory - start eviction timer proc
                    if (!isEvictionProcRunning) {
                        isEvictionProcRunning = 1;
                        aeCreateTimeEvent(server.el, 0,
                                evictionTimeProc, NULL, NULL);
                    }
                    break;
                }
            }
        } else {
            goto cant_free; /* nothing to free... */
        }
    }
    /* at this point, the memory is OK, or we have reached the time limit */
    result = (isEvictionProcRunning) ? EVICT_RUNNING : EVICT_OK;

cant_free:
    if (result == EVICT_FAIL) {
        /* At this point, we have run out of evictable items.  It's possible
         * that some items are being freed in the lazyfree thread.  Perform a
         * short wait here if such jobs exist, but don't wait long.  */
        if (bioPendingJobsOfType(BIO_LAZY_FREE)) {
            usleep(eviction_time_limit_us);
            if (getMaxmemoryState(NULL,NULL,NULL,NULL) == C_OK) {
                result = EVICT_OK;
            }
        }
    }

    latencyEndMonitor(latency);
    latencyAddSampleIfNeeded("eviction-cycle",latency);
    return result;
}
```
### propagate
```c

/* Propagate the specified command (in the context of the specified database id)
 * to AOF and Slaves.
 *
 * flags are an xor between:
 * + PROPAGATE_NONE (no propagation of command at all)
 * + PROPAGATE_AOF (propagate into the AOF file if is enabled)
 * + PROPAGATE_REPL (propagate into the replication link)
 *
 * This should not be used inside commands implementation since it will not
 * wrap the resulting commands in MULTI/EXEC. Use instead alsoPropagate(),
 * preventCommandPropagation(), forceCommandPropagation().
 *
 * However for functions that need to (also) propagate out of the context of a
 * command execution, for example when serving a blocked client, you
 * want to use propagate().
 */
void propagate(struct redisCommand *cmd, int dbid, robj **argv, int argc,
               int flags)
{
    if (!server.replication_allowed)
        return;

    /* Propagate a MULTI request once we encounter the first command which
     * is a write command.
     * This way we'll deliver the MULTI/..../EXEC block as a whole and
     * both the AOF and the replication link will have the same consistency
     * and atomicity guarantees. */
    if (server.in_exec && !server.propagate_in_transaction)
        execCommandPropagateMulti(dbid);

    /* This needs to be unreachable since the dataset should be fixed during 
     * client pause, otherwise data may be lossed during a failover. */
    serverAssert(!(areClientsPaused() && !server.client_pause_in_transaction));

    if (server.aof_state != AOF_OFF && flags & PROPAGATE_AOF)
        feedAppendOnlyFile(cmd,dbid,argv,argc);
    if (flags & PROPAGATE_REPL)
        replicationFeedSlaves(server.slaves,dbid,argv,argc);
}
```


### LRU

```c
void initServerConfig(void) {
    // ...
    unsigned int lruclock = getLRUClock();
    atomicSet(server.lruclock,lruclock);
    // ...
}
```

```c

#define LRU_BITS 24
#define LRU_CLOCK_MAX ((1<<LRU_BITS)-1) /* Max value of obj->lru */
#define LRU_CLOCK_RESOLUTION 1000 /* LRU clock resolution in ms */
```

```
maxmemory-samples

```

```c
#define EVPOOL_SIZE 16
#define EVPOOL_CACHED_SDS_SIZE 255
struct evictionPoolEntry {
    unsigned long long idle;    /* Object idle time (inverse frequency for LFU) */
    sds key;                    /* Key name. */
    sds cached;                 /* Cached SDS object for key name. */
    int dbid;                   /* Key DB number. */
};
```

### LFU

LFU is approximated like LRU: it uses a probabilistic counter, called a [Morris counter](https://en.wikipedia.org/wiki/Approximate_counting_algorithm) in order to estimate the object access frequency using just a few bits per object, combined with a decay period so that the counter is reduced over time: at some point we no longer want to consider keys as frequently accessed, even if they were in the past, so that the algorithm can adapt to a shift in the access pattern.

Those informations are sampled similarly to what happens for LRU (as explained in the previous section of this documentation) in order to select a candidate for eviction.

However unlike LRU, LFU has certain tunable parameters: for instance, how fast should a frequent item lower in rank if it gets no longer accessed? It is also possible to tune the Morris counters range in order to better adapt the algorithm to specific use cases.

By default Redis 4.0 is configured to:

- Saturate the counter at, around, one million requests.
- Decay the counter every one minute.

Those should be reasonable values and were tested experimental, but the user may want to play with these configuration settings in order to pick optimal values.

Instructions about how to tune these parameters can be found inside the example `redis.conf` file in the source distribution, but briefly, they are:

```
lfu-log-factor 10
lfu-decay-time 1
```

The decay time is the obvious one, it is the amount of minutes a counter should be decayed, when sampled and found to be older than that value. A special value of `0` means: always decay the counter every time is scanned, and is rarely useful.

The counter *logarithm factor* changes how many hits are needed in order to saturate the frequency counter, which is just in the range 0-255. The higher the factor, the more accesses are needed in order to reach the maximum. The lower the factor, the better is the resolution of the counter for low accesses, according to the following table:

```
+--------+------------+------------+------------+------------+------------+
| factor | 100 hits   | 1000 hits  | 100K hits  | 1M hits    | 10M hits   |
+--------+------------+------------+------------+------------+------------+
| 0      | 104        | 255        | 255        | 255        | 255        |
+--------+------------+------------+------------+------------+------------+
| 1      | 18         | 49         | 255        | 255        | 255        |
+--------+------------+------------+------------+------------+------------+
| 10     | 10         | 18         | 142        | 255        | 255        |
+--------+------------+------------+------------+------------+------------+
| 100    | 8          | 11         | 49         | 143        | 255        |
+--------+------------+------------+------------+------------+------------+
```





prefer `allkeys-lru` or `volatile-lru`


## evict

To improve the quality of the LRU approximation we take a set of keys that are good candidate for eviction across performEvictions() calls.

Entries inside the eviction pool are taken ordered by idle time, putting greater idle times to the right (ascending order).

When an LFU policy is used instead, a reverse frequency indication is used instead of the idle time, so that we still evict by larger value (larger inverse frequency means to evict keys with the least frequent accesses). 

Empty entries have the key pointer set to NULL.
```c
#define EVPOOL_SIZE 16
#define EVPOOL_CACHED_SDS_SIZE 255
struct evictionPoolEntry {
    unsigned long long idle;    /* Object idle time (inverse frequency for LFU) */
    sds key;                    /* Key name. */
    sds cached;                 /* Cached SDS object for key name. */
    int dbid;                   /* Key DB number. */
};
```

`performEvictions` called by `processCommand()` which is defined inside `server.c` in order to actually execute the command

```c
int performEvictions(void)
```

`evictionPoolPopulate` called by `performEvictions`



### Memory Fragmentation
Fragmentation is a natural process that happens with every allocator (but less so with `Jemalloc`, fortunately) and certain workloads. Normally a server restart is needed in order to lower the fragmentation, or at least to flush away all the data and create it again. However thanks to this feature implemented by Oran Agra for Redis 4.0 this process can happen at runtime in a "hot" way, while the server is running.

```
INFO memory
used_memory_rss
used_memory

mem_fragmentation_ratio: x.xx
```

mem_fragmentation_ratio = used_memory_rss / used_memory

usually ratio < 1.5

#### active defragmentation

Active (online) defragmentation allows a Redis server to compact the spaces left between small allocations and deallocations of data in memory, thus allowing to reclaim back memory.

Basically when the fragmentation is over a certain level (see the configuration options below) Redis will start to create new copies of the values in contiguous memory regions by exploiting certain specific Jemalloc features (in order to understand if an allocation is causing fragmentation and to allocate it in a better place), and at the same time, will release the old copies of the data. This process, repeated incrementally for all the keys will cause the fragmentation to drop back to normal values.

Important things to understand:

1. This feature is disabled by default, and only works if you compiled Redis to use the copy of Jemalloc we ship with the source code of Redis. This is the default with Linux builds.

2. You never need to enable this feature if you don't have fragmentation issues.

3. Once you experience fragmentation, you can enable this feature when needed with the command "`CONFIG SET activedefrag yes`".

The configuration parameters are able to fine tune the behavior of the defragmentation process. If you are not sure about what they mean it is a good idea to leave the defaults untouched.

```
Enabled active defragmentation
activedefrag yes

Minimum amount of fragmentation waste to start active defrag
active-defrag-ignore-bytes 100mb

Minimum percentage of fragmentation to start active defrag
active-defrag-threshold-lower 10

Maximum percentage of fragmentation at which we use maximum effort
active-defrag-threshold-upper 100

Minimal effort for defrag in CPU percentage, to be used when the lower
threshold is reached
active-defrag-cycle-min 1

Maximal effort for defrag in CPU percentage, to be used when the upper
threshold is reached
active-defrag-cycle-max 25

Maximum number of set/hash/zset/list fields that will be processed from
the main dictionary scan
active-defrag-max-scan-fields 1000

Jemalloc background thread for purging will be enabled by default
jemalloc-bg-thread yes
```



## Optimization

Special encoding of small aggregate data types
Since Redis 2.2 many data types are optimized to use less space up to a certain size. Hashes, Lists, Sets composed of just integers, and Sorted Sets, when smaller than a given number of elements, and up to a maximum element size, are encoded in a very memory efficient way that uses up to 10 times less memory (with 5 time less memory used being the average saving).

This is completely transparent from the point of view of the user and API. Since this is a CPU / memory trade off it is possible to tune the maximum number of elements and maximum element size for special encoded types using the following redis.conf directives.
```
hash-max-ziplist-entries 512
hash-max-ziplist-value 64
zset-max-ziplist-entries 128
zset-max-ziplist-value 64
set-max-intset-entries 512
```

Bit and byte level operations
Redis 2.2 introduced new bit and byte level operations: GETRANGE, SETRANGE, GETBIT and SETBIT. Using these commands you can treat the Redis string type as a random access array. For instance if you have an application where users are identified by a unique progressive integer number, you can use a bitmap in order to save information about the subscription of users in a mailing list, setting the bit for subscribed and clearing it for unsubscribed, or the other way around. With 100 million users this data will take just 12 megabytes of RAM in a Redis instance. You can do the same using GETRANGE and SETRANGE in order to store one byte of information for each user. This is just an example but it is actually possible to model a number of problems in very little space with these new primitives.

Use hashes when possible
Small hashes are encoded in a very small space, so you should try representing your data using hashes whenever possible. For instance if you have objects representing users in a web application, instead of using different keys for name, surname, email, password, use a single hash with all the required fields.

**A few keys use a lot more memory than a single key containing a hash with a few fields**.
## References
1. [Memory Optimization](https://redis.io/topics/memory-optimization)
2. [Optimising session key storage in Redis](https://deliveroo.engineering/2016/10/07/optimising-session-key-storage.html)
3. [Partitioning: how to split data among multiple Redis instances.](https://redis.io/topics/partitioning)
4. [Why is Redis different compared to other key-value stores?](https://redis.io/topics/faq#what-is-the-maximum-number-of-keys-a-single-redis-instance-can-hold-and-what-the-max-number-of-elements-in-a-hash-list-set-sorted-set)
5. [Using Redis as an LRU cache](https://redis.io/topics/lru-cache)
6. [Storing hundreds of millions of simple key-value pairs in Redis](https://instagram-engineering.com/storing-hundreds-of-millions-of-simple-key-value-pairs-in-redis-1091ae80f74c)