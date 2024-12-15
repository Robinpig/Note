## Introduction

[redisDb](/docs/CS/DB/Redis/redisDb.md) also a hashtable

redis command table

## Structures


final struct dict

rehashing not in progress if rehashidx == -1

```c
// dict.c
typedef struct dict {
    dictType *type;
    void *privdata;
    dictht ht[2];
    long rehashidx;
    unsigned long iterators; /* number of iterators currently running */
} dict;
```


This is our hash table structure. Every dictionary has **two of this** as we implement **incremental rehashing**, for the old to the new table.

```c
typedef struct dictht {
    dictEntry **table;
    unsigned long size;
    unsigned long sizemask;// always size -1
    unsigned long used;
} dictht;
```

dictEntry:

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

siphash

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

Expand the hash table if needed(check loadFactor & if has active childProcess):

1. If the hash table is empty expand it to the initial size.
2. If we reached the 1:1 ratio, and we are allowed to resize the hash table (avoid `hasActiveChildProcess`)
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

### dictExpand

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

```c
// dict.c
static void _dictRehashStep(dict *d) {
    if (d->pauserehash == 0) dictRehash(d,1);
}
```

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
```

Get the index in the new hash table

```c
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
