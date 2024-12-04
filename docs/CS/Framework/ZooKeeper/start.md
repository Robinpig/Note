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

通过zkServer.sh启动ZooKeeper时，应用的统一入口为QuorumPeerMain。
此处Quorum的含义是“保证数据冗余和最终一致的机制”，Peer表示集群中的一个平等地位节点

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

##### **Standalone**

```java
public class ZooKeeperServerMain {
    public static void main(String[] args) {
        ZooKeeperServerMain main = new ZooKeeperServerMain();
        // ...
        main.initializeAndRun(args);
    }
}
```

<!-- tabs:end -->



### QuorumPeer

QuorumPeer类型继承了ZooKeeperThread，而ZookeeperThread类型继承了Thread 也就是说QuorumPeer其实是一个线程类型

QuorumPeerConfig::parse -> setupQuorumPeerConfig -> parseDynamicConfig

针对 Leader 选举关键配置信息如下：
- 读取 dataDir 目录找到 myid 文件内容，设置当前应用 sid 标识，做为投票人身份信息。下面遇到 myid 变量为当前节点自己 sid 标识。
- 设置 peerType 当前应用是否参与选举
- new QuorumMaj() 解析 server.前缀加载集群成员信息，加载 allMembers 所有成员，votingMembers参与选举成员，observingMembers 观察者成员，设置half值为 votingMembers.size()/2.


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





#### loadDataBase

最终 Session 和 数据的恢复，都将在 loadData 方法中完成。ZKServer 首先利用 ZKDatabase#loadDataBase 调用 FileTxnSnapLog#restore 方法，从磁盘中反序列化 100（硬编码了在 findNValidSnapshots(100) 代码里）个有效的 Snapshot 文件，恢复出 DataTree 和 sessionsWithTimeouts 两个数据结构，以便获取到最新有效的 ZXID，并使用 FileTxnSnapLog#processTransaction 方法增量地处理 DataTree 中的事务。随后根据 Session 超时时间，将超时的 Session 从 DataTree#ephemerals 变量（Map<Long: sessionId, HashSet<String>: pathList>）中移除。同时，利用 ZooKeeperServer#takeSnapshot 方法，将 DataTree 实例持久化到磁盘，创建一个全新的 Snapshot 文件

Snapshot 策略
首先，我们可以看到 SyncRequestProcessor 类的 run() 方法中，ZooKeeperServer#takeSnapshot 方法的调用是在一个新起的线程中发起的，因此 Snapshot 流程是异步发起的

另外，在启动 Snapshot 线程之前，通过 𝑙𝑜𝑔𝐶𝑜𝑢𝑛𝑡>(𝑠𝑛𝑎𝑝𝐶𝑜𝑢𝑛𝑡/2+𝑟𝑎𝑛𝑑𝑅𝑜𝑙𝑙) 公式进行计算，是否应该发起 Snapshot（同时会保证前一个 Snapshot 已经结束才会开始）。由此可见 ZooKeeper 的设计巧妙之处，这里加入了 randRoll 随机数，可以降低所有 Server 节点同时发生 Snapshot 的概率，从而避免因 Snapshot 导致服务受影响。因为，Snapshot 的过程会消耗大量的 磁盘 IO、CPU 等资源，所以全部节点同时 Snapshot 会严重影响集群的对外服务能力


按照 ZooKeeperServer 的文档中所示，事务处理的大体流程链应该为 PrepRequestProcessor - SyncRequestProcessor - FinalRequestProcessor

PrepRequestProcessor和SyncRequestProcessor都是一个线程子类，而在实际的ZK服务端运行过程中这两个就是以线程轮询的方式异步执行的
FinalRequestProcessor实现类只实现了RequestProcessor接口，因此这个类的流程是同步的，为什么呢？
因为这个类一般都是处理所有的请求类型，且在RequestProcessor调用链的末尾，没有nextProcessor，因此便不需要像其它的RequestProcessor实现类一样使用线程轮询的方式来处理请求。

