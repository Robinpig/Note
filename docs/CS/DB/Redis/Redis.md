## Introduction

[Redis](https://redis.io) is an open source (BSD licensed), in-memory data structure store, used as a database, cache, and message broker. 

Redis provides data structures such as **strings, hashes, lists, sets, sorted sets** with **range queries, bitmaps, hyperloglogs, geospatial indexes, and streams**. 

Redis has **built-in replication, Lua scripting, LRU eviction, transactions, and different levels of on-disk persistence,** and provides **high availability via Redis Sentinel** and **automatic partitioning with Redis Cluster**.



## [How fast is Redis?](https://redis.io/topics/benchmarks)

24bits

- 8bits logistic counter log
- 16bits last decrement time minutes


- [db](/docs/CS/DB/Redis/redisDb.md)
- [IO](/docs/CS/DB/Redis/ae.md)

BigKey



## Install

- Docker

- make source
- apt-get(Ubuntu) yum(RedHat) brew(Mac)

## sys

struct redisServer and struct client in server.h

struct redisCommand redisCommandTable[] in server.c



## [Struct](/docs/CS/DB/Redis/struct.md)
## [Persistence](/docs/CS/DB/Redis/persist.md)
## [Lifecycle](/docs/CS/DB/Redis/Lifecycle.md)

### Event
ServerCron:
- evict key
- RDB and AOF
- master-slave sync
- cluster keepalive
- close dead connection
- statistic memory and other server info

Time_Event


### Slowlog

The Redis Slow Log is a system to log queries that exceeded a specified execution time. The execution time does not include the I/O operations like talking with the client, sending the reply and so forth, but just the time needed to actually execute the command (this is the only stage of command execution where the thread is blocked and can not serve other requests in the meantime).

You can configure the slow log with two parameters: one tells Redis what is the execution time, in microseconds, to exceed in order for the command to get logged, and the other parameter is the length of the slow log. When a new command is logged the oldest one is removed from the queue of logged commands.


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

### Singleton 

### Master-Slave

disadvantage:

load balance and recovery

### Redis Sentinel
monitor

- choose new master from slaves when master down
- notify slaves to replicaof and notify clients to create connections with new master

### Redis Cluster

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


## References
1. [Redis 面试全攻略、面试题大集合](https://mp.weixin.qq.com/s/6NobACeeKCcUy98Ikanryg)
2. [Redis源码分析(一) - 硬核课堂](https://hardcore.feishu.cn/docs/doccnp9v7IljXiJ5FpNT1ipLhlR#)
3. [Distributed locks with Redis](https://redis.io/topics/distlock)