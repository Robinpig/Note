# Redis Skiplist: Source Deep Dive

## Introduction

跳表（skiplist）是 Sorted Set 在 SKIPLIST 编码下的有序索引结构：按 `score` 排序，`score` 相同再按成员 `ele`（sds）字典序。它和 dict 一起构成 `zset`——dict 负责 O(1) 查成员，跳表负责范围查询与 rank。

> 版本基线：Redis 8.10.2（commit 498ecd0d）。以下片段均取自该 tag，路径为 `src/` 相对路径。

三个最容易被旧资料误导的点：

- **`ele` 不再是独立字段**：8.10.2 把 sds **嵌入到节点分配里**（`node + level[] + embedded sds` 单块内存），`zskiplistNode` 结构体里已没有 `sds ele` 成员，靠 `zslGetNodeElement(node)` 按偏移取。
- **`level[0].span` 被复用**：普通节点在 level 0 的 `span` 不存跨度，而是存 `zskiplistNodeInfo`（内嵌 sds 的偏移 + 层数）；真正的 level-0 跨度在需要时由结构体推导。这是 8.x 为省内存做的紧凑化。
- **`zskiplist` 多了 `alloc_size`**：跟踪整条跳表的分配字节数；`zslCreate`/`zslFree` 用 `zmalloc_usable` 系列记账。

## Structure: zskiplistNode / zskiplist

8.10.2 的节点结构：`score` + `backward` + 柔性数组 `level[]`，sds 嵌在 `level[]` 之后。注意 `zskiplistNodeInfo` 的说明注释原文。

```c
/* Node info placed in level[0].span since it's unused at level 0 (static assert verified) */
typedef struct zskiplistNodeInfo {
    uint16_t sdsoffset;  /* Offset from node start to sds data (after sds header) */
    uint8_t levels;      /* Number of levels in this node (1-32) */
    uint8_t reserved;
} zskiplistNodeInfo;

typedef struct zskiplistNode {
    double score;
    struct zskiplistNode *backward;
    struct zskiplistLevel {
        struct zskiplistNode *forward;
        /* Span is the number of elements between this node and the next node at this level.
         * At level 0, span is repurposed to store zskiplistNodeInfo for regular nodes, */
        unsigned long span;
    } level[];
    /* sds ele is embedded after level[] array (assist zslGetNodeElement(node) to access it) */
} zskiplistNode;
```

跳表本身多了 `alloc_size`：

```c
typedef struct zskiplist {
    struct zskiplistNode *header, *tail;
    unsigned long length;
    int level;
    size_t alloc_size;
} zskiplist;
```

`zset`（SKIPLIST 编码对象）仍是 dict + 跳表两成员：

```c
typedef struct zset {
    dict *dict;
    zskiplist *zsl;
} zset;
```

## Create: zslCreate / zslCreateHeaderNode

8.10.2 把表头创建抽成 `zslCreateHeaderNode`，用 `ZSL_OFFSET_NO_ELE` 哨兵表示「无内嵌 sds」，并对 `alloc_size` 记账；普通节点 `zslCreateNode` 把 sds 用 `sdsnewplacement` 嵌进同一块分配。

```c
/* Create a skiplist header node with ZSKIPLIST_MAXLEVEL levels */
static zskiplistNode *zslCreateHeaderNode(zskiplist *zsl) {
    size_t usable;
    zskiplistNode *zn = zmalloc_usable(sizeof(*zn) + ZSKIPLIST_MAXLEVEL * sizeof(struct zskiplistLevel), &usable);

    /* Initialize all fields */
    zn->score = 0;
    zn->backward = NULL;

    /* Initialize all level pointers and spans */
    for (int j = 0; j < ZSKIPLIST_MAXLEVEL; j++) {
        zn->level[j].forward = NULL;
        zn->level[j].span = 0;  /* Will be overwritten for level[0] below */
    }

    /* Use ZSL_OFFSET_NO_ELE as sentinel to indicate no embedded sds (header node) */
    zslSetNodeInfo(zn, ZSKIPLIST_MAXLEVEL, ZSL_OFFSET_NO_ELE);

    /* Track allocation size */
    zsl->alloc_size += usable;

    return zn;
}

/* Create a new skiplist. */
zskiplist *zslCreate(void) {
    zskiplist *zsl;
    size_t zsl_size;

    zsl = zmalloc_usable(sizeof(*zsl), &zsl_size);
    zsl->level = 1;
    zsl->length = 0;
    zsl->alloc_size = zsl_size;
    zsl->header = zslCreateHeaderNode(zsl);
    zsl->header->backward = NULL;
    zsl->tail = NULL;
    return zsl;
}
```

## Insert: zslInsert

