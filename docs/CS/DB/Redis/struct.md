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



```c
/* Objects encoding. Some kind of objects like Strings and Hashes can be
 * internally represented in multiple ways. The 'encoding' field of the object
 * is set to one of this fields for this object. */
#define OBJ_ENCODING_RAW 0     /* Raw representation */
#define OBJ_ENCODING_INT 1     /* Encoded as integer */
#define OBJ_ENCODING_HT 2      /* Encoded as hash table */
#define OBJ_ENCODING_ZIPMAP 3  /* Encoded as zipmap */
#define OBJ_ENCODING_LINKEDLIST 4 /* No longer used: old list encoding. */
#define OBJ_ENCODING_ZIPLIST 5 /* Encoded as ziplist */
#define OBJ_ENCODING_INTSET 6  /* Encoded as intset */
#define OBJ_ENCODING_SKIPLIST 7  /* Encoded as skiplist */
#define OBJ_ENCODING_EMBSTR 8  /* Embedded sds string encoding */
#define OBJ_ENCODING_QUICKLIST 9 /* Encoded as linked list of ziplists */
#define OBJ_ENCODING_STREAM 10 /* Encoded as a radix tree of listpacks */
```

object
- [string](/docs/CS/DB/Redis/SDS.md)
- [hash](/docs/CS/DB/Redis/hash.md)
- [list](/docs/CS/DB/Redis/list.md)
- [set](/docs/CS/DB/Redis/set.md)
- [zset](/docs/CS/DB/Redis/zset.md)


struct
- [sds](/docs/CS/DB/Redis/SDS.md)
- [dict](/docs/CS/DB/Redis/hash.md)
- [list](/docs/CS/DB/Redis/list.md)
- [intset](/docs/CS/DB/Redis/set.md?id=intset)
- [ziplist](/docs/CS/DB/Redis/zset.md?id=ziplist)
- [skiplist](/docs/CS/DB/Redis/zset.md?id=skiplist)
- [rax](/docs/CS/DB/Redis/Stream.md?id=rax)






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

## string

### example
counter/limiter
cache (shared sessions)

## list

blocking queue
 lpush + brpop



## hash

## set
tags
combine


## zset

sorted-set



## bitmap

bitcount

bitpos

bitfield KEY [GET type offset] [SET type offset value] [INCRBY type offset increment] [OVERFLOW WRAP|SAT|FAIL]

- wrap cycle value
- sat keep the max/min value
- fail return fail and do nothing

## HLL