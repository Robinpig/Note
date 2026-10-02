## Introduction



```shell
git clone https://github.com/apache/zookeeper.git

mvn clean install -DskipTest
```

拷贝conf目录下的zoo_smaple.cfg to zoo.cfg

拷贝conf目录下logback.xml到resources下


启动类配置参数 zoo.cfg


> ZooKeeper源码若是因为ClassNotFound导致compile failed，可以确认依赖的scope是provide导致 修改scope

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


AdminServer用来管理ZooKeeperServer。
有两种实现方式JettyAdminServer和DummyAdminServer。当zookeeper.admin.enableServer为true时才启动AdminServer，通过反射的方式创建实例
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

最终 Session 和 数据的恢复，都将在 loadData 方法中完成。ZKServer 首先利用 ZKDatabase#loadDataBase 调用 FileTxnSnapLog#restore 方法，
从磁盘中反序列化 100（硬编码了在 findNValidSnapshots(100) 代码里）个有效的 Snapshot 文件，恢复出 DataTree 和 sessionsWithTimeouts 两个数据结构，以便获取到最新有效的 ZXID，并使用 FileTxnSnapLog#processTransaction 方法增量地处理 DataTree 中的事务。随后根据 Session 超时时间，将超时的 Session 从 DataTree#ephemerals 变量（Map<Long: sessionId, HashSet<String>: pathList>）中移除。
同时，利用 ZooKeeperServer#takeSnapshot 方法，将 DataTree 实例持久化到磁盘，创建一个全新的 Snapshot 文件

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


session

客户端连接 process ConnectRequest

submitRequestNow里 touch session

检测session



#### quorumMaj

```java
public class QuorumMaj implements QuorumVerifier {
    /**
     * Defines a majority to avoid computing it every time.
     */
    public QuorumMaj(Map<Long, QuorumServer> allMembers) {
        this.allMembers = allMembers;
        for (QuorumServer qs : allMembers.values()) {
            if (qs.type == LearnerType.PARTICIPANT) {
                votingMembers.put(Long.valueOf(qs.id), qs);
            } else {
                observingMembers.put(Long.valueOf(qs.id), qs);
            }
        }
        half = votingMembers.size() / 2;
    }

    /**
     * Verifies if a set is a majority. Assumes that ackSet contains acks only
     * from votingMembers
     */
    public boolean containsQuorum(Set<Long> ackSet) {
        return (ackSet.size() > half);
    }
}
```


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
        long zxid = snapLog.restore(dataTree, sessionsWithTimeouts, commitProposalPlaybackListener);
        initialized = true;
        return zxid;
    }
}
```


FileTxnSnapLog above the implementations of txnlog and snapshot

```java
public class FileTxnSnapLog {

    //the directory containing
    //the transaction logs
    final File dataDir;
    //the directory containing
    //the snapshot directory
    final File snapDir;
    TxnLog txnLog;
    SnapShot snapLog;
    private final boolean autoCreateDB;
    private final boolean trustEmptySnapshot;
    public static final int VERSION = 2;
}
```
SnapLog 是 Zookeeper 的持久化存储模块，用于将 Zookeeper 的内存数据备份到磁盘上。SnapLog 由两部分组成：事务日志（Transaction Log）和快照文件（Snapshot File）
事务日志用于记录所有的数据变更操作，快照文件会定期全量备份 DataTree 中的所有数据
当 Server 启动时，会先加载最近日期的快照文件，然后逐个加载事务日志文件，最终恢复到最新的状态

客户端的每次写入操作都会同步到磁盘，这会增加写操作的延迟，因此事务日志的写入性能直接决定 Zookeeper Server 对请求的响应速度，为了增加写入性能，Zookeeper 采用磁盘预分配的策略，在事务日志文件创建之初就向操作系统预分配一个很大的磁盘块，默认是64M，而一旦已分配的文件剩余空间不足 4KB 时，那么将会再次进行预分配

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

```java
public class FileTxnSnapLog {
    public long fastForwardFromEdits(
            DataTree dt,
            Map<Long, Integer> sessions,
            PlayBackListener listener) throws IOException {
        TxnIterator itr = txnLog.read(dt.lastProcessedZxid + 1);
        long highestZxid = dt.lastProcessedZxid;
        TxnHeader hdr;
        int txnLoaded = 0;
        long startTime = Time.currentElapsedTime();
        try {
            while (true) {
                // iterator points to
                // the first valid txn when initialized
                hdr = itr.getHeader();
                if (hdr == null) {
                    //empty logs
                    return dt.lastProcessedZxid;
                }
                if (hdr.getZxid() < highestZxid && highestZxid != 0) {
                    LOG.error("{}(highestZxid) > {}(next log) for type {}", highestZxid, hdr.getZxid(), hdr.getType());
                } else {
                    highestZxid = hdr.getZxid();
                }
                try {
                    processTransaction(hdr, dt, sessions, itr.getTxn());
                    dt.compareDigest(hdr, itr.getTxn(), itr.getDigest());
                    txnLoaded++;
                } catch (KeeperException.NoNodeException e) {
                    throw new IOException("Failed to process transaction type: "
                            + hdr.getType()
                            + " error: "
                            + e.getMessage(),
                            e);
                }
                listener.onTxnLoaded(hdr, itr.getTxn(), itr.getDigest());
                if (!itr.next()) {
                    break;
                }
            }
        } finally {
            if (itr != null) {
                itr.close();
            }
        }

        long loadTime = Time.currentElapsedTime() - startTime;
        LOG.info("{} txns loaded in {} ms", txnLoaded, loadTime);
        ServerMetrics.getMetrics().STARTUP_TXNS_LOADED.add(txnLoaded);
        ServerMetrics.getMetrics().STARTUP_TXNS_LOAD_TIME.add(loadTime);

        return highestZxid;
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
        return;
    }
    // Don't schedule the purge task with zero or negative purge interval.
    if (purgeInterval <= 0) {
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