插入被拆成两步：`zslCreateNode` 分配节点并生成随机层数，`zslInsertNode` 负责找位置、改 forward/backward/span。`zslInsert` 只做编排：

```c
zskiplistNode *zslInsert(zskiplist *zsl, double score, sds ele) {
    int level;

    serverAssert(!isnan(score));

    /* we assume the element is not already inside, since we allow duplicated
     * scores, reinserting the same element should never happen since the
     * caller of zslInsert() should test in the hash table if the element is
     * already inside or not. */
    level = zslRandomLevel();
    zskiplistNode *node = zslCreateNode(zsl, level, score, ele);
    zslInsertNode(zsl, node);
    return node;
}
```

`zslInsertNode` 内部用 `update[]` 记录每层待改前驱、`rank[]` 累加跨度，用于 rank 计算：

```c
    zskiplistNode *update[ZSKIPLIST_MAXLEVEL];  /* Nodes that will point to the new node at each level */
    unsigned long rank[ZSKIPLIST_MAXLEVEL];     /* Rank (0-based) at each level during traversal */
    zskiplistNode *x;
    int i, level;
    double score = node->score;
    sds ele = zslGetNodeElement(node);
    level = zslGetNodeInfo(node)->levels;
    serverAssert(!isnan(score));
```

## Random Level

随机层数：返回值 1..`ZSKIPLIST_MAXLEVEL`，呈幂律分布，越高层概率越低。8.10.2 用 `static const int threshold = ZSKIPLIST_P*RAND_MAX` 预计算阈值（旧版本用 `random()&0xFFFF`）。

```c
/* Returns a random level for the new skiplist node we are going to create.
 * The return value of this function is between 1 and ZSKIPLIST_MAXLEVEL
 * (both inclusive), with a powerlaw-alike distribution where higher
 * levels are less likely to be returned. */
static int zslRandomLevel(void) {
    static const int threshold = ZSKIPLIST_P*RAND_MAX;
    int level = 1;
    while (random() < threshold)
        level += 1;
    return (level<ZSKIPLIST_MAXLEVEL) ? level : ZSKIPLIST_MAXLEVEL;
}
```

`ZSKIPLIST_P = 0.25`，期望层数 $E = 1/(1-p) ≈ 1.33$：

```tex
E = 1/(1-p)
```

## Delete / Update: zslUnlinkNode / zslDelete / zslUpdateScore

删除拆成「断链」与「释放」：`zslUnlinkNode` 改 span/forward/backward 并可能降低跳表高度，`zslDelete` 定位节点后断链再 `zslFreeNode`。8.10.2 用 `zslIncrNodeSpanAtLevel`/`zslDecrNodeSpanAtLevel` 操作跨度（不再直接读写 `span` 字段，因为 level 0 的 span 被复用了）。

```c
static void zslUnlinkNode(zskiplist *zsl, zskiplistNode *x, zskiplistNode **update) {
    int i;
    for (i = 0; i < zsl->level; i++) {
        if (update[i]->level[i].forward == x) {
            zslIncrNodeSpanAtLevel(update[i], i, zslGetNodeSpanAtLevel(x, i) - 1);
            update[i]->level[i].forward = x->level[i].forward;
        } else {
            zslDecrNodeSpanAtLevel(update[i], i, 1);
        }
    }
    if (x->level[0].forward) {
        x->level[0].forward->backward = x->backward;
    } else {
        zsl->tail = x->backward;
    }
    while(zsl->level > 1 && zsl->header->level[zsl->level-1].forward == NULL) {
        zsl->header->level[zsl->level-1].span = 0;
        zsl->level--;
    }
    zsl->length--;
}
```

`zslUpdateScore(zskiplist *zsl, zskiplistNode *node, double newscore)` 直接传节点指针：若新 score 不改变位置则原地更新（快路径），否则断链重插；**节点指针始终不变**，所以 dict 无需更新（这正是上一版 zsetAdd 里删掉 `dictGetVal(de) = &znode->score` 的原因）。

## Summary

- 跳表按 score + 成员字典序排序，配合 dict 构成 SKIPLIST 编码的 zset。
- 8.10.2 把 sds 内嵌进节点、复用 level[0].span 存节点信息、新增 alloc_size 记账——旧版结构片段已失效。
- 插入/删除/改分分别由 `zslInsert`、`zslDelete`、`zslUpdateScore` 完成，rank 靠各层 span 累加。

## Links

- [Sorted sets](/docs/CS/DB/Redis/struct/zset.md)
- [SDS](/docs/CS/DB/Redis/struct/SDS.md)
- [Redis Struct 总纲](/docs/CS/DB/Redis/struct/struct.md)

## References

- <https://github.com/redis/redis/blob/8.10.2/src/t_zset.c>
- <https://github.com/redis/redis/blob/8.10.2/src/server.h>
