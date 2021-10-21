## Introduction

[Redis](https://redis.io) is an open source (BSD licensed), in-memory data structure store, used as a database, cache, and message broker. 

Redis provides data structures such as **strings, hashes, lists, sets, sorted sets** with **range queries, bitmaps, hyperloglogs, geospatial indexes, and streams**. 

Redis has **built-in replication, Lua scripting, LRU eviction, transactions, and different levels of on-disk persistence,** and provides **high availability via Redis Sentinel** and **automatic partitioning with Redis Cluster**.

- [How fast is Redis?](https://redis.io/topics/benchmarks)
- [db](/docs/CS/DB/Redis/redisDb.md)
- [IO](/docs/CS/DB/Redis/ae.md)

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



## Transaction

support isolation and consistency, and support durability when use AOF and appendfsync is always

**A command will still run when prior command run failed.**

**can not rollback transaction**

WATCH set sign of key
MULTI start transaction


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



### How fast is Redis?



24bits

- 8bits logistic counter log
- 16bits last decrement time minutes

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