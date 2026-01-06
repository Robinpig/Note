## Introduction

对于 Redis 键值数据库来说，Hash 表既是键值对中的一种值类型，
同时，Redis 也使用一个全局 Hash 表来保存所有的键值对，从而既满足应用存取 Hash 结构数据需求，又能提供快速查询功能

[redisDb](/docs/CS/DB/Redis/redisDb.md) also a hashtable

redis command table



哈希字典的典型使用场景如下：

- 商品购物车，购物车非常适合用哈希字典表示，使用人员唯一编号作为字典的 key，value 值可以存储商品的 id 和数量等信息；
- 存储用户的属性信息，使用人员唯一编号作为字典的 key，value 值为属性字段和对应的值；
- 存储文章详情页信息等。







在实际应用 Hash 表时，当数据量不断增加，它的性能就经常会受到**哈希冲突**和 **rehash 开销**的影响

针对哈希冲突，Redis 采用了**链式哈希**，在不扩容哈希表的前提下，将具有相同哈希值的数据链接起来，以便这些数据在表中仍然可以被查询到；对于 rehash 开销，Redis 实现了**渐进式 rehash 设计**，进而缓解了 rehash 操作带来的额外开销对系统的性能影响



Redis 准备了两个哈希表，用于 rehash 时交替保存数据

在实际使用 Hash 表时，Redis 又在 dict.h 文件中，定义了一个 dict 结构体。这个结构体中有一个数组（ht[2]），包含了两个 Hash 表 ht[0]和 ht[1]





## Structures




rehashing not in progress if rehashidx == -1

```c

struct dict {
    dictType *type;

    dictEntry **ht_table[2];
    unsigned long ht_used[2];

    long rehashidx; /* rehashing not in progress if rehashidx == -1 */

    /* Keep small vars at end for optimal (minimal) struct padding */
    unsigned pauserehash : 15; /* If >0 rehashing is paused */

    unsigned useStoredKeyApi : 1; /* See comment of storedHashFunction above */
    signed char ht_size_exp[2]; /* exponent of size. (size = 1<<exp) */
    int16_t pauseAutoResize;  /* If >0 automatic resizing is disallowed (<0 indicates coding error) */
    void *metadata[];
};
```

在 dict.h 文件中，Hash 表被定义为一个二维数组 数组的每个元素是一个指向哈希项（dictEntry）的指针

Every dictionary has **two of this** as we implement **incremental rehashing**, for the old to the new table.

为了实现链式哈希， Redis 在每个 dictEntry 的结构设计中，除了包含指向键和值的指针，还包含了指向下一个哈希项的指针

在 dictEntry 结构体中，键值对的值是由一个**联合体 v** 定义的。这个联合体 v 中包含了指向实际值的指针 *val，还包含了无符号的 64 位整数、有符号的 64 位整数，以及 double 类的值 便于节省内存

```c
typedef struct dictEntry {
    void *key; // always string
    union {
        void *val;
        uint64_t u64;
        int64_t s64;
        double d;
    } v;
    struct dictEntry *next;
} dictEntry;
```

```c
typedef struct dictType {
    uint64_t (*hashFunction)(const void *key);
    void *(*keyDup)(void *privdata, const void *key);
    void *(*valDup)(void *privdata, const void *obj);
    int (*keyCompare)(void *privdata, const void *key1, const void *key2);
    void (*keyDestructor)(void *privdata, void *key);
    void (*valDestructor)(void *privdata, void *obj);
} dictType;
```



## Hash Function

在redis中hash使用的是 siphash 算法

Hash Function: times33

hash(i) = hash(i - 1) * 33 + str[i]

