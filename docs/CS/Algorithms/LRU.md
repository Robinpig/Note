## Introduction

LRU（Least Recently Used，最近最久未使用）是最常用的缓存/页面置换策略：当容量不足需要淘汰时，**优先丢弃最久没有被访问过的数据**。
直觉依据是局部性原理——最近用过的数据，将来更可能再次被使用。它是操作系统[页面置换算法](/docs/CS/Algorithms/Algorithms.md?id=page-replacement-algorithms)与各类缓存（CPU cache、Redis、Buffer Pool、业务缓存）的共同基础。

## Operations

一个 LRU 缓存需要支持三个操作且都应尽量 O(1)：

- `get(key)`：读取，命中后要把该项标记为「最近使用」；
- `put(key, value)`：写入/更新；容量超限时淘汰「最久未使用」项；
- 维护严格的访问时间顺序。

## Data Structure: HashMap + Doubly Linked List

单一结构都不够：

- 纯[哈希表](/docs/CS/Algorithms/hash.md)能 O(1) 查找，但无序，无法知道谁最久未用；
- 纯[链表](/docs/CS/Algorithms/struct/linked-list.md)能 O(1) 增删，但查找要 O(n)。

经典组合是 **HashMap + 双向链表**：

```
head(最近)                                                          tail(最久)
  │                                                                   │
[D] ↔ [B] ↔ [A] ↔ [C]        map: { D→node, B→node, A→node, C→node }
```

- HashMap：key → 链表节点，O(1) 定位；
- 双向链表：维护访问顺序，**头是最近使用、尾是最久未使用**；
- 访问命中：把节点摘下来移到头部；
- 写入超容：删掉尾节点，并从 map 中移除。

借助 dummy head/tail（哨兵）可以省掉大量空指针判断。

```java
class Node { int key, val; Node prev, next; }

get(k):
    node = map.get(k); 若不存在返回 -1
    moveToHead(node)          // 标记为最近使用

put(k, v):
    若 k 已存在: 更新 val 并 moveToHead
    否则: 新建节点插头部、放入 map
          若 size > capacity: 删除尾节点并从 map 移除其 key
```

Java 可直接用 [LinkedHashMap](/docs/CS/Java/JDK/Collection/Map.md)：构造时 `accessOrder=true`，
重写 `removeEldestEntry` 即可，内部正是「HashMap + 双向链表」，无需手写。

## Cache Hit and Analyze

- 缓存命中率依赖工作集存在明显的访问局部性；对扫描型、访问均匀的负载，LRU 会被「一次性遍历大量冷数据」污染（cache污染/扫描冲刷），把热点挤出。
- 工程上常用改进：**LFU**（按访问频率而非最近时间，抗扫描但对频率突变不敏感）、**ARC/LIRS**（自适应区分 recency 与 frequency）、
  分段 LRU（如 MySQL 的 young/old 两段）、以及采样近似 LRU（不全量维护链表）。
- 缓存写策略（write-through / write-back / 失效）与 LRU 是正交问题。

## System Implementations

理论上的精确 LRU 需要为每次访问维护全局链表，在数据量巨大或并发极高时代价可观，真实系统多做近似或改造：

- **Java**：`LinkedHashMap`（accessOrder + removeEldestEntry）手写最简 LRU。
- **Redis**：maxmemory 淘汰策略 `allkeys-lru` / `volatile-lru`，采用**采样近似 LRU**——随机取若干 key 淘汰其中最久未用者，避免给每个 key 维护全局双向链表；另有 LFU 选项，见 [Redis memory](/docs/CS/DB/Redis/memory.md)。
- **MySQL InnoDB Buffer Pool**：LRU 列表分为 young（热）/old（冷）两段，全表扫描的页先进入 old 段、需二次访问才晋升 young，避免单次扫描污染热数据，见 [Buffer Pool LRU](/docs/CS/DB/MySQL/memory.md?id=lru-algorithm)。

## Links

- [Page Replacement Algorithms](/docs/CS/Algorithms/Algorithms.md?id=page-replacement-algorithms)
- [hash](/docs/CS/Algorithms/hash.md)
- [linked-list](/docs/CS/Algorithms/struct/linked-list.md)
- [Redis memory](/docs/CS/DB/Redis/memory.md)
- [MySQL InnoDB Buffer Pool](/docs/CS/DB/MySQL/memory.md?id=lru-algorithm)

## References

1. [LRU - Wikipedia](https://en.wikipedia.org/wiki/Cache_replacement_policies#Least_recently_used_(LRU))
2. [Redis: Using Redis as an LRU cache](https://redis.io/docs/latest/develop/reference/eviction/)
