## Introduction



[redisServer](/docs/CS/DB/Redis/server.md?id=server) 中存储着redisDb数组的指针

```c
struct redisServer {
  	redisDb *db;
  	int dbnum;                      /* Total number of configured DBs */
}  
```

在initServer时创建redisDb数据

```c
void initServer(void){
  ...
  /* Create the Redis databases, and initialize other internal state. */
    for (j = 0; j < server.dbnum; j++) {
        server.db[j].dict = dictCreate(&dbDictType);
        server.db[j].expires = dictCreate(&dbExpiresDictType);
        server.db[j].expires_cursor = 0;
        server.db[j].blocking_keys = dictCreate(&keylistDictType);
        server.db[j].ready_keys = dictCreate(&objectKeyPointerValueDictType);
        server.db[j].watched_keys = dictCreate(&keylistDictType);
        server.db[j].id = j;
        server.db[j].avg_ttl = 0;
        server.db[j].defrag_later = listCreate();
        server.db[j].slots_to_keys = NULL; /* Set by clusterInit later on if necessary. */
        listSetFreeMethod(server.db[j].defrag_later,(void (*)(void*))sdsfree);
    }
}
```

## redisDb

Redis database representation. There are multiple databases identified by integers from 0 (the default database) up to the max configured database.

```java
// server.h
typedef struct redisDb {
    dict *dict;                 /* The keyspace for this DB */
    dict *expires;							/* Timeout of keys with a timeout set */
    dict *blocking_keys;        /* Keys with clients waiting for data (BLPOP)*/
    dict *ready_keys;           /* Blocked keys that received a PUSH */
    dict *watched_keys;         /* WATCHED keys for MULTI/EXEC CAS */
    int id;                     /* Database ID */
    long long avg_ttl;          /* Average TTL, just for stats */
    unsigned long expires_cursor; /* Cursor of the active expire cycle. */
    list *defrag_later;         /* List of key names to attempt to defrag one by one, gradually. */
} redisDb;
```

将expires和dict分开存储因为不是每个key都有过期时间 分开存储能节省空间 在key过期时便于查询

blocking_keys 和 ready_keys 用于BLPOP命令的



### dict


```c
// dict.h
struct dict {
    dictType *type;

    dictEntry **ht_table[2];
    unsigned long ht_used[2];

    long rehashidx; /* rehashing not in progress if rehashidx == -1 */

    /* Keep small vars at end for optimal (minimal) struct padding */
    int16_t pauserehash; /* If >0 rehashing is paused (<0 indicates coding error) */
    char ht_size_exp[2]; /* exponent of size. (size = 1<<exp) */
};
```

一开始只使用 ht_table[0] 读写数据 ht_table[1] 指向NULL, 当rehash时才会创建更大的散列表 ht_table[1], rehash迁移完成后 交换 ht_table[0]  和 ht_table[1] 的指针 ht_table[1] 重新指向 NULL





[dicht in hash](/docs/CS/DB/Redis/hash.md?id=dicht)

```c
// dict.h
typedef struct dictEntry {
    void *key; 
    union {
        void *val; // -> redisObject
        uint64_t u64;
        int64_t s64;
        double d;
    } v;
    struct dictEntry *next;
} dictEntry;
```





Certain Redis commands operate on specific data types; others are general.
Examples of generic commands are `DEL` and `EXPIRE`. They operate on keys and not on their values specifically.
All those generic commands are defined inside `db.c`.

Moreover `db.c` implements an API in order to perform certain operations on the Redis dataset without directly accessing the internal data structures.

The most important functions inside `db.c` which are used in many command implementations are the following:

* [lookupKeyRead()](/docs/CS/DB/Redis/redisDb.md?id=lookupKey) and [lookupKeyWrite()](/docs/CS/DB/Redis/redisDb.md?id=lookupKey) are used in order to get a pointer to the value associated to a given key, or `NULL` if the key does not exist.
* [dbAdd()](/docs/CS/DB/Redis/redisDb.md?id=add) and its higher level counterpart `setKey()` create a new key in a Redis database.
* [dbDelete()](/docs/CS/DB/Redis/redisDb.md?id=delete) removes a key and its associated value.
* `emptyDb()` removes an entire single database or all the databases defined.

## redisObject

The following is the full `robj` structure, which defines a *Redis object*(16bytes):

- `type` : 4bits get type by `type keyName`
- `encoding` : 4bits get encoding  by `object encoding keyName`
- `lru` : 24bits
- `refcount` : 4bytes
- `ptr` : 8bytes

```c
// server.h
typedef struct redisObject {
    unsigned type:4;
    unsigned encoding:4;
    unsigned lru:LRU_BITS; /* LRU time (relative to global lru_clock) or
                            * LFU data (least significant 8 bits frequency
                            * and most significant 16 bits access time). */
    int refcount;
    void *ptr; // pointer of value
} robj;
```

- Basically this structure can represent all the basic Redis data types like strings, lists, sets, sorted sets and so forth.
- The interesting thing is that it has a `type` field, so that it is possible to know what type a given object has, and a `refcount`, so that the same object can be referenced in multiple places without allocating it multiple times.
- Finally the `ptr` field points to the actual representation of the object, which might vary even for the same type, depending on the `encoding` used.

Redis objects are used extensively in the Redis internals, however in order to avoid the overhead of indirect accesses, recently in many places we just use plain dynamic strings not wrapped inside a Redis object.

Inside `object.c` there are all the functions that operate with Redis objects at a basic level, like functions to allocate new objects, handle the reference counting and so forth. Notable functions inside this file:

- `incrRefCount()` and `decrRefCount()` are used in order to increment or decrement an object reference count. When it drops to 0 the object is finally freed.
- [createObject()](/docs/CS/DB/Redis/redisDb.md?id=createObject) allocates a new object.
  There are also specialized functions to allocate string objects having a specific content, like `createStringObjectFromLongLong()` and similar functions.

24bits

- 8bits logistic counter log
- 16bits last decrement time minutes

### refCount

decrRefCount

```c
// object.c
void decrRefCount(robj *o) {
    if (o->refcount == 1) {
        switch(o->type) {
        case OBJ_STRING: freeStringObject(o); break;
        case OBJ_LIST: freeListObject(o); break;
        case OBJ_SET: freeSetObject(o); break;
        case OBJ_ZSET: freeZsetObject(o); break;
        case OBJ_HASH: freeHashObject(o); break;
        case OBJ_MODULE: freeModuleObject(o); break;
        case OBJ_STREAM: freeStreamObject(o); break;
        default: serverPanic("Unknown object type"); break;
        }
        zfree(o);
    } else {
        if (o->refcount <= 0) serverPanic("decrRefCount against refcount <= 0");
        if (o->refcount != OBJ_SHARED_REFCOUNT) o->refcount--;
    }
}
```

### createObject

```c
// object.c
robj *createObject(int type, void *ptr) {
    robj *o = zmalloc(sizeof(*o));
    o->type = type;
    o->encoding = OBJ_ENCODING_RAW;
    o->ptr = ptr;
    o->refcount = 1;

    /* Set the LRU to the current lruclock (minutes resolution), or
     * alternatively the LFU counter. */
    if (server.maxmemory_policy & MAXMEMORY_FLAG_LFU) {
        o->lru = (LFUGetTimeInMinutes()<<8) | LFU_INIT_VAL;
    } else {
        o->lru = LRU_CLOCK();
    }
    return o;
}
```

## get



### lookupKey

```c
// db.c
robj *lookupKeyReadOrReply(client *c, robj *key, robj *reply) {
    robj *o = lookupKeyRead(c->db, key);
    if (!o) SentReplyOnKeyMiss(c, reply);
    return o;
}

/* Like lookupKeyReadWithFlags(), but does not use any flag, which is the
 * common case. */
robj *lookupKeyRead(redisDb *db, robj *key) {
    return lookupKeyReadWithFlags(db,key,LOOKUP_NONE);
}

robj *lookupKeyWrite(redisDb *db, robj *key) {
    return lookupKeyWriteWithFlags(db, key, LOOKUP_NONE);
}


/* Lookup a key for write operations, and as a side effect, if needed, expires
 * the key if its TTL is reached.
 *
 * Returns the linked value object if the key exists or NULL if the key
 * does not exist in the specified DB. */
robj *lookupKeyWriteWithFlags(redisDb *db, robj *key, int flags) {
    expireIfNeeded(db,key);
    return lookupKey(db,key,flags);
}
```

```c
// db.c

/* This function is called when we are going to perform some operation
 * in a given key, but such key may be already logically expired even if
 * it still exists in the database. The main way this function is called
 * is via lookupKey*() family of functions.
 *
 * The behavior of the function depends on the replication role of the
 * instance, because slave instances do not expire keys, they wait
 * for DELs from the master for consistency matters. However even
 * slaves will try to have a coherent return value for the function,
 * so that read commands executed in the slave side will be able to
 * behave like if the key is expired even if still present (because the
 * master has yet to propagate the DEL).
 *
 * In masters as a side effect of finding a key which is expired, such
 * key will be evicted from the database. Also this may trigger the
 * propagation of a DEL/UNLINK command in AOF / replication stream.
 *
 * The return value of the function is 0 if the key is still valid,
 * otherwise the function returns 1 if the key is expired. */
int expireIfNeeded(redisDb *db, robj *key) {
    if (!keyIsExpired(db,key)) return 0;

    /* If we are running in the context of a slave, instead of
     * evicting the expired key from the database, we return ASAP:
     * the slave key expiration is controlled by the master that will
     * send us synthesized DEL operations for expired keys.
     *
     * Still we try to return the right information to the caller,
     * that is, 0 if we think the key should be still valid, 1 if
     * we think the key is expired at this time. */
    if (server.masterhost != NULL) return 1;

    /* If clients are paused, we keep the current dataset constant,
     * but return to the client what we believe is the right state. Typically,
     * at the end of the pause we will properly expire the key OR we will
     * have failed over and the new primary will send us the expire. */
    if (checkClientPauseTimeoutAndReturnIfPaused()) return 1;

    /* Delete the key */
    deleteExpiredKeyAndPropagate(db,key);
    return 1;
}
```

call [dictFind](/docs/CS/DB/Redis/redisDb.md?id=dictFind) to find dictEntry, then **update lfu or lru access time**

```c
// db.c
robj *lookupKey(redisDb *db, robj *key, int flags) {
    dictEntry *de = dictFind(db->dict,key->ptr);
    if (de) {
        robj *val = dictGetVal(de);

        /* Update the access time for the ageing algorithm.
         * Don't do it if we have a saving child, as this will trigger
         * a copy on write madness. */
        if (!hasActiveChildProcess() && !(flags & LOOKUP_NOTOUCH)){
            if (server.maxmemory_policy & MAXMEMORY_FLAG_LFU) {
                updateLFU(val);
            } else {
                val->lru = LRU_CLOCK();
            }
        }
        return val;
    } else {
        return NULL;
    }
}
```

#### LRUClock

If the current resolution is lower than the frequency we refresh the LRU clock (as it should be in production servers) we return the precomputed value, otherwise we need to resort to a system call.

```c
#define LRU_CLOCK_RESOLUTION 1000 /* LRU clock resolution in ms */

unsigned int LRU_CLOCK(void) {
    unsigned int lruclock;
    if (1000/server.hz <= LRU_CLOCK_RESOLUTION) {
        atomicGet(server.lruclock,lruclock);
    } else {
        lruclock = getLRUClock();
    }
    return lruclock;
}
```

[update cached mstime](/docs/CS/DB/Redis/start.md?id=updateCachedTime)

```c
unsigned int getLRUClock(void) {
    return (mstime()/LRU_CLOCK_RESOLUTION) & LRU_CLOCK_MAX;
}
```



#### updateLFU

Update LFU when an object is accessed.

- Firstly, decrement the counter if the decrement time is reached.
- Then logarithmically increment the counter, and update the access time.

```c
// db.c
void updateLFU(robj *val) {
    unsigned long counter = LFUDecrAndReturn(val);
    counter = LFULogIncr(counter);
    val->lru = (LFUGetTimeInMinutes()<<8) | counter;
}
```

Logarithmically increment a counter. The greater is the current counter value the less likely is that it gets really implemented. Saturate it at 255.

```
#define LFU_INIT_VAL 5
 
uint8_t LFULogIncr(uint8_t counter) {
    if (counter == 255) return 255;
    double r = (double)rand()/RAND_MAX;
    double baseval = counter - LFU_INIT_VAL;
    if (baseval < 0) baseval = 0;
    double p = 1.0/(baseval*server.lfu_log_factor+1);
    if (r < p) counter++;
    return counter;
}
```

If the object decrement time is reached decrement the LFU counter but do not update LFU fields of the object, we update the access time and counter in an explicit way when the object is really accessed.
And we will times halve the counter according to the times of elapsed time than server.lfu_decay_time.
Return the object frequency counter.

This function is used in order to scan the dataset for the best object to fit: as we check for the candidate, we incrementally decrement the counter of the scanned objects if needed.

```
unsigned long LFUDecrAndReturn(robj *o) {
    unsigned long ldt = o->lru >> 8;
    unsigned long counter = o->lru & 255;
    unsigned long num_periods = server.lfu_decay_time ? LFUTimeElapsed(ldt) / server.lfu_decay_time : 0;
    if (num_periods)
        counter = (num_periods > counter) ? 0 : counter - num_periods;
    return counter;
}
```

### dictFind

call [rehash](/docs/CS/DB/Redis/hash.md?id=rehash) when dictIsRehashing

```c
// dict.c
dictEntry *dictFind(dict *d, const void *key)
{
    dictEntry *he;
    uint64_t h, idx, table;

    if (dictSize(d) == 0) return NULL; /* dict is empty */
    if (dictIsRehashing(d)) _dictRehashStep(d);
    h = dictHashKey(d, key);
    for (table = 0; table <= 1; table++) { // two table
        idx = h & DICTHT_SIZE_MASK(d->ht_size_exp[table]);
        he = d->ht_table[table][idx];
        while(he) {
            if (key==he->key || dictCompareKeys(d, key, he->key))
                return he;
            he = he->next;
        }
        if (!dictIsRehashing(d)) return NULL;
    }
    return NULL;
}
```

## set

### genericSetKey

- if [lookup] is NULL, call [dbAdd](/docs/CS/DB/Redis/redisDb.md?id=add)
- or else [overwrite](/docs/CS/DB/Redis/redisDb.md?id=overwrite)

```c
/* High level Set operation. This function can be used in order to set
 * a key, whatever it was existing or not, to a new object.
 *
 * 1) The ref count of the value object is incremented.
 * 2) clients WATCHing for the destination key notified.
 * 3) The expire time of the key is reset (the key is made persistent),
 *    unless 'keepttl' is true.
 *
 * All the new keys in the database should be created via this interface.
 * The client 'c' argument may be set to NULL if the operation is performed
 * in a context where there is no clear client performing the operation. */
// db.c
void genericSetKey(client *c, redisDb *db, robj *key, robj *val, int keepttl, int signal) {
    if (lookupKeyWrite(db,key) == NULL) {
        dbAdd(db,key,val);
    } else {
        dbOverwrite(db,key,val);
    }
    incrRefCount(val);
    if (!keepttl) removeExpire(db,key);
    if (signal) signalModifiedKey(c,db,key);
}
```

### add

call [dictAddRaw in hash](/docs/CS/DB/Redis/redisDb.md?id=dictAddRaw)

```c
// db.c
/* Add the key to the DB. It's up to the caller to increment the reference
 * counter of the value if needed.
 *
 * The program is aborted if the key already exists. */
void dbAdd(redisDb *db, robj *key, robj *val) {
    sds copy = sdsdup(key->ptr);
    int retval = dictAdd(db->dict, copy, val);

    serverAssertWithInfo(NULL,key,retval == DICT_OK);
    signalKeyAsReady(db, key, val->type);
    if (server.cluster_enabled) slotToKeyAdd(key->ptr);
}


/* Add an element to the target hash table */
int dictAdd(dict *d, void *key, void *val)
{
    dictEntry *entry = dictAddRaw(d,key,NULL);

    if (!entry) return DICT_ERR;
    dictSetVal(d, entry, val);
    return DICT_OK;
}
```

#### dictAddRaw

**Insert the element in top**

add new object in ht[1] when rehashing

[expand if needed](/docs/CS/DB/Redis/hash.md?id=expand)

```c
/* Low level add or find:
 * This function adds the entry but instead of setting a value returns the
 * dictEntry structure to the user, that will make sure to fill the value
 * field as they wish.
 *
 * This function is also directly exposed to the user API to be called
 * mainly in order to store non-pointers inside the hash value, example:
 *
 * entry = dictAddRaw(dict,mykey,NULL);
 * if (entry != NULL) dictSetSignedIntegerVal(entry,1000);
 *
 * Return values:
 *
 * If key already exists NULL is returned, and "*existing" is populated
 * with the existing entry if existing is not NULL.
 *
 * If key was added, the hash entry is returned to be manipulated by the caller.
 */
dictEntry *dictAddRaw(dict *d, void *key, dictEntry **existing)
{
    long index;
    dictEntry *entry;
    int htidx;

    if (dictIsRehashing(d)) _dictRehashStep(d);

    /* Get the index of the new element, or -1 if
     * the element already exists. */
    if ((index = _dictKeyIndex(d, key, dictHashKey(d,key), existing)) == -1)
        return NULL;

    /* Allocate the memory and store the new entry.
     * Insert the element in top, with the assumption that in a database
     * system it is more likely that recently added entries are accessed
     * more frequently. */
    htidx = dictIsRehashing(d) ? 1 : 0;
    entry = zmalloc(sizeof(*entry));
    entry->next = d->ht_table[htidx][index];
    d->ht_table[htidx][index] = entry;
    d->ht_used[htidx]++;

    /* Set the hash entry fields. */
    dictSetKey(d, entry, key);
    return entry;
}


/* Returns the index of a free slot that can be populated with
 * a hash entry for the given 'key'.
 * If the key already exists, -1 is returned
 * and the optional output parameter may be filled.
 *
 * Note that if we are in the process of rehashing the hash table, the
 * index is always returned in the context of the second (new) hash table. */
static long _dictKeyIndex(dict *d, const void *key, uint64_t hash, dictEntry **existing)
{
    unsigned long idx, table;
    dictEntry *he;
    if (existing) *existing = NULL;

    /* Expand the hash table if needed */
    if (_dictExpandIfNeeded(d) == DICT_ERR)
        return -1;
    for (table = 0; table <= 1; table++) {
        idx = hash & d->ht[table].sizemask;
        /* Search if this slot does not already contain the given key */
        he = d->ht[table].table[idx];
        while(he) {
            if (key==he->key || dictCompareKeys(d, key, he->key)) {
                if (existing) *existing = he;
                return -1;
            }
            he = he->next;
        }
        if (!dictIsRehashing(d)) break;
    }
    return idx;
}
```

### overwrite

1. [dictFind](/docs/CS/DB/Redis/redisDb.md?id=dictFind)
2. unlink+add

```c
// db.c
/* Overwrite an existing key with a new value. Incrementing the reference
 * count of the new value is up to the caller.
 * This function does not modify the expire time of the existing key.
 *
 * The program is aborted if the key was not already present. */
void dbOverwrite(redisDb *db, robj *key, robj *val) {
    dictEntry *de = dictFind(db->dict,key->ptr);

    serverAssertWithInfo(NULL,key,de != NULL);
    dictEntry auxentry = *de;
    robj *old = dictGetVal(de);
    if (server.maxmemory_policy & MAXMEMORY_FLAG_LFU) {
        val->lru = old->lru;
    }
    /* Although the key is not really deleted from the database, we regard 
    overwrite as two steps of unlink+add, so we still need to call the unlink 
    callback of the module. */
    moduleNotifyKeyUnlink(key,old);
    dictSetVal(db->dict, de, val);

    if (server.lazyfree_lazy_server_del) {
        freeObjAsync(key,old);
        dictSetVal(db->dict, &auxentry, NULL);
    }

    dictFreeVal(db->dict, &auxentry);
}
```

## delete

This is a wrapper whose behavior depends on the Redis lazy free configuration.
Deletes the key synchronously or asynchronously.

```c
// db.c
int dbDelete(redisDb *db, robj *key) {
    return server.lazyfree_lazy_server_del ? dbAsyncDelete(db,key) :
                                             dbSyncDelete(db,key);
}
```

### Async Delete

> unlinkCommand -> delGenericCommand -> dbAsyncDelete

Delete a key, value, and associated expiration entry if any, from the DB.
If there are enough allocations to free the value object may be put into a lazy free list instead of being freed synchronously.
The lazy free list will be reclaimed in a different bio.c thread.

```c
// db.c
#define LAZYFREE_THRESHOLD 64
int dbAsyncDelete(redisDb *db, robj *key) {
```

[Deleting](/docs/CS/DB/Redis/redisDb.md?id=dictDelete) an entry from the expires dict will not free the sds of the key, because it is shared with the main dictionary.

```c
    if (dictSize(db->expires) > 0) dictDelete(db->expires,key->ptr);
```

If the value is composed of a few allocations, to free in a lazy way is actually just slower.
So under a certain limit we just free the object synchronously.

```c
    dictEntry *de = dictUnlink(db->dict,key->ptr);
    if (de) {
        robj *val = dictGetVal(de);

        /* Tells the module that the key has been unlinked from the database. */
        moduleNotifyKeyUnlink(key,val);

        size_t free_effort = lazyfreeGetFreeEffort(key,val);
```

If releasing the object is too much work, do it in the background by adding the object to the lazy free list.
Note that if the object is shared, to reclaim it now it is not possible.
This rarely happens, however sometimes the implementation of parts of the Redis core may call incrRefCount() to protect objects, and then call dbDelete().
In this case we'll fall through and reach the dictFreeUnlinkedEntry() call, that will be equivalent to just calling decrRefCount().

```c
        if (free_effort > LAZYFREE_THRESHOLD && val->refcount == 1) {
            atomicIncr(lazyfree_objects,1);
            bioCreateLazyFreeJob(lazyfreeFreeObject,1, val);
            dictSetVal(db->dict,de,NULL);
        }
    }

```

Release the key-val pair, or just the key if we set the val field to NULL in order to lazy free it later.

```c
    if (de) {
        dictFreeUnlinkedEntry(db->dict,de);
        if (server.cluster_enabled) slotToKeyDel(key->ptr);
        return 1;
    } else {
        return 0;
    }
}
```

#### dictDelete

Search and remove an element. This is an helper function for dictDelete() and dictUnlink(), please check the top comment of those functions.

```c
// dict.c
int dictDelete(dict *ht, const void *key) {
    return dictGenericDelete(ht,key,0) ? DICT_OK : DICT_ERR;
}

static dictEntry *dictGenericDelete(dict *d, const void *key, int nofree) {
    uint64_t h, idx;
    dictEntry *he, *prevHe;
    int table;

    if (d->ht[0].used == 0 && d->ht[1].used == 0) return NULL;

    if (dictIsRehashing(d)) _dictRehashStep(d);
    h = dictHashKey(d, key);

    for (table = 0; table <= 1; table++) {
        idx = h & d->ht[table].sizemask;
        he = d->ht[table].table[idx];
        prevHe = NULL;
        while(he) {
            if (key==he->key || dictCompareKeys(d, key, he->key)) {
                /* Unlink the element from the list */
                if (prevHe)
                    prevHe->next = he->next;
                else
                    d->ht[table].table[idx] = he->next;
                if (!nofree) {
                    dictFreeKey(d, he);
                    dictFreeVal(d, he);
                    zfree(he);
                }
                d->ht[table].used--;
                return he;
            }
            prevHe = he;
            he = he->next;
        }
        if (!dictIsRehashing(d)) break;
    }
    return NULL; /* not found */
}
```

## expire
in [beforeSleep](/docs/CS/DB/Redis/ae.md?id=beforeSleep)
`activeExpireCycle()` handles eviction of keys with a time to live set via the `EXPIRE` command.


Try to expire a few timed out keys. The algorithm used is adaptive and will use few CPU cycles if there are few expiring keys, otherwise it will get more aggressive to avoid that too much memory is used by keys that can be removed from the keyspace.

Every expire cycle tests multiple databases: the next call will start again from the next db. No more than CRON_DBS_PER_CALL databases are tested at every iteration.

The function can perform more or less work, depending on the "type"argument. It can execute a "fast cycle" or a "slow cycle". 
The slow cycle is the main way we collect expired cycles: this happens with the "server.hz" frequency (usually 10 hertz).

However the slow cycle can exit for timeout, since it used too much time. 
For this reason the function is also invoked to perform a fast cycle at every event loop cycle, in the beforeSleep() function. The fast cycle will try to perform less work, but will do it much more often.

The following are the details of the two expire cycles and their stop conditions:

If type is ACTIVE_EXPIRE_CYCLE_FAST the function will try to run a "fast" expire cycle that takes no longer than ACTIVE_EXPIRE_CYCLE_FAST_DURATION microseconds, and is not repeated again before the same amount of time. 
The cycle will also refuse to run at all if the latest slow cycle did not terminate because of a time limit condition.

If type is ACTIVE_EXPIRE_CYCLE_SLOW, that normal expire cycle is executed, where the time limit is a percentage of the REDIS_HZ period as specified by the ACTIVE_EXPIRE_CYCLE_SLOW_TIME_PERC define. 
In the fast cycle, the check of every database is interrupted once the number of already expired keys in the database is estimated to be lower than a given percentage, in order to avoid doing too much work to gain too little memory.

The configured expire "effort" will modify the baseline parameters in order to do more work in both the fast and slow expire cycles.

```c
#define ACTIVE_EXPIRE_CYCLE_KEYS_PER_LOOP 20 /* Keys for each DB loop. */
#define ACTIVE_EXPIRE_CYCLE_FAST_DURATION 1000 /* Microseconds. */
#define ACTIVE_EXPIRE_CYCLE_SLOW_TIME_PERC 25 /* Max % of CPU to use. */
#define ACTIVE_EXPIRE_CYCLE_ACCEPTABLE_STALE 10 /* % of stale keys after which
                                                   we do extra efforts. */

void activeExpireCycle(int type) {
    /* Adjust the running parameters according to the configured expire
     * effort. The default effort is 1, and the maximum configurable effort
     * is 10. */
    unsigned long
    effort = server.active_expire_effort-1, /* Rescale from 0 to 9. */
    config_keys_per_loop = ACTIVE_EXPIRE_CYCLE_KEYS_PER_LOOP +
                           ACTIVE_EXPIRE_CYCLE_KEYS_PER_LOOP/4*effort,
    config_cycle_fast_duration = ACTIVE_EXPIRE_CYCLE_FAST_DURATION +
                                 ACTIVE_EXPIRE_CYCLE_FAST_DURATION/4*effort,
    config_cycle_slow_time_perc = ACTIVE_EXPIRE_CYCLE_SLOW_TIME_PERC +
                                  2*effort,
    config_cycle_acceptable_stale = ACTIVE_EXPIRE_CYCLE_ACCEPTABLE_STALE-
                                    effort;

    /* This function has some global state in order to continue the work
     * incrementally across calls. */
    static unsigned int current_db = 0; /* Next DB to test. */
    static int timelimit_exit = 0;      /* Time limit hit in previous call? */
    static long long last_fast_cycle = 0; /* When last fast cycle ran. */

    int j, iteration = 0;
    int dbs_per_call = CRON_DBS_PER_CALL;
    long long start = ustime(), timelimit, elapsed;

    /* When clients are paused the dataset should be static not just from the
     * POV of clients not being able to write, but also from the POV of
     * expires and evictions of keys not being performed. */
    if (checkClientPauseTimeoutAndReturnIfPaused()) return;

    if (type == ACTIVE_EXPIRE_CYCLE_FAST) {
        /* Don't start a fast cycle if the previous cycle did not exit
         * for time limit, unless the percentage of estimated stale keys is
         * too high. Also never repeat a fast cycle for the same period
         * as the fast cycle total duration itself. */
        if (!timelimit_exit &&
            server.stat_expired_stale_perc < config_cycle_acceptable_stale)
            return;

        if (start < last_fast_cycle + (long long)config_cycle_fast_duration*2)
            return;

        last_fast_cycle = start;
    }
```
We usually should test CRON_DBS_PER_CALL per iteration, with two exceptions:

