## Introduction

GeoHash encode to a binary value and use Sorted-Set

Location-Based Service (LBS)



GeoHash将经纬度编码转换为一个N位的二进制数

每个地理位置坐标表示为geoPoint

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

    /* Parse options. At the end 'longidx' is set to the argument position
     * of the longitude of the first element. */
    while (longidx < c->argc) {
        char *opt = c->argv[longidx]->ptr;
        if (!strcasecmp(opt,"nx")) nx = 1;
        else if (!strcasecmp(opt,"xx")) xx = 1;
        else if (!strcasecmp(opt,"ch")) { /* Handle in zaddCommand. */ }
        else break;
        longidx++;
    }

    if ((c->argc - longidx) % 3 || (xx && nx)) {
        /* Need an odd number of arguments if we got this far... */
            addReplyErrorObject(c,shared.syntaxerr);
        return;
    }

    /* Set up the vector for calling ZADD. */
    int elements = (c->argc - longidx) / 3;
    int argc = longidx+elements*2; /* ZADD key [CH] [NX|XX] score ele ... */
    robj **argv = zcalloc(argc*sizeof(robj*));
    argv[0] = createRawStringObject("zadd",4);
    for (i = 1; i < longidx; i++) {
        argv[i] = c->argv[i];
        incrRefCount(argv[i]);
    }

    /* Create the argument vector to call ZADD in order to add all
     * the score,value pairs to the requested zset, where score is actually
     * an encoded version of lat,long. */
    for (i = 0; i < elements; i++) {
        double xy[2];

        if (extractLongLatOrReply(c, (c->argv+longidx)+(i*3),xy) == C_ERR) {
            for (i = 0; i < argc; i++)
                if (argv[i]) decrRefCount(argv[i]);
            zfree(argv);
            return;
        }

        /* Turn the coordinates into the score of the element. */
        GeoHashBits hash;
        geohashEncodeWGS84(xy[0], xy[1], GEO_STEP_MAX, &hash);
        GeoHashFix52Bits bits = geohashAlign52Bits(hash);
        robj *score = createObject(OBJ_STRING, sdsfromlonglong(bits));
        robj *val = c->argv[longidx + i * 3 + 2];
        argv[longidx+i*2] = score;
        argv[longidx+1+i*2] = val;
        incrRefCount(val);
    }

    /* Finally call ZADD that will do the work for us. */
    replaceClientCommandVector(c,argc,argv);
    zaddCommand(c);
}
```

地理位置信息查询

```c
void georadiusGeneric(client *c, int srcKeyIndex, int flags) {
    robj *storekey = NULL;
    int storedist = 0; /* 0 for STORE, 1 for STOREDIST. */

    /* Look up the requested zset */
    robj *zobj = lookupKeyRead(c->db, c->argv[srcKeyIndex]);
    if (checkType(c, zobj, OBJ_ZSET)) return;

    /* Find long/lat to use for radius or box search based on inquiry type */
    int base_args;
    GeoShape shape = {0};
    if (flags & RADIUS_COORDS) {
        /* GEORADIUS or GEORADIUS_RO */
        base_args = 6;
        shape.type = CIRCULAR_TYPE;
        if (extractLongLatOrReply(c, c->argv + 2, shape.xy) == C_ERR) return;
        if (extractDistanceOrReply(c, c->argv+base_args-2, &shape.conversion, &shape.t.radius) != C_OK) return;
    } else if ((flags & RADIUS_MEMBER) && !zobj) {
        /* We don't have a source key, but we need to proceed with argument
         * parsing, so we know which reply to use depending on the STORE flag. */
        base_args = 5;
    } else if (flags & RADIUS_MEMBER) {
        /* GEORADIUSBYMEMBER or GEORADIUSBYMEMBER_RO */
        base_args = 5;
        shape.type = CIRCULAR_TYPE;
        robj *member = c->argv[2];
        if (longLatFromMember(zobj, member, shape.xy) == C_ERR) {
            addReplyError(c, "could not decode requested zset member");
            return;
        }
        if (extractDistanceOrReply(c, c->argv+base_args-2, &shape.conversion, &shape.t.radius) != C_OK) return;
    } else if (flags & GEOSEARCH) {
        /* GEOSEARCH or GEOSEARCHSTORE */
        base_args = 2;
        if (flags & GEOSEARCHSTORE) {
            base_args = 3;
            storekey = c->argv[1];
        }
    } else {
        addReplyError(c, "Unknown georadius search type");
        return;
    }

    /* Discover and populate all optional parameters. */
    int withdist = 0, withhash = 0, withcoords = 0;
    int frommember = 0, fromloc = 0, byradius = 0, bybox = 0;
    int sort = SORT_NONE;
    int any = 0; /* any=1 means a limited search, stop as soon as enough results were found. */
    long long count = 0;  /* Max number of results to return. 0 means unlimited. */
    if (c->argc > base_args) {
        int remaining = c->argc - base_args;
        for (int i = 0; i < remaining; i++) {
            char *arg = c->argv[base_args + i]->ptr;
            if (!strcasecmp(arg, "withdist")) {
                withdist = 1;
            } else if (!strcasecmp(arg, "withhash")) {
                withhash = 1;
            } else if (!strcasecmp(arg, "withcoord")) {
                withcoords = 1;
            } else if (!strcasecmp(arg, "any")) {
                any = 1;
            } else if (!strcasecmp(arg, "asc")) {
                sort = SORT_ASC;
            } else if (!strcasecmp(arg, "desc")) {
                sort = SORT_DESC;
            } else if (!strcasecmp(arg, "count") && (i+1) < remaining) {
                if (getLongLongFromObjectOrReply(c, c->argv[base_args+i+1],
                                                 &count, NULL) != C_OK) return;
                if (count <= 0) {
                    addReplyError(c,"COUNT must be > 0");
                    return;
                }
                i++;
            } else if (!strcasecmp(arg, "store") &&
                       (i+1) < remaining &&
                       !(flags & RADIUS_NOSTORE) &&
                       !(flags & GEOSEARCH))
            {
                storekey = c->argv[base_args+i+1];
                storedist = 0;
                i++;
            } else if (!strcasecmp(arg, "storedist") &&
                       (i+1) < remaining &&
                       !(flags & RADIUS_NOSTORE) &&
                       !(flags & GEOSEARCH))
            {
                storekey = c->argv[base_args+i+1];
                storedist = 1;
                i++;
            } else if (!strcasecmp(arg, "storedist") &&
                       (flags & GEOSEARCH) &&
                       (flags & GEOSEARCHSTORE))
            {
                storedist = 1;
            } else if (!strcasecmp(arg, "frommember") &&
                      (i+1) < remaining &&
                      flags & GEOSEARCH &&
                      !fromloc)
            {
                /* No source key, proceed with argument parsing and return an error when done. */
                if (zobj == NULL) {
                    frommember = 1;
                    i++;
                    continue;
                }

                if (longLatFromMember(zobj, c->argv[base_args+i+1], shape.xy) == C_ERR) {
                    addReplyError(c, "could not decode requested zset member");
                    return;
                }
                frommember = 1;
                i++;
            } else if (!strcasecmp(arg, "fromlonlat") &&
                       (i+2) < remaining &&
                       flags & GEOSEARCH &&
                       !frommember)
            {
                if (extractLongLatOrReply(c, c->argv+base_args+i+1, shape.xy) == C_ERR) return;
                fromloc = 1;
                i += 2;
            } else if (!strcasecmp(arg, "byradius") &&
                       (i+2) < remaining &&
                       flags & GEOSEARCH &&
                       !bybox)
            {
                if (extractDistanceOrReply(c, c->argv+base_args+i+1, &shape.conversion, &shape.t.radius) != C_OK)
                    return;
                shape.type = CIRCULAR_TYPE;
                byradius = 1;
                i += 2;
            } else if (!strcasecmp(arg, "bybox") &&
                       (i+3) < remaining &&
                       flags & GEOSEARCH &&
                       !byradius)
            {
                if (extractBoxOrReply(c, c->argv+base_args+i+1, &shape.conversion, &shape.t.r.width,
                        &shape.t.r.height) != C_OK) return;
                shape.type = RECTANGLE_TYPE;
                bybox = 1;
                i += 3;
            } else {
                addReplyErrorObject(c,shared.syntaxerr);
                return;
            }
        }
    }

    /* Trap options not compatible with STORE and STOREDIST. */
    if (storekey && (withdist || withhash || withcoords)) {
        addReplyErrorFormat(c,
            "%s is not compatible with WITHDIST, WITHHASH and WITHCOORD options",
            flags & GEOSEARCHSTORE? "GEOSEARCHSTORE": "STORE option in GEORADIUS");
        return;
    }

    if ((flags & GEOSEARCH) && !(frommember || fromloc)) {
        addReplyErrorFormat(c,
            "exactly one of FROMMEMBER or FROMLONLAT can be specified for %s",
            (char *)c->argv[0]->ptr);
        return;
    }

    if ((flags & GEOSEARCH) && !(byradius || bybox)) {
        addReplyErrorFormat(c,
            "exactly one of BYRADIUS and BYBOX can be specified for %s",
            (char *)c->argv[0]->ptr);
        return;
    }

    if (any && !count) {
        addReplyErrorFormat(c, "the ANY argument requires COUNT argument");
        return;
    }

    /* Return ASAP when src key does not exist. */
    if (zobj == NULL) {
        if (storekey) {
            /* store key is not NULL, try to delete it and return 0. */
            if (dbDelete(c->db, storekey)) {
                signalModifiedKey(c, c->db, storekey);
                notifyKeyspaceEvent(NOTIFY_GENERIC, "del", storekey, c->db->id);
                server.dirty++;
            }
            addReply(c, shared.czero);
        } else {
            /* Otherwise we return an empty array. */
            addReply(c, shared.emptyarray);
        }
        return;
    }

    /* COUNT without ordering does not make much sense (we need to
     * sort in order to return the closest N entries),
     * force ASC ordering if COUNT was specified but no sorting was
     * requested. Note that this is not needed for ANY option. */
    if (count != 0 && sort == SORT_NONE && !any) sort = SORT_ASC;

    /* Get all neighbor geohash boxes for our radius search */
    GeoHashRadius georadius = geohashCalculateAreasByShapeWGS84(&shape);

    /* Search the zset for all matching points */
    geoArray *ga = geoArrayCreate();
    membersOfAllNeighbors(zobj, &georadius, &shape, ga, any ? count : 0);

    /* If no matching results, the user gets an empty reply. */
    if (ga->used == 0 && storekey == NULL) {
        addReply(c,shared.emptyarray);
        geoArrayFree(ga);
        return;
    }

    long result_length = ga->used;
    long returned_items = (count == 0 || result_length < count) ?
                          result_length : count;
    long option_length = 0;

    /* Process [optional] requested sorting */
    if (sort != SORT_NONE) {
        int (*sort_gp_callback)(const void *a, const void *b) = NULL;
        if (sort == SORT_ASC) {
            sort_gp_callback = sort_gp_asc;
        } else if (sort == SORT_DESC) {
            sort_gp_callback = sort_gp_desc;
        }

        if (returned_items == result_length) {
            qsort(ga->array, result_length, sizeof(geoPoint), sort_gp_callback);
        } else {
            pqsort(ga->array, result_length, sizeof(geoPoint), sort_gp_callback,
                0, (returned_items - 1));
        }
    }

    if (storekey == NULL) {
        /* No target key, return results to user. */

        /* Our options are self-contained nested multibulk replies, so we
         * only need to track how many of those nested replies we return. */
        if (withdist)
            option_length++;

        if (withcoords)
            option_length++;

        if (withhash)
            option_length++;

        /* The array len we send is exactly result_length. The result is
         * either all strings of just zset members  *or* a nested multi-bulk
         * reply containing the zset member string _and_ all the additional
         * options the user enabled for this request. */
        addReplyArrayLen(c, returned_items);

        /* Finally send results back to the caller */
        int i;
        for (i = 0; i < returned_items; i++) {
            geoPoint *gp = ga->array+i;
            gp->dist /= shape.conversion; /* Fix according to unit. */

            /* If we have options in option_length, return each sub-result
             * as a nested multi-bulk.  Add 1 to account for result value
             * itself. */
            if (option_length)
                addReplyArrayLen(c, option_length + 1);

            addReplyBulkSds(c,gp->member);
            gp->member = NULL;

            if (withdist)
                addReplyDoubleDistance(c, gp->dist);

            if (withhash)
                addReplyLongLong(c, gp->score);

            if (withcoords) {
                addReplyArrayLen(c, 2);
                addReplyHumanLongDouble(c, gp->longitude);
                addReplyHumanLongDouble(c, gp->latitude);
            }
        }
    } else {
        /* Target key, create a sorted set with the results. */
        robj *zobj;
        zset *zs;
        int i;
        size_t maxelelen = 0, totelelen = 0;

        if (returned_items) {
            zobj = createZsetObject();
            zs = zobj->ptr;
        }

        for (i = 0; i < returned_items; i++) {
            zskiplistNode *znode;
            geoPoint *gp = ga->array+i;
            gp->dist /= shape.conversion; /* Fix according to unit. */
            double score = storedist ? gp->dist : gp->score;
            size_t elelen = sdslen(gp->member);

            if (maxelelen < elelen) maxelelen = elelen;
            totelelen += elelen;
            znode = zslInsert(zs->zsl,score,gp->member);
            serverAssert(dictAdd(zs->dict,gp->member,&znode->score) == DICT_OK);
            gp->member = NULL;
        }

        if (returned_items) {
            zsetConvertToListpackIfNeeded(zobj,maxelelen,totelelen);
            setKey(c,c->db,storekey,zobj,0);
            decrRefCount(zobj);
            notifyKeyspaceEvent(NOTIFY_ZSET,flags & GEOSEARCH ? "geosearchstore" : "georadiusstore",storekey,
                                c->db->id);
            server.dirty += returned_items;
        } else if (dbDelete(c->db,storekey)) {
            signalModifiedKey(c,c->db,storekey);
            notifyKeyspaceEvent(NOTIFY_GENERIC,"del",storekey,c->db->id);
            server.dirty++;
        }
        addReplyLongLong(c, returned_items);
    }
    geoArrayFree(ga);
}
```



地图信息通常数据量较多 为避免big key 可以将区域划分得较细些

## Links

- [Redis Struct](/docs/CS/DB/Redis/struct/struct.md)
