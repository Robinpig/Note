## Overview



Nacos 配置管理⼀致性协议分为两个大部分， 第⼀部分是 Server 间⼀致性协议， ⼀个是 SDK 与
Server 的⼀致性协议， 配置作为分布式系统中非强⼀致数据， 在出现脑裂的时候可用性高于⼀致性，
因此阿里配置中心是采用 AP ⼀致性协议。  

Server 间的⼀致性协议
有 DB 模式（读写分离架构）
⼀致性的核心是 Server 与 DB 保持数据⼀致性， 从而保证 Server 数据⼀致； Server 之间都是对
等的。 数据写任何⼀个 Server， 优先持久化， 持久化成功后异步通知其他节点到数据库中拉取最新
配置值， 并且通知写入成功。  

无 DB 模式
Server 间采用 Raft 协议保证数据⼀致性  



SDK 与 Server 的⼀致性协议
SDK 与 Server ⼀致性协议的核心是通过 MD5 值是否⼀致， 如果不⼀致就拉取最新值  

Nacos2.x升级成长链接模式， 配置变更， 启动建立长链接， 配置变更服务端推送变更配置列表， 然后 SDK 拉取配置更新， 因此通信效率大幅提升。  






从整体上Nacos服务端的配置存储分为三层：

- 内存：Nacos每个节点都在内存里缓存了配置，但是只包含配置的md5（缓存配置文件太多了），所以内存级别的配置只能用于比较配置是否发生了变更，只用于客户端长轮询配置等场景。
- 文件系统：文件系统配置来源于数据库写入的配置。如果是集群启动或mysql单机启动，服务端会以本地文件系统的配置响应客户端查询。
- 数据库：所有写数据都会先写入数据库。只有当以derby数据源（-DembeddedStorage=true）单机（-Dnacos.standalone=true）启动时，客户端的查询配置请求会实时查询derby数据库。


对于写请求，Nacos会将数据先更新到数据库，之后异步写入所有节点的文件系统并更新内存。

CacheItem在Nacos服务端对应一个配置文件，缓存了配置的md5，持有一把读写锁控制访问冲突。



```java
public class CacheItem {

    public CacheItem(String groupKey) {
        this.groupKey = StringPool.get(groupKey);
    }

    final String groupKey;

    public volatile String md5 = Constants.NULL;

    public volatile long lastModifiedTs;

    /**
     * Use for beta.
     */
    public volatile boolean isBeta = false;

    public volatile String md54Beta = Constants.NULL;
}
```


```java
public class ConfigCacheService {
    /**
     * groupKey -> cacheItem.
     */
    private static final ConcurrentHashMap<String, CacheItem> CACHE = new ConcurrentHashMap<>();

    @Autowired
    private static PersistService persistService;
}
```