```c
// dict.c
uint64_t dictGenHashFunction(const void *key, int len) {
    return siphash(key,len,dict_hash_function_seed);
}

// siphash.c
uint64_t siphash(const uint8_t *in, const size_t inlen, const uint8_t *k) {
#ifndef UNALIGNED_LE_CPU
    uint64_t hash;
    uint8_t *out = (uint8_t*) &hash;
#endif
    uint64_t v0 = 0x736f6d6570736575ULL;
    uint64_t v1 = 0x646f72616e646f6dULL;
    uint64_t v2 = 0x6c7967656e657261ULL;
    uint64_t v3 = 0x7465646279746573ULL;
    uint64_t k0 = U8TO64_LE(k);
    uint64_t k1 = U8TO64_LE(k + 8);
    uint64_t m;
    const uint8_t *end = in + inlen - (inlen % sizeof(uint64_t));
    const int left = inlen & 7;
    uint64_t b = ((uint64_t)inlen) << 56;
    v3 ^= k1;
    v2 ^= k0;
    v1 ^= k1;
    v0 ^= k0;

    for (; in != end; in += 8) {
        m = U8TO64_LE(in);
        v3 ^= m;

        SIPROUND;

        v0 ^= m;
    }

    switch (left) {
    case 7: b |= ((uint64_t)in[6]) << 48; /* fall-thru */
    case 6: b |= ((uint64_t)in[5]) << 40; /* fall-thru */
    case 5: b |= ((uint64_t)in[4]) << 32; /* fall-thru */
    case 4: b |= ((uint64_t)in[3]) << 24; /* fall-thru */
    case 3: b |= ((uint64_t)in[2]) << 16; /* fall-thru */
    case 2: b |= ((uint64_t)in[1]) << 8; /* fall-thru */
    case 1: b |= ((uint64_t)in[0]); break;
    case 0: break;
    }

    v3 ^= b;

    SIPROUND;

    v0 ^= b;
    v2 ^= 0xff;

    SIPROUND;
    SIPROUND;

    b = v0 ^ v1 ^ v2 ^ v3;
#ifndef UNALIGNED_LE_CPU
    U64TO8_LE(out, b);
    return hash;
#else
    return b;
#endif
}
```

index -1

## hset

1. [lookupKeyWrite in db](/docs/CS/DB/Redis/redisDb.md?id=redisObject)
2. [createQuicklistObject](/docs/CS/DB/Redis/struct/list.mdlist.md?id=quicklistCreate)
3. [dbAdd](/docs/CS/DB/Redis/redisDb.md?id=add)
4. [hashTypeTryConversion](/docs/CS/DB/Redis/struct/hash.mdhash.md?id=hashTypeTryConversion)

```c
// server.c
void hsetCommand(client *c) {
    int i, created = 0;
    robj *o;

  	...

    if ((o = hashTypeLookupWriteOrCreate(c,c->argv[1])) == NULL) return;
    hashTypeTryConversion(o,c->argv,2,c->argc-1);

    for (i = 2; i < c->argc; i += 2)
        created += !hashTypeSet(o,c->argv[i]->ptr,c->argv[i+1]->ptr,HASH_SET_COPY);

    /* HMSET (deprecated) and HSET return value is different. */
    char *cmdname = c->argv[0]->ptr;
    if (cmdname[1] == 's' || cmdname[1] == 'S') {
        /* HSET */
        addReplyLongLong(c, created);
    } else {
        /* HMSET */
        addReply(c, shared.ok);
    }
    signalModifiedKey(c,c->db,c->argv[1]);
    notifyKeyspaceEvent(NOTIFY_HASH,"hset",c->argv[1],c->db->id);
    server.dirty += (c->argc - 2)/2;
}

// call lookupKeyWrite and createHashObject, dbAdd
robj *hashTypeLookupWriteOrCreate(client *c, robj *key) {
    robj *o = lookupKeyWrite(c->db,key);
    if (checkType(c,o,OBJ_HASH)) return NULL;

    if (o == NULL) {
        o = createHashObject();
        dbAdd(c->db,key,o);
    }
    return o;
}
```

### hashTypeTryConversion

