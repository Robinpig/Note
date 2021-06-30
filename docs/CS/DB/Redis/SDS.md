# SDS



**长度限制? 使用hash存储,占用空间**

**expire will be delete after reset value**


```c
struct  sdshdr{
//记录buf中已保存字符的长度
//等于SDS所保存的字符串的长度
int  len;
//记录buf数组中未使用字节的数量
int free;
//字节数组，用于保存字符串
char buf[];
};
```

SDS为了能够**使用部分C字符串函数**，遵循了C字符串以空字符结尾的惯例，保存空字符的1字节不计算在SDSlen属性中，并且为空字符分配额外的1字节空间，以及添加空字符到字符串末尾等操作，都是由SDS函数自动完成的，可以说**空字符对使用者是透明的** 。

- O(1) get len

- 杜绝缓冲区溢出 可以在超过free空间时自动动态扩展内存

- 减少修改字符串时带来的内存重分配次数

    -  空间预分配 当字符串长度小于 **1M** 时，扩容都是加倍现有的空间，如果超过 1M，扩容时一次只会多扩 1M 的空间。(字符串最大长度为 **512M**)

    -  惰性空间释放 free可以用以记录未被使用的空间，不需重新构建新的字符串对象。

- 二进制安全 **字节数组**，不同于C语言的字符数组。



when create string, len=capacity, usually we don't append string.

len>44 raw, else embstr.

debug object key

RedisObject is 16byte

capacity +len +flags =3byte

NULL = 1byte

jemalloc apply 64byte

so a SDS max string len is 64-16-3-1=44byte

```c
// object.c
/* Create a string object with EMBSTR encoding if it is smaller than
 * OBJ_ENCODING_EMBSTR_SIZE_LIMIT, otherwise the RAW encoding is
 * used.
 *
 * The current limit of 44 is chosen so that the biggest string object
 * we allocate as EMBSTR will still fit into the 64 byte arena of jemalloc. */
#define OBJ_ENCODING_EMBSTR_SIZE_LIMIT 44
robj *createStringObject(const char *ptr, size_t len) {
    if (len <= OBJ_ENCODING_EMBSTR_SIZE_LIMIT)
        return createEmbeddedStringObject(ptr,len);
    else
        return createRawStringObject(ptr,len);
}
```



redisObject is close value in embstr




```c
// sds的定义
typedef char *sds;

/* Note: sdshdr5 is never used, we just access the flags byte directly.
 * However is here to document the layout of type 5 SDS strings. */
// 不会被用到
struct __attribute__ ((__packed__)) sdshdr5 {
    unsigned char flags; /* 3 lsb of type, and 5 msb of string length */
    char buf[];
};
struct __attribute__ ((__packed__)) sdshdr8 {
    uint8_t len; // 字符串长度，buf已经用过的长度
    uint8_t alloc; // 字符串的总容量
    unsigned char flags; // 第三位保存类型标志
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

```







```c
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



### sdslen



### sdsReqType



### sdsnewlen



### sdscat