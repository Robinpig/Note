## 简介

有序集合是一种介于集合和哈希之间的数据类型。
与集合一样，有序集合由唯一、不重复的字符串元素组成，因此在某种意义上，有序集合也是集合。

有序集合的经典使用场景如下：

- 学生成绩排名
- 粉丝列表，根据关注的先后时间排序
- 排行榜

然而，集合中的元素是无序的，而有序集合中的每个元素都关联一个浮点数值，称为*分数*（这也是该类型类似于哈希的原因，因为每个元素都映射到一个值）。

此外，有序集合中的元素是*有序的*（因此它们不是按需排序，顺序是用于表示有序集合的数据结构的特性）。它们根据以下规则排序：

- 如果 A 和 B 是两个具有不同分数的元素，则 A > B 如果 A.score > B.score。
- 如果 A 和 B 具有完全相同的分数，则 A > B 如果 A 字符串在字典序上大于 B 字符串。A 和 B 字符串不能相等，因为有序集合只有唯一元素。

从一个简单示例开始，添加一些选定的黑客名字作为有序集合元素，以其出生年份作为"分数"。

```
> zadd hackers 1940 "Alan Kay"
(integer) 1
> zadd hackers 1957 "Sophie Wilson"
(integer) 1
> zadd hackers 1953 "Richard Stallman"
(integer) 1
> zadd hackers 1949 "Anita Borg"
(integer) 1
> zadd hackers 1965 "Yukihiro Matsumoto"
(integer) 1
> zadd hackers 1914 "Hedy Lamarr"
(integer) 1
> zadd hackers 1916 "Claude Shannon"
(integer) 1
> zadd hackers 1969 "Linus Torvalds"
(integer) 1
> zadd hackers 1912 "Alan Turing"
(integer) 1
```

如你所见，`ZADD` 类似于 `SADD`，但多了一个参数（放在要添加的元素之前），即分数。
`ZADD` 也是可变参数的，因此可以自由指定多个分数-值对，即使上面的示例中没有使用。

对于有序集合，返回按出生年份排序的黑客列表很简单，因为*它们已经排好序了*。

实现说明：有序集合通过同时包含跳表和哈希表的双端口数据结构实现，因此每次添加元素时 Redis 执行 O(log(N)) 操作。
这很好，但当请求有序元素时，Redis 完全不需要做任何工作，已经全部排好序了：

```
> zrange hackers 0 -1
1) "Alan Turing"
2) "Hedy Lamarr"
3) "Claude Shannon"
4) "Alan Kay"
5) "Anita Borg"
6) "Richard Stallman"
7) "Sophie Wilson"
8) "Yukihiro Matsumoto"
9) "Linus Torvalds"
```

注意：0 和 -1 表示从元素索引 0 到最后一个元素（-1 的工作方式与 `LRANGE` 命令相同）。

如果想要相反的顺序，从小到大，则使用 `ZREVRANGE` 而不是 `ZRANGE`：

```
> zrevrange hackers 0 -1
1) "Linus Torvalds"
2) "Yukihiro Matsumoto"
3) "Sophie Wilson"
4) "Richard Stallman"
5) "Anita Borg"
6) "Alan Kay"
7) "Claude Shannon"
8) "Hedy Lamarr"
9) "Alan Turing"
```

也可以使用 `WITHSCORES` 参数返回分数：

```redis
> zrange hackers 0 -1 withscores
1) "Alan Turing"
2) "1912"
3) "Hedy Lamarr"
4) "1914"
5) "Claude Shannon"
6) "1916"
7) "Alan Kay"
8) "1940"
9) "Anita Borg"
10) "1949"
11) "Richard Stallman"
12) "1953"
13) "Sophie Wilson"
14) "1957"
15) "Yukihiro Matsumoto"
16) "1965"
17) "Linus Torvalds"
18) "1969"
```

### zset

Sorted Set 相关的结构定义在 server.h 文件中。Sorted Set 结构体的名称为 zset，其中包含了两个成员，分别是哈希表 dict 和跳表 zsl。

```c
typedef struct zset {
    dict *dict;
    zskiplist *zsl;
} zset;
```

## zadd

创建 [ziplist](/docs/CS/DB/Redis/struct/ziplist.md) 或 [skiplist](/docs/CS/DB/Redis/zset.md?id=skiplist) + [dict](/docs/CS/DB/Redis/struct/hash.md)。

```c
void zaddCommand(client *c) {
    zaddGenericCommand(c,ZADD_IN_NONE);
}

/* 此通用命令实现 ZADD 和 ZINCRBY */
void zaddGenericCommand(client *c, int flags) {
    // ...
    for (j = 0; j < elements; j++) {
        double newscore;
        score = scores[j];
        int retflags = 0;

        ele = c->argv[scoreidx+1+j*2]->ptr;
        int retval = zsetAdd(zobj, score, ele, flags, &retflags, &newscore);
        if (retval == 0) {
            addReplyError(c,nanerr);
            goto cleanup;
        }
        if (retflags & ZADD_OUT_ADDED) added++;
        if (retflags & ZADD_OUT_UPDATED) updated++;
        if (!(retflags & ZADD_OUT_NOP)) processed++;
        score = newscore;
    }
    // ...
}
```

使用 [hash table](/docs/CS/DB/Redis/struct/hash.md) 和 zskiplist。

### zsetAdd

当往 Sorted Set 中插入数据时，zsetAdd 函数就会被调用。zsetAdd 函数会判定 Sorted Set 采用的是 ziplist 还是 skiplist 的编码方式。

zsetAdd 函数会先使用哈希表的 dictFind 函数，查找要插入的元素是否存在。
如果不存在，就直接调用跳表元素插入函数 zslInsert 和哈希表元素插入函数 dictAdd，将新元素分别插入到跳表和哈希表中。

> [!TIP]
>
> Redis 并没有把哈希表的操作嵌入到跳表本身的操作函数中，而是在 zsetAdd 函数中依次执行以上两个函数。这样设计的好处是保持了跳表和哈希表两者操作的独立性。

如果 zsetAdd 函数通过 dictFind 函数发现要插入的元素已经存在，那么 zsetAdd 函数会判断是否要增加元素的权重值。如果权重值发生了变化，zsetAdd 函数就会调用 zslUpdateScore 函数，更新跳表中的元素权重值。紧接着，zsetAdd 函数会把哈希表中该元素（对应哈希表中的 key）的 value 指向跳表结点中的权重值，这样一来，哈希表中元素的权重值就可以保持最新值了。

```c
int zsetAdd(robj *zobj, double score, sds ele, int in_flags, int *out_flags, double *newscore) {
    // ... 实现逻辑 ...
}
```

## zsetConvertToZiplistIfNeeded

由 geo 或 ZUNION、ZINTER、ZDIFF、ZUNIONSTORE、ZINTERSTORE、ZDIFFSTORE 调用。

```c
// t_zset.c
/* 将有序集合对象转换为 ziplist，如果它还不是 ziplist
 * 且元素数量和最大元素大小在预期范围内。 */
void zsetConvertToZiplistIfNeeded(robj *zobj, size_t maxelelen) {
    if (zobj->encoding == OBJ_ENCODING_ZIPLIST) return;
    zset *zset = zobj->ptr;

    if (zset->zsl->length <= server.zset_max_ziplist_entries &&
        maxelelen <= server.zset_max_ziplist_value)
            zsetConvert(zobj,OBJ_ENCODING_ZIPLIST);
}
```

在 redis.conf 中：

zset 默认使用 ziplist。

**删除节点时不转换回 ziplist**。

```conf
# 与哈希和列表类似，有序集合也经过特殊编码以节省大量空间。
# 此编码仅在有序集合的长度和元素低于以下限制时使用：
zset-max-ziplist-entries 128
zset-max-ziplist-value 64
```

## 总结

- zset 由哈希表和跳表组成。
- zset 默认使用 ziplist，然后使用 skiplist 且不再转换回来。
- zset 按 score 和 ele(sds) 比较。

在面对需要展示最新列表、排行榜等场景时，如果数据更新频繁或者需要分页显示，建议优先考虑使用 Sorted Set。

延迟队列的常见使用场景有以下几种：

1. 超过 30 分钟未支付的订单，将会被取消。
2. 外卖商家超过 5 分钟未接单的订单，将会被取消。
3. 在平台注册但 30 天内未登录的用户，发短信提醒。

等类似的应用场景，都可以使用延迟队列来实现。

Redis 是通过有序集合（ZSet）的方式来实现延迟消息队列的，ZSet 有一个 Score 属性可以用来存储延迟执行的时间。

**优点**

1. 灵活方便，Redis 是互联网公司的标配，无需额外搭建相关环境。
2. 可进行消息持久化，大大提高了延迟队列的可靠性。
3. 分布式支持，不像 JDK 自身的 DelayQueue。
4. 高可用性，利用 Redis 本身高可用方案，增加了系统健壮性。

**缺点**

需要使用无限循环的方式来执行任务检查，会消耗少量的系统资源。

## 链接

- [Redis 数据结构](/docs/CS/DB/Redis/struct/struct.md?id=Sorted-sets)
