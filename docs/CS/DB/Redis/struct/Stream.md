## 简介

Stream 是 Redis 5.0 中引入的新数据类型，它以更抽象的方式建模日志数据结构。
然而日志的本质仍然完好：像通常以追加模式打开的文件实现的日志文件一样，Redis Streams 主要是追加型数据结构。
至少在概念上是这样，因为作为内存中表示的抽象数据类型，Redis Streams 实现了强大的操作来克服日志文件的限制。

Redis streams 实现了额外的非强制功能：一组阻塞操作，允许消费者等待生产者添加到流中的新数据，此外还有一个名为**消费者组**的概念（允许客户端组协作消费同一消息流的不同部分）。

消费者组就像一个从流中获取数据的*伪消费者*，实际服务于多个消费者，提供特定保证：

1. 每条消息都提供给不同的消费者，因此同一消息不可能被分发给多个消费者。
2. 在消费者组内，消费者通过名称标识，名称是实现消费者的客户端选择的区分大小写的字符串。
   这意味着即使在断开连接后，流消费者组仍保留所有状态，因为客户端将再次声明为同一消费者。
   然而，这也意味着客户端需要提供唯一标识符。
3. 每个消费者组都有*从未消费过的第一个 ID* 的概念，因此当消费者请求新消息时，它可以只提供之前未传递过的消息。
4. 然而，消费消息需要使用特定命令进行显式确认。Redis 将确认解释为：此消息已正确处理，因此可以从消费者组中移除。
5. 消费者组跟踪所有当前待处理的消息，即已传递给消费者组中某个消费者但尚未确认处理完成的消息。
   凭借此功能，当访问流的历史消息时，每个消费者*只会看到已传递给它的消息*。

## 与 Kafka 分区的区别

Redis streams 中的消费者组在某些方面类似于 Kafka 基于分区的消费者组，但 Redis streams 实际上非常不同。
分区只是*逻辑上*的，消息只是放入单个 Redis 键中，因此不同客户端的服务方式取决于谁准备好处理新消息，而不是客户端从哪个分区读取。
例如，如果消费者 C3 在某些时候永久失败，Redis 将继续向 C1 和 C2 提供所有到达的新消息，就像现在只有两个*逻辑*分区一样。

同样，如果某个消费者处理消息的速度远快于其他消费者，该消费者在同一时间单位内将成比例地接收更多消息。
这是可能的，因为 Redis 显式跟踪所有未确认的消息，并记住谁收到了哪条消息以及从未传递给任何消费者的第一个消息的 ID。

然而，这也意味着在 Redis 中，如果确实希望将同一流中的消息分区到多个 Redis 实例，必须使用多个键和某些分片系统，如 Redis Cluster 或其他特定于应用程序的分片系统。
单个 Redis 流不会自动分区到多个实例。

可以示意性地描述如下：

* 如果使用 1 个流对应 1 个消费者，则按顺序处理消息。
* 如果使用 N 个流对应 N 个消费者，使得只有特定消费者访问 N 个流的子集，则可以扩展上述 1 流 1 消费者的模型。
* 如果使用 1 个流对应 N 个消费者，则是对 N 个消费者进行负载均衡，但相同逻辑项的消息可能被乱序消费，因为某个消费者可能比另一个消费者处理消息 4 更快。

因此，Kafka 分区更类似于使用 N 个不同的 Redis 键，而 Redis 消费者组是将来自给定流的消息负载均衡到 N 个不同消费者的服务器端系统。

## 持久化

Stream 与任何其他 Redis 数据结构一样，异步复制到副本并持久化到 AOF 和 RDB 文件中。
然而，不太明显的是，消费者组的完整状态也会传播到 AOF、RDB 和副本，因此如果主库上有一条待处理消息，副本也会有相同的信息。
同样，重启后 AOF 将恢复消费者组的状态。

但需要注意的是，Redis streams 和消费者组使用 Redis 默认复制进行持久化和复制，因此：

* 如果应用程序中消息的持久性很重要，则必须使用强 fsync 策略的 AOF。
* 默认情况下，异步复制不能保证 `XADD` 命令或消费者组状态更改被复制：故障转移后，根据副本从主库接收数据的能力，可能会丢失一些数据。
* `WAIT` 命令可用于强制将更改传播到一组副本。
  但注意，虽然这样数据丢失的可能性非常低，Sentinel 或 Redis Cluster 执行的 Redis 故障转移过程仅进行*尽力而为*的检查来故障转移到最新副本，
  且在特定故障条件下可能提升缺少部分数据的副本。

