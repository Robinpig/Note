## Introduction

quicklistNode是一个双向链表, 链表每个节点都是 ziplist

quicklist 是一个 40 字节的结构体（64 位系统上），用于描述一个 quicklist。

- 'count' 是总的条目数。
- 'len' 是 quicklist 节点的数量。
- 'compress' 是：0 表示未启用压缩，否则表示 quicklist 两端未压缩的 quicklistNode 数量。
- 'fill' 是用户请求的（或默认的）填充因子。
- 'bookmarks' 是一个可选功能，用于 realloc 此结构体，以便在不使用时不会消耗内存。

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

quicklistNode 是一个 32 字节的结构体，用于描述 quicklist 的一个 ziplist。
我们使用位字段将 quicklistNode 保持在 32 字节。
- count: 16 位，最大 65536（最大 zl 字节是 65k，因此最大实际 count < 32k）。
- encoding: 2 位，RAW=1, LZF=2。
- container: 2 位，NONE=1, ZIPLIST=2。
- recompress: 1 位，布尔值，表示节点是否因使用而临时解压缩。
- attempted_compress: 1 位，布尔值，用于在测试期间验证。
- extra: 10 位，供将来使用；填充剩余的 32 位。

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

Lists 也以一种特殊方式进行编码以节省大量空间。
每个内部列表节点允许的条目数可以指定为固定最大大小或最大元素数量。
对于固定最大大小，使用 -5 到 -1，含义如下：

- -5: 最大大小: 64 Kb  <-- 不建议用于正常工作负载
- -4: 最大大小: 32 Kb  <-- 不建议
- -3: 最大大小: 16 Kb  <-- 可能不建议
- -2: 最大大小: 8 Kb   <-- 良好
- -1: 最大大小: 4 Kb   <-- 良好

正数表示每个列表节点存储恰好该数量的元素。
性能最高的选项通常是 -2（8 Kb 大小）或 -1（4 Kb 大小），但如果你的使用场景特殊，请根据需要调整设置。

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
