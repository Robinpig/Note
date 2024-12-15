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

Radix Tree save id, and listpack save message.

```c
typedef struct stream {
    rax *rax;               /* The radix tree holding the stream. */
    uint64_t length;        /* Number of elements inside this stream. */
    streamID last_id;       /* Zero if there are yet no items. */
    rax *cgroups;           /* Consumer groups dictionary: name -> streamCG */
} stream;
```

### streamID

```c
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

## Links

- [Redis Struct](/docs/CS/DB/Redis/struct/struct.md)

## References

1. [Rax, an ANSI C radix tree implementation](https://github.com/antirez/rax)
