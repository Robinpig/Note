## Introduction


**expire will be delete after set value again** -- set is idempotent

when create string, len=capacity, usually we don't append string.


counter/limiter
cache (shared sessions)

## Type



| Type  | len  | alloc | flag                             | buf  |
| ----- | ---- | ----- | -------------------------------- | ---- |
| hdr5  | /    | /     | 3 lsb of type,  5 msb of  length |      |
| hdr8  | 1    | 1     | 3 lsb of type, 5 unused bits     |      |
| hdr16 | 2    | 2     | 3 lsb of type, 5 unused bits     |      |
| hdr32 | 4    | 4     | 3 lsb of type, 5 unused bits     |      |
| hdr64 | 8    | 8     | 3 lsb of type, 5 unused bits     |      |

`(__packed__)` of 1byte

```c
typedef char *sds;

/* Note: sdshdr5 is never used, we just access the flags byte directly.
 * However is here to document the layout of type 5 SDS strings. */
struct __attribute__ ((__packed__)) sdshdr5 {
    unsigned char flags; /* 3 lsb of type, and 5 msb of string length */
    char buf[];
};
struct __attribute__ ((__packed__)) sdshdr8 {
    uint8_t len; /* used */
    uint8_t alloc; /* excluding the header and null terminator */
    unsigned char flags; /* 3 lsb of type, 5 unused bits */
    char buf[];
};
struct __attribute__ ((__packed__)) sdshdr16 {
    uint16_t len; /* used */
    uint16_t alloc; /* excluding the header and null terminator */
    unsigned char flags; /* 3 lsb of type, 5 unused bits */
    char buf[];
};
struct __attribute__ ((__packed__)) sdshdr32 {
    uint32_t len; /* used */
    uint32_t alloc; /* excluding the header and null terminator */
    unsigned char flags; /* 3 lsb of type, 5 unused bits */
    char buf[];
};
struct __attribute__ ((__packed__)) sdshdr64 {
    uint64_t len; /* used */
    uint64_t alloc; /* excluding the header and null terminator */
    unsigned char flags; /* 3 lsb of type, 5 unused bits */
    char buf[];
};

// 3lsb in flags
#define SDS_TYPE_5  0
#define SDS_TYPE_8  1
#define SDS_TYPE_16 2
#define SDS_TYPE_32 3
#define SDS_TYPE_64 4

#define SDS_TYPE_MASK 7
#define SDS_TYPE_BITS 3
#define SDS_HDR_VAR(T,s) struct sdshdr##T *sh = (void*)((s)-(sizeof(struct sdshdr##T)));
#define SDS_HDR(T,s) ((struct sdshdr##T *)((s)-(sizeof(struct sdshdr##T))))
#define SDS_TYPE_5_LEN(f) ((f)>>SDS_TYPE_BITS)
```



get Length O(1)

```c
// sds.h
static inline size_t sdslen(const sds s) {
    unsigned char flags = s[-1]; // because of packed 1 byte
    switch(flags&SDS_TYPE_MASK) {
        case SDS_TYPE_5:
            return SDS_TYPE_5_LEN(flags);
        case SDS_TYPE_8:
            return SDS_HDR(8,s)->len;
        case SDS_TYPE_16:
            return SDS_HDR(16,s)->len;
        case SDS_TYPE_32:
            return SDS_HDR(32,s)->len;
        case SDS_TYPE_64:
            return SDS_HDR(64,s)->len;
    }
    return 0;
}
```







## setCommand

```c
// server.c
/* Note that we can't flag set as fast, since it may perform an
 * implicit DEL of a large key. */
{"set",setCommand,-3,
 "write use-memory @string",
 0,NULL,1,1,1,0,0,0}
```

Set request:
![Image](https://mmbiz.qpic.cn/mmbiz_png/655VFpRwHAC2CwibLs5ibAm2IZadq8qbsQaAjaK2TTqFPTWibCsdKdXgiazJRJfCENRhpicERvhfyac4A2s7KarIENA/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)



1. tryObjectEncoding
2. setGenericCommand

```c
// t_string.c
/* SET key value [NX] [XX] [KEEPTTL] [EX <seconds>] [PX <milliseconds>] */
void setCommand(client *c) {
    ...
    c->argv[2] = tryObjectEncoding(c->argv[2]);
    setGenericCommand(c,flags,c->argv[1],c->argv[2],expire,unit,NULL,NULL);
}

void setnxCommand(client *c) {
    c->argv[2] = tryObjectEncoding(c->argv[2]);
    setGenericCommand(c,OBJ_SET_NX,c->argv[1],c->argv[2],NULL,0,shared.cone,shared.czero);
}

void setexCommand(client *c) {
    c->argv[3] = tryObjectEncoding(c->argv[3]);
    setGenericCommand(c,OBJ_SET_NO_FLAGS,c->argv[1],c->argv[3],c->argv[2],UNIT_SECONDS,NULL,NULL);
}

void psetexCommand(client *c) {
    c->argv[3] = tryObjectEncoding(c->argv[3]);
    setGenericCommand(c,OBJ_SET_NO_FLAGS,c->argv[1],c->argv[3],c->argv[2],UNIT_MILLISECONDS,NULL,NULL);
}
```

**createStringObject**

```c
// object.c
#define OBJ_ENCODING_EMBSTR_SIZE_LIMIT 44
```

len>44 raw, else embstr.

debug object key

1. 16bytes for [redisObject](/docs/CS/DB/Redis/redisDb.md?id=redisObject)
2. 3bytes for capacity +len +flags
3. 1byte for NULL

jemalloc apply 64byte(for cache line)

so a SDS max **embstr** string len is 64-16-3-1= **44 byte**

```c
// object.c
/* Create a string object with EMBSTR encoding if it is smaller than
 * OBJ_ENCODING_EMBSTR_SIZE_LIMIT, otherwise the RAW encoding is
 * used.
 *
 * The current limit of 44 is chosen so that the biggest string object
 * we allocate as EMBSTR will still fit into the 64 byte arena of jemalloc. */
robj *createStringObject(const char *ptr, size_t len) {
    if (len <= OBJ_ENCODING_EMBSTR_SIZE_LIMIT)
        return createEmbeddedStringObject(ptr,len);
    else
        return createRawStringObject(ptr,len); // createObject & sdsnewlen
}
```


### tryObjectEncoding

This object is encodable as a long. Try to use a shared object when maxmemory is not used

1. INT use shared value or set value to *ptr
2. RAW `createStringObjectFromLongLongWithOptions`
3. EMBSTR `createEmbeddedStringObject`

```c
// object.c
/* Try to encode a string object in order to save space */
robj *tryObjectEncoding(robj *o) {
    long value;
    sds s = o->ptr;
    size_t len;

    /* Make sure this is a string object, the only type we encode
     * in this function. Other types use encoded memory efficient
     * representations but are handled by the commands implementing
     * the type. */
    serverAssertWithInfo(NULL,o,o->type == OBJ_STRING);

    /* We try some specialized encoding only for objects that are
     * RAW or EMBSTR encoded, in other words objects that are still
     * in represented by an actually array of chars. */
    if (!sdsEncodedObject(o)) return o;

    /* It's not safe to encode shared objects: shared objects can be shared
     * everywhere in the "object space" of Redis and may end in places where
     * they are not handled. We handle them only as values in the keyspace. */
     if (o->refcount > 1) return o;

    /* Check if we can represent this string as a long integer.
     * Note that we are sure that a string larger than 20 chars is not
     * representable as a 32 nor 64 bit integer. */
    len = sdslen(s);
    if (len <= 20 && string2l(s,len,&value)) {
        /* This object is encodable as a long. Try to use a shared object.
         * Note that we avoid using shared integers when maxmemory is used
         * because every object needs to have a private LRU field for the LRU
         * algorithm to work well. */
        if ((server.maxmemory == 0 ||
            !(server.maxmemory_policy & MAXMEMORY_FLAG_NO_SHARED_INTEGERS)) &&
            value >= 0 &&
            value < OBJ_SHARED_INTEGERS)
        {
            decrRefCount(o);
            incrRefCount(shared.integers[value]);
            return shared.integers[value];
        } else {
            if (o->encoding == OBJ_ENCODING_RAW) {
                sdsfree(o->ptr);
                o->encoding = OBJ_ENCODING_INT;
                o->ptr = (void*) value; // set value to ptr if int
                return o;
            } else if (o->encoding == OBJ_ENCODING_EMBSTR) {
                decrRefCount(o);
                return createStringObjectFromLongLongForValue(value);
            }
        }
    }

    /* If the string is small and is still RAW encoded,
     * try the EMBSTR encoding which is more efficient.
     * In this representation the object and the SDS string are allocated
     * in the same chunk of memory to save space and cache misses. */
    if (len <= OBJ_ENCODING_EMBSTR_SIZE_LIMIT) {
        robj *emb;

        if (o->encoding == OBJ_ENCODING_EMBSTR) return o;
        emb = createEmbeddedStringObject(s,sdslen(s));
        decrRefCount(o);
        return emb;
    }

    /* We can't encode the object...
     *
     * Do the last try, and at least optimize the SDS string inside
     * the string object to require little space, in case there
     * is more than 10% of free space at the end of the SDS string.
     *
     * We do that only for relatively large strings as this branch
     * is only entered if the length of the string is greater than
     * OBJ_ENCODING_EMBSTR_SIZE_LIMIT. */
    trimStringObjectIfNeeded(o);

    /* Return the original object. */
    return o;
}
```



#### createEmbeddedStringObject

zmalloc 1, better for cache

```c
/* Create a string object with encoding OBJ_ENCODING_EMBSTR, that is
 * an object where the sds string is actually an unmodifiable string
 * allocated in the same chunk as the object itself. */
robj *createEmbeddedStringObject(const char *ptr, size_t len) {
    robj *o = zmalloc(sizeof(robj)+sizeof(struct sdshdr8)+len+1);
    struct sdshdr8 *sh = (void*)(o+1);

    o->type = OBJ_STRING;
    o->encoding = OBJ_ENCODING_EMBSTR;
    o->ptr = sh+1;
    o->refcount = 1;
    if (server.maxmemory_policy & MAXMEMORY_FLAG_LFU) {
        o->lru = (LFUGetTimeInMinutes()<<8) | LFU_INIT_VAL;
    } else {
        o->lru = LRU_CLOCK();
    }

    sh->len = len;
    sh->alloc = len;
    sh->flags = SDS_TYPE_8;
    if (ptr == SDS_NOINIT)
        sh->buf[len] = '\0';
    else if (ptr) {
        memcpy(sh->buf,ptr,len);
        sh->buf[len] = '\0';
    } else {
        memset(sh->buf,0,len+1);
    }
    return o;
}
```



#### createStringObjectFromLongLongWithOptions

zmolloc twice

1. [createObject](/docs/CS/DB/Redis/struct.md?id=createobject)
2. [sdsnewlen in sdsfromlonglong](/docs/CS/DB/Redis/SDS?id=sdsnewlen)

```c
// object.c
/* Create a string object from a long long value. When possible returns a
 * shared integer object, or at least an integer encoded one.
 *
 * If valueobj is non zero, the function avoids returning a a shared
 * integer, because the object is going to be used as value in the Redis key
 * space (for instance when the INCR command is used), so we want LFU/LRU
 * values specific for each key. */
robj *createStringObjectFromLongLongWithOptions(long long value, int valueobj) {
    robj *o;

    if (server.maxmemory == 0 ||
        !(server.maxmemory_policy & MAXMEMORY_FLAG_NO_SHARED_INTEGERS))
    {
        /* If the maxmemory policy permits, we can still return shared integers
         * even if valueobj is true. */
        valueobj = 0;
    }

    if (value >= 0 && value < OBJ_SHARED_INTEGERS && valueobj == 0) {
        incrRefCount(shared.integers[value]);
        o = shared.integers[value];
    } else {
        if (value >= LONG_MIN && value <= LONG_MAX) {
            o = createObject(OBJ_STRING, NULL);
            o->encoding = OBJ_ENCODING_INT;
            o->ptr = (void*)((long)value);
        } else {
            o = createObject(OBJ_STRING,sdsfromlonglong(value));
        }
    }
    return o;
}
```



#### sdsnewlen

Don't use sdshdr5, turn to SDS_TYPE_8.


```c
/* Create an sds string from a long long value. It is much faster than:
 * sdscatprintf(sdsempty(),"%lld\n", value);
 */
sds sdsfromlonglong(long long value) {
    char buf[SDS_LLSTR_SIZE];
    int len = sdsll2str(buf,value);
    return sdsnewlen(buf,len);
}


/* Create a string object with encoding OBJ_ENCODING_RAW, that is a plain
 * string object where o->ptr points to a proper sds string. */
robj *createRawStringObject(const char *ptr, size_t len) {
    return createObject(OBJ_STRING, sdsnewlen(ptr,len));
}

/* Create a new sds string with the content specified by the 'init' pointer
 * and 'initlen'.
 * If NULL is used for 'init' the string is initialized with zero bytes.
 * If SDS_NOINIT is used, the buffer is left uninitialized;
 *
 * The string is always null-termined (all the sds strings are, always) so
 * even if you create an sds string with:
 *
 * mystring = sdsnewlen("abc",3);
 *
 * You can print the string with printf() as there is an implicit \0 at the
 * end of the string. However the string is binary safe and can contain
 * \0 characters in the middle, as the length is stored in the sds header. */
sds sdsnewlen(const void *init, size_t initlen) {
    void *sh;
    sds s;
    char type = sdsReqType(initlen);
    /* Empty strings are usually created in order to append. Use type 8
     * since type 5 is not good at this. */
    if (type == SDS_TYPE_5 && initlen == 0) type = SDS_TYPE_8;
    int hdrlen = sdsHdrSize(type);
    unsigned char *fp; /* flags pointer. */

    sh = s_malloc(hdrlen+initlen+1); // +1 for '\0' 
    if (sh == NULL) return NULL;
    if (init==SDS_NOINIT)
        init = NULL;
    else if (!init)
        memset(sh, 0, hdrlen+initlen+1);
    s = (char*)sh+hdrlen; // s
    fp = ((unsigned char*)s)-1;
    switch(type) {
        case SDS_TYPE_5: {
            *fp = type | (initlen << SDS_TYPE_BITS);
            break;
        }
        case SDS_TYPE_8: {
            SDS_HDR_VAR(8,s);
            sh->len = initlen;
            sh->alloc = initlen;
            *fp = type;
            break;
        }
        case SDS_TYPE_16: {
            SDS_HDR_VAR(16,s);
            sh->len = initlen;
            sh->alloc = initlen;
            *fp = type;
            break;
        }
        case SDS_TYPE_32: {
            SDS_HDR_VAR(32,s);
            sh->len = initlen;
            sh->alloc = initlen;
            *fp = type;
            break;
        }
        case SDS_TYPE_64: {
            SDS_HDR_VAR(64,s);
            sh->len = initlen;
            sh->alloc = initlen;
            *fp = type;
            break;
        }
    }
    if (initlen && init)
        memcpy(s, init, initlen);
    s[initlen] = '\0'; // for c
    return s; // return ptr of buf[]
}
```





### setGenericCommand


The setGenericCommand() function implements the SET operation with differen options and variants. This function is called in order to implement the following commands: SET, SETEX, PSETEX, SETNX.
- 'flags' changes the behavior of the command (NX or XX, see below).
- 'expire' represents an expire to set in form of a Redis object as passed by the user. It is interpreted according to the specified 'unit'.
- 'ok_reply' and 'abort_reply' is what the function will reply to the client if the operation is performed, or when it is not because of NX or XX flags.

If ok_reply is NULL "+OK" is used.
If abort_reply is NULL, "$-1" is used.

[genericSetKey](/docs/CS/DB/Redis/redisDb.md?id=genericSetKey)

```c
// t_string.c
#define OBJ_SET_NO_FLAGS 0
#define OBJ_SET_NX (1<<0)          /* Set if key not exists. */
#define OBJ_SET_XX (1<<1)          /* Set if key exists. */
#define OBJ_SET_EX (1<<2)          /* Set if time in seconds is given */
#define OBJ_SET_PX (1<<3)          /* Set if time in ms in given */
#define OBJ_SET_KEEPTTL (1<<4)     /* Set and keep the ttl */

void setGenericCommand(client *c, int flags, robj *key, robj *val, robj *expire, int unit, robj *ok_reply, robj *abort_reply) {
    long long milliseconds = 0, when = 0; /* initialized to avoid any harmness warning */

    if (expire) {
        if (getLongLongFromObjectOrReply(c, expire, &milliseconds, NULL) != C_OK)
            return;
        if (milliseconds <= 0 || (unit == UNIT_SECONDS && milliseconds > LLONG_MAX / 1000)) {
            /* Negative value provided or multiplication is gonna overflow. */
            addReplyErrorFormat(c, "invalid expire time in %s", c->cmd->name);
            return;
        }
        if (unit == UNIT_SECONDS) milliseconds *= 1000;
        when = milliseconds;
        if ((flags & OBJ_PX) || (flags & OBJ_EX))
            when += mstime();
        if (when <= 0) {
            /* Overflow detected. */
            addReplyErrorFormat(c, "invalid expire time in %s", c->cmd->name);
            return;
        }
    }

    if ((flags & OBJ_SET_NX && lookupKeyWrite(c->db,key) != NULL) ||
        (flags & OBJ_SET_XX && lookupKeyWrite(c->db,key) == NULL))
    {
        addReply(c, abort_reply ? abort_reply : shared.null[c->resp]);
        return;
    }

    if (flags & OBJ_SET_GET) {
        if (getGenericCommand(c) == C_ERR) return;
    }

    genericSetKey(c,c->db,key, val,flags & OBJ_KEEPTTL,1);
    server.dirty++;
    notifyKeyspaceEvent(NOTIFY_STRING,"set",key,c->db->id);
    if (expire) {
        setExpire(c,c->db,key,when);
        notifyKeyspaceEvent(NOTIFY_GENERIC,"expire",key,c->db->id);

        /* Propagate as SET Key Value PXAT millisecond-timestamp if there is EXAT/PXAT or
         * propagate as SET Key Value PX millisecond if there is EX/PX flag.
         *
         * Additionally when we propagate the SET with PX (relative millisecond) we translate
         * it again to SET with PXAT for the AOF.
         *
         * Additional care is required while modifying the argument order. AOF relies on the
         * exp argument being at index 3. (see feedAppendOnlyFile)
         * */
        robj *exp = (flags & OBJ_PXAT) || (flags & OBJ_EXAT) ? shared.pxat : shared.px;
        robj *millisecondObj = createStringObjectFromLongLong(milliseconds);
        rewriteClientCommandVector(c,5,shared.set,key,val,exp,millisecondObj);
        decrRefCount(millisecondObj);
    }
    if (!(flags & OBJ_SET_GET)) {
        addReply(c, ok_reply ? ok_reply : shared.ok);
    }

    /* Propagate without the GET argument (Isn't needed if we had expire since in that case we completely re-written the command argv) */
    if ((flags & OBJ_SET_GET) && !expire) {
        int argc = 0;
        int j;
        robj **argv = zmalloc((c->argc-1)*sizeof(robj*));
        for (j=0; j < c->argc; j++) {
            char *a = c->argv[j]->ptr;
            /* Skip GET which may be repeated multiple times. */
            if (j >= 3 &&
                (a[0] == 'g' || a[0] == 'G') &&
                (a[1] == 'e' || a[1] == 'E') &&
                (a[2] == 't' || a[2] == 'T') && a[3] == '\0')
                continue;
            argv[argc++] = c->argv[j];
            incrRefCount(c->argv[j]);
        }
        replaceClientCommandVector(c, argc, argv);
    }
}
```





## sdscatjoin



```c
/* Like sdsjoin, but joins an array of SDS strings. */
sds sdsjoinsds(sds *argv, int argc, const char *sep, size_t seplen) {
  // Create an empty (zero length) sds string. 
  // Even in this case the  string always has an implicit null term. 
  sds join = sdsempty(); 
    int j;

    for (j = 0; j < argc; j++) {
        join = sdscatsds(join, argv[j]);
        if (j != argc-1) join = sdscatlen(join,sep,seplen);
    }
    return join;
}
```




### sdscatlen
```c
/* Append the specified binary-safe string pointed by 't' of 'len' bytes to the
 * end of the specified sds string 's'.
 *
 * After the call, the passed sds string is no longer valid and all the
 * references must be substituted with the new pointer returned by the call. */
sds sdscatlen(sds s, const void *t, size_t len) {
    size_t curlen = sdslen(s);

    s = sdsMakeRoomFor(s,len);
    if (s == NULL) return NULL;
    memcpy(s+curlen, t, len);
    sdssetlen(s, curlen+len);
    s[curlen+len] = '\0';
    return s;
}
```




### _sdsMakeRoomFor
1. avail >= addlen, return
2. expand pow of 2 when len < 1M, or else expand 1M util 512M
3. calc new Type, if same Type return, or else allocate new memory and `memcpy`

```c
// sds.h
#define SDS_MAX_PREALLOC (1024*1024) // 1MB

/* Enlarge the free space at the end of the sds string so that the caller
 * is sure that after calling this function can overwrite up to addlen
 * bytes after the end of the string, plus one more byte for nul term.
 * If there's already sufficient free space, this function returns without any
 * action, if there isn't sufficient free space, it'll allocate what's missing,
 * and possibly more:
 * When greedy is 1, enlarge more than needed, to avoid need for future reallocs
 * on incremental growth.
 * When greedy is 0, enlarge just enough so that there's free space for 'addlen'.
 *
 * Note: this does not change the *length* of the sds string as returned
 * by sdslen(), but only the free buffer space we have. */
sds _sdsMakeRoomFor(sds s, size_t addlen, int greedy) {
    void *sh, *newsh;
    size_t avail = sdsavail(s);
    size_t len, newlen;
    char type, oldtype = s[-1] & SDS_TYPE_MASK;
    int hdrlen;
    size_t usable;

    /* Return ASAP if there is enough space left. */
    if (avail >= addlen) return s;

    len = sdslen(s);
    sh = (char*)s-sdsHdrSize(oldtype);
    newlen = (len+addlen);
    assert(newlen > len);   /* Catch size_t overflow */
    if (greedy == 1) {
        if (newlen < SDS_MAX_PREALLOC)
            newlen *= 2;
        else
            newlen += SDS_MAX_PREALLOC;
    }

    type = sdsReqType(newlen);

    /* Don't use type 5: the user is appending to the string and type 5 is
     * not able to remember empty space, so sdsMakeRoomFor() must be called
     * at every appending operation. */
    if (type == SDS_TYPE_5) type = SDS_TYPE_8;

    hdrlen = sdsHdrSize(type);
    assert(hdrlen + newlen + 1 > len);  /* Catch size_t overflow */
    if (oldtype==type) {
        newsh = s_realloc_usable(sh, hdrlen+newlen+1, &usable);
        if (newsh == NULL) return NULL;
        s = (char*)newsh+hdrlen;
    } else {
        /* Since the header size changes, need to move the string forward,
         * and can't use realloc */
        newsh = s_malloc_usable(hdrlen+newlen+1, &usable);
        if (newsh == NULL) return NULL;
        memcpy((char*)newsh+hdrlen, s, len+1);
        s_free(sh);
        s = (char*)newsh+hdrlen;
        s[-1] = type;
        sdssetlen(s, len);
    }
    usable = usable-hdrlen-1;
    if (usable > sdsTypeMaxSize(type))
        usable = sdsTypeMaxSize(type);
    sdssetalloc(s, usable);
    return s;
}
```



## free

use `sdsclear` rather than `sdsfree`

```c
/* Free an sds string. No operation is performed if 's' is NULL. */
#define s_free zfree

void sdsfree(sds s) {
    if (s == NULL) return;
    s_free((char*)s-sdsHdrSize(s[-1]));
}
```



```c
/* Modify an sds string in-place to make it empty (zero length).
 * However all the existing buffer is not discarded but set as free space
 * so that next append operations will not require allocations up to the
 * number of bytes previously available. */
void sdsclear(sds s) {
    sdssetlen(s, 0);
    s[0] = '\0';
}
```

## Summary

- packed and always append '\0'
- expand pow of 2 when len < 1M, or else expand 1M util 512M
- use sdsclear rather than sdsfree
- encoding int value in ptr
- encoding embstr value memory close to [redisObject](/docs/CS/DB/Redis/redisDb.md?id=redisObject)

## References

1. [Simple Dynamic Strings](https://github.com/antirez/sds)
