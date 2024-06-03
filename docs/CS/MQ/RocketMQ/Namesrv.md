## Introduction
NameServer是一个几乎无状态节点，可集群部署，节点之间无任何信息同步。

## start

Brokers send heart beats to name server every 30 seconds and name server update live broker table time stamp.
Name server scan live broker table every 10s and remove last time stamp > 120s brokers.

```java
public class NamesrvStartup {
  public static void main(String[] args) {
    main0(args);
    controllerManagerMain();
  }

  public static void main0(String[] args) {
    try {
      parseCommandlineAndConfigFile(args);
      createAndStartNamesrvController();
    } catch (Throwable e) {
      e.printStackTrace();
      System.exit(-1);
    }
  }
}
```

```java
public class NettyServerConfig implements Cloneable {

  private int serverWorkerThreads = 8;
  private int serverCallbackExecutorThreads = 0;
  private int serverSelectorThreads = 3;
  private int serverOnewaySemaphoreValue = 256;
  
}
```

initialize -> start ->

```java
public class NamesrvController {
  public boolean initialize() {
    loadConfig();
    initiateNetworkComponents(); // Netty 
    initiateThreadExecutors();
    registerProcessor();
    startScheduleService();
    initiateSslContext();
    initiateRpcHooks();
    return true;
  }

  private void initiateNetworkComponents() {
    this.remotingServer = new NettyRemotingServer(this.nettyServerConfig, this.brokerHousekeepingService);
    this.remotingClient = new NettyRemotingClient(this.nettyClientConfig);
  }

  private void initiateThreadExecutors() {
    this.defaultThreadPoolQueue = new LinkedBlockingQueue<>(this.namesrvConfig.getDefaultThreadPoolQueueCapacity());
    this.defaultExecutor = new ThreadPoolExecutor(this.namesrvConfig.getDefaultThreadPoolNums(), this.namesrvConfig.getDefaultThreadPoolNums(), 1000 * 60, TimeUnit.MILLISECONDS, this.defaultThreadPoolQueue, new ThreadFactoryImpl("RemotingExecutorThread_")) {
      @Override
      protected <T> RunnableFuture<T> newTaskFor(final Runnable runnable, final T value) {
        return new FutureTaskExt<>(runnable, value);
      }
    };

    this.clientRequestThreadPoolQueue = new LinkedBlockingQueue<>(this.namesrvConfig.getClientRequestThreadPoolQueueCapacity());
    this.clientRequestExecutor = new ThreadPoolExecutor(this.namesrvConfig.getClientRequestThreadPoolNums(), this.namesrvConfig.getClientRequestThreadPoolNums(), 1000 * 60, TimeUnit.MILLISECONDS, this.clientRequestThreadPoolQueue, new ThreadFactoryImpl("ClientRequestExecutorThread_")) {
      @Override
      protected <T> RunnableFuture<T> newTaskFor(final Runnable runnable, final T value) {
        return new FutureTaskExt<>(runnable, value);
      }
    };
  }

  private void registerProcessor() {
    if (namesrvConfig.isClusterTest()) {

      this.remotingServer.registerDefaultProcessor(new ClusterTestRequestProcessor(this, namesrvConfig.getProductEnvName()), this.defaultExecutor);
    } else {
      // Support get route info only temporarily
      ClientRequestProcessor clientRequestProcessor = new ClientRequestProcessor(this);
      this.remotingServer.registerProcessor(RequestCode.GET_ROUTEINFO_BY_TOPIC, clientRequestProcessor, this.clientRequestExecutor);

      this.remotingServer.registerDefaultProcessor(new DefaultRequestProcessor(this), this.defaultExecutor);
    }
  }
  // Three tasks： 
  private void startScheduleService() {
    this.scanExecutorService.scheduleAtFixedRate(NamesrvController.this.routeInfoManager::scanNotActiveBroker,
            5, this.namesrvConfig.getScanNotActiveBrokerInterval(), TimeUnit.MILLISECONDS);

    this.scheduledExecutorService.scheduleAtFixedRate(NamesrvController.this.kvConfigManager::printAllPeriodically,
            1, 10, TimeUnit.MINUTES);

    this.scheduledExecutorService.scheduleAtFixedRate(() -> {
      try {
        NamesrvController.this.printWaterMark();
      } catch (Throwable e) {
        LOGGER.error("printWaterMark error.", e);
      }
    }, 10, 1, TimeUnit.SECONDS);
  }
}
```

### DefaultRequestProcessor#processRequest

```java
public class DefaultRequestProcessor implements NettyRequestProcessor {
  @Override
  public RemotingCommand processRequest(ChannelHandlerContext ctx,
                                        RemotingCommand request) throws RemotingCommandException {

    if (ctx != null) {
      log.debug("receive request, {} {} {}",
              request.getCode(),
              RemotingHelper.parseChannelRemoteAddr(ctx.channel()),
              request);
    }

    switch (request.getCode()) {
      case RequestCode.PUT_KV_CONFIG:
        return this.putKVConfig(ctx, request);
      case RequestCode.GET_KV_CONFIG:
        return this.getKVConfig(ctx, request);
      case RequestCode.DELETE_KV_CONFIG:
        return this.deleteKVConfig(ctx, request);
      case RequestCode.QUERY_DATA_VERSION:
        return this.queryBrokerTopicConfig(ctx, request);
      case RequestCode.REGISTER_BROKER:
        return this.registerBroker(ctx, request);
      case RequestCode.UNREGISTER_BROKER:
        return this.unregisterBroker(ctx, request);
      case RequestCode.BROKER_HEARTBEAT:
        return this.brokerHeartbeat(ctx, request);
      case RequestCode.GET_BROKER_MEMBER_GROUP:
        return this.getBrokerMemberGroup(ctx, request);
      case RequestCode.GET_BROKER_CLUSTER_INFO:
        return this.getBrokerClusterInfo(ctx, request);
      case RequestCode.WIPE_WRITE_PERM_OF_BROKER:
        return this.wipeWritePermOfBroker(ctx, request);
      case RequestCode.ADD_WRITE_PERM_OF_BROKER:
        return this.addWritePermOfBroker(ctx, request);
      case RequestCode.GET_ALL_TOPIC_LIST_FROM_NAMESERVER:
        return this.getAllTopicListFromNameserver(ctx, request);
      case RequestCode.DELETE_TOPIC_IN_NAMESRV:
        return this.deleteTopicInNamesrv(ctx, request);
      case RequestCode.REGISTER_TOPIC_IN_NAMESRV:
        return this.registerTopicToNamesrv(ctx, request);
      case RequestCode.GET_KVLIST_BY_NAMESPACE:
        return this.getKVListByNamespace(ctx, request);
      case RequestCode.GET_TOPICS_BY_CLUSTER:
        return this.getTopicsByCluster(ctx, request);
      case RequestCode.GET_SYSTEM_TOPIC_LIST_FROM_NS:
        return this.getSystemTopicListFromNs(ctx, request);
      case RequestCode.GET_UNIT_TOPIC_LIST:
        return this.getUnitTopicList(ctx, request);
      case RequestCode.GET_HAS_UNIT_SUB_TOPIC_LIST:
        return this.getHasUnitSubTopicList(ctx, request);
      case RequestCode.GET_HAS_UNIT_SUB_UNUNIT_TOPIC_LIST:
        return this.getHasUnitSubUnUnitTopicList(ctx, request);
      case RequestCode.UPDATE_NAMESRV_CONFIG:
        return this.updateConfig(ctx, request);
      case RequestCode.GET_NAMESRV_CONFIG:
        return this.getConfig(ctx, request);
      case RequestCode.GET_CLIENT_CONFIG:
        return this.getClientConfigs(ctx, request);
      default:
        String error = " request type " + request.getCode() + " not supported";
        return RemotingCommand.createResponseCommand(RemotingSysResponseCode.REQUEST_CODE_NOT_SUPPORTED, error);
    }
  }
}
```

clients get latest route information by active

## Route

### RouteInfoManager

```java

public class RouteInfoManager {
  private final Map<String/* topic */, Map<String, QueueData>> topicQueueTable;
  private final Map<String/* brokerName */, BrokerData> brokerAddrTable;
  private final Map<String/* clusterName */, Set<String/* brokerName */>> clusterAddrTable;
  private final Map<BrokerAddrInfo/* brokerAddr */, BrokerLiveInfo> brokerLiveTable;
  private final Map<BrokerAddrInfo/* brokerAddr */, List<String>/* Filter Server */> filterServerTable;
  private final Map<String/* topic */, Map<String/*brokerName*/, TopicQueueMappingInfo>> topicQueueMappingInfoTable;

  private final BatchUnregistrationService unRegisterService;

  private final NamesrvController namesrvController;
  private final NamesrvConfig namesrvConfig;

  public RouteInfoManager(final NamesrvConfig namesrvConfig, NamesrvController namesrvController) {
    this.topicQueueTable = new ConcurrentHashMap<>(1024);
    this.brokerAddrTable = new ConcurrentHashMap<>(128);
    this.clusterAddrTable = new ConcurrentHashMap<>(32);
    this.brokerLiveTable = new ConcurrentHashMap<>(256);
    this.filterServerTable = new ConcurrentHashMap<>(256);
    this.topicQueueMappingInfoTable = new ConcurrentHashMap<>(1024);
    this.unRegisterService = new BatchUnregistrationService(this, namesrvConfig);
    this.namesrvConfig = namesrvConfig;
    this.namesrvController = namesrvController;
  }
}
```

Use [ReentrantReadWriteLock](/docs/CS/Java/JDK/Concurrency/Lock.md?id=Read-Write-Lock)

RouteInfoManager

#### registerBroker

receive register request
```java
public class DefaultRequestProcessor implements NettyRequestProcessor {
    public RemotingCommand processRequest(ChannelHandlerContext ctx,
                                          RemotingCommand request) throws RemotingCommandException {
        switch (request.getCode()) {
            // ...
            case RequestCode.REGISTER_BROKER:
                return this.registerBroker(ctx, request);
        }
    }
}
```


Route info is not real-time. The clients need to pull latest topic info in fix rate.

```java
public class DefaultRequestProcessor implements NettyRequestProcessor {
    public RemotingCommand registerBroker(ChannelHandlerContext ctx,
                                          RemotingCommand request) throws RemotingCommandException {
        final RemotingCommand response = RemotingCommand.createResponseCommand(RegisterBrokerResponseHeader.class);
        final RegisterBrokerResponseHeader responseHeader = (RegisterBrokerResponseHeader) response.readCustomHeader();
        final RegisterBrokerRequestHeader requestHeader =
                (RegisterBrokerRequestHeader) request.decodeCommandCustomHeader(RegisterBrokerRequestHeader.class);

        if (!checksum(ctx, request, requestHeader)) {
            response.setCode(ResponseCode.SYSTEM_ERROR);
            response.setRemark("crc32 not match");
            return response;
        }

        TopicConfigSerializeWrapper topicConfigWrapper = null;
        List<String> filterServerList = null;

        Version brokerVersion = MQVersion.value2Version(request.getVersion());
        if (brokerVersion.ordinal() >= MQVersion.Version.V3_0_11.ordinal()) {
            final RegisterBrokerBody registerBrokerBody = extractRegisterBrokerBodyFromRequest(request, requestHeader);
            topicConfigWrapper = registerBrokerBody.getTopicConfigSerializeWrapper();
            filterServerList = registerBrokerBody.getFilterServerList();
        } else {
            // RegisterBrokerBody of old version only contains TopicConfig.
            topicConfigWrapper = extractRegisterTopicConfigFromRequest(request);
        }

        RegisterBrokerResult result = this.namesrvController.getRouteInfoManager().registerBroker(
                requestHeader.getClusterName(),
                requestHeader.getBrokerAddr(),
                requestHeader.getBrokerName(),
                requestHeader.getBrokerId(),
                requestHeader.getHaServerAddr(),
                request.getExtFields().get(MixAll.ZONE_NAME),
                requestHeader.getHeartbeatTimeoutMillis(),
                requestHeader.getEnableActingMaster(),
                topicConfigWrapper,
                filterServerList,
                ctx.channel()
        );

        if (result == null) {
            // Register single topic route info should be after the broker completes the first registration.
            response.setCode(ResponseCode.SYSTEM_ERROR);
            response.setRemark("register broker failed");
            return response;
        }

        responseHeader.setHaServerAddr(result.getHaServerAddr());
        responseHeader.setMasterAddr(result.getMasterAddr());

        if (this.namesrvController.getNamesrvConfig().isReturnOrderTopicConfigToBroker()) {
            byte[] jsonValue = this.namesrvController.getKvConfigManager().getKVListByNamespace(NamesrvUtil.NAMESPACE_ORDER_TOPIC_CONFIG);
            response.setBody(jsonValue);
        }

        response.setCode(ResponseCode.SUCCESS);
        response.setRemark(null);
        return response;
    }
}
```

#### getRouteInfoByTopic

```java

public class ClientRequestProcessor implements NettyRequestProcessor {
    protected NamesrvController namesrvController;

    public RemotingCommand getRouteInfoByTopic(ChannelHandlerContext ctx,
                                               RemotingCommand request) throws RemotingCommandException {
        final RemotingCommand response = RemotingCommand.createResponseCommand(null);
        final GetRouteInfoRequestHeader requestHeader =
                (GetRouteInfoRequestHeader) request.decodeCommandCustomHeader(GetRouteInfoRequestHeader.class);

        TopicRouteData topicRouteData = this.namesrvController.getRouteInfoManager().pickupTopicRouteData(requestHeader.getTopic());

        if (topicRouteData != null) {
            if (this.namesrvController.getNamesrvConfig().isOrderMessageEnable()) {
                String orderTopicConf =
                        this.namesrvController.getKvConfigManager().getKVConfig(NamesrvUtil.NAMESPACE_ORDER_TOPIC_CONFIG,
                                requestHeader.getTopic());
                topicRouteData.setOrderTopicConf(orderTopicConf);
            }

            byte[] content;
            Boolean standardJsonOnly = requestHeader.getAcceptStandardJsonOnly();
            if (request.getVersion() >= MQVersion.Version.V4_9_4.ordinal() || null != standardJsonOnly && standardJsonOnly) {
                content = topicRouteData.encode(SerializerFeature.BrowserCompatible,
                        SerializerFeature.QuoteFieldNames, SerializerFeature.SkipTransientField,
                        SerializerFeature.MapSortField);
            } else {
                content = topicRouteData.encode();
            }

            response.setBody(content);
            response.setCode(ResponseCode.SUCCESS);
            response.setRemark(null);
            return response;
        }

        response.setCode(ResponseCode.TOPIC_NOT_EXIST);
        response.setRemark("No topic route info in name server for the topic: " + requestHeader.getTopic()
                + FAQUrl.suggestTodo(FAQUrl.APPLY_TOPIC_URL));
        return response;
    }
}
```

## HouseKeep

BrokerHousekeepingService


## Links

- [RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
