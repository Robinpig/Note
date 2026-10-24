## Version Baseline

> [!IMPORTANT]
> 本页及 `Memcached/` 子树的所有默认值、命令可用性均以 **Memcached 1.6.45（2026-07-09）** 为基线。
> 读到与下表冲突的旧口径表述时，一律以本基线为准。

**当前版本**：1.6.45，发布于 2026-07-09（`git` tag `1.6.45`）。

**支持状态**（来源：官方仓库 memcached/memcached 的 `SECURITY.md`）：

Memcached 没有 Redis 那样的官方支持矩阵或年限承诺，**唯一稳定信号是 1.6.x 作为当前主线**。1.5.0（2017-02）引入 modern LRU 并默认启用；1.6.0（2020-03）引入内建 Lua Proxy，是架构分水岭。

**许可证**：BSD-3-Clause，从始至终未变。

**1.6.x 关键能力节点**（用于判断某特性是否可用）：

| 版本 | 日期 | 关键变化 |
| :-- | :-- | :-- |
| 1.5.0 | 2017-02 | modern LRU 默认启用（Segmented LRU + LRU Maintainer + LRU Crawler） |
| 1.6.0 | 2020-03 | **内建 Lua Proxy**（`mcp_config` 系列）；Meta Text Protocol（`mc.mget` / `mc.set`） |
| 1.6.6 | 2021-03 | Slab Automover 默认开启（`slab_automover`） |
| 1.6.23 | 2024-05 | 多队列哈希表（`-o hashtable` 可选） |
| **1.6.45** | 2026-07 | 当前最新 GA；安全修复（CVE-2026-90698 已于 1.6.44 修复） |

---

## Introduction

[Memcached](https://memcached.org/) 是纯内存键值缓存系统，诞生于 2003 年 Brad Fitzpatrick 为 LiveJournal 解决数据库压力的需求。它的设计哲学极度收敛：**只做 KV 缓存、不做持久化、不做数据结构、不做服务端分片**——所有复杂度都压进客户端和上层应用。

Memcached 的典型场景是「加速」而非「存储」：当数据库查询、API 调用或页面渲染结果可在一定时间窗口内复用时，把它们以小数据块（字符串或对象序列化后的二进制）的形式放进 Memcached，后续请求直接命中内存返回，从而减轻后端数据库的负载。

核心特性归纳为五点：

- **单节点百万级 QPS**：主线程 accept + 多 worker 线程各自跑独立 event loop，共享哈希表和 slab 分配器，锁粒度细化到 slabclass 内部的子 LRU 和哈希表的分桶锁。
- **协议极简**：文本协议仅约 12 条命令（`get` / `set` / `add` / `replace` / `append` / `prepend` / `cas` / `touch` / `gat` / `incr` / `decr` / `delete` / `flush_all` / `stats`），二进制协议字段化适配高并发，Meta 协议（1.6.0+）提供 `E` 标志位做服务端版本戳对比。
- **Opaque Value**：对 value 不做任何语义解析，客户端负责序列化；这是性能的根基——服务端零解析负担，但也意味着没有 `HGET` / `ZRANGE` 这种结构查询能力。
- **Slab 内存分配**：启动时预分配，运行时按需增 slab，避免 malloc/free 碎片；chunk 按增长因子逐级放大，最接近拟合每个 item 的实际大小。
- **客户端分布式**：服务节点之间零通信，客户端自己决定 key 路由到哪台 Memcached 实例。

---

## Knowledge Map

Memcached 的代码结构可以沿着「请求进来 → 找到 item → 分配内存 → 维护内存」这一条数据路径拆开。以下各子文件按因果递进组织：

### Architecture：从 socket 到线程

请求首先由主线程 accept，然后通过自管道（self-pipe）唤醒某个 worker 线程的 libevent loop，后续协议解析、命令执行、响应发送全部在该 worker 内完成。后台线程（LRU Maintainer、LRU Crawler、Slab Automover、Stats Maintainer）不处理任何客户端请求，只负责维持缓存的健康度。完整的线程角色分工和事件循环细节见 [Architecture](/docs/CS/DB/Memcached/Architecture.md)。

### Memory Allocation：Slab 的分层拟合

value 进来之前，先决定放进哪个 slabclass。slab 是 1 MB 的页面，每个 slab 在创建时被等切成固定大小的 chunk；slabclass 1 的 chunk 最小（102 字节默认），后续按 `-f` 增长因子（默认 1.25）逐级放大，再对 8 取整。新 item 写入时选择**能装下它的最小 chunk**，避免浪费。当某个 slabclass 的全部 chunk 用完时，要么该 slabclass 新申请一个 slab，要么走淘汰流程。详见 [Memory_Allocation](/docs/CS/DB/Memcached/Memory_Allocation.md)。

### Hash Table：渐进式扩容

item 写进 chunk 后，会把 `key → Item` 的映射插入主哈希表。查找时一次 hash + 遍历同桶链表即可定位。当表中 item 数超过 bucket 数的 1.5 倍时触发扩容：旧主表变成 `old_hashtable`，新申请两倍容量的表作为 `primary_hashtable`。扩容过程中用户请求同时查两张表，由后台线程逐步把旧表的 item 指针迁移到新表，迁完后回收旧表。这是 Memcached 为数不多使用双份数据结构的地方。详见 [Hash_Table](/docs/CS/DB/Memcached/Hash_Table.md)。

### Eviction：Segmented LRU + Crawler

内存不够用时不做随机淘汰。Memcached 1.5.0 起默认启用的 Segmented LRU 把每个 slabclass 的 LRU 拆成 HOT / WARM / COLD / TEMP 四段子队列，每段有自己的 mutex。HOT 只放新进且只被 fetch 过一次的 item，WARM 放被 fetch 过至少两次的热点，COLD 放冷数据，TEMP 专门接住 TTL 很短（通常几秒）的临时 item。真正的淘汰发生在 COLD 尾部。与此同时，LRU Crawler 后台线程沿着四段子 LRU 从下往上爬行，主动回收过期 item，避免它们一直占坑。两者配合使得缓存的「死内存」占比大幅下降。详见 [Eviction](/docs/CS/DB/Memcached/Eviction.md)。

### Protocol：文本 / 二进制 / Meta

文本协议是最通用的交互方式，命令以 `\r\n` 分隔、行式输入，适合人工 `telnet` 调试和脚本快速接入。二进制协议把字段固定化，省掉分隔符解析，适合需要极低延迟的客户端。Meta 协议（1.6.0 起）是在文本协议之上加了 `mc.mget` / `mc.set` 等带扩展标志的命令，支持服务端版本戳（CAS value）和客户端自定义版本号，让客户端可以做「我这份比你新才写入」的条件更新。三种协议共用同一个 TCP 端口，服务端自动识别首包格式。详见 [Protocol](/docs/CS/DB/Memcached/Protocol.md)。

### Commands：命令集速查

从存储命令（`set` / `add` / `replace` / `append` / `prepend` / `cas`）到检索命令（`get` / `gets` / `gat` / `gats`），再到变更（`incr` / `decr`）和管理（`touch` / `delete` / `flush_all` / `stats`）的完整命令集，连同每个命令的响应码、边界条件和常见踩坑，集中在 [Commands](/docs/CS/DB/Memcached/Commands.md)。

### Built-in Proxy：内建 Lua 代理

1.6.0 起引入的内建代理让单台 Memcached 实例可以同时做缓存和代理：客户端命令进来后，每个 worker 线程上跑自己的 Lua VM，可以在 Lua 里做路由（把 key 映射到不同的后端 Memcached 集群）、读写穿透到不同数据源、甚至在 Lua 里做聚合。这使得 Memcached 从「纯缓存节点」演进成「缓存 + 代理」二合一。详见 [Proxy](/docs/CS/DB/Memcached/Proxy.md)。

### Configuration：启动参数与运行时调优

`-m`（总内存）、`-f`（增长因子）、`-t`（worker 线程数）、`-c`（最大连接数）、`-o modern`（modern 模式开关）等常用启动参数，以及运行时通过 `stats` 和 `lru tune` 做的在线调优参数说明，集中在 [Configuration](/docs/CS/DB/Memcached/Configuration.md)。

### Distributed：客户端分片

Memcached 服务节点之间不通信，集群能力完全由客户端库（Twemcache、libmemcached、SpyMemcached 等）实现：客户端维护一份节点列表，对 key 做 hash（通常是一致性哈希或 ketama 环），直接连到目标节点。节点增删时哈希环的重分布影响被限制在相邻节点之间。Proxy 模式下服务端也可以做路由，但本质还是客户端不关心后端拓扑的黑盒。详见 [Distributed](/docs/CS/DB/Memcached/Distributed.md)。

### Comparison：与 Redis / Dragonfly 的对比

三者都在内存里跑，但设计目标完全不同：Redis 是「数据结构服务器」，值本身有类型语义；Dragonfly 是「垂直扩展的 Redis/Memcached 兼容替代」，用 thread-per-core 吃满单机器；Memcached 是「最轻量的纯缓存」，值是不透明字节串。选型对比见 [Comparison](/docs/CS/DB/Memcached/Comparison.md)。

---

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Redis](/docs/CS/DB/Redis/Redis.md)
- [Dragonfly](/docs/CS/DB/Dragonfly.md)
- [Cache](/docs/CS/SE/Cache.md)

## References

1. [Scaling Memcached at Facebook](https://www.usenix.org/system/files/conference/nsdi13/nsdi13-final170_update.pdf) — NSDI 2013，Facebook 的大规模 Memcached 集群实践
2. [Memcached GitHub Repository](https://github.com/memcached/memcached) — 官方仓库，`doc/protocol.txt` 是最权威的协议文档
3. [Replacing the Cache Replacement Algorithm in Memcached](https://memcached.org/blog/modern-lru) — 2018 年官方博客，解释 Segmented LRU + LRU Crawler 的设计动机与实现
4. [Memcached Documentation — Internal Architecture](http://docs.memcached.org/features/proxy/arch/) — 内建 Proxy 架构文档
