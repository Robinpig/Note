## Introduction

Redis的list是一种线性的有序结构 可以用于实现队列、栈

list的底层数据结构一直在进行优化 从早期的linkedlist和ziplist 到3.2引入的linkedlist与ziplist组成的quicklist 再到7.0版本中的listpack

这些都是为了在内存空间开销和访问性能之间做取舍



列表的典型使用场景有以下两个：

- 消息队列：列表类型可以使用 rpush 实现先进先出的功能，同时又可以使用 lpop 轻松的弹出（查询并删除）第一个元素，所以列表类型可以用来实现消息队列；
- 文章列表：对于博客站点来说，当用户和文章都越来越多时，为了加快程序的响应速度，我们可以把用户自己的文章存入到 List 中，因为 List 是有序的结构，所以这样又可以完美的实现分页功能，从而加速了程序的响应速度



## linkedlist

Redis 3.2 之前 当list对象满足以下条件时使用 ziplist 否则使用 linkedlist

- 单个元素占用 < 64byte
- 元素数量 < 512

```c
typedef struct list {
    listNode *head;
    listNode *tail;
    void *(*dup)(void *ptr);
    void (*free)(void *ptr);
    int (*match)(void *ptr, void *key);
    unsigned long len; // get size O(1)
} list;

/* Node, List, and Iterator are the only data structures used currently. */
typedef struct listNode {
    struct listNode *prev;
    struct listNode *next;
    void *value;
} listNode;

typedef struct listIter {
    listNode *next;
    int direction;
} listIter;
```
linkedlist的特征
- get head/tail $O(1)$
- get prev/next $O(1)$
- get len $O(1)$
- value void* support multiple types

linkedlist的缺点

- prev/next指针占用空间 在数据本身很小的情况下就显得浪费了
- 链表结构存储 遍历效率低


Lists may also be compressed.
Compress depth is the number of quicklist ziplist nodes from *each* side of the list to *exclude* from compression.
The head and tail of the list are always uncompressed for fast push/pop operations.
Settings are:

- 0: disable all list compression
- 1: depth 1 means "don't start compressing until after 1 node into the list, going from either the head or tail" So: [head]->node->node->...->node->[tail]. [head], [tail] will always be uncompressed; inner nodes will compress.
- 2: [head]->[next]->node->node->...->node->[prev]->[tail] 2 here means: don't compress head or head->next or tail->prev or tail, but compress all nodes between them.
- 3: [head]->[next]->[next]->node->node->...->node->[prev]->[prev]->[tail] etc.

```conf
list-compress-depth 0
```

use in Pub/Sub Monitor

dup free match can be override  by other method

## LPUSH

1. [lookupKeyWrite in db](/docs/CS/DB/Redis/redisDb.md?id=redisObject)
2. [createQuicklistObject](/docs/CS/DB/Redis/struct/list.mdlist.md?id=quicklistCreate)
3. [dbAdd](/docs/CS/DB/Redis/redisDb.md?id=add)

default using quicklist

```c
// t_list.c
/* LPUSH <key> <element> [<element> ...] */
void lpushCommand(client *c) {
    pushGenericCommand(c,LIST_HEAD,0);
}


/* Implements LPUSH/RPUSH/LPUSHX/RPUSHX. 
 * 'xx': push if key exists. */
void pushGenericCommand(client *c, int where, int xx) {
    int j;

    robj *lobj = lookupKeyWrite(c->db, c->argv[1]);
    if (checkType(c,lobj,OBJ_LIST)) return;
    if (!lobj) {
        if (xx) {
            addReply(c, shared.czero);
            return;
        }

        lobj = createQuicklistObject(); // quicklist
        quicklistSetOptions(lobj->ptr, server.list_max_ziplist_size,
                            server.list_compress_depth);
        dbAdd(c->db,c->argv[1],lobj); // add to db
    }

    for (j = 2; j < c->argc; j++) {
        listTypePush(lobj,c->argv[j],where);
        server.dirty++;
    }

    addReplyLongLong(c, listTypeLength(lobj));

    char *event = (where == LIST_HEAD) ? "lpush" : "rpush";
    signalModifiedKey(c,c->db,c->argv[1]);
    notifyKeyspaceEvent(NOTIFY_LIST,event,c->argv[1],c->db->id);
}
```








## Links

- [Redis Struct](/docs/CS/DB/Redis/struct/struct.mdruct.md?id=lists)
