## Introduction

[A simple totally ordered broadcast protocol](https://www.datadoghq.com/pdf/zab.totally-ordered-broadcast-protocol.2008.pdf)

[ZooKeeper’s atomic broadcast protocol:Theory and practice](http://www.tcs.hut.fi/Studies/T-79.5001/reports/2012-deSouzaMedeiros.pdf)

[Zab: High-performance broadcast for primary-backup systems](https://marcoserafini.github.io/papers/zab.pdf)




Zab is very similar to [Paxos](/docs/CS/Distributed/Paxos.md), with one crucial difference – the agreement is reached on full history prefixes rather than on individual operations.
This difference allows Zab to preserve primary order, which may be violated by Paxos.


ZooKeeper 中，则是引入了 领导者（Leader）、跟随者（Follower）、观察者（Observer） 三种角色 和 领导（Leading）、跟随（Following）、观察（Observing）、寻找（Looking） 等相应的状态。在 ZooKeeper 集群中的通过一种 Leader 选举的过程，来选定某个节点作为 Leader 节点，该节点为客户端提供读和写服务。而 Follower 和 Observer 节点，则都能提供读服务，唯一的区别在于，Observer 机器不参与 Leader 选举过程 和 写操作的 "过半写成功" 策略，Observer 只会被告知已经 commit 的 proposal。因此 Observer 可以在不影响写性能的情况下提升集群的读性能


所有事务请求必须由一个全局唯一的服务器来协调处理，这样的服务器被称为leader服务器，而余下的其他服务器则成为follower服务器。
leader服务器负责将一个客户端事务请求转换成一个事务proposal，并将该proposal分发给集群中所有的follower服务器。之后leader服务器需要等待所有follower服务器的反馈，一旦超过半数的follower服务器进行了正确的反馈后，那么leader就会自己先commit这个事务，并再次向所有的follower服务器分发commit消息，要求其将前一个proposal进行提交。

ZAB协议的消息广播过程使用原子广播协议，类似于一个二阶段提交过程，针对客户端的事务请求，Leader服务器会为其生成对应的事务Proposal，并将其发送给集群中其余所有的机器，然后再分别收集各自的选票，最后进行事务提交
此处ZAB的二阶段提交和一般的二阶段提交略有不同，ZAB移除了二阶段提交中的事务中断的逻辑，follower服务器要么正常反馈，要么抛弃leader。好处是我们不需要等待所有follower都反馈响应才能提交事务，坏处是集群无法处理leader崩溃而带来的数据不一致的问题。后者需要崩溃恢复模式来解决这个问题。
整个消息广播协议是基于具有FIFO特性的TCP协议来进行网络通信的，因此能够很容易保证消息广播过程中消息接受与发送的顺序性。
整个消息广播过程中，Leader服务器会为每个事务生成对应的Proposal来进行广播，并且在广播事务Proposal之前，Leader服务器会先为这个Proposal分配一个全局单调递增的唯一ID，称之为事务ID（ZXID），由于ZAB协议需要保证每个消息严格的因果关系，因此必须将每个事务Proposal按照其ZXID的先后顺序来进行排序和处理。
在广播过程中，leader会为每一个follower分配一个单独的队列，然后将需要广播的事务proposal依次放入，并且根据FIFO策略进行消息发送。每个follower接收到proposal之后，都会首先将其以事务日志的形式写入本地磁盘，写入成功后反馈leader一个ack响应。当leader收到超过半数的follower的ack响应之后，就会广播一个commit消息给所有follower以通知其进行事务提交，同时leader自身也完成事务的提交。每个follower在接收到commit之后，也会完成对事务的提交。
在广播过程中，如果follower接收到proposal之后记录事务日志失败，或者proposal丢失。紧接着不久后，它直接接到了这个proposal的commit，那么follower就会向leader发送请求重新申请这个任务，leader会再次发送proposal和commit

```java
    public enum ServerState {
        LOOKING,
        FOLLOWING,
        LEADING,
        OBSERVING
    }
```

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


## Links

- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Consensus](/docs/CS/Distributed/Consensus.md)
