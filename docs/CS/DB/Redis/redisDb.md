## Introduction

The most important functions inside `db.c` which are used in many command implementations are the following:
* [lookupKeyRead()](/docs/CS/DB/Redis/redisDb.md?id=lookupKey) and [lookupKeyWrite()](/docs/CS/DB/Redis/redisDb.md?id=lookupKey) are used in order to get a pointer to the value associated to a given key, or `NULL` if the key does not exist.
* [dbAdd()](/docs/CS/DB/Redis/redisDb.md?id=add) and its higher level counterpart `setKey()` create a new key in a Redis database.
* [dbDelete()](/docs/CS/DB/Redis/redisDb.md?id=delete) removes a key and its associated value.
* `emptyDb()` removes an entire single database or all the databases defined.




```java
// server.h
/* Redis database representation. There are multiple databases identified
 * by integers from 0 (the default database) up to the max configured
 * database. The database number is the 'id' field in the structure. */
typedef struct redisDb {
    dict *dict;                 /* The keyspace for this DB */
    dict *expires;              /* Timeout of keys with a timeout set */
    dict *blocking_keys;        /* Keys with clients waiting for data (BLPOP)*/
    dict *ready_keys;           /* Blocked keys that received a PUSH */
    dict *watched_keys;         /* WATCHED keys for MULTI/EXEC CAS */
    int id;                     /* Database ID */
    long long avg_ttl;          /* Average TTL, just for stats */
    unsigned long expires_cursor; /* Cursor of the active expire cycle. */
    list *defrag_later;         /* List of key names to attempt to defrag one by one, gradually. */
} redisDb;
```



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



## redisObject


Basically this structure can represent all the basic Redis data types like strings, lists, sets, sorted sets and so forth. The interesting thing is that it has a `type` field, so that it is possible to know what type a given object has, and a `refcount`, so that the same object can be referenced in multiple places without allocating it multiple times. Finally the `ptr` field points to the actual representation of the object, which might vary even for the same type, depending on the `encoding` used.

**Layout:** 16bytes
- type : 4bits get type by `type keyName`
- encoding : 4bits get encoding  by `object encoding keyName`
- lru : 24bits
- refcount : 4bytes
- *ptr : 8bytes

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

Redis objects are used extensively in the Redis internals, however in order to avoid the overhead of indirect accesses, recently in many places we just use plain dynamic strings not wrapped inside a Redis object.

The `robj` structure defining Redis objects was already described. Inside `object.c` there are all the functions that operate with Redis objects at a basic level, like functions to allocate new objects, handle the reference counting and so forth. Notable functions inside this file:

- `incrRefCount()` and `decrRefCount()` are used in order to increment or decrement an object reference count. When it drops to 0 the object is finally freed.
- [createObject()](/docs/CS/DB/Redis/redisDb.md?id=createObject) allocates a new object. There are also specialized functions to allocate string objects having a specific content, like `createStringObjectFromLongLong()` and similar functions.



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

/* Low level key lookup API, not actually called directly from commands
 * implementations that should instead rely on lookupKeyRead(),
 * lookupKeyWrite() and lookupKeyReadWithFlags(). */
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

### updateLFU
- ldt
- counter
```c
// db.c
/* Update LFU when an object is accessed.
 * Firstly, decrement the counter if the decrement time is reached.
 * Then logarithmically increment the counter, and update the access time. */
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

```
/* If the object decrement time is reached decrement the LFU counter but
 * do not update LFU fields of the object, we update the access time
 * and counter in an explicit way when the object is really accessed.
 * And we will times halve the counter according to the times of
 * elapsed time than server.lfu_decay_time.
 * Return the object frequency counter.
 *
 * This function is used in order to scan the dataset for the best object
 * to fit: as we check for the candidate, we incrementally decrement the
 * counter of the scanned objects if needed. */
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

```c
// db.c
/* This is a wrapper whose behavior depends on the Redis lazy free
 * configuration. Deletes the key synchronously or asynchronously. */
int dbDelete(redisDb *db, robj *key) {
    return server.lazyfree_lazy_server_del ? dbAsyncDelete(db,key) :
                                             dbSyncDelete(db,key);
}
```

```c
// db.c
/* Delete a key, value, and associated expiration entry if any, from the DB.
 * If there are enough allocations to free the value object may be put into
 * a lazy free list instead of being freed synchronously. The lazy free list
 * will be reclaimed in a different bio.c thread. */
#define LAZYFREE_THRESHOLD 64
int dbAsyncDelete(redisDb *db, robj *key) {
    /* Deleting an entry from the expires dict will not free the sds of
     * the key, because it is shared with the main dictionary. */
    if (dictSize(db->expires) > 0) dictDelete(db->expires,key->ptr);

    /* If the value is composed of a few allocations, to free in a lazy way
     * is actually just slower... So under a certain limit we just free
     * the object synchronously. */
    dictEntry *de = dictUnlink(db->dict,key->ptr);
    if (de) {
        robj *val = dictGetVal(de);

        /* Tells the module that the key has been unlinked from the database. */
        moduleNotifyKeyUnlink(key,val);

        size_t free_effort = lazyfreeGetFreeEffort(key,val);

        /* If releasing the object is too much work, do it in the background
         * by adding the object to the lazy free list.
         * Note that if the object is shared, to reclaim it now it is not
         * possible. This rarely happens, however sometimes the implementation
         * of parts of the Redis core may call incrRefCount() to protect
         * objects, and then call dbDelete(). In this case we'll fall
         * through and reach the dictFreeUnlinkedEntry() call, that will be
         * equivalent to just calling decrRefCount(). */
        if (free_effort > LAZYFREE_THRESHOLD && val->refcount == 1) {
            atomicIncr(lazyfree_objects,1);
            bioCreateLazyFreeJob(lazyfreeFreeObject,1, val);
            dictSetVal(db->dict,de,NULL);
        }
    }

    /* Release the key-val pair, or just the key if we set the val
     * field to NULL in order to lazy free it later. */
    if (de) {
        dictFreeUnlinkedEntry(db->dict,de);
        if (server.cluster_enabled) slotToKeyDel(key->ptr);
        return 1;
    } else {
        return 0;
    }
}
```
### dictDelete

```c
// dict.c
/* Remove an element, returning DICT_OK on success or DICT_ERR if the
 * element was not found. */
int dictDelete(dict *ht, const void *key) {
    return dictGenericDelete(ht,key,0) ? DICT_OK : DICT_ERR;
}


/* Search and remove an element. This is an helper function for
 * dictDelete() and dictUnlink(), please check the top comment
 * of those functions. */
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


## resize
call by databaseCron

[rehash](/docs/CS/DB/Redis/hash.md?id=rehash) or [expand](/docs/CS/DB/Redis/hash.md?id=expand) when filled less than 10%
```c
// server.c
/* If the percentage of used slots in the HT reaches HASHTABLE_MIN_FILL
 * we resize the hash table to save memory */
void tryResizeHashTables(int dbid) {
    if (htNeedsResize(server.db[dbid].dict))
        dictResize(server.db[dbid].dict);
    if (htNeedsResize(server.db[dbid].expires))
        dictResize(server.db[dbid].expires);
}


/* This is the initial size of every hash table */
#define DICT_HT_INITIAL_SIZE     4

/* Hash table parameters */
#define HASHTABLE_MIN_FILL        10      /* Minimal hash table fill 10% */

int htNeedsResize(dict *dict) {
    long long size, used;

    size = dictSlots(dict);
    used = dictSize(dict);
    return (size > DICT_HT_INITIAL_SIZE &&
            (used*100/size < HASHTABLE_MIN_FILL));
}



/* Resize the table to the minimal size that contains all the elements,
 * but with the invariant of a USED/BUCKETS ratio near to <= 1 */
int dictResize(dict *d)
{
    unsigned long minimal;

    if (!dict_can_resize || dictIsRehashing(d)) return DICT_ERR;
    minimal = d->ht[0].used;
    if (minimal < DICT_HT_INITIAL_SIZE)
        minimal = DICT_HT_INITIAL_SIZE;
    return dictExpand(d, minimal);
}
```

## Summary
Set:
- Insert the element in top
