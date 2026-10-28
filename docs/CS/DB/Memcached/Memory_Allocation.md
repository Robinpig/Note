## Introduction

Memcached 的内存分配器的核心目标是 **避免 malloc/free 产生的碎片**。传统的动态内存分配在高频小块分配/释放场景下会产生大量碎片，导致物理内存无法被利用。Memcached 从设计之初就决定自己管理内存：启动时一次性向系统申请一大块内存（默认 64 MB，通过 `-m` 参数指定），然后在自己的地盘里按需切 slab、切 chunk、切 item。

## Slab Class Hierarchy

Memcached 启动时会预创建 **64 个 slabclass**（索引 0 到 63），每个 slabclass 管一个固定 chunk 大小范围：

- slabclass 1 的 chunk 最小，默认 102 字节（8 字节增长对齐后的实际值是 96 字节）。
- 后续 slabclass i 的 chunk size = `前一级 chunk size × 增长因子`，再对 8 取整。
- 默认增长因子 `-f 1.25`，可通过 `-f` 参数调大或调小。
- slabclass 0 保留给 slab 重新分配使用，基本不参与日常 chunk 分配。

当 value 实际大小落在两个 slabclass 的 chunk size 之间时，选择**能装下它的最小 chunk**，保证不溢出。例如 key+value+item 头占 150 字节时，会放进 chunk size 为 160 的 slabclass，而不是更大的。

```
slabclass 1  chunk ≈ 96B    (102 × 1.0, 8对齐)
slabclass 2  chunk ≈ 120B   (102 × 1.25)
slabclass 3  chunk ≈ 152B   (120 × 1.25)
...
slabclass 63 chunk 非常大    (取决于配置的增长因子)
```

## Slab Allocation

每个 slabclass 按需要不断分配新的 **slab**（大小固定 1 MB）。slab 是向操作系统申请内存的基本单位，申请后立即被**等切成相同大小的 chunk**，chunk 数量 = slab_size / chunk_size。

chunk 是 item 的容器。每个 chunk 里放一个 `item` 结构，item 头部预留了链表指针、flag、过期时间、CAS value 等元数据，真正的 key 和 value 接在后面。

新分配出来的 chunk 会被加入该 slabclass 的 **freelist**（空闲链表），set 命令写入时从 freelist 头部取一个，过期被淘汰后重新回到 freelist。

### Item Layout

`item` 结构在 chunk 内的内存布局：

```
┌─────────────┬──────────────┬──────────────┬──────────────┐
│  item header│    key       │    CAS val   │    value     │
└─────────────┴──────────────┴──────────────┴──────────────┘
```

item header 包含：哈希表桶内链表指针、slabclass 索引、flag、过期时间戳（绝对时间）、CAS value、LRU 双向链表指针、活动位（FETCHED / ACTIVE）等。

## Slab Automover

1.6.6 起 **默认开启** `slab_automover`（可通过 `-o slab_automover=no` 关闭）。

正常情况下，一个 slabclass 的 chunk 用完时会申请新 slab；一个 slabclass 的 chunk 长期空闲时，它的 slab 就一直躺着。Slab Automover 的作用是在不同 slabclass 之间**搬运 slab**：

- 监控每个 slabclass 的 eviction 频率和空闲 chunk 数。
- 如果 slabclass A 频繁 eviction（说明内存不够）而 slabclass B 有大量空闲 chunk（说明分多了），就把 B 的一个 slab 移给 A。
- 被移动的 slab 上已有的 chunk 和 item 不会丢失——slab 只是整块移动，内部结构不变。

这个机制使得不同 slabclass 之间的内存分配更动态，避免了某些 slabclass 被饿死、某些被闲置的情况。

### Slab Reassignment

更早版本的 slab 重新分配是手动触发的，需要通过 `stats slabs` 观察后重启 memcached 并调整 `-f` 增长因子。现在有了 Slab Automover，一般不需要手动干预。

## Memory Lifecycle

一个 item 的完整内存生命周期：

1. **写入（SET）**：计算 key+value 总大小 → 匹配最小 slabclass → 从 freelist 取 chunk → 填充 item → 插入哈希表 → 插入对应 slabclass 的 LRU 头部。
2. **读取（GET）**：哈希表定位 item → 返回 value → 根据 LRU 策略决定是否 bump。
3. **过期（TTL 到期）**：被动（GET 时发现已过期，释放内存）或主动（LRU Crawler 爬行回收）。
4. **淘汰（内存不足）**：从 COLD LRU 尾部取 item → 检查是否已过期（是则直接回收，否则从哈希表摘除并释放）。
5. **释放**：chunk 回到 freelist，等待下一个 item 写入。

## Links

- [Memcached](/docs/CS/DB/Memcached.md)
- [Architecture](/docs/CS/DB/Memcached/Architecture.md)
- [Hash Table](/docs/CS/DB/Memcached/Hash_Table.md)
- [Eviction](/docs/CS/DB/Memcached/Eviction.md)

## References

1. [Memcached GitHub — slabs.c](https://github.com/memcached/memcached/blob/master/slabs.c) — slab 分配器源码
2. [Memcached GitHub — items.c](https://github.com/memcached/memcached/blob/master/items.c) — item 管理源码
