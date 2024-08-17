## Introduction



```shell
git clone https://github.com/apache/zookeeper.git

mvn clean install -DskipTest
```

拷贝conf目录下的zoo_smaple.cfg to zoo.cfg

拷贝conf目录下logback.xml到resources下


启动类配置参数 zoo.cfg

直接启动类找不到的话 对provide的依赖 注释provide

## Start

通过zkServer.sh启动ZooKeeper时，应用的统一入口为QuorumPeerMain。此处Quorum的含义是“保证数据冗余和最终一致的机制”，Peer表示集群中的一个平等地位节点

### initializeAndRun

```java
@InterfaceAudience.Public
public class QuorumPeerMain {

    private static final Logger LOG = LoggerFactory.getLogger(QuorumPeerMain.class);

    private static final String USAGE = "Usage: QuorumPeerMain configfile";

    protected QuorumPeer quorumPeer;

   protected void initializeAndRun(String[] args) throws ConfigException, IOException, AdminServerException {
        // 使用配置文件解析
        QuorumPeerConfig config = new QuorumPeerConfig();
        if (args.length == 1) {
            config.parse(args[0]);
        }

        // Start and schedule the the purge task
        DatadirCleanupManager purgeMgr = new DatadirCleanupManager(
            config.getDataDir(),
            config.getDataLogDir(),
            config.getSnapRetainCount(),
            config.getPurgeInterval());
        purgeMgr.start();

        if (args.length == 1 && config.isDistributed()) {
            runFromConfig(config);
        } else {
            LOG.warn("Either no config or no quorum defined in config, running in standalone mode");
            // there is only server in the quorum -- run as standalone
            ZooKeeperServerMain.main(args);
        }
    }
}
```
QuorumPeerMain会做一个判断，当使用配置文件(args.length == 1)且是集群配置的情况下，启动集群形式QuorumPeer，否则启动单机模式ZooKeeperServerMain。

这里还启动了DatadirCleanupManager，用于清理早期的版本快照文件




<!-- tabs:start -->


##### **Quorum**

```java
public class QuorumPeerMain {
    public void runFromConfig(QuorumPeerConfig config) throws IOException, AdminServerException {
        try {
            ManagedUtil.registerLog4jMBeans();
        } catch (JMException e) {
            LOG.warn("Unable to register log4j JMX control", e);
        }

        LOG.info("Starting quorum peer, myid=" + config.getServerId());
        final MetricsProvider metricsProvider;
        try {
            metricsProvider = MetricsProviderBootstrap.startMetricsProvider(
                    config.getMetricsProviderClassName(),
                    config.getMetricsProviderConfiguration());
        } catch (MetricsProviderLifeCycleException error) {
            throw new IOException("Cannot boot MetricsProvider " + config.getMetricsProviderClassName(), error);
        }
        try {
            ServerMetrics.metricsProviderInitialized(metricsProvider);
            ProviderRegistry.initialize();
            ServerCnxnFactory cnxnFactory = null;
            ServerCnxnFactory secureCnxnFactory = null;

            if (config.getClientPortAddress() != null) {
                cnxnFactory = ServerCnxnFactory.createFactory();
                cnxnFactory.configure(config.getClientPortAddress(), config.getMaxClientCnxns(), config.getClientPortListenBacklog(), false);
            }

            if (config.getSecureClientPortAddress() != null) {
                secureCnxnFactory = ServerCnxnFactory.createFactory();
                secureCnxnFactory.configure(config.getSecureClientPortAddress(), config.getMaxClientCnxns(), config.getClientPortListenBacklog(), true);
            }

            quorumPeer = getQuorumPeer();
            quorumPeer.setTxnFactory(new FileTxnSnapLog(config.getDataLogDir(), config.getDataDir()));
            quorumPeer.enableLocalSessions(config.areLocalSessionsEnabled());
            quorumPeer.enableLocalSessionsUpgrading(config.isLocalSessionsUpgradingEnabled());
            //quorumPeer.setQuorumPeers(config.getAllMembers());
            quorumPeer.setElectionType(config.getElectionAlg());
            quorumPeer.setMyid(config.getServerId());
            quorumPeer.setTickTime(config.getTickTime());
            quorumPeer.setMinSessionTimeout(config.getMinSessionTimeout());
            quorumPeer.setMaxSessionTimeout(config.getMaxSessionTimeout());
            quorumPeer.setInitLimit(config.getInitLimit());
            quorumPeer.setSyncLimit(config.getSyncLimit());
            quorumPeer.setConnectToLearnerMasterLimit(config.getConnectToLearnerMasterLimit());
            quorumPeer.setObserverMasterPort(config.getObserverMasterPort());
            quorumPeer.setConfigFileName(config.getConfigFilename());
            quorumPeer.setClientPortListenBacklog(config.getClientPortListenBacklog());
            quorumPeer.setZKDatabase(new ZKDatabase(quorumPeer.getTxnFactory()));
            quorumPeer.setQuorumVerifier(config.getQuorumVerifier(), false);
            if (config.getLastSeenQuorumVerifier() != null) {
                quorumPeer.setLastSeenQuorumVerifier(config.getLastSeenQuorumVerifier(), false);
            }
            quorumPeer.initConfigInZKDatabase();
            quorumPeer.setCnxnFactory(cnxnFactory);
            quorumPeer.setSecureCnxnFactory(secureCnxnFactory);
            quorumPeer.setSslQuorum(config.isSslQuorum());
            quorumPeer.setUsePortUnification(config.shouldUsePortUnification());
            quorumPeer.setLearnerType(config.getPeerType());
            quorumPeer.setSyncEnabled(config.getSyncEnabled());
            quorumPeer.setQuorumListenOnAllIPs(config.getQuorumListenOnAllIPs());
            if (config.sslQuorumReloadCertFiles) {
                quorumPeer.getX509Util().enableCertFileReloading();
            }
            quorumPeer.setMultiAddressEnabled(config.isMultiAddressEnabled());
            quorumPeer.setMultiAddressReachabilityCheckEnabled(config.isMultiAddressReachabilityCheckEnabled());
            quorumPeer.setMultiAddressReachabilityCheckTimeoutMs(config.getMultiAddressReachabilityCheckTimeoutMs());

            // sets quorum sasl authentication configurations
            quorumPeer.setQuorumSaslEnabled(config.quorumEnableSasl);
            if (quorumPeer.isQuorumSaslAuthEnabled()) {
                quorumPeer.setQuorumServerSaslRequired(config.quorumServerRequireSasl);
                quorumPeer.setQuorumLearnerSaslRequired(config.quorumLearnerRequireSasl);
                quorumPeer.setQuorumServicePrincipal(config.quorumServicePrincipal);
                quorumPeer.setQuorumServerLoginContext(config.quorumServerLoginContext);
                quorumPeer.setQuorumLearnerLoginContext(config.quorumLearnerLoginContext);
            }
            quorumPeer.setQuorumCnxnThreadsSize(config.quorumCnxnThreadsSize);
            quorumPeer.initialize();

            if (config.jvmPauseMonitorToRun) {
                quorumPeer.setJvmPauseMonitor(new JvmPauseMonitor(config));
            }

            quorumPeer.start();
            ZKAuditProvider.addZKStartStopAuditLog();
            quorumPeer.join();
        } catch (InterruptedException e) {
            // warn, but generally this is ok
            LOG.warn("Quorum Peer interrupted", e);
        } finally {
            try {
                metricsProvider.stop();
            } catch (Throwable error) {
                LOG.warn("Error while stopping metrics", error);
            }
        }
    }
}
```

##### **ZooKeeperServerMain**

```java
public class ZooKeeperServerMain {
    public static void main(String[] args) {
        ZooKeeperServerMain main = new ZooKeeperServerMain();
        // ...
        main.initializeAndRun(args);
    }

    protected void initializeAndRun(String[] args) throws ConfigException, IOException, AdminServerException {
        ServerConfig config = new ServerConfig();
        if (args.length == 1) {
            config.parse(args[0]);
        } else {
            config.parse(args);
        }

        runFromConfig(config);
    }

    public void runFromConfig(ServerConfig config) throws IOException, AdminServerException {
        LOG.info("Starting server");
        FileTxnSnapLog txnLog = null;
        try {
            try {
                metricsProvider = MetricsProviderBootstrap.startMetricsProvider(
                        config.getMetricsProviderClassName(),
                        config.getMetricsProviderConfiguration());
            } catch (MetricsProviderLifeCycleException error) {
                throw new IOException("Cannot boot MetricsProvider " + config.getMetricsProviderClassName(), error);
            }
            ServerMetrics.metricsProviderInitialized(metricsProvider);
            ProviderRegistry.initialize();
            // Note that this thread isn't going to be doing anything else,
            // so rather than spawning another thread, we will just call
            // run() in this thread.
            // create a file logger url from the command line args
            txnLog = new FileTxnSnapLog(config.dataLogDir, config.dataDir);
            JvmPauseMonitor jvmPauseMonitor = null;
            if (config.jvmPauseMonitorToRun) {
                jvmPauseMonitor = new JvmPauseMonitor(config);
            }
            final ZooKeeperServer zkServer = new ZooKeeperServer(jvmPauseMonitor, txnLog, config.tickTime, config.minSessionTimeout, config.maxSessionTimeout, config.listenBacklog, null, config.initialConfig);
            txnLog.setServerStats(zkServer.serverStats());

            // Registers shutdown handler which will be used to know the
            // server error or shutdown state changes.
            final CountDownLatch shutdownLatch = new CountDownLatch(1);
            zkServer.registerServerShutdownHandler(new ZooKeeperServerShutdownHandler(shutdownLatch));

            // Start Admin server
            adminServer = AdminServerFactory.createAdminServer();
            adminServer.setZooKeeperServer(zkServer);
            adminServer.start();

            boolean needStartZKServer = true;
            if (config.getClientPortAddress() != null) {
                cnxnFactory = ServerCnxnFactory.createFactory();
                cnxnFactory.configure(config.getClientPortAddress(), config.getMaxClientCnxns(), config.getClientPortListenBacklog(), false);
                cnxnFactory.startup(zkServer);
                // zkServer has been started. So we don't need to start it again in secureCnxnFactory.
                needStartZKServer = false;
            }
            if (config.getSecureClientPortAddress() != null) {
                secureCnxnFactory = ServerCnxnFactory.createFactory();
                secureCnxnFactory.configure(config.getSecureClientPortAddress(), config.getMaxClientCnxns(), config.getClientPortListenBacklog(), true);
                secureCnxnFactory.startup(zkServer, needStartZKServer);
            }

            containerManager = new ContainerManager(
                    zkServer.getZKDatabase(),
                    zkServer.firstProcessor,
                    Integer.getInteger("znode.container.checkIntervalMs", (int) TimeUnit.MINUTES.toMillis(1)),
                    Integer.getInteger("znode.container.maxPerMinute", 10000),
                    Long.getLong("znode.container.maxNeverUsedIntervalMs", 0)
            );
            containerManager.start();
            ZKAuditProvider.addZKStartStopAuditLog();

            serverStarted();

            // Watch status of ZooKeeper server. It will do a graceful shutdown
            // if the server is not running or hits an internal error.
            shutdownLatch.await();

            shutdown();

            if (cnxnFactory != null) {
                cnxnFactory.join();
            }
            if (secureCnxnFactory != null) {
                secureCnxnFactory.join();
            }
            if (zkServer.canShutdown()) {
                zkServer.shutdown(true);
            }
        } catch (InterruptedException e) {
            // warn, but generally this is ok
            LOG.warn("Server interrupted", e);
        } finally {
            if (txnLog != null) {
                txnLog.close();
            }
            if (metricsProvider != null) {
                try {
                    metricsProvider.stop();
                } catch (Throwable error) {
                    LOG.warn("Error while stopping metrics", error);
                }
            }
        }
    }
}
```

<!-- tabs:end -->



### QuorumPeer

QuorumPeer类型继承了ZooKeeperThread，而ZookeeperThread类型继承了Thread 也就是说QuorumPeer其实是一个线程类型

QuorumPeer重写了start方法在 线程启动之前执行了一些初始化操作 QuorumPeer类型中 重写了start方法主要步骤如下:
- 将数据从 磁盘加载到内存 中，并将事务添加到内存中的committedlog中。
- 服务端 开启连接线程
- 开启 管理端
- 开启 选举功能
- 开启 JVM监控
- QuorumPeer线程启动 ,开始进行逻辑处理


```java
public class QuorumPeer extends ZooKeeperThread implements QuorumStats.Provider {
    @Override
    public synchronized void start() {
        if (!getView().containsKey(myid)) {
            throw new RuntimeException("My id " + myid + " not in the peer list");
        }
        loadDataBase();
        startServerCnxnFactory();
        try {
            adminServer.start();
        } catch (AdminServerException e) {
            LOG.warn("Problem starting AdminServer", e);
        }
        startLeaderElection();
        startJvmPauseMonitor();
        super.start();
    }
}
```





FileTxnSnapLog是ZooKeeper上层服务于底层数据存储之间的对接层，提供了一系列操作数据文件的接口。包括事务日志文件和快照数据文件。根据dataDir和snapDir来创建FileTxnSnapLog。







创建CountDownLatch，用来watch zk的状态，当zk关闭或者出现内部错误的时候优雅的关闭服务 ZooKeeperServerShutdownHandler是zk用于处理异常的组件。当系统发生错误时，会使用CountDownLatch通知其他线程停止工作


AdminServer用来管理ZooKeeperServer。有两种实现方式JettyAdminServer和DummyAdminServer。当zookeeper.admin.enableServer为true时才启动AdminServer，通过反射的方式创建实例
AdminServer是3.5.0版本中新增特性，是一个内置的Jettry服务，它提供了一个HTTP接口为四字母单词命令。默认的，服务被启动在8080端口，并且命令被发起通过URL "/commands/[command name]",例如，http://localhost:8080/commands/stat。命令响应以JSON的格式返回。不像原来的协议，命令不是限制为四字母的名字，并且命令可以有多个名字。例如"stmk"可以被指定为"set_trace_mask"。为了查看所有可用命令的列表，指向一个浏览器的URL/commands (例如， http://localhost:8080/commands)。
AdminServer默认开启，但是可以被关闭通过下面的方法：
- 设置系统属性zookeeper.admin.enableServer为false.
- 从类路径中移除Jetty.(这个选项是有用的如果你想覆盖ZooKeeper的jetty依赖)。注意TCP四字母单词接口是仍然可用的如果AdminServer被关闭


启动zkserver


早期版本，都是自己实现NIO框架，从3.4.0版本引入了Netty，可以通过zookeeper.serverCnxnFactory来指定使用NIO还是Netty作为Zookeeper服务端网络连接工厂。注：还会根据是否配置了安全，决定是否安全的启动zk服务器


cnxnFactory.startup(zkServer)，启动zk服务器


从本地快照和事务日志文件中进行数据恢复


创建会话管理器SessionTracker，SessionTracker主要负责ZooKeeper服务端的会话管理，创建SessionTracker时，会设置expireInterval、NextExpirationTime和SessionWithTimeout，还会计算出一个初始化的SessionID


请求处理 典型的责任链方式实现，在ZooKeeper服务器上，会有多个请求处理器一次来处理一个客户端请求，在服务器启动的时候，会将这些请求处理器串联起来形成一个请求处理链。单机版服务器的请求处理链主要包括PrepRequestProcessor、SyncRequestProcessor、FinalRequestProcessor

创建定时清除容器节点管理器，用于处理容器节点下不存在子节点的清理容器节点工作等


Zookeeper服务主要由几大部分组成，请求处理器，原子广播，可复制的数据库等组件组成主要的请求处理如下图所示

| 类型 | 	说明                                                                                                                          |
| --- |------------------------------------------------------------------------------------------------------------------------------|
| 可复制的数据库 | 	可复制的数据库是一个包含整个数据树的内存数据库，更新被记录到磁盘上以保证可恢复性，写操作在更新内存数据库之前会先将数据序列化到磁盘来做持久化。                                                     |
| 读请求处理 | 	客户端只连接到一个服务器来提交请求。读取请求由每个服务器数据库本地副本提供服务。                                                                                    |
| 写请求处理 | 	作为协议的一部分，所有来自客户端的写请求都被转发到一个名为leader的服务器上,Zookeeper上的其他服务器角色，被称为Follower或者Observer,Follower参与投票并与Leader脸色同步，Observer是不参与投票的。 |
| 自定义的原子消息协议 |                                                                                                                              |


Zookeeper被设计成 高性能 的，在 读的数量超过写 的应用程序中性能会更好，写操作 还涉及到其他操作比如 同步所有服务器的状态 ，而读操作则可以直接读取内存中数据。
Zoookeeper的吞吐量 受写操作的影响 ，随着读写比的变化而变化


session


Zookeeper服务器启动后可以监听客户端的连接:
- 建立会话： Zookeeper客户端建立通过创建服务句柄来建立与Zookeeper的会话，
- CONNECTING状态： 句柄创建后状态切换至CONNECTING状态，开始尝试连接到组成Zookeeper服务的其中一个服务器，
- CONNECTED状态： 然后切换到CONNECTED状态，如果连接成功则切换到CONNECTED状态
- CLOSED状态： 如果发生了不可恢复的错误，例如会话过期或身份验证失败，或者应用程序显式的关闭了句柄，则将切换到CLOSED状态

当客户端(会话)从ZK服务集群中分区时，它将开始搜索在会话创建期间指定的服务器列表。
最终，当客户端和至少一个服务器之间的连接重新建立时，会话将再次转换到“已连接”状态(如果在会话超时值内重新连接)，或者转换到“过期”状态(如果在会话超时后重新连接)。
不建议在断开连接时创建一个新的会话对象(一个新的zookeeper .class或c绑定中的zookeeper句柄)。 ZK客户端库将为您处理重新连接。特别地，我们在客户端库中内置了启发式来处理“群体效应”等事情。仅在收到会话过期通知时才创建新会话(强制

Session过期由ZooKeeper集群本身管理 ，而不是由客户端管理。 当ZK客户机与集群建立会话时，它会提供上面详细描述的“超时”值。集群使用此值来确定客户端会话何时过期。
当集群在指定的会话超时时间内没有收到来自客户机的消息(即没有心跳)时，就会发生失效。

在会话到期时，集群将删除该会话拥有的任何/所有临时节点，并立即通知任何/所有连接的客户端(任何监视这些znode的人)。


此时，过期会话的客户端仍然与集群断开连接，它将不会收到会话过期的通知，直到/除非它能够重新建立到集群的连接。客户端将保持断开连接状态，
直到TCP连接与集群重新建立，此时过期会话的观察者将收到“会话过期”通知。 会话通过客户端发送的请求保持活跃 。
如果会话空闲了一段时间，将使会话超时，客户端将发送一个PING请求以使会话保持活跃。
这个PING请求不仅可以让ZooKeeper服务器知道客户端仍然处于活动状态，还可以让客户端验证自己与ZooKeeper服务器的连接是否仍然处于活动状态。
PING的时间足够保守，以确保有合理的时间检测死连接并重新连接到新的服务器。 客户端通过逗号分隔的host:port列表字符串来连接zookeeper，每条信息对应一个ZooKeeper服务器。
该函数调用一个 概率负载平衡算法 ，该算法可能导致客户机断开与当前主机的连接，目标是在新列表中实现每个服务器的预期统一连接数。

如果客户端连接到的当前主机不在新列表中，此调用将始终导致连接被删除。否则，决策取决于服务器的数量是增加了还是减少了，以及减少了多少









## Leader Election

This class manages the quorum protocol. There are three states this server can be in:
1. Leader election - each server will elect a leader (proposing itself as a leader initially).
2. Follower - the server will synchronize with the leader and replicate any transactions.


This class will setup a datagram socket that will always respond with its view of the current leader. The response will take the form of:
   int xid;
   long myid;
   long leader_id;
   long leader_zxid;


The request for the current leader will consist solely of an xid: int xid


启动时候从磁盘加载数据到内存，然后开启服务端的网络处理服务，然后开启一个管理端，接下来就进入比较重要的选举功能
startLeaderElection

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
ZK节点状态角色 ZK集群单节点状态（每个节点有且只有一个状态），ZK的定位一定需要一个leader节点处于lading状态。
● looking：寻找leader状态，当前集群没有leader，进入leader选举流程。
● following：跟随者状态，接受leading节点同步和指挥。
● leading：领导者状态。
● observing：观察者状态，表名当前服务器是observer。




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
● “0”表示使用 原生的UDP（LeaderElection），
● “1”表示使用 非授权UDP
● “2”表示 授权UDP
● “3”基于 TCP的快速选举（FastLeaderElection）

目前保留“3”，其他方式将在未来版本不予支持，参QuorumPear.createElectionAlgorithm（int alg）

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
创建对象完毕之后则将QuorumCnxManager对象存入成员变量AtomicReference中用于跨线程可见

Listener内部线程的run方法如下用于启动监听端口，监听其他server的连接与数据传输



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
- Messenger类型对象通过内部的WorkerSender和WorkerReceiver线程来处理需要发送和需要接收的消息然后将消息放入发送队列(queueSendMap中sid对应的发送队列)或者从接收队列recvQueue中获取消息进行处理 



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

```java

FastLeaderElection fle = new FastLeaderElection(this, qcm);
fle.start();

void start() {
    this.wsThread.start();
    this.wrThread.start();
}
```
启动了用于接收和发送数据使用的WorkerSender线程和WorkerReceiver线程,是否需要投票还需要根据当前集群的一个状态来看,在 QuorumPeer 最后一步启动的时候会进行状态判断发起投票. 发送和接收的详细内容待会在看 WorkerSender数据传输层 这个发送类型主要做中间层将需要发送的消息转换成ByteBuffer ,然后调用QuorumCnxManager的toSend方法来发送消息

### Sender


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

WorkerReceiver类型主要作用是解析来自远端的消息,并对消息内容做处理

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
## issue


线上 flink 用户使用 ZooKeeper 做元数据中心以及集群选主，一些版本的 flink 在 ZooKeeper 选主时，会重启 Job，导致一些非预期的业务损失。而 ZooKeeper 在 zxid溢出时，会主动触发一次选主，就会导致 flink Job 的非预期重启，造成业务损失。本篇从原理和最佳实践上分析和解决由于 ZooKeeper zxid 溢出导致的集群选主问题。检查 ZooKeeper Server 日志出现

```
zxid lower 32 bits have rolled over, forcing re-election, and therefore new epoch start
```

ZooKeeper 本身提供当前处理的最大的 Zxid，通过 stat 接口可查看到当前处理的最大的 zxid 的值，通过此值可以计算当前 zxid 距离溢出值还有多少差距。

xid 是 ZooKeeper 中一个事务的全局唯一 id，通过 zxid 描述各个事务之间的全序关系。客户端对 ZooKeeper 内部数据的变更都是通过事务在 ZooKeeper 集群内的传播和处理完成的，因此 zxid 就是客户端对数据进行一次变更所产生的事务在全局事务中的一个唯一 id，这个 id 描述了本次变更的事务在全局事务中的位置，并且不会有两个不同的事务拥有相同的 zxid（全序关系）。

zxid 是一个 64bits 的数，有两个部分组成：当前选举周期（epoch，占用高32bits）以及计数部分（counter，占用低32bits），epoch 表示 leader 关系的变化，每当新的集群产生新的leader，都会产生一个新的 epoch表示当前 leader 的选举周期，ZooKeeper  集群选主成功之后保证只会有一个Leader，并且此 Leader 的 epoch 是以前没有使用过的，这就保证了只会有一个 leader 使用本次选举过程中产生的 epoch， 在此基础上，每当客户端对数据进行变更的时候，leader 对产生的事务在当前 counter 的值加一产生新的事务的 zxid，并使用此 zxid 将此事务在集群中进行同步，这样就保证了事务的全序关系

当单个 epoch 中处理的事务过多，以至于当前epoch 对应的 counter 数值超过了 32bits 计数的最大值，如果继续计数 epoch 就会 +1 ， 如果在未来，进行了一次选举，其他的 Server 当选了 leader，但是他产生的新 epoch 可能就会和现在 zxid 中的 epoch 重合，导致不同的事务会有相同的 zxid，破坏了事务之间的全序关系，可能导致脏数据的产生。因此 ZooKeeper 在低 32 位达到最大计数值的时候，就会主动产生一次选主，避免以上问题。

一般情况下使用 ZooKeeper 作为注册配置中心，集群选主对于客户端来说是无感知的，集群选主之后客户端会主动重连恢复，
对于依赖于客户端Disconnected事件的使用场景：例如，Curator Recipes中的LeaderLatch场景，在集群选主时，Server会产生Disconnected事件，表示Client与Server断开了连接。在选主完成之后，Client会通过重连机制重新连接到Server。
在产生Disconnected事件后，LeaderLatch会重新选主（这里的选主是指使用LeaderLatch做集群选主的场景中，重新选择注册上来的其他实例作为主），此时可能会触发业务侧的一些其他逻辑。例如，在Flink 1.14及以下版本使用LeaderLatch作为选主的默认实现，在ZooKeeper集群选主时会导致Flink Job被重启。
在业务的实现中，可通过Curator Recipes中的LeaderSelector替换LeaderLatch的方法，对ZooKeeper短暂的断连做一定的容忍


## Observer

setObserver(makeObserver(logFactory));
观察者是不参与原子广播协议的对等点。 相反，他们会被领导者告知成功的提案。 因此，观察者自然地充当发布提案流的中继点，并可以减轻追随者的一些连接负载。 观察员可以提交提案，但不投票接受。 有关此功能的讨论，请参阅 ZOOKEEPER-368。



## Purge

清理日志和快照文件

DatadirCleanupManager日志清理工具,相关配置如下：
- autopurge.purgeInterval 参数，单位是小时，当填写一个1或更大的整数，则开启，默认是0，或者配置了负数则表示不开启自动清理功能。
- autopurge.snapRetainCount 这个参数和上面的参数搭配使用，这个参数指定了需要保留的文件数目。默认是保留3个

这里start方法中使用了Java的Timer来启动的定时任务来清理
在使用Zookeeper过程中，，会有 dataDir 和 dataLogDir 两个目录，分别用于 snapshot 和 事务日志 的输出 （默认情况下只有dataDir目录，snapshot和事务日志都保存在这个目录中，正常运行过程中，ZK会不断地把快照数据和事务日志输出到这两个目录，并且如果没有人为操作的话，ZK自己是不会清理这些文件的，需要管理员来清理，



具体清理方法主要调用PurgeTxnLog类的purge方法

```java
public class DatadirCleanupManager {

    private PurgeTaskStatus purgeTaskStatus = PurgeTaskStatus.NOT_STARTED;

    private final File snapDir;

    private final File dataLogDir;

    private final int snapRetainCount;

    private final int purgeInterval;

    private Timer timer;
    public DatadirCleanupManager(File snapDir, File dataLogDir, int snapRetainCount, int purgeInterval) {
        this.snapDir = snapDir;
        this.dataLogDir = dataLogDir;
        this.snapRetainCount = snapRetainCount;
        this.purgeInterval = purgeInterval;
        LOG.info("autopurge.snapRetainCount set to {}", snapRetainCount);
        LOG.info("autopurge.purgeInterval set to {}", purgeInterval);
    }
}
```


```java
public void start() {
    if (PurgeTaskStatus.STARTED == purgeTaskStatus) {
        LOG.warn("Purge task is already running.");
        return;
    }
    // Don't schedule the purge task with zero or negative purge interval.
    if (purgeInterval <= 0) {
        LOG.info("Purge task is not scheduled.");
        return;
    }

    timer = new Timer("PurgeTask", true);
    TimerTask task = new PurgeTask(dataLogDir, snapDir, snapRetainCount);
    timer.scheduleAtFixedRate(task, 0, TimeUnit.HOURS.toMillis(purgeInterval));

    purgeTaskStatus = PurgeTaskStatus.STARTED;
}
```

创建清理任务PurgeTask开启定时器以一定间隔时间来执行PurgeTask中的定时任务，定时任务在执行的时候会触发定时任务的run方法

```java
static class PurgeTask extends TimerTask {

    private File logsDir;
    private File snapsDir;
    private int snapRetainCount;

    @Override
    public void run() {
        LOG.info("Purge task started.");
        try {
            PurgeTxnLog.purge(logsDir, snapsDir, snapRetainCount);
        } catch (Exception e) {
            LOG.error("Error occurred while purging.", e);
        }
        LOG.info("Purge task completed.");
    }

}
```


```java
public static void purge(File dataDir, File snapDir, int num) throws IOException {
    if (num < 3) {
        throw new IllegalArgumentException(COUNT_ERR_MSG);
    }

    FileTxnSnapLog txnLog = new FileTxnSnapLog(dataDir, snapDir);

    List<File> snaps = txnLog.findNValidSnapshots(num);
    int numSnaps = snaps.size();
    if (numSnaps > 0) {
        purgeOlderSnapshots(txnLog, snaps.get(numSnaps - 1));
    }
}
```

创建事物快照日志文件对象FileTxnSnapLog，然后根据参数获取获取到需要保留的文件数量， 然后根据保留的文件数量计算出保留文件中最小的那个zxid， 然后根据最小的zxid找到需要保留的事物日志文件列表 (事物日志当前最小的那个id之前的1个不能清理在zookeeper事物日志中可能发生滚动日志之前的文件也是会记录到最新的数据)， 然后过滤所有事物日志文件过滤出来需要删除的事物日志文件， 在过滤所有的快照文件找到所有需要删除的快照文件，最后循环删除需要删除的事物日志和快照文件

```java
public List<File> findNValidSnapshots(int n) {
    FileSnap snaplog = new FileSnap(snapDir);
    return snaplog.findNValidSnapshots(n);
}

protected List<File> findNValidSnapshots(int n) {
        List<File> files = Util.sortDataDir(snapDir.listFiles(), SNAPSHOT_FILE_PREFIX, false);
        int count = 0;
        List<File> list = new ArrayList<>();
        for (File f : files) {
            // we should catch the exceptions
            // from the valid snapshot and continue
            // until we find a valid one
            try {
                if (SnapStream.isValidSnapshot(f)) {
                    list.add(f);
                    count++;
                    if (count == n) {
                        break;
                    }
                }
            } catch (IOException e) {
                LOG.warn("invalid snapshot {}", f, e);
            }
        }
        return list;
    }
```

在处理事物日志和快照的时候，事物日志不能直接删除掉所有比需要保留最小zxid更小的日志文件 ，因为比需要保留最小zxid快照文件的事物日志可能存在于当前最小需要保留zxid的前一个文件中， 也就是说事物日志要比快快照日志多保留一个，这个于日志写入时的滚动机制有关

We delete all files with a zxid in their name that is less than leastZxidToBeRetain. This rule applies to both snapshot files as well as log files, with the following exception for log files.

A log file with zxid less than X may contain transactions with zxid larger than X.  More
precisely, a log file named log.(X-a) may contain transactions newer than snapshot.X if
there are no other log files with starting zxid in the interval (X-a, X].  Assuming the latter condition is true, log.(X-a) must be retained to ensure that snapshot.X is recoverable.  In fact, this log file may very well extend beyond snapshot.X to newer snapshot files if these newer snapshots were not accompanied by log rollover (possible in the learner state machine at the time of this writing).  We can make more precise determination of whether log.(leastZxidToBeRetain-a) for the smallest 'a' is actually needed or not (e.g. not needed if there's a log file named log.(leastZxidToBeRetain+1)), but the complexity quickly adds up with gains only in uncommon scenarios.  It's safe and simple to just preserve log.(leastZxidToBeRetain-a) for the smallest 'a' to ensure recoverability of all snapshots being retained.  We determine that log file here by calling txnLog.getSnapshotLogs().


```java
static void purgeOlderSnapshots(FileTxnSnapLog txnLog, File snapShot) {
    final long leastZxidToBeRetain = Util.getZxidFromName(snapShot.getName(), PREFIX_SNAPSHOT);

    final Set<File> retainedTxnLogs = new HashSet<>();
    retainedTxnLogs.addAll(Arrays.asList(txnLog.getSnapshotLogs(leastZxidToBeRetain)));

    /**
     * Finds all candidates for deletion, which are files with a zxid in their name that is less
     * than leastZxidToBeRetain.  There's an exception to this rule, as noted above.
     */
    class MyFileFilter implements FileFilter {

        private final String prefix;
        MyFileFilter(String prefix) {
            this.prefix = prefix;
        }
        public boolean accept(File f) {
            if (!f.getName().startsWith(prefix + ".")) {
                return false;
            }
            if (retainedTxnLogs.contains(f)) {
                return false;
            }
            long fZxid = Util.getZxidFromName(f.getName(), prefix);
            return fZxid < leastZxidToBeRetain;
        }

    }
    // add all non-excluded log files
    File[] logs = txnLog.getDataLogDir().listFiles(new MyFileFilter(PREFIX_LOG));
    List<File> files = new ArrayList<>();
    if (logs != null) {
        files.addAll(Arrays.asList(logs));
    }

    // add all non-excluded snapshot files to the deletion list
    File[] snapshots = txnLog.getSnapDir().listFiles(new MyFileFilter(PREFIX_SNAPSHOT));
    if (snapshots != null) {
        files.addAll(Arrays.asList(snapshots));
    }

    // remove the old files
    for (File f : files) {
        final String msg = String.format(
            "Removing file: %s\t%s",
            DateFormat.getDateTimeInstance().format(f.lastModified()),
            f.getPath());

        LOG.info(msg);
        System.out.println(msg);

        if (!f.delete()) {
            System.err.println("Failed to remove " + f.getPath());
        }
    }

}
```




## Links