encoding **LISTPACK or HT**

Check the length of a number of objects to see if we need to convert a listpack to a real hash.
Note that we only check string encoded objects as their string length can be queried in constant time.

```c
void hashTypeTryConversion(robj *o, robj **argv, int start, int end) {
    int i;

    if (o->encoding != OBJ_ENCODING_LISTPACK) return;

    for (i = start; i <= end; i++) {
        if (sdsEncodedObject(argv[i]) &&
            sdslen(argv[i]->ptr) > server.hash_max_listpack_value)
        {
            hashTypeConvert(o, OBJ_ENCODING_HT);
            break;
        }
    }
}
```

Hashes are encoded using a memory efficient data structure when they have a small number of entries, and the biggest entry does not exceed a giventhreshold.
These thresholds can be configured using the following directives.

```conf
// redis.conf
hash-max-listpack-entries 512
hash-max-listpack-value 64
```

```c
void hashTypeConvert(robj *o, int enc) {
    if (o->encoding == OBJ_ENCODING_LISTPACK) {
        hashTypeConvertListpack(o, enc);
    } else if (o->encoding == OBJ_ENCODING_HT) {
        serverPanic("Not implemented");
    } else {
        serverPanic("Unknown hash encoding");
    }
}
```

call [dictCreate](/docs/CS/DB/Redis/struct/hash.mdhash.md?id=create)

```c
void hashTypeConvertListpack(robj *o, int enc) {
    serverAssert(o->encoding == OBJ_ENCODING_LISTPACK);

    if (enc == OBJ_ENCODING_LISTPACK) {
        /* Nothing to do... */

    } else if (enc == OBJ_ENCODING_HT) {
        hashTypeIterator *hi;
        dict *dict;
        int ret;

        hi = hashTypeInitIterator(o);
        dict = dictCreate(&hashDictType);

        /* Presize the dict to avoid rehashing */
        dictExpand(dict,hashTypeLength(o));

        while (hashTypeNext(hi) != C_ERR) {
            sds key, value;

            key = hashTypeCurrentObjectNewSds(hi,OBJ_HASH_KEY);
            value = hashTypeCurrentObjectNewSds(hi,OBJ_HASH_VALUE);
            ret = dictAdd(dict, key, value);
            if (ret != DICT_OK) {
                serverLogHexDump(LL_WARNING,"listpack with dup elements dump",
                    o->ptr,lpBytes(o->ptr));
                serverPanic("Listpack corruption detected");
            }
        }
        hashTypeReleaseIterator(hi);
        zfree(o->ptr);
        o->encoding = OBJ_ENCODING_HT;
        o->ptr = dict;
    } else {
        serverPanic("Unknown hash encoding");
    }
}
```

## create

Create a new hash table

```c
// dict.c
dict *dictCreate(dictType *type)
{
    dict *d = zmalloc(sizeof(*d));

    _dictInit(d,type);
    return d;
}


int _dictInit(dict *d, dictType *type)
{
    _dictReset(d, 0);
    _dictReset(d, 1);
    d->type = type;
    d->rehashidx = -1;
    d->pauserehash = 0;
    return DICT_OK;
}
```

## expand

This function is called once a background process of some kind terminates, as we want to avoid resizing the hash tables when there is a child in order to play well with `copy-on-write` (otherwise when a resize happens lots of memory pages are copied).
The goal of this function is to update the ability for `dict.c` to resize the hash tables accordingly to the fact we have an active fork child running.

Using dictEnableResize() / dictDisableResize() we make possible to enable/disable resizing of the hash table as needed.
This is very important for Redis, as we use copy-on-write and don't want to move too much memory around when there is a child performing saving operations.

Note that even when dict_can_resize is set to 0, not all resizes are prevented: a hash table is still allowed to grow if the ratio between the number of elements and the buckets > dict_force_resize_ratio.

```c
static int dict_can_resize = 1;
static unsigned int dict_force_resize_ratio = 5;

// server.c
void updateDictResizePolicy(void) {
    if (!hasActiveChildProcess())
        dictEnableResize();
    else
        dictDisableResize();
}
```

### expandIfNeeded

Redis 用来判断是否触发 rehash 的函数是 **_dictExpandIfNeeded**

Expand the hash table if needed(check loadFactor & if has active childProcess):

1. If the hash table is empty expand it to the initial size.
2. If we reached the 1:1 ratio, and we are allowed to resize the hash table (avoid `hasActiveChildProcess`) 避开RDB 快照和 AOF 重写
3. or we should avoid it but the ratio between elements/buckets is over the "safe" threshold, we resize doubling the number of buckets.

```c
static int _dictExpandIfNeeded(dict *d)
{
    if (dictIsRehashing(d)) return DICT_OK;

    if (d->ht[0].size == 0) return dictExpand(d, DICT_HT_INITIAL_SIZE);

    if (d->ht[0].used >= d->ht[0].size &&
        (dict_can_resize ||
         d->ht[0].used/d->ht[0].size > dict_force_resize_ratio) &&
        // Because we may need to allocate huge memory chunk at once when dict expands, 
        // we will check this allocation is allowed or not if the dict type has expandAllowed member function.
        dictTypeExpandAllowed(d))
    {
        return dictExpand(d, d->ht[0].used + 1);
    }
    return DICT_OK;
}
```



_dictExpandIfNeeded 是被 _dictKeyIndex 函数调用的，而 _dictKeyIndex 函数又会被 dictAddRaw 函数调用，然后 dictAddRaw 会被以下三个函数调用。

- dictAdd：用来往 Hash 表中添加一个键值对。
- dictRelace：用来往 Hash 表中添加一个键值对，或者键值对存在时，修改键值对。
- dictAddorFind：直接调用 dictAddRaw。

当我们往 Redis 中写入新的键值对或是修改键值对时，Redis 都会判断下是否需要进行 rehash



### dictExpand

ehash 对 Hash 表空间的扩容是通过调用 `dictExpand` 函数来完成的 dictExpand 函数的参数有两个，一个是要扩容的 Hash 表，另一个是要扩到的容量

Expand or create the hash table, when malloc_failed is non-NULL, it'll avoid panic if malloc fails (in which case it'll be set to 1).

```c
int _dictExpand(dict *d, unsigned long size, int* malloc_failed)
{
    if (malloc_failed) *malloc_failed = 0;

    if (dictIsRehashing(d) || d->ht[0].used > size)
        return DICT_ERR;

    dictht n; /* the new hash table */
    unsigned long realsize = _dictNextPower(size);

    /* Rehashing to the same table size is not useful. */
    if (realsize == d->ht[0].size) return DICT_ERR;

    /* Allocate the new hash table and initialize all pointers to NULL */
    n.size = realsize;
    n.sizemask = realsize-1;
    if (malloc_failed) {
        n.table = ztrycalloc(realsize*sizeof(dictEntry*));
        *malloc_failed = n.table == NULL;
        if (*malloc_failed)
            return DICT_ERR;
    } else
        n.table = zcalloc(realsize*sizeof(dictEntry*));

    n.used = 0;

    /* Is this the first initialization? If so it's not really a rehashing
     * we just set the first hash table so that it can accept keys. */
    if (d->ht[0].table == NULL) {
        d->ht[0] = n;
        return DICT_OK;
    }

    /* Prepare a second hash table for incremental rehashing */
    d->ht[1] = n;
    d->rehashidx = 0;
    return DICT_OK;
}
```



```c
/* Our hash table capability is a power of two */
static unsigned long _dictNextPower(unsigned long size) {
    unsigned long i = DICT_HT_INITIAL_SIZE;

    if (size >= LONG_MAX) return LONG_MAX;
    while(1) {
        if (i >= size)
            return i;
        i *= 2;
    }
}
```





## resize

1. databasesCron -> tryResizeHashTables -> dictResize
2. Del operations -> dictResize if htNeedsResize

```c
void tryResizeHashTables(int dbid) {
    if (htNeedsResize(server.db[dbid].dict))
        dictResize(server.db[dbid].dict);
    if (htNeedsResize(server.db[dbid].expires))
        dictResize(server.db[dbid].expires);
}
```

If the percentage of used slots in the HT reaches HASHTABLE_MIN_FILL we resize the hash table to save memory.

```c
#define DICT_HT_INITIAL_SIZE     4
#define HASHTABLE_MIN_FILL        10

int htNeedsResize(dict *dict) {
    long long size, used;

    size = dictSlots(dict);
    used = dictSize(dict);
    return (size > DICT_HT_INITIAL_SIZE &&
            (used*100/size < HASHTABLE_MIN_FILL));
}
```

Resize the table to the minimal size that contains all the elements, but with the invariant of a USED/BUCKETS ratio near to <= 1

```c
int dictResize(dict *d)
{
    unsigned long minimal;

    if (!dict_can_resize || dictIsRehashing(d)) return DICT_ERR;
    minimal = d->ht_used[0];
    if (minimal < DICT_HT_INITIAL_SIZE)
        minimal = DICT_HT_INITIAL_SIZE;
    return dictExpand(d, minimal);
}
```

## rehash



This function performs just a step of rehashing, and only if hashing has not been paused for our hash table.
When we have iterators in the middle of a rehashing we can't mess with the two hash tables otherwise some element can be missed or duplicated.

This function is called by **common lookup or update operations** in the dictionary so that the hash table `automatically migrates` from H1 to H2 while it is actively used.

这个函数实现了每次只对一个 bucket 执行 rehash

一共会有 5 个函数通过调用 _dictRehashStep 函数，进而调用 dictRehash 函数，来执行 rehash，它们分别是：dictAddRaw，dictGenericDelete，dictFind，dictGetRandomKey，dictGetSomeKeys

```c
// dict.c
static void _dictRehashStep(dict *d) {
    if (d->pauserehash == 0) dictRehash(d,1);
}
```

每次迁移完一个 bucket，Hash 表就会执行正常的增删查请求操作，这就是在代码层面实现渐进式 rehash 的方法

Try to use 1 millisecond of CPU time at every call of this function to perform some rehashing, but only if there are no other processes saving the DB on disk.
Otherwise rehashing is bad as will cause a lot of copy-on-write of memory pages.

> databasesCron -> incrementallyRehash -> dictRehashMilliseconds -> dictRehashMilliseconds

```c
int dictRehashMilliseconds(dict *d, int ms) {
    if (d->pauserehash > 0) return 0;

    long long start = timeInMilliseconds();
    int rehashes = 0;

    while(dictRehash(d,100)) {
        rehashes += 100;
        if (timeInMilliseconds()-start > ms) break;
    }
    return rehashes;
}
```

### dictRehash

Max number of empty buckets to visit **1000**

Performs N steps of incremental rehashing.
Note that a rehashing step consists in moving a bucket (that may have more than one key as we use chaining) from the old to the new hash table, however since part of the hash table may be composed of empty spaces,
it is not guaranteed that this function will rehash even a single bucket, since it will visit at max N*10 empty buckets in total, otherwise the amount of work it does would be unbound and the function may block for a long time.

dictRehash 函数的整体逻辑包括两部分：

- 首先，该函数会执行一个循环，根据要进行键拷贝的 bucket 数量 n，依次完成这些 bucket 内部所有键的迁移。当然，如果 ht[0]哈希表中的数据已经都迁移完成了，键拷贝的循环也会停止执行。
- 其次，在完成了 n 个 bucket 拷贝后，dictRehash 函数的第二部分逻辑，就是判断 ht[0]表中数据是否都已迁移完。如果都迁移完了，那么 ht[0]的空间会被释放。因为 Redis 在处理请求时，代码逻辑中都是使用 ht[0]，所以当 rehash 执行完成后，虽然数据都在 ht[1]中了，但 Redis 仍然会把 ht[1]赋值给 ht[0]，以便其他部分的代码逻辑正常使用。
- 而在 ht[1]赋值给 ht[0]后，它的大小就会被重置为 0，等待下一次 rehash。与此同时，全局哈希表中的 rehashidx 变量会被标为 -1，表示 rehash 结束了（这里的 rehashidx 变量用来表示 rehash 的进度，稍后我会给你具体解释）。

渐进式 rehash 在执行时设置了一个变量 `empty_visits`，用来表示已经检查过的空 bucket，当检查了一定数量的空 bucket 后，这一轮的 rehash 就停止执行，转而继续处理外来请求，避免了对 Redis 性能的影响

```c
int dictRehash(dict *d, int n) {
    int empty_visits = n*10; /* Max number of empty buckets to visit. */
    if (!dictIsRehashing(d)) return 0;

    while(n-- && d->ht[0].used != 0) {
        dictEntry *de, *nextde;

        assert(d->ht[0].size > (unsigned long)d->rehashidx);
        while(d->ht[0].table[d->rehashidx] == NULL) {
            d->rehashidx++;
            if (--empty_visits == 0) return 1;
        }
        de = d->ht[0].table[d->rehashidx];
        /* Move all the keys in this bucket from the old to the new hash HT */
        while(de) {
            uint64_t h;

            nextde = de->next;

            h = dictHashKey(d, de->key) & d->ht[1].sizemask;
            de->next = d->ht[1].table[h];
            d->ht[1].table[h] = de;
            d->ht[0].used--;
            d->ht[1].used++;
            de = nextde;
        }
        d->ht[0].table[d->rehashidx] = NULL;
        d->rehashidx++;
    }

    /* Check if we already rehashed the whole table... */
    if (d->ht[0].used == 0) {
        zfree(d->ht[0].table);
        d->ht[0] = d->ht[1];
        _dictReset(&d->ht[1]);
        d->rehashidx = -1;
        return 0;
    }

    return 1;
}
```

## iterator

- If safe is set to 1 this is a safe iterator, that means, you can call dictAdd, dictFind, and other functions against the dictionary even while iterating.
- Otherwise it is a non safe iterator, and only dictNext() should be called while iterating.

```c
//dict.h
typedef struct dictIterator {
    dict *d;
    long index;
    int table, safe;
    dictEntry *entry, *nextEntry;
    /* unsafe iterator fingerprint for misuse detection. */
    long long fingerprint;
} dictIterator;
```

### scan

The `SCAN` command, and the other commands in the `SCAN` family, are able to provide to the user a set of guarantees associated to full iterations.

* A full iteration always retrieves all the elements that were present in the collection from the start to the end of a full iteration.
  This means that if a given element is inside the collection when an iteration is started, and is still there when an iteration terminates, then at some point `SCAN` returned it to the user.
* A full iteration never returns any element that was NOT present in the collection from the start to the end of a full iteration.
  So if an element was removed before the start of an iteration, and is never added back to the collection for all the time an iteration lasts, `SCAN` ensures that this element will never be returned.

However because `SCAN` has very little state associated (just the cursor) it has the following drawbacks:

* A given element may be returned multiple times.
  It is up to the application to handle the case of duplicated elements, for example only using the returned elements in order to perform operations that are safe when re-applied multiple times.
* Elements that were not constantly present in the collection during a full iteration, may be returned or not: it is undefined.

## Links

- [Redis Struct](/docs/CS/DB/Redis/struct/struct.mdruct.md?id=hashes)

## References

1. [Redis Internal Data Structure : Dictionary](https://blog.wjin.org/posts/redis-internal-data-structure-dictionary.html)
