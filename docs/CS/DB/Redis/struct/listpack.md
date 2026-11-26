# Redis Listpack: Source Deep Dive

## Introduction

Listpack 是「字符串/整数的序列化列表格式」，是 ziplist 的接替者。7.0 起 Redis 用它替换 ziplist 作为 hash / zset / list / quicklist 节点的紧凑编码。

> 版本基线：Redis 8.10.2（commit 498ecd0d）。以下片段均取自该 tag，路径为 `src/` 相对路径。

两个关键点：

- **为什么替换 ziplist：消除级联更新**。ziplist 每个 entry 记录「前一个 entry 的长度」（prevlen），前驱长度跨越 254 字节边界变化时，本 entry 的 prevlen 字段要扩容，进而可能触发后续所有 entry 连锁扩容（详见 [Ziplist 历史篇](/docs/CS/DB/Redis/struct/ziplist.md)）。listpack 改成每个 entry **自描述自身长度**（backlen 放在 entry 尾部，可反向遍历），插入/删除只影响本节点，不再级联。
- **每个 entry 是 string 或 integer**：整数直接编码进 entry，不存字符序列；`listpackEntry` 是遍历时对外暴露的解析结果结构。

```c
/* Each entry in the listpack is either a string or an integer. */
typedef struct {
    /* When string is used, it is provided with the length (slen). */
    unsigned char *sval;
    uint32_t slen;
    /* When integer is used, 'sval' is NULL, and lval holds the value. */
    long long lval;
} listpackEntry;
```

## Layout: header + entries + EOF

`LP_HDR_SIZE` = 6 字节（32 位总字节数 + 16 位元素数），末尾是 `LP_EOF`（0xFF）。这是 8.10.2 的真实定义：

```c
#define LP_HDR_SIZE 6       /* 32 bit total len + 16 bit number of elements. */
#define LP_EOF 0xFF
```

## lpNew

创建一个空 listpack：至少分配 `LP_HDR_SIZE+1` 字节，写入总字节数、元素数 0，末尾放 `LP_EOF`。

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

## lpFirst / traversal

`lpFirst` 跳过 6 字节 header，若首字节即 `LP_EOF` 说明空表。反向遍历靠每个 entry 尾部的 backlen（见下面 `lpInsert` 里的 `lpEncodeBacklen` 注释）。

```c
unsigned char *lpFirst(unsigned char *lp) {
    unsigned char *p = lp + LP_HDR_SIZE; /* Skip the header. */
    if (p[0] == LP_EOF) return NULL;
    lpAssertValidEntry(lp, lpBytes(lp), p);
    return p;
}
```

## lpGet

`lpGet` 解析一个 entry：返回字符串指针（通过 `count` 回传长度）或 NULL 表示是整数（整数值放 `intbuf`）。`lpGetValue` 在其上封装出「字符串给 slen、整数给 lval」的便捷接口。

```c
unsigned char *lpGet(unsigned char *p, int64_t *count, unsigned char *intbuf) {
    return lpGetWithBuf(p, count, intbuf);
}

/* This is just a wrapper to lpGet() that is able to get entry value directly.
 * When the function returns NULL, it populates the integer value by reference in 'lval'.
 * Otherwise if the element is encoded as a string a pointer to the string (pointing
 * inside the listpack itself) is returned, and 'slen' is set to the length of the
 * string. */
unsigned char *lpGetValue(unsigned char *p, unsigned int *slen, long long *lval) {
    unsigned char *vstr;
    int64_t ele_len;

    vstr = lpGet(p, &ele_len, NULL);
    if (vstr) {
        *slen = ele_len;
    } else {
        *lval = ele_len;
    }
    return vstr;
```

## lpInsert

`lpInsert` 是核心写入函数，同时承担插入、替换、删除（`elestr == NULL && eleint == NULL` 即删除）。关键点：

- `LP_AFTER` 被归一化成「跳到下一个元素再 LP_BEFORE」，所以内部只处理 `LP_BEFORE` 与 `LP_REPLACE` 两种。
- 用 `poff = p - lp` 记录偏移，realloc 后重新定位，避免指针失效。
- `lpEncodeBacklen` 把「本 entry 长度」编码到 entry 尾部，用于反向遍历——这正是**不记录前驱长度、因此无级联更新**的结构原因。

```c
unsigned char *lpInsert(unsigned char *lp, unsigned char *elestr, unsigned char *eleint,
                        uint32_t size, unsigned char *p, int where, unsigned char **newp)
{
    unsigned char intenc[LP_MAX_INT_ENCODING_LEN];
    unsigned char backlen[LP_MAX_BACKLEN_SIZE];

    uint64_t enclen; /* The length of the encoded element. */
    int delete = (elestr == NULL && eleint == NULL);

    /* when deletion, it is conceptually replacing the element with a
     * zero-length element. So whatever we get passed as 'where', set
     * it to LP_REPLACE. */
    if (delete) where = LP_REPLACE;

    /* If we need to insert after the current element, we just jump to the
     * next element (that could be the EOF one) and handle the case of
     * inserting before. So the function will actually deal with just two
     * cases: LP_BEFORE and LP_REPLACE. */
    if (where == LP_AFTER) {
        p = lpSkip(p);
        where = LP_BEFORE;
        ASSERT_INTEGRITY(lp, p);
    }

    /* Store the offset of the element 'p', so that we can obtain its
     * address again after a reallocation. */
    unsigned long poff = p-lp;

    /* ... lpEncodeGetType / enctype 编码略 ... */

    /* We need to also encode the backward-parsable length of the element
     * and append it to the end: this allows to traverse the listpack from
     * the end to the start. */
    unsigned long backlen_size = (!delete) ? lpEncodeBacklen(backlen,enclen) : 0;
    uint64_t old_listpack_bytes = lpGetTotalBytes(lp);
    uint32_t replaced_len  = 0;
    if (where == LP_REPLACE) {
        replaced_len = lpCurrentEncodedSizeUnsafe(p);
        replaced_len += lpEncodeBacklenBytes(replaced_len);
    }

    uint64_t new_listpack_bytes = old_listpack_bytes + enclen + backlen_size
                                  - replaced_len;
    if (new_listpack_bytes > UINT32_MAX) return NULL;
```

## Summary

- Listpack 是 ziplist 的接替者，每个 entry 自描述长度（尾部 backlen），插入删除不级联。
- 核心 API：`lpNew` 建表、`lpFirst`/`lpSeek` 遍历、`lpGet` 解析、`lpInsert` 写入/替换/删除。
- 8.10.2 中 hash、zset、list、quicklist 节点均基于 listpack。

## Links

- [Redis Struct 总纲](/docs/CS/DB/Redis/struct/struct.md?id=lists)
- [Ziplist（历史篇）](/docs/CS/DB/Redis/struct/ziplist.md)
- [Quicklist](/docs/CS/DB/Redis/struct/quicklist.md)
- [Hash](/docs/CS/DB/Redis/struct/hash.md)
- [Zset](/docs/CS/DB/Redis/struct/zset.md)

## References

- <https://github.com/redis/redis/blob/8.10.2/src/listpack.c>
- <https://github.com/redis/redis/blob/8.10.2/src/listpack.h>
