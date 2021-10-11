##
memory

- used_memory
  - process memory
  - data memory
  - buffer memory
    - client buffer
      - client buffer for connections
      - slaves client connections
      - pub/sub connections  
    - copy buffer
    - AOF buffer
- fragmentation

mem_fragmentation_ratio usually 1.03

if > 1, is fragmentation
< 1, using swap

fragmentation by 

- usually using append setrange
- delete lots of expire keys

allocate memory by jemelloc
small: << 8byte
big : << 4KB
huge : << 4MB

## maxMemory
```c
//server.h

/* Redis maxmemory strategies. Instead of using just incremental number
 * for this defines, we use a set of flags so that testing for certain
 * properties common to multiple policies is faster. */
#define MAXMEMORY_FLAG_LRU (1<<0)
#define MAXMEMORY_FLAG_LFU (1<<1)
#define MAXMEMORY_FLAG_ALLKEYS (1<<2)
#define MAXMEMORY_FLAG_NO_SHARED_INTEGERS \
    (MAXMEMORY_FLAG_LRU|MAXMEMORY_FLAG_LFU)

#define MAXMEMORY_VOLATILE_LRU ((0<<8)|MAXMEMORY_FLAG_LRU)
#define MAXMEMORY_VOLATILE_LFU ((1<<8)|MAXMEMORY_FLAG_LFU)
#define MAXMEMORY_VOLATILE_TTL (2<<8)
#define MAXMEMORY_VOLATILE_RANDOM (3<<8)
#define MAXMEMORY_ALLKEYS_LRU ((4<<8)|MAXMEMORY_FLAG_LRU|MAXMEMORY_FLAG_ALLKEYS)
#define MAXMEMORY_ALLKEYS_LFU ((5<<8)|MAXMEMORY_FLAG_LFU|MAXMEMORY_FLAG_ALLKEYS)
#define MAXMEMORY_ALLKEYS_RANDOM ((6<<8)|MAXMEMORY_FLAG_ALLKEYS)
#define MAXMEMORY_NO_EVICTION (7<<8)
```

[redisObject](/docs/CS/DB/Redis/redisDb.md?id=redisObject) has `lru:LRU_BITS` and [update access time](/docs/CS/DB/Redis/redisDb.md?id=updateLFU)

```c
// server.h
typedef struct redisObject {
    unsigned lru:LRU_BITS; /* LRU time (relative to global lru_clock) or
                            * LFU data (least significant 8 bits frequency
                            * and most significant 16 bits access time). */
    // ...
} robj;
```

1000 ms
```c

#define LRU_BITS 24
#define LRU_CLOCK_MAX ((1<<LRU_BITS)-1) /* Max value of obj->lru */
#define LRU_CLOCK_RESOLUTION 1000 /* LRU clock resolution in ms */
```


### evict

To improve the quality of the LRU approximation we take a set of keys that are good candidate for eviction across performEvictions() calls.

Entries inside the eviction pool are taken ordered by idle time, putting greater idle times to the right (ascending order).

When an LFU policy is used instead, a reverse frequency indication is used instead of the idle time, so that we still evict by larger value (larger inverse frequency means to evict keys with the least frequent accesses). 

Empty entries have the key pointer set to NULL.
```c
#define EVPOOL_SIZE 16
#define EVPOOL_CACHED_SDS_SIZE 255
struct evictionPoolEntry {
    unsigned long long idle;    /* Object idle time (inverse frequency for LFU) */
    sds key;                    /* Key name. */
    sds cached;                 /* Cached SDS object for key name. */
    int dbid;                   /* Key DB number. */
};
```

`performEvictions` called by `processCommand()` which is defined inside `server.c` in order to actually execute the command

```c
int performEvictions(void)
```

`evictionPoolPopulate` called by `performEvictions`