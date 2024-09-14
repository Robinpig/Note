## Introduction

At the base of Redis replication (excluding the high availability features provided as an additional layer by Redis Cluster or Redis Sentinel) there is a *leader follower* (master-replica) replication that is simple to use and configure.
It allows replica Redis instances to be exact copies of master instances.
The replica will automatically reconnect to the master every time the link breaks, and will attempt to be an exact copy of it *regardless* of what happens to the master.

This system works using three main mechanisms:

1. When a master and a replica instances are well-connected, the master keeps the replica updated by sending a stream of commands to the replica to replicate the effects on the dataset happening in the master side due to:
   client writes, keys expired or evicted, any other action changing the master dataset.
2. When the link between the master and the replica breaks, for network issues or because a timeout is sensed in the master or the replica, the replica reconnects and attempts to proceed with a partial resynchronization:
   it means that it will try to just obtain the part of the stream of commands it missed during the disconnection.
3. When a partial resynchronization is not possible, the replica will ask for a full resynchronization.
   This will involve a more complex process in which the master needs to create a snapshot of all its data, send it to the replica, and then continue sending the stream of commands as the dataset changes.

Redis uses by default asynchronous replication, which being low latency and high performance, is the natural replication mode for the vast majority of Redis use cases. 
However, Redis replicas asynchronously acknowledge the amount of data they received periodically with the master. 
So the master does not wait every time for a command to be processed by the replicas, however it knows, if needed, what replica already processed what command. This allows having optional synchronous replication.

Synchronous replication of certain data can be requested by the clients using the `WAIT` command.
However `WAIT` is only able to ensure there are the specified number of acknowledged copies in the other Redis instances, it does not turn a set of Redis instances into a CP system with strong consistency:
acknowledged writes can still be lost during a failover, depending on the exact configuration of the Redis persistence.
However with `WAIT` the probability of losing a write after a failure event is greatly reduced to certain hard to trigger failure modes.

### Important facts

* Redis uses asynchronous replication, with asynchronous replica-to-master acknowledges of the amount of data processed.
* A master can have multiple replicas.
* Replicas are able to accept connections from other replicas. Aside from connecting a number of replicas to the same master, replicas can also be connected to other replicas in a cascading-like structure.
  Since Redis 4.0, all the sub-replicas will receive exactly the same replication stream from the master.
* Redis replication is non-blocking on the master side. This means that the master will continue to handle queries when one or more replicas perform the initial synchronization or a partial resynchronization.
* Replication is also largely non-blocking on the replica side.
  While the replica is performing the initial synchronization, it can handle queries using the old version of the dataset, assuming you configured Redis to do so in redis.conf.
  Otherwise, you can configure Redis replicas to return an error to clients if the replication stream is down. However, after the initial sync, the old dataset must be deleted and the new one must be loaded.
  The replica will block incoming connections during this brief window (that can be as long as many seconds for very large datasets).
  Since Redis 4.0 you can configure Redis so that the deletion of the old data set happens in a different thread, however loading the new initial dataset will still happen in the main thread and block the replica.
* Replication can be used both for scalability, to have multiple replicas for read-only queries (for example, slow O(N) operations can be offloaded to replicas), or simply for improving data safety and high availability.
* You can use replication to avoid the cost of having the master writing the full dataset to disk: a typical technique involves configuring your master `redis.conf` to avoid persisting to disk at all, then connect a replica configured to save from time to time, or with AOF enabled.
  However, this setup must be handled with care, since a restarting master will start with an empty dataset: if the replica tries to sync with it, the replica will be emptied as well.

In setups where Redis replication is used, it is strongly advised to have persistence turned on in the master and in the replicas.
When this is not possible, for example because of latency concerns due to very slow disks, instances should be configured to **avoid restarting automatically** after a reboot.

## Replication works

同步分为三种情况：

第一次主从库全量复制；
主从正常运行期间的同步；
主从库间网络断开重连同步。


Every Redis master has a replication ID: it is a large pseudo random string that marks a given story of the dataset.
Each master also takes an offset that increments for every byte of replication stream that it is produced to be sent to replicas, to update the state of the replicas with the new changes modifying the dataset.
The replication offset is incremented even if no replica is actually connected, so basically every given pair of:

```
Replication ID, offset
```

Identifies an exact version of the dataset of a master.

When replicas connect to masters, they use the `PSYNC` command to send their old master replication ID and the offsets they processed so far.
This way the master can send just the incremental part needed.
However if there is not enough *backlog* in the master buffers, or if the replica is referring to an history (replication ID) which is no longer known, then a full resynchronization happens: in this case the replica will get a full copy of the dataset, from scratch.

This is how a full synchronization works in more details:

The master starts a background saving process to produce an RDB file. At the same time it starts to buffer all new write commands received from the clients.
When the background saving is complete, the master transfers the database file to the replica, which saves it on disk, and then loads it into memory.
The master will then send all buffered commands to the replica. This is done as a stream of commands and is in the same format of the Redis protocol itself.

You can try it yourself via telnet.
Connect to the Redis port while the server is doing some work and issue the `SYNC` command.
You'll see a bulk transfer and then every command received by the master will be re-issued in the telnet session.
Actually `SYNC` is an old protocol no longer used by newer Redis instances, but is still there for backward compatibility: it does not allow partial resynchronizations, so now `PSYNC` is used instead.

As already said, replicas are able to automatically reconnect when the master-replica link goes down for some reason.
If the master receives multiple concurrent replica synchronization requests, it performs a single background save in to serve all of them.

This is one of the most complex files inside Redis, it is recommended to approach it only after getting a bit familiar with the rest of the code base. In this file there is the implementation of both the master and replica role of Redis.

One of the most important functions inside this file is `replicationFeedSlaves()` that writes commands to the clients representing replica instances connected to our master, so that the replicas can get the writes performed by the clients: this way their data set will remain synchronized with the one in the master.

This file also implements both the `SYNC` and `PSYNC` commands that are used in order to perform the first synchronization between masters and replicas, or to continue the replication after a disconnection.

Prepare a configuration file for the Redis slave server.
You can make a copy of redis.conf and rename it redis-slave.conf, then make the following changes:

> port 6380
> pidfile /var/run/redis_6380.pid
> replicaof 127.0.0.1 6379

The backlog is a buffer that accumulates replica data when replicas are disconnected for some time, so that when a replica wants to reconnect again, often a full resync is not needed, but a
partial resync is enough, just passing the portion of data the replica missed while disconnected.

The bigger the replication backlog, the longer the replica can endure the disconnect and later be able to perform a partial resynchronization.

The backlog is only allocated if there is at least one replica connected.

```
repl-backlog-size 1mb
```

By calculating the delta value of the master_repl_offset from the INFO command during peak hours, we can estimate an appropriate size for the replication backlog:

> t*(master_repl_offset2- master_repl_offset1)/(t2-t1)
> t  is how long the disconnection may last in seconds

## Expire Keys

Redis expires allow keys to have a limited time to live (TTL). 
Such a feature depends on the ability of an instance to count the time, however Redis replicas correctly replicate keys with expires, even when such keys are altered using Lua scripts.

To implement such a feature Redis cannot rely on the ability of the master and replica to have syncd clocks, since this is a problem that cannot be solved and would result in race conditions and diverging data sets, so Redis uses three main techniques to make the replication of expired keys able to work:

1. Replicas don't expire keys, instead they wait for masters to expire the keys. 
   When a master expires a key (or evict it because of LRU), it synthesizes a `DEL` command which is transmitted to all the replicas.
2. However because of master-driven expire, sometimes replicas may still have in memory keys that are already logically expired, since the master was not able to provide the `DEL` command in time. 
   To deal with that the replica uses its logical clock to report that a key does not exist **only for read operations** that don't violate the consistency of the data set (as new commands from the master will arrive). 
   In this way replicas avoid reporting logically expired keys that are still existing. 
   In practical terms, an HTML fragments cache that uses replicas to scale will avoid returning items that are already older than the desired time to live.
3. During Lua scripts executions no key expiries are performed. As a Lua script runs, conceptually the time in the master is frozen, so that a given key will either exist or not for all the time the script runs. 
   This prevents keys expiring in the middle of a script, and is needed to send the same script to the replica in a way that is guaranteed to have the same effects in the data set.

Once a replica is promoted to a master it will start to expire keys independently, and will not require any help from its old master.

## How Redis replication works

Every Redis master has a replication ID: it is a large pseudo random string that marks a given story of the dataset.
Each master also takes an offset that increments for every byte of replication stream that it is produced to be sent to replicas, in order to update the state of the replicas with the new changes modifying the dataset.
The replication offset is incremented even if no replica is actually connected, so basically every given pair of:

After a master has no connected replicas for some time, the backlog will be freed.
The following option configures the amount of seconds that need to elapse, starting from the time the last replica disconnected, for the backlog buffer to be freed.

Note that replicas never free the backlog for timeout, since they may be promoted to masters later, and should be able to correctly "partially resynchronize" with other replicas: hence they should always accumulate backlog.

A value of 0 means to never release the backlog.

```
repl-backlog-ttl 3600
```

Disable TCP_NODELAY on the replica socket after SYNC?

If you select "yes" Redis will use a smaller number of TCP packets and less bandwidth to send data to replicas.
But this can add a delay for the data to appear on the replica side, up to 40 milliseconds with Linux kernels using a default configuration.

If you select "no" the delay for data to appear on the replica side will be reduced but more bandwidth will be used for replication.

By default we optimize for low latency, but in very high traffic conditions or when the master and replicas are many hops away, turning this to "yes" may be a good idea.

```
repl-disable-tcp-nodelay no
```

```
Replication ID, offset
```

Identifies an exact version of the dataset of a master.

When replicas connect to masters, they use the `PSYNC` command in order to send their old master replication ID and the offsets they processed so far.
This way the master can send just the incremental part needed.
However if there is not enough *backlog* in the master buffers, or if the replica is referring to an history (replication ID) which is no longer known, than a full resynchronization happens: in this case the replica will get a full copy of the dataset, from scratch.

replication buffer

One of the most important functions inside this file is `replicationFeedSlaves()` that writes commands to the clients representing replica instances connected to our master, so that the replicas can get the writes performed by the clients:
this way their data set will remain synchronized with the one in the master.

#### replicationSetMaster

Set replication to the specified master address and port.

```c
// replication.c
void replicationSetMaster(char *ip, int port) {
    int was_master = server.masterhost == NULL;

    sdsfree(server.masterhost);
    server.masterhost = NULL;
    if (server.master) {
        freeClient(server.master);
    }
    disconnectAllBlockedClients(); /* Clients blocked in master, now slave. */

    /* Setting masterhost only after the call to freeClient since it calls
     * replicationHandleMasterDisconnection which can trigger a re-connect
     * directly from within that call. */
    server.masterhost = sdsnew(ip);
    server.masterport = port;

    /* Update oom_score_adj */
    setOOMScoreAdj(-1);

    /* Force our slaves to resync with us as well. They may hopefully be able
     * to partially resync with us, but we can notify the replid change. */
    disconnectSlaves();
    cancelReplicationHandshake(0);
    /* Before destroying our master state, create a cached master using
     * our own parameters, to later PSYNC with the new master. */
    if (was_master) {
        replicationDiscardCachedMaster();
        replicationCacheMasterUsingMyself();
    }

    /* Fire the role change modules event. */
    moduleFireServerEvent(REDISMODULE_EVENT_REPLICATION_ROLE_CHANGED,
                          REDISMODULE_EVENT_REPLROLECHANGED_NOW_REPLICA,
                          NULL);

    /* Fire the master link modules event. */
    if (server.repl_state == REPL_STATE_CONNECTED)
        moduleFireServerEvent(REDISMODULE_EVENT_MASTER_LINK_CHANGE,
                              REDISMODULE_SUBEVENT_MASTER_LINK_DOWN,
                              NULL);

    server.repl_state = REPL_STATE_CONNECT;
    serverLog(LL_NOTICE,"Connecting to MASTER %s:%d",
        server.masterhost, server.masterport);
    connectWithMaster();
}
```

#### connectWithMaster

```c
// replication.c
int connectWithMaster(void) {
    server.repl_transfer_s = server.tls_replication ? connCreateTLS() : connCreateSocket();
    if (connConnect(server.repl_transfer_s, server.masterhost, server.masterport,
                NET_FIRST_BIND_ADDR, syncWithMaster) == C_ERR) {
        serverLog(LL_WARNING,"Unable to connect to MASTER: %s",
                connGetLastError(server.repl_transfer_s));
        connClose(server.repl_transfer_s);
        server.repl_transfer_s = NULL;
        return C_ERR;
    }


    server.repl_transfer_lastio = server.unixtime;
    server.repl_state = REPL_STATE_CONNECTING;
    serverLog(LL_NOTICE,"MASTER <-> REPLICA sync started");
    return C_OK;
}
```

#### sync

This handler fires when the non blocking connect was able to establish a connection with the master.

```c
void syncWithMaster(connection *conn) {
```

## PSYNC

![](https://mmbiz.qpic.cn/mmbiz_png/FbXJ7UCc6O1zU7aax8Hldic4B0PNZTsqhNvt5GshSvzh4e0y6YHtom4h83npL4XXZGicaJicicSKMbIT5KxybRjuXw/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

### fullsync
主从库第一次复制过程大体可以分为 3 个阶段：连接建立阶段（即准备阶段）、主库同步数据到从库阶段、发送同步期间新写命令到从库阶段

建立连接
该阶段的主要作用是在主从节点之间建立连接，为数据全量同步做好准备。从库会和主库建立连接，从库执行 replicaof 并发送 psync 命令并告诉主库即将进行同步，主库确认回复后会用 FULLRESYNC 响应命令带上两个参数：主库 runID 和主库目前的复制进度 offset，返回给从库，主从库间就开始同步了

master 执行 bgsave命令生成 RDB 文件，并将文件发送给从库，同时主库为每一个 slave 开辟一块 replication buffer 缓冲区记录从生成 RDB 文件开始收到的所有写命令。

从库收到 RDB 文件后保存到磁盘，并清空当前数据库的数据，再加载 RDB 文件数据到内存中


从节点加载 RDB 完成后，主节点将 replication buffer 缓冲区的数据发送到从节点，Slave 接收并执行，从节点同步至主节点相同的状态。


replication buffer是一个在 master 端上创建的缓冲区，存放的数据是下面三个时间内所有的 master 数据写操作。

1. master 执行 bgsave 产生 RDB 的期间的写操作；
2. master 发送 rdb 到 slave 网络传输期间的写操作；
3. slave load rdb 文件把数据恢复到内存的期间的写操作。

replication buffer 由 client-output-buffer-limit slave 设置，当这个值太小会导致主从复制连接断开
1）当 master-slave 复制连接断开，master 会释放连接相关的数据。replication buffer 中的数据也就丢失了，此时主从之间重新开始复制过程。

2）还有个更严重的问题，主从复制连接断开，导致主从上出现重新执行 bgsave 和 rdb 重传操作无限循环。

当主节点数据量较大，或者主从节点之间网络延迟较大时，可能导致该缓冲区的大小超过了限制，此时主节点会断开与从节点之间的连接；

这种情况可能引起全量复制 -> replication buffer 溢出导致连接中断 -> 重连 -> 全量复制 -> replication buffer 缓冲区溢出导致连接中断……的循环。
推荐把 replication buffer 的 hard/soft limit 设置成 512M



### 增量复制
当主从库完成了全量复制，它们之间就会一直维护一个网络连接，主库会通过这个连接将后续陆续收到的命令操作再同步给从库，这个过程也称为基于长连接的命令传播，使用长连接的目的就是避免频繁建立连接导致的开销。

在命令传播阶段，除了发送写命令，主从节点还维持着心跳机制：PING 和 REPLCONF ACK


断开重连增量复制的实现奥秘就是 repl_backlog_buffer 缓冲区，不管在什么时候 master 都会将写指令操作记录在 repl_backlog_buffer 中，因为内存有限， repl_backlog_buffer 是一个定长的环形数组，如果数组内容满了，就会从头开始覆盖前面的内容。

master 使用 master_repl_offset记录自己写到的位置偏移量，slave 则使用 slave_repl_offset记录已经读取到的偏移量
master 收到写操作，偏移量则会增加。从库持续执行同步的写指令后，在 repl_backlog_buffer 的已复制的偏移量 slave_repl_offset 也在不断增加。

正常情况下，这两个偏移量基本相等。在网络断连阶段，主库可能会收到新的写操作命令，所以 master_repl_offset会大于 slave_repl_offset

当主从断开重连后，slave 会先发送 psync 命令给 master，同时将自己的 runID，slave_repl_offset发送给 master。

master 只需要把 master_repl_offset与 slave_repl_offset之间的命令同步给从库即可。



replication buffer 和 repl_backlog

replication buffer 对应于每个 slave，通过 config set client-output-buffer-limit slave设置。
repl_backlog_buffer是一个环形缓冲区，整个 master 进程中只会存在一个，所有的 slave 公用。repl_backlog 的大小通过 repl-backlog-size 参数设置，默认大小是 1M，其大小可以根据每秒产生的命令、（master 执行 rdb bgsave） +（ master 发送 rdb 到 slave） + （slave load rdb 文件）时间之和来估算积压缓冲区的大小，repl-backlog-size 值不小于这两者的乘积。
总的来说，replication buffer 是主从库在进行全量复制时，主库上用于和从库连接的客户端的 buffer，而 repl_backlog_buffer 是为了支持从库增量复制，主库上用于持续保存写操作的一块专用 buffer。

repl_backlog_buffer是一块专用 buffer，在 Redis 服务器启动后，开始一直接收写操作命令，这是所有从库共享的。主库和从库会各自记录自己的复制进度，所以，不同的从库在进行恢复时，会把自己的复制进度（slave_repl_offset）发给主库，主库就可以和它独立同步。
### master

#### masterTryPartialResynchronization

This function handles the PSYNC command from the point of view of a master receiving a request for partial resynchronization.

On success return C_OK, otherwise C_ERR is returned and we proceed with the usual full resync.

```c
int masterTryPartialResynchronization(client *c) {
    long long psync_offset, psync_len;
    char *master_replid = c->argv[1]->ptr;
    char buf[128];
    int buflen;

    /* Parse the replication offset asked by the slave. Go to full sync
     * on parse error: this should never happen but we try to handle
     * it in a robust way compared to aborting. */
    if (getLongLongFromObjectOrReply(c,c->argv[2],&psync_offset,NULL) !=
       C_OK) goto need_full_resync;

    /* Is the replication ID of this master the same advertised by the wannabe
     * slave via PSYNC? If the replication ID changed this master has a
     * different replication history, and there is no way to continue.
     *
     * Note that there are two potentially valid replication IDs: the ID1
     * and the ID2. The ID2 however is only valid up to a specific offset. */
    if (strcasecmp(master_replid, server.replid) &&
        (strcasecmp(master_replid, server.replid2) ||
         psync_offset > server.second_replid_offset))
    {
        /* Replid "?" is used by slaves that want to force a full resync. */
        if (master_replid[0] != '?') {
            if (strcasecmp(master_replid, server.replid) &&
                strcasecmp(master_replid, server.replid2))
            {
                serverLog(LL_NOTICE,"Partial resynchronization not accepted: "
                    "Replication ID mismatch (Replica asked for '%s', my "
                    "replication IDs are '%s' and '%s')",
                    master_replid, server.replid, server.replid2);
            } else {
                serverLog(LL_NOTICE,"Partial resynchronization not accepted: "
                    "Requested offset for second ID was %lld, but I can reply "
                    "up to %lld", psync_offset, server.second_replid_offset);
            }
        } else {
            serverLog(LL_NOTICE,"Full resync requested by replica %s",
                replicationGetSlaveName(c));
        }
        goto need_full_resync;
    }

    /* We still have the data our slave is asking for? */
    if (!server.repl_backlog ||
        psync_offset < server.repl_backlog_off ||
        psync_offset > (server.repl_backlog_off + server.repl_backlog_histlen))
    {
        serverLog(LL_NOTICE,
            "Unable to partial resync with replica %s for lack of backlog (Replica request was: %lld).", replicationGetSlaveName(c), psync_offset);
        if (psync_offset > server.master_repl_offset) {
            serverLog(LL_WARNING,
                "Warning: replica %s tried to PSYNC with an offset that is greater than the master replication offset.", replicationGetSlaveName(c));
        }
        goto need_full_resync;
    }

    /* If we reached this point, we are able to perform a partial resync:
     * 1) Set client state to make it a slave.
     * 2) Inform the client we can continue with +CONTINUE
     * 3) Send the backlog data (from the offset to the end) to the slave. */
    c->flags |= CLIENT_SLAVE;
    c->replstate = SLAVE_STATE_ONLINE;
    c->repl_ack_time = server.unixtime;
    c->repl_put_online_on_ack = 0;
    listAddNodeTail(server.slaves,c);
    /* We can't use the connection buffers since they are used to accumulate
     * new commands at this stage. But we are sure the socket send buffer is
     * empty so this write will never fail actually. */
    if (c->slave_capa & SLAVE_CAPA_PSYNC2) {
        buflen = snprintf(buf,sizeof(buf),"+CONTINUE %s\r\n", server.replid);
    } else {
        buflen = snprintf(buf,sizeof(buf),"+CONTINUE\r\n");
    }
    if (connWrite(c->conn,buf,buflen) != buflen) {
        freeClientAsync(c);
        return C_OK;
    }
    psync_len = addReplyReplicationBacklog(c,psync_offset);
    serverLog(LL_NOTICE,
        "Partial resynchronization request from %s accepted. Sending %lld bytes of backlog starting from offset %lld.",
            replicationGetSlaveName(c),
            psync_len, psync_offset);
    /* Note that we don't need to set the selected DB at server.slaveseldb
     * to -1 to force the master to emit SELECT, since the slave already
     * has this state from the previous connection with the master. */

    refreshGoodSlavesCount();

    /* Fire the replica change modules event. */
    moduleFireServerEvent(REDISMODULE_EVENT_REPLICA_CHANGE,
                          REDISMODULE_SUBEVENT_REPLICA_CHANGE_ONLINE,
                          NULL);

    return C_OK; /* The caller can return, no full resync needed. */

need_full_resync:
    /* We need a full resync for some reason... Note that we can't
     * reply to PSYNC right now if a full SYNC is needed. The reply
     * must include the master offset at the time the RDB file we transfer
     * is generated, so we need to delay the reply to that moment. */
    return C_ERR;
}
```

### slave

Try a partial resynchronization with the master if we are about to reconnect.
If there is no cached master structure, at least try to issue a "PSYNC ? -1" command in order to trigger a full resync using the PSYNC command in order to obtain the master replid and the master replication global offset.

This function is designed to be called from syncWithMaster(), so the following assumptions are made:

1. We pass the function an already connected socket "fd".
2. This function does not close the file descriptor "fd".
   However in case of successful partial resynchronization, the function will reuse 'fd' as file descriptor of the server.master client structure.

The function is split in two halves: if read_reply is 0, the function writes the PSYNC command on the socket, and a new function call is needed, with read_reply set to 1, in order to read the reply of the command.
This is useful in order to support non blocking operations, so that we write, return into the event loop, and read when there are data.

When read_reply is 0 the function returns PSYNC_WRITE_ERR if there was a write error, or PSYNC_WAIT_REPLY to signal we need another call with read_reply set to 1.
However even when read_reply is set to 1 the function may return PSYNC_WAIT_REPLY again to signal there were insufficient data to read to complete its work.
We should re-enter into the event loop and wait in such a case.

The function returns:

- PSYNC_CONTINUE: If the PSYNC command succeeded and we can continue.
- PSYNC_FULLRESYNC: If PSYNC is supported but a full resync is needed. In this case the master replid and global replication offset is saved.
- PSYNC_NOT_SUPPORTED: If the server does not understand PSYNC at all and the caller should fall back to SYNC.
- PSYNC_WRITE_ERROR: There was an error writing the command to the socket.
- PSYNC_WAIT_REPLY: Call again the function with read_reply set to 1.
- PSYNC_TRY_LATER: Master is currently in a transient error condition.

Notable side effects:

1. As a side effect of the function call the function removes the readable event handler from "fd", unless the return value is PSYNC_WAIT_REPLY.
2. server.master_initial_offset is set to the right value according to the master reply. This will be used to populate the 'server.master' structure replication offset.

#### slaveTryPartialResynchronization

```c
int slaveTryPartialResynchronization(connection *conn, int read_reply) {
    char *psync_replid;
    char psync_offset[32];
    sds reply;

    /* Writing half */
    if (!read_reply) {
        /* Initially set master_initial_offset to -1 to mark the current
         * master replid and offset as not valid. Later if we'll be able to do
         * a FULL resync using the PSYNC command we'll set the offset at the
         * right value, so that this information will be propagated to the
         * client structure representing the master into server.master. */
        server.master_initial_offset = -1;

        if (server.cached_master) {
            psync_replid = server.cached_master->replid;
            snprintf(psync_offset,sizeof(psync_offset),"%lld", server.cached_master->reploff+1);
            serverLog(LL_NOTICE,"Trying a partial resynchronization (request %s:%s).", psync_replid, psync_offset);
        } else {
            serverLog(LL_NOTICE,"Partial resynchronization not possible (no cached master)");
            psync_replid = "?";
            memcpy(psync_offset,"-1",3);
        }

        /* Issue the PSYNC command, if this is a master with a failover in
         * progress then send the failover argument to the replica to cause it
         * to become a master */
        if (server.failover_state == FAILOVER_IN_PROGRESS) {
            reply = sendCommand(conn,"PSYNC",psync_replid,psync_offset,"FAILOVER",NULL);
        } else {
            reply = sendCommand(conn,"PSYNC",psync_replid,psync_offset,NULL);
        }

        if (reply != NULL) {
            serverLog(LL_WARNING,"Unable to send PSYNC to master: %s",reply);
            sdsfree(reply);
            connSetReadHandler(conn, NULL);
            return PSYNC_WRITE_ERROR;
        }
        return PSYNC_WAIT_REPLY;
    }

    /* Reading half */
    reply = receiveSynchronousResponse(conn);
    if (sdslen(reply) == 0) {
        /* The master may send empty newlines after it receives PSYNC
         * and before to reply, just to keep the connection alive. */
        sdsfree(reply);
        return PSYNC_WAIT_REPLY;
    }

    connSetReadHandler(conn, NULL);

    if (!strncmp(reply,"+FULLRESYNC",11)) {
        char *replid = NULL, *offset = NULL;

        /* FULL RESYNC, parse the reply in order to extract the replid
         * and the replication offset. */
        replid = strchr(reply,' ');
        if (replid) {
            replid++;
            offset = strchr(replid,' ');
            if (offset) offset++;
        }
        if (!replid || !offset || (offset-replid-1) != CONFIG_RUN_ID_SIZE) {
            serverLog(LL_WARNING,
                "Master replied with wrong +FULLRESYNC syntax.");
            /* This is an unexpected condition, actually the +FULLRESYNC
             * reply means that the master supports PSYNC, but the reply
             * format seems wrong. To stay safe we blank the master
             * replid to make sure next PSYNCs will fail. */
            memset(server.master_replid,0,CONFIG_RUN_ID_SIZE+1);
        } else {
            memcpy(server.master_replid, replid, offset-replid-1);
            server.master_replid[CONFIG_RUN_ID_SIZE] = '\0';
            server.master_initial_offset = strtoll(offset,NULL,10);
            serverLog(LL_NOTICE,"Full resync from master: %s:%lld",
                server.master_replid,
                server.master_initial_offset);
        }
        /* We are going to full resync, discard the cached master structure. */
        replicationDiscardCachedMaster();
        sdsfree(reply);
        return PSYNC_FULLRESYNC;
    }

    if (!strncmp(reply,"+CONTINUE",9)) {
        /* Partial resync was accepted. */
        serverLog(LL_NOTICE,
            "Successful partial resynchronization with master.");

        /* Check the new replication ID advertised by the master. If it
         * changed, we need to set the new ID as primary ID, and set or
         * secondary ID as the old master ID up to the current offset, so
         * that our sub-slaves will be able to PSYNC with us after a
         * disconnection. */
        char *start = reply+10;
        char *end = reply+9;
        while(end[0] != '\r' && end[0] != '\n' && end[0] != '\0') end++;
        if (end-start == CONFIG_RUN_ID_SIZE) {
            char new[CONFIG_RUN_ID_SIZE+1];
            memcpy(new,start,CONFIG_RUN_ID_SIZE);
            new[CONFIG_RUN_ID_SIZE] = '\0';

            if (strcmp(new,server.cached_master->replid)) {
                /* Master ID changed. */
                serverLog(LL_WARNING,"Master replication ID changed to %s",new);

                /* Set the old ID as our ID2, up to the current offset+1. */
                memcpy(server.replid2,server.cached_master->replid,
                    sizeof(server.replid2));
                server.second_replid_offset = server.master_repl_offset+1;

                /* Update the cached master ID and our own primary ID to the
                 * new one. */
                memcpy(server.replid,new,sizeof(server.replid));
                memcpy(server.cached_master->replid,new,sizeof(server.replid));

                /* Disconnect all the sub-slaves: they need to be notified. */
                disconnectSlaves();
            }
        }

        /* Setup the replication to continue. */
        sdsfree(reply);
        replicationResurrectCachedMaster(conn);

        /* If this instance was restarted and we read the metadata to
         * PSYNC from the persistence file, our replication backlog could
         * be still not initialized. Create it. */
        if (server.repl_backlog == NULL) createReplicationBacklog();
        return PSYNC_CONTINUE;
    }

    /* If we reach this point we received either an error (since the master does
     * not understand PSYNC or because it is in a special state and cannot
     * serve our request), or an unexpected reply from the master.
     *
     * Return PSYNC_NOT_SUPPORTED on errors we don't understand, otherwise
     * return PSYNC_TRY_LATER if we believe this is a transient error. */

    if (!strncmp(reply,"-NOMASTERLINK",13) ||
        !strncmp(reply,"-LOADING",8))
    {
        serverLog(LL_NOTICE,
            "Master is currently unable to PSYNC "
            "but should be in the future: %s", reply);
        sdsfree(reply);
        return PSYNC_TRY_LATER;
    }

    if (strncmp(reply,"-ERR",4)) {
        /* If it's not an error, log the unexpected event. */
        serverLog(LL_WARNING,
            "Unexpected reply to PSYNC from master: %s", reply);
    } else {
        serverLog(LL_NOTICE,
            "Master does not support PSYNC or is in "
            "error state (reply: %s)", reply);
    }
    sdsfree(reply);
    replicationDiscardCachedMaster();
    return PSYNC_NOT_SUPPORTED;
}
```

Propagate write commands to slaves, and populate the replication backlog as well.
This function is used if the instance is a master: we use the commands received by our clients in order to create the replication stream.
Instead if the instance is a slave and has sub-slaves attached, we use replicationFeedSlavesFromMasterStream()

```c
void replicationFeedSlaves(list *slaves, int dictid, robj **argv, int argc) {
    listNode *ln;
    listIter li;
    int j, len;
    char llstr[LONG_STR_SIZE];

    /* If the instance is not a top level master, return ASAP: we'll just proxy
     * the stream of data we receive from our master instead, in order to
     * propagate *identical* replication stream. In this way this slave can
     * advertise the same replication ID as the master (since it shares the
     * master replication history and has the same backlog and offsets). */
    if (server.masterhost != NULL) return;
```

If there aren't slaves, and there is no backlog buffer to populate, we can return ASAP.

```c
    if (server.repl_backlog == NULL && listLength(slaves) == 0) return;

    /* We can't have slaves attached and no backlog. */
    serverAssert(!(listLength(slaves) != 0 && server.repl_backlog == NULL));

    /* Send SELECT command to every slave if needed. */
    if (server.slaveseldb != dictid) {
        robj *selectcmd;

        /* For a few DBs we have pre-computed SELECT command. */
        if (dictid >= 0 && dictid < PROTO_SHARED_SELECT_CMDS) {
            selectcmd = shared.select[dictid];
        } else {
            int dictid_len;

            dictid_len = ll2string(llstr,sizeof(llstr),dictid);
            selectcmd = createObject(OBJ_STRING,
                sdscatprintf(sdsempty(),
                "*2\r\n$6\r\nSELECT\r\n$%d\r\n%s\r\n",
                dictid_len, llstr));
        }

        /* Add the SELECT command into the backlog. */
        if (server.repl_backlog) feedReplicationBacklogWithObject(selectcmd);

        /* Send it to slaves. */
        listRewind(slaves,&li);
        while((ln = listNext(&li))) {
            client *slave = ln->value;

            if (!canFeedReplicaReplBuffer(slave)) continue;
            addReply(slave,selectcmd);
        }

        if (dictid < 0 || dictid >= PROTO_SHARED_SELECT_CMDS)
            decrRefCount(selectcmd);
    }
    server.slaveseldb = dictid;

    /* Write the command to the replication backlog if any. */
    if (server.repl_backlog) {
        char aux[LONG_STR_SIZE+3];

        /* Add the multi bulk reply length. */
        aux[0] = '*';
        len = ll2string(aux+1,sizeof(aux)-1,argc);
        aux[len+1] = '\r';
        aux[len+2] = '\n';
        feedReplicationBacklog(aux,len+3);

        for (j = 0; j < argc; j++) {
            long objlen = stringObjectLen(argv[j]);

            /* We need to feed the buffer with the object as a bulk reply
             * not just as a plain string, so create the $..CRLF payload len
             * and add the final CRLF */
            aux[0] = '$';
            len = ll2string(aux+1,sizeof(aux)-1,objlen);
            aux[len+1] = '\r';
            aux[len+2] = '\n';
            feedReplicationBacklog(aux,len+3);
            feedReplicationBacklogWithObject(argv[j]);
            feedReplicationBacklog(aux+len+1,2);
        }
    }

    /* Write the command to every slave. */
    listRewind(slaves,&li);
    while((ln = listNext(&li))) {
        client *slave = ln->value;

        if (!canFeedReplicaReplBuffer(slave)) continue;

        /* Feed slaves that are waiting for the initial SYNC (so these commands
         * are queued in the output buffer until the initial SYNC completes),
         * or are already in sync with the master. */

        /* Add the multi bulk length. */
        addReplyArrayLen(slave,argc);

        /* Finally any additional argument that was not stored inside the
         * static buffer if any (from j to argc). */
        for (j = 0; j < argc; j++)
            addReplyBulk(slave,argv[j]);
    }
}
```

## Memory

By default, a replica will ignore `maxmemory` (unless it is promoted to master after a failover or manually).
It means that the eviction of keys will be handled by the master, sending the DEL commands to the replica as keys evict in the master side.

This behavior ensures that masters and replicas stay consistent, which is usually what you want.
However, if your replica is writable, or you want the replica to have a different memory setting, and you are sure all the writes performed to the replica are idempotent, then you may change this default (but be sure to understand what you are doing).

Note that since the replica by default does not evict, it may end up using more memory than what is set via `maxmemory` (since there are certain buffers that may be larger on the replica, or data structures may sometimes take more memory and so forth).
Make sure you monitor your replicas, and make sure they have enough memory to never hit a real out-of-memory condition before the master hits the configured `maxmemory` setting.

To change this behavior, you can allow a replica to not ignore the `maxmemory`. The configuration directives to use is:

```
replica-ignore-maxmemory no
```

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md?id=persistence)

## References

1. [Redis Replication](https://redis.io/topics/replication#partial-resynchronizations-after-restarts-and-failovers)
2. [Top Redis Headaches for Devops – Replication Timeouts](https://redis.io/blog/top-redis-headaches-for-devops-replication-timeouts/)