1. Don't test more DBs than we have.
2. If last time we hit the time limit, we want to scan all DBs in this iteration, as there is work to do in some DB and we don't want expired keys to use memory for too much time. */
```c
    if (dbs_per_call > server.dbnum || timelimit_exit)
        dbs_per_call = server.dbnum;

    /* We can use at max 'config_cycle_slow_time_perc' percentage of CPU
     * time per iteration. Since this function gets called with a frequency of
     * server.hz times per second, the following is the max amount of
     * microseconds we can spend in this function. */
    timelimit = config_cycle_slow_time_perc*1000000/server.hz/100;
    timelimit_exit = 0;
    if (timelimit <= 0) timelimit = 1;

    if (type == ACTIVE_EXPIRE_CYCLE_FAST)
        timelimit = config_cycle_fast_duration; /* in microseconds. */

    /* Accumulate some global stats as we expire keys, to have some idea
     * about the number of keys that are already logically expired, but still
     * existing inside the database. */
    long total_sampled = 0;
    long total_expired = 0;

    for (j = 0; j < dbs_per_call && timelimit_exit == 0; j++) {
        /* Expired and checked in a single loop. */
        unsigned long expired, sampled;

        redisDb *db = server.db+(current_db % server.dbnum);

        /* Increment the DB now so we are sure if we run out of time
         * in the current DB we'll restart from the next. This allows to
         * distribute the time evenly across DBs. */
        current_db++;

        /* Continue to expire if at the end of the cycle there are still
         * a big percentage of keys to expire, compared to the number of keys
         * we scanned. The percentage, stored in config_cycle_acceptable_stale
         * is not fixed, but depends on the Redis configured "expire effort". */
        do {
            unsigned long num, slots;
            long long now, ttl_sum;
            int ttl_samples;
            iteration++;

            /* If there is nothing to expire try next DB ASAP. */
            if ((num = dictSize(db->expires)) == 0) {
                db->avg_ttl = 0;
                break;
            }
            slots = dictSlots(db->expires);
            now = mstime();

            /* When there are less than 1% filled slots, sampling the key
             * space is expensive, so stop here waiting for better times...
             * The dictionary will be resized asap. */
            if (slots > DICT_HT_INITIAL_SIZE &&
                (num*100/slots < 1)) break;

            /* The main collection cycle. Sample random keys among keys
             * with an expire set, checking for expired ones. */
            expired = 0;
            sampled = 0;
            ttl_sum = 0;
            ttl_samples = 0;

            if (num > config_keys_per_loop)
                num = config_keys_per_loop;

            /* Here we access the low level representation of the hash table
             * for speed concerns: this makes this code coupled with dict.c,
             * but it hardly changed in ten years.
             *
             * Note that certain places of the hash table may be empty,
             * so we want also a stop condition about the number of
             * buckets that we scanned. However scanning for free buckets
             * is very fast: we are in the cache line scanning a sequential
             * array of NULL pointers, so we can scan a lot more buckets
             * than keys in the same time. */
            long max_buckets = num*20;
            long checked_buckets = 0;

            while (sampled < num && checked_buckets < max_buckets) {
                for (int table = 0; table < 2; table++) {
                    if (table == 1 && !dictIsRehashing(db->expires)) break;

                    unsigned long idx = db->expires_cursor;
                    idx &= db->expires->ht[table].sizemask;
                    dictEntry *de = db->expires->ht[table].table[idx];
                    long long ttl;

                    /* Scan the current bucket of the current table. */
                    checked_buckets++;
                    while(de) {
                        /* Get the next entry now since this entry may get
                         * deleted. */
                        dictEntry *e = de;
                        de = de->next;

                        ttl = dictGetSignedIntegerVal(e)-now;
                        if (activeExpireCycleTryExpire(db,e,now)) expired++;
                        if (ttl > 0) {
                            /* We want the average TTL of keys yet
                             * not expired. */
                            ttl_sum += ttl;
                            ttl_samples++;
                        }
                        sampled++;
                    }
                }
                db->expires_cursor++;
            }
            total_expired += expired;
            total_sampled += sampled;

            /* Update the average TTL stats for this database. */
            if (ttl_samples) {
                long long avg_ttl = ttl_sum/ttl_samples;

                /* Do a simple running average with a few samples.
                 * We just use the current estimate with a weight of 2%
                 * and the previous estimate with a weight of 98%. */
                if (db->avg_ttl == 0) db->avg_ttl = avg_ttl;
                db->avg_ttl = (db->avg_ttl/50)*49 + (avg_ttl/50);
            }

            /* We can't block forever here even if there are many keys to
             * expire. So after a given amount of milliseconds return to the
             * caller waiting for the other active expire cycle. */
            if ((iteration & 0xf) == 0) { /* check once every 16 iterations. */
                elapsed = ustime()-start;
                if (elapsed > timelimit) {
                    timelimit_exit = 1;
                    server.stat_expired_time_cap_reached_count++;
                    break;
                }
            }
            /* We don't repeat the cycle for the current database if there are
             * an acceptable amount of stale keys (logically expired but yet
             * not reclaimed). */
        } while (sampled == 0 ||
                 (expired*100/sampled) > config_cycle_acceptable_stale);
    }

    elapsed = ustime()-start;
    server.stat_expire_cycle_time_used += elapsed;
    latencyAddSampleIfNeeded("expire-cycle",elapsed/1000);

    /* Update our estimate of keys existing but yet to be expired.
     * Running average with this sample accounting for 5%. */
    double current_perc;
    if (total_sampled) {
        current_perc = (double)total_expired/total_sampled;
    } else
        current_perc = 0;
    server.stat_expired_stale_perc = (current_perc*0.05)+
                                     (server.stat_expired_stale_perc*0.95);
}
```

Set:

- Insert the element in top



## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)

## References