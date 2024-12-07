## Introduction

Zab is very similar to [Paxos](/docs/CS/Distributed/Paxos.md), with one crucial difference – the agreement is reached on full history prefixes rather than on individual operations.
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




## Leader Election

配置4个文件

```
# zoo1.cfg文件内容：
dataDir=/export/data/zookeeper-1
clientPort=2181
server.1=127.0.0.1:2001:3001
server.2=127.0.0.1:2002:3002
server.3=127.0.0.1:2003:3003
server.4=127.0.0.1:2004:3004:observer


# zoo2.cfg文件内容：
dataDir=/export/data/zookeeper-2
clientPort=2182
server.1=127.0.0.1:2001:3001
server.2=127.0.0.1:2002:3002
server.3=127.0.0.1:2003:3003
server.4=127.0.0.1:2004:3004:observer


# zoo3.cfg文件内容：
dataDir=/export/data/zookeeper-3
clientPort=2183
server.1=127.0.0.1:2001:3001
server.2=127.0.0.1:2002:3002
server.3=127.0.0.1:2003:3003
server.4=127.0.0.1:2004:3004:observer


# zoo4.cfg文件内容：
dataDir=/export/data/zookeeper-4
clientPort=2184
server.1=127.0.0.1:2001:3001
server.2=127.0.0.1:2002:3002
server.3=127.0.0.1:2003:3003
server.4=127.0.0.1:2004:3004:observer
```


leader选举存在与两个阶段中，一个是服务器启动时的leader选举。 一个是运行过程中leader节点宕机导致的leader选举


The request for the current leader will consist solely of an xid: int xid

启动时候从磁盘加载数据到内存，然后开启服务端的网络处理服务，然后开启一个管理端，接下来就进入比较重要的选举功能

zookeeper 选举底层主要分为选举应用层和消息传输队列层，第一层应用层队列统一接收和发送选票，而第二层传输层队列，是按照服务端 sid 分成了多个队列，是为了避免给每台服务端发送消息互相影响。比如对某台机器发送不成功不会影响正常服务端的发送

#### startLeaderElection

This class manages the quorum protocol. There are three states this server can be in:
1. Leader election - each server will elect a leader (proposing itself as a leader initially).
2. Follower - the server will synchronize with the leader and replicate any transactions.

This class will setup a datagram socket that will always respond with its view of the current leader. The response will take the form of:
int xid;
long myid;
long leader_id;
long leader_zxid;

优先zxid最大 其次myid最大


```java
public synchronized void startLeaderElection() {
    try {
        if (getPeerState() == ServerState.LOOKING) {
            currentVote = new Vote(myid, getLastLoggedZxid(), getCurrentEpoch());
        }
    } catch (IOException e) {
        RuntimeException re = new RuntimeException(e.getMessage());
        re.setStackTrace(e.getStackTrace());
        throw re;
    }

    this.electionAlg = createElectionAlgorithm(electionType);
}
```
ZK节点状态角色 ZK集群单节点状态（每个节点有且只有一个状态），ZK的定位一定需要一个leader节点处于leading状态。
- looking：寻找leader状态，当前集群没有leader，进入leader选举流程。
- following：跟随者状态，接受leading节点同步和指挥。
- leading：领导者状态。
- observing：观察者状态，表名当前服务器是observer。




```java
protected Election createElectionAlgorithm(int electionAlgorithm) {
    Election le = null;

    //TODO: use a factory rather than a switch
    switch (electionAlgorithm) {
    case 1:
        throw new UnsupportedOperationException("Election Algorithm 1 is not supported.");
    case 2:
        throw new UnsupportedOperationException("Election Algorithm 2 is not supported.");
    case 3:
        QuorumCnxManager qcm = createCnxnManager();
        QuorumCnxManager oldQcm = qcmRef.getAndSet(qcm);
        if (oldQcm != null) {
            LOG.warn("Clobbering already-set QuorumCnxManager (restarting leader election?)");
            oldQcm.halt();
        }
        QuorumCnxManager.Listener listener = qcm.listener;
        if (listener != null) {
            listener.start();
            FastLeaderElection fle = new FastLeaderElection(this, qcm);
            fle.start();
            le = fle;
        } else {
            LOG.error("Null listener when initializing cnx manager");
        }
        break;
    default:
        assert false;
    }
    return le;
}
```
electionType 的值是哪里来的呢 其实是来源配置文件中electionAlg属性默认值为3.使用何种选举方式，目前只支持3在老的版本中也是支持其他选项的（0，1，2，3），
- “0”表示使用 原生的UDP（LeaderElection），
- “1”表示使用 非授权UDP
- “2”表示 授权UDP
- “3”基于 TCP的快速选举（FastLeaderElection）



创建QuorumCnxManager和Listener并启动Listener 创建对象完毕之后则将QuorumCnxManager对象存入成员变量AtomicReference中用于跨线程可见

使用QuorumCnxManager创建并启动FastLeaderElection

### QuorumCnxManager

QuorumCnxManager 作为核心的实现类，用来管理 Leader 服务器与 Follow 服务器的 TCP 通信，以及消息的接收与发送等功能。
在 QuorumCnxManager 中，主要定义了 ConcurrentHashMap 类型的 senderWorkerMap 数据字段，用来管理每一个通信的服务器

Qcm主要成员变量：

- `public final ArrayBlockingQueue recvQueue;` //本节点的消息接收队列
- `final ConcurrentHashMap senderWorkerMap;`//对每一个远程节点都会定义一个SendWorker
- `ConcurrentHashMap> queueSendMap;`//每个远程节点都会定义一个消息发型队列

Qcm主要三个内类（线程）：
- `Listener` 网络监听线程
- `SendWorker` 消息发送线程（每个远程节点都会有一个）
- `RecvWorker` 消息接受线程



而在 QuorumCnxManager 类的内部，定义了 RecvWorker 内部类。该类继承了一个 ZooKeeperThread 类的多线程类。
主要负责消息接收。在 ZooKeeper 的实现中，为每一个集群中的通信服务器都分配一个 RecvWorker，负责接收来自其他服务器发送的信息。
在 RecvWorker 的 run 函数中，不断通过 queueSendMap 队列读取信息

除了接收信息的功能外，QuorumCnxManager 内还定义了一个 SendWorker 内部类用来向集群中的其他服务器发送投票信息。如下面的代码所示。在 SendWorker 类中，不会立刻将投票信息发送到 ZooKeeper 集群中，而是将投票信息首先插入到 pollSendQueue 队列，之后通过 send 函数进行发送

对于每个对等点，管理器维护一个要发送的消息队列。

如果与任何特定对等点的连接断开，则发送方线程将消息放回到列表中。由于此实现目前使用队列实现来维护要发送给另一个对等体的消息，因此我们将消息添加到队列的尾部，从而更改消息的顺序。虽然这对领导选举来说不是问题，但在点对点通信时可能会出现问题

```java
public QuorumCnxManager createCnxnManager() {
    int timeout = quorumCnxnTimeoutMs > 0 ? quorumCnxnTimeoutMs : this.tickTime * this.syncLimit;
    LOG.info("Using {}ms as the quorum cnxn socket timeout", timeout);
    return new QuorumCnxManager(
        this,
        this.getMyId(),
        this.getView(),
        this.authServer,
        this.authLearner,
        timeout,
        this.getQuorumListenOnAllIPs(),
        this.quorumCnxnThreadsSize,
        this.isQuorumSaslAuthEnabled());
}
```

构造器的初始化主要看一下initializeConnectionExecutor创建连接线程池 在连接初始化期间使用Connection Executor(用于处理连接超时)，也可以在接收连接期间选择使用它(因为Quorum SASL身份验证可能需要额外的时间)

```java
public QuorumCnxManager(QuorumPeer self, final long mySid, Map<Long, QuorumPeer.QuorumServer> view,
    QuorumAuthServer authServer, QuorumAuthLearner authLearner, int socketTimeout, boolean listenOnAllIPs,
    int quorumCnxnThreadsSize, boolean quorumSaslAuthEnabled) {

    this.recvQueue = new CircularBlockingQueue<>(RECV_CAPACITY);
    this.queueSendMap = new ConcurrentHashMap<>();
    this.senderWorkerMap = new ConcurrentHashMap<>();
    this.lastMessageSent = new ConcurrentHashMap<>();

    String cnxToValue = System.getProperty("zookeeper.cnxTimeout");
    if (cnxToValue != null) {
        this.cnxTO = Integer.parseInt(cnxToValue);
    }

    this.self = self;

    this.mySid = mySid;
    this.socketTimeout = socketTimeout;
    this.view = view;
    this.listenOnAllIPs = listenOnAllIPs;
    this.authServer = authServer;
    this.authLearner = authLearner;
    this.quorumSaslAuthEnabled = quorumSaslAuthEnabled;

    initializeConnectionExecutor(mySid, quorumCnxnThreadsSize);

    // Starts listener thread that waits for connection requests
    listener = new Listener();
    listener.setName("QuorumPeerListener");
}
```






```java
private void initializeConnectionExecutor(final long mySid, final int quorumCnxnThreadsSize) {
    final AtomicInteger threadIndex = new AtomicInteger(1);
    SecurityManager s = System.getSecurityManager();
    final ThreadGroup group = (s != null) ? s.getThreadGroup() : Thread.currentThread().getThreadGroup();

    final ThreadFactory daemonThFactory = runnable -> new Thread(group, runnable,
        String.format("QuorumConnectionThread-[myid=%d]-%d", mySid, threadIndex.getAndIncrement()));

    this.connectionExecutor = new ThreadPoolExecutor(3, quorumCnxnThreadsSize, 60, TimeUnit.SECONDS,
                                                     new SynchronousQueue<>(), daemonThFactory);
    this.connectionExecutor.allowCoreThreadTimeOut(true);
}
```


### listener

Listener内部线程的run方法如下用于启动监听端口，监听其他server的连接与数据传输

使用BIO模式 对每个member创建一个线程处理
```java
public class Listener extends ZooKeeperThread {
    @Override
    public void run() {
        if (!shutdown) {
            LOG.debug("Listener thread started, myId: {}", self.getMyId());
            Set<InetSocketAddress> addresses;

            if (self.getQuorumListenOnAllIPs()) {
                addresses = self.getElectionAddress().getWildcardAddresses();
            } else {
                addresses = self.getElectionAddress().getAllAddresses();
            }

            CountDownLatch latch = new CountDownLatch(addresses.size());
            listenerHandlers = addresses.stream().map(address ->
                                                      new ListenerHandler(address, self.shouldUsePortUnification(), self.isSslQuorum(), latch))
            .collect(Collectors.toList());

            final ExecutorService executor = Executors.newFixedThreadPool(addresses.size());
            try {
                listenerHandlers.forEach(executor::submit);
            } finally {
                // prevent executor's threads to leak after ListenerHandler tasks complete
                executor.shutdown();
            }

            try {
                latch.await();
            } catch (InterruptedException ie) {
                LOG.error("Interrupted while sleeping. Ignoring exception", ie);
            } finally {
                // Clean up for shutdown.
                for (ListenerHandler handler : listenerHandlers) {
                    try {
                        handler.close();
                    } catch (IOException ie) {
                        // Don't log an error for shutdown.
                        LOG.debug("Error closing server socket", ie);
                    }
                }
            }
        }

        LOG.info("Leaving listener");
        if (!shutdown) {
            LOG.error(
                "As I'm leaving the listener thread, I won't be able to participate in leader election any longer: {}",
                self.getElectionAddress().getAllAddresses().stream()
                .map(NetUtils::formatInetAddr)
                .collect(Collectors.joining("|")));
            if (socketException.get()) {
                // After leaving listener thread, the host cannot join the quorum anymore,
                // this is a severe error that we cannot recover from, so we need to exit
                socketBindErrorHandler.run();
            }
        }
    }
}
```


开启服务端口监听等待客户端连接, 大的sid连接小的sid的服务逻辑如下:
- 如果建立连接的客户端的sid小于当前实例的sid则断开与当前客户端的连接转而充当客户端- 连接当前更大sid的服务
- 如果建立连接的客户端的sid大于当前实例的sid则正常连接开启发送和接收的子线程SendWorker和RecvWorker
- 发送线程循环从发送队列中拉取消息进行发送(queueSendMap 中sid对应的发送队列)
- 接收消息线程循环的获取客户端发送过来的消息,然后将消息存入接收消息队列中recvQueue - 在FastLeaderElection选取算法类型中会创建Messenger类型对象
- Messenger类型对象通过内部的WorkerSender和WorkerReceiver线程来处理需要发送和需要接收的消息然后将消息放入发送队列(queueSendMap中sid对应的发送队列)或者从接收队列recvQueue中获取消息进行处理



```java
class ListenerHandler implements Runnable, Closeable {
    private ServerSocket serverSocket;
    private InetSocketAddress address;
    private boolean portUnification;
    private boolean sslQuorum;
    private CountDownLatch latch;

    ListenerHandler(InetSocketAddress address, boolean portUnification, boolean sslQuorum,
                    CountDownLatch latch) {
        this.address = address;
        this.portUnification = portUnification;
        this.sslQuorum = sslQuorum;
        this.latch = latch;
    }

    @Override
    public void run() {
        try {
            Thread.currentThread().setName("ListenerHandler-" + address);
            acceptConnections();
            try {
                close();
            } catch (IOException e) {
                LOG.warn("Exception when shutting down listener: ", e);
            }
        } catch (Exception e) {
            // Output of unexpected exception, should never happen
            LOG.error("Unexpected error ", e);
        } finally {
            latch.countDown();
        }
    }
}
```



连接处理

```java
private void acceptConnections() {
    int numRetries = 0;
    Socket client = null;

    while ((!shutdown) && (portBindMaxRetry == 0 || numRetries < portBindMaxRetry)) {
        try {
            serverSocket = createNewServerSocket();
            LOG.info("{} is accepting connections now, my election bind port: {}", QuorumCnxManager.this.mySid, address.toString());
            while (!shutdown) {
                try {
                    client = serverSocket.accept();
                    setSockOpts(client);
                    LOG.info("Received connection request from {}", client.getRemoteSocketAddress());
                    // Receive and handle the connection request
                    // asynchronously if the quorum sasl authentication is
                    // enabled. This is required because sasl server
                    // authentication process may take few seconds to finish,
                    // this may delay next peer connection requests.
                    if (quorumSaslAuthEnabled) {
                        receiveConnectionAsync(client);
                    } else {
                        receiveConnection(client);
                    }
                    numRetries = 0;
                } catch (SocketTimeoutException e) {
                    LOG.warn("The socket is listening for the election accepted "
                            + "and it timed out unexpectedly, but will retry."
                            + "see ZOOKEEPER-2836");
                }
            }
        } catch (IOException e) {
            if (shutdown) {
                break;
            }

            LOG.error("Exception while listening to address {}", address, e);

            if (e instanceof SocketException) {
                socketException.set(true);
            }

            numRetries++;
            try {
                close();
                Thread.sleep(1000);
            } catch (IOException ie) {
                LOG.error("Error closing server socket", ie);
            } catch (InterruptedException ie) {
                LOG.error("Interrupted while sleeping. Ignoring exception", ie);
            }
            closeSocket(client);
        }
    }
    if (!shutdown) {
        LOG.error(
          "Leaving listener thread for address {} after {} errors. Use {} property to increase retry count.",
          formatInetAddr(address),
          numRetries,
          ELECTION_PORT_BIND_RETRY);
    }
}

private ServerSocket createNewServerSocket() throws IOException {
    ServerSocket socket;

    if (portUnification) {
        LOG.info("Creating TLS-enabled quorum server socket");
        socket = new UnifiedServerSocket(self.getX509Util(), true);
    } else if (sslQuorum) {
        LOG.info("Creating TLS-only quorum server socket");
        socket = new UnifiedServerSocket(self.getX509Util(), false);
    } else {
        socket = new ServerSocket();
    }

    socket.setReuseAddress(true);
    address = new InetSocketAddress(address.getHostString(), address.getPort());
    socket.bind(address);

    return socket;
}
```

updateProposal
```java
synchronized void updateProposal(long leader, long zxid, long epoch) {
        proposedLeader = leader;
        proposedZxid = zxid;
        proposedEpoch = epoch;
    }
```


### FastLeaderElection

FastLeaderElection对象的创建涉及到哪些内容:

- 创建发送队列sendqueue
- 创建接收队列recvqueue
- 创建线程 WorkerSender
- 创建线程 WorkerReceiver

```java
public class FastLeaderElection implements Election {
    public FastLeaderElection(QuorumPeer self, QuorumCnxManager manager) {
        this.stop = false;
        this.manager = manager;
        starter(self, manager);
    }

    private void starter(QuorumPeer self, QuorumCnxManager manager) {
        this.self = self;
        proposedLeader = -1;
        proposedZxid = -1;

        sendqueue = new LinkedBlockingQueue<>();
        recvqueue = new LinkedBlockingQueue<>();
        this.messenger = new Messenger(manager);
    }

    protected class Messenger {
        WorkerSender ws;
        WorkerReceiver wr;
        Thread wsThread = null;
        Thread wrThread = null;

        Messenger(QuorumCnxManager manager) {
            this.ws = new WorkerSender(manager);
            this.wsThread = new Thread(this.ws, "WorkerSender[myid=" + self.getMyId() + "]");
            this.wsThread.setDaemon(true);

            this.wr = new WorkerReceiver(manager);
            this.wrThread = new Thread(this.wr, "WorkerReceiver[myid=" + self.getMyId() + "]");
            this.wrThread.setDaemon(true);
        }
    }
}
```

启动了用于接收和发送数据使用的WorkerSender线程和WorkerReceiver线程,

是否需要投票还需要根据当前集群的一个状态来看,在 QuorumPeer 最后一步启动的时候会进行状态判断发起投票. 发送和接收的详细内容待会在看 WorkerSender数据传输层

这个发送类型主要做中间层将需要发送的消息转换成ByteBuffer ,然后调用QuorumCnxManager的toSend方法来发送消息


```java

FastLeaderElection fle = new FastLeaderElection(this, qcm);
fle.start();

void start() {
    this.wsThread.start();
    this.wrThread.start();
}
```

### Sender
WorkerSender 线程自旋获取 sendqueue 第一层队列元素
- sendqueue 队列元素内容为相关选票信息详见 ToSend 类；
- 首先判断选票 sid 是否和自己 sid 值相同，相等直接放入到 recvQueue 队列中；
- 不相同将 sendqueue 队列元素转储到 queueSendMap第二层传输队列中。

```java
class WorkerSender extends ZooKeeperThread {

    volatile boolean stop;
    QuorumCnxManager manager;

    WorkerSender(QuorumCnxManager manager) {
        super("WorkerSender");
        this.stop = false;
        this.manager = manager;
    }

    public void run() {
        while (!stop) {
            try {
                ToSend m = sendqueue.poll(3000, TimeUnit.MILLISECONDS);
                if (m == null) {
                    continue;
                }

                process(m);
            } catch (InterruptedException e) {
                break;
            }
        }
        LOG.info("WorkerSender is down");
    }

    /**
     * Called by run() once there is a new message to send.
     *
     * @param m     message to send
     */
    void process(ToSend m) {
        ByteBuffer requestBuffer = buildMsg(m.state.ordinal(), m.leader, m.zxid, m.electionEpoch, m.peerEpoch, m.configData);

        manager.toSend(m.sid, requestBuffer);

    }

}
```

### receive

WorkerReceiver 线程自旋获取 recvQueue 第二层传输队列元素转存到 recvqueue 第一层队列中

自旋 recvqueue 队列元素获取投票过来的选票信息
sid>self.sid 才可以创建连接 Socket 和 SendWorker,RecvWorker 线程，
存储到 senderWorkerMap中。对应第 2 步中的 sid<self.sid 逻辑，保证集群中所有节点之间只有一个通道连接。

自旋从 recvqueue 队列中获取到选票信息。开始进行选举：
- 判断当前选票和接收过来的选票周期是否一致
- 大于当前周期更新当前选票信息，再次发送投票
- 周期相等：当前选票信息和接收的选票信息进行 PK


```java
class WorkerReceiver extends ZooKeeperThread {

    volatile boolean stop;
    QuorumCnxManager manager;

    WorkerReceiver(QuorumCnxManager manager) {
        super("WorkerReceiver");
        this.stop = false;
        this.manager = manager;
    }

    public void run() {

        Message response;
        while (!stop) {
            // Sleeps on receive
            try {
                response = manager.pollRecvQueue(3000, TimeUnit.MILLISECONDS);
                if (response == null) {
                    continue;
                }

                final int capacity = response.buffer.capacity();

                // The current protocol and two previous generations all send at least 28 bytes
                if (capacity < 28) {
                    LOG.error("Got a short response from server {}: {}", response.sid, capacity);
                    continue;
                }

                // this is the backwardCompatibility mode in place before ZK-107
                // It is for a version of the protocol in which we didn't send peer epoch
                // With peer epoch and version the message became 40 bytes
                boolean backCompatibility28 = (capacity == 28);

                // this is the backwardCompatibility mode for no version information
                boolean backCompatibility40 = (capacity == 40);

                response.buffer.clear();

                // Instantiate Notification and set its attributes
                Notification n = new Notification();

                int rstate = response.buffer.getInt();
                long rleader = response.buffer.getLong();
                long rzxid = response.buffer.getLong();
                long relectionEpoch = response.buffer.getLong();
                long rpeerepoch;

                int version = 0x0;
                QuorumVerifier rqv = null;

                try {
                    if (!backCompatibility28) {
                        rpeerepoch = response.buffer.getLong();
                        if (!backCompatibility40) {
                            /*
                             * Version added in 3.4.6
                             */

                            version = response.buffer.getInt();
                        } else {
                            LOG.info("Backward compatibility mode (36 bits), server id: {}", response.sid);
                        }
                    } else {
                        LOG.info("Backward compatibility mode (28 bits), server id: {}", response.sid);
                        rpeerepoch = ZxidUtils.getEpochFromZxid(rzxid);
                    }

                    // check if we have a version that includes config. If so extract config info from message.
                    if (version > 0x1) {
                        int configLength = response.buffer.getInt();

                        // we want to avoid errors caused by the allocation of a byte array with negative length
                        // (causing NegativeArraySizeException) or huge length (causing e.g. OutOfMemoryError)
                        if (configLength < 0 || configLength > capacity) {
                            throw new IOException(String.format("Invalid configLength in notification message! sid=%d, capacity=%d, version=%d, configLength=%d",
                                                                response.sid, capacity, version, configLength));
                        }

                        byte[] b = new byte[configLength];
                        response.buffer.get(b);

                        synchronized (self) {
                            try {
                                rqv = self.configFromString(new String(b, UTF_8));
                                QuorumVerifier curQV = self.getQuorumVerifier();
                                if (rqv.getVersion() > curQV.getVersion()) {
                                    LOG.info("{} Received version: {} my version: {}",
                                             self.getMyId(),
                                             Long.toHexString(rqv.getVersion()),
                                             Long.toHexString(self.getQuorumVerifier().getVersion()));
                                    if (self.getPeerState() == ServerState.LOOKING) {
                                        LOG.debug("Invoking processReconfig(), state: {}", self.getServerState());
                                        self.processReconfig(rqv, null, null, false);
                                        if (!rqv.equals(curQV)) {
                                            LOG.info("restarting leader election");
                                            self.shuttingDownLE = true;
                                            self.getElectionAlg().shutdown();

                                            break;
                                        }
                                    } else {
                                        LOG.debug("Skip processReconfig(), state: {}", self.getServerState());
                                    }
                                }
                            } catch (IOException | ConfigException e) {
                                LOG.error("Something went wrong while processing config received from {}", response.sid);
                            }
                        }
                    } else {
                        LOG.info("Backward compatibility mode (before reconfig), server id: {}", response.sid);
                    }
                } catch (BufferUnderflowException | IOException e) {
                    LOG.warn("Skipping the processing of a partial / malformed response message sent by sid={} (message length: {})",
                             response.sid, capacity, e);
                    continue;
                }
                /*
                 * If it is from a non-voting server (such as an observer or
                 * a non-voting follower), respond right away.
                 */
                if (!validVoter(response.sid)) {
                    Vote current = self.getCurrentVote();
                    QuorumVerifier qv = self.getQuorumVerifier();
                    ToSend notmsg = new ToSend(
                        ToSend.mType.notification,
                        current.getId(),
                        current.getZxid(),
                        logicalclock.get(),
                        self.getPeerState(),
                        response.sid,
                        current.getPeerEpoch(),
                        qv.toString().getBytes(UTF_8));

                    sendqueue.offer(notmsg);
                } else {
                    // Receive new message
                    LOG.debug("Receive new notification message. My id = {}", self.getMyId());

                    // State of peer that sent this message
                    QuorumPeer.ServerState ackstate = QuorumPeer.ServerState.LOOKING;
                    switch (rstate) {
                    case 0:
                        ackstate = QuorumPeer.ServerState.LOOKING;
                        break;
                    case 1:
                        ackstate = QuorumPeer.ServerState.FOLLOWING;
                        break;
                    case 2:
                        ackstate = QuorumPeer.ServerState.LEADING;
                        break;
                    case 3:
                        ackstate = QuorumPeer.ServerState.OBSERVING;
                        break;
                    default:
                        continue;
                    }

                    n.leader = rleader;
                    n.zxid = rzxid;
                    n.electionEpoch = relectionEpoch;
                    n.state = ackstate;
                    n.sid = response.sid;
                    n.peerEpoch = rpeerepoch;
                    n.version = version;
                    n.qv = rqv;
                    /*
                     * Print notification info
                     */
                    LOG.info(
                        "Notification: my state:{}; n.sid:{}, n.state:{}, n.leader:{}, n.round:0x{}, "
                            + "n.peerEpoch:0x{}, n.zxid:0x{}, message format version:0x{}, n.config version:0x{}",
                        self.getPeerState(),
                        n.sid,
                        n.state,
                        n.leader,
                        Long.toHexString(n.electionEpoch),
                        Long.toHexString(n.peerEpoch),
                        Long.toHexString(n.zxid),
                        Long.toHexString(n.version),
                        (n.qv != null ? (Long.toHexString(n.qv.getVersion())) : "0"));

                    /*
                     * If this server is looking, then send proposed leader
                     */

                    if (self.getPeerState() == QuorumPeer.ServerState.LOOKING) {
                        recvqueue.offer(n);

                        /*
                         * Send a notification back if the peer that sent this
                         * message is also looking and its logical clock is
                         * lagging behind.
                         */
                        if ((ackstate == QuorumPeer.ServerState.LOOKING)
                            && (n.electionEpoch < logicalclock.get())) {
                            Vote v = getVote();
                            QuorumVerifier qv = self.getQuorumVerifier();
                            ToSend notmsg = new ToSend(
                                ToSend.mType.notification,
                                v.getId(),
                                v.getZxid(),
                                logicalclock.get(),
                                self.getPeerState(),
                                response.sid,
                                v.getPeerEpoch(),
                                qv.toString().getBytes());
                            sendqueue.offer(notmsg);
                        }
                    } else {
                        /*
                         * If this server is not looking, but the one that sent the ack
                         * is looking, then send back what it believes to be the leader.
                         */
                        Vote current = self.getCurrentVote();
                        if (ackstate == QuorumPeer.ServerState.LOOKING) {
                            if (self.leader != null) {
                                if (leadingVoteSet != null) {
                                    self.leader.setLeadingVoteSet(leadingVoteSet);
                                    leadingVoteSet = null;
                                }
                                self.leader.reportLookingSid(response.sid);
                            }


                            LOG.debug(
                                "Sending new notification. My id ={} recipient={} zxid=0x{} leader={} config version = {}",
                                self.getMyId(),
                                response.sid,
                                Long.toHexString(current.getZxid()),
                                current.getId(),
                                Long.toHexString(self.getQuorumVerifier().getVersion()));

                            QuorumVerifier qv = self.getQuorumVerifier();
                            ToSend notmsg = new ToSend(
                                ToSend.mType.notification,
                                current.getId(),
                                current.getZxid(),
                                current.getElectionEpoch(),
                                self.getPeerState(),
                                response.sid,
                                current.getPeerEpoch(),
                                qv.toString().getBytes());
                            sendqueue.offer(notmsg);
                        }
                    }
                }
            } catch (InterruptedException e) {
                LOG.warn("Interrupted Exception while waiting for new message", e);
            }
        }
        LOG.info("WorkerReceiver is down");
    }

}
```


### QuorumPeer::run

在QuorumPeer 中通过super.start()方法启动线程 在线程中根据集群的状态来决定是否需要参与投票,加入集群

```java
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
```





#### case LOOKING

由于是刚刚启动，是 LOOKING 状态。所以走第一条分支。调用 setCurrentVote(makeLEStrategy().lookForLeader())

```java
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
```

##### lookForLeader

recvset 是存储每个 sid 推举的选票信息



```java
public Vote lookForLeader() throws InterruptedException {
    // ...
    self.start_fle = Time.currentElapsedTime();
    try {
        /*
         * The votes from the current leader election are stored in recvset. In other words, a vote v is in recvset
         * if v.electionEpoch == logicalclock. The current participant uses recvset to deduce on whether a majority
         * of participants has voted for it.
         */
        Map<Long, Vote> recvset = new HashMap<>();

        /*
         * The votes from previous leader elections, as well as the votes from the current leader election are
         * stored in outofelection. Note that notifications in a LOOKING state are not stored in outofelection.
         * Only FOLLOWING or LEADING notifications are stored in outofelection. The current participant could use
         * outofelection to learn which participant is the leader if it arrives late (i.e., higher logicalclock than
         * the electionEpoch of the received notifications) in a leader election.
         */
        Map<Long, Vote> outofelection = new HashMap<>();

        int notTimeout = minNotificationInterval;

        synchronized (this) {
            logicalclock.incrementAndGet();
            updateProposal(getInitId(), getInitLastLoggedZxid(), getPeerEpoch());
        }

        sendNotifications();

        SyncedLearnerTracker voteSet = null;

        /*
         * Loop in which we exchange notifications until we find a leader
         */

        while ((self.getPeerState() == ServerState.LOOKING) && (!stop)) {
            /*
             * Remove next notification from queue, times out after 2 times
             * the termination time
             */
            Notification n = recvqueue.poll(notTimeout, TimeUnit.MILLISECONDS);

            /*
             * Sends more notifications if haven't received enough.
             * Otherwise processes new notification.
             */
            if (n == null) {
                if (manager.haveDelivered()) {
                    // 发送投票请求
                    sendNotifications();
                } else {
                    // 连接其它的servers
                    manager.connectAll();
                }

                /*
                 * Exponential backoff
                 */
                notTimeout = Math.min(notTimeout << 1, maxNotificationInterval);

                /*
                 * When a leader failure happens on a master, the backup will be supposed to receive the honour from
                 * Oracle and become a leader, but the honour is likely to be delay. We do a re-check once timeout happens
                 *
                 * The leader election algorithm does not provide the ability of electing a leader from a single instance
                 * which is in a configuration of 2 instances.
                 * */
                if (self.getQuorumVerifier() instanceof QuorumOracleMaj
                        && self.getQuorumVerifier().revalidateVoteset(voteSet, notTimeout != minNotificationInterval)) {
                    setPeerState(proposedLeader, voteSet);
                    Vote endVote = new Vote(proposedLeader, proposedZxid, logicalclock.get(), proposedEpoch);
                    leaveInstance(endVote);
                    return endVote;
                }

                LOG.info("Notification time out: {} ms", notTimeout);

            } else if (validVoter(n.sid) && validVoter(n.leader)) {
                /*
                 * Only proceed if the vote comes from a replica in the current or next
                 * voting view for a replica in the current or next voting view.
                 */
                switch (n.state) {
                case LOOKING:
                    if (getInitLastLoggedZxid() == -1) {
                        break;
                    }
                    if (n.zxid == -1) {
                        break;
                    }
                    // If notification > current, replace and send messages out
                    if (n.electionEpoch > logicalclock.get()) {
                        logicalclock.set(n.electionEpoch);
                        recvset.clear();
                        if (totalOrderPredicate(n.leader, n.zxid, n.peerEpoch, getInitId(), getInitLastLoggedZxid(), getPeerEpoch())) {
                            updateProposal(n.leader, n.zxid, n.peerEpoch);
                        } else {
                            updateProposal(getInitId(), getInitLastLoggedZxid(), getPeerEpoch());
                        }
                        sendNotifications();
                    } else if (n.electionEpoch < logicalclock.get()) {
                        break;
                    } else if (totalOrderPredicate(n.leader, n.zxid, n.peerEpoch, proposedLeader, proposedZxid, proposedEpoch)) {
                        updateProposal(n.leader, n.zxid, n.peerEpoch);
                        sendNotifications();
                    }

                    // don't care about the version if it's in LOOKING state
                    recvset.put(n.sid, new Vote(n.leader, n.zxid, n.electionEpoch, n.peerEpoch));

                    voteSet = getVoteTracker(recvset, new Vote(proposedLeader, proposedZxid, logicalclock.get(), proposedEpoch));

                    // 存在多数派
                    if (voteSet.hasAllQuorums()) {

                        // Verify if there is any change in the proposed leader
                        while ((n = recvqueue.poll(finalizeWait, TimeUnit.MILLISECONDS)) != null) {
                            if (totalOrderPredicate(n.leader, n.zxid, n.peerEpoch, proposedLeader, proposedZxid, proposedEpoch)) {
                                recvqueue.put(n);
                                break;
                            }
                        }

                        /*
                         * This predicate is true once we don't read any new
                         * relevant message from the reception queue
                         */
                        if (n == null) {
                            setPeerState(proposedLeader, voteSet);
                            Vote endVote = new Vote(proposedLeader, proposedZxid, logicalclock.get(), proposedEpoch);
                            leaveInstance(endVote);
                            return endVote;
                        }
                    }
                    break;
                case OBSERVING:
                    break;
                case FOLLOWING:
                    /*
                    * To avoid duplicate codes
                    * */
                    Vote resultFN = receivedFollowingNotification(recvset, outofelection, voteSet, n);
                    if (resultFN == null) {
                        break;
                    } else {
                        return resultFN;
                    }
                case LEADING:
                    /*
                    * In leadingBehavior(), it performs followingBehvior() first. When followingBehavior() returns
                    * a null pointer, ask Oracle whether to follow this leader.
                    * */
                    Vote resultLN = receivedLeadingNotification(recvset, outofelection, voteSet, n);
                    if (resultLN == null) {
                        break;
                    } else {
                        return resultLN;
                    }
                default:
                    LOG.warn("Notification state unrecognized: {} (n.state), {}(n.sid)", n.state, n.sid);
                    break;
                }
            } else {
                if (!validVoter(n.leader)) {
                    LOG.warn("Ignoring notification for non-cluster member sid {} from sid {}", n.leader, n.sid);
                }
                if (!validVoter(n.sid)) {
                    LOG.warn("Ignoring notification for sid {} from non-quorum member sid {}", n.leader, n.sid);
                }
            }
        }
        return null;
    } finally {
        try {
            if (self.jmxLeaderElectionBean != null) {
                MBeanRegistry.getInstance().unregister(self.jmxLeaderElectionBean);
            }
        } catch (Exception e) {
            LOG.warn("Failed to unregister with JMX", e);
        }
        self.jmxLeaderElectionBean = null;
        LOG.debug("Number of connection processing threads: {}", manager.getConnectionThreadCount());
    }
}
```
取dataTree上的lastProcessedZxid

```java
private long getInitLastLoggedZxid() {
    if (self.getLearnerType() == LearnerType.PARTICIPANT) {
        return self.getLastLoggedZxid();
    } else {
        return Long.MIN_VALUE;
    }
}

public long getDataTreeLastProcessedZxid() {
    return dataTree.lastProcessedZxid;
}
```



We return true if one of the following three cases hold:
1. New epoch is higher
2. New epoch is the same as current epoch, but new zxid is higher
3. New epoch is the same as current epoch, new zxid is the same as current zxid, but server id is higher.

```java
protected boolean totalOrderPredicate(long newId, long newZxid, long newEpoch, long curId, long curZxid, long curEpoch) {
    if (self.getQuorumVerifier().getWeight(newId) == 0) {
        return false;
    }

    return ((newEpoch > curEpoch)
            || ((newEpoch == curEpoch)
                && ((newZxid > curZxid)
                    || ((newZxid == curZxid)
                        && (newId > curId)))));
}
```
update state
```java
private void setPeerState(long proposedLeader, SyncedLearnerTracker voteSet) {
    ServerState ss = (proposedLeader == self.getMyId()) ? ServerState.LEADING : learningState();
    self.setPeerState(ss);
    if (ss == ServerState.LEADING) {
        leadingVoteSet = voteSet;
    }
}
```
在case COMMITANDACTIVATE中，我们可以看到当其收到leader改变相关的消息时，就会抛出异常。接下来它自己就会变成LOOKING状态，开始选举

当leader宕机后 follower会通过心跳检测退出循环 关闭socket 设置状态为LOOKING 重新开始选举

leader检测到过半节点失去通信时 退出当前循环 关闭所有和learner的socket连接 设置状态为LOOKING 开始新的选举


In ZOOKEEPER-3922, we separate the behaviors of FOLLOWING and LEADING.
To avoid the duplication of codes, we create a method called followingBehavior which was used to shared by FOLLOWING and LEADING. This method returns a Vote.
When the returned Vote is null, it follows the original idea to break switch statement; otherwise, a valid returned Vote indicates, a leader is generated.

The reason why we need to separate these behaviors is to make the algorithm runnable for 2-node setting. An extra condition for generating leader is needed.
Due to the majority rule, only when there is a majority in the voteset, a leader will be generated.
However, in a configuration of 2 nodes, the number to achieve the majority remains 2, which means a recovered node cannot generate a leader which is the existed leader.
Therefore, we need the Oracle to kick in this situation.
In a two-node configuration, the Oracle only grants the permission to maintain the progress to one node.
The oracle either grants the permission to the remained node and makes it a new leader when there is a faulty machine, which is the case to maintain the progress.
Otherwise, the oracle does not grant the permission to the remained node, which further causes a service down.

In the former case, when a failed server recovers and participate in the leader election, it would not locate a new leader because there does not exist a majority in the voteset.
It fails on the containAllQuorum() infinitely due to two facts.
- First one is the fact that it does do not have a majority in the voteset.
- The other fact is the fact that the oracle would not give the permission since the oracle already gave the permission to the existed leader, the healthy machine.

Logically, when the oracle replies with negative, it implies the existed leader which is LEADING notification comes from is a valid leader.
To threat this negative replies as a permission to generate the leader is the purpose to separate these two behaviors.


#### sendNotifications

sendNotifications() 向其它节点发送选票信息，选票信息存储到 sendqueue 队列中。sendqueue 队列由 WorkerSender 线程处理放置到queueSendMap中 由单独的sendWorker线程处理


```java
private void sendNotifications() {
    for (long sid : self.getCurrentAndNextConfigVoters()) {
        QuorumVerifier qv = self.getQuorumVerifier();
        ToSend notmsg = new ToSend(
            ToSend.mType.notification,
            proposedLeader,
            proposedZxid,
            logicalclock.get(),
            QuorumPeer.ServerState.LOOKING,
            sid,
            proposedEpoch,
            qv.toString().getBytes(UTF_8));

        sendqueue.offer(notmsg);
    }
}
```



#### case OBSERVING



```java
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
```

setObserver(makeObserver(logFactory));
观察者是不参与原子广播协议的对等点。 相反，他们会被领导者告知成功的提案。 因此，观察者自然地充当发布提案流的中继点，并可以减轻追随者的一些连接负载。 观察员可以提交提案，但不投票接受。 有关此功能的讨论，请参阅 ZOOKEEPER-368。



Observer和Follower都继承了Learner 接下来Observer开始连接leader

```java
void observeLeader() throws Exception {
    zk.registerJMX(new ObserverBean(this, zk), self.jmxLocalPeerBean);
    long connectTime = 0;
    boolean completedSync = false;
    try {
        self.setZabState(QuorumPeer.ZabState.DISCOVERY);
        QuorumServer master = findLearnerMaster();
        try {
            connectToLeader(master.addr, master.hostname);
            connectTime = System.currentTimeMillis();
            long newLeaderZxid = registerWithLeader(Leader.OBSERVERINFO);
            if (self.isReconfigStateChange()) {
                throw new Exception("learned about role change");
            }

            final long startTime = Time.currentElapsedTime();
            self.setLeaderAddressAndId(master.addr, master.getId());
            self.setZabState(QuorumPeer.ZabState.SYNCHRONIZATION);
            syncWithLeader(newLeaderZxid);
            self.setZabState(QuorumPeer.ZabState.BROADCAST);
            completedSync = true;
            final long syncTime = Time.currentElapsedTime() - startTime;
            ServerMetrics.getMetrics().OBSERVER_SYNC_TIME.add(syncTime);
            QuorumPacket qp = new QuorumPacket();
            while (this.isRunning() && nextLearnerMaster.get() == null) {
                readPacket(qp);
                processPacket(qp);
            }
        } catch (Exception e) {
            LOG.warn("Exception when observing the leader", e);
            closeSocket();

            // clear pending revalidations
            pendingRevalidations.clear();
        }
    } finally {
        currentLearnerMaster = null;
        zk.unregisterJMX(this);
        if (connectTime != 0) {
            long connectionDuration = System.currentTimeMillis() - connectTime;
            messageTracker.dumpToLog(leaderAddr.toString());
        }
    }
}
```



#### case FOLLOWING

选主完成following切换到following状态

```java
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
```

followLeader

```java
void followLeader() throws InterruptedException {
    self.end_fle = Time.currentElapsedTime();
    long electionTimeTaken = self.end_fle - self.start_fle;
    self.setElectionTimeTaken(electionTimeTaken);
    ServerMetrics.getMetrics().ELECTION_TIME.add(electionTimeTaken);
    LOG.info("FOLLOWING - LEADER ELECTION TOOK - {} {}", electionTimeTaken, QuorumPeer.FLE_TIME_UNIT);
    self.start_fle = 0;
    self.end_fle = 0;
    fzk.registerJMX(new FollowerBean(this, zk), self.jmxLocalPeerBean);

    long connectionTime = 0;
    boolean completedSync = false;

    try {
        self.setZabState(QuorumPeer.ZabState.DISCOVERY);
        QuorumServer leaderServer = findLeader();
        try {
            connectToLeader(leaderServer.addr, leaderServer.hostname);
            connectionTime = System.currentTimeMillis();
            long newEpochZxid = registerWithLeader(Leader.FOLLOWERINFO);
            if (self.isReconfigStateChange()) {
                throw new Exception("learned about role change");
            }
            //check to see if the leader zxid is lower than ours
            //this should never happen but is just a safety check
            long newEpoch = ZxidUtils.getEpochFromZxid(newEpochZxid);
            if (newEpoch < self.getAcceptedEpoch()) {
                LOG.error("Proposed leader epoch "
                          + ZxidUtils.zxidToString(newEpochZxid)
                          + " is less than our accepted epoch "
                          + ZxidUtils.zxidToString(self.getAcceptedEpoch()));
                throw new IOException("Error: Epoch of leader is lower");
            }
            long startTime = Time.currentElapsedTime();
            self.setLeaderAddressAndId(leaderServer.addr, leaderServer.getId());
            self.setZabState(QuorumPeer.ZabState.SYNCHRONIZATION);
            syncWithLeader(newEpochZxid);
            self.setZabState(QuorumPeer.ZabState.BROADCAST);
            completedSync = true;
            long syncTime = Time.currentElapsedTime() - startTime;
            ServerMetrics.getMetrics().FOLLOWER_SYNC_TIME.add(syncTime);
            if (self.getObserverMasterPort() > 0) {
                LOG.info("Starting ObserverMaster");

                om = new ObserverMaster(self, fzk, self.getObserverMasterPort());
                om.start();
            } else {
                om = null;
            }
            // create a reusable packet to reduce gc impact
            QuorumPacket qp = new QuorumPacket();
            while (this.isRunning()) {
                readPacket(qp);
                processPacket(qp);
            }
        } catch (Exception e) {
            LOG.warn("Exception when following the leader", e);
            closeSocket();

            // clear pending revalidations
            pendingRevalidations.clear();
        }
    } finally {
        if (om != null) {
            om.stop();
        }
        zk.unregisterJMX(this);

        if (connectionTime != 0) {
            long connectionDuration = System.currentTimeMillis() - connectionTime;
            LOG.info(
                "Disconnected from leader (with address: {}). Was connected for {}ms. Sync state: {}",
                leaderAddr,
                connectionDuration,
                completedSync);
            messageTracker.dumpToLog(leaderAddr.toString());
        }
    }
}
```



#### case LEADING

```java
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
```



lead方法



```java
void lead() throws IOException, InterruptedException {
    self.end_fle = Time.currentElapsedTime();
    long electionTimeTaken = self.end_fle - self.start_fle;
    self.setElectionTimeTaken(electionTimeTaken);
    ServerMetrics.getMetrics().ELECTION_TIME.add(electionTimeTaken);
    LOG.info("LEADING - LEADER ELECTION TOOK - {} {}", electionTimeTaken, QuorumPeer.FLE_TIME_UNIT);
    self.start_fle = 0;
    self.end_fle = 0;

    zk.registerJMX(new LeaderBean(this, zk), self.jmxLocalPeerBean);

    try {
        self.setZabState(QuorumPeer.ZabState.DISCOVERY);
        self.tick.set(0);
        zk.loadData();

        leaderStateSummary = new StateSummary(self.getCurrentEpoch(), zk.getLastProcessedZxid());

        // Start thread that waits for connection requests from
        // new followers.
        cnxAcceptor = new LearnerCnxAcceptor();
        cnxAcceptor.start();

        long epoch = getEpochToPropose(self.getMyId(), self.getAcceptedEpoch());

        zk.setZxid(ZxidUtils.makeZxid(epoch, 0));

        synchronized (this) {
            lastProposed = zk.getZxid();
        }

        newLeaderProposal.packet = new QuorumPacket(NEWLEADER, zk.getZxid(), null, null);

        if ((newLeaderProposal.packet.getZxid() & 0xffffffffL) != 0) {
            LOG.info("NEWLEADER proposal has Zxid of {}", Long.toHexString(newLeaderProposal.packet.getZxid()));
        }

        QuorumVerifier lastSeenQV = self.getLastSeenQuorumVerifier();
        QuorumVerifier curQV = self.getQuorumVerifier();
        if (curQV.getVersion() == 0 && curQV.getVersion() == lastSeenQV.getVersion()) {
            // This was added in ZOOKEEPER-1783. The initial config has version 0 (not explicitly
            // specified by the user; the lack of version in a config file is interpreted as version=0).
            // As soon as a config is established we would like to increase its version so that it
            // takes presedence over other initial configs that were not established (such as a config
            // of a server trying to join the ensemble, which may be a partial view of the system, not the full config).
            // We chose to set the new version to the one of the NEWLEADER message. However, before we can do that
            // there must be agreement on the new version, so we can only change the version when sending/receiving UPTODATE,
            // not when sending/receiving NEWLEADER. In other words, we can't change curQV here since its the committed quorum verifier,
            // and there's still no agreement on the new version that we'd like to use. Instead, we use
            // lastSeenQuorumVerifier which is being sent with NEWLEADER message
            // so its a good way to let followers know about the new version. (The original reason for sending
            // lastSeenQuorumVerifier with NEWLEADER is so that the leader completes any potentially uncommitted reconfigs
            // that it finds before starting to propose operations. Here we're reusing the same code path for
            // reaching consensus on the new version number.)

            // It is important that this is done before the leader executes waitForEpochAck,
            // so before LearnerHandlers return from their waitForEpochAck
            // hence before they construct the NEWLEADER message containing
            // the last-seen-quorumverifier of the leader, which we change below
            try {
                LOG.debug(String.format("set lastSeenQuorumVerifier to currentQuorumVerifier (%s)", curQV.toString()));
                QuorumVerifier newQV = self.configFromString(curQV.toString());
                newQV.setVersion(zk.getZxid());
                self.setLastSeenQuorumVerifier(newQV, true);
            } catch (Exception e) {
                throw new IOException(e);
            }
        }

        newLeaderProposal.addQuorumVerifier(self.getQuorumVerifier());
        if (self.getLastSeenQuorumVerifier().getVersion() > self.getQuorumVerifier().getVersion()) {
            newLeaderProposal.addQuorumVerifier(self.getLastSeenQuorumVerifier());
        }

        // We have to get at least a majority of servers in sync with
        // us. We do this by waiting for the NEWLEADER packet to get
        // acknowledged

        waitForEpochAck(self.getMyId(), leaderStateSummary);
        self.setCurrentEpoch(epoch);
        self.setLeaderAddressAndId(self.getQuorumAddress(), self.getMyId());
        self.setZabState(QuorumPeer.ZabState.SYNCHRONIZATION);

        try {
            waitForNewLeaderAck(self.getMyId(), zk.getZxid());
        } catch (InterruptedException e) {
            shutdown("Waiting for a quorum of followers, only synced with sids: [ "
                     + newLeaderProposal.ackSetsToString()
                     + " ]");
            HashSet<Long> followerSet = new HashSet<>();

            for (LearnerHandler f : getLearners()) {
                if (self.getQuorumVerifier().getVotingMembers().containsKey(f.getSid())) {
                    followerSet.add(f.getSid());
                }
            }
            boolean initTicksShouldBeIncreased = true;
            for (Proposal.QuorumVerifierAcksetPair qvAckset : newLeaderProposal.qvAcksetPairs) {
                if (!qvAckset.getQuorumVerifier().containsQuorum(followerSet)) {
                    initTicksShouldBeIncreased = false;
                    break;
                }
            }
            if (initTicksShouldBeIncreased) {
                LOG.warn("Enough followers present. Perhaps the initTicks need to be increased.");
            }
            return;
        }

        startZkServer();

        /**
         * WARNING: do not use this for anything other than QA testing
         * on a real cluster. Specifically to enable verification that quorum
         * can handle the lower 32bit roll-over issue identified in
         * ZOOKEEPER-1277. Without this option it would take a very long
         * time (on order of a month say) to see the 4 billion writes
         * necessary to cause the roll-over to occur.
         *
         * This field allows you to override the zxid of the server. Typically
         * you'll want to set it to something like 0xfffffff0 and then
         * start the quorum, run some operations and see the re-election.
         */
        String initialZxid = System.getProperty("zookeeper.testingonly.initialZxid");
        if (initialZxid != null) {
            long zxid = Long.parseLong(initialZxid);
            zk.setZxid((zk.getZxid() & 0xffffffff00000000L) | zxid);
        }

        if (!System.getProperty("zookeeper.leaderServes", "yes").equals("no")) {
            self.setZooKeeperServer(zk);
        }

        self.setZabState(QuorumPeer.ZabState.BROADCAST);
        self.adminServer.setZooKeeperServer(zk);

        // We ping twice a tick, so we only update the tick every other
        // iteration
        boolean tickSkip = true;
        // If not null then shutdown this leader
        String shutdownMessage = null;

        while (true) {
            synchronized (this) {
                long start = Time.currentElapsedTime();
                long cur = start;
                long end = start + self.tickTime / 2;
                while (cur < end) {
                    wait(end - cur);
                    cur = Time.currentElapsedTime();
                }

                if (!tickSkip) {
                    self.tick.incrementAndGet();
                }

                // We use an instance of SyncedLearnerTracker to
                // track synced learners to make sure we still have a
                // quorum of current (and potentially next pending) view.
                SyncedLearnerTracker syncedAckSet = new SyncedLearnerTracker();
                syncedAckSet.addQuorumVerifier(self.getQuorumVerifier());
                if (self.getLastSeenQuorumVerifier() != null
                    && self.getLastSeenQuorumVerifier().getVersion() > self.getQuorumVerifier().getVersion()) {
                    syncedAckSet.addQuorumVerifier(self.getLastSeenQuorumVerifier());
                }

                syncedAckSet.addAck(self.getMyId());

                for (LearnerHandler f : getLearners()) {
                    if (f.synced()) {
                        syncedAckSet.addAck(f.getSid());
                    }
                }

                // check leader running status
                if (!this.isRunning()) {
                    // set shutdown flag
                    shutdownMessage = "Unexpected internal error";
                    break;
                }

                /*
                 *
                 * We will need to re-validate the outstandingProposal to maintain the progress of ZooKeeper.
                 * It is likely a proposal is waiting for enough ACKs to be committed. The proposals are sent out, but the
                 * only follower goes away which makes the proposals will not be committed until the follower recovers back.
                 * An earlier proposal which is not committed will block any further proposals. So, We need to re-validate those
                 * outstanding proposal with the help from Oracle. A key point in the process of re-validation is that the proposals
                 * need to be processed in order.
                 *
                 * We make the whole method blocking to avoid any possible race condition on outstandingProposal and lastCommitted
                 * as well as to avoid nested synchronization.
                 *
                 * As a more generic approach, we pass the object of forwardingFollowers to QuorumOracleMaj to determine if we need
                 * the help from Oracle.
                 *
                 *
                 * the size of outstandingProposals can be 1. The only one outstanding proposal is the one waiting for the ACK from
                 * the leader itself.
                 * */
                if (!tickSkip && !syncedAckSet.hasAllQuorums()
                    && !(self.getQuorumVerifier().overrideQuorumDecision(getForwardingFollowers()) && self.getQuorumVerifier().revalidateOutstandingProp(this, new ArrayList<>(outstandingProposals.values()), lastCommitted))) {
                    // Lost quorum of last committed and/or last proposed
                    // config, set shutdown flag
                    shutdownMessage = "Not sufficient followers synced, only synced with sids: [ "
                                      + syncedAckSet.ackSetsToString()
                                      + " ]";
                    break;
                }
                tickSkip = !tickSkip;
            }
            for (LearnerHandler f : getLearners()) {
                f.ping();
            }
        }
        if (shutdownMessage != null) {
            shutdown(shutdownMessage);
            // leader goes in looking state
        }
    } finally {
        zk.unregisterJMX(this);
    }
}
```

waitForNewLeaderAck


```java
public void waitForNewLeaderAck(long sid, long zxid) throws InterruptedException {

    synchronized (newLeaderProposal.qvAcksetPairs) {

        if (quorumFormed) {
            return;
        }

        long currentZxid = newLeaderProposal.packet.getZxid();
        if (zxid != currentZxid) {
            LOG.error(
                    "NEWLEADER ACK from sid: {} is from a different epoch - current 0x{} received 0x{}",
                    sid,
                    Long.toHexString(currentZxid),
                    Long.toHexString(zxid));
            return;
        }

        /*
         * Note that addAck already checks that the learner
         * is a PARTICIPANT.
         */
        newLeaderProposal.addAck(sid);

        if (newLeaderProposal.hasAllQuorums()) {
            quorumFormed = true;
            newLeaderProposal.qvAcksetPairs.notifyAll();
        } else {
            long start = Time.currentElapsedTime();
            long cur = start;
            long end = start + self.getInitLimit() * self.getTickTime();
            while (!quorumFormed && cur < end) {
                newLeaderProposal.qvAcksetPairs.wait(end - cur);
                cur = Time.currentElapsedTime();
            }
            if (!quorumFormed) {
                throw new InterruptedException("Timeout while waiting for NEWLEADER to be acked by quorum");
            }
        }
    }
}
```



通过LearnerHandler进行数据同步



```java
public class LearnerHandler extends ZooKeeperThread {
     @Override
    public void run() {
        try {
            learnerMaster.addLearnerHandler(this);
            tickOfNextAckDeadline = learnerMaster.getTickOfInitialAckDeadline();

            ia = BinaryInputArchive.getArchive(bufferedInput);
            bufferedOutput = new BufferedOutputStream(sock.getOutputStream());
            oa = BinaryOutputArchive.getArchive(bufferedOutput);

            QuorumPacket qp = new QuorumPacket();
            ia.readRecord(qp, "packet");

            messageTracker.trackReceived(qp.getType());
            if (qp.getType() != Leader.FOLLOWERINFO && qp.getType() != Leader.OBSERVERINFO) {
                LOG.error("First packet {} is not FOLLOWERINFO or OBSERVERINFO!", qp.toString());

                return;
            }

            if (learnerMaster instanceof ObserverMaster && qp.getType() != Leader.OBSERVERINFO) {
                throw new IOException("Non observer attempting to connect to ObserverMaster. type = " + qp.getType());
            }
            byte[] learnerInfoData = qp.getData();
            if (learnerInfoData != null) {
                ByteBuffer bbsid = ByteBuffer.wrap(learnerInfoData);
                if (learnerInfoData.length >= 8) {
                    this.sid = bbsid.getLong();
                }
                if (learnerInfoData.length >= 12) {
                    this.version = bbsid.getInt(); // protocolVersion
                }
                if (learnerInfoData.length >= 20) {
                    long configVersion = bbsid.getLong();
                    if (configVersion > learnerMaster.getQuorumVerifierVersion()) {
                        throw new IOException("Follower is ahead of the leader (has a later activated configuration)");
                    }
                }
            } else {
                this.sid = learnerMaster.getAndDecrementFollowerCounter();
            }

            String followerInfo = learnerMaster.getPeerInfo(this.sid);
            if (followerInfo.isEmpty()) {
                LOG.info(
                    "Follower sid: {} not in the current config {}",
                    this.sid,
                    Long.toHexString(learnerMaster.getQuorumVerifierVersion()));
            } else {
                LOG.info("Follower sid: {} : info : {}", this.sid, followerInfo);
            }

            if (qp.getType() == Leader.OBSERVERINFO) {
                learnerType = LearnerType.OBSERVER;
            }

            learnerMaster.registerLearnerHandlerBean(this, sock);

            long lastAcceptedEpoch = ZxidUtils.getEpochFromZxid(qp.getZxid());

            long peerLastZxid;
            StateSummary ss = null;
            long zxid = qp.getZxid();
            long newEpoch = learnerMaster.getEpochToPropose(this.getSid(), lastAcceptedEpoch);
            long newLeaderZxid = ZxidUtils.makeZxid(newEpoch, 0);

            if (this.getVersion() < 0x10000) {
                // we are going to have to extrapolate the epoch information
                long epoch = ZxidUtils.getEpochFromZxid(zxid);
                ss = new StateSummary(epoch, zxid);
                // fake the message
                learnerMaster.waitForEpochAck(this.getSid(), ss);
            } else {
                byte[] ver = new byte[4];
                ByteBuffer.wrap(ver).putInt(0x10000);
                QuorumPacket newEpochPacket = new QuorumPacket(Leader.LEADERINFO, newLeaderZxid, ver, null);
                oa.writeRecord(newEpochPacket, "packet");
                messageTracker.trackSent(Leader.LEADERINFO);
                bufferedOutput.flush();
                QuorumPacket ackEpochPacket = new QuorumPacket();
                ia.readRecord(ackEpochPacket, "packet");
                messageTracker.trackReceived(ackEpochPacket.getType());
                if (ackEpochPacket.getType() != Leader.ACKEPOCH) {
                    LOG.error("{} is not ACKEPOCH", ackEpochPacket.toString());
                    return;
                }
                ByteBuffer bbepoch = ByteBuffer.wrap(ackEpochPacket.getData());
                ss = new StateSummary(bbepoch.getInt(), ackEpochPacket.getZxid());
                learnerMaster.waitForEpochAck(this.getSid(), ss);
            }
            peerLastZxid = ss.getLastZxid();

            // Take any necessary action if we need to send TRUNC or DIFF
            // startForwarding() will be called in all cases
            boolean needSnap = syncFollower(peerLastZxid, learnerMaster);

            // syncs between followers and the leader are exempt from throttling because it
            // is important to keep the state of quorum servers up-to-date. The exempted syncs
            // are counted as concurrent syncs though
            boolean exemptFromThrottle = getLearnerType() != LearnerType.OBSERVER;
            /* if we are not truncating or sending a diff just send a snapshot */
            if (needSnap) {
                syncThrottler = learnerMaster.getLearnerSnapSyncThrottler();
                syncThrottler.beginSync(exemptFromThrottle);
                ServerMetrics.getMetrics().INFLIGHT_SNAP_COUNT.add(syncThrottler.getSyncInProgress());
                try {
                    long zxidToSend = learnerMaster.getZKDatabase().getDataTreeLastProcessedZxid();
                    oa.writeRecord(new QuorumPacket(Leader.SNAP, zxidToSend, null, null), "packet");
                    messageTracker.trackSent(Leader.SNAP);
                    bufferedOutput.flush();

                    LOG.info(
                        "Sending snapshot last zxid of peer is 0x{}, zxid of leader is 0x{}, "
                            + "send zxid of db as 0x{}, {} concurrent snapshot sync, "
                            + "snapshot sync was {} from throttle",
                        Long.toHexString(peerLastZxid),
                        Long.toHexString(leaderLastZxid),
                        Long.toHexString(zxidToSend),
                        syncThrottler.getSyncInProgress(),
                        exemptFromThrottle ? "exempt" : "not exempt");
                    // Dump data to peer
                    learnerMaster.getZKDatabase().serializeSnapshot(oa);
                    oa.writeString("BenWasHere", "signature");
                    bufferedOutput.flush();
                } finally {
                    ServerMetrics.getMetrics().SNAP_COUNT.add(1);
                }
            } else {
                syncThrottler = learnerMaster.getLearnerDiffSyncThrottler();
                syncThrottler.beginSync(exemptFromThrottle);
                ServerMetrics.getMetrics().INFLIGHT_DIFF_COUNT.add(syncThrottler.getSyncInProgress());
                ServerMetrics.getMetrics().DIFF_COUNT.add(1);
            }

            LOG.debug("Sending NEWLEADER message to {}", sid);
            // the version of this quorumVerifier will be set by leader.lead() in case
            // the leader is just being established. waitForEpochAck makes sure that readyToStart is true if
            // we got here, so the version was set
            if (getVersion() < 0x10000) {
                QuorumPacket newLeaderQP = new QuorumPacket(Leader.NEWLEADER, newLeaderZxid, null, null);
                oa.writeRecord(newLeaderQP, "packet");
            } else {
                QuorumPacket newLeaderQP = new QuorumPacket(Leader.NEWLEADER, newLeaderZxid, learnerMaster.getQuorumVerifierBytes(), null);
                queuedPackets.add(newLeaderQP);
            }
            bufferedOutput.flush();

            // Start thread that blast packets in the queue to learner
            startSendingPackets();

            /*
             * Have to wait for the first ACK, wait until
             * the learnerMaster is ready, and only then we can
             * start processing messages.
             */
            qp = new QuorumPacket();
            ia.readRecord(qp, "packet");

            messageTracker.trackReceived(qp.getType());
            if (qp.getType() != Leader.ACK) {
                LOG.error("Next packet was supposed to be an ACK, but received packet: {}", packetToString(qp));
                return;
            }

            LOG.debug("Received NEWLEADER-ACK message from {}", sid);

            learnerMaster.waitForNewLeaderAck(getSid(), qp.getZxid());

            syncLimitCheck.start();
            // sync ends when NEWLEADER-ACK is received
            syncThrottler.endSync();
            if (needSnap) {
                ServerMetrics.getMetrics().INFLIGHT_SNAP_COUNT.add(syncThrottler.getSyncInProgress());
            } else {
                ServerMetrics.getMetrics().INFLIGHT_DIFF_COUNT.add(syncThrottler.getSyncInProgress());
            }
            syncThrottler = null;

            // now that the ack has been processed expect the syncLimit
            sock.setSoTimeout(learnerMaster.syncTimeout());

            /*
             * Wait until learnerMaster starts up
             */
            learnerMaster.waitForStartup();

            // Mutation packets will be queued during the serialize,
            // so we need to mark when the peer can actually start
            // using the data
            //
            LOG.debug("Sending UPTODATE message to {}", sid);
            queuedPackets.add(new QuorumPacket(Leader.UPTODATE, -1, null, null));

            while (true) {
                qp = new QuorumPacket();
                ia.readRecord(qp, "packet");
                messageTracker.trackReceived(qp.getType());

                if (LOG.isTraceEnabled()) {
                    long traceMask = ZooTrace.SERVER_PACKET_TRACE_MASK;
                    if (qp.getType() == Leader.PING) {
                        traceMask = ZooTrace.SERVER_PING_TRACE_MASK;
                    }
                    ZooTrace.logQuorumPacket(LOG, traceMask, 'i', qp);
                }
                tickOfNextAckDeadline = learnerMaster.getTickOfNextAckDeadline();

                packetsReceived.incrementAndGet();

                ByteBuffer bb;
                long sessionId;
                int cxid;
                int type;

                switch (qp.getType()) {
                case Leader.ACK:
                    if (this.learnerType == LearnerType.OBSERVER) {
                        LOG.debug("Received ACK from Observer {}", this.sid);
                    }
                    syncLimitCheck.updateAck(qp.getZxid());
                    learnerMaster.processAck(this.sid, qp.getZxid(), sock.getLocalSocketAddress());
                    break;
                case Leader.PING:
                    // Process the touches
                    ByteArrayInputStream bis = new ByteArrayInputStream(qp.getData());
                    DataInputStream dis = new DataInputStream(bis);
                    while (dis.available() > 0) {
                        long sess = dis.readLong();
                        int to = dis.readInt();
                        learnerMaster.touch(sess, to);
                    }
                    break;
                case Leader.REVALIDATE:
                    ServerMetrics.getMetrics().REVALIDATE_COUNT.add(1);
                    learnerMaster.revalidateSession(qp, this);
                    break;
                case Leader.REQUEST:
                    bb = ByteBuffer.wrap(qp.getData());
                    sessionId = bb.getLong();
                    cxid = bb.getInt();
                    type = bb.getInt();
                    bb = bb.slice();
                    Request si;
                    if (type == OpCode.sync) {
                        si = new LearnerSyncRequest(this, sessionId, cxid, type, RequestRecord.fromBytes(bb), qp.getAuthinfo());
                    } else {
                        si = new Request(null, sessionId, cxid, type, RequestRecord.fromBytes(bb), qp.getAuthinfo());
                    }
                    si.setOwner(this);
                    learnerMaster.submitLearnerRequest(si);
                    requestsReceived.incrementAndGet();
                    break;
                default:
                    LOG.warn("unexpected quorum packet, type: {}", packetToString(qp));
                    break;
                }
            }
        } catch (IOException e) {
            LOG.error("Unexpected exception in LearnerHandler: ", e);
            closeSocket();
        } catch (InterruptedException e) {
            LOG.error("Unexpected exception in LearnerHandler.", e);
        } catch (SyncThrottleException e) {
            LOG.error("too many concurrent sync.", e);
            syncThrottler = null;
        } catch (Exception e) {
            LOG.error("Unexpected exception in LearnerHandler.", e);
            throw e;
        } finally {
            if (syncThrottler != null) {
                syncThrottler.endSync();
                syncThrottler = null;
            }
            String remoteAddr = getRemoteAddress();
            LOG.warn("******* GOODBYE {} ********", remoteAddr);
            messageTracker.dumpToLog(remoteAddr);
            shutdown();
        }
    }
}
```





#### syncFollower

When leader election is completed, the leader will set its lastProcessedZxid to be (epoch < 32). There will be no txn associated with this zxid.
The learner will set its lastProcessedZxid to the same value if it get DIFF or SNAP from the learnerMaster. If the same learner come back to sync with learnerMaster using this zxid, we will never find this zxid in our history. In this case, we will ignore TRUNC logic and always send DIFF if we have old enough history


```java
boolean syncFollower(long peerLastZxid, LearnerMaster learnerMaster) {
        boolean isPeerNewEpochZxid = (peerLastZxid & 0xffffffffL) == 0;
        // Keep track of the latest zxid which already queued
        long currentZxid = peerLastZxid;
        boolean needSnap = true;
        ZKDatabase db = learnerMaster.getZKDatabase();
        boolean txnLogSyncEnabled = db.isTxnLogSyncEnabled();
        ReentrantReadWriteLock lock = db.getLogLock();
        ReadLock rl = lock.readLock();
        try {
            rl.lock();
            long maxCommittedLog = db.getmaxCommittedLog();
            long minCommittedLog = db.getminCommittedLog();
            long lastProcessedZxid = db.getDataTreeLastProcessedZxid();

            LOG.info("Synchronizing with Learner sid: {} maxCommittedLog=0x{}"
                     + " minCommittedLog=0x{} lastProcessedZxid=0x{}"
                     + " peerLastZxid=0x{}",
                     getSid(),
                     Long.toHexString(maxCommittedLog),
                     Long.toHexString(minCommittedLog),
                     Long.toHexString(lastProcessedZxid),
                     Long.toHexString(peerLastZxid));

            if (db.getCommittedLog().isEmpty()) {
                /*
                 * It is possible that committedLog is empty. In that case
                 * setting these value to the latest txn in learnerMaster db
                 * will reduce the case that we need to handle
                 *
                 * Here is how each case handle by the if block below
                 * 1. lastProcessZxid == peerZxid -> Handle by (2)
                 * 2. lastProcessZxid < peerZxid -> Handle by (3)
                 * 3. lastProcessZxid > peerZxid -> Handle by (5)
                 */
                minCommittedLog = lastProcessedZxid;
                maxCommittedLog = lastProcessedZxid;
            }

            /*
             * Here are the cases that we want to handle
             *
             * 1. Force sending snapshot (for testing purpose)
             * 2. Peer and learnerMaster is already sync, send empty diff
             * 3. Follower has txn that we haven't seen. This may be old leader
             *    so we need to send TRUNC. However, if peer has newEpochZxid,
             *    we cannot send TRUNC since the follower has no txnlog
             * 4. Follower is within committedLog range or already in-sync.
             *    We may need to send DIFF or TRUNC depending on follower's zxid
             *    We always send empty DIFF if follower is already in-sync
             * 5. Follower missed the committedLog. We will try to use on-disk
             *    txnlog + committedLog to sync with follower. If that fail,
             *    we will send snapshot
             */

            if (forceSnapSync) {
                // Force learnerMaster to use snapshot to sync with follower
                LOG.warn("Forcing snapshot sync - should not see this in production");
            } else if (lastProcessedZxid == peerLastZxid) {
                // Follower is already sync with us, send empty diff
                LOG.info(
                    "Sending DIFF zxid=0x{} for peer sid: {}",
                    Long.toHexString(peerLastZxid),
                    getSid());
                queueOpPacket(Leader.DIFF, peerLastZxid);
                needOpPacket = false;
                needSnap = false;
            } else if (peerLastZxid > maxCommittedLog && !isPeerNewEpochZxid) {
                // Newer than committedLog, send trunc and done
                LOG.debug(
                    "Sending TRUNC to follower zxidToSend=0x{} for peer sid:{}",
                    Long.toHexString(maxCommittedLog),
                    getSid());
                queueOpPacket(Leader.TRUNC, maxCommittedLog);
                currentZxid = maxCommittedLog;
                needOpPacket = false;
                needSnap = false;
            } else if ((maxCommittedLog >= peerLastZxid) && (minCommittedLog <= peerLastZxid)) {
                // Follower is within commitLog range
                LOG.info("Using committedLog for peer sid: {}", getSid());
                Iterator<Proposal> itr = db.getCommittedLog().iterator();
                currentZxid = queueCommittedProposals(itr, peerLastZxid, null, maxCommittedLog);
                needSnap = false;
            } else if (peerLastZxid < minCommittedLog && txnLogSyncEnabled) {
                // Use txnlog and committedLog to sync

                // Calculate sizeLimit that we allow to retrieve txnlog from disk
                long sizeLimit = db.calculateTxnLogSizeLimit();
                // This method can return empty iterator if the requested zxid
                // is older than on-disk txnlog
                Iterator<Proposal> txnLogItr = db.getProposalsFromTxnLog(peerLastZxid, sizeLimit);
                if (txnLogItr.hasNext()) {
                    LOG.info("Use txnlog and committedLog for peer sid: {}", getSid());
                    currentZxid = queueCommittedProposals(txnLogItr, peerLastZxid, minCommittedLog, maxCommittedLog);

                    if (currentZxid < minCommittedLog) {
                        LOG.info(
                            "Detected gap between end of txnlog: 0x{} and start of committedLog: 0x{}",
                            Long.toHexString(currentZxid),
                            Long.toHexString(minCommittedLog));
                        currentZxid = peerLastZxid;
                        // Clear out currently queued requests and revert
                        // to sending a snapshot.
                        queuedPackets.clear();
                        needOpPacket = true;
                    } else {
                        LOG.debug("Queueing committedLog 0x{}", Long.toHexString(currentZxid));
                        Iterator<Proposal> committedLogItr = db.getCommittedLog().iterator();
                        currentZxid = queueCommittedProposals(committedLogItr, currentZxid, null, maxCommittedLog);
                        needSnap = false;
                    }
                }
                // closing the resources
                if (txnLogItr instanceof TxnLogProposalIterator) {
                    TxnLogProposalIterator txnProposalItr = (TxnLogProposalIterator) txnLogItr;
                    txnProposalItr.close();
                }
            } else {
                LOG.warn(
                    "Unhandled scenario for peer sid: {} maxCommittedLog=0x{}"
                        + " minCommittedLog=0x{} lastProcessedZxid=0x{}"
                        + " peerLastZxid=0x{} txnLogSyncEnabled={}",
                    getSid(),
                    Long.toHexString(maxCommittedLog),
                    Long.toHexString(minCommittedLog),
                    Long.toHexString(lastProcessedZxid),
                    Long.toHexString(peerLastZxid),
                    txnLogSyncEnabled);
            }
            if (needSnap) {
                currentZxid = db.getDataTreeLastProcessedZxid();
            }

            LOG.debug("Start forwarding 0x{} for peer sid: {}", Long.toHexString(currentZxid), getSid());
            leaderLastZxid = learnerMaster.startForwarding(this, currentZxid);
        } finally {
            rl.unlock();
        }

        if (needOpPacket && !needSnap) {
            // This should never happen, but we should fall back to sending
            // snapshot just in case.
            LOG.error("Unhandled scenario for peer sid: {} fall back to use snapshot",  getSid());
            needSnap = true;
        }

        return needSnap;
    }
```









### failover election

当 ZooKeeper 集群中的 Leader 服务器发生崩溃时，集群会暂停处理事务性的会话请求，直到 ZooKeeper 集群中选举出新的 Leader 服务器。

在 ZooKeeper 集群服务运行的过程中，集群中每台服务器的角色已经确定了，当 Leader 服务器崩溃后 ，ZooKeeper 集群中的其他服务器会首先将自身的状态信息变为 LOOKING 状态，该状态表示服务器已经做好选举新 Leader 服务器的准备了，这之后整个 ZooKeeper 集群开始进入选举新的 Leader 服务器过程。




[Reassign `ZXID` for solving 32bit overflow problem](https://issues.apache.org/jira/browse/ZOOKEEPER-2789)
1. I am worry about if the lower 8 bits of the upper 32 bits are divided into the low 32 bits of the entire `long` and become 40 bits low, there may be a concurrent problem.
   Actually, it shouldn't be worried, all operation about `ZXID` is bit operation rather than `=` assignment operation.
   So, it cann't be a concurrent problem in `JVM` level.
2. Yep, it is. Especially, if it is `1k/s` ops, then as long as $2^ {32} / (86400 * 1000) \approx 49.7$ days `ZXID` will exhausted. 
   And more terrible situation will make the `re-election` process comes early.
   At the same time, the "re-election" process could take half a minute. And it will be cannot acceptable.
3. As so far, it will throw a `XidRolloverException` to force `re-election` process and reset the `counter` to zero



```java
    public enum ServerState {
        LOOKING,
        FOLLOWING,
        LEADING,
        OBSERVING
    }
```
Follower发现Leader失活后会从follower.followLeader()的阻塞中退出
```java
@Override
public void run() {
    while (running) {
        if (unavailableStartTime == 0) {
            unavailableStartTime = Time.currentElapsedTime();
        }

        switch (getPeerState()) {
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
        }
    }
}
```
## Broadcast



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

Responsible for performing local session upgrade. Only request submitted directly to the leader should go through this processor.

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

## Links

- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Consensus](/docs/CS/Distributed/Consensus.md)

## References

1. [Zab: High-performance broadcast for primary-backup systems](https://marcoserafini.github.io/papers/zab.pdf)
2. [ZooKeeper’s atomic broadcast protocol:Theory and practice](http://www.tcs.hut.fi/Studies/T-79.5001/reports/2012-deSouzaMedeiros.pdf)
3. [A simple totally ordered broadcast protocol](https://www.datadoghq.com/pdf/zab.totally-ordered-broadcast-protocol.2008.pdf)