```java
protected void dumpOperate(DumpProcessor processor, DumpAllProcessor dumpAllProcessor,
            DumpAllBetaProcessor dumpAllBetaProcessor, DumpAllTagProcessor dumpAllTagProcessor) throws NacosException {
        String dumpFileContext = "CONFIG_DUMP_TO_FILE";
        TimerContext.start(dumpFileContext);
        try {
            LogUtil.DEFAULT_LOG.warn("DumpService start");
            
            Runnable dumpAll = () -> dumpAllTaskMgr.addTask(DumpAllTask.TASK_ID, new DumpAllTask());
            
            Runnable dumpAllBeta = () -> dumpAllTaskMgr.addTask(DumpAllBetaTask.TASK_ID, new DumpAllBetaTask());
            
            Runnable dumpAllTag = () -> dumpAllTaskMgr.addTask(DumpAllTagTask.TASK_ID, new DumpAllTagTask());
            
            Runnable clearConfigHistory = () -> {
                LOGGER.warn("clearConfigHistory start");
                if (canExecute()) {
                    try {
                        Timestamp startTime = getBeforeStamp(TimeUtils.getCurrentTime(), 24 * getRetentionDays());
                        int pageSize = 1000;
                        LOGGER.warn("clearConfigHistory, getBeforeStamp:{}, pageSize:{}", startTime, pageSize);
                        persistService.removeConfigHistory(startTime, pageSize);
                    } catch (Throwable e) {
                        LOGGER.error("clearConfigHistory error : {}", e.toString());
                    }
                }
            };
            
            try {
                dumpConfigInfo(dumpAllProcessor);
                
                // update Beta cache
                LogUtil.DEFAULT_LOG.info("start clear all config-info-beta.");
                DiskUtil.clearAllBeta();
                if (persistService.isExistTable(BETA_TABLE_NAME)) {
                    dumpAllBetaProcessor.process(new DumpAllBetaTask());
                }
                // update Tag cache
                LogUtil.DEFAULT_LOG.info("start clear all config-info-tag.");
                DiskUtil.clearAllTag();
                if (persistService.isExistTable(TAG_TABLE_NAME)) {
                    dumpAllTagProcessor.process(new DumpAllTagTask());
                }
                
                // add to dump aggr
                List<ConfigInfoChanged> configList = persistService.findAllAggrGroup();
                if (configList != null && !configList.isEmpty()) {
                    total = configList.size();
                    List<List<ConfigInfoChanged>> splitList = splitList(configList, INIT_THREAD_COUNT);
                    for (List<ConfigInfoChanged> list : splitList) {
                        MergeAllDataWorker work = new MergeAllDataWorker(list);
                        work.start();
                    }
                    LOGGER.info("server start, schedule merge end.");
                }
            } catch (Exception e) {
                LogUtil.FATAL_LOG
                        .error("Nacos Server did not start because dumpservice bean construction failure :\n" + e);
                throw new NacosException(NacosException.SERVER_ERROR,
                        "Nacos Server did not start because dumpservice bean construction failure :\n" + e.getMessage(),
                        e);
            }
            if (!EnvUtil.getStandaloneMode()) {
                Runnable heartbeat = () -> {
                    String heartBeatTime = TimeUtils.getCurrentTime().toString();
                    // write disk
                    try {
                        DiskUtil.saveHeartBeatToDisk(heartBeatTime);
                    } catch (IOException e) {
                        LogUtil.FATAL_LOG.error("save heartbeat fail" + e.getMessage());
                    }
                };
                
                ConfigExecutor.scheduleConfigTask(heartbeat, 0, 10, TimeUnit.SECONDS);
                
                long initialDelay = new Random().nextInt(INITIAL_DELAY_IN_MINUTE) + 10;
                LogUtil.DEFAULT_LOG.warn("initialDelay:{}", initialDelay);
                
                ConfigExecutor.scheduleConfigTask(dumpAll, initialDelay, DUMP_ALL_INTERVAL_IN_MINUTE, TimeUnit.MINUTES);
                
                ConfigExecutor
                        .scheduleConfigTask(dumpAllBeta, initialDelay, DUMP_ALL_INTERVAL_IN_MINUTE, TimeUnit.MINUTES);
                
                ConfigExecutor
                        .scheduleConfigTask(dumpAllTag, initialDelay, DUMP_ALL_INTERVAL_IN_MINUTE, TimeUnit.MINUTES);
            }
            
            ConfigExecutor.scheduleConfigTask(clearConfigHistory, 10, 10, TimeUnit.MINUTES);
        } finally {
            TimerContext.end(dumpFileContext, LogUtil.DUMP_LOG);
        }
        
    }
```


```java

@Component(value = "internalConfigChangeNotifier")
public class InternalConfigChangeNotifier extends Subscriber<LocalDataChangeEvent> {

    @Autowired
    private ConfigQueryRequestHandler configQueryRequestHandler;

    public InternalConfigChangeNotifier() {
        NotifyCenter.registerToPublisher(ConnectionLimitRuleChangeEvent.class, 16384);
        NotifyCenter.registerToPublisher(TpsControlRuleChangeEvent.class, 16384);
        NotifyCenter.registerSubscriber(this);

    }

    private static final String DATA_ID_TPS_CONTROL_RULE = "nacos.internal.tps.control_rule_";

    private static final String DATA_ID_CONNECTION_LIMIT_RULE = "nacos.internal.connection.limit.rule";

    private static final String NACOS_GROUP = "nacos";

    @Override
    public void onEvent(LocalDataChangeEvent event) {
        String groupKey = event.groupKey;
        String dataId = GroupKey.parseKey(groupKey)[0];
        String group = GroupKey.parseKey(groupKey)[1];
        if (DATA_ID_CONNECTION_LIMIT_RULE.equals(dataId) && NACOS_GROUP.equals(group)) {

            try {
                String content = loadLocalConfigLikeClient(dataId, group);
                NotifyCenter.publishEvent(new ConnectionLimitRuleChangeEvent(content));

            } catch (NacosException e) {
                Loggers.REMOTE.error("connection limit rule load fail.", e);
            }
        }

        if (dataId.startsWith(DATA_ID_TPS_CONTROL_RULE) && NACOS_GROUP.equals(group)) {
            try {
                String pointName = dataId.replaceFirst(DATA_ID_TPS_CONTROL_RULE, "");

                String content = loadLocalConfigLikeClient(dataId, group);
                NotifyCenter.publishEvent(new TpsControlRuleChangeEvent(pointName, content));

            } catch (NacosException e) {
                Loggers.REMOTE.error("connection limit rule load fail.", e);
            }

        }

    }
}
```


在Nacos的设计中，Mysql是一个中心数据仓库，且认为在Mysql中的数据是绝对正确的。 除此之外，Nacos在启动时会把Mysql中的数据写一份到本地磁盘。

这么设计的好处是可以提高性能，当客户端需要请求某个配置项时，服务端会想Ian从磁盘中读取对应文件返回，而磁盘的读取效率要比数据库效率高。

当配置发生变更时：

- Nacos会把变更的配置保存到数据库，然后再写入本地文件。
- 接着发送一个HTTP请求，给到集群中的其他节点，其他节点收到事件后，从Mysql中dump刚刚写入的数据到本地文件中。


另外，NacosServer启动后，会同步启动一个定时任务，每隔6小时，会dump一次全量数据到本地文件




```java
public class ConfigChangePublisher {
    
    public static void notifyConfigChange(ConfigDataChangeEvent event) {
        if (PropertyUtil.isEmbeddedStorage() && !EnvUtil.getStandaloneMode()) {
            return;
        }
        NotifyCenter.publishEvent(event);
    }
    
}
```




```java

@Service
public class AsyncNotifyService {

    @Autowired
    private DumpService dumpService;

    @Autowired
    private ConfigClusterRpcClientProxy configClusterRpcClientProxy;

    private ServerMemberManager memberManager;

    @Autowired
    public AsyncNotifyService(ServerMemberManager memberManager) {
        this.memberManager = memberManager;

        // Register ConfigDataChangeEvent to NotifyCenter.
        NotifyCenter.registerToPublisher(ConfigDataChangeEvent.class, NotifyCenter.ringBufferSize);

        // Register A Subscriber to subscribe ConfigDataChangeEvent.
        NotifyCenter.registerSubscriber(new Subscriber() {

            @Override
            public void onEvent(Event event) {
                // Generate ConfigDataChangeEvent concurrently
                if (event instanceof ConfigDataChangeEvent) {
                    ConfigDataChangeEvent evt = (ConfigDataChangeEvent) event;
                    long dumpTs = evt.lastModifiedTs;
                    String dataId = evt.dataId;
                    String group = evt.group;
                    String tenant = evt.tenant;
                    String tag = evt.tag;
                    Collection<Member> ipList = memberManager.allMembers();

                    // In fact, any type of queue here can be
                    Queue<NotifySingleTask> httpQueue = new LinkedList<NotifySingleTask>();
                    Queue<NotifySingleRpcTask> rpcQueue = new LinkedList<NotifySingleRpcTask>();

                    for (Member member : ipList) {
                        if (!MemberUtil.isSupportedLongCon(member)) {
                            httpQueue.add(new NotifySingleTask(dataId, group, tenant, tag, dumpTs, member.getAddress(),
                                    evt.isBeta));
                        } else {
                            rpcQueue.add(
                                    new NotifySingleRpcTask(dataId, group, tenant, tag, dumpTs, evt.isBeta, member));
                        }
                    }
                    if (!httpQueue.isEmpty()) {
                        ConfigExecutor.executeAsyncNotify(new AsyncTask(nacosAsyncRestTemplate, httpQueue));
                    }
                    if (!rpcQueue.isEmpty()) {
                        ConfigExecutor.executeAsyncNotify(new AsyncRpcTask(rpcQueue));
                    }

                }
            }

            @Override
            public Class<? extends Event> subscribeType() {
                return ConfigDataChangeEvent.class;
            }
        });
    }
}
```

async

```java

    class AsyncTask implements Runnable {
        
        private Queue<NotifySingleTask> queue;
        
        private NacosAsyncRestTemplate restTemplate;
        
        public AsyncTask(NacosAsyncRestTemplate restTemplate, Queue<NotifySingleTask> queue) {
            this.restTemplate = restTemplate;
            this.queue = queue;
        }
        
        @Override
        public void run() {
            executeAsyncInvoke();
        }
        
        private void executeAsyncInvoke() {
            while (!queue.isEmpty()) {
                NotifySingleTask task = queue.poll();
                String targetIp = task.getTargetIP();
                if (memberManager.hasMember(targetIp)) {
                    // start the health check and there are ips that are not monitored, put them directly in the notification queue, otherwise notify
                    boolean unHealthNeedDelay = memberManager.isUnHealth(targetIp);
                    if (unHealthNeedDelay) {
                        // target ip is unhealthy, then put it in the notification list
                        ConfigTraceService.logNotifyEvent(task.getDataId(), task.getGroup(), task.getTenant(), null,
                                task.getLastModified(), InetUtils.getSelfIP(), ConfigTraceService.NOTIFY_EVENT_UNHEALTH,
                                0, task.target);
                        // get delay time and set fail count to the task
                        asyncTaskExecute(task);
                    } else {
                        Header header = Header.newInstance();
                        header.addParam(NotifyService.NOTIFY_HEADER_LAST_MODIFIED,
                                String.valueOf(task.getLastModified()));
                        header.addParam(NotifyService.NOTIFY_HEADER_OP_HANDLE_IP, InetUtils.getSelfIP());
                        if (task.isBeta) {
                            header.addParam("isBeta", "true");
                        }
                        AuthHeaderUtil.addIdentityToHeader(header);
                        restTemplate.get(task.url, header, Query.EMPTY, String.class, new AsyncNotifyCallBack(task));
                    }
                }
            }
        }
    }
```


### Example

```java
public static void main(String[] args) throws NacosException, InterruptedException {
        Properties properties = new Properties();
        properties.put("serverAddr", "xxx.xxx.xxx.xxx:8848");
        String dataId = "info";
        ConfigService configService = new NacosConfigService(properties);
        String defaultGroup = "DEFAULT_GROUP";
        String config = configService.getConfig(dataId, defaultGroup, 5000);
        System.out.println(config);
        configService.addListener(dataId, defaultGroup, new Listener() {
            @Override
            public Executor getExecutor() {
                return null;
            }

            @Override
            public void receiveConfigInfo(String s) {
                System.out.println("Config has been changed! :" + s);
            }
        });

        TimeUnit.MINUTES.sleep(5);
    }
```


```java
@RestController
@RequestMapping(Constants.COMMUNICATION_CONTROLLER_PATH)
public class CommunicationController {
    @GetMapping("/dataChange")
    public Boolean notifyConfigInfo(HttpServletRequest request, @RequestParam("dataId") String dataId,
                                    @RequestParam("group") String group,
                                    @RequestParam(value = "tenant", required = false, defaultValue = StringUtils.EMPTY) String tenant,
                                    @RequestParam(value = "tag", required = false) String tag) {
        dataId = dataId.trim();
        group = group.trim();
        String lastModified = request.getHeader(NotifyService.NOTIFY_HEADER_LAST_MODIFIED);
        long lastModifiedTs = StringUtils.isEmpty(lastModified) ? -1 : Long.parseLong(lastModified);
        String handleIp = request.getHeader(NotifyService.NOTIFY_HEADER_OP_HANDLE_IP);
        String isBetaStr = request.getHeader("isBeta");
        if (StringUtils.isNotBlank(isBetaStr) && Boolean.parseBoolean(isBetaStr)) {
            dumpService.dump(dataId, group, tenant, lastModifiedTs, handleIp, true);
        } else {
            dumpService.dump(dataId, group, tenant, tag, lastModifiedTs, handleIp);
        }
        return true;
    }
}
```


```java
public void dump(String dataId, String group, String tenant, long lastModified, String handleIp, boolean isBeta) {
        String groupKey = GroupKey2.getKey(dataId, group, tenant);
        String taskKey = String.join("+", dataId, group, tenant, String.valueOf(isBeta));
        dumpTaskMgr.addTask(taskKey, new DumpTask(groupKey, lastModified, handleIp, isBeta));
        DUMP_LOG.info("[dump-task] add task. groupKey={}, taskKey={}", groupKey, taskKey);
    }
```


```java
@Override
    public void addTask(Object key, AbstractDelayTask newTask) {
        super.addTask(key, newTask);
        MetricsMonitor.getDumpTaskMonitor().set(tasks.size());
    }
```




```java

public class NacosDelayTaskExecuteEngine extends AbstractNacosTaskExecuteEngine<AbstractDelayTask> {

    private final ScheduledExecutorService processingExecutor;

    protected final ConcurrentHashMap<Object, AbstractDelayTask> tasks;

    protected final ReentrantLock lock = new ReentrantLock();

    public NacosDelayTaskExecuteEngine(String name, int initCapacity, Logger logger, long processInterval) {
        super(logger);
        tasks = new ConcurrentHashMap<>(initCapacity);
        processingExecutor = ExecutorFactory.newSingleScheduledExecutorService(new NameThreadFactory(name));
        processingExecutor
                .scheduleWithFixedDelay(new ProcessRunnable(), processInterval, processInterval, TimeUnit.MILLISECONDS);
    }

}
```



```java

private class ProcessRunnable implements Runnable {
    
    @Override
    public void run() {
        try {
            processTasks();
        } catch (Throwable e) {
            getEngineLog().error(e.toString(), e);
        }
    }
}

protected void processTasks() {
    Collection<Object> keys = getAllTaskKeys();
    for (Object taskKey : keys) {
        AbstractDelayTask task = removeTask(taskKey);
        if (null == task) {
            continue;
        }
        NacosTaskProcessor processor = getProcessor(taskKey);
        if (null == processor) {
            getEngineLog().error("processor not found for task, so discarded. " + task);
            continue;
        }
        try {
            // ReAdd task if process failed
            if (!processor.process(task)) {
                retryFailedTask(taskKey, task);
            }
        } catch (Throwable e) {
            getEngineLog().error("Nacos task execute error ", e);
            retryFailedTask(taskKey, task);
        }
    }
}
```

dumpProcessor
```java
public class DumpProcessor implements NacosTaskProcessor {
    
    final DumpService dumpService;
    @Override
    public boolean process(NacosTask task) {
        final PersistService persistService = dumpService.getPersistService();
        DumpTask dumpTask = (DumpTask) task;
        String[] pair = GroupKey2.parseKey(dumpTask.getGroupKey());
        String dataId = pair[0];
        String group = pair[1];
        String tenant = pair[2];
        long lastModified = dumpTask.getLastModified();
        String handleIp = dumpTask.getHandleIp();
        boolean isBeta = dumpTask.isBeta();
        String tag = dumpTask.getTag();
        
        ConfigDumpEvent.ConfigDumpEventBuilder build = ConfigDumpEvent.builder().namespaceId(tenant).dataId(dataId)
                .group(group).isBeta(isBeta).tag(tag).lastModifiedTs(lastModified).handleIp(handleIp);
        
        if (isBeta) {
            // if publish beta, then dump config, update beta cache
            ConfigInfo4Beta cf = persistService.findConfigInfo4Beta(dataId, group, tenant);
            
            build.remove(Objects.isNull(cf));
            build.betaIps(Objects.isNull(cf) ? null : cf.getBetaIps());
            build.content(Objects.isNull(cf) ? null : cf.getContent());
            build.encryptedDataKey(Objects.isNull(cf) ? null : cf.getEncryptedDataKey());
            
            return DumpConfigHandler.configDump(build.build());
        }
        if (StringUtils.isBlank(tag)) {
            ConfigInfo cf = persistService.findConfigInfo(dataId, group, tenant);
            
            build.remove(Objects.isNull(cf));
            build.content(Objects.isNull(cf) ? null : cf.getContent());
            build.type(Objects.isNull(cf) ? null : cf.getType());
            build.encryptedDataKey(Objects.isNull(cf) ? null : cf.getEncryptedDataKey());
        } else {
            ConfigInfo4Tag cf = persistService.findConfigInfo4Tag(dataId, group, tenant, tag);
            
            build.remove(Objects.isNull(cf));
            build.content(Objects.isNull(cf) ? null : cf.getContent());
            
        }
        return DumpConfigHandler.configDump(build.build());
    }
}
```


DumpConfigHandler

```java

public class DumpConfigHandler extends Subscriber<ConfigDumpEvent> {

    public static boolean configDump(ConfigDumpEvent event) {
        final String dataId = event.getDataId();
        final String group = event.getGroup();
        final String namespaceId = event.getNamespaceId();
        final String content = event.getContent();
        final String type = event.getType();
        final long lastModified = event.getLastModifiedTs();
        final String encryptedDataKey = event.getEncryptedDataKey();
        if (event.isBeta()) {
            boolean result;
            if (event.isRemove()) {
                result = ConfigCacheService.removeBeta(dataId, group, namespaceId);
                if (result) {
                    ConfigTraceService.logDumpEvent(dataId, group, namespaceId, null, lastModified, event.getHandleIp(),
                            ConfigTraceService.DUMP_EVENT_REMOVE_OK, System.currentTimeMillis() - lastModified, 0);
                }
                return result;
            } else {
                result = ConfigCacheService
                        .dumpBeta(dataId, group, namespaceId, content, lastModified, event.getBetaIps(),
                                encryptedDataKey);
                if (result) {
                    ConfigTraceService.logDumpEvent(dataId, group, namespaceId, null, lastModified, event.getHandleIp(),
                            ConfigTraceService.DUMP_EVENT_OK, System.currentTimeMillis() - lastModified,
                            content.length());
                }
            }
            
            return result;
        }
        if (StringUtils.isBlank(event.getTag())) {
            if (dataId.equals(AggrWhitelist.AGGRIDS_METADATA)) {
                AggrWhitelist.load(content);
            }
            
            if (dataId.equals(ClientIpWhiteList.CLIENT_IP_WHITELIST_METADATA)) {
                ClientIpWhiteList.load(content);
            }
            
            if (dataId.equals(SwitchService.SWITCH_META_DATAID)) {
                SwitchService.load(content);
            }
            
            boolean result;
            if (!event.isRemove()) {
                result = ConfigCacheService
                        .dump(dataId, group, namespaceId, content, lastModified, type, encryptedDataKey);
                
                if (result) {
                    ConfigTraceService.logDumpEvent(dataId, group, namespaceId, null, lastModified, event.getHandleIp(),
                            ConfigTraceService.DUMP_EVENT_OK, System.currentTimeMillis() - lastModified,
                            content.length());
                }
            } else {
                result = ConfigCacheService.remove(dataId, group, namespaceId);
                
                if (result) {
                    ConfigTraceService.logDumpEvent(dataId, group, namespaceId, null, lastModified, event.getHandleIp(),
                            ConfigTraceService.DUMP_EVENT_REMOVE_OK, System.currentTimeMillis() - lastModified, 0);
                }
            }
            return result;
        } else {
            //
            boolean result;
            if (!event.isRemove()) {
                result = ConfigCacheService
                        .dumpTag(dataId, group, namespaceId, event.getTag(), content, lastModified, encryptedDataKey);
                if (result) {
                    ConfigTraceService.logDumpEvent(dataId, group, namespaceId, null, lastModified, event.getHandleIp(),
                            ConfigTraceService.DUMP_EVENT_OK, System.currentTimeMillis() - lastModified,
                            content.length());
                }
            } else {
                result = ConfigCacheService.removeTag(dataId, group, namespaceId, event.getTag());
                if (result) {
                    ConfigTraceService.logDumpEvent(dataId, group, namespaceId, null, lastModified, event.getHandleIp(),
                            ConfigTraceService.DUMP_EVENT_REMOVE_OK, System.currentTimeMillis() - lastModified, 0);
                }
            }
            return result;
        }
        
    }
    
    @Override
    public void onEvent(ConfigDumpEvent event) {
        configDump(event);
    }
    
    @Override
    public Class<? extends Event> subscribeType() {
        return ConfigDumpEvent.class;
    }
}
```


## Config Refresh

### PropertySourceLocator
1. init [ConfigService](/docs/CS/Framework/Spring_Cloud/nacos/config.md?id=ConfigService)
2. merge configurations

```java
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "spring.cloud.nacos.config.enabled", matchIfMissing = true)
public class NacosConfigBootstrapConfiguration {
    //...
    
    @Bean
    public NacosPropertySourceLocator nacosPropertySourceLocator(
            NacosConfigManager nacosConfigManager) {
        return new NacosPropertySourceLocator(nacosConfigManager);
    }
}

public class NacosPropertySourceLocator implements PropertySourceLocator {
    @Override
    public PropertySource<?> locate(Environment env) {
        nacosConfigProperties.setEnvironment(env);
        ConfigService configService = nacosConfigManager.getConfigService();

        if (null == configService) {
            log.warn("no instance of config service found, can't load config from nacos");
            return null;
        }
        long timeout = nacosConfigProperties.getTimeout();
        nacosPropertySourceBuilder = new NacosPropertySourceBuilder(configService,
                timeout);
        String name = nacosConfigProperties.getName();

        String dataIdPrefix = nacosConfigProperties.getPrefix();
        if (StringUtils.isEmpty(dataIdPrefix)) {
            dataIdPrefix = name;
        }

        if (StringUtils.isEmpty(dataIdPrefix)) {
            dataIdPrefix = env.getProperty("spring.application.name");
        }

        CompositePropertySource composite = new CompositePropertySource(
                NACOS_PROPERTY_SOURCE_NAME);

        loadSharedConfiguration(composite);
        loadExtConfiguration(composite);
        loadApplicationConfiguration(composite, dataIdPrefix, nacosConfigProperties, env);
        return composite;
    }
}
```

### ConfigService
ClientWorker
```java
public NacosConfigService(Properties properties) throws NacosException {
    PreInitUtils.asyncPreLoadCostComponent();
    final NacosClientProperties clientProperties = NacosClientProperties.PROTOTYPE.derive(properties);
    ValidatorUtils.checkInitParam(clientProperties);

    initNamespace(clientProperties);
    this.configFilterChainManager = new ConfigFilterChainManager(clientProperties.asProperties());
    ServerListManager serverListManager = new ServerListManager(clientProperties);
    serverListManager.start();

    this.worker = new ClientWorker(this.configFilterChainManager, serverListManager, clientProperties);
    // will be deleted in 2.0 later versions
    agent = new ServerHttpAgent(serverListManager);

}
```




ClientWorker里两个单线程池 一个负责10ms一次配置变更检查 将长轮询请求[LongPollingRunnable](/docs/CS/Framework/Spring_Cloud/nacos/Nacos.md?id=LongPollingRunnable) dispatch到另一个线程池处理

```java
public class NacosConfigService implements ConfigService {
    
    private ClientWorker worker;

    @Override
    public void addListener(String dataId, String group, Listener listener) throws NacosException {
        worker.addTenantListeners(dataId, group, Arrays.asList(listener));
    }

    public ClientWorker(final HttpAgent agent, final ConfigFilterChainManager configFilterChainManager,
                        final Properties properties) {
        this.agent = agent;
        this.configFilterChainManager = configFilterChainManager;

        // Initialize the timeout parameter

        init(properties);

        this.executor = Executors.newScheduledThreadPool(1, new ThreadFactory() {
            @Override
            public Thread newThread(Runnable r) {
                Thread t = new Thread(r);
                t.setName("com.alibaba.nacos.client.Worker." + agent.getName());
                t.setDaemon(true);
                return t;
            }
        });

        this.executorService = Executors
                .newScheduledThreadPool(Runtime.getRuntime().availableProcessors(), new ThreadFactory() {
                    @Override
                    public Thread newThread(Runnable r) {
                        Thread t = new Thread(r);
                        t.setName("com.alibaba.nacos.client.Worker.longPolling." + agent.getName());
                        t.setDaemon(true);
                        return t;
                    }
                });

        this.executor.scheduleWithFixedDelay(new Runnable() {
            @Override
            public void run() {
                try {
                    checkConfigInfo();
                } catch (Throwable e) {
                    LOGGER.error("[" + agent.getName() + "] [sub-check] rotate check error", e);
                }
            }
        }, 1L, 10L, TimeUnit.MILLISECONDS);
    }
    
    public void checkConfigInfo() {
        // Dispatch tasks.
        int listenerSize = cacheMap.size();
        // Round up the longingTaskCount.
        int longingTaskCount = (int) Math.ceil(listenerSize / ParamUtil.getPerTaskConfigSize());
        if (longingTaskCount > currentLongingTaskCount) {
            for (int i = (int) currentLongingTaskCount; i < longingTaskCount; i++) {
                // The task list is no order.So it maybe has issues when changing.
                executorService.execute(new LongPollingRunnable(i));
            }
            currentLongingTaskCount = longingTaskCount;
        }
    }
}
```
#### LongPollingRunnable

1. check failover config
2. longPoll check server config
```java
class LongPollingRunnable implements Runnable {
        private int taskId;

        public LongPollingRunnable(int taskId) {
            this.taskId = taskId;
        }

    @Override
    public void run() {

        List<CacheData> cacheDatas = new ArrayList<CacheData>();
        List<String> inInitializingCacheList = new ArrayList<String>();
        try {
            // check failover config
            for (CacheData cacheData : cacheMap.values()) {
                if (cacheData.getTaskId() == taskId) {
                    cacheDatas.add(cacheData);
                    try {
                        checkLocalConfig(cacheData);
                        if (cacheData.isUseLocalConfigInfo()) {
                            cacheData.checkListenerMd5();
                        }
                    } catch (Exception e) {
                        LOGGER.error("get local config info error", e);
                    }
                }
            }

            // check server config
            List<String> changedGroupKeys = checkUpdateDataIds(cacheDatas, inInitializingCacheList);

            for (String groupKey : changedGroupKeys) {
                String[] key = GroupKey.parseKey(groupKey);
                String dataId = key[0];
                String group = key[1];
                String tenant = null;
                if (key.length == 3) {
                    tenant = key[2];
                }
                try {
                    ConfigResponse response = getServerConfig(dataId, group, tenant, 3000L);
                    CacheData cache = cacheMap.get(GroupKey.getKeyTenant(dataId, group, tenant));
                    cache.setContent(response.getContent());
                    cache.setEncryptedDataKey(response.getEncryptedDataKey());
                    if (null != response.getConfigType()) {
                        cache.setType(response.getConfigType());
                    }
                } catch (NacosException ioe) {
                    // log
                }
            }
            for (CacheData cacheData : cacheDatas) {
                if (!cacheData.isInitializing() || inInitializingCacheList
                        .contains(GroupKey.getKeyTenant(cacheData.dataId, cacheData.group, cacheData.tenant))) {
                    cacheData.checkListenerMd5();
                    cacheData.setInitializing(false);
                }
            }
            inInitializingCacheList.clear();

            executorService.execute(this);

        } catch (Throwable e) {
            // If the rotation training task is abnormal, the next execution time of the task will be punished
            executorService.schedule(this, taskPenaltyTime, TimeUnit.MILLISECONDS);
        }
    }
}
```


### Refresh Listener

Register listeners for Publish RefreshEvent to [Spring RefreshEventListener](/docs/CS/Framework/Spring/IoC.md?id=EventListener).

```java
public class NacosContextRefresher
        implements ApplicationListener<ApplicationReadyEvent>, ApplicationContextAware {
    @Override
    public void onApplicationEvent(ApplicationReadyEvent event) {
        // many Spring context
        if (this.ready.compareAndSet(false, true)) {
            this.registerNacosListenersForApplications();
        }
    }


    private void registerNacosListenersForApplications() {
        if (isRefreshEnabled()) {
            for (NacosPropertySource propertySource : NacosPropertySourceRepository.getAll()) {
                if (!propertySource.isRefreshable()) {
                    continue;
                }
                String dataId = propertySource.getDataId();
                registerNacosListener(propertySource.getGroup(), dataId);
            }
        }
    }

    private void registerNacosListener(final String groupKey, final String dataKey) {
        String key = NacosPropertySourceRepository.getMapKey(dataKey, groupKey);
        Listener listener = listenerMap.computeIfAbsent(key,
                lst -> new AbstractSharedListener() {
                    @Override
                    public void innerReceive(String dataId, String group,
                                             String configInfo) {
                        refreshCountIncrement();
                        nacosRefreshHistory.addRefreshRecord(dataId, group, configInfo);
                        // todo feature: support single refresh for listening
                        applicationContext.publishEvent(new RefreshEvent(this, null, "Refresh Nacos config"));
                    }
                });
        try {
            configService.addListener(dataKey, groupKey, listener);
        }
        catch (NacosException e) {
            log.warn(String.format(
                    "register fail for nacos listener ,dataId=[%s],group=[%s]", dataKey,
                    groupKey), e);
        }
    }
}
```


## Server Config



## Summary

1. use ScheduledThreadPool.scheduleWithFixedDelay and longPoll



## Links

- [Nacos](/docs/CS/Framework/Spring_Cloud/nacos/Nacos.md)


## References
1. [Listen for configurations](https://nacos.io/en-us/docs/open-api.html)