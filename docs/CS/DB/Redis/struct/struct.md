## Introduction

要理解一个程序如何工作，最直接的办法是先理解它使用的数据结构。

所有服务器配置、以及总体上所有共享状态，都定义在一个名为 [server](/docs/CS/DB/Redis/server.md) 的全局结构里，类型为 `struct redisServer`。

另一个重要的 Redis 数据结构是 [client](/docs/CS/DB/Redis/server.md?id=client)。它的字段很多，这里只列主要几个：

```c
struct client {
    int fd;
    sds querybuf;
    int argc;
    robj **argv;
    redisDb *db;
    int flags;
    list *reply;
    // ... many other fields ...
    char buf[PROTO_REPLY_CHUNK_BYTES];
}
```

如上面的 client 结构所示，命令里的参数用 `robj` 结构描述。
下面是完整的 `robj` 结构，它定义了 [Redis 对象](/docs/CS/DB/Redis/redisDb.md?id=redisobject)：

```c
typedef struct redisObject {
    unsigned type:4;
    unsigned encoding:4;
    unsigned lru:LRU_BITS; /* lru time (relative to server.lruclock) */
    int refcount;
    void *ptr;
} robj;
```

- 这个结构基本可以表示 Redis 的全部基本数据类型：字符串、列表、集合、有序集合等。
- 它带 `type` 字段，因此能知道某个对象是什么类型；带 `refcount`，同一个对象可以在多处被引用而不必重复分配。
- 最后 `ptr` 指向对象的真实表示，即便 `type` 相同，表示也会随 `encoding` 不同而变化。

Redis 内部大量使用 redis object，但为了避开间接访问的开销，许多地方已经改用不被 Redis 对象包裹的裸动态字符串。

## Directory Navigation

本目录按「通用字符串 → 集合类型 → 编码实现 → 专用结构」组织。`Redis` 对象与 key 的字典体系在父级页 [redisDb.md](/docs/CS/DB/Redis/redisDb.md)，本页只讲被 `robj.ptr` 指向的具体结构。

**字符串与通用编码**：[SDS](/docs/CS/DB/Redis/struct/SDS.md) 是 Redis 自己的动态字符串实现（长度前缀 + 分配策略 + 二进制安全），一切字符串值的底座；[bitmap](/docs/CS/DB/Redis/struct/bitmap.md) 是在普通 string 上做的位操作封装。

**集合类型**：[hash](/docs/CS/DB/Redis/struct/hash.md) 讲哈希表编码与其 listpack 小对象编码；[list](/docs/CS/DB/Redis/struct/list.md) 与合并后的 [quicklist](/docs/CS/DB/Redis/struct/quicklist.md) 是链表与 quicklist 的关系；[set](/docs/CS/DB/Redis/struct/set.md) 与整数集合 [intset](/docs/CS/DB/Redis/struct/intset.md) 是两种集合编码；[zset](/docs/CS/DB/Redis/struct/zset.md) 是有序集合，其跳表底层单独成篇 [skiplist](/docs/CS/DB/Redis/struct/skiplist.MD)。

**压缩表示**：[ziplist](/docs/CS/DB/Redis/struct/ziplist.md) 与 [listpack](/docs/CS/DB/Redis/struct/listpack.md) 是 ziplist 及其后继listpack 的实现，小元素聚合编码依赖它们。

**专用结构**：[Stream](/docs/CS/DB/Redis/struct/Stream.md) 是持久化消息流（rax 索引 + listpack 打包，消费组与 PEL）；[geo](/docs/CS/DB/Redis/struct/geo.md) 是经纬度编码（Zset 的 52 位地理哈希）；[HyperLogLog](/docs/CS/DB/Redis/struct/HyperLogLog.md) 与 [BloomFilter](/docs/CS/DB/Redis/struct/BloomFilter.md) 是两个近似基数/概率结构。

## Data Types

Redis 实现的数据结构有几个特别之处：

- 即使它们始终在服务器内存里被服务和修改，Redis 仍负责把它们存到磁盘上——也就是说 Redis 很快，但默认不保证不丢。
- 数据结构的实现把内存效率放在第一位，所以同一个结构在 Redis 里通常比用高级语言建模时更省内存。
- Redis 还提供一整套本该在数据库里才见到的能力：复制、可调的持久化强度、集群与高可用。

