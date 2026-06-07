## 介绍

在 Redis 复制的基础上（不包括由 Redis Cluster 或 Redis Sentinel 提供的额外高可用性功能），有一个简单易用且易于配置的*领导者追随者*（主-从）复制机制。
它允许从 Redis 实例成为主实例的精确副本。
每当链接断开时，从实例会自动重新连接到主实例，并*无论*主实例发生什么，都会尝试成为其精确副本。

该系统使用三个主要机制工作：

1. 当主实例和从实例连接良好时，主实例通过向从实例发送命令流来保持从实例更新，以复制主实例端由于以下原因导致的数据集变化：
   客户端写入、键过期或淘汰、任何其他更改主数据集的行动。
2. 当主从之间的链接因网络问题或主从端超时而断开时，从实例重新连接并尝试进行部分重新同步：
   这意味着它将尝试仅获取断开期间错过的命令流部分。
3. 当无法进行部分重新同步时，从实例将请求全量重新同步。
   这将涉及一个更复杂的过程，其中主实例需要创建其所有数据的快照，发送给从实例，然后随着数据集的变化继续发送命令流。

Redis 默认使用异步复制，具有低延迟和高性能的特点，是绝大多数 Redis 用例的自然复制模式。
然而，Redis 从实例会异步确认它们定期从主实例接收的数据量。
因此主实例不会每次都等待从实例处理命令，但如果需要，它知道哪个从实例已经处理了哪个命令。这允许支持可选的同步复制。

客户端可以使用 `WAIT` 命令请求某些数据的同步复制。
然而 `WAIT` 只能确保在其他 Redis 实例中存在指定数量的已确认副本，它不会将一组 Redis 实例转换为具有强一致性的 CP 系统：
已确认的写入在故障转移期间仍可能丢失，具体取决于 Redis 持久化的确切配置。
但使用 `WAIT` 后，故障事件后丢失写入的概率大大降低，仅限于某些难以触发的故障模式。

### 重要事实

* Redis 使用异步复制，从实例异步确认已处理的数据量。
* 一个主实例可以有多个从实例。
* 从实例能够接受其他从实例的连接。除了将多个从实例连接到同一个主实例外，从实例还可以以级联结构连接到其他从实例。
  从 Redis 4.0 开始，所有子从实例将从主实例接收完全相同的复制流。
* Redis 复制在主端是非阻塞的。这意味着当一个或多个从实例执行初始同步或部分重新同步时，主实例将继续处理查询。
* 复制在从端也基本上是非阻塞的。
  当从实例执行初始同步时，它可以继续使用旧版本的数据集处理查询，前提是你已在 redis.conf 中配置 Redis 这样做。
  否则，你可以配置 Redis 从实例在复制流断开时向客户端返回错误。然而，初始同步后，旧数据集必须被删除，新数据集必须加载。
  在这个短暂的时间窗口内（对于非常大的数据集可能长达数秒），从实例将阻塞传入连接。
  从 Redis 4.0 开始，你可以配置 Redis 在单独的线程中删除旧数据集，但加载新的初始数据集仍将在主线程中进行并阻塞从实例。
* 复制既可用于可扩展性，让多个从实例处理只读查询（例如，慢的 O(N) 操作可以卸载到从实例），也可用于提高数据安全性和高可用性。
* 你可以使用复制来避免主实例将完整数据集写入磁盘的成本：一种典型技术是配置主实例 `redis.conf` 完全避免持久化，然后连接一个配置为定期保存或启用 AOF 的从实例。
  然而，这种设置必须谨慎处理，因为重启的主实例将以空数据集启动：如果从实例尝试与其同步，从实例也会被清空。

在使用 Redis 复制的设置中，强烈建议在主实例和从实例上都开启持久化。
如果无法做到，例如由于磁盘较慢导致的延迟问题，实例应配置为在重启后**避免自动重启**。

## 复制工作原理

同步分为三种情况：

- 第一次主从库全量复制；
- 主从正常运行期间的同步；
- 主从库间网络断开重连同步。

每个 Redis 主实例都有一个复制 ID：它是一个大的伪随机字符串，标记数据集的一段给定历史。
每个主实例还会维护一个偏移量，该偏移量随复制流的每个字节递增，复制流被生成以发送给从实例，以使用修改数据集的新更改更新从实例的状态。
即使没有从实例实际连接，复制偏移量也会递增，因此基本上每个给定的：

