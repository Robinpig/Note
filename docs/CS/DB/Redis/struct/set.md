## Introduction

set是无序集合 

集合类型的经典使用场景如下：

- 微博关注我的人和我关注的人都适合用集合存储，可以保证人员不会重复；
- 中奖人信息也适合用集合类型存储，这样可以保证一个人不会重复中奖





Sets can be encoded as:
  - `hashtable`, normal set encoding.
  - `intset`, a special encoding used for small sets composed solely of integers.
  - `listpack`, Redis >= 7.2, a space-efficient encoding used for small sets.

## sadd

1. [lookupKeyWrite](/docs/CS/DB/Redis/redisDb.md?id=add)
2. [setTypeCreate](/docs/CS/DB/Redis/struct/zset.mdzset.md?id=setTypeCreate)
3. [dbAdd](/docs/CS/DB/Redis/redisDb.md?id=add)
4. [setTypeCreate](/docs/CS/DB/Redis/struct/zset.mdzset.md?id=setTypeAdd)

```c
// server.c
void saddCommand(client *c) {
    robj *set;
    int j, added = 0;

    set = lookupKeyWrite(c->db,c->argv[1]);
    if (checkType(c,set,OBJ_SET)) return;
  
    if (set == NULL) {
        set = setTypeCreate(c->argv[2]->ptr);
        dbAdd(c->db,c->argv[1],set);
    }

    for (j = 2; j < c->argc; j++) {
        if (setTypeAdd(set,c->argv[j]->ptr)) added++;
    }
    if (added) {
        signalModifiedKey(c,c->db,c->argv[1]);
        notifyKeyspaceEvent(NOTIFY_SET,"sadd",c->argv[1],c->db->id);
    }
    server.dirty += added;
    addReplyLongLong(c,added);
}
```

### setTypeCreate

```c
// t_set.c
/* Factory method to return a set that *can* hold "value". When the object has
 * an integer-encodable value, an intset will be returned. Otherwise a regular
 * hash table. */
robj *setTypeCreate(sds value) {
    if (isSdsRepresentableAsLongLong(value,NULL) == C_OK)
        return createIntsetObject();
    return createSetObject();
}

// object.c
robj *createIntsetObject(void) {
    intset *is = intsetNew();
    robj *o = createObject(OBJ_SET,is);
    o->encoding = OBJ_ENCODING_INTSET;
    return o;
}
```

Create intset

```c
// intset.c
/* Create an empty intset. */
intset *intsetNew(void) {
    intset *is = zmalloc(sizeof(intset));
    is->encoding = intrev32ifbe(INTSET_ENC_INT16);
    is->length = 0;
    return is;
}
```

or [create hashtable](/docs/CS/DB/Redis/struct/hash.mdhash.md?id=create)

```c
// object.c
robj *createSetObject(void) {
    dict *d = dictCreate(&setDictType);
    robj *o = createObject(OBJ_SET,d);
    o->encoding = OBJ_ENCODING_HT; // hashtable
    return o;
}
```

### setTypeAdd

[dictAddRaw in hash](/docs/CS/DB/Redis/struct/hash.mdhash.md?id=dictAddRaw)

- if isSdsRepresentableAsLongLong, add to intset, when over max_intset_entries(512) convert to [dict](/docs/CS/DB/Redis/struct/hash.mdhash.md)
- or else [dictAdd](/docs/CS/DB/Redis/redisDb.md?id=add)

```c
// t-set.c
/* Add the specified value into a set.
 *
 * If the value was already member of the set, nothing is done and 0 is
 * returned, otherwise the new element is added and 1 is returned. */
int setTypeAdd(robj *subject, sds value) {
    long long llval;
    if (subject->encoding == OBJ_ENCODING_HT) {
        dict *ht = subject->ptr;
        dictEntry *de = dictAddRaw(ht,value,NULL);
        if (de) {
            dictSetKey(ht,de,sdsdup(value));
            dictSetVal(ht,de,NULL);
            return 1;
        }
    } else if (subject->encoding == OBJ_ENCODING_INTSET) {
        if (isSdsRepresentableAsLongLong(value,&llval) == C_OK) {
            uint8_t success = 0;
            subject->ptr = intsetAdd(subject->ptr,llval,&success);
            if (success) {
                /* Convert to regular set when the intset contains
                 * too many entries. */
                if (intsetLen(subject->ptr) > server.set_max_intset_entries)
                    setTypeConvert(subject,OBJ_ENCODING_HT);
                return 1;
            }
        } else {
            /* Failed to get integer from object, convert to regular set. */
            setTypeConvert(subject,OBJ_ENCODING_HT);

            /* The set *was* an intset and this value is not integer
             * encodable, so dictAdd should always work. */
            serverAssert(dictAdd(subject->ptr,sdsdup(value),NULL) == DICT_OK);
            return 1;
        }
    } else {
        serverPanic("Unknown set encoding");
    }
    return 0;
}
```
## Summary


Set 的差集、并集和交集的计算复杂度较高，在数据量较大的情况下，如果直接执行这些计算，会导致 Redis 实例阻塞。所以，我给你分享一个小建议：你可以从主从集群中选择一个从库，让它专门负责聚合计算，或者是把数据读取到客户端，在客户端来完成聚合统计，这样就可以规避阻塞主库实例和其他从库实例的风险了


## Links

- [Redis Struct](/docs/CS/DB/Redis/struct/struct.mdruct.md?id=sets)
