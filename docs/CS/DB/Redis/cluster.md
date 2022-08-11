## Introduction


Redis Cluster 16384 slots for master

max 1000

## gossip 
Initially we don't know our "name", but we'll find it once we connect to the first node, using the getsockname() function. Then we'll use this address for all the next messages.


```c
typedef struct {
    char nodename[CLUSTER_NAMELEN];
    uint32_t ping_sent;
    uint32_t pong_received;
    char ip[NET_IP_STR_LEN];  /* IP address last time it was seen */
    uint16_t port;              /* base port last time it was seen */
    uint16_t cport;             /* cluster port last time it was seen */
    uint16_t flags;             /* node->flags copy */
    uint16_t pport;             /* plaintext-port, when base port is TLS */
    uint16_t notused1;
} clusterMsgDataGossip;
```

Cluster node timeout is the amount of milliseconds a node must be unreachable for it to be considered in failure state. Most other internal time limits are a multiple of the node timeout.

```
cluster-node-timeout 15000
```

gossip 协议包含多种消息，包含 `ping` , `pong` , `meet` , `fail` 等等。

- meet：某个节点发送 meet 给新加入的节点，让新节点加入集群中，然后新节点就会开始与其它节点进行通信。

```bash
Redis-trib.rb add-nodeCopy to clipboardErrorCopied
```

其实内部就是发送了一个 gossip meet 消息给新加入的节点，通知那个节点去加入我们的集群。

- ping：每个节点都会频繁给其它节点发送 ping，其中包含自己的状态还有自己维护的集群元数据，互相通过 ping 交换元数据。
- pong：返回 ping 和 meeet，包含自己的状态和其它信息，也用于信息广播和更新。
- fail：某个节点判断另一个节点 fail 之后，就发送 fail 给其它节点，通知其它节点说，某个节点宕机啦。


#### [ping 消息深入](https://doocs.github.io/advanced-java/#/./docs/high-concurrency/redis-cluster?id=ping-消息深入)

ping 时要携带一些元数据，如果很频繁，可能会加重网络负担。

每个节点每秒会执行 10 次 ping，每次会选择 5 个最久没有通信的其它节点。当然如果发现某个节点通信延时达到了 `cluster_node_timeout / 2` ，那么立即发送 ping，避免数据交换延时过长，落后的时间太长了。比如说，两个节点之间都 10 分钟没有交换数据了，那么整个集群处于严重的元数据不一致的情况，就会有问题。所以 `cluster_node_timeout` 可以调节，如果调得比较大，那么会降低 ping 的频率。

每次 ping，会带上自己节点的信息，还有就是带上 1/10 其它节点的信息，发送出去，进行交换。至少包含 `3` 个其它节点的信息，最多包含 `总节点数减 2` 个其它节点的信息。

### [Redis cluster 的高可用与主备切换原理](https://doocs.github.io/advanced-java/#/./docs/high-concurrency/redis-cluster?id=redis-cluster-的高可用与主备切换原理)

Redis cluster 的高可用的原理，几乎跟哨兵是类似的。

#### [判断节点宕机](https://doocs.github.io/advanced-java/#/./docs/high-concurrency/redis-cluster?id=判断节点宕机)

如果一个节点认为另外一个节点宕机，那么就是 `pfail` ，**主观宕机**。如果多个节点都认为另外一个节点宕机了，那么就是 `fail` ，**客观宕机**，跟哨兵的原理几乎一样，sdown，odown。

在 `cluster-node-timeout` 内，某个节点一直没有返回 `pong` ，那么就被认为 `pfail` 。

如果一个节点认为某个节点 `pfail` 了，那么会在 `gossip ping` 消息中， `ping` 给其他节点，如果**超过半数**的节点都认为 `pfail` 了，那么就会变成 `fail` 。

#### [从节点过滤](https://doocs.github.io/advanced-java/#/./docs/high-concurrency/redis-cluster?id=从节点过滤)

对宕机的 master node，从其所有的 slave node 中，选择一个切换成 master node。

检查每个 slave node 与 master node 断开连接的时间，如果超过了 `cluster-node-timeout * cluster-slave-validity-factor` ，那么就**没有资格**切换成 `master` 。

#### [从节点选举](https://doocs.github.io/advanced-java/#/./docs/high-concurrency/redis-cluster?id=从节点选举)

每个从节点，都根据自己对 master 复制数据的 offset，来设置一个选举时间，offset 越大（复制数据越多）的从节点，选举时间越靠前，优先进行选举。

所有的 master node 开始 slave 选举投票，给要进行选举的 slave 进行投票，如果大部分 master node `（N/2 + 1）` 都投票给了某个从节点，那么选举通过，那个从节点可以切换成 master。

从节点执行主备切换，从节点切换为主节点。

#### [与哨兵比较](https://doocs.github.io/advanced-java/#/./docs/high-concurrency/redis-cluster?id=与哨兵比较)

整个流程跟哨兵相比，非常类似，所以说，Redis cluster 功能强大，直接集成了 replication 和 sentinel 的功能。





## master

#### clusterSetMaster

```c
void clusterSetMaster(clusterNode *n) {
    serverAssert(n != myself);
    serverAssert(myself->numslots == 0);

    if (nodeIsMaster(myself)) {
        myself->flags &= ~(CLUSTER_NODE_MASTER|CLUSTER_NODE_MIGRATE_TO);
        myself->flags |= CLUSTER_NODE_SLAVE;
        clusterCloseAllSlots();
    } else {
        if (myself->slaveof)
            clusterNodeRemoveSlave(myself->slaveof,myself);
    }
    myself->slaveof = n;
    clusterNodeAddSlave(n,myself);
    replicationSetMaster(n->ip, n->port);
    resetManualFailover();
}
```

一个集群由多个Redis节点组成，不同的节点通过`CLUSTER MEET`命令进行连接：

```
CLUSTER MEET <ip> <port>
```

收到命令的节点会与命令中指定的目标节点进行握手，握手成功后目标节点会加入到集群中,看个例子,图片来自于[Redis的设计与实现](http://redisbook.com/preview/cluster/node.html)：

[![image](https://camo.githubusercontent.com/6f1f8a2c673312dfd220f6d6ce8beff342100188dcfb1698fc58d70d0aa99332/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353436353539376631383f773d34353826683d32323226663d706e6726733d3231333936)](https://camo.githubusercontent.com/6f1f8a2c673312dfd220f6d6ce8beff342100188dcfb1698fc58d70d0aa99332/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353436353539376631383f773d34353826683d32323226663d706e6726733d3231333936)

[![image](https://camo.githubusercontent.com/75ef437b642023cad9a3e5c8a521cda995b8a20c0d17603b3dd514d9b92e9af2/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353364353862303365653f773d35353226683d33373126663d706e6726733d3332333134)](https://camo.githubusercontent.com/75ef437b642023cad9a3e5c8a521cda995b8a20c0d17603b3dd514d9b92e9af2/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353364353862303365653f773d35353226683d33373126663d706e6726733d3332333134)

[![image](https://camo.githubusercontent.com/1a90fa4bea67a133ec7b659a3a3c14b0263335ba7b02d895a02bda396144f48f/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353464653737303761383f773d36363426683d33363526663d706e6726733d3330343532)](https://camo.githubusercontent.com/1a90fa4bea67a133ec7b659a3a3c14b0263335ba7b02d895a02bda396144f48f/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353464653737303761383f773d36363426683d33363526663d706e6726733d3330343532)

[![image](https://camo.githubusercontent.com/bfade42bd8225e2e32dbd4b8d0ff2cf574f1824669f91ef02aba90a23a803794/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353366306233333133363f773d35383926683d33363526663d706e6726733d3334313337)](https://camo.githubusercontent.com/bfade42bd8225e2e32dbd4b8d0ff2cf574f1824669f91ef02aba90a23a803794/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353366306233333133363f773d35383926683d33363526663d706e6726733d3334313337)

[![image](https://camo.githubusercontent.com/b70da7bbcf999309b775d806302e14fd987ab7dde2c9a1fd4f8d69e85127a7f1/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353364353562313235303f773d36323626683d33323126663d706e6726733d3238303939)](https://camo.githubusercontent.com/b70da7bbcf999309b775d806302e14fd987ab7dde2c9a1fd4f8d69e85127a7f1/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353364353562313235303f773d36323626683d33323126663d706e6726733d3238303939)

### 槽分配

一个集群的所有数据被分为16384个槽，可以通过`CLUSTER ADDSLOTS`命令将槽指派给对应的节点。当所有的槽都有节点负责时，集群处于上线状态，否则处于下线状态不对外提供服务。

clusterNode的位数组slots代表一个节点负责的槽信息。

```
struct clusterNode {


    unsigned char slots[16384/8]; /* slots handled by this node */

    int numslots;   /* Number of slots handled by this node */

    ...
}
```

看个例子，下图中1、3、5、8、9、10位的值为1，代表该节点负责槽1、3、5、8、9、10。

每个Redis Server上都有一个ClusterState的对象，代表了该Server所在集群的信息，其中字段slots记录了集群中所有节点负责的槽信息。

```
typedef struct clusterState {

    // 负责处理各个槽的节点
    // 例如 slots[i] = clusterNode_A 表示槽 i 由节点 A 处理
    // slots[i] = null 代表该槽目前没有节点负责
    clusterNode *slots[REDIS_CLUSTER_SLOTS];

}
```

### 槽重分配

可以通过redis-trib工具对槽重新分配，重分配的实现步骤如下：

1. 通知目标节点准备好接收槽
2. 通知源节点准备好发送槽
3. 向源节点发送命令：`CLUSTER GETKEYSINSLOT <slot> <count>`从源节点获取最多count个槽slot的key
4. 对于步骤3的每个key，都向源节点发送一个`MIGRATE <target_ip> <target_port> <key_name> 0 <timeout> `命令，将被选中的键原子的从源节点迁移至目标节点。
5. 重复步骤3、4。直到槽slot的所有键值对都被迁移到目标节点
6. 将槽slot指派给目标节点的信息发送到整个集群。

在槽重分配的过程中，槽中的一部分数据保存着源节点，另一部分保存在目标节点。这时如果要客户端向源节点发送一个命令，且相关数据在一个正在迁移槽中，源节点处理步骤如图:
[![image](https://camo.githubusercontent.com/49788d2516d676cd45ccfda4572d0497687baade043dfe8d0111ca03c0873266/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353365663764623564623f773d39393626683d34373426663d706e6726733d313838343836)](https://camo.githubusercontent.com/49788d2516d676cd45ccfda4572d0497687baade043dfe8d0111ca03c0873266/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353365663764623564623f773d39393626683d34373426663d706e6726733d313838343836)

当客户端收到一个ASK错误的时候，会根据返回的信息向目标节点重新发起一次请求。

ASK和MOVED的区别主要是ASK是一次性的，MOVED是永久性的，有点像Http协议中的301和302。

### 一次命令执行过程

我们来看cluster下一次命令的请求过程,假设执行命令 `get testKey`

1. cluster client在运行前需要配置若干个server节点的ip和port。我们称这些节点为种子节点。
2. cluster的客户端在执行命令时，会先通过计算得到key的槽信息，计算规则为：`getCRC16(key) & (16384 - 1)`，得到槽信息后，会从一个缓存map中获得槽对应的redis server信息，如果能获取到，则调到第4步
3. 向种子节点发送`slots`命令以获得整个集群的槽分布信息，然后跳转到第2步重试命令
4. 向负责该槽的server发起调用
   server处理如图：
   [![image](https://camo.githubusercontent.com/0c6fc867400481025448a59c20d4c7a74f16fb365aa978755569970c963c2236/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353465376538376535303f773d3131313626683d35323626663d706e6726733d323134323931)](https://camo.githubusercontent.com/0c6fc867400481025448a59c20d4c7a74f16fb365aa978755569970c963c2236/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353465376538376535303f773d3131313626683d35323626663d706e6726733d323134323931)
5. 客户端如果收到MOVED错误，则根据对应的地址跳转到第4步重新请求，
6. 客户段如果收到ASK错误，则根据对应的地址跳转到第4步重新请求，并在请求前带上ASKING标识。

以上步骤大致就是redis cluster下一次命令请求的过程，但忽略了一个细节，如果要查找的数据锁所在的槽正在重分配怎么办？

### Redis故障转移

#### 疑似下线与已下线

集群中每个Redis节点都会定期的向集群中的其他节点发送PING消息，如果目标节点没有在有效时间内回复PONG消息，则会被标记为疑似下线。同时将该信息发送给其他节点。当一个集群中有半数负责处理槽的主节点都将某个节点A标记为疑似下线后，那么A会被标记为已下线，将A标记为已下线的节点会将该信息发送给其他节点。

比如说有A,B,C,D,E 5个主节点。E有F、G两个从节点。
当E节点发生异常后，其他节点发送给A的PING消息将不能得到正常回复。当过了最大超时时间后，假设A,B先将E标记为疑似下线；之后C也会将E标记为疑似下线，这时C发现集群中由3个节点（A、B、C）都将E标记为疑似下线，超过集群复制槽的主节点个数的一半(>2.5)则会将E标记为已下线，并向集群广播E下线的消息。

#### 选取新的主节点

当F、G（E的从节点）收到E被标记已下线的消息后，会根据Raft算法选举出一个新的主节点，新的主节点会将E复制的所有槽指派给自己，然后向集群广播消息，通知其他节点新的主节点信息。

选举新的主节点算法与选举Sentinel头节点的[过程](http://www.farmerjohn.top/2018/08/20/redis-sentinel/#选举领头Sentinel)很像：

1. 集群的配置纪元是一个自增计数器，它的初始值为0.
2. 当集群里的某个节点开始一次故障转移操作时，集群配置纪元的值会被增一。
3. 对于每个配置纪元，集群里每个负责处理槽的主节点都有一次投票的机会，而第一个向主节点要求投票的从节点将获得主节点的投票。
4. 档从节点发现自己正在复制的主节点进入已下线状态时，从节点会想集群广播一条CLUSTER_TYPE_FAILOVER_AUTH_REQUEST消息，要求所有接收到这条消息、并且具有投票权的主节点向这个从节点投票。
5. 如果一个主节点具有投票权（它正在负责处理槽），并且这个主节点尚未投票给其他从节点，那么主节点将向要求投票的从节点返回一条CLUSTERMSG_TYPE_FAILOVER_AUTH_ACK消息，表示这个主节点支持从节点成为新的主节点。
6. 每个参与选举的从节点都会接收CLUSTERMSG_TYPE_FAILOVER_AUTH_ACK消息，并根据自己收到了多少条这种消息来同济自己获得了多少主节点的支持。
7. 如果集群里有N个具有投票权的主节点，那么当一个从节点收集到大于等于N/2+1张支持票时，这个从节点就会当选为新的主节点。
8. 因为在每一个配置纪元里面，每个具有投票权的主节点只能投一次票，所以如果有N个主节点进行投票，那么具有大于等于N/2+1张支持票的从节点只会有一个，这确保了新的主节点只会有一个。
9. 如果在一个配置纪元里面没有从节点能收集到足够多的支持票，那么集群进入一个新的配置纪元，并再次进行选举，知道选出新的主节点为止。

### Redis常用分布式实现方案

最后，聊聊redis集群的其他两种实现方案。

#### client做分片

客户端做路由，采用一致性hash算法，将key映射到对应的redis节点上。
其优点是实现简单，没有引用其他中间件。
缺点也很明显：是一种静态分片方案，扩容性差。

Jedis中的ShardedJedis是该方案的实现。

#### proxy做分片

该方案在client与redis之间引入一个代理层。client的所有操作都发送给代理层，由代理层实现路由转发给不同的redis服务器。

[![image](https://camo.githubusercontent.com/bfa899736c8ccd998701f289446603b0302d96386f98dc39a57bbb21c558da35/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353365663936643635663f773d3130303026683d38303826663d7765627026733d3331373638)](https://camo.githubusercontent.com/bfa899736c8ccd998701f289446603b0302d96386f98dc39a57bbb21c558da35/68747470733a2f2f757365722d676f6c642d63646e2e786974752e696f2f323031382f392f31302f313635633366353365663936643635663f773d3130303026683d38303826663d7765627026733d3331373638)

其优点是: 路由规则可自定义，扩容方便。
缺点是： 代理层有单点问题，多一层转发的网络开销

其开源实现有twitter的[twemproxy](https://github.com/twitter/twemproxy)
和豌豆荚的[codis](https://github.com/CodisLabs/codis)

### 结束

分布式redis深度历险系列到此为止了，之后一个系列会详细讲讲单机Redis的实现，包括Redis的底层数据结构、对内存占用的优化、基于事件的处理机制、持久化的实现等等偏底层的内容，敬请期待~

## Msg

```c
// cluster.h

/* Message types.
 *
 * Note that the PING, PONG and MEET messages are actually the same exact
 * kind of packet. PONG is the reply to ping, in the exact format as a PING,
 * while MEET is a special PING that forces the receiver to add the sender
 * as a node (if it is not already in the list). */
#define CLUSTERMSG_TYPE_PING 0          /* Ping */
#define CLUSTERMSG_TYPE_PONG 1          /* Pong (reply to Ping) */
#define CLUSTERMSG_TYPE_MEET 2          /* Meet "let's join" message */
#define CLUSTERMSG_TYPE_FAIL 3          /* Mark node xxx as failing */
#define CLUSTERMSG_TYPE_PUBLISH 4       /* Pub/Sub Publish propagation */
#define CLUSTERMSG_TYPE_FAILOVER_AUTH_REQUEST 5 /* May I failover? */
#define CLUSTERMSG_TYPE_FAILOVER_AUTH_ACK 6     /* Yes, you have my vote */
#define CLUSTERMSG_TYPE_UPDATE 7        /* Another node slots configuration */
#define CLUSTERMSG_TYPE_MFSTART 8       /* Pause clients for manual failover */
#define CLUSTERMSG_TYPE_MODULE 9        /* Module cluster API message. */
#define CLUSTERMSG_TYPE_COUNT 10        /* Total number of message types. */
```

## References
1. [Twemproxy, a Redis proxy from Twitter](http://antirez.com/news/44)