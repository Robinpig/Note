## Introduction



quicklist is a 40 byte struct (on 64-bit systems) describing a quicklist.

- 'count' is the number of total entries.
- 'len' is the number of quicklist nodes.
- 'compress' is: 0 if compression disabled, otherwise it's the number of quicklistNodes to leave uncompressed at ends of quicklist.
- 'fill' is the user-requested (or default) fill factor.
- 'bookmakrs are an optional feature that is used by realloc this struct, so that they don't consume memory when not used.

```c
typedef struct quicklist {
    quicklistNode *head;
    quicklistNode *tail;
    unsigned long count;        /* total count of all entries in all ziplists */
    unsigned long len;          /* number of quicklistNodes */
    int fill : QL_FILL_BITS;              /* fill factor for individual nodes */
    unsigned int compress : QL_COMP_BITS; /* depth of end nodes not to compress;0=off */
    unsigned int bookmark_count: QL_BM_BITS;
    quicklistBookmark bookmarks[];
} quicklist;
```

quicklistNode是一个双向链表, 链表每个节点都是 ziplist

quicklistNode is a 32 byte struct describing a ziplist for a quicklist.
We use bit fields keep the quicklistNode at 32 bytes.
- count: 16 bits, max 65536 (max zl bytes is 65k, so max count actually < 32k).
- encoding: 2 bits, RAW=1, LZF=2.
- container: 2 bits, NONE=1, ZIPLIST=2.
- recompress: 1 bit, bool, true if node is temporary decompressed for usage.
- attempted_compress: 1 bit, boolean, used for verifying during testing.
- extra: 10 bits, free for future use; pads out the remainder of 32 bits

```c
typedef struct quicklistNode {
    struct quicklistNode *prev;
    struct quicklistNode *next;
    unsigned char *zl;
    unsigned int sz;             /* ziplist size in bytes */
    unsigned int count : 16;     /* count of items in ziplist */
    unsigned int encoding : 2;   /* RAW==1 or LZF==2 */
    unsigned int container : 2;  /* NONE==1 or ZIPLIST==2 */
    unsigned int recompress : 1; /* was this node previous compressed? */
    unsigned int attempted_compress : 1; /* node can't compress; too small */
    unsigned int extra : 10; /* more bits to steal for future usage */
} quicklistNode;
```

从数据结构上看quicklist的设计重点在于控制每个ziplist的大小和元素个数 有效减少了在 ziplist 中新增或修改元素后，发生连锁更新的情况

- 单个ziplist的过小就会退化成linkedlist
- 单个ziplist过大极端情况下只有一个ziplist同样无法避免级联更新


Lists are also encoded in a special way to save a lot of space.
The number of entries allowed per internal list node can be specified as a fixed maximum size or a maximum number of elements.
For a fixed maximum size, use -5 through -1, meaning:

- -5: max size: 64 Kb  <-- not recommended for normal workloads
- -4: max size: 32 Kb  <-- not recommended
- -3: max size: 16 Kb  <-- probably not recommended
- -2: max size: 8 Kb   <-- good
- -1: max size: 4 Kb   <-- good

Positive numbers mean store up to _exactly_ that number of elements per list node.
The highest performing option is usually -2 (8 Kb size) or -1 (4 Kb size), but if your use case is unique, adjust the settings as necessary.

```conf
list-max-ziplist-size -2
```


## quicklistCreate

```c
// quicklist.c
// Create a new quicklist. Free with quicklistRelease().
quicklist *quicklistCreate(void) {
    struct quicklist *quicklist;

    quicklist = zmalloc(sizeof(*quicklist));
    quicklist->head = quicklist->tail = NULL;
    quicklist->len = 0;
    quicklist->count = 0;
    quicklist->compress = 0;
    quicklist->fill = -2;
    quicklist->bookmark_count = 0;
    return quicklist;
}
```

convertFromZiplist in rdb.c

