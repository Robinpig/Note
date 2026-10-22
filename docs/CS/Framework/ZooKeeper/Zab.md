## Introduction

Zab is very similar to [Paxos](/docs/CS/Distributed/Consensus/Paxos.md), with one crucial difference – the agreement is reached on full history prefixes rather than on individual operations.
This difference allows Zab to preserve primary order, which may be violated by Paxos.

> Given our use of the primary order property, we say that Zab is a `PO atomic broadcast` protocol.

Zab has three phases: discovery, synchronization, and broadcast. 
Each process executes one iteration of this protocol at a time, and at any time, a process may drop the current iteration and start a new one by proceeding to Phase 1.

ZooKeeper有Leader、Follower、Observer三种角色 其中Follower、Observer都是Learner 
Observer不负责选举投票 可以在不影响写性能的情况下提升集群的读性能


所有事务请求必须由一个全局唯一的服务器来协调处理，这样的服务器被称为leader服务器，而余下的其他服务器则成为follower服务器。
leader服务器负责将一个客户端事务请求转换成一个事务proposal，并将该proposal分发给集群中所有的follower服务器。
之后leader服务器需要等待所有follower服务器的反馈，一旦超过半数的follower服务器进行了正确的反馈后，那么leader就会自己先commit这个事务，并再次向所有的follower服务器分发commit消息，要求其将前一个proposal进行提交。

ZAB协议的消息广播过程使用原子广播协议，类似于一个二阶段提交过程，针对客户端的事务请求，Leader服务器会为其生成对应的事务Proposal，并将其发送给集群中其余所有的机器，然后再分别收集各自的选票，最后进行事务提交
此处ZAB的二阶段提交和一般的二阶段提交略有不同，ZAB移除了二阶段提交中的事务中断的逻辑，follower服务器要么正常反馈，要么抛弃leader。好处是我们不需要等待所有follower都反馈响应才能提交事务，坏处是集群无法处理leader崩溃而带来的数据不一致的问题。后者需要崩溃恢复模式来解决这个问题。
整个消息广播协议是基于具有FIFO特性的TCP协议来进行网络通信的，因此能够很容易保证消息广播过程中消息接受与发送的顺序性。
整个消息广播过程中，Leader服务器会为每个事务生成对应的Proposal来进行广播，并且在广播事务Proposal之前，Leader服务器会先为这个Proposal分配一个全局单调递增的唯一ID，称之为事务ID（ZXID），由于ZAB协议需要保证每个消息严格的因果关系，因此必须将每个事务Proposal按照其ZXID的先后顺序来进行排序和处理。
在广播过程中，leader会为每一个follower分配一个单独的队列，然后将需要广播的事务proposal依次放入，并且根据FIFO策略进行消息发送。每个follower接收到proposal之后，都会首先将其以事务日志的形式写入本地磁盘，写入成功后反馈leader一个ack响应。当leader收到超过半数的follower的ack响应之后，就会广播一个commit消息给所有follower以通知其进行事务提交，同时leader自身也完成事务的提交。每个follower在接收到commit之后，也会完成对事务的提交。
在广播过程中，如果follower接收到proposal之后记录事务日志失败，或者proposal丢失。紧接着不久后，它直接接到了这个proposal的commit，那么follower就会向leader发送请求重新申请这个任务，leader会再次发送proposal和commit

## 角色模型

ZooKeeper 有 Leader、Follower、Observer 三种角色，后两者都是 **Learner**。Observer 不参与选举投票，可在不影响写性能的前提下提升读性能（跨 DC 只读扩展见 [cluster](/docs/CS/Framework/ZooKeeper/cluster.md)）。

- **Leader**：唯一处理写请求的角色，将事务转成 proposal 广播，等过半 follower 的 ACK 后 commit 并下发 commit 消息。
- **Follower**：Learner，参与投票与提案复制，同步 Leader 的事务。
- **Observer**：Learner，**只同步不投票**，读请求本地处理，跨 DC 扩展读能力。

所有事务请求必须由一个全局唯一的服务器（Leader）协调：Leader 把客户端事务请求转成事务 proposal 分发给所有 follower，等过半 follower 正确反馈（写入本地事务日志并 ACK）后，Leader 先 commit 再广播 commit。ZAB 相比一般二阶段提交移除了"事务中断"逻辑——follower 要么正常反馈要么抛弃 Leader，因此不需等所有 follower 但也无法处理 Leader 崩溃导致的不一致（后者靠崩溃恢复/重新同步解决）。整个广播基于 TCP 的 FIFO 保证顺序，每个 proposal 先分配全局单调递增唯一 ID（zxid）并按 zxid 顺序处理。广播中若 follower 写事务日志失败或 proposal 丢失却先收到 commit，会向 Leader 重新申请该任务，Leader 重发 proposal+commit。

> [!IMPORTANT]
> **本页导航**：Zab 的选主（Leader Election）源码深潜已独立成页 **[Election](/docs/CS/Framework/ZooKeeper/Election.md)**（QuorumCnxManager / FastLeaderElection / QuorumPeer::run / 故障切换）；广播后的请求处理链见 [pipeline](/docs/CS/Framework/ZooKeeper/pipeline.md)；存储见 [storage](/docs/CS/Framework/ZooKeeper/storage.md)。本页只讲 Zab 协议本身（角色、广播模型、三阶段、与 Raft 对照）。

## Leader Election（摘要）

Zab 的 Leader Election 要解决"集群刚启动 / Leader 失效后谁当 Leader"以及"新 Leader 如何让全集群状态对齐"。它分两步：

1. **投票选举（FastLeaderElection）**：每个 peer 先投自己一票，按"得票最多 + zxid 最高"收敛出唯一候选 Leader。
2. **状态同步（synchronization）**：新 Leader 必须拿到**超过半数** follower 的 ACK 才真正生效，否则放弃并重新选举；follower 与新 Leader 对齐（补发缺失 proposal 或整体快照）。

> 选主通信层 `QuorumCnxManager`（SID 大者主动连）、FLE 四步状态机、`QuorumPeer::run` 主循环与故障切换，全部在 [Election](/docs/CS/Framework/ZooKeeper/Election.md)。


## Atomic Broadcast

Zab 的核心是**原子广播**，与 Paxos 类似但关键差异在于"**对完整历史前缀达成一致**"（而非单个操作），从而保留 primary order。因此 Zab 是一个 `PO atomic broadcast` 协议。

Zab 分三阶段：**discovery（发现）→ synchronization（同步）→ broadcast（广播）**。每个进程同一时刻只执行协议的一轮迭代；任何时刻可放弃当前迭代、退回 Phase 1 重新开始。

> [!NOTE]
> 具体的 proposal 广播与提交（zxid 分配、过半 ACK、commit 下发、proposal 丢失重发）已在 Introduction 的"角色模型"中说明；同步恢复的代码细节见 [Election](/docs/CS/Framework/ZooKeeper/Election.md)。

## process

每台服务器在进行FastLeaderElection对象创建时，都会启动一个QuorumCnxManager,负责各台服务器之间的底层Leader选举过程中的网络通信，
这个类中维护了一系列的队列，用于保存接收到的/待发送的消息，对于发送队列，会对每台其他服务器分别创建一个发送队列，互不干扰。



QuorumCnxManager会为每个远程服务器创建一个SendWorker线程和RecvWorker线程

- 消息发送过程：
  每个SendWorker不断的从对应的消息发送队列中获取一个消息来发送，并将这个消息放入lastMessageSent中，如果队列为空，则从lastMessageSent取出最后一个消息重新发送，可解决接方没有正确接收或处理消息的问题
- 消息接收过程：
  每个RecvWorker不断的从这个TCP连接中读取消息，并将其保存到recvQueue队列中



在两两创建连接时，有个规则：只允许SID大的服务器主动和其他服务器建立连接，否则断开连接。在receiveConnection方法中，服务器会接受远程SID比自己大的连接。从而避免了两台服务器之间的重复连接


There are three states this server can be in:
Leader election - each server will elect a leader (proposing itself as a leader initially).
Follower - the server will synchronize with the leader and replicate any transactions.
Leader - the server will process requests and forward them to followers. A majority of followers must log the request before it can be accepted.

```java
public class QuorumPeer extends ZooKeeperThread implements QuorumStats.Provider {
    @Override
    public void run() {
        updateThreadName();

        LOG.debug("Starting quorum peer");
        try {
            jmxQuorumBean = new QuorumBean(this);
            MBeanRegistry.getInstance().register(jmxQuorumBean, null);
            for (QuorumServer s : getView().values()) {
                ZKMBeanInfo p;
                if (getMyId() == s.id) {
                    p = jmxLocalPeerBean = new LocalPeerBean(this);
                    try {
                        MBeanRegistry.getInstance().register(p, jmxQuorumBean);
                    } catch (Exception e) {
                        LOG.warn("Failed to register with JMX", e);
                        jmxLocalPeerBean = null;
                    }
                } else {
                    RemotePeerBean rBean = new RemotePeerBean(this, s);
                    try {
                        MBeanRegistry.getInstance().register(rBean, jmxQuorumBean);
                        jmxRemotePeerBean.put(s.id, rBean);
                    } catch (Exception e) {
                        LOG.warn("Failed to register with JMX", e);
                    }
                }
            }
        } catch (Exception e) {
            LOG.warn("Failed to register with JMX", e);
            jmxQuorumBean = null;
        }

        try {
            /*
             * Main loop
             */
            while (running) {
                if (unavailableStartTime == 0) {
                    unavailableStartTime = Time.currentElapsedTime();
                }

                switch (getPeerState()) {
                case LOOKING:
                    LOG.info("LOOKING");
                    ServerMetrics.getMetrics().LOOKING_COUNT.add(1);

                    if (Boolean.getBoolean("readonlymode.enabled")) {
                        LOG.info("Attempting to start ReadOnlyZooKeeperServer");

                        // Create read-only server but don't start it immediately
                        final ReadOnlyZooKeeperServer roZk = new ReadOnlyZooKeeperServer(logFactory, this, this.zkDb);

                        // Instead of starting roZk immediately, wait some grace
                        // period before we decide we're partitioned.
                        //
                        // Thread is used here because otherwise it would require
                        // changes in each of election strategy classes which is
                        // unnecessary code coupling.
                        Thread roZkMgr = new Thread() {
                            public void run() {
                                try {
                                    // lower-bound grace period to 2 secs
                                    sleep(Math.max(2000, tickTime));
                                    if (ServerState.LOOKING.equals(getPeerState())) {
                                        roZk.startup();
                                    }
                                } catch (InterruptedException e) {
                                    LOG.info("Interrupted while attempting to start ReadOnlyZooKeeperServer, not started");
                                } catch (Exception e) {
                                    LOG.error("FAILED to start ReadOnlyZooKeeperServer", e);
                                }
                            }
                        };
                        try {
                            roZkMgr.start();
                            reconfigFlagClear();
                            if (shuttingDownLE) {
                                shuttingDownLE = false;
                                startLeaderElection();
                            }
                            setCurrentVote(makeLEStrategy().lookForLeader());
                            checkSuspended();
                        } catch (Exception e) {
                            LOG.warn("Unexpected exception", e);
                            setPeerState(ServerState.LOOKING);
                        } finally {
                            // If the thread is in the the grace period, interrupt
                            // to come out of waiting.
                            roZkMgr.interrupt();
                            roZk.shutdown();
                        }
                    } else {
                        try {
                            reconfigFlagClear();
                            if (shuttingDownLE) {
                                shuttingDownLE = false;
                                startLeaderElection();
                            }
                            setCurrentVote(makeLEStrategy().lookForLeader());
                        } catch (Exception e) {
                            LOG.warn("Unexpected exception", e);
                            setPeerState(ServerState.LOOKING);
                        }
                    }
                    break;
                case OBSERVING:
                    try {
                        LOG.info("OBSERVING");
                        setObserver(makeObserver(logFactory));
                        observer.observeLeader();
                    } catch (Exception e) {
                        LOG.warn("Unexpected exception", e);
                    } finally {
                        observer.shutdown();
                        setObserver(null);
                        updateServerState();

                        // Add delay jitter before we switch to LOOKING
                        // state to reduce the load of ObserverMaster
                        if (isRunning()) {
                            Observer.waitForObserverElectionDelay();
                        }
                    }
                    break;
                case FOLLOWING:
                    try {
                        LOG.info("FOLLOWING");
                        setFollower(makeFollower(logFactory));
                        follower.followLeader();
                    } catch (Exception e) {
                        LOG.warn("Unexpected exception", e);
                    } finally {
                        follower.shutdown();
                        setFollower(null);
                        updateServerState();
                    }
                    break;
                case LEADING:
                    LOG.info("LEADING");
                    try {
                        setLeader(makeLeader(logFactory));
                        leader.lead();
                        setLeader(null);
                    } catch (Exception e) {
                        LOG.warn("Unexpected exception", e);
                    } finally {
                        if (leader != null) {
                            leader.shutdown("Forcing shutdown");
                            setLeader(null);
                        }
                        updateServerState();
                    }
                    break;
                }
            }
        } finally {
            LOG.warn("QuorumPeer main thread exited");
            MBeanRegistry instance = MBeanRegistry.getInstance();
            instance.unregister(jmxQuorumBean);
            instance.unregister(jmxLocalPeerBean);

            for (RemotePeerBean remotePeerBean : jmxRemotePeerBean.values()) {
                instance.unregister(remotePeerBean);
            }

            jmxQuorumBean = null;
            jmxLocalPeerBean = null;
            jmxRemotePeerBean = null;
        }
    }
}
```

Responsible for performing local session upgrade. 
Only request submitted directly to the leader should go through this processor.

```java
public class LeaderRequestProcessor implements RequestProcessor {
    @Override
    public void processRequest(Request request) throws RequestProcessorException {
        // Screen quorum requests against ACLs first
        if (!lzks.authWriteRequest(request)) {
            return;
        }

        // Check if this is a local session and we are trying to create
        // an ephemeral node, in which case we upgrade the session
        Request upgradeRequest = null;
        try {
            upgradeRequest = lzks.checkUpgradeSession(request);
        } catch (KeeperException ke) {
            if (request.getHdr() != null) {
                request.getHdr().setType(OpCode.error);
                request.setTxn(new ErrorTxn(ke.code().intValue()));
            }
            request.setException(ke);
        } catch (IOException ie) {
            LOG.error("Unexpected error in upgrade", ie);
        }
        if (upgradeRequest != null) {
            nextProcessor.processRequest(upgradeRequest);
        }

        nextProcessor.processRequest(request);
    }
}
```


对于事务请求会发起Proposal 将事务请求交付给SyncRequestProcessor
```java
public class ProposalRequestProcessor implements RequestProcessor {
    public void processRequest(Request request) throws RequestProcessorException {
        /* In the following IF-THEN-ELSE block, we process syncs on the leader.
         * If the sync is coming from a follower, then the follower
         * handler adds it to syncHandler. Otherwise, if it is a client of
         * the leader that issued the sync command, then syncHandler won't
         * contain the handler. In this case, we add it to syncHandler, and
         * call processRequest on the next processor.
         */
        if (request instanceof LearnerSyncRequest) {
            zks.getLeader().processSync((LearnerSyncRequest) request);
        } else {
            if (shouldForwardToNextProcessor(request)) {
                nextProcessor.processRequest(request);
            }
            if (request.getHdr() != null) {
                // We need to sync and get consensus on any transactions
                try {
                    zks.getLeader().propose(request);
                } catch (XidRolloverException e) {
                    throw new RequestProcessorException(e.getMessage(), e);
                }
                syncProcessor.processRequest(request);
            }
        }
    }
}
```

ToBeAppliedRequestProcessor 的核心为一个toBeApplied队列，专门用来存储那些已经被CommitProcessor处理过的可提交的Proposal——直到FinalRequestProcessor处理完后，才会将其移除。

```java
// Leader.java
static class ToBeAppliedRequestProcessor implements RequestProcessor {
    public void processRequest(Request request) throws RequestProcessorException {
        next.processRequest(request);

        // The only requests that should be on toBeApplied are write
        // requests, for which we will have a hdr. We can't simply use
        // request.zxid here because that is set on read requests to equal
        // the zxid of the last write op.
        if (request.getHdr() != null) {
            long zxid = request.getHdr().getZxid();
            Iterator<Proposal> iter = leader.toBeApplied.iterator();
            if (iter.hasNext()) {
                Proposal p = iter.next();
                if (p.request != null && p.request.zxid == zxid) {
                    iter.remove();
                    return;
                }
            }
            LOG.error("Committed request not found on toBeApplied: {}", request);
        }
    }
}
```

#### FinalRequestProcessor

This Request processor actually applies any transaction associated with a request and services any queries. It is always at the end of a RequestProcessor chain (hence the name), so it does not have a nextProcessor member. This RequestProcessor counts on ZooKeeperServer to populate the outstandingRequests member of ZooKeeperServer.

```java
public class FinalRequestProcessor implements RequestProcessor {
    
}
```

### RecvWorker

```java
class RecvWorker extends ZooKeeperThread {

    Long sid;
    Socket sock;
    volatile boolean running = true;
    final DataInputStream din;
    final SendWorker sw;

    @Override
    public void run() {
        threadCnt.incrementAndGet();
        try {
            LOG.debug("RecvWorker thread towards {} started. myId: {}", sid, QuorumCnxManager.this.mySid);
            while (running && !shutdown && sock != null) {
                /**
                 * Reads the first int to determine the length of the
                 * message
                 */
                int length = din.readInt();
                if (length <= 0 || length > PACKETMAXSIZE) {
                    throw new IOException("Received packet with invalid packet: " + length);
                }
                /**
                 * Allocates a new ByteBuffer to receive the message
                 */
                final byte[] msgArray = new byte[length];
                din.readFully(msgArray, 0, length);
                addToRecvQueue(new Message(ByteBuffer.wrap(msgArray), sid));
            }
        } catch (Exception e) {
            LOG.warn(
                    "Connection broken for id {}, my id = {}",
                    sid,
                    QuorumCnxManager.this.mySid,
                    e);
        } finally {
            sw.finish();
            closeSocket(sock);
        }
    }
}
```
Inserts an element in the recvQueue. 
If the Queue is full, this methods removes an element from the head of the Queue and then inserts the element at the tail of the queue.


```java
    public void addToRecvQueue(final Message msg) {
      final boolean success = this.recvQueue.offer(msg);
      if (!success) {
          throw new RuntimeException("Could not insert into receive queue");
      }
    }
```

## ZAB and Raft

ZAB 是专为 Zookeeper 定制的非通用协议，

|        | ZAB                                            | Raft           |
| ------ | ---------------------------------------------- | -------------- |
| 一致性 | 写强一致性，读线性一致性（支持同步读强一致性） | 写、读强一致性 |
|        |                                                |                |
|        |                                                |                |

## Links

- [Election（Leader Election 源码深潜）](/docs/CS/Framework/ZooKeeper/Election.md)
- [ZooKeeper（概念枢纽）](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [请求处理链 pipeline](/docs/CS/Framework/ZooKeeper/pipeline.md)
- [存储 storage](/docs/CS/Framework/ZooKeeper/storage.md)
- [集群角色 cluster](/docs/CS/Framework/ZooKeeper/cluster.md)
- [NIO 网络层](/docs/CS/Framework/ZooKeeper/NIO.md)
- [Consensus](/docs/CS/Distributed/Consensus/Consensus.md)
- [Paxos](/docs/CS/Distributed/Consensus/Paxos.md)

## References

1. [Zab: High-performance broadcast for primary-backup systems](https://marcoserafini.github.io/papers/zab.pdf)
2. [ZooKeeper’s atomic broadcast protocol:Theory and practice](http://www.tcs.hut.fi/Studies/T-79.5001/reports/2012-deSouzaMedeiros.pdf)
3. [A simple totally ordered broadcast protocol](https://www.datadoghq.com/pdf/zab.totally-ordered-broadcast-protocol.2008.pdf)
