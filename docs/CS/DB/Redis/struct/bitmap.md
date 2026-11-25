# Redis Bitmap: Source Deep Dive

## Introduction

Bitmap 不是独立数据类型，而是定义在 [String 类型](/docs/CS/DB/Redis/struct/SDS.md) 上的一组位操作。字符串是二进制安全的 blob，最大 512 MB，因此最多可表示 2^32 个 bit。

> 版本基线：Redis 8.10.2（commit 498ecd0d）。以下片段均取自该 tag，路径为 `src/` 相对路径。

最大优势是省空间：用递增用户 ID 当 offset，4 billion 用户的「是/否」一位信息只需 512 MB。Bitmap 也易于拆分成多个 key（每 key 存 M 个 bit，key 名用 `bit-number/M`、key 内偏移用 `bit-number MOD M`）。

## SETBIT / GETBIT

`setbitCommand` 用 `getBitOffsetFromArgument` 解析 offset，`lookupStringForBitCommand` 在必要时扩容字符串，再定位到字节 `bitoffset >> 3` 与位 `7 - (bitoffset & 0x7)`（高位在前）修改并返回原值。

```c
void setbitCommand(client *c) {
    char *err = "bit is not an integer or out of range";
    uint64_t bitoffset;
    ssize_t byte, bit;
    int byteval, bitval;
    long on;

    if (getBitOffsetFromArgument(c,c->argv[2],&bitoffset,0,0) != C_OK)
        return;

    if (getLongFromObjectOrReply(c,c->argv[3],&on,err) != C_OK)
        return;

    /* Bits can only be set or cleared... */
    if (on & ~1) {
        addReplyError(c,err);
        return;
    }

    size_t strOldSize, strGrowSize;
    kvobj *o = lookupStringForBitCommand(c, bitoffset, &strOldSize, &strGrowSize);
    if (o == NULL) return;

    /* Get current values */
    byte = bitoffset >> 3;
    byteval = ((uint8_t*)o->ptr)[byte];
    bit = 7 - (bitoffset & 0x7);
    bitval = byteval & (1 << bit);

    if (strGrowSize || (!!bitval != on)) {
        byteval &= ~(1 << bit);
        byteval |= ((on & 0x1) << bit);
        ((uint8_t*)o->ptr)[byte] = byteval;
        keyModified(c,c->db,c->argv[1],o,1);
        notifyKeyspaceEvent(NOTIFY_STRING,"setbit",c->argv[1],c->db->id);
        server.dirty++;
    }

    /* Return original value. */
    addReply(c, bitval ? shared.cone : shared.czero);
}
```

`getbitCommand` 类似定位，但对 sds 编码与非 sds（整数编码）对象分别处理；越界返回 0。

```c
/* GETBIT key offset */
void getbitCommand(client *c) {
    char llbuf[32];
    uint64_t bitoffset;
    size_t byte, bit;
    size_t bitval = 0;

    if (getBitOffsetFromArgument(c,c->argv[2],&bitoffset,0,0) != C_OK)
        return;

    kvobj *kv = lookupKeyReadOrReply(c, c->argv[1], shared.czero);
    if (kv == NULL || checkType(c,kv,OBJ_STRING)) return;

    byte = bitoffset >> 3;
    bit = 7 - (bitoffset & 0x7);
    if (sdsEncodedObject(kv)) {
        if (byte < sdslen(kv->ptr))
            bitval = ((uint8_t*)kv->ptr)[byte] & (1 << bit);
    } else {
        if (byte < (size_t)ll2string(llbuf,sizeof(llbuf),(long)kv->ptr))
            bitval = llbuf[byte] & (1 << bit);
    }
```

## Commands

BITOP 在 8.x 支持 `AND` / `OR` / `XOR` / `NOT`，8.2.0 起新增 `DIFF` / `DIFF1` / `ANDOR` / `ONE`。可用 `help @string` 查看。

## Links

- [SDS](/docs/CS/DB/Redis/struct/SDS.md)
- [Redis Struct 总纲](/docs/CS/DB/Redis/struct/struct.md?id=bitmaps)

## References

- <https://github.com/redis/redis/blob/8.10.2/src/bitops.c>
- [Redis bitmaps](https://redis.io/docs/latest/develop/data-types/bitmaps/)
