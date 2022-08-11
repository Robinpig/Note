## Introduction

replication.c

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

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md?id=persistence)

## References

1. [Redis Replication](https://redis.io/topics/replication#partial-resynchronizations-after-restarts-and-failovers)
