## Introduction


listpack和ziplist的区别是element不像zentry一样保存prelen

ZipList 会有连锁更新的问题，最根本的原因就是因为 prevlen 的存在，当 ZipList 新增某个元素或修改某个元素时，如果空间不不够，压缩列表占用的内存空间就需要重新分配。而当新插入的元素较大时，可能会导致后续元素的 prevlen 占用空间都发生变化，从而引起连锁更新问题

ziplist 列表项类似，listpack 列表项也包含了元数据信息和数据本身 它只会包含三个方面内容，分别是当前元素的编码类型（entry-encoding）、元素数据 (entry-data)，以及编码类型和元素数据这两部分的长度 (entry-len)



```c
unsigned char *lpNew(size_t capacity) {
    unsigned char *lp = lp_malloc(capacity > LP_HDR_SIZE+1 ? capacity : LP_HDR_SIZE+1);
    if (lp == NULL) return NULL;
    lpSetTotalBytes(lp,LP_HDR_SIZE+1);
    lpSetNumElements(lp,0);
    lp[LP_HDR_SIZE] = LP_EOF;
    return lp;
}
```



istpack 支持正、反向查询列表

```c
unsigned char *lpFirst(unsigned char *lp) {
    unsigned char *p = lp + LP_HDR_SIZE; /* Skip the header. */
    if (p[0] == LP_EOF) return NULL;
    lpAssertValidEntry(lp, lpBytes(lp), p);
    return p;
}
```









## Links

- [Redis Struct](/docs/CS/DB/Redis/struct.md?id=lists)