## Introduction

[Redis](https://redis.io) is often referred to as a *data structures* server.
What this means is that Redis provides access to mutable data structures via a set of commands, which are sent using a *server-client* model with [TCP sockets](/docs/CS/CN/TCP/TCP.md) and a simple protocol.
So different processes can query and modify the same data structures in a shared way.

Data structures implemented into Redis have a few special properties:

- Redis cares to store them on disk, even if they are always served and modified into the server memory. This means that Redis is fast, but that it is also non-volatile.
- The implementation of data structures emphasizes memory efficiency, so data structures inside Redis will likely use less memory compared to the same data structure modelled using a high-level programming language.
- Redis offers a number of features that are natural to find in a database, like replication, tunable levels of durability, clustering, and high availability.

> Another good example is to think of Redis as a more complex version of memcached, where the operations are not just SETs and GETs, but operations that work with complex data types like Lists, Sets, ordered data structures, and so forth.

 

>  [!TIP]
>
> The Linux Foundation announced its intent to form [Valkey](/docs/CS/DB/Valkey.md), an open source alternative to the Redis in-memory, NoSQL data store. 



> It’s not very frequent that CPU becomes your bottleneck with Redis, as usually Redis is either memory or network bound. 
> For instance, using pipelining Redis running on an average Linux system can deliver even 1 million requests per second, so if your application mainly uses O(N) or O(log(N)) commands, it is hardly going to use too much CPU.


上下文切换
多线程同步

Source code layout


monotonic clock


By default, Redis will build using the POSIX clock_gettime function as the monotonic clock source. On most modern systems, the internal processor clock can be used to improve performance. Cautions can be found here: http://oliveryang.net/2015/09/pitfalls-of-TSC-usage/

To build with support for the processor’s internal instruction clock, use:

% make CFLAGS=“-DUSE_PROCESSOR_CLOCK”



> Link: [How fast is Redis?](https://redis.io/topics/benchmarks)

The simplest way to understand how a program works is to understand the [data structures](/docs/CS/DB/Redis/struct.md) it uses.

- [db](/docs/CS/DB/Redis/redisDb.md)

Redis has **built-in replication, Lua scripting, LRU eviction, [transactions](/docs/CS/DB/Redis/Transaction.md), and different levels of on-disk persistence,** and provides **high availability via Redis Sentinel** and **automatic partitioning with Redis Cluster**.

## Persistence

[Persistence](/docs/CS/DB/Redis/persist.md) refers to the writing of data to durable storage, such as a solid-state disk (SSD).
The most important thing to understand is the different trade-offs between the RDB and AOF persistence.

## [Lifecycle](/docs/CS/DB/Redis/Lifecycle.md)

Server and Client

## Event

[IO Event](/docs/CS/DB/Redis/ae.md)

Time_Event

ServerCron:

- evict key
- RDB and AOF
- master-slave sync
- cluster keepalive
- close dead connection
- statistic memory and other server info

## Log

### Slowlog

The Redis Slow Log is a system to log queries that exceeded a specified execution time. 
The execution time does not include the I/O operations like talking with the client, sending the reply and so forth, but just the time needed to actually execute the command
(this is the only stage of command execution where the thread is blocked and can not serve other requests in the meantime).

You can configure the slow log with two parameters: one tells Redis what is the execution time, in microseconds, to exceed in order for the command to get logged, and the other parameter is the length of the slow log.
When a new command is logged the oldest one is removed from the queue of logged commands.

slowlog len can set to 1000

```
The following time is expressed in microseconds, so 1000000 is equivalent
to one second. Note that a negative number disables the slow log, while
a value of zero forces the logging of every command.

slowlog-log-slower-than 10000

# There is no limit to this length. Just be aware that it will consume memory.
# You can reclaim memory used by the slow log with SLOWLOG RESET.
slowlog-max-len 128
```

slowlog get

slowlog len

extension:

latency monitor

```shell
# use it at slave
./redis-cli --bigkeys -i 0.1
```

## Cluster

单机Redis瓶颈
- QPS
- 容量
- 单点故障



### Master-Slave

主从复制
- Redis读大于写 类似MySQL 副本提供读



主从一致性



```
(error) READONLY You can't write against a read only replica.
```


disadvantage:

load balance and recovery





```log
# replica log
Connecting to MASTER 127.0.0.1:7000
MASTER <-> REPLICA sync started
Non blocking connect for SYNC fired the event.
Master replied to PING, replication can continue...
Partial resynchronization not possible (no cached master)
Full resync from master: 21a84515a95124a3326bd63d9ecf94e52e44c129:0
MASTER <-> REPLICA sync: receiving streamed RDB from master with EOF to disk
MASTER <-> REPLICA sync: Flushing old data
MASTER <-> REPLICA sync: Loading DB in memory
Loading RDB produced by version 7.2.5
RDB age 0 seconds
RDB memory usage when created 0.52 Mb
Done loading RDB, keys loaded: 0, keys expired: 0.
MASTER <-> REPLICA sync: Finished with success
```

```log
# master log
Replica 127.0.0.1:7001 asks for synchronization
Full resync requested by replica 127.0.0.1:7001
Replication backlog created, my new replication IDs are '21a84515a95124a3326bd63d9ecf94e52e44c129' and '0000000000000000000000000000000000000000'
Delay next BGSAVE for diskless SYNC
Starting BGSAVE for SYNC with target: replicas sockets
Background RDB transfer started by pid 16752
Fork CoW for RDB: current 4 MB, peak 4 MB, average 4 MB
Diskless rdb transfer, done reading from pipe, 1 replicas still up.
Background RDB transfer terminated with success
Streamed RDB transfer with replica 127.0.0.1:7001 succeeded (socket). Waiting for REPLCONF ACK from replica to enable streaming
Synchronization with replica 127.0.0.1:7001 succeeded
```



### Redis Sentinel

monitor

- choose new master from slaves when master down
- notify slaves to replicaof and notify clients to create connections with new master

### Redis Cluster
分片算法

range 连续数据 业务相关

hash


## [Distributed Lock](/docs/CS/DB/Redis/Lock.md)

## Performance

monitor

### Block

using wrong API or struct Slow get n : get n slow Sqls > 10ms

CPU overflow

Persistence:

- fork
- AOF flush to disk
- enable THP

CPU race

swap

- make sure have enough memory
- Prefer not use swap

Network

connection refused

timeout

network soft interrupt

## memory

Used_memor_rss

- Used_memory
- memory chip

## command

### info

- Server
- Clients
  - rejected_connections
- Memory
  - human  memory jemalloc apply
  - rss_human  memory in top command
  - peak_human
  - lua_human
- Persistence
- Stats
  - ops_per_sec
  - sync_partial_err
- Replication
  - backlog
- CPU
- Modules
- Errorstats
- Cluster
- Keyspace

monitor get request cmds of current time

maxmemory-policy

- noeviction default refuse write(exclude del) request
- volatile-lru
- volatile-ttl
- volatile-random
- alleys-lru
- alleys-random
- volatile-lfu
- allkeys-lfu

LRU

keys contain a 24bits of timestamp

random get keys and del the oldest one util the memory is enough

unlink use a async thread to del big value

flushdb and flushall can add params to be async

LFU

## TLS

## THP

Transparent Huge Pages（THP）
copy-on-write期间复制内存页从4KB变成2MB
fork子进程的速度变慢
高并发下开启容易造成内存溢出，建议关闭

## Tools

- redis-server
- redis-sentinel
- redis-cli
- redis-check-rdb
- redis-check-aof
- redis-benchmark


## 缓存一致性

广播更新

应用监听Redis的更改


定时更新




## Tuning

BigKey

对于JIT技术在存储引擎中而言，“EVAL is evil”，尽量避免使用lua耗费内存和计算资源


Pubsub的典型场景
Pubsub适合悲观锁和简单信号，不适合稳定的更新，因为可能会丢消息。在1对N的消息转发通道中，服务瓶颈。还有模
糊通知方面，算力瓶颈。在channel和client比较多的情况下，造成CPU打满、服务夯住。

Transaction
Transaction是一种伪事物，没有回滚条件；集群版需要所有key使用hashtag保证，代码比较复杂，hashtag也可能导
致算力和存储倾斜；Lua中封装了multi-exec，但更耗费CPU，比如编译、加载时，经常出现问题。


Pipeline
Pipeline用的比较多，如下面的示意图，实际上是把多个请求封装在一个请求中，合并在一个请求里发送，服务端一次
性返回，能够有效减少IO，提高执行效率。需要注意的是，用户需要聚合小的命令，避免在pipeline里做大range。注意
Pipeline中的批量任务不是原子执行的（从来不是），所以要处理Pipeline其中部分命令失败的场景。

危险命令禁用

### slowlog

```properties
# 10ms
slowlog-log-slower-than=10000
# 128
slowlog-max-len=128
```
慢查询日志删除使用FIFO

```c
void slowlogPushEntryIfNeeded(client *c, robj **argv, int argc, long long duration) {
    if (server.slowlog_log_slower_than < 0 || server.slowlog_max_len == 0) return; /* Slowlog disabled */
    if (duration >= server.slowlog_log_slower_than)
        listAddNodeHead(server.slowlog,
                        slowlogCreateEntry(c,argv,argc,duration));

    /* Remove old entries if needed. */
    while (listLength(server.slowlog) > server.slowlog_max_len)
        listDelNode(server.slowlog,listLast(server.slowlog));
}
```

slowlog get


## Links

- [DataBases](/docs/CS/DB/DB.md?id=Redis)

## References

1. [Redis 面试全攻略、面试题大集合](https://mp.weixin.qq.com/s/6NobACeeKCcUy98Ikanryg)
2. [Redis源码分析(一) - 硬核课堂](https://hardcore.feishu.cn/docs/doccnp9v7IljXiJ5FpNT1ipLhlR#)
3. [Distributed locks with Redis](https://redis.io/topics/distlock)
4. [Garnet](https://github.com/microsoft/garnet)
