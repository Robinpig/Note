## Introduction


Radix Tree save id, and listpack save message.


```c
typedef struct stream {
    rax *rax;               /* The radix tree holding the stream. */
    uint64_t length;        /* Number of elements inside this stream. */
    streamID last_id;       /* Zero if there are yet no items. */
    rax *cgroups;           /* Consumer groups dictionary: name -> streamCG */
} stream;
```


### streamID
```c
/* Stream item ID: a 128 bit number composed of a milliseconds time and
 * a sequence counter. IDs generated in the same millisecond (or in a past
 * millisecond if the clock jumped backward) will use the millisecond time
 * of the latest generated ID and an incremented sequence. */
typedef struct streamID {
    uint64_t ms;        /* Unix time in milliseconds. */
    uint64_t seq;       /* Sequence number. */
} streamID;
```


```c
// t-stream.c
/* Create a new stream data structure. */
stream *streamNew(void) {
    stream *s = zmalloc(sizeof(*s));
    s->rax = raxNew();
    s->length = 0;
    s->last_id.ms = 0;
    s->last_id.seq = 0;
    s->cgroups = NULL; /* Created on demand to save memory when not used. */
    return s;
}
```


## Rax

Trie Tree
```c
/* Representation of a radix tree as implemented in this file, that contains
 * the strings "foo", "foobar" and "footer" after the insertion of each
 * word. When the node represents a key inside the radix tree, we write it
 * between [], otherwise it is written between ().
 *
 * This is the vanilla representation:
 *
 *              (f) ""
 *                \
 *                (o) "f"
 *                  \
 *                  (o) "fo"
 *                    \
 *                  [t   b] "foo"
 *                  /     \
 *         "foot" (e)     (a) "foob"
 *                /         \
 *      "foote" (r)         (r) "fooba"
 *              /             \
 *    "footer" []             [] "foobar"
 *
 */
 ```

Low level stream encoding: a `radix tree` of `listpacks`.

```c
typedef struct rax {
    raxNode *head;
    uint64_t numele;
    uint64_t numnodes;
} rax;
```

raxNode

```c
typedef struct raxNode {
    uint32_t iskey:1;     /* Does this node contain a key? */
    uint32_t isnull:1;    /* Associated value is NULL (don't store it). */
    uint32_t iscompr:1;   /* Node is compressed. */
    uint32_t size:29;     /* Number of children, or compressed string len. */
   
    unsigned char data[];
} raxNode;
```
Data layout is as follows:

If node is not compressed we have 'size' bytes, one for each children
character, and 'size' raxNode pointers, point to each child node.
Note how the character is not stored in the children but in the
edge of the parents:

> [header iscompr=0][abc][a-ptr][b-ptr][c-ptr](value-ptr?)

if node is compressed (iscompr bit is 1) the node has 1 children.
In that case the 'size' bytes of the string stored immediately at
the start of the data section, represent a sequence of successive
nodes linked one after the other, for which only the last one in
the sequence is actually represented as a node, and pointed to by
the current compressed node.

> [header iscompr=1][xyz][z-ptr](value-ptr?)

Both compressed and not compressed nodes can represent a key
with associated data in the radix tree at any level (not just terminal
nodes).

If the node has an associated key (iskey=1) and is not NULL
(isnull=0), then after the raxNode pointers pointing to the
children, an additional value pointer is present (as you can see
in the representation above as "value-ptr" field).

### raxNew
```c
// rax.c

/* Allocate a new rax and return its pointer. On out of memory the function
 * returns NULL. */
rax *raxNew(void) {
    rax *rax = rax_malloc(sizeof(*rax));
    if (rax == NULL) return NULL;
    rax->numele = 0;
    rax->numnodes = 1;
    rax->head = raxNewNode(0,0);
    if (rax->head == NULL) {
        rax_free(rax);
        return NULL;
    } else {
        return rax;
    }
}
```
Allocate a new non compressed node with the specified number of children.
If datafiled is true, the allocation is made large enough to hold the
associated data pointer.

Returns the new node pointer. On out of memory NULL is returned.

```
raxNode *raxNewNode(size_t children, int datafield) {
    size_t nodesize = sizeof(raxNode)+children+raxPadding(children)+
                      sizeof(raxNode*)*children;
    if (datafield) nodesize += sizeof(void*);
    raxNode *node = rax_malloc(nodesize);
    if (node == NULL) return NULL;
    node->iskey = 0;
    node->isnull = 0;
    node->iscompr = 0;
    node->size = children;
    return node;
}
```

## References
1. [Rax, an ANSI C radix tree implementation](https://github.com/antirez/rax)

