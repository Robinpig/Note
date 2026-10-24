## Introduction

Memcached 是多线程架构，但它的多线程不是「每个连接一个线程」，也不是「全局大锁单线程 event loop」，而是一个介于两者之间的混合模型：**一个主线程负责 accept，N 个 worker 线程各自跑独立的 libevent loop 处理连接，若干后台线程维护缓存的健康度**。线程之间不共享连接，只共享哈希表和 slab 分配器的少量数据结构，锁粒度细化到每个 slabclass 内部的子 LRU。

## Thread Roles

Memcached 的线程按职责可以分成三类：

### Main Thread

主线程只做一件事——accept 新连接。它自己不处理任何客户端命令。accept 到的新 socket 通过一个**自管道（self-pipe）** 通知某个 worker 线程（round-robin 或最少连接策略），worker 收到通知后把新 socket 注册进自己的 libevent loop。

自管道是主线程与 worker 线程之间唯一的同步机制：主线程对每个新连接往管道写一个字节，worker 的 libevent loop 中有一个监听管道读端的事件，被唤醒后去主线程维护的共享队列里取出新 fd。

### Worker Threads

`-t N` 参数指定 worker 线程数（默认 4）。每个 worker 线程：

- 拥有自己独立的 libevent event base，互不干扰。
- 管理自己的客户端连接集合，协议解析、命令执行、响应发送全部在本线程内完成。
- 当需要操作共享数据结构时加细粒度锁：哈希表的分桶锁、slabclass 的 LRU 子队列锁、全局 stats 锁等。

这使得 Memcached 能在高并发下同时跑满多个 CPU 核心，而不会像「全局单线程大锁」那样成为瓶颈。实测在 48 核机器上，纯读场景可以线性扩展。

### Background Threads

后台线程不处理任何客户端请求，只维护缓存的健康度：

| 线程 | 职责 |
| :-- | :-- |
| **LRU Maintainer** | 遍历每个 slabclass 的四段 LRU（HOT/WARM/COLD/TEMP），维护各段的大小限制和尾部年龄限制，执行 item 在各段之间的迁移；异步处理来自 COLD 的 bump 请求 |
| **LRU Crawler** | 异步沿 LRU 爬行，主动回收过期 item，周期性扫描以直方图形式统计 TTL 剩余分布，据此决定下次扫描的频率 |
| **Slab Automover**（1.6.6+ 默认开启） | 监控各 slabclass 的 chunk 使用率，当某个 slabclass 频繁发生 eviction 而另一个 slabclass 有大量空闲 chunk 时，把空闲 slab 从后者移到前者 |
| **Stats Maintainer** | 定期聚合线程级 stats 到全局 stats，供 `stats` 命令读取 |
| **Watchdog** | 检测 worker 线程是否卡死或陷入长时间阻塞（例如直接回收模式下 worker 阻塞在 LRU 上），触发后打日志并可配置是否自动终止 |

## Event Loop

每个 worker 线程内部运行一个 libevent 驱动的事件循环，Linux 下默认使用 epoll。事件循环处理的事件类型包括：

1. **客户端 socket 的可读事件**：收到请求数据包后触发协议解析。
2. **客户端 socket 的可写事件**：响应发送完毕后清理。
3. **自管道的可读事件**：主线程发来新连接通知。
4. **定时事件**：连接超时处理、stats 聚合周期等。

libevent 自身已经封装了 epoll/kevent/poll 的平台差异，worker 线程只需要对自己关心的 fd 注册 `event_set` 回调即可。这层抽象也是 Memcached 能在 Linux、macOS、FreeBSD 上无差异运行的原因。

## Locking Granularity

Memcached 在锁粒度上做了大量工作，这是它能扩展到多核的根基：

- **哈希表**：每个 bucket 有自己的 mutex（`item_lock` 数组），不是全局一把锁。扩容期间主表和旧表各有各的锁。
- **LRU**：每个 slabclass 的四段子 LRU（HOT/WARM/COLD/TEMP）各有自己的 mutex（`lru_locks` 数组）。
- **Slab class**：每级 slabclass 独立维护 freelist 和已分配 slab 列表。
- **Stats**：全局 stats 使用原子操作或细粒度锁，避免在热路径上争用。

唯一的全局锁是 LRU Maintainer 在调度迁移时会短暂持有，以及连接队列在主线程和 worker 之间传递时需要互斥保护。

## Links

- [Memcached](/docs/CS/DB/Memcached.md)
- [Hash Table](/docs/CS/DB/Memcached/Hash_Table.md)
- [Memory Allocation](/docs/CS/DB/Memcached/Memory_Allocation.md)
- [Eviction](/docs/CS/DB/Memcached/Eviction.md)

## References

1. [Memcached GitHub — thread.c](https://github.com/memcached/memcached/blob/master/thread.c) — 线程模型核心源码
2. [libevent](https://libevent.org/) — Memcached 依赖的事件驱动库
