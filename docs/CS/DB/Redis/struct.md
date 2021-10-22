## Introduction




As you can see in the client structure above, arguments in a command
are described as `robj` structures. The following is the full `robj`
structure, which defines a *Redis object*:

```c
typedef struct redisObject {
    unsigned type:4;
    unsigned encoding:4;
    unsigned lru:LRU_BITS; /* LRU time (relative to global lru_clock) or
                            * LFU data (least significant 8 bits frequency
                            * and most significant 16 bits access time). */
    int refcount;
    void *ptr;
} robj;
```

Basically this structure can represent all the basic Redis data types like strings, lists, sets, sorted sets and so forth. The interesting thing is that it has a `type` field, so that it is possible to know what type a given object has, and a `refcount`, so that the same object can be referenced in multiple places without allocating it multiple times. Finally the `ptr` field points to the actual representation of the object, which might vary even for the same type, depending on the `encoding` used.

Redis objects are used extensively in the Redis internals, however in order to avoid the overhead of indirect accesses, recently in many places we just use plain dynamic strings not wrapped inside a Redis object.

## Data Types
![](./images/struct.png)

object
- [string](/docs/CS/DB/Redis/SDS.md)
- [list](/docs/CS/DB/Redis/list.md)
- [set](/docs/CS/DB/Redis/set.md)
- [zset](/docs/CS/DB/Redis/zset.md)
- [hash](/docs/CS/DB/Redis/hash.md)
- [Stream](/docs/CS/DB/Redis/Stream.md)
- [geo](/docs/CS/DB/Redis/geo.md)
- [HyperLogLog](/docs/CS/DB/Redis/HyperLogLog.md)

```c
// server.h
/* A redis object, that is a type able to hold a string / list / set */

/* The actual Redis Object */
#define OBJ_STRING 0    /* String object. */
#define OBJ_LIST 1      /* List object. */
#define OBJ_SET 2       /* Set object. */
#define OBJ_ZSET 3      /* Sorted set object. */
#define OBJ_HASH 4      /* Hash object. */

/* The "module" object type is a special one that signals that the object
 * is one directly managed by a Redis module. In this case the value points
 * to a moduleValue struct, which contains the object value (which is only
 * handled by the module itself) and the RedisModuleType struct which lists
 * function pointers in order to serialize, deserialize, AOF-rewrite and
 * free the object.
 *
 * Inside the RDB file, module types are encoded as OBJ_MODULE followed
 * by a 64 bit module type ID, which has a 54 bits module-specific signature
 * in order to dispatch the loading to the right module, plus a 10 bits
 * encoding version. */
#define OBJ_MODULE 5    /* Module object. */
#define OBJ_STREAM 6    /* Stream object. */
```


struct
- [int embstr raw](/docs/CS/DB/Redis/SDS.md?id=type)
- [hashtable](/docs/CS/DB/Redis/hash.md)
- [ziplist](/docs/CS/DB/Redis/zset.md?id=ziplist)
- [intset](/docs/CS/DB/Redis/set.md?id=intset)
- [skiplist](/docs/CS/DB/Redis/zset.md?id=skiplist)
- [ziplist](/docs/CS/DB/Redis/list.md?id=quciklist)
- [Stream](/docs/CS/DB/Redis/Stream.md?id=rax)

```c
/* Objects encoding. Some kind of objects like Strings and Hashes can be
 * internally represented in multiple ways. The 'encoding' field of the object
 * is set to one of this fields for this object. */
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


### Redis keys

Redis keys are binary safe, this means that you can use any binary sequence as a key, from a string like "foo" to the content of a JPEG file. 

The empty string is also a valid key.

A few other rules about keys:

- **Very long keys are not a good idea**. For instance a key of 1024 bytes is a bad idea not only memory-wise, but also because the lookup of the key in the dataset may require several costly key-comparisons. Even when the task at hand is to match the existence of a large value, hashing it (for example with SHA1) is a better idea, especially from the perspective of memory and bandwidth.
- **Very short keys are often not a good idea**. There is little point in writing "u1000flw" as a key if you can instead write "`user:1000:followers`". The latter is more readable and the added space is minor compared to the space used by the key object itself and the value object. While short keys will obviously consume a bit less memory, your job is to find the right balance.
- **Try to stick with a schema.** For instance "object-type:id" is a good idea, as in "user:1000". Dots or dashes are often used for multi-word fields, as in "`comment:1234:reply.to`" or "`comment:1234:reply-to`".
- The maximum allowed key size is **512 MB**.

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

### tips
- use SCAN rather than KEYS（block）to get all keys
- use UNLINK rather than DEL when delete big data
- check if EXISTS before RENAME

## Data Features

### bitmap
[Bitmaps](/docs/CS/DB/Redis/bitmap.md) can be used in lieu of strings to save memory space under some circumstances.

### expiration keys

### sort
Sometimes we may need to get a sorted copy of a Redis list or set in some order, or sort elements in a Redis sorted set by an order other than scores. Redis provides a convenient command called SORT for this purpose. 

### pipeline


### Transaction

support isolation and consistency, and support durability when use AOF and appendfsync is always

It's important to note that **even when a command fails, all the other commands in the queue are processed** – Redis will *not* stop the processing of commands.

#### Why Redis does not support roll backs?

- Redis commands can fail only if called with a wrong syntax (and the problem is not detectable during the command queueing), or against keys holding the wrong data type: this means that in practical terms a failing command is the result of a **programming errors**, and a kind of error that is very likely to be detected during development, and not in production.
- Redis is internally simplified and faster because it does not need the ability to roll back.

**In general the roll back does not save you from programming errors**.



#### Optimistic locking using check-and-set

[WATCH](https://redis.io/commands/watch) is used to provide a check-and-set (CAS) behavior to Redis transactions.

`WATCH`ed keys are monitored in order to detect changes against them. If at least one watched key is modified before the [EXEC](https://redis.io/commands/exec) command, the whole transaction aborts, and [EXEC](https://redis.io/commands/exec) returns a [Null reply](https://redis.io/topics/protocol#nil-reply) to notify that the transaction failed.

We just have to repeat the operation hoping this time we'll not get a new race. This form of locking is called *optimistic locking* and is a very powerful form of locking.



A [Redis script](/docs/CS/DB/Redis/struct.md?id=lua-scripts) is transactional by definition, so everything you can do with a Redis transaction, you can also do with a script, and usually the script will be both simpler and faster.

### PubSub
[Publish-Subscribe (PubSub)](/docs/CS/DB/Redis/PubSub.md) is a classic messaging pattern which has a long history, as far back as 1987 according to Wikipedia.

### Lua scripts
[Lua](/docs/CS/DB/Redis/Lua.md), a lightweight script language, has been introduced into Redis since version 2.6.