> 另一个合适的类比是：把 Redis 想成一个更复杂的 memcached——操作不止 SET 和 GET，而是作用在列表、集合、有序结构这类复杂数据类型上的操作。

 



传统键值存储把字符串 key 关联到字符串 value；Redis 的 value 不限于简单字符串，还可以放更复杂的数据结构。
下面是 Redis 支持的全部数据结构，本目录会分别展开：

* 二进制安全的字符串（Binary-safe strings）。
* 列表（Lists）：按插入顺序排列的字符串元素集合，本质是链表。
* 集合（Sets）：去重、无序的字符串元素集合。
* 有序集合（Sorted sets）：与集合类似，但每个字符串元素都关联一个浮点数 *score*；
  元素始终按 score 排序，因此可以像 Sets 那样取一段元素范围（例如给我前 10 个或后 10 个）。
* 哈希（Hashes）：由 field 与 value 组成的 map，field 和 value 都是字符串，很像 Ruby / Python 的 hash。
* 位数组（bitmaps）：用专门的命令把 String 的值当作位数组操作——置位、清位、统计为 1 的位数、找第一个 0 或 1 的位。
* HyperLogLog：用来估算集合基数（cardinality）的概率型结构，比看起来简单，详见 [HyperLogLog](/docs/CS/DB/Redis/struct/HyperLogLog.md)。
* [Streams](/docs/CS/DB/Redis/struct/Stream.md)：只追加的、类 map 条目集合，提供一种抽象的日志数据类型。



同一个 Redis 对象可以有多种编码方式：



<!-- tabs:start -->

##### **Object**
```c
// server.h
/* The actual Redis Object */
#define OBJ_STRING 0    /* String object. */
#define OBJ_LIST 1      /* List object. */
#define OBJ_SET 2       /* Set object. */
#define OBJ_ZSET 3      /* Sorted set object. */
#define OBJ_HASH 4      /* Hash object. */
#define OBJ_MODULE 5    /* Module object. */
#define OBJ_STREAM 6    /* Stream object. */
```

##### **Encoding**
```c
#define OBJ_ENCODING_RAW 0     /* Raw representation */
#define OBJ_ENCODING_INT 1     /* Encoded as integer */
#define OBJ_ENCODING_HT 2      /* Encoded as hash table */
#define OBJ_ENCODING_ZIPMAP 3  /* Encoded as zipmap */
#define OBJ_ENCODING_ZIPLIST 5 /* Encoded as ziplist */
#define OBJ_ENCODING_INTSET 6  /* Encoded as intset */
#define OBJ_ENCODING_SKIPLIST 7  /* Encoded as skiplist */
#define OBJ_ENCODING_EMBSTR 8  /* Embedded sds string encoding */
#define OBJ_ENCODING_QUICKLIST 9 /* Encoded as linked list of ziplists */
#define OBJ_ENCODING_STREAM 10 /* Encoded as a radix tree of listpacks */
```

<!-- tabs:end -->



从 Redis 2.2 起，多数数据类型在元素规模不超过阈值时会改用更省空间的编码。哈希、列表、纯整数集合与有序集合，只要元素个数与单元素大小都在限制内，就会用极省内存的方式编码，*最多可省 10 倍内存*（平均约省 5 倍）。

类型与编码的对应关系，以及具体结构在哪一页：

| type | 常见 encoding | 底层结构 | 本库详页 |
| :-- | :-- | :-- | :-- |
| `OBJ_STRING` | `RAW`、`INT`、`EMBSTR` | SDS | [SDS](/docs/CS/DB/Redis/struct/SDS.md)、[bitmap](/docs/CS/DB/Redis/struct/bitmap.md) |
| `OBJ_LIST` | `QUICKLIST` | 由 listpack（旧版 ziplist）串成的链表 | [list](/docs/CS/DB/Redis/struct/list.md)、[quicklist](/docs/CS/DB/Redis/struct/quicklist.md) |
| `OBJ_SET` | `INTSET`、`HT` | 整数用紧凑数组，否则用字典 | [set](/docs/CS/DB/Redis/struct/set.md)、[intset](/docs/CS/DB/Redis/struct/intset.md) |
| `OBJ_ZSET` | `SKIPLIST`、`LISTPACK` | 小集合用压缩列表，否则跳表 + 字典 | [zset](/docs/CS/DB/Redis/struct/zset.md)、[skiplist](/docs/CS/DB/Redis/struct/skiplist.MD) |
| `OBJ_HASH` | `HT`、`LISTPACK` | 小集合用压缩列表，否则字典 | [hash](/docs/CS/DB/Redis/struct/hash.md) |
| `OBJ_STREAM` | 由 listpack 组成的 radix tree | Stream 的条目打包 | [Stream](/docs/CS/DB/Redis/struct/Stream.md) |
| `OBJ_MODULE` | 模块自定义 | 由模块自己决定 | [module](/docs/CS/DB/Redis/module.md) |



![](https://substackcdn.com/image/fetch/f_auto,q_auto:good,fl_progressive:steep/https%3A%2F%2Fsubstack-post-media.s3.amazonaws.com%2Fpublic%2Fimages%2F36232d4c-1720-4ca0-81db-bbb6df5f95a2_1600x687.png)


### Keys

Redis 的 key 是二进制安全的：任何二进制序列都能当 key，从 "foo" 这样的字符串到一个 JPEG 文件的内容都行，空串也是合法的 key。

关于 key 还有几条规则：

- **过长的 key 不是好主意**。1024 字节的 key 不仅费内存，还因为要在数据集里做多次数昂贵的 key 比较而拖慢查找。即便目的确实是拿一个大值去判存在，先哈希一次（例如 SHA1）也更划算——尤其是内存与带宽上。
- **过短的 key 往往也不是好主意**。能写 `user:1000:followers` 时，没必要写成 "u1000flw"：后者更易读，而多出的字符相比 key 对象与 value 对象自身的开销只是零头。短 key 确实省一点内存，你要做的是找到平衡点。
- **尽量固定一套命名 schema**，比如 "object-type:id"（`user:1000`）；多段字段常用点或横线，如 `comment:1234:reply.to` 或 `comment:1234:reply-to`。
- key 的最大长度是 **512 MB**。

```shell
# client
127.0.0.1:6379> set 111.111 hello

# server
gdb redis-server
(gdb) r
(gdb) b dictGenHashFunction

(gdb) c
(gdb) p (char*) key
$4 = 0x7ffff1a1b0d3 "111.111"
(gdb) p len
$5 = 7
```

#### Key expiration

Key 过期（expiration）可以给一个 key 设超时时间，也就是 "time to live"、TTL；到期后 key 会被自动销毁。

几点要注意：

* 可以用秒或毫秒为精度设置过期。
* 但过期时间的分辨率始终是 1 毫秒。
* 过期信息会被复制并持久化到磁盘；服务器停机期间时间「照算」——因为 Redis 存的是 key 过期的那个时刻，而不是剩余时长。

### Strings

Redis 的 [String](/docs/CS/DB/Redis/struct/SDS.md) 是最简单的 value 类型。既然 key 本身就是字符串，把 string 当 value 用等于把字符串映射到字符串。
value 可以是任意内容的字符串（含二进制数据），例如把一张 jpeg 存进 value；单个 value 不能超过 512 MB。

`INCR` 把字符串 value 当整数解析、加一，再写回为新值。**INCR 是原子的**：多个客户端同时对同一个 key 执行 INCR 也不会踩到竞态。

### Lists

Redis [列表](/docs/CS/DB/Redis/struct/list.md) 用链表实现，这意味着即使列表里有上百万个元素，在头部或尾部追加一个元素仍是*常数时间*操作。

Redis 之所以用链表实现列表，是因为对数据库来说「往一个很长的列表里极快地追加元素」是关键能力。
另一个显著优势（马上会看到）是：列表的长度也能在常数时间内取到。

当需要快速访问一个大集合的中间部分时，该换另一种结构——有序集合（sorted sets）。

列表能派上用场的场景很多，两个最有代表性的：

* 记住用户在社交网络里最新发布的动态。
* 进程间通信，用生产者-消费者模式：生产者把条目 push 进列表，消费者（通常是 *worker*）取出并执行动作。Redis 有专门的列表命令让这种用法更可靠也更高效。

用一个常见场景逐步说明：首页要展示图片社交网站最新发布的照片并加速访问。

* 每当用户发布新照片，就用 `LPUSH` 把它的 ID 塞进列表。
* 用户访问首页时，用 `LRANGE 0 9` 取最近 10 条。

#### Capped lists

很多场景只想要列表里的*最新 N 项*——社交动态、日志，或任何东西。

Redis 允许把列表当受限集合（capped collection）用：只保留最新 N 项，用 `LTRIM` 丢弃最老的。
`LTRIM` 与 `LRANGE` 语法相似，但**不是把指定范围的元素显示出来，而是把这个范围设为列表的新值**，范围之外的元素全部删除。

> [!NOTE]
>
> `LRANGE` 严格来说是 O(N) 命令，但取靠近头部或尾部的短区间是常数时间操作。

#### Blocking Queue

Redis 提供了 `BRPOP` 与 `BLPOP`，它们是 `RPOP`/`LPOP` 的可阻塞版本：列表为空时挂起，只有当有新元素加入、或到达用户指定的超时才返回调用方。

超时可以填 0 表示无限等待；也可以一次指定多个列表，只要其中任意一个来元素就被通知。

关于 `BRPOP` 还有几点：

1. 客户端按顺序得到服务：最早阻塞等待某个列表的客户端，会最先拿到其他客户端 push 进来的元素。
2. 返回值与 `RPOP` 不同，是包含 key 名的二元数组——因为 `BRPOP`/`BLPOP` 可以同时等多个列表。
3. 超时到达时返回 NULL。

### Hashes

Redis [哈希](/docs/CS/DB/Redis/struct/hash.md)就是人们期待中「hash」的样子，由 field-value 对组成。

哈希很适合表示*对象*，而且单个哈希能放的 field 数量没有实际限制（只受内存约束），因此可以在应用里以很多种方式使用它。

值得注意的是，小哈希（少量元素、小 value）在内存里会用一种特殊编码存放，非常省内存。

### Sets

Redis [集合](/docs/CS/DB/Redis/struct/set.md)是无序的字符串元素集合。

`SADD` 往集合里加新元素；此外还能做很多操作：判断某元素是否已存在、对多个集合求交并差等。
集合擅长表达对象之间的关系，例如实现 tag 就很直接。

### Sorted Sets

[有序集合](/docs/CS/DB/Redis/struct/zset.md)像集合与哈希的混合体：和集合一样由不重复的字符串元素组成，某种意义上它就是集合；
但集合里的元素无序，有序集合里每个元素都关联一个浮点数 *score*（这一点又像哈希，因为每个元素都映射到一个值）。

而且元素是*按序取出的*——不是「按需排序」，顺序本身就是它所采用的数据结构的特性。排序规则：

* 若 A、B 两个元素 score 不同，则 `A.score > B.score` 时 A > B。
* 若 A、B score 完全相同，则 A 的字符串按字典序大于 B 时 A > B；两者不可能相等，因为元素唯一。

有序集合用一份「双端口」结构实现——同时含跳表与哈希表，因此每次添加元素都是 $O(log(N))$。
它很适合更新量极大的场景，最常见的用法是排行榜（leader board）。

### Bitmaps

[位图](/docs/CS/DB/Redis/struct/bitmap.md)不是一种独立数据类型，而是在 String 上定义的一组按位操作。
字符串是二进制安全的 blob、最长 512 MB，因此最多可以放到 $2^{32}$ 个不同的位。

位操作分两类：常数时间的单比特操作（置 1、清 0、取某位的值），以及对一组比特的操作，例如统计给定范围内置 1 的位数（population count）。

位图最大的优势是存信息时极度省空间。比如一个系统里用户用递增 ID 表示，那么「某个用户是否愿意收简报」这一位信息，40 亿用户只需 512 MB 内存。

常见用法：

* 各类实时分析。
* 存与对象 ID 关联的布尔信息——既省空间又高性能。

举例：想知道网站用户「连续每日访问」的最长纪录。把第 0 天定为网站上线日，用户每次访问就用 `SETBIT` 置一位；位下标取当前 unix 时间减去初始偏移再除以一天的秒数（通常 `3600*24`）。
这样每个用户只有一个记录着每日到访情况的小字符串：`BITCOUNT` 直接算出到访天数，多调用几次 `BITPOS`（或把位图取回客户端分析）就能算出最长连续段。

位图很容易切成多个 key，比如为了分片，也因为一般不该操作巨大的 key。做法很直接：每个 key 存 M 位，key 名用 `bit-number/M` 求得，key 内要操作的位用 `bit-number MOD M`。

### HyperLogLogs

[HyperLogLog](/docs/CS/DB/Redis/struct/HyperLogLog.md) 是概率型结构，用来数「不重复的东西」（严格说是估算集合的基数）。
通常统计不重复元素要花的内存与元素数量成正比，因为必须记住见过的元素才不会重复计数；
但有一类算法用精度换内存：得到的是带标准误差的估计值，Redis 实现里小于 1%。它的妙处在于内存不再随数量增长，而是常数——最坏 12k 字节，如果 HLL 见过的元素很少则远小于此。

一个典型用例：统计每天搜索框里有多少不重复的查询。

## Streams

Stream 是 Redis 5.0 引入的新类型，用更抽象的方式建模「日志」这一数据结构。
日志的本质没变：日志文件常以只追加模式打开，Redis Stream 首先也是一种只追加结构；
作为一种内存里的抽象数据类型，它实现了强力的操作来突破日志文件的限制。

此外 Redis Stream 还实现了两个非必需的附加特性：一组阻塞操作让消费者可以等生产者写入的新数据，以及所谓的**消费组（Consumer Groups）**——让一组客户端协作消费同一个消息流的不同部分。

### Tips

- 取全部 key 用 SCAN 而不是 KEYS（后者会阻塞）
- 删大数据用 UNLINK 而不是 DEL
- RENAME 之前先确认 EXISTS

## Data Features

### Shared Objects

见 [createSharedObjects](/docs/CS/DB/Redis/start.md?id=createsharedobjects)。

### Automatic Creation and Removal of Keys

这不是列表特有的行为，而是所有由多元素构成的 Redis 类型共有的规则——Stream、Set、Sorted Set、Hash 都一样。
行为可以用三条规则概括：

1. 往聚合类型里加元素时，若目标 key 不存在，会先创建一个空的聚合类型再加元素。
2. 从聚合类型里删元素时，若值变空，key 会被自动销毁。Stream 是这条规则的唯一例外。
3. 对一个不存在的 key 调用只读命令（如返回列表长度的 `LLEN`），或调用会删元素的写命令，其结果与该 key 恰好持有一个对应类型的空聚合时完全一致。

### Sort

有时需要拿到 Redis 列表或集合按某种顺序排好的副本，或者让有序集合按 score 之外的顺序输出。Redis 为此提供了 `SORT` 命令。

### Pipeline

类似批量操作：把多条命令一次写入、一次读回，省掉逐条往返的 RTT。

### Transaction

Redis 事务提供隔离性与一致性；若开启 AOF 且 `appendfsync always`，也提供持久性。

需要强调的是，**即使某条命令失败，队列里的其余命令仍会继续执行**——Redis *不会*因此中断处理。

#### Why Redis does not support roll backs?

- Redis 命令只有两种失败方式：语法错误（入队时检测不出来），或对类型不对的 key 调用。也就是说命令失败其实是**程序错误**，而这类错误极早在开发期就会暴露，不会留到生产环境。
- 不需要回滚能力，让 Redis 内部更简单、也更快。

**回滚本身也救不了程序错误。**

#### Optimistic locking using check-and-set

[WATCH](https://redis.io/commands/watch) 给 Redis 事务带来 check-and-set（CAS）语义：被 `WATCH` 的 key 会被监视，只要在 [EXEC](https://redis.io/commands/exec) 之前有任何一个被改动，整个事务放弃执行，[EXEC](https://redis.io/commands/exec) 返回一个 [Null reply](https://redis.io/topics/protocol#nil-reply) 告知事务失败。
这时只能重做一遍，盼着这次不再撞上竞争。这种加锁方式称为*乐观锁*，是一种很有力的手段。

[Redis 脚本](/docs/CS/DB/Redis/struct/struct.md?id=lua-scripts)天生就是一个事务：事务能做的事脚本都能做，而且通常更简单也更快。

### PubSub

[发布订阅（PubSub）](/docs/CS/DB/Redis/PubSub.md)是一种经典消息模式，历史可追溯到 1987 年。

### Lua Scripts

[Lua](/docs/CS/DB/Redis/Lua.md) 这门轻量脚本语言自 Redis 2.6 起被引入。

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)
- [redisDb.md](/docs/CS/DB/Redis/redisDb.md)

## References

1. [A Crash Course in Redis](https://blog.bytebytego.com/p/a-crash-course-in-redis)
2. [OBJECT ENCODING](https://redis.io/docs/latest/commands/object-encoding/)