```c
// t_list.c

/* The function pushes an element to the specified list object 'subject',
 * at head or tail position as specified by 'where'.
 *
 * There is no need for the caller to increment the refcount of 'value' as
 * the function takes care of it if needed. */
void listTypePush(robj *subject, robj *value, int where) {
    if (subject->encoding == OBJ_ENCODING_QUICKLIST) {
        int pos = (where == LIST_HEAD) ? QUICKLIST_HEAD : QUICKLIST_TAIL;
        if (value->encoding == OBJ_ENCODING_INT) {
            char buf[32];
            ll2string(buf, 32, (long)value->ptr);
            quicklistPush(subject->ptr, buf, strlen(buf), pos);
        } else {
            quicklistPush(subject->ptr, value->ptr, sdslen(value->ptr), pos);
        }
    } else {
        serverPanic("Unknown list encoding");
    }
}
```

call [ziplistPush](/docs/CS/DB/Redis/struct/zset.mdzset.md?id=insert)

```c
//quicklist.c

/* Wrapper to allow argument-based switching between HEAD/TAIL pop */
void quicklistPush(quicklist *quicklist, void *value, const size_t sz,
                   int where) {
    if (where == QUICKLIST_HEAD) {
        quicklistPushHead(quicklist, value, sz);
    } else if (where == QUICKLIST_TAIL) {
        quicklistPushTail(quicklist, value, sz);
    }
}

/* Add new entry to head node of quicklist.
 *
 * Returns 0 if used existing head.
 * Returns 1 if new head created. */
int quicklistPushHead(quicklist *quicklist, void *value, size_t sz) {
    quicklistNode *orig_head = quicklist->head;
    if (likely(
            _quicklistNodeAllowInsert(quicklist->head, quicklist->fill, sz))) {
        quicklist->head->zl =
            ziplistPush(quicklist->head->zl, value, sz, ZIPLIST_HEAD);
        quicklistNodeUpdateSz(quicklist->head);
    } else {
        quicklistNode *node = quicklistCreateNode();
        node->zl = ziplistPush(ziplistNew(), value, sz, ZIPLIST_HEAD);

        quicklistNodeUpdateSz(node);
        _quicklistInsertNodeBefore(quicklist, quicklist->head, node);
    }
    quicklist->count++;
    quicklist->head->count++;
    return (orig_head != quicklist->head);
}

/* Add new entry to tail node of quicklist.
 *
 * Returns 0 if used existing tail.
 * Returns 1 if new tail created. */
int quicklistPushTail(quicklist *quicklist, void *value, size_t sz) {
    quicklistNode *orig_tail = quicklist->tail;
    if (likely(
            _quicklistNodeAllowInsert(quicklist->tail, quicklist->fill, sz))) {
        quicklist->tail->zl =
            ziplistPush(quicklist->tail->zl, value, sz, ZIPLIST_TAIL);
        quicklistNodeUpdateSz(quicklist->tail);
    } else {
        quicklistNode *node = quicklistCreateNode();
        node->zl = ziplistPush(ziplistNew(), value, sz, ZIPLIST_TAIL);

        quicklistNodeUpdateSz(node);
        _quicklistInsertNodeAfter(quicklist, quicklist->tail, node);
    }
    quicklist->count++;
    quicklist->tail->count++;
    return (orig_tail != quicklist->tail);
}
```

当插入一个新的元素时，quicklist 首先就会检查插入位置的 ziplist 是否能容纳该元素，这是通过 _quicklistNodeAllowInsert 函数来完成判断

```c
REDIS_STATIC int _quicklistNodeAllowInsert(const quicklistNode *node,
                                           const int fill, const size_t sz) {
    if (unlikely(!node))
        return 0;

    if (unlikely(QL_NODE_IS_PLAIN(node) || isLargeElement(sz, fill)))
        return 0;

    /* Estimate how many bytes will be added to the listpack by this one entry.
     * We prefer an overestimation, which would at worse lead to a few bytes
     * below the lowest limit of 4k (see optimization_level).
     * Note: No need to check for overflow below since both `node->sz` and
     * `sz` are to be less than 1GB after the plain/large element check above. */
    size_t new_sz = node->sz + sz + SIZE_ESTIMATE_OVERHEAD;
    if (unlikely(quicklistNodeExceedsLimit(fill, new_sz, node->count + 1)))
        return 0;
    retur
```










## Tuning

quicklist解决了单个ziplist过大 缩小连锁更新的范围



## Links

