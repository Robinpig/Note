## Introduction

本页记录基于 ZooKeeper 原始 API 实现的**分布式协调配方（Recipes）**：屏障、队列、锁、两阶段提交、选主。配方基于 znode 的三大原语组合而成：**顺序节点（SEQUENCE）** 提供全局有序、**临时节点（EPHEMERAL）** 绑定会话存活、**一次性 watch** 提供变更通知。

> [!IMPORTANT]
> 生产环境**不要手写这些配方**——直接使用 [Curator](/docs/CS/Framework/ZooKeeper/Curator.md) 的 `InterProcessMutex` / `InterProcessQueue` / `LeaderSelector` 等经过验证的实现。本页用于理解原理与面试/排障，Curator 是生产首选。

### 页内导航

| 配方 | 实现要点 |
| :--- | :--- |
| **[Barriers](#barriers)** | 屏障节点存在即"阻塞"；`exists`+watch 循环等待节点消失（双屏障同步计算起止） |
| **[Queues](#queues)** | `queue-` 前缀 + SEQUENCE\|EPHEMERAL；取最小序号消费（优先级队列加 `YY` 优先级前缀） |
| **[Locks](#locks)** | 临时顺序节点排序取最小者持锁；watch 前驱避免惊群，无轮询无超时 |
| **[Two-phased Commit](#two-phased-commit)** | 协调者建事务节点，各站点写 commit/abort 投票；改进：O(n) 消息复杂度 + 临时节点探测故障 |
| **[Leader Election](#leader-election)** | `n_` + SEQUENCE\|EPHEMERAL；序号最小者当选，watch 前驱接棒 |

> [!NOTE]
> 所有配方的共同陷阱：一旦涉及 watch，**通知可能丢失**（一次性语义，见 [Watches](/docs/CS/Framework/ZooKeeper/Watches.md)）。锁与队列的正确性依赖"watch 前驱 + 重新读取子节点"组合，而非"恰好一次的事件"。Kleppmann 指出一次性 watch 正是分布式锁的脆弱点之一。

### Barriers

Barriers are implemented in ZooKeeper by designating a barrier node. The barrier is in place if the barrier node exists. Here's the pseudo code:

1. Client calls the ZooKeeper API's **exists()** function on the barrier node, with *watch* set to true.
2. If **exists()** returns false, the barrier is gone and the client proceeds
3. Else, if **exists()** returns true, the clients wait for a watch event from ZooKeeper for the barrier node.
4. When the watch event is triggered, the client reissues the **exists( )** call, again waiting until the barrier node is removed.

#### Double Barriers

Double barriers enable clients to synchronize the beginning and the end of a computation.
When enough processes have joined the barrier, processes start their computation and leave the barrier once they have finished.

### Queues

To implement a distributed queue in ZooKeeper, first designate a znode to hold the queue, the queue node.
The distributed clients put something into the queue by calling create() with a pathname ending in "queue-", with the *sequence* and *ephemeral* flags in the create() call set to true.
Because the *sequence* flag is set, the new pathname will have the form  *path-to-queue-node* /queue-X, where X is a monotonic increasing number.
A client that wants to be removed from the queue calls ZooKeeper's **getChildren( )** function, with *watch* set to true on the queue node, and begins processing nodes with the lowest number.
The client does not need to issue another **getChildren( )** until it exhausts the list obtained from the first **getChildren( )** call.
If there are no children in the queue node, the reader waits for a watch notification to check the queue again.

#### Priority Queues

To implement a priority queue, you need only make two simple changes to the generic queue recipe.

- First, to add to a queue, the pathname ends with "queue-YY" where YY is the priority of the element with lower numbers representing higher priority (just like UNIX).
- Second, when removing from the queue, a client uses an up-to-date children list meaning that the client will invalidate previously obtained children lists if a watch notification triggers for the queue node.

### Locks

Fully distributed locks that are globally synchronous, meaning at any snapshot in time no two clients think they hold the same lock.
These can be implemented using ZooKeeper. As with priority queues, first define a lock node.

Here are a few things to notice:

- The removal of a node will only cause one client to wake up since each node is watched by exactly one client. In this way, you avoid the *herd effect*.
- There is no polling or timeouts.
- Because of the way you implement locking, it is easy to see the amount of lock contention, break locks, debug locking problems, etc.

```java
public interface LockListener {
    void lockAcquired();

    void lockReleased();
}
```

Attempts to acquire the exclusive write lock returning whether or not it was acquired. Note that the exclusive lock may be acquired some time later after this method has been invoked due to the current lock owner going away.

```
public class WriteLock extends ProtocolSupport {
    public synchronized boolean lock() throws KeeperException, InterruptedException {
        if (isClosed()) {
            return false;
        }
        ensurePathExists(dir);

        return (Boolean) retryOperation(zop);
    }
}
```

the command that is run and retried for actually obtaining the lock.

delay =

```
attemptCount * 0.5s
```

```
RETRY_COUNT = 10
```

```
 @SuppressFBWarnings(
            value = "NP_NULL_PARAM_DEREF_NONVIRTUAL",
            justification = "findPrefixInChildren will assign a value to this.id")
        public boolean execute() throws KeeperException, InterruptedException {
            do {
                if (id == null) {
                    long sessionId = zookeeper.getSessionId();
                    String prefix = "x-" + sessionId + "-";
                    // lets try look up the current ID if we failed
                    // in the middle of creating the znode
                    findPrefixInChildren(prefix, zookeeper, dir);
                    idName = new ZNodeName(id);
                }
                List<String> names = zookeeper.getChildren(dir, false);
                if (names.isEmpty()) {
                    LOG.warn("No children in: {} when we've just created one! Lets recreate it...", dir);
                    // lets force the recreation of the id
                    id = null;
                } else {
                    // lets sort them explicitly (though they do seem to come back in order ususally :)
                    SortedSet<ZNodeName> sortedNames = new TreeSet<>();
                    for (String name : names) {
                        sortedNames.add(new ZNodeName(dir + "/" + name));
                    }
                    ownerId = sortedNames.first().getName();
                    SortedSet<ZNodeName> lessThanMe = sortedNames.headSet(idName);
                    if (!lessThanMe.isEmpty()) {
                        ZNodeName lastChildName = lessThanMe.last();
                        lastChildId = lastChildName.getName();
                        LOG.debug("Watching less than me node: {}", lastChildId);
                        Stat stat = zookeeper.exists(lastChildId, new LockWatcher());
                        if (stat != null) {
                            return Boolean.FALSE;
                        } else {
                            LOG.warn("Could not find the stats for less than me: {}", lastChildName.getName());
                        }
                    } else {
                        if (isOwner()) {
                            LockListener lockListener = getLockListener();
                            if (lockListener != null) {
                                lockListener.lockAcquired();
                            }
                            return Boolean.TRUE;
                        }
                    }
                }
            }
            while (id == null);
            return Boolean.FALSE;
        }
```

### Two-phased Commit

A two-phase commit protocol is an algorithm that lets all clients in a distributed system agree either to commit a transaction or abort.

In ZooKeeper, you can implement a two-phased commit by having a coordinator create a transaction node, say "/app/Tx", and one child node per participating site, say "/app/Tx/s_i".
When coordinator creates the child node, it leaves the content undefined. Once each site involved in the transaction receives the transaction from the coordinator, the site reads each child node and sets a watch.
Each site then processes the query and votes "commit" or "abort" by writing to its respective node.
Once the write completes, the other sites are notified, and as soon as all sites have all votes, they can decide either "abort" or "commit". Note that a node can decide "abort" earlier if some site votes for "abort".

An interesting aspect of this implementation is that the only role of the coordinator is to decide upon the group of sites, to create the ZooKeeper nodes, and to propagate the transaction to the corresponding sites.
In fact, even propagating the transaction can be done through ZooKeeper by writing it in the transaction node.

There are two important drawbacks of the approach described above. One is the message complexity, which is O(n²). The second is the impossibility of detecting failures of sites through ephemeral nodes.
To detect the failure of a site using ephemeral nodes, it is necessary that the site create the node.

To solve the first problem, you can have only the coordinator notified of changes to the transaction nodes, and then notify the sites once coordinator reaches a decision.
Note that this approach is scalable, but it's is slower too, as it requires all communication to go through the coordinator.

To address the second problem, you can have the coordinator propagate the transaction to the sites, and have each site creating its own ephemeral node.

### Leader Election

A simple way of doing leader election with ZooKeeper is to use the *SEQUENCE|EPHEMERAL* flags when creating znodes that represent "proposals" of clients.
The idea is to have a znode, say "/election", such that each znode creates a child znode "/election/n_" with both flags SEQUENCE|EPHEMERAL.
With the sequence flag, ZooKeeper automatically appends a sequence number that is greater that any one previously appended to a child of "/election".
The process that created the znode with the smallest appended sequence number is the leader.

To avoid the herd effect, it is sufficient to watch for the next znode down on the sequence of znodes.
If a client receives a notification that the znode it is watching is gone, then it becomes the new leader in the case that there is no smaller znode.
Note that this avoids the herd effect by not having all clients watching the same znode.

Once configured, invoking start() will cause the client to connect to ZooKeeper and create a leader offer.

```java
 public synchronized void start() {
        state = State.START;
        dispatchEvent(EventType.START);

        LOG.info("Starting leader election support");

        if (zooKeeper == null) {
            throw new IllegalStateException(
                "No instance of zookeeper provided. Hint: use setZooKeeper()");
        }

        if (hostName == null) {
            throw new IllegalStateException(
                "No hostname provided. Hint: use setHostName()");
        }

        try {
            makeOffer();
            determineElectionStatus();
        } catch (KeeperException | InterruptedException e) {
            becomeFailed(e);
        }
    }
```

```java
private void makeOffer() throws KeeperException, InterruptedException {
        state = State.OFFER;
        dispatchEvent(EventType.OFFER_START);

        LeaderOffer newLeaderOffer = new LeaderOffer();
        byte[] hostnameBytes;
        synchronized (this) {
            newLeaderOffer.setHostName(hostName);
            hostnameBytes = hostName.getBytes();
            newLeaderOffer.setNodePath(zooKeeper.create(rootNodeName + "/" + "n_",
                                                        hostnameBytes, ZooDefs.Ids.OPEN_ACL_UNSAFE,
                                                        CreateMode.EPHEMERAL_SEQUENTIAL));
            leaderOffer = newLeaderOffer;
        }
        LOG.debug("Created leader offer {}", leaderOffer);

        dispatchEvent(EventType.OFFER_COMPLETE);
    }
```

```java
    private void determineElectionStatus() throws KeeperException, InterruptedException {

        state = State.DETERMINE;
        dispatchEvent(EventType.DETERMINE_START);

        LeaderOffer currentLeaderOffer = getLeaderOffer();

        String[] components = currentLeaderOffer.getNodePath().split("/");

        currentLeaderOffer.setId(Integer.valueOf(components[components.length - 1].substring("n_".length())));

        List<LeaderOffer> leaderOffers = toLeaderOffers(zooKeeper.getChildren(rootNodeName, false));

        /*
         * For each leader offer, find out where we fit in. If we're first, we
         * become the leader. If we're not elected the leader, attempt to stat the
         * offer just less than us. If they exist, watch for their failure, but if
         * they don't, become the leader.
         */
        for (int i = 0; i < leaderOffers.size(); i++) {
            LeaderOffer leaderOffer = leaderOffers.get(i);

            if (leaderOffer.getId().equals(currentLeaderOffer.getId())) {
                LOG.debug("There are {} leader offers. I am {} in line.", leaderOffers.size(), i);

                dispatchEvent(EventType.DETERMINE_COMPLETE);

                if (i == 0) {
                    becomeLeader();
                } else {
                    becomeReady(leaderOffers.get(i - 1));
                }

                /* Once we've figured out where we are, we're done. */
                break;
            }
        }
    }
```

## Links

- [Curator（生产级配方实现，生产首选）](/docs/CS/Framework/ZooKeeper/Curator.md)
- [ZooKeeper（概念枢纽）](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Watches（一次性语义与丢失窗口）](/docs/CS/Framework/ZooKeeper/Watches.md)
- [Session（临时节点与会话绑定）](/docs/CS/Framework/ZooKeeper/Session.md)
- [Leader Flapping 排查（troubleshooting）](/docs/CS/Framework/ZooKeeper/troubleshooting.md)
- [start（zxid 溢出触发选主）](/docs/CS/Framework/ZooKeeper/start.md)
- [How to do distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)

## References

1. [ZooKeeper Recipes](https://zookeeper.apache.org/doc/current/recipes.html)
2. [ZooKeeper Programmer's Guide](https://zookeeper.apache.org/doc/current/zookeeperProgrammers.html)
3. [How to do distributed locking (Kleppmann)](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)
4. [Distributed Locks are Dead; Long Live Distributed Locks!](https://hazelcast.com/blog/long-live-distributed-locks/)
