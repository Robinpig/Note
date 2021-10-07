## Introduction

[Redis](https://redis.io) is an open source (BSD licensed), in-memory data structure store, used as a database, cache, and message broker. 

Redis provides data structures such as **strings, hashes, lists, sets, sorted sets** with **range queries, bitmaps, hyperloglogs, geospatial indexes, and streams**. 

Redis has **built-in replication, Lua scripting, LRU eviction, transactions, and different levels of on-disk persistence,** and provides **high availability via Redis Sentinel** and **automatic partitioning with Redis Cluster**.

- [How fast is Redis?](https://redis.io/topics/benchmarks)
- [start](/docs/CS/DB/Redis/start.md?id=main)
- [exec](/docs/CS/DB/Redis/start.md?id=do)
- [db](/docs/CS/DB/Redis/redisDb.md)
- [Struct](/docs/CS/DB/Redis/struct.md)
- [IO](/docs/CS/DB/Redis/ae.md)

## Install

- Docker

- make source
- apt-get(Ubuntu) yum(RedHat) brew(Mac)

## sys

struct redisServer and struct client in server.h

struct redisCommand redisCommandTable[] in server.c



## Struct




## Pipeline

使用管道将多个命令放入同一个执行队列中，减少往返时延消耗。

Event
Redis的文件事件和时间事件

Redis作为单线程服务要处理的工作一点也不少，Redis是事件驱动的服务器，主要的事件类型就是：文件事件类型和时间事件类型，其中时间事件是理解单线程逻辑模型的关键。

时间事件
Redis的时间事件分为两类：
定时事件：任务在等待指定大小的等待时间之后就执行，执行完成就不再执行，只触发一次；
周期事件：任务每隔一定时间就执行，执行完成之后等待下一次执行，会周期性的触发；

周期性时间事件
Redis中大部分是周期事件，周期事件主要是服务器定期对自身运行情况进行检测和调整，从而保证稳定性，这项工作主要是ServerCron函数来完成的，周期事件的内容主要包括：
删除数据库的key
触发RDB和AOF持久化
主从同步
集群化保活
关闭清理死客户端链接
统计更新服务器的内存、key数量等信息
可见 Redis的周期性事件虽然主要处理辅助任务，但是对整个服务的稳定运行，起到至关重要的作用。

时间事件的无序链表
Redis的每个时间事件分为三个部分：
事件ID 全局唯一 依次递增
触发时间戳 ms级精度
事件处理函数 事件回调函数
时间事件Time_Event结构：


## Lua

EVAL





## Persistence

### RDB
save
bgsave
snapshot，
SAVE使用主线程同步转储，BGSAVE create child process by calling fork() of glib.
文件名默认为dump.rdb。但数据一致性不高，但转储恢复速度更快，占用存储空间更少。


### AOF

like binlog in MySQL

flushAppendOnlyFile

写入操作的日志，fsync()将写缓冲区中内容刷新到磁盘，写入AOF文件。

AOF重写可压缩AOF文件，对键过期时间有变动的数据按情况处理。

## Cluster

### 单机 

持久化技术  可用性不强

### 主从复制

备份数据，减轻读压力；缺陷是故障恢复无法自动化 写操作无法负载均衡 

### Redis Sentinel
monitor
choose new master from slaves when master down
notify slaves to replicaof and notify clients to create connections with new master

故障恢复自动化，故障恢复时服务不可用

### Redis Cluster

## 缓存

缓存能极大减小数据库压力，读走缓存，写不走缓存。

### 缓存分类

#### CDN 缓存

**CDN**(Content Delivery Network 内容分发网络)的基本原理是广泛采用各种缓存服务器，将这些缓存服务器分布到用户访问相对集中的地区或网络中。

在用户访问网站时，利用全局负载技术将用户的访问指向距离最近的工作正常的缓存服务器上，由缓存服务器直接响应用户请求。

**应用场景**：主要用于缓存静态资源，例如图片，视频。

#### 反向代理缓存

 

反向代理位于应用服务器机房，处理所有对 Web 服务器的请求。

如果用户请求的页面在代理服务器上有缓冲的话，代理服务器直接将缓冲内容发送给用户。

如果没有缓冲则先向 Web 服务器发出请求，取回数据，本地缓存后再发送给用户。通过降低向 Web 服务器的请求数，从而降低了 Web 服务器的负载。

**应用场景**:一般只缓存体积较小静态文件资源，如 css、js、图片。

 

#### 本地缓存

Encache,Guava

客户端：浏览器缓存 页面缓存

#### 分布式缓存

Redis Memcached

### 缓存失效策略

一般而言，缓存系统中都会对缓存的对象设置一个超时时间，避免浪费相对比较稀缺的缓存资源。对于缓存时间的处理有两种，分别是主动失效和被动失效。

#### 主动失效

主动失效是指系统有一个主动检查缓存是否失效的机制，比如通过定时任务或者单独的线程不断的去检查缓存队列中的对象是否失效，如果失效就把他们清除掉，避免浪费。主动失效的好处是能够避免内存的浪费，但是会占用额外的CPU时间。

#### 被动失效

被动失效是通过访问缓存对象的时候才去检查缓存对象是否失效，这样的好处是系统占用的CPU时间更少，但是风险是长期不被访问的缓存对象不会被系统清除。

### expire strategy

缓存淘汰，又称为缓存逐出(cache replacement algorithms或者cache replacement policies)，是指在存储空间不足的情况下，缓存系统主动释放一些缓存对象获取更多的存储空间。

对于大部分内存型的分布式缓存（非持久化），淘汰策略优先于失效策略，一旦空间不足，缓存对象即使没有过期也会被释放。这里只是简单介绍一下，相关的资料都很多，一般LRU用的比较多，可以重点了解一下。

#### Random


#### FIFO

先进先出（First In First Out）是一种简单的淘汰策略，缓存对象以队列的形式存在，如果空间不足，就释放队列头部的（先缓存）对象。一般用链表实现。

#### LRU

最近最久未使用（Least Recently Used），这种策略是根据访问的时间先后来进行淘汰的，如果空间不足，会释放最久没有访问的对象（上次访问时间最早的对象）。比较常见的是通过优先队列来实现。

#### LFU

最近最少使用（Least Frequently Used），这种策略根据最近访问的频率来进行淘汰，如果空间不足，会释放最近访问频率最低的对象。这个算法也是用优先队列实现的比较常见。

#### no-eviction

### 分布式缓存的常见问题

#### 数据一致性问题

缓存数据和数据库数据不一致，

#### 缓存穿透

DB中不存在数据，每次都穿过缓存查DB，造成DB的压力。一般是对Key-Value进行网络攻击。

**解决方案**：

- 对结果为空的数据也进行缓存，当此 Key 有数据后，清理缓存。
- 一定不存在的 Key，采用布隆过滤器，建立一个大的 Bitmap 中，查询时通过该 Bitmap 过滤。

#### 缓存击穿

- 在缓存失效的瞬间大量请求，造成DB的压力瞬间增大
- 解决方案：更新缓存时使用分布式锁锁住服务，防止请求穿透直达DB

#### 缓存雪崩

- 大量缓存设置了相同的失效时间，同一时间失效，造成服务瞬间性能急剧下降
- 解决方案：缓存时间使用基本时间加上随机时间

## Distributed Lock


[Distributed locks with Redis](https://redis.io/topics/distlock)

### Safety and Liveness guarantees
We are going to model our design with just three properties that, from our point of view, are the minimum guarantees needed to use distributed locks in an effective way.

- Safety property: Mutual exclusion. At any given moment, only one client can hold a lock.
- Liveness property A: Deadlock free. Eventually it is always possible to acquire a lock, even if the client that locked a resource crashes or gets partitioned.
- Liveness property B: Fault tolerance. As long as the majority of Redis nodes are up, clients are able to acquire and release locks.

### Correct implementation with a single instance

Before trying to overcome the limitation of the single instance setup described above, let’s check how to do it correctly in this simple case, since this is actually a viable solution in applications where a race condition from time to time is acceptable, and because locking into a single instance is the foundation we’ll use for the distributed algorithm described here.

To acquire the lock, the way to go is the following:

```
    SET resource_name my_random_value NX PX 30000
```

The command will set the key only if it does not already exist (NX option), with an expire of 30000 milliseconds (PX option). The key is set to a value “my_random_value”. This value must be unique across all clients and all lock requests.

Basically the random value is used in order to release the lock in a safe way, with a script that tells Redis: remove the key only if it exists and the value stored at the key is exactly the one I expect to be. This is accomplished by the following Lua script:

```
if redis.call("get",KEYS[1]) == ARGV[1] then
    return redis.call("del",KEYS[1])
else
    return 0
end
```

This is important in order to avoid removing a lock that was created by another client. For example a client may acquire the lock, get blocked in some operation for longer than the lock validity time (the time at which the key will expire), and later remove the lock, that was already acquired by some other client. Using just DEL is not safe as a client may remove the lock of another client. With the above script instead every lock is “signed” with a random string, so the lock will be removed only if it is still the one that was set by the client trying to remove it.

What should this random string be? I assume it’s 20 bytes from /dev/urandom, but you can find cheaper ways to make it unique enough for your tasks. For example a safe pick is to seed RC4 with /dev/urandom, and generate a pseudo random stream from that. A simpler solution is to use a combination of unix time with microseconds resolution, concatenating it with a client ID, it is not as safe, but probably up to the task in most environments.

The time we use as the key time to live, is called the “lock validity time”. It is both the auto release time, and the time the client has in order to perform the operation required before another client may be able to acquire the lock again, without technically violating the mutual exclusion guarantee, which is only limited to a given window of time from the moment the lock is acquired.

So now we have a good way to acquire and release the lock. The system, reasoning about a non-distributed system composed of a single, always available, instance, is safe. Let’s extend the concept to a distributed system where we don’t have such guarantees.



### The Redlock algorithm

In the distributed version of the algorithm we assume we have N Redis masters. Those nodes are totally independent, so we don’t use replication or any other implicit coordination system. We already described how to acquire and release the lock safely in a single instance. We take for granted that the algorithm will use this method to acquire and release the lock in a single instance. In our examples we set N=5, which is a reasonable value, so we need to run 5 Redis masters on different computers or virtual machines in order to ensure that they’ll fail in a mostly independent way.

In order to acquire the lock, the client performs the following operations:

1. It gets the current time in milliseconds.
2. It tries to acquire the lock in all the N instances sequentially, using the same key name and random value in all the instances. During step 2, when setting the lock in each instance, the client uses a timeout which is small compared to the total lock auto-release time in order to acquire it. For example if the auto-release time is 10 seconds, the timeout could be in the ~ 5-50 milliseconds range. This prevents the client from remaining blocked for a long time trying to talk with a Redis node which is down: if an instance is not available, we should try to talk with the next instance ASAP.
3. The client computes how much time elapsed in order to acquire the lock, by subtracting from the current time the timestamp obtained in step 1. If and only if the client was able to acquire the lock in the majority of the instances (at least 3), and the total time elapsed to acquire the lock is less than lock validity time, the lock is considered to be acquired.
4. If the lock was acquired, its validity time is considered to be the initial validity time minus the time elapsed, as computed in step 3.
5. If the client failed to acquire the lock for some reason (either it was not able to lock N/2+1 instances or the validity time is negative), it will try to unlock all the instances (even the instances it believed it was not able to lock).



### Is the algorithm asynchronous?

The algorithm relies on the assumption that while there is no synchronized clock across the processes, still the local time in every process flows approximately at the same rate, with an error which is small compared to the auto-release time of the lock. This assumption closely resembles a real-world computer: every computer has a local clock and we can usually rely on different computers to have a clock drift which is small.

At this point we need to better specify our mutual exclusion rule: it is guaranteed only as long as the client holding the lock will terminate its work within the lock validity time (as obtained in step 3), minus some time (just a few milliseconds in order to compensate for clock drift between processes).

For more information about similar systems requiring a bound *clock drift*, this paper is an interesting reference: [Leases: an efficient fault-tolerant mechanism for distributed file cache consistency](http://dl.acm.org/citation.cfm?id=74870).



### Retry on failure

When a client is unable to acquire the lock, it should try again after a random delay in order to try to desynchronize multiple clients trying to acquire the lock for the same resource at the same time (this may result in a split brain condition where nobody wins). Also the faster a client tries to acquire the lock in the majority of Redis instances, the smaller the window for a split brain condition (and the need for a retry), so ideally the client should try to send the SET commands to the N instances at the same time using multiplexing.

It is worth stressing how important it is for clients that fail to acquire the majority of locks, to release the (partially) acquired locks ASAP, so that there is no need to wait for key expiry in order for the lock to be acquired again (however if a network partition happens and the client is no longer able to communicate with the Redis instances, there is an availability penalty to pay as it waits for key expiration).



### Releasing the lock

Releasing the lock is simple and involves just releasing the lock in all instances, whether or not the client believes it was able to successfully lock a given instance.



### Safety arguments

Is the algorithm safe? We can try to understand what happens in different scenarios.

To start let’s assume that a client is able to acquire the lock in the majority of instances. All the instances will contain a key with the same time to live. However, the key was set at different times, so the keys will also expire at different times. But if the first key was set at worst at time T1 (the time we sample before contacting the first server) and the last key was set at worst at time T2 (the time we obtained the reply from the last server), we are sure that the first key to expire in the set will exist for at least `MIN_VALIDITY=TTL-(T2-T1)-CLOCK_DRIFT`. All the other keys will expire later, so we are sure that the keys will be simultaneously set for at least this time.

During the time that the majority of keys are set, another client will not be able to acquire the lock, since N/2+1 SET NX operations can’t succeed if N/2+1 keys already exist. So if a lock was acquired, it is not possible to re-acquire it at the same time (violating the mutual exclusion property).

However we want to also make sure that multiple clients trying to acquire the lock at the same time can’t simultaneously succeed.

If a client locked the majority of instances using a time near, or greater, than the lock maximum validity time (the TTL we use for SET basically), it will consider the lock invalid and will unlock the instances, so we only need to consider the case where a client was able to lock the majority of instances in a time which is less than the validity time. In this case for the argument already expressed above, for `MIN_VALIDITY` no client should be able to re-acquire the lock. So multiple clients will be able to lock N/2+1 instances at the same time (with "time" being the end of Step 2) only when the time to lock the majority was greater than the TTL time, making the lock invalid.

Are you able to provide a formal proof of safety, point to existing algorithms that are similar, or find a bug? That would be greatly appreciated.



### Liveness arguments

The system liveness is based on three main features:

1. The auto release of the lock (since keys expire): eventually keys are available again to be locked.
2. The fact that clients, usually, will cooperate removing the locks when the lock was not acquired, or when the lock was acquired and the work terminated, making it likely that we don’t have to wait for keys to expire to re-acquire the lock.
3. The fact that when a client needs to retry a lock, it waits a time which is comparably greater than the time needed to acquire the majority of locks, in order to probabilistically make split brain conditions during resource contention unlikely.

However, we pay an availability penalty equal to [TTL](https://redis.io/commands/ttl) time on network partitions, so if there are continuous partitions, we can pay this penalty indefinitely. This happens every time a client acquires a lock and gets partitioned away before being able to remove the lock.

Basically if there are infinite continuous network partitions, the system may become not available for an infinite amount of time.



### Performance, crash-recovery and fsync

Many users using Redis as a lock server need high performance in terms of both latency to acquire and release a lock, and number of acquire / release operations that it is possible to perform per second. In order to meet this requirement, the strategy to talk with the N Redis servers to reduce latency is definitely multiplexing (or poor man's multiplexing, which is, putting the socket in non-blocking mode, send all the commands, and read all the commands later, assuming that the RTT between the client and each instance is similar).

However there is another consideration to do about persistence if we want to target a crash-recovery system model.

Basically to see the problem here, let’s assume we configure Redis without persistence at all. A client acquires the lock in 3 of 5 instances. One of the instances where the client was able to acquire the lock is restarted, at this point there are again 3 instances that we can lock for the same resource, and another client can lock it again, violating the safety property of exclusivity of lock.

If we enable AOF persistence, things will improve quite a bit. For example we can upgrade a server by sending SHUTDOWN and restarting it. Because Redis expires are semantically implemented so that virtually the time still elapses when the server is off, all our requirements are fine. However everything is fine as long as it is a clean shutdown. What about a power outage? If Redis is configured, as by default, to fsync on disk every second, it is possible that after a restart our key is missing. In theory, if we want to guarantee the lock safety in the face of any kind of instance restart, we need to enable fsync=always in the persistence setting. This in turn will totally ruin performances to the same level of CP systems that are traditionally used to implement distributed locks in a safe way.

However things are better than what they look like at a first glance. Basically the algorithm safety is retained as long as when an instance restarts after a crash, it no longer participates to any **currently active** lock, so that the set of currently active locks when the instance restarts, were all obtained by locking instances other than the one which is rejoining the system.

To guarantee this we just need to make an instance, after a crash, unavailable for at least a bit more than the max [TTL](https://redis.io/commands/ttl) we use, which is, the time needed for all the keys about the locks that existed when the instance crashed, to become invalid and be automatically released.

Using *delayed restarts* it is basically possible to achieve safety even without any kind of Redis persistence available, however note that this may translate into an availability penalty. For example if a majority of instances crash, the system will become globally unavailable for [TTL](https://redis.io/commands/ttl) (here globally means that no resource at all will be lockable during this time).



### Making the algorithm more reliable: Extending the lock

If the work performed by clients is composed of small steps, it is possible to use smaller lock validity times by default, and extend the algorithm implementing a lock extension mechanism. Basically the client, if in the middle of the computation while the lock validity is approaching a low value, may extend the lock by sending a Lua script to all the instances that extends the TTL of the key if the key exists and its value is still the random value the client assigned when the lock was acquired.

The client should only consider the lock re-acquired if it was able to extend the lock into the majority of instances, and within the validity time (basically the algorithm to use is very similar to the one used when acquiring the lock).

However this does not technically change the algorithm, so the maximum number of lock reacquisition attempts should be limited, otherwise one of the liveness properties is violated.

### Analysis of Redlock

Martin Kleppmann [analyzed Redlock here](http://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html). The analysis and  [reply here](http://antirez.com/news/101).

[Note on fencing and distributed locks](https://fpj.systems/2016/02/10/note-on-fencing-and-distributed-locks/)

[TIL: clock skew exists](http://jvns.ca/blog/2016/02/09/til-clock-skew-exists/)

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

## References
1. [Redis 面试全攻略、面试题大集合](https://mp.weixin.qq.com/s/6NobACeeKCcUy98Ikanryg)
2. [Redis源码分析(一) - 硬核课堂](https://hardcore.feishu.cn/docs/doccnp9v7IljXiJ5FpNT1ipLhlR#)
3. [Distributed locks with Redis](https://redis.io/topics/distlock)