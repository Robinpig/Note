## Introduction

The Stream is a new data type introduced with Redis 5.0, which models a log data structure in a more abstract way.
However the essence of a log is still intact: like a log file, often implemented as a file open in append-only mode, Redis Streams are primarily an append-only data structure.
At least conceptually, because being an abstract data type represented in memory, Redis Streams implement powerful operations to overcome the limitations of a log file.

Redis streams implement additional, non-mandatory features: a set of blocking operations allowing consumers to wait for new data added to a stream by producers, and in addition to that a concept called **Consumer Groups**(allow a group of clients to cooperate in consuming a different portion of the same stream of messages).

A consumer group is like a *pseudo consumer* that gets data from a stream, and actually serves multiple consumers, providing certain guarantees:

1. Each message is served to a different consumer so that it is not possible that the same message will be delivered to multiple consumers.
2. Consumers are identified, within a consumer group, by a name, which is a case-sensitive string that the clients implementing consumers must choose.
   This means that even after a disconnect, the stream consumer group retains all the state, since the client will claim again to be the same consumer.
   However, this also means that it is up to the client to provide a unique identifier.
3. Each consumer group has the concept of the *first ID never consumed* so that, when a consumer asks for new messages, it can provide just messages that were not previously delivered.
4. Consuming a message, however, requires an explicit acknowledgment using a specific command. Redis interprets the acknowledgment as: this message was correctly processed so it can be evicted from the consumer group.
5. A consumer group tracks all the messages that are currently pending, that is, messages that were delivered to some consumer of the consumer group, but are yet to be acknowledged as processed.
   Thanks to this feature, when accessing the message history of a stream, each consumer  *will only see messages that were delivered to it* .

## Differences with Kafka (TM) partitions

Consumer groups in Redis streams may resemble in some way Kafka (TM) partitioning-based consumer groups, however note that Redis streams are, in practical terms, very different.
The partitions are only *logical* and the messages are just put into a single Redis key, so the way the different clients are served is based on who is ready to process new messages, and not from which partition clients are reading.
For instance, if the consumer C3 at some point fails permanently, Redis will continue to serve C1 and C2 all the new messages arriving, as if now there are only two *logical* partitions.

Similarly, if a given consumer is much faster at processing messages than the other consumers, this consumer will receive proportionally more messages in the same unit of time.
This is possible since Redis tracks all the unacknowledged messages explicitly, and remembers who received which message and the ID of the first message never delivered to any consumer.

However, this also means that in Redis if you really want to partition messages in the same stream into multiple Redis instances, you have to use multiple keys and some sharding system such as Redis Cluster or some other application-specific sharding system.
A single Redis stream is not automatically partitioned to multiple instances.

We could say that schematically the following is true:

* If you use 1 stream -> 1 consumer, you are processing messages in order.
* If you use N streams with N consumers, so that only a given consumer hits a subset of the N streams, you can scale the above model of 1 stream -> 1 consumer.
* If you use 1 stream -> N consumers, you are load balancing to N consumers, however in that case, messages about the same logical item may be consumed out of order, because a given consumer may process message 3 faster than another consumer is processing message 4.

So basically Kafka partitions are more similar to using N different Redis keys, while Redis consumer groups are a server-side load balancing system of messages from a given stream to N different consumers.

## Persistence

A Stream, like any other Redis data structure, is asynchronously replicated to replicas and persisted into AOF and RDB files.
However what may not be so obvious is that also the consumer groups full state is propagated to AOF, RDB and replicas, so if a message is pending in the master, also the replica will have the same information.
Similarly, after a restart, the AOF will restore the consumer groups' state.

However note that Redis streams and consumer groups are persisted and replicated using the Redis default replication, so:

* AOF must be used with a strong fsync policy if persistence of messages is important in your application.
* By default the asynchronous replication will not guarantee that `XADD` commands or consumer groups state changes are replicated: after a failover something can be missing depending on the ability of replicas to receive the data from the master.
* The `WAIT` command may be used in order to force the propagation of the changes to a set of replicas.
  However note that while this makes it very unlikely that data is lost, the Redis failover process as operated by Sentinel or Redis Cluster performs only a *best effort* check to failover to the replica which is the most updated,
  and under certain specific failure conditions may promote a replica that lacks some data.

So when designing an application using Redis streams and consumer groups, make sure to understand the semantical properties your application should have during failures, and configure things accordingly, evaluating whether it is safe enough for your use case.

## Zero length streams

A difference between streams and other Redis data structures is that when the other data structures no longer have any elements, as a side effect of calling commands that remove elements, the key itself will be removed.
So for instance, a sorted set will be completely removed when a call to `ZREM` will remove the last element in the sorted set.
Streams, on the other hand, are allowed to stay at zero elements, both as a result of using a **MAXLEN** option with a count of zero (`XADD` and `XTRIM` commands), or because `XDEL` was called.

The reason why such an asymmetry exists is because Streams may have associated consumer groups, and we do not want to lose the state that the consumer groups defined just because there are no longer any items in the stream.
Currently the stream is not deleted even when it has no associated consumer groups.



为了充分节省内存空间，Stream 使用了两种内存友好的数据结构：listpack 和 Radix Tree。其中，消息 ID 是作为 Radix Tree 中的 key，消息具体数据是使用 listpack 保存，并作为 value 和消息 ID 一起保存到 Radix Tree 中

每条消息都会有一个时间戳和序号组成的消息 ID，以及键值对组成的消息内容。而因为不同消息 ID 中的时间戳，通常会共享部分相同的前缀，如果采用诸如哈希表的结构来保存消息，每个消息 ID 都单独保存，容易造成空间浪费。因此，Stream 为了节省内存空间，采用了 Radix Tree 来保存消息 ID，同时使用 listpack 来保存消息本身的内容。

```c
typedef struct stream {
    rax *rax;               /* The radix tree holding the stream. */
    uint64_t length;        /* Current number of elements inside this stream. */
    streamID last_id;       /* Zero if there are yet no items. */
    streamID first_id;      /* The first non-tombstone entry, zero if empty. */
    streamID max_deleted_entry_id;  /* The maximal ID that was deleted. */
    uint64_t entries_added; /* All time count of elements added. */
    rax *cgroups;           /* Consumer groups dictionary: name -> streamCG */
} stream;

/* Stream item ID: a 128 bit number composed of a milliseconds time and
 * a sequence counter. IDs generated in the same millisecond (or in a past
 * millisecond if the clock jumped backward) will use the millisecond time
 * of the latest generated ID and an incremented sequence. */
typedef struct streamID {
    uint64_t ms;        /* Unix time in milliseconds. */
    uint64_t seq;       /* Sequence number. */
} streamID;
```





```c

/* Consumer group. */
typedef struct streamCG {
    streamID last_id;       /* Last delivered (not acknowledged) ID for this
                               group. Consumers that will just ask for more
                               messages will served with IDs > than this. */
    long long entries_read; /* In a perfect world (CG starts at 0-0, no dels, no
                               XGROUP SETID, ...), this is the total number of
                               group reads. In the real world, the reasoning behind
                               this value is detailed at the top comment of
                               streamEstimateDistanceFromFirstEverEntry(). */
    rax *pel;               /* Pending entries list. This is a radix tree that
                               has every message delivered to consumers (without
                               the NOACK option) that was yet not acknowledged
                               as processed. The key of the radix tree is the
                               ID as a 64 bit big endian number, while the
                               associated value is a streamNACK structure.*/
    rax *consumers;         /* A radix tree representing the consumers by name
                               and their associated representation in the form
                               of streamConsumer structures. */
} streamCG;

/* A specific consumer in a consumer group.  */
typedef struct streamConsumer {
    mstime_t seen_time;         /* Last time this consumer was active. */
    sds name;                   /* Consumer name. This is how the consumer
                                   will be identified in the consumer group
                                   protocol. Case sensitive. */
    rax *pel;                   /* Consumer specific pending entries list: all
                                   the pending messages delivered to this
                                   consumer not yet acknowledged. Keys are
                                   big endian message IDs, while values are
                                   the same streamNACK structure referenced
                                   in the "pel" of the consumer group structure
                                   itself, so the value is shared. */
} streamConsumer;
```





```c
// t-stream.c
/* Create a new stream data structure. */
stream *streamNew(void) {
    stream *s = zmalloc(sizeof(*s));
    s->rax = raxNew();
    s->length = 0;
    s->last_id.ms = 0;
    s->last_id.seq = 0;
    s->cgroups = NULL; /* Created on demand to save memory when not used. */
    return s;
}
```











## Rax

Representation of a radix tree as implemented in this file, that contains the strings "foo", "foobar" and "footer" after the insertion of each word.
When the node represents a key inside the radix tree, we write it between [], otherwise it is written between ().

Redis使用的是Compact Prefix Tree

This is the vanilla representation:

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

Low level stream encoding: a `radix tree` of `listpacks`.

```c
typedef struct rax {
    raxNode *head;
    uint64_t numele;
    uint64_t numnodes;
} rax;
```

raxNode

```c
typedef struct raxNode {
    uint32_t iskey:1;     /* Does this node contain a key? */
    uint32_t isnull:1;    /* Associated value is NULL (don't store it). */
    uint32_t iscompr:1;   /* Node is compressed. */
    uint32_t size:29;     /* Number of children, or compressed string len. */
   
    unsigned char data[];
} raxNode;
```

Data layout is as follows:

If node is not compressed we have 'size' bytes, one for each children
character, and 'size' raxNode pointers, point to each child node.
Note how the character is not stored in the children but in the
edge of the parents:

> [header iscompr=0][abc][a-ptr][b-ptr][c-ptr](value-ptr?)

if node is compressed (iscompr bit is 1) the node has 1 children.
In that case the 'size' bytes of the string stored immediately at
the start of the data section, represent a sequence of successive
nodes linked one after the other, for which only the last one in
the sequence is actually represented as a node, and pointed to by
the current compressed node.

> [header iscompr=1][xyz][z-ptr](value-ptr?)

Both compressed and not compressed nodes can represent a key
with associated data in the radix tree at any level (not just terminal
nodes).

If the node has an associated key (iskey=1) and is not NULL
(isnull=0), then after the raxNode pointers pointing to the
children, an additional value pointer is present (as you can see
in the representation above as "value-ptr" field).

### raxNew

Allocate a new rax and return its pointer. On out of memory the function returns NULL.

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

Allocate a new non compressed node with the specified number of children.
If datafiled is true, the allocation is made large enough to hold the associated data pointer.

Returns the new node pointer. On out of memory NULL is returned.

```
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



## previous

消息队列的另外两种实现方式 List 和 ZSet，它们都是利用自身方法，先把数据放到队列里，在使用无限循环读取队列中的消息，以实现消息队列的功能，相比发布订阅模式本文介绍的这两种方式的优势是支持持久化，当然它们各自都存在一些问题

List 不能支持订阅 不能重复消费



ZSet 优点：

- 支持消息持久化；
- 相比于 List 查询更方便，ZSet 可以利用 score 属性很方便的完成检索，而 List 则需要遍历整个元素才能检索到某个值。

ZSet 缺点：

- ZSet 不能存储相同元素的值，也就是如果有消息是重复的，那么只能插入一条信息在有序集合中；
- ZSet 是根据 score 值排序的，不能像 List 一样，按照插入顺序来排序；
- ZSet 没有向 List 的 brpop 那样的阻塞弹出的功能



并且以上三种方式在实现消息队列时，只能存储单 value 值，也就是如果你要存储一个对象的情况下，必须先序列化成 JSON 字符串，在读取之后还要反序列化成对象才行







## Links

- [Redis Struct](/docs/CS/DB/Redis/struct/struct.md)

## References

1. [Rax, an ANSI C radix tree implementation](https://github.com/antirez/rax)
