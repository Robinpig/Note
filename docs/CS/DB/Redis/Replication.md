## Introduction





Prepare a configuration file for the Redis slave server. You can make a copy
of redis.conf and rename it redis-slave.conf, then make the following changes:

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






After a master has no connected replicas for some time, the backlog will be freed. The following option configures the amount of seconds that need to elapse, starting from the time the last replica disconnected, for the backlog buffer to be freed.

Note that replicas never free the backlog for timeout, since they may be promoted to masters later, and should be able to correctly "partially resynchronize" with other replicas: hence they should always accumulate backlog.

A value of 0 means to never release the backlog.
```
repl-backlog-ttl 3600
```





Disable TCP_NODELAY on the replica socket after SYNC?

If you select "yes" Redis will use a smaller number of TCP packets and less bandwidth to send data to replicas. But this can add a delay for the data to appear on the replica side, up to 40 milliseconds with Linux kernels using a default configuration.

If you select "no" the delay for data to appear on the replica side will be reduced but more bandwidth will be used for replication.

By default we optimize for low latency, but in very high traffic conditions or when the master and replicas are many hops away, turning this to "yes" may be a good idea.

```
repl-disable-tcp-nodelay no
```



## References

1. [Redis Replication](https://redis.io/topics/replication#partial-resynchronizations-after-restarts-and-failovers)