因此，在使用 Redis streams 和消费者组设计应用程序时，请确保了解应用程序在故障期间应具有的语义属性，并相应地进行配置，评估是否对用例足够安全。

## 零长度流

Streams 与其他 Redis 数据结构之间的一个区别是，当其他数据结构不再有元素时，作为调用删除元素的命令的副作用，键本身将被删除。
例如，当调用 `ZREM` 删除有序集合中的最后一个元素时，该有序集合将被完全删除。
另一方面，允许 Streams 保持零元素，无论是使用计数为零的 **MAXLEN** 选项（`XADD` 和 `XTRIM` 命令）的结果，还是因为调用了 `XDEL`。

存在这种不对称性的原因是 Streams 可能有关联的消费者组，并且我们不希望仅仅因为流中不再有任何项就丢失消费者组定义的状态。
目前，即使没有关联的消费者组，流也不会被删除。

为了充分节省内存空间，Stream 使用了两种内存友好的数据结构：listpack 和 Radix Tree。其中，消息 ID 是作为 Radix Tree 中的 key，消息具体数据是使用 listpack 保存，并作为 value 和消息 ID 一起保存到 Radix Tree 中。

每条消息都会有一个时间戳和序号组成的消息 ID，以及键值对组成的消息内容。而因为不同消息 ID 中的时间戳，通常会共享部分相同的前缀，如果采用诸如哈希表的结构来保存消息，每个消息 ID 都单独保存，容易造成空间浪费。因此，Stream 为了节省内存空间，采用了 Radix Tree 来保存消息 ID，同时使用 listpack 来保存消息本身的内容。

```c
typedef struct stream {
    rax *rax;               /* 保存流的基数树 */
    uint64_t length;        /* 此流中当前的元素数 */
    streamID last_id;       /* 如果还没有项目则为 0 */
    streamID first_id;      /* 第一个非墓碑条目，如果为空则为 0 */
    streamID max_deleted_entry_id;  /* 已删除的最大 ID */
    uint64_t entries_added; /* 所有时间添加的元素数 */
    rax *cgroups;           /* 消费者组字典：name -> streamCG */
} stream;

/* 流项目 ID：一个 128 位数字，由毫秒时间和序号计数器组成。
在同一毫秒内生成的时间戳（或如果时钟向后跳，则在过去毫秒中生成的 ID）
将使用最新生成 ID 的毫秒时间和递增的序号。 */
typedef struct streamID {
    uint64_t ms;        /* Unix 时间（毫秒） */
    uint64_t seq;       /* 序号 */
} streamID;
```

```c
/* 消费者组 */
typedef struct streamCG {
    streamID last_id;       /* 此组最后传递（未确认）的 ID。
                               将请求更多消息的消费者将获得大于此值的 ID。 */
    long long entries_read; /* 在理想世界中（CG 从 0-0 开始，无删除，无
                               XGROUP SETID 等），这是组读取的总数。
                               在现实世界中，此值背后的推理详见
                               streamEstimateDistanceFromFirstEverEntry() 顶部的注释。 */
    rax *pel;               /* 待处理条目列表。这是一个基数树，
                               包含已传递给消费者（未使用 NOACK 选项）
                               但尚未确认处理完成的每条消息。
                               基数树的键是 64 位大端数字的 ID，
                               关联的值是 streamNACK 结构。*/
    rax *consumers;         /* 按名称表示消费者的基数树，
                               及其以 streamConsumer 结构形式的表现。 */
} streamCG;

/* 消费者组中的特定消费者 */
typedef struct streamConsumer {
    mstime_t seen_time;         /* 此消费者最后活跃的时间 */
    sds name;                   /* 消费者名称。这是消费者在消费者组协议中
                                   被识别的方式。区分大小写。 */
    rax *pel;                   /* 消费者特定的待处理条目列表：
                                   所有已传递给此消费者但尚未确认的待处理消息。
                                   键是大端消息 ID，值是在消费者组结构
                                   的 "pel" 中引用的相同 streamNACK 结构，
                                   因此值是共享的。 */
} streamConsumer;
```

```c
// t-stream.c
/* 创建一个新的流数据结构 */
stream *streamNew(void) {
    stream *s = zmalloc(sizeof(*s));
    s->rax = raxNew();
    s->length = 0;
    s->last_id.ms = 0;
    s->last_id.seq = 0;
    s->cgroups = NULL; /* 按需创建以在未使用时节省内存 */
    return s;
}
```

## Rax

基数树的表示形式，如本文件中实现的，包含字符串 "foo"、"foobar" 和 "footer" 在插入每个单词后的状态。
当节点在基数树中表示一个键时，我们用 [] 括起来，否则用 () 括起来。

Redis 使用的是压缩前缀树（Compact Prefix Tree）。

这是标准表示：

```c
/* 
 *
 *              (f) ""
 *                \
 *                (o) "f"
 *                  \
 *                  (o) "fo"
 *                    \
 *                  [t   b] "foo"
 *                  /     \
 *         "foot" (e)     (a) "foob"
 *                /         \
 *      "foote" (r)         (r) "fooba"
 *              /             \
 *    "footer" []             [] "foobar"
 *
 */
```

流底层编码：一个由 listpack 构成的`基数树`。

```c
typedef struct rax {
    raxNode *head;
    uint64_t numele;
    uint64_t numnodes;
} rax;
```

raxNode：

```c
typedef struct raxNode {
    uint32_t iskey:1;     /* 此节点是否包含键？ */
    uint32_t isnull:1;    /* 关联值为 NULL（不存储） */
    uint32_t iscompr:1;   /* 节点已压缩 */
    uint32_t size:29;     /* 子节点数或压缩字符串长度 */
   
    unsigned char data[];
} raxNode;
```

数据布局如下：

如果节点未压缩，则有 'size' 字节，每个子字符一个字节，以及 'size' 个 raxNode 指针，指向每个子节点。
注意，字符不存储在子节点中，而是存储在父节点的边上：

> [header iscompr=0][abc][a-ptr][b-ptr][c-ptr](value-ptr?)

如果节点已压缩（iscompr 位为 1），则该节点有 1 个子节点。
在这种情况下，'size' 字节的字符串立即存储在数据部分的开头，表示一系列连续连接的节点，其中只有序列中的最后一个实际表示为节点，并由当前压缩节点指向。

> [header iscompr=1][xyz][z-ptr](value-ptr?)

压缩和未压缩的节点都可以在基数树的任何级别表示具有关联数据的键（不仅是终端节点）。

如果节点具有关联的键（iskey=1）且不为 NULL（isnull=0），则在指向子节点的 raxNode 指针之后，存在一个额外的值指针（如上述表示中的 "value-ptr" 字段所示）。

### raxNew

分配一个新的 rax 并返回其指针。内存不足时返回 NULL。

```c
// rax.c
rax *raxNew(void) {
    rax *rax = rax_malloc(sizeof(*rax));
    if (rax == NULL) return NULL;
    rax->numele = 0;
    rax->numnodes = 1;
    rax->head = raxNewNode(0,0);
    if (rax->head == NULL) {
        rax_free(rax);
        return NULL;
    } else {
        return rax;
    }
}
```

分配一个新的未压缩节点，具有指定数量的子节点。
如果 datafiled 为 true，则分配足够大以容纳关联数据指针的大小。

返回新节点指针。内存不足时返回 NULL。

```c
raxNode *raxNewNode(size_t children, int datafield) {
    size_t nodesize = sizeof(raxNode)+children+raxPadding(children)+
                      sizeof(raxNode*)*children;
    if (datafield) nodesize += sizeof(void*);
    raxNode *node = rax_malloc(nodesize);
    if (node == NULL) return NULL;
    node->iskey = 0;
    node->isnull = 0;
    node->iscompr = 0;
    node->size = children;
    return node;
}
```

## 之前的实现

消息队列的另外两种实现方式 List 和 ZSet，它们都是利用自身方法，先把数据放到队列里，再使用无限循环读取队列中的消息，以实现消息队列的功能，相比发布订阅模式本文介绍的这两种方式的优势是支持持久化，当然它们各自都存在一些问题。

List 不能支持订阅，不能重复消费。

ZSet 优点：
- 支持消息持久化。
- 相比于 List 查询更方便，ZSet 可以利用 score 属性很方便地完成检索，而 List 则需要遍历整个元素才能检索到某个值。

ZSet 缺点：
- ZSet 不能存储相同元素的值，也就是如果有消息是重复的，那么只能插入一条信息在有序集合中。
- ZSet 是根据 score 值排序的，不能像 List 一样，按照插入顺序来排序。
- ZSet 没有向 List 的 brpop 那样的阻塞弹出的功能。

并且以上三种方式在实现消息队列时，只能存储单 value 值，也就是如果你要存储一个对象的情况下，必须先序列化成 JSON 字符串，在读取之后还要反序列化成对象才行。

## 链接

- [Redis 数据结构](/docs/CS/DB/Redis/struct/struct.md)

## 参考

1. [Rax, an ANSI C radix tree implementation](https://github.com/antirez/rax)
