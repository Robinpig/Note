## 简介

GeoHash 编码成二进制值并使用有序集合（Sorted Set）。

基于位置的服务（LBS）

Redis 中的 GEO 经典使用场景如下：

1. 查询附近的人、附近的地点等；
2. 计算相关的距离信息。

GEO 本质上是基于 ZSet 实现的。

GeoHash 将经纬度编码转换为一个 N 位的二进制数。

每个地理位置坐标表示为 geoPoint：

```c
typedef struct geoPoint {
    double longitude;
    double latitude;
    double dist;
    double score;
    char *member;
} geoPoint;

typedef struct geoArray {
    struct geoPoint *array;
    size_t buckets;
    size_t used;
} geoArray;
```

```c
void geoaddCommand(client *c) {
    int xx = 0, nx = 0, longidx = 2;
    int i;

    /* 解析选项。最后 'longidx' 设置为第一个元素的经度参数位置。 */
    while (longidx < c->argc) {
        char *opt = c->argv[longidx]->ptr;
        if (!strcasecmp(opt,"nx")) nx = 1;
        else if (!strcasecmp(opt,"xx")) xx = 1;
        else if (!strcasecmp(opt,"ch")) { /* 在 zaddCommand 中处理 */ }
        else break;
        longidx++;
    }

    if ((c->argc - longidx) % 3 || (xx && nx)) {
        /* 如果到这里，需要奇数个参数... */
            addReplyErrorObject(c,shared.syntaxerr);
        return;
    }

    /* 设置调用 ZADD 的参数向量。 */
    int elements = (c->argc - longidx) / 3;
    int argc = longidx+elements*2; /* ZADD key [CH] [NX|XX] score ele ... */
    robj **argv = zcalloc(argc*sizeof(robj*));
    argv[0] = createRawStringObject("zadd",4);
    for (i = 1; i < longidx; i++) {
        argv[i] = c->argv[i];
        incrRefCount(argv[i]);
    }

    /* 创建调用 ZADD 的参数向量，以将所有 score,value 对添加到请求的 zset 中，
    其中 score 实际上是 lat,long 的编码版本。 */
    for (i = 0; i < elements; i++) {
        double xy[2];

        if (extractLongLatOrReply(c, (c->argv+longidx)+(i*3),xy) == C_ERR) {
            for (i = 0; i < argc; i++)
                if (argv[i]) decrRefCount(argv[i]);
            zfree(argv);
            return;
        }

        /* 将坐标转换为元素的 score。 */
        GeoHashBits hash;
        geohashEncodeWGS84(xy[0], xy[1], GEO_STEP_MAX, &hash);
        GeoHashFix52Bits bits = geohashAlign52Bits(hash);
        robj *score = createObject(OBJ_STRING, sdsfromlonglong(bits));
        robj *val = c->argv[longidx + i * 3 + 2];
        argv[longidx+i*2] = score;
        argv[longidx+1+i*2] = val;
        incrRefCount(val);
    }

    /* 最后调用 ZADD 为我们完成工作。 */
    replaceClientCommandVector(c,argc,argv);
    zaddCommand(c);
}
```

地理位置信息查询：

```c
void georadiusGeneric(client *c, int srcKeyIndex, int flags) {
    robj *storekey = NULL;
    int storedist = 0; /* 0 表示 STORE，1 表示 STOREDIST */

    /* 查找请求的 zset */
    robj *zobj = lookupKeyRead(c->db, c->argv[srcKeyIndex]);
    if (checkType(c, zobj, OBJ_ZSET)) return;

    /* 根据查询类型查找用于半径或矩形搜索的经纬度 */
    int base_args;
    GeoShape shape = {0};
    if (flags & RADIUS_COORDS) {
        /* GEORADIUS 或 GEORADIUS_RO */
        base_args = 6;
        shape.type = CIRCULAR_TYPE;
        if (extractLongLatOrReply(c, c->argv + 2, shape.xy) == C_ERR) return;
        if (extractDistanceOrReply(c, c->argv+base_args-2, &shape.conversion, &shape.t.radius) != C_OK) return;
    } else if ((flags & RADIUS_MEMBER) && !zobj) {
        /* 没有源键，但需要继续解析参数，以便根据 STORE 标志确定使用哪种回复。 */
        base_args = 5;
    } else if (flags & RADIUS_MEMBER) {
        /* GEORADIUSBYMEMBER 或 GEORADIUSBYMEMBER_RO */
        base_args = 5;
        shape.type = CIRCULAR_TYPE;
        robj *member = c->argv[2];
        if (longLatFromMember(zobj, member, shape.xy) == C_ERR) {
            addReplyError(c, "could not decode requested zset member");
            return;
        }
        if (extractDistanceOrReply(c, c->argv+base_args-2, &shape.conversion, &shape.t.radius) != C_OK) return;
    } else if (flags & GEOSEARCH) {
        /* GEOSEARCH 或 GEOSEARCHSTORE */
        base_args = 2;
        if (flags & GEOSEARCHSTORE) {
            base_args = 3;
            storekey = c->argv[1];
        }
    } else {
        addReplyError(c, "Unknown georadius search type");
        return;
    }

    /* 发现并填充所有可选参数。 */
    // ... 解析参数 ...

    /* 当源键不存在时立即返回。 */
    if (zobj == NULL) {
        // ... 处理空结果 ...
        return;
    }

    /* 获取所有邻近的 geohash 盒子用于半径搜索 */
    GeoHashRadius georadius = geohashCalculateAreasByShapeWGS84(&shape);

    /* 在 zset 中搜索所有匹配的点 */
    geoArray *ga = geoArrayCreate();
    membersOfAllNeighbors(zobj, &georadius, &shape, ga, any ? count : 0);

    // ... 处理和返回结果 ...
}
```

地图信息通常数据量较多，为避免 big key，可以将区域划分得较细些。

## 链接

- [Redis 数据结构](/docs/CS/DB/Redis/struct/struct.md)