```
Replication ID, offset
```

标识了主实例数据集的一个精确版本。

当从实例连接到主实例时，它们使用 `PSYNC` 命令发送其旧的主实例复制 ID 和已处理的偏移量。
这样主实例只需发送所需的增量部分。
然而，如果主实例缓冲区中没有足够的*积压*，或者从实例引用的历史（复制 ID）已不再知晓，则会发生全量重新同步：在这种情况下，从实例将从头开始获取数据集的完整副本。

以下是全量同步的详细工作方式：

主实例启动后台保存进程以生成 RDB 文件。同时，它开始缓冲从客户端收到的所有新写入命令。
当后台保存完成时，主实例将数据库文件传输给从实例，从实例将其保存到磁盘，然后加载到内存中。
然后主实例将所有缓冲的命令发送给从实例。这是作为命令流完成的，格式与 Redis 协议本身相同。

你可以通过 telnet 亲自尝试。
在服务器执行某些工作时连接到 Redis 端口并发出 `SYNC` 命令。
你会看到一个批量传输，然后主实例收到的每个命令都会在 telnet 会话中重新发出。
实际上 `SYNC` 是一个旧协议，新的 Redis 实例不再使用，但仍保留用于向后兼容：它不允许部分重新同步，所以现在使用 `PSYNC`。

如前所述，当主从链接因某种原因断开时，从实例能够自动重新连接。
如果主实例收到多个并发的从实例同步请求，它会执行一次后台保存来服务所有从实例。

这是 Redis 内部最复杂的文件之一，建议在熟悉了其他代码库后再来阅读。此文件中实现了 Redis 的主实例和从实例角色。

此文件中最重要的函数之一是 `replicationFeedSlaves()`，它将命令写入连接到我们主实例的从实例客户端，以便从实例能够获取客户端执行的写入：这样它们的数据集将与主实例保持同步。

此文件还实现了 `SYNC` 和 `PSYNC` 命令，用于执行主从之间的首次同步，或在断开连接后继续复制。

为 Redis 从服务器准备配置文件。
你可以复制 redis.conf 并重命名为 redis-slave.conf，然后进行以下更改：

> port 6380
> pidfile /var/run/redis_6380.pid
> replicaof 127.0.0.1 6379

积压是一个缓冲区，在从实例断开连接一段时间后累积从实例数据，这样当从实例想要重新连接时，通常不需要全量重新同步，
而只需要部分重新同步，传递从实例断开期间错过的数据部分即可。

复制积压越大，从实例可以忍受断开的连接时间越长，之后才能执行部分重新同步。

只有至少连接了一个从实例时，积压才会分配。

```
repl-backlog-size 1mb
```

通过计算高峰时段 INFO 命令中的 master_repl_offset 的增量值，我们可以估计复制积压的适当大小：

> t*(master_repl_offset2- master_repl_offset1)/(t2-t1)
> t 是断开可能持续的时间（秒）

## 过期键

Redis 过期允许键具有有限的生命周期（TTL）。
此功能依赖于实例计时能力，但 Redis 从实例可以正确复制具有过期时间的键，即使这些键是使用 Lua 脚本更改的。

为了实现此功能，Redis 不能依赖主从实例具有同步时钟，因为这是一个无法解决的问题，会导致竞争条件和数据集发散，因此 Redis 使用三种主要技术使过期键的复制能够工作：

1. 从实例不会过期键，而是等待主实例过期键。
   当主实例过期键（或由于 LRU 淘汰键）时，它会合成一个 `DEL` 命令，传输给所有从实例。
2. 然而，由于主驱动的过期，有时从实例可能仍然在内存中保存已逻辑过期的键，因为主实例未能及时提供 `DEL` 命令。
   为处理这种情况，从实例使用其逻辑时钟报告键不存在，**仅针对不违反数据集一致性的读操作**（因为来自主实例的新命令会到达）。
   这样，从实例避免报告仍然存在的逻辑过期键。
   实际上，使用从实例来扩展的 HTML 片段缓存将避免返回已经超过所需 TTL 的项目。
3. 在 Lua 脚本执行期间，不会进行任何键过期。当 Lua 脚本运行时，概念上主实例的时间被冻结，因此给定的键在脚本运行的所有时间内要么存在要么不存在。
   这防止了键在脚本执行中途过期，并且是向从实例发送相同脚本以确保对数据集产生相同效果所必需的。

一旦从实例被提升为主实例，它将开始独立过期键，并且不需要从其旧主实例获得任何帮助。

## Redis 复制如何工作

每个 Redis 主实例都有一个复制 ID：它是一个大的伪随机字符串，标记数据集的一段给定历史。
每个主实例还会维护一个偏移量，该偏移量随复制流的每个字节递增，复制流被生成以发送给从实例，以使用修改数据集的新更改更新从实例的状态。
即使没有从实例实际连接，复制偏移量也会递增。

在主实例一段时间没有连接的从实例后，积压将被释放。
以下选项配置从最后一个从实例断开连接开始，需要经过多少秒积压缓冲区才会被释放。

请注意，从实例永远不会因超时而释放积压，因为它们稍后可能被提升为主实例，并且应能正确地对其他从实例进行"部分重新同步"：因此它们应始终保持积压。

值为 0 表示永远不会释放积压。

```
repl-backlog-ttl 3600
```

在 SYNC 后禁用从套接字的 TCP_NODELAY？

如果选择"yes"，Redis 将使用更少的 TCP 数据包和更少的带宽向从实例发送数据。
但这可能会增加数据在从端出现的时间延迟，使用 Linux 内核的默认配置可达 40 毫秒。

如果选择"no"，数据在从端出现的延迟将减少，但复制将使用更多带宽。

默认情况下，我们优化低延迟，但在非常高的流量条件下，或者当主从实例之间的距离很远时，将此设置为"yes"可能是个好主意。

```
repl-disable-tcp-nodelay no
```

```
Replication ID, offset
```

标识了主实例数据集的一个精确版本。

当从实例连接到主实例时，它们使用 `PSYNC` 命令发送其旧的主实例复制 ID 和已处理的偏移量。
这样主实例只需发送所需的增量部分。
然而，如果主实例缓冲区中没有足够的*积压*，或者从实例引用的历史（复制 ID）已不再知晓，则会发生全量重新同步：在这种情况下，从实例将从头开始获取数据集的完整副本。

replication buffer

此文件中最重要的函数之一是 `replicationFeedSlaves()`，它将命令写入连接到我们主实例的从实例客户端，以便从实例能够获取客户端执行的写入：
这样它们的数据集将与主实例保持同步。

#### replicationSetMaster

将复制设置为指定的主实例地址和端口。

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

当非阻塞连接能够与主实例建立连接时，此处理程序触发。

```c
void syncWithMaster(connection *conn) {
```

## PSYNC

![](https://mmbiz.qpic.cn/mmbiz_png/FbXJ7UCc6O1zU7aax8Hldic4B0PNZTsqhNvt5GshSvzh4e0y6YHtom4h83npL4XXZGicaJicicSKMbIT5KxybRjuXw/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

### fullsync

主从库第一次复制过程大体可以分为 3 个阶段：连接建立阶段（即准备阶段）、主库同步数据到从库阶段、发送同步期间新写命令到从库阶段。

建立连接
该阶段的主要作用是在主从节点之间建立连接，为数据全量同步做好准备。从库会和主库建立连接，从库执行 replicaof 并发送 psync 命令并告诉主库即将进行同步，主库确认回复后会用 FULLRESYNC 响应命令带上两个参数：主库 runID 和主库目前的复制进度 offset，返回给从库，主从库间就开始同步了。

master 执行 bgsave 命令生成 RDB 文件，并将文件发送给从库，同时主库为每一个 slave 开辟一块 replication buffer 缓冲区记录从生成 RDB 文件开始收到的所有写命令。

从库收到 RDB 文件后保存到磁盘，并清空当前数据库的数据，再加载 RDB 文件数据到内存中。

从节点加载 RDB 完成后，主节点将 replication buffer 缓冲区的数据发送到从节点，Slave 接收并执行，从节点同步至主节点相同的状态。

replication buffer 是一个在 master 端上创建的缓冲区，存放的数据是下面三个时间内所有的 master 数据写操作。

1. master 执行 bgsave 产生 RDB 的期间的写操作；
2. master 发送 rdb 到 slave 网络传输期间的写操作；
3. slave load rdb 文件把数据恢复到内存的期间的写操作。

replication buffer 由 client-output-buffer-limit slave 设置，当这个值太小会导致主从复制连接断开。
1. 当 master-slave 复制连接断开，master 会释放连接相关的数据。replication buffer 中的数据也就丢失了，此时主从之间重新开始复制过程。
2. 还有个更严重的问题，主从复制连接断开，导致主从上出现重新执行 bgsave 和 rdb 重传操作无限循环。

当主节点数据量较大，或者主从节点之间网络延迟较大时，可能导致该缓冲区的大小超过了限制，此时主节点会断开与从节点之间的连接。

这种情况可能引起全量复制 -> replication buffer 溢出导致连接中断 -> 重连 -> 全量复制 -> replication buffer 缓冲区溢出导致连接中断……的循环。
推荐把 replication buffer 的 hard/soft limit 设置成 512M。

一次全量复制中，对于主库来说，需要完成两个耗时的操作：生成 RDB 文件和传输 RDB 文件。
如果从库数量很多，而且都要和主库进行全量复制的话，就会导致主库忙于 fork 子进程生成 RDB 文件，进行数据全量同步。
fork 这个操作会阻塞主线程处理正常请求，从而导致主库响应应用程序的请求速度变慢。此外，传输 RDB 文件也会占用主库的网络带宽，同样会给主库的资源使用带来压力。

主 - 从 - 从 模式将主库生成 RDB 和传输 RDB 的压力，以级联的方式分散到从库上。

### 增量复制

当主从库完成了全量复制，它们之间就会一直维护一个网络连接，主库会通过这个连接将后续陆续收到的命令操作再同步给从库，这个过程也称为基于长连接的命令传播，使用长连接的目的就是避免频繁建立连接导致的开销。

在命令传播阶段，除了发送写命令，主从节点还维持着心跳机制：PING 和 REPLCONF ACK。

断开重连增量复制的实现奥秘就是 repl_backlog_buffer 缓冲区，不管在什么时候 master 都会将写指令操作记录在 repl_backlog_buffer 中，
因为内存有限，repl_backlog_buffer 是一个定长的环形数组，如果数组内容满了，就会从头开始覆盖前面的内容。

master 使用 master_repl_offset 记录自己写到的位置偏移量，slave 则使用 slave_repl_offset 记录已经读取到的偏移量。
master 收到写操作，偏移量则会增加。从库持续执行同步的写指令后，在 repl_backlog_buffer 的已复制的偏移量 slave_repl_offset 也在不断增加。

正常情况下，这两个偏移量基本相等。在网络断连阶段，主库可能会收到新的写操作命令，所以 master_repl_offset 会大于 slave_repl_offset。

当主从断开重连后，slave 会先发送 psync 命令给 master，同时将自己的 runID，slave_repl_offset 发送给 master。
master 只需要把 master_repl_offset 与 slave_repl_offset 之间的命令同步给从库即可。

replication buffer 和 repl_backlog

replication buffer 对应于每个 slave，通过 config set client-output-buffer-limit slave 设置。
repl_backlog_buffer 是一个环形缓冲区，整个 master 进程中只会存在一个，所有的 slave 公用。repl_backlog 的大小通过 repl-backlog-size 参数设置，默认大小是 1M，其大小可以根据每秒产生的命令、（master 执行 rdb bgsave）+（master 发送 rdb 到 slave）+（slave load rdb 文件）时间之和来估算积压缓冲区的大小，repl-backlog-size 值不小于这两者的乘积。
总的来说，replication buffer 是主从库在进行全量复制时，主库上用于和从库连接的客户端的 buffer，而 repl_backlog_buffer 是为了支持从库增量复制，主库上用于持续保存写操作的一块专用 buffer。

repl_backlog_buffer 是一块专用 buffer，在 Redis 服务器启动后，开始一直接收写操作命令，这是所有从库共享的。主库和从库会各自记录自己的复制进度，所以，不同的从库在进行恢复时，会把自己的复制进度（slave_repl_offset）发给主库，主库就可以和它独立同步。
### master

#### masterTryPartialResynchronization

此函数从主实例的角度处理 PSYNC 命令，接收部分重新同步请求。

成功时返回 C_OK，否则返回 C_ERR，我们将进行通常的全量重新同步。

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

时钟定期检查副本链接健康情况。

此函数计算 `lag <= min-slaves-max-lag` 的从实例数量。
如果该选项启用，当没有足够多的具有指定延迟（或更少）的连接从实例时，服务器将阻止写入。
```c
void refreshGoodSlavesCount(void) {
    listIter li;
    listNode *ln;
    int good = 0;

    if (!server.repl_min_slaves_to_write ||
        !server.repl_min_slaves_max_lag) return;

    listRewind(server.slaves,&li);
    while((ln = listNext(&li))) {
        client *slave = ln->value;
        time_t lag = server.unixtime - slave->repl_ack_time;

        if (slave->replstate == SLAVE_STATE_ONLINE &&
            lag <= server.repl_min_slaves_max_lag) good++;
    }
    server.repl_good_slaves_count = good;
}

```

超出配置范围，master 禁止写命令。

```c
int processCommand(client *c) {
    ...
    /* Don't accept write commands if there are not enough good slaves and
    * user configured the min-slaves-to-write option. */
    if (server.masterhost == NULL &&
        server.repl_min_slaves_to_write &&
        server.repl_min_slaves_max_lag &&
        c->cmd->flags & CMD_WRITE &&
        server.repl_good_slaves_count < server.repl_min_slaves_to_write)
    {
        flagTransaction(c);
        addReply(c, shared.noreplicaserr);
        return C_OK;
    }
    ...
}
```

### slave

如果我们要重新连接，尝试与主实例进行部分重新同步。
如果没有缓存的主实例结构，至少尝试发出"PSYNC ? -1"命令，以便使用 PSYNC 命令触发全量重新同步，从而获取主实例 replid 和全局复制偏移量。

此函数设计为由 syncWithMaster() 调用，因此有以下假设：

1. 我们传递一个已连接的套接字 "fd"。
2. 此函数不会关闭文件描述符 "fd"。
   然而，在部分重新同步成功的情况下，该函数将重用 'fd' 作为 server.master 客户端结构的文件描述符。

该函数分为两部分：如果 read_reply 为 0，该函数将 PSYNC 命令写入套接字，然后需要再次调用该函数，read_reply 设置为 1，以读取命令的回复。
这对于支持非阻塞操作很有用，这样我们写入、返回到事件循环，然后在有数据时读取。

当 read_reply 为 0 时，如果发生写入错误，函数返回 PSYNC_WRITE_ERR，或者返回 PSYNC_WAIT_REPLY 表示我们需要再次调用 read_reply 设置为 1。
然而，即使 read_reply 设置为 1，该函数也可能再次返回 PSYNC_WAIT_REPLY，表示没有足够的数据可供读取以完成其工作。
在这种情况下，我们应该重新进入事件循环并等待。

函数返回：

- PSYNC_CONTINUE：如果 PSYNC 命令成功，我们可以继续。
- PSYNC_FULLRESYNC：如果支持 PSYNC 但需要全量重新同步。在这种情况下，主实例 replid 和全局复制偏移量会被保存。
- PSYNC_NOT_SUPPORTED：如果服务器根本不理解 PSYNC，调用者应回退到 SYNC。
- PSYNC_WRITE_ERROR：写入命令到套接字时发生错误。
- PSYNC_WAIT_REPLY：再次调用该函数，read_reply 设置为 1。
- PSYNC_TRY_LATER：主实例当前处于临时错误状态。

值得注意的副作用：

1. 作为函数调用的副作用，该函数会从 "fd" 移除可读事件处理程序，除非返回值是 PSYNC_WAIT_REPLY。
2. server.master_initial_offset 根据主实例回复设置为正确的值。这将用于填充 'server.master' 结构复制偏移量。

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

将写入命令传播到从实例，并同时填充复制积压。
如果实例是主实例，则使用此函数：我们使用客户端收到的命令来创建复制流。
如果实例是从实例且附有子从实例，则使用 replicationFeedSlavesFromMasterStream()。

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

如果没有从实例，也没有需要填充的积压缓冲区，我们可以立即返回。

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

### startBgsaveForReplication

从服务刚启动或因网络原因，与主服务长时间断开，重连后发现主从数据已经严重不匹配了，主服务需要将内存数据保存成 rdb 二进制压缩文件，传送给这些重新链接的服务。

```c
int startBgsaveForReplication(int mincapa, int req) {
    int retval;
    int socket_target = 0;
    listIter li;
    listNode *ln;

    /* We use a socket target if slave can handle the EOF marker and we're configured to do diskless syncs.
     * Note that in case we're creating a "filtered" RDB (functions-only, for example) we also force socket replication
     * to avoid overwriting the snapshot RDB file with filtered data. */
    socket_target = (server.repl_diskless_sync || req & SLAVE_REQ_RDB_MASK) && (mincapa & SLAVE_CAPA_EOF);
    /* `SYNC` should have failed with error if we don't support socket and require a filter, assert this here */
    serverAssert(socket_target || !(req & SLAVE_REQ_RDB_MASK));

    serverLog(LL_NOTICE,"Starting BGSAVE for SYNC with target: %s",
        socket_target ? "replicas sockets" : "disk");

    rdbSaveInfo rsi, *rsiptr;
    rsiptr = rdbPopulateSaveInfo(&rsi);
    /* Only do rdbSave* when rsiptr is not NULL,
     * otherwise slave will miss repl-stream-db. */
    if (rsiptr) {
        if (socket_target)
            retval = rdbSaveToSlavesSockets(req,rsiptr);
        else {
            /* Keep the page cache since it'll get used soon */
            retval = rdbSaveBackground(req, server.rdb_filename, rsiptr, RDBFLAGS_REPLICATION | RDBFLAGS_KEEP_CACHE);
        }
    } else {
        serverLog(LL_WARNING,"BGSAVE for replication: replication information not available, can't generate the RDB file right now. Try later.");
        retval = C_ERR;
    }

    /* If we succeeded to start a BGSAVE with disk target, let's remember
     * this fact, so that we can later delete the file if needed. Note
     * that we don't set the flag to 1 if the feature is disabled, otherwise
     * it would never be cleared: the file is not deleted. This way if
     * the user enables it later with CONFIG SET, we are fine. */
    if (retval == C_OK && !socket_target && server.rdb_del_sync_files)
        RDBGeneratedByReplication = 1;

    /* If we failed to BGSAVE, remove the slaves waiting for a full
     * resynchronization from the list of slaves, inform them with
     * an error about what happened, close the connection ASAP. */
    if (retval == C_ERR) {
        serverLog(LL_WARNING,"BGSAVE for replication failed");
        listRewind(server.slaves,&li);
        while((ln = listNext(&li))) {
            client *slave = ln->value;

            if (slave->replstate == SLAVE_STATE_WAIT_BGSAVE_START) {
                slave->replstate = REPL_STATE_NONE;
                slave->flags &= ~CLIENT_SLAVE;
                listDelNode(server.slaves,ln);
                addReplyError(slave,
                    "BGSAVE failed, replication can't continue");
                slave->flags |= CLIENT_CLOSE_AFTER_REPLY;
            }
        }
        return retval;
    }

    /* If the target is socket, rdbSaveToSlavesSockets() already setup
     * the slaves for a full resync. Otherwise for disk target do it now.*/
    if (!socket_target) {
        listRewind(server.slaves,&li);
        while((ln = listNext(&li))) {
            client *slave = ln->value;

            if (slave->replstate == SLAVE_STATE_WAIT_BGSAVE_START) {
                /* Check slave has the exact requirements */
                if (slave->slave_req != req)
                    continue;
                replicationSetupSlaveForFullResync(slave, getPsyncInitialOffset());
            }
        }
    }

    return retval;
}

```

## Memory

默认情况下，从实例会忽略 `maxmemory`（除非在故障转移后或被手动提升为主实例）。
这意味着键的淘汰将由主实例处理，在主端淘汰键时向从实例发送 DEL 命令。

此行为确保主从实例保持一致，这通常是期望的。
然而，如果从实例是可写的，或者你希望从实例有不同的内存设置，并且你确定对从实例执行的所有写入都是幂等的，那么你可以更改此默认值（但请确保你了解自己在做什么）。

请注意，由于从实例默认不淘汰，它最终可能使用比 `maxmemory` 设置更多的内存（因为某些缓冲区在从实例上可能更大，或者数据结构有时可能占用更多内存等）。
请确保监控你的从实例，确保它们有足够的内存，在主实例达到配置的 `maxmemory` 设置之前永远不会遇到真正的内存不足情况。

要更改此行为，你可以允许从实例不忽略 `maxmemory`。要使用的配置指令是：

```
replica-ignore-maxmemory no
```

## Summary

全量复制虽然耗时，但是对于从库来说，如果是第一次同步，全量复制是无法避免的，
所以，一个 Redis 实例的数据库不要太大，一个实例大小在几 GB 级别比较合适，这样可以减少 RDB 文件生成、传输和重新加载的开销。
另外，为了避免多个从库同时和主库进行全量复制，给主库过大的同步压力，我们也可以采用"主 - 从 - 从"这一级联模式，来缓解主库的压力。

两个典型的坑。

- 主从数据不一致。Redis 采用的是异步复制，所以无法实现强一致性保证（主从数据时时刻刻保持一致），数据不一致是难以避免的。我给你提供了应对方法：保证良好网络环境，以及使用程序监控从库复制进度，一旦从库复制进度超过阈值，不让客户端连接从库。
- 对于读到过期数据，这是可以提前规避的，一个方法是，使用 Redis 3.2 及以上版本；另外，你也可以使用 EXPIREAT/PEXPIREAT 命令设置过期时间，避免从库上的数据过期时间滞后。
  不过，这里有个地方需要注意下，因为 EXPIREAT/PEXPIREAT 设置的是时间点，所以，主从节点上的时钟要保持一致，具体的做法是，让主从节点和相同的 NTP 服务器（时间服务器）进行时钟同步。

> Redis 中的 slave-serve-stale-data 配置项设置了从库能否处理数据读写命令，你可以把它设置为 no。这样一来，从库只能服务 INFO、SLAVEOF 命令，这就可以避免在从库中读到不一致的数据了。

把 min-slaves-to-write 和 min-slaves-max-lag 这两个配置项搭配起来使用，分别给它们设置一定的阈值，假设为 N 和 T。
这两个配置项组合后的要求是，主库连接的从库中至少有 N 个从库，和主库进行数据复制时的 ACK 消息延迟不能超过 T 秒，否则，主库就不会再接收客户端的请求了。

## Tuning

线上 Redis 使用，不管是最初的 sync 机制，还是后来的 psync 和 psync2，主从复制都会受限于复制积压缓冲。如果 slave 断开复制连接的时间较长，或者 master 某段时间写入量过大，而 slave 的复制延迟较大，slave 的复制偏移量落在 master 的复制积压缓冲之外，则会导致全量复制。
于是，微博整合 Redis 的 rdb 和 aof 策略，构建了完全增量复制方案。
在完全增量方案中，aof 文件不再只有一个，而是按后缀 id 进行递增，如 aof.00001、aof.00002，当 aof 文件超过阀值，则创建下一个 id 加 1 的文件，从而滚动存储最新的写指令。
在 bgsave 构建 rdb 时，rdb 文件除了记录当前的内存数据快照，还会记录 rdb 构建时间，对应 aof 文件的 id 及位置。这样 rdb 文件和其记录 aof 文件位置之后的写指令，就构成一份完整的最新数据记录。
主从复制时，master 通过独立的复制线程向 slave 同步数据。每个 slave 会创建一个复制线程。第一次复制是全量复制，之后的复制，不管 slave 断开复制连接有多久，只要 aof 文件没有被删除，都是增量复制。
第一次全量复制时，复制线程首先将 rdb 发给 slave，然后再将 rdb 记录的 aof 文件位置之后的所有数据，也发送给 slave，即可完成。整个过程不用重新构建 rdb。
后续同步时，slave 首先传递之前复制的 aof 文件的 id 及位置。master 的复制线程根据这个信息，读取对应 aof 文件位置之后的所有内容，发送给 slave，即可完成数据同步。
由于整个复制过程，master 在独立复制线程中进行，所以复制过程不影响用户的正常请求。为了减轻 master 的复制压力，全增量复制方案仍然支持 slave 嵌套，即可以在 slave 后继续挂载多个 slave，从而把复制压力分散到多个不同的 Redis 实例。

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md?id=persistence)

## References

1. [Redis Replication](https://redis.io/topics/replication#partial-resynchronizations-after-restarts-and-failovers)
2. [Top Redis Headaches for Devops – Replication Timeouts](https://redis.io/blog/top-redis-headaches-for-devops-replication-timeouts/)
