## Introduction


* `createClient()` allocates and initializes a new client.
* the `addReply*()` family of functions are used by command implementations in order to append data to the client structure, that will be transmitted to the client as a reply for a given command executed.
* `writeToClient()` transmits the data pending in the output buffers to the client and is called by the *writable event handler* `sendReplyToClient()`.
* `readQueryFromClient()` is the *readable event handler* and accumulates data read from the client into the query buffer.
* `processInputBuffer()` is the entry point in order to parse the client query buffer according to the Redis protocol. Once commands are ready to be processed, it calls `processCommand()` which is defined inside `server.c` in order to actually execute the command.
* `freeClient()` deallocates, disconnects and removes a client.



### Buffer


 The structure `client`(in the past it was called `redisClient`) has many fields, here we'll just show the main ones:
```c
typedef struct client {
    uint64_t id;            /* Client incremental unique ID. */
    int resp;               /* RESP protocol version. Can be 2 or 3. */
    redisDb *db;            /* Pointer to currently SELECTed DB. */
    robj *name;             /* As set by CLIENT SETNAME. */

    sds querybuf;           /* Buffer we use to accumulate client queries. */
    size_t querybuf_peak;   /* Recent (100ms or more) peak of querybuf size. */

    int argc;               /* Num of arguments of current command. */
    robj **argv;            /* Arguments of current command. */

    list *reply;            /* List of reply objects to send to the client. */

    /* Response buffer */
    int bufpos;
    char buf[PROTO_REPLY_CHUNK_BYTES];
    // ... many other fields ...
} client;

 #define PROTO_REPLY_CHUNK_BYTES (16*1024) /* 16k output buffer */
```
The client structure defines a *connected client*:
* `querybuf` accumulates the requests from the client, which are parsed by the Redis server according to the Redis protocol and executed by calling the implementations of the commands the client is executing.
* `reply` and `buf` are dynamic and static buffers(16KB) that accumulate the replies the server sends to the client. These buffers are incrementally written to the socket as soon as the file descriptor is writeable.

#### querybuf


```c
// config.c
createSizeTConfig("client-query-buffer-limit", NULL, MODIFIABLE_CONFIG, 1024*1024, LONG_MAX, server.client_max_querybuf_len, 1024*1024*1024, MEMORY_CONFIG, NULL, NULL), /* Default: 1GB max query buffer. */
```

close client if over limit

```c
// networking::readQueryFromClient
if (sdslen(c->querybuf) > server.client_max_querybuf_len) {
    sds ci = catClientInfoString(sdsempty(),c), bytes = sdsempty();

    bytes = sdscatrepr(bytes,c->querybuf,64);
    serverLog(LL_WARNING,"Closing client that reached max query buffer length: %s (qbuf initial bytes: %s)", ci, bytes);
    sdsfree(ci);
    sdsfree(bytes);
    freeClientAsync(c);
    return;
}
```



#### reply dynamic buffer

The client output buffer limits can be used to force disconnection of clients that are not reading data from the server fast enough for some reason (a common reason is that a Pub/Sub client can't consume messages as fast as the publisher can produce them).

```
client-output-buffer-limit normal 0 0 0
client-output-buffer-limit replica 256mb 64mb 60
client-output-buffer-limit pubsub 32mb 8mb 60
```

## Cache





## monitor

```
info clients
```



```
client list
```







## References
