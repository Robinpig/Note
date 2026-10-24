## Introduction

Memcached 使用**链式哈希表**解决冲突。哈希表的查找路径很短：一次 hash 定位 bucket 头部 → 遍历该 bucket 的单向链表 → 对比 key 找到 Item。在 Memcached 的工作负载下（value 相对均匀、key 有足够熵），链表平均长度接近 1，实际查找几乎是 O(1)。

## Structure

Memcached 维护两张哈希表指针：

- `primary_hashtable`：**主哈希表**，所有正常的插入、查找、删除都走这里。
- `old_hashtable`：**旧哈希表**，仅在扩容期间被使用——当新主表已经建好但旧表的 item 还没全部迁移过来时，查找会同时查两张表。

每张哈希表由一个 `bucket *` 数组组成。每个 bucket 是一个指向 `item` 的链表头，同一个 bucket 内的多个 item 组成**单向链表**（插入用头插法），靠 `item->h_next` 链接。

哈希函数默认是 32 位的 `hash()` 函数（MurmurHash3 的简化实现），对 key 做 hash 后取模得到 bucket 下标。

### Per-Bucket Lock

早期 Memcached 的哈希表只有一把全局锁，随着线程数增加锁争用严重。现在 bucket 数组后面紧跟一组 `item_lock[]` 互斥锁——**每个 bucket 有自己的 mutex**。这使得 worker 线程在做哈希表操作时只需要锁住目标 bucket，而不是整个表。扩容期间旧表和主表各自有独立的锁数组。

## Incremental Expansion

当主哈希表中 item 数超过 bucket 数的 **1.5 倍**（`HASH_POWER_LOW 32`，即负载因子 32）时触发扩容：

1. 新申请一张 bucket 数为旧表 **两倍** 的哈希表，作为新的 `primary_hashtable`。
2. 原来的 `primary_hashtable` 变成 `old_hashtable`。
3. 后台线程**逐步**把旧表的 item 指针迁移到新表——每次迁移固定数量（默认 1024）的 item，迁完一批让出 CPU，避免阻塞请求处理。
4. 迁移过程中，用户请求的查找逻辑变成「先查 primary_hashtable，没找到再查 old_hashtable」；插入和删除**只操作 primary_hashtable**。
5. 全部迁移完成后，释放 `old_hashtable` 内存，系统回归单表模式。

### Why Incremental

如果一次性把所有 item 重哈希，Memcached 会在扩容期间完全停摆——bucket 数翻倍意味着每个 item 的 bucket 下标都可能变化，全量重哈希在百万级 item 的场景下会阻塞几十毫秒甚至更长。增量扩容把重哈希拆成很多小步骤，每个 worker 线程每次只迁几批 item，用户请求的延迟抖动可以忽略不计。

### Multi-Queue Mode（1.6.23+）

1.6.23 起支持 `-o hashtable=multi_queue` 模式：哈希表被切成 16 个队列，每个队列的 bucket 和锁独立。这进一步降低了锁争用，适合超大规模实例（几百万 item、高并发写入）。默认仍然是单队列模式（向后兼容）。

## Lookup Path

一个 GET 请求的哈希表查找路径：

1. 对 key 做 hash 得到 bucket 下标。
2. 加 bucket 的 mutex。
3. 遍历 bucket 内的单向链表，逐个对比 key（Memcached 的 key 是 C 字符串，直接 `memcmp`）。
4. 找到 item → 释放锁 → 返回 value。
5. 没找到 → 释放锁 → 查 `old_hashtable`（如果存在）。
6. 旧表也没 → MISS。

写入时（SET / ADD / REPLACE / CAS）会先做查找：如果 bucket 里已有同名 key，直接覆盖 item 的 value 部分（释放旧 chunk、填充新 chunk、重置过期时间和 flag）；如果是新 key，头插到 bucket 链表头部。

## Links

- [Memcached](/docs/CS/DB/Memcached.md)
- [Architecture](/docs/CS/DB/Memcached/Architecture.md)
- [Memory Allocation](/docs/CS/DB/Memcached/Memory_Allocation.md)
- [Eviction](/docs/CS/DB/Memcached/Eviction.md)

## References

1. [Memcached GitHub — hash.c](https://github.com/memcached/memcached/blob/master/hash.c) — 哈希表实现源码
2. [Memcached GitHub — item.c](https://github.com/memcached/memcached/blob/master/item.c) — item 结构与生命周期