其用到的三个重要实现子类功能分别如下：
1. PrepRequestProcessor：RequestProcessor的开始部分，根据请求的参数判断请求的类型，如create、delete操作这些，随后将会创建相应的Record实现子类，进行一些合法性校验以及改动记录；
2. SyncRequestProcessor：同步刷新记录请求到日志，在将请求的日志同步到磁盘之前，不会把请求传递给下一个RequestProcessor；
3. FinalRequestProcessor：为RequestProcessor的末尾处理类，从名字也能看出来，基本上所有的请求都会最后经过这里此类将会处理改动记录以及session记录，最后会根据请求的操作类型更新对象的ServerCnxn对象并回复请求的客户端

以一次ZK Client端向Server端请求创建节点请求为例，ZK的做法是使用一个RequestHeader对象和CreateRequest分别序列化并组合形成一次请求，
到ZK Server端先反序列化RequestHeader获取Client端的请求类型，再根据不同的请求类型使用相应的Request对象反序列化，
这样Server端和Client端就可以完成信息的交互。相应也是一样的步骤，只是RequestHeader变成了ReplyHeader，而Request变成了Response。大致交互图如下

```java
private void loadDataBase() {
        try {
            zkDb.loadDataBase();

            // load the epochs
            long lastProcessedZxid = zkDb.getDataTree().lastProcessedZxid;
            long epochOfZxid = ZxidUtils.getEpochFromZxid(lastProcessedZxid);
            try {
                currentEpoch = readLongFromFile(CURRENT_EPOCH_FILENAME);
            } catch (FileNotFoundException e) {
                // pick a reasonable epoch number
                // this should only happen once when moving to a
                // new code version
                currentEpoch = epochOfZxid;
                LOG.info(
                    "{} not found! Creating with a reasonable default of {}. "
                        + "This should only happen when you are upgrading your installation",
                    CURRENT_EPOCH_FILENAME,
                    currentEpoch);
                writeLongToFile(CURRENT_EPOCH_FILENAME, currentEpoch);
            }
            if (epochOfZxid > currentEpoch) {
                // acceptedEpoch.tmp file in snapshot directory
                File currentTmp = new File(getTxnFactory().getSnapDir(),
                    CURRENT_EPOCH_FILENAME + AtomicFileOutputStream.TMP_EXTENSION);
                if (currentTmp.exists()) {
                    long epochOfTmp = readLongFromFile(currentTmp.getName());
                    LOG.info("{} found. Setting current epoch to {}.", currentTmp, epochOfTmp);
                    setCurrentEpoch(epochOfTmp);
                } else {
                    throw new IOException(
                        "The current epoch, " + ZxidUtils.zxidToString(currentEpoch)
                            + ", is older than the last zxid, " + lastProcessedZxid);
                }
            }
            try {
                acceptedEpoch = readLongFromFile(ACCEPTED_EPOCH_FILENAME);
            } catch (FileNotFoundException e) {
                // pick a reasonable epoch number
                // this should only happen once when moving to a
                // new code version
                acceptedEpoch = epochOfZxid;
                LOG.info(
                    "{} not found! Creating with a reasonable default of {}. "
                        + "This should only happen when you are upgrading your installation",
                    ACCEPTED_EPOCH_FILENAME,
                    acceptedEpoch);
                writeLongToFile(ACCEPTED_EPOCH_FILENAME, acceptedEpoch);
            }
            if (acceptedEpoch < currentEpoch) {
                throw new IOException("The accepted epoch, "
                                      + ZxidUtils.zxidToString(acceptedEpoch)
                                      + " is less than the current epoch, "
                                      + ZxidUtils.zxidToString(currentEpoch));
            }
        } catch (IOException ie) {
            LOG.error("Unable to load database on disk", ie);
            throw new RuntimeException("Unable to run quorum server ", ie);
        }
    }
```

load the database from the disk onto memory and also add the transactions to the committedlog in memory.

```java
public long loadDataBase() throws IOException {
    long startTime = Time.currentElapsedTime();
    long zxid = snapLog.restore(dataTree, sessionsWithTimeouts, commitProposalPlaybackListener);
    initialized = true;
    long loadTime = Time.currentElapsedTime() - startTime;
    ServerMetrics.getMetrics().DB_INIT_TIME.add(loadTime);
    LOG.info("Snapshot loaded in {} ms, highest zxid is 0x{}, digest is {}",
            loadTime, Long.toHexString(zxid), dataTree.getTreeDigest());
    return zxid;
}
```

由FileTxnSnapLog执行restore操作



```java
public long restore(DataTree dt, Map<Long, Integer> sessions, PlayBackListener listener) throws IOException {
    long snapLoadingStartTime = Time.currentElapsedTime();
    long deserializeResult = snapLog.deserialize(dt, sessions);
    ServerMetrics.getMetrics().STARTUP_SNAP_LOAD_TIME.add(Time.currentElapsedTime() - snapLoadingStartTime);
    FileTxnLog txnLog = new FileTxnLog(dataDir);
    boolean trustEmptyDB;
    File initFile = new File(dataDir.getParent(), "initialize");
    if (Files.deleteIfExists(initFile.toPath())) {
        LOG.info("Initialize file found, an empty database will not block voting participation");
        trustEmptyDB = true;
    } else {
        trustEmptyDB = autoCreateDB;
    }

    RestoreFinalizer finalizer = () -> {
        long highestZxid = fastForwardFromEdits(dt, sessions, listener);
        // The snapshotZxidDigest will reset after replaying the txn of the
        // zxid in the snapshotZxidDigest, if it's not reset to null after
        // restoring, it means either there are not enough txns to cover that
        // zxid or that txn is missing
        DataTree.ZxidDigest snapshotZxidDigest = dt.getDigestFromLoadedSnapshot();
        if (snapshotZxidDigest != null) {
            LOG.warn(
                    "Highest txn zxid 0x{} is not covering the snapshot digest zxid 0x{}, "
                            + "which might lead to inconsistent state",
                    Long.toHexString(highestZxid),
                    Long.toHexString(snapshotZxidDigest.getZxid()));
        }
        return highestZxid;
    };

    if (-1L == deserializeResult) {
        /* this means that we couldn't find any snapshot, so we need to
         * initialize an empty database (reported in ZOOKEEPER-2325) */
        if (txnLog.getLastLoggedZxid() != -1) {
            // ZOOKEEPER-3056: provides an escape hatch for users upgrading
            // from old versions of zookeeper (3.4.x, pre 3.5.3).
            if (!trustEmptySnapshot) {
                throw new IOException(EMPTY_SNAPSHOT_WARNING + "Something is broken!");
            } else {
                LOG.warn("{}This should only be allowed during upgrading.", EMPTY_SNAPSHOT_WARNING);
                return finalizer.run();
            }
        }

        if (trustEmptyDB) {
            /* TODO: (br33d) we should either put a ConcurrentHashMap on restore()
             *       or use Map on save() */
            save(dt, (ConcurrentHashMap<Long, Integer>) sessions, false);

            /* return a zxid of 0, since we know the database is empty */
            return 0L;
        } else {
            /* return a zxid of -1, since we are possibly missing data */
            LOG.warn("Unexpected empty data tree, setting zxid to -1");
            dt.lastProcessedZxid = -1L;
            return -1L;
        }
    }

    return finalizer.run();
}
```

先从snapshot恢复数据 再看事务日志是否有未完成的事务
之后再save snapshot

协议位于jute module下

```java
@InterfaceAudience.Public
public interface Record {
    void serialize(OutputArchive archive, String tag) throws IOException;
    void deserialize(InputArchive archive, String tag) throws IOException;
}
```

session

客户端连接 process ConnectRequest

submitRequestNow里 touch session

检测session





### Standalone

单机启动入口是`ZookeeperServerMain.main`

- 首先是解析配置文件 `ServerConfig.parse`
- `initializeAndRun`
  
两个主要的对象 ZooKeeperServer 和 [ServerCnxnFactory](/docs/CS/Framework/ZooKeeper/IO.md)

ServerCnxnFactory.start会调用 ZooKeeperServer.startData

```java
public class ZooKeeperServerMain {

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
            // ...
        } catch (InterruptedException e) {
            // ...
        } 
        // ...
    }
}
```




```java
public class ZooKeeperServer implements SessionExpirer, ServerStats.Provider {
    public void startdata() throws IOException, InterruptedException {
        //check to see if zkDb is not null
        if (zkDb == null) {
            zkDb = new ZKDatabase(this.txnLogFactory);
        }
        if (!zkDb.isInitialized()) {
            loadData();
        }
    }
}
```

这里创建DataTree
```java
public class ZKDatabase {
    public ZKDatabase(FileTxnSnapLog snapLog) {
        dataTree = createDataTree();
        sessionsWithTimeouts = new ConcurrentHashMap<>();
        this.snapLog = snapLog;

        try {
            snapshotSizeFactor = Double.parseDouble(
                    System.getProperty(SNAPSHOT_SIZE_FACTOR,
                            Double.toString(DEFAULT_SNAPSHOT_SIZE_FACTOR)));
            if (snapshotSizeFactor > 1) {
                snapshotSizeFactor = DEFAULT_SNAPSHOT_SIZE_FACTOR;
            }
        } catch (NumberFormatException e) {
            snapshotSizeFactor = DEFAULT_SNAPSHOT_SIZE_FACTOR;
        }

        try {
            commitLogCount = Integer.parseInt(
                    System.getProperty(COMMIT_LOG_COUNT,
                            Integer.toString(DEFAULT_COMMIT_LOG_COUNT)));
            if (commitLogCount < DEFAULT_COMMIT_LOG_COUNT) {
                commitLogCount = DEFAULT_COMMIT_LOG_COUNT;
            }
        } catch (NumberFormatException e) {
            commitLogCount = DEFAULT_COMMIT_LOG_COUNT;
        }
    }
}
```


When a new leader starts executing Leader#lead, it invokes this method. 
The database, however, has been initialized before running leader election so that the server could pick its zxid for its initial vote.
It does it by invoking QuorumPeer#getLastLoggedZxid.
Consequently, we don't need to initialize it once more and avoid the penalty of loading it a second time. 
Not reloading it is particularly important for applications that host a large database.

The following if block checks whether the database has been initialized or not.
Note that this method is invoked by at least one other method: ZooKeeperServer#startdata.

See ZOOKEEPER-1642 for more detail.
 

```java
public class ZooKeeperServer implements SessionExpirer, ServerStats.Provider {
    public void loadData() throws IOException, InterruptedException {
        if (zkDb.isInitialized()) {
            setZxid(zkDb.getDataTreeLastProcessedZxid());
        } else {
            setZxid(zkDb.loadDataBase());
        }

        // Clean up dead sessions
        zkDb.getSessions().stream()
                .filter(session -> zkDb.getSessionWithTimeOuts().get(session) == null)
                .forEach(session -> killSession(session, zkDb.getDataTreeLastProcessedZxid()));

        // Make a clean snapshot
        takeSnapshot();
    }
}
```

load the database from the disk onto memory and also add the transactions to the committedlog in memory. 

```java
public class ZKDatabase {
    public long loadDataBase() throws IOException {
        long startTime = Time.currentElapsedTime();
        long zxid = snapLog.restore(dataTree, sessionsWithTimeouts, commitProposalPlaybackListener);
        initialized = true;
        long loadTime = Time.currentElapsedTime() - startTime;
        ServerMetrics.getMetrics().DB_INIT_TIME.add(loadTime);
        return zxid;
    }
}
```


```java
public class FileTxnSnapLog {
    public long restore(DataTree dt, Map<Long, Integer> sessions, PlayBackListener listener) throws IOException {
        long snapLoadingStartTime = Time.currentElapsedTime();
        long deserializeResult = snapLog.deserialize(dt, sessions);
        ServerMetrics.getMetrics().STARTUP_SNAP_LOAD_TIME.add(Time.currentElapsedTime() - snapLoadingStartTime);
        FileTxnLog txnLog = new FileTxnLog(dataDir);
        boolean trustEmptyDB;
        File initFile = new File(dataDir.getParent(), "initialize");
        if (Files.deleteIfExists(initFile.toPath())) {
            LOG.info("Initialize file found, an empty database will not block voting participation");
            trustEmptyDB = true;
        } else {
            trustEmptyDB = autoCreateDB;
        }

        RestoreFinalizer finalizer = () -> {
            long highestZxid = fastForwardFromEdits(dt, sessions, listener);
            // The snapshotZxidDigest will reset after replaying the txn of the
            // zxid in the snapshotZxidDigest, if it's not reset to null after
            // restoring, it means either there are not enough txns to cover that
            // zxid or that txn is missing
            DataTree.ZxidDigest snapshotZxidDigest = dt.getDigestFromLoadedSnapshot();
            return highestZxid;
        };

        if (-1L == deserializeResult) {
            /* this means that we couldn't find any snapshot, so we need to
             * initialize an empty database (reported in ZOOKEEPER-2325) */
            if (txnLog.getLastLoggedZxid() != -1) {
                // ZOOKEEPER-3056: provides an escape hatch for users upgrading
                // from old versions of zookeeper (3.4.x, pre 3.5.3).
                if (!trustEmptySnapshot) {
                    throw new IOException(EMPTY_SNAPSHOT_WARNING + "Something is broken!");
                } else {
                    LOG.warn("{}This should only be allowed during upgrading.", EMPTY_SNAPSHOT_WARNING);
                    return finalizer.run();
                }
            }

            if (trustEmptyDB) {
                /* TODO: (br33d) we should either put a ConcurrentHashMap on restore()
                 *       or use Map on save() */
                save(dt, (ConcurrentHashMap<Long, Integer>) sessions, false);

                /* return a zxid of 0, since we know the database is empty */
                return 0L;
            } else {
                /* return a zxid of -1, since we are possibly missing data */
                LOG.warn("Unexpected empty data tree, setting zxid to -1");
                dt.lastProcessedZxid = -1L;
                return -1L;
            }
        }

        return finalizer.run();
    }
}
```

save the datatree and the sessions into a snapshot
```java
public class FileTxnSnapLog {
    public File save(
            DataTree dataTree,
            ConcurrentHashMap<Long, Integer> sessionsWithTimeouts,
            boolean syncSnap) throws IOException {
        long lastZxid = dataTree.lastProcessedZxid;
        File snapshotFile = new File(snapDir, Util.makeSnapshotName(lastZxid));
        LOG.info("Snapshotting: 0x{} to {}", Long.toHexString(lastZxid), snapshotFile);
        try {
            snapLog.serialize(dataTree, sessionsWithTimeouts, snapshotFile, syncSnap);
            return snapshotFile;
        } catch (IOException e) {
            if (snapshotFile.length() == 0) {
                /* This may be caused by a full disk. In such a case, the server
                 * will get stuck in a loop where it tries to write a snapshot
                 * out to disk, and ends up creating an empty file instead.
                 * Doing so will eventually result in valid snapshots being
                 * removed during cleanup. */
                if (snapshotFile.delete()) {
                    LOG.info("Deleted empty snapshot file: {}", snapshotFile.getAbsolutePath());
                } else {
                    LOG.warn("Could not delete empty snapshot file: {}", snapshotFile.getAbsolutePath());
                }
            } else {
                /* Something else went wrong when writing the snapshot out to
                 * disk. If this snapshot file is invalid, when restarting,
                 * ZooKeeper will skip it, and find the last known good snapshot
                 * instead. */
            }
            throw e;
        }
    }
}
```

```java
public class FileSnap implements SnapShot {
    public synchronized void serialize(
            DataTree dt,
            Map<Long, Integer> sessions,
            File snapShot,
            boolean fsync) throws IOException {
        if (!close) {
            try (CheckedOutputStream snapOS = SnapStream.getOutputStream(snapShot, fsync)) {
                OutputArchive oa = BinaryOutputArchive.getArchive(snapOS);
                FileHeader header = new FileHeader(SNAP_MAGIC, VERSION, dbId);
                serialize(dt, sessions, oa, header);
                SnapStream.sealStream(snapOS, oa);

                // Digest feature was added after the CRC to make it backward
                // compatible, the older code cal still read snapshots which
                // includes digest.
                //
                // To check the intact, after adding digest we added another
                // CRC check.
                if (dt.serializeZxidDigest(oa)) {
                    SnapStream.sealStream(snapOS, oa);
                }

                // serialize the last processed zxid and add another CRC check
                if (dt.serializeLastProcessedZxid(oa)) {
                    SnapStream.sealStream(snapOS, oa);
                }

                lastSnapshotInfo = new SnapshotInfo(
                        Util.getZxidFromName(snapShot.getName(), SNAPSHOT_FILE_PREFIX),
                        snapShot.lastModified() / 1000);
            }
        } else {
            throw new IOException("FileSnap has already been closed");
        }
    }

    protected void serialize(
            DataTree dt,
            Map<Long, Integer> sessions,
            OutputArchive oa,
            FileHeader header) throws IOException {
        // this is really a programmatic error and not something that can
        // happen at runtime
        if (header == null) {
            throw new IllegalStateException("Snapshot's not open for writing: uninitialized header");
        }
        header.serialize(oa, "fileheader");
        SerializeUtils.serializeSnapshot(dt, oa, sessions);
    }
}
```
FileHeader
```java
public class FileHeader implements Record {
    private int magic;
    private int version;
    private long dbid;
    public void serialize(OutputArchive a_, String tag) throws java.io.IOException {
        a_.startRecord(this,tag);
        a_.writeInt(magic,"magic");
        a_.writeInt(version,"version");
        a_.writeLong(dbid,"dbid");
        a_.endRecord(this,tag);
    }
}
```


```java
  public static void serializeSnapshot(DataTree dt, OutputArchive oa, Map<Long, Integer> sessions) throws IOException {
        HashMap<Long, Integer> sessSnap = new HashMap<>(sessions);
        oa.writeInt(sessSnap.size(), "count");
        for (Entry<Long, Integer> entry : sessSnap.entrySet()) {
            oa.writeLong(entry.getKey().longValue(), "id");
            oa.writeInt(entry.getValue().intValue(), "timeout");
        }
        dt.serialize(oa, "tree");
    }
```

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





## Purge

由于 ZooKeeper 的任何一个变更操作都产生事务，事务日志需要持久化到硬盘，同时当写操作达到一定量或者一定时间间隔后，会对内存中的数据进行一次快照并写入到硬盘上的 snapshop 中，快照为了缩短启动时加载数据的时间从而加快整个系统启动。而随着运行时间的增长生成的 transaction log 和 snapshot 将越来越多，所以要定期清理，DatadirCleanupManager 就是启动一个 TimeTask 定时任务用于清理 DataDir 中的 snapshot 及对应的 transaction log

DatadirCleanupManager日志清理工具,相关配置如下：
- autopurge.purgeInterval 参数，单位是小时，当填写一个1或更大的整数，则开启，默认是0，或者配置了负数则表示不开启自动清理功能。
- autopurge.snapRetainCount 这个参数和上面的参数搭配使用，这个参数指定了需要保留的文件数目。默认是保留3个

这里start方法中使用了Java的Timer来启动的定时任务来清理
在使用Zookeeper过程中，，会有 dataDir 和 dataLogDir 两个目录，分别用于 snapshot 和 事务日志 的输出 （默认情况下只有dataDir目录，snapshot和事务日志都保存在这个目录中，正常运行过程中，ZK会不断地把快照数据和事务日志输出到这两个目录，并且如果没有人为操作的话，ZK自己是不会清理这些文件的，需要管理员来清理，

查看snapshot文件
运行SnapshotFormatter类 -d snapshot文件绝对路径
TxnLogToolkit

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

### PurgeTask

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

#### findNValidSnapshots

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

#### purgeOlderSnapshots

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

- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)