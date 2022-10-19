## Introduction

Apache RocketMQ is a distributed middleware service that adopts an asynchronous communication model and a publish/subscribe message transmission model.
The asynchronous communication model of Apache RocketMQ features simple system topology and weak upstream-downstream coupling.
Apache RocketMQ is used in asynchronous decoupling and load shifting scenarios.

### Domain Model

<div style="text-align: center;">

![Fig.1. Domain model](./img/Domain-Model.png)

</div>

<p style="text-align: center;">
Fig.1. Domain model of Apache RocketMQ.
</p>

As shown in the preceding figure, the lifecycle of a Apache RocketMQ message consists of three stages: production, storage, and consumption.
A producer generates a message and sends it to a Apache RocketMQ broker. The message is stored in a topic on the broker. A consumer subscribes to the topic to consume the message.

Message production

Producer：
The running entity that is used to generate messages in Apache RocketMQ. Producers are the upstream parts of business call links. Producers are lightweight, anonymous, and do not have identities.

Message storage

- Topic：
  The grouping container that is used for message transmission and storage in Apache RocketMQ. A topic consists of multiple message queues, which are used to store messages and scale out the topic.
- MessageQueue：
  The unit container that is used for message transmission and storage in Apache RocketMQ. Message queues are similar to partitions in Kafka. Apache RocketMQ stores messages in a streaming manner based on an infinite queue structure. Messages are stored in order in a queue.
- Message：
  The minimum unit of data transmission in Apache RocketMQ. Messages are immutable after they are initialized and stored.

Message consumption

- ConsumerGroup：
  An independent group of consumption identities defined in the publish/subscribe model of Apache RocketMQ. A consumer group is used to centrally manage consumers that run at the bottom layer. Consumers in the same group must maintain the same consumption logic and configurations with each other, and consume the messages subscribed by the group together to scale out the consumption capacity of the group.
- Consumer：
  The running entity that is used to consume messages in Apache RocketMQ. Consumers are the downstream parts of business call links, A consumer must belong to a specific consumer group.
- Subscription：
  The collection of configurations in the publish/subscribe model of Apache RocketMQ. The configurations include message filtering, retry, and consumer progress Subscriptions are managed at the consumer group level. You use consumer groups to specify subscriptions to manage how consumers in the group filter messages, retry consumption, and restore a consumer offset.
  The configurations in a Apache RocketMQ subscription are all persistent, except for filter expressions. Subscriptions are unchanged regardless of whether the broker restarts or the connection is closed.
- Producer
- Consumer

  - DefaultLitePullConsumer
  - DefaultMQPushConsumer
- Broker
- NameServer

Topic -> multi message queue(like partition)

## Broker


BrokerController

```java
public void start() throws Exception {

        this.shouldStartTime = System.currentTimeMillis() + messageStoreConfig.getDisappearTimeAfterStart();

        if (messageStoreConfig.getTotalReplicas() > 1 && this.brokerConfig.isEnableSlaveActingMaster() || this.brokerConfig.isEnableControllerMode()) {
            isIsolated = true;
        }

        if (this.brokerOuterAPI != null) {
            this.brokerOuterAPI.start();
        }

        startBasicService();

        if (!isIsolated && !this.messageStoreConfig.isEnableDLegerCommitLog() && !this.messageStoreConfig.isDuplicationEnable()) {
            changeSpecialServiceStatus(this.brokerConfig.getBrokerId() == MixAll.MASTER_ID);
            this.registerBrokerAll(true, false, true);
        }

        scheduledFutures.add(this.scheduledExecutorService.scheduleAtFixedRate(new AbstractBrokerRunnable(this.getBrokerIdentity()) {
            @Override
            public void run2() {
                try {
                    if (System.currentTimeMillis() < shouldStartTime) {
                        BrokerController.LOG.info(“Register to namesrv after {}”, shouldStartTime);
                        return;
                    }
                    if (isIsolated) {
                        BrokerController.LOG.info(“Skip register for broker is isolated”);
                        return;
                    }
                    // Send heartbeat
                    BrokerController.this.registerBrokerAll(true, false, brokerConfig.isForceRegister());
                } catch (Throwable e) {
                    BrokerController.LOG.error(“registerBrokerAll Exception”, e);
                }
            }
        }, 1000 * 10, Math.max(10000, Math.min(brokerConfig.getRegisterNameServerPeriod(), 60000)), TimeUnit.MILLISECONDS));

        if (this.brokerConfig.isEnableSlaveActingMaster()) {
            scheduleSendHeartbeat();

            scheduledFutures.add(this.syncBrokerMemberGroupExecutorService.scheduleAtFixedRate(new AbstractBrokerRunnable(this.getBrokerIdentity()) {
                @Override
                public void run2() {
                    try {
                        BrokerController.this.syncBrokerMemberGroup();
                    } catch (Throwable e) {
                        BrokerController.LOG.error(“sync BrokerMemberGroup error. “, e);
                    }
                }
            }, 1000, this.brokerConfig.getSyncBrokerMemberGroupPeriod(), TimeUnit.MILLISECONDS));
        }

        if (this.brokerConfig.isEnableControllerMode()) {
            scheduleSendHeartbeat();
        }

        if (brokerConfig.isSkipPreOnline()) {
            startServiceWithoutCondition();
        }
    }
```



Broker sync route table every 30s

PushConumser

Actually a pull

RebalanceService thread

pullRequestQueue

PullMessageProcessor of broker

## NameServer

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


Processor




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

```java
public RegisterBrokerResult registerBroker(
        final String clusterName,
        final String brokerAddr,
        final String brokerName,
        final long brokerId,
        final String haServerAddr,
        final String zoneName,
        final Long timeoutMillis,
        final TopicConfigSerializeWrapper topicConfigWrapper,
        final List<String> filterServerList,
        final Channel channel) {
        return registerBroker(clusterName, brokerAddr, brokerName, brokerId, haServerAddr, zoneName, timeoutMillis, false, topicConfigWrapper, filterServerList, channel);
    }
```

Route info is not real-time. The clients need to pull latest topic info in fix rate.



## Producer

The producers of Apache RocketMQ are underlying resources that can be reused, like the connection pool of a database.
You do not need to create producers each time you send messages or destroy the producers after you send messages.
If you regularly create and destroy producers, a large number of short connection requests are generated on the broker.
We recommend that you create and initialize the minimum number of producers that your business scenarios require, and reuse as many producers as you can.

### send

```java
public SendResult send(Message msg,
      long timeout) throws MQClientException, RemotingException, MQBrokerException, InterruptedException {
      return this.sendDefaultImpl(msg, CommunicationMode.SYNC, null, timeout);
  }
```

1. findTopic -> update Topic
2. selectOneMessageQueue

```java
public class DefaultMQProducerImpl implements MQProducerInner {

  private MQClientInstance mQClientFactory;

  private MQFaultStrategy mqFaultStrategy = new MQFaultStrategy();
  
  private SendResult sendDefaultImpl(
          Message msg,
          final CommunicationMode communicationMode,
          final SendCallback sendCallback,
          final long timeout
  ) throws MQClientException, RemotingException, MQBrokerException, InterruptedException {
    this.makeSureStateOK();
    Validators.checkMessage(msg, this.defaultMQProducer);
    final long invokeID = random.nextLong();
    long beginTimestampFirst = System.currentTimeMillis();
    long beginTimestampPrev = beginTimestampFirst;
    long endTimestamp = beginTimestampFirst;
    TopicPublishInfo topicPublishInfo = this.tryToFindTopicPublishInfo(msg.getTopic());
    if (topicPublishInfo != null && topicPublishInfo.ok()) {
      boolean callTimeout = false;
      MessageQueue mq = null;
      Exception exception = null;
      SendResult sendResult = null;
      int timesTotal = communicationMode == CommunicationMode.SYNC ? 1 + this.defaultMQProducer.getRetryTimesWhenSendFailed() : 1;
      int times = 0;
      String[] brokersSent = new String[timesTotal];
      for (; times < timesTotal; times++) {
        String lastBrokerName = null == mq ? null : mq.getBrokerName();
        MessageQueue mqSelected = this.selectOneMessageQueue(topicPublishInfo, lastBrokerName);
        if (mqSelected != null) {
          mq = mqSelected;
          brokersSent[times] = mq.getBrokerName();
          try {
            beginTimestampPrev = System.currentTimeMillis();
            if (times > 0) {
              //Reset topic with namespace during resend.
              msg.setTopic(this.defaultMQProducer.withNamespace(msg.getTopic()));
            }
            long costTime = beginTimestampPrev - beginTimestampFirst;
            if (timeout < costTime) {
              callTimeout = true;
              break;
            }

            sendResult = this.sendKernelImpl(msg, mq, communicationMode, sendCallback, topicPublishInfo, timeout - costTime);
            endTimestamp = System.currentTimeMillis();
            this.updateFaultItem(mq.getBrokerName(), endTimestamp - beginTimestampPrev, false);
            switch (communicationMode) {
              case ASYNC:
                return null;
              case ONEWAY:
                return null;
              case SYNC:
                if (sendResult.getSendStatus() != SendStatus.SEND_OK) {
                  if (this.defaultMQProducer.isRetryAnotherBrokerWhenNotStoreOK()) {
                    continue;
                  }
                }

                return sendResult;
              default:
                break;
            }
          } catch (RemotingException e) {
            endTimestamp = System.currentTimeMillis();
            this.updateFaultItem(mq.getBrokerName(), endTimestamp - beginTimestampPrev, true);
            log.warn(String.format("sendKernelImpl exception, resend at once, InvokeID: %s, RT: %sms, Broker: %s", invokeID, endTimestamp - beginTimestampPrev, mq), e);
            log.warn(msg.toString());
            exception = e;
            continue;
          } catch (MQClientException e) {
            endTimestamp = System.currentTimeMillis();
            this.updateFaultItem(mq.getBrokerName(), endTimestamp - beginTimestampPrev, true);
            log.warn(String.format("sendKernelImpl exception, resend at once, InvokeID: %s, RT: %sms, Broker: %s", invokeID, endTimestamp - beginTimestampPrev, mq), e);
            log.warn(msg.toString());
            exception = e;
            continue;
          } catch (MQBrokerException e) {
            endTimestamp = System.currentTimeMillis();
            this.updateFaultItem(mq.getBrokerName(), endTimestamp - beginTimestampPrev, true);
            log.warn(String.format("sendKernelImpl exception, resend at once, InvokeID: %s, RT: %sms, Broker: %s", invokeID, endTimestamp - beginTimestampPrev, mq), e);
            log.warn(msg.toString());
            exception = e;
            if (this.defaultMQProducer.getRetryResponseCodes().contains(e.getResponseCode())) {
              continue;
            } else {
              if (sendResult != null) {
                return sendResult;
              }

              throw e;
            }
          } catch (InterruptedException e) {
            endTimestamp = System.currentTimeMillis();
            this.updateFaultItem(mq.getBrokerName(), endTimestamp - beginTimestampPrev, false);
            log.warn(String.format("sendKernelImpl exception, throw exception, InvokeID: %s, RT: %sms, Broker: %s", invokeID, endTimestamp - beginTimestampPrev, mq), e);
            log.warn(msg.toString());
            throw e;
          }
        } else {
          break;
        }
      }

      if (sendResult != null) {
        return sendResult;
      }

      String info = String.format("Send [%d] times, still failed, cost [%d]ms, Topic: %s, BrokersSent: %s",
              times,
              System.currentTimeMillis() - beginTimestampFirst,
              msg.getTopic(),
              Arrays.toString(brokersSent));

      info += FAQUrl.suggestTodo(FAQUrl.SEND_MSG_FAILED);

      MQClientException mqClientException = new MQClientException(info, exception);
      if (callTimeout) {
        throw new RemotingTooMuchRequestException("sendDefaultImpl call timeout");
      }

      if (exception instanceof MQBrokerException) {
        mqClientException.setResponseCode(((MQBrokerException) exception).getResponseCode());
      } else if (exception instanceof RemotingConnectException) {
        mqClientException.setResponseCode(ClientErrorCode.CONNECT_BROKER_EXCEPTION);
      } else if (exception instanceof RemotingTimeoutException) {
        mqClientException.setResponseCode(ClientErrorCode.ACCESS_BROKER_TIMEOUT);
      } else if (exception instanceof MQClientException) {
        mqClientException.setResponseCode(ClientErrorCode.BROKER_NOT_EXIST_EXCEPTION);
      }

      throw mqClientException;
    }

    validateNameServerSetting();

    throw new MQClientException("No route info of this topic: " + msg.getTopic() + FAQUrl.suggestTodo(FAQUrl.NO_TOPIC_ROUTE_INFO),
            null).setResponseCode(ClientErrorCode.NOT_FOUND_TOPIC_EXCEPTION);
  }
}
```


#### FaultStrategy

### MQClientInstance

```java
public class MQClientInstance {
    
    
}
```


start

```java
public class MQClientInstance {
  public void start() throws MQClientException {

    synchronized (this) {
      switch (this.serviceState) {
        case CREATE_JUST:
          this.serviceState = ServiceState.START_FAILED;
          // If not specified,looking address from name server
          if (null == this.clientConfig.getNamesrvAddr()) {
            this.mQClientAPIImpl.fetchNameServerAddr();
          }
          // Start request-response channel
          this.mQClientAPIImpl.start();
          // Start various schedule tasks
          this.startScheduledTask();
          // Start pull service
          this.pullMessageService.start();
          // Start rebalance service
          this.rebalanceService.start();
          // Start push service
          this.defaultMQProducer.getDefaultMQProducerImpl().start(false);
          log.info("the client factory [{}] start OK", this.clientId);
          this.serviceState = ServiceState.RUNNING;
          break;
        case START_FAILED:
          throw new MQClientException("The Factory object[" + this.getClientId() + "] has been created before, and failed.", null);
        default:
          break;
      }
    }
  }
}
```

startScheduledTask
```java

    private void startScheduledTask() {
        if (null == this.clientConfig.getNamesrvAddr()) {
            this.scheduledExecutorService.scheduleAtFixedRate(() -> {
                try {
                    MQClientInstance.this.mQClientAPIImpl.fetchNameServerAddr();
                } catch (Exception e) {
                    log.error("ScheduledTask fetchNameServerAddr exception", e);
                }
            }, 1000 * 10, 1000 * 60 * 2, TimeUnit.MILLISECONDS);
        }

        this.scheduledExecutorService.scheduleAtFixedRate(() -> {
            try {
                MQClientInstance.this.updateTopicRouteInfoFromNameServer();
            } catch (Exception e) {
                log.error("ScheduledTask updateTopicRouteInfoFromNameServer exception", e);
            }
        }, 10, this.clientConfig.getPollNameServerInterval(), TimeUnit.MILLISECONDS);

        this.scheduledExecutorService.scheduleAtFixedRate(() -> {
            try {
                MQClientInstance.this.cleanOfflineBroker();
                MQClientInstance.this.sendHeartbeatToAllBrokerWithLock();
            } catch (Exception e) {
                log.error("ScheduledTask sendHeartbeatToAllBroker exception", e);
            }
        }, 1000, this.clientConfig.getHeartbeatBrokerInterval(), TimeUnit.MILLISECONDS);

        this.scheduledExecutorService.scheduleAtFixedRate(() -> {
            try {
                MQClientInstance.this.persistAllConsumerOffset();
            } catch (Exception e) {
                log.error("ScheduledTask persistAllConsumerOffset exception", e);
            }
        }, 1000 * 10, this.clientConfig.getPersistConsumerOffsetInterval(), TimeUnit.MILLISECONDS);

        this.scheduledExecutorService.scheduleAtFixedRate(() -> {
            try {
                MQClientInstance.this.adjustThreadPool();
            } catch (Exception e) {
                log.error("ScheduledTask adjustThreadPool exception", e);
            }
        }, 1, 1, TimeUnit.MINUTES);
    }
```

## Consumer

Message model defines the way how messages are delivered to each consumer clients.
RocketMQ supports two message models: clustering and broadcasting.

- If clustering is set, consumer clients with the same consumerGroup would only consume shards of the messages subscribed, which achieves load balances;
- Conversely, if the broadcasting is set, each consumer client will consume all subscribed messages separately.

This defaults model is clustering.

```java
public class PullMessageService extends ServiceThread {
  @Override
  public void run() {
    log.info(this.getServiceName() + " service started");

    while (!this.isStopped()) {
      try {
        MessageRequest messageRequest = this.messageRequestQueue.take();
        if (messageRequest.getMessageRequestMode() == MessageRequestMode.POP) {
          this.popMessage((PopRequest) messageRequest);
        } else {
          this.pullMessage((PullRequest) messageRequest);
        }
      } catch (InterruptedException ignored) {
      } catch (Exception e) {
        log.error("Pull Message Service Run Method exception", e);
      }
    }

    log.info(this.getServiceName() + " service end");
  }
}
```

### PushConsumer


#### start
DefaultMQPushConsumerImpl#start

```java
public class DefaultMQPushConsumerImpl implements MQConsumerInner {
  public synchronized void start() throws MQClientException {
    switch (this.serviceState) {
      case CREATE_JUST:
        log.info("the consumer [{}] start beginning. messageModel={}, isUnitMode={}", this.defaultMQPushConsumer.getConsumerGroup(),
                this.defaultMQPushConsumer.getMessageModel(), this.defaultMQPushConsumer.isUnitMode());
        this.serviceState = ServiceState.START_FAILED;

        this.checkConfig();

        this.copySubscription();

        if (this.defaultMQPushConsumer.getMessageModel() == MessageModel.CLUSTERING) {
          this.defaultMQPushConsumer.changeInstanceNameToPID();
        }

        this.mQClientFactory = MQClientManager.getInstance().getOrCreateMQClientInstance(this.defaultMQPushConsumer, this.rpcHook);

        this.rebalanceImpl.setConsumerGroup(this.defaultMQPushConsumer.getConsumerGroup());
        this.rebalanceImpl.setMessageModel(this.defaultMQPushConsumer.getMessageModel());
        this.rebalanceImpl.setAllocateMessageQueueStrategy(this.defaultMQPushConsumer.getAllocateMessageQueueStrategy());
        this.rebalanceImpl.setmQClientFactory(this.mQClientFactory);

        if (this.pullAPIWrapper == null) {
          this.pullAPIWrapper = new PullAPIWrapper(
                  mQClientFactory,
                  this.defaultMQPushConsumer.getConsumerGroup(), isUnitMode());
        }
        this.pullAPIWrapper.registerFilterMessageHook(filterMessageHookList);

        if (this.defaultMQPushConsumer.getOffsetStore() != null) {
          this.offsetStore = this.defaultMQPushConsumer.getOffsetStore();
        } else {
          switch (this.defaultMQPushConsumer.getMessageModel()) {
            case BROADCASTING:
              this.offsetStore = new LocalFileOffsetStore(this.mQClientFactory, this.defaultMQPushConsumer.getConsumerGroup());
              break;
            case CLUSTERING:
              this.offsetStore = new RemoteBrokerOffsetStore(this.mQClientFactory, this.defaultMQPushConsumer.getConsumerGroup());
              break;
            default:
              break;
          }
          this.defaultMQPushConsumer.setOffsetStore(this.offsetStore);
        }
        this.offsetStore.load();

        if (this.getMessageListenerInner() instanceof MessageListenerOrderly) {
          this.consumeOrderly = true;
          this.consumeMessageService =
                  new ConsumeMessageOrderlyService(this, (MessageListenerOrderly) this.getMessageListenerInner());
          //POPTODO reuse Executor ?
          this.consumeMessagePopService = new ConsumeMessagePopOrderlyService(this, (MessageListenerOrderly) this.getMessageListenerInner());
        } else if (this.getMessageListenerInner() instanceof MessageListenerConcurrently) {
          this.consumeOrderly = false;
          this.consumeMessageService =
                  new ConsumeMessageConcurrentlyService(this, (MessageListenerConcurrently) this.getMessageListenerInner());
          //POPTODO reuse Executor ?
          this.consumeMessagePopService =
                  new ConsumeMessagePopConcurrentlyService(this, (MessageListenerConcurrently) this.getMessageListenerInner());
        }

        this.consumeMessageService.start();
        // POPTODO
        this.consumeMessagePopService.start();

        boolean registerOK = mQClientFactory.registerConsumer(this.defaultMQPushConsumer.getConsumerGroup(), this);
        if (!registerOK) {
          this.serviceState = ServiceState.CREATE_JUST;
          this.consumeMessageService.shutdown(defaultMQPushConsumer.getAwaitTerminationMillisWhenShutdown());
          throw new MQClientException("The consumer group[" + this.defaultMQPushConsumer.getConsumerGroup()
                  + "] has been created before, specify another name please." + FAQUrl.suggestTodo(FAQUrl.GROUP_NAME_DUPLICATE_URL),
                  null);
        }

        mQClientFactory.start();
        log.info("the consumer [{}] start OK.", this.defaultMQPushConsumer.getConsumerGroup());
        this.serviceState = ServiceState.RUNNING;
        break;
      case RUNNING:
      case START_FAILED:
      case SHUTDOWN_ALREADY:
        throw new MQClientException("The PushConsumer service state not OK, maybe started once, "
                + this.serviceState
                + FAQUrl.suggestTodo(FAQUrl.CLIENT_SERVICE_NOT_OK),
                null);
      default:
        break;
    }

    this.updateTopicSubscribeInfoWhenSubscriptionChanged();
    this.mQClientFactory.checkClientInBroker();
    this.mQClientFactory.sendHeartbeatToAllBrokerWithLock();
    this.mQClientFactory.rebalanceImmediately();
  }
}
```



#### pullMessage

```java
public class DefaultMQPushConsumerImpl implements MQConsumerInner {
  public void pullMessage(final PullRequest pullRequest) {
    final ProcessQueue processQueue = pullRequest.getProcessQueue();
    if (processQueue.isDropped()) {
      log.info("the pull request[{}] is dropped.", pullRequest.toString());
      return;
    }

    pullRequest.getProcessQueue().setLastPullTimestamp(System.currentTimeMillis());

    try {
      this.makeSureStateOK();
    } catch (MQClientException e) {
      log.warn("pullMessage exception, consumer state not ok", e);
      this.executePullRequestLater(pullRequest, pullTimeDelayMillsWhenException);
      return;
    }

    if (this.isPause()) {
      log.warn("consumer was paused, execute pull request later. instanceName={}, group={}", this.defaultMQPushConsumer.getInstanceName(), this.defaultMQPushConsumer.getConsumerGroup());
      this.executePullRequestLater(pullRequest, PULL_TIME_DELAY_MILLS_WHEN_SUSPEND);
      return;
    }

    long cachedMessageCount = processQueue.getMsgCount().get();
    long cachedMessageSizeInMiB = processQueue.getMsgSize().get() / (1024 * 1024);

    if (cachedMessageCount > this.defaultMQPushConsumer.getPullThresholdForQueue()) {
      this.executePullRequestLater(pullRequest, PULL_TIME_DELAY_MILLS_WHEN_FLOW_CONTROL);
      if ((queueFlowControlTimes++ % 1000) == 0) {
        log.warn(
                "the cached message count exceeds the threshold {}, so do flow control, minOffset={}, maxOffset={}, count={}, size={} MiB, pullRequest={}, flowControlTimes={}",
                this.defaultMQPushConsumer.getPullThresholdForQueue(), processQueue.getMsgTreeMap().firstKey(), processQueue.getMsgTreeMap().lastKey(), cachedMessageCount, cachedMessageSizeInMiB, pullRequest, queueFlowControlTimes);
      }
      return;
    }

    if (cachedMessageSizeInMiB > this.defaultMQPushConsumer.getPullThresholdSizeForQueue()) {
      this.executePullRequestLater(pullRequest, PULL_TIME_DELAY_MILLS_WHEN_FLOW_CONTROL);
      if ((queueFlowControlTimes++ % 1000) == 0) {
        log.warn(
                "the cached message size exceeds the threshold {} MiB, so do flow control, minOffset={}, maxOffset={}, count={}, size={} MiB, pullRequest={}, flowControlTimes={}",
                this.defaultMQPushConsumer.getPullThresholdSizeForQueue(), processQueue.getMsgTreeMap().firstKey(), processQueue.getMsgTreeMap().lastKey(), cachedMessageCount, cachedMessageSizeInMiB, pullRequest, queueFlowControlTimes);
      }
      return;
    }

    if (!this.consumeOrderly) {
      if (processQueue.getMaxSpan() > this.defaultMQPushConsumer.getConsumeConcurrentlyMaxSpan()) {
        this.executePullRequestLater(pullRequest, PULL_TIME_DELAY_MILLS_WHEN_FLOW_CONTROL);
        if ((queueMaxSpanFlowControlTimes++ % 1000) == 0) {
          log.warn(
                  "the queue's messages, span too long, so do flow control, minOffset={}, maxOffset={}, maxSpan={}, pullRequest={}, flowControlTimes={}",
                  processQueue.getMsgTreeMap().firstKey(), processQueue.getMsgTreeMap().lastKey(), processQueue.getMaxSpan(),
                  pullRequest, queueMaxSpanFlowControlTimes);
        }
        return;
      }
    } else {
      if (processQueue.isLocked()) {
        if (!pullRequest.isPreviouslyLocked()) {
          long offset = -1L;
          try {
            offset = this.rebalanceImpl.computePullFromWhereWithException(pullRequest.getMessageQueue());
            if (offset < 0) {
              throw new MQClientException(ResponseCode.SYSTEM_ERROR, "Unexpected offset " + offset);
            }
          } catch (Exception e) {
            this.executePullRequestLater(pullRequest, pullTimeDelayMillsWhenException);
            log.error("Failed to compute pull offset, pullResult: {}", pullRequest, e);
            return;
          }
          boolean brokerBusy = offset < pullRequest.getNextOffset();
          log.info("the first time to pull message, so fix offset from broker. pullRequest: {} NewOffset: {} brokerBusy: {}",
                  pullRequest, offset, brokerBusy);
          if (brokerBusy) {
            log.info("[NOTIFYME]the first time to pull message, but pull request offset larger than broker consume offset. pullRequest: {} NewOffset: {}",
                    pullRequest, offset);
          }

          pullRequest.setPreviouslyLocked(true);
          pullRequest.setNextOffset(offset);
        }
      } else {
        this.executePullRequestLater(pullRequest, pullTimeDelayMillsWhenException);
        log.info("pull message later because not locked in broker, {}", pullRequest);
        return;
      }
    }

    final SubscriptionData subscriptionData = this.rebalanceImpl.getSubscriptionInner().get(pullRequest.getMessageQueue().getTopic());
    if (null == subscriptionData) {
      this.executePullRequestLater(pullRequest, pullTimeDelayMillsWhenException);
      log.warn("find the consumer's subscription failed, {}", pullRequest);
      return;
    }

    final long beginTimestamp = System.currentTimeMillis();

    PullCallback pullCallback = new PullCallback() {
      @Override
      public void onSuccess(PullResult pullResult) {
        if (pullResult != null) {
          pullResult = DefaultMQPushConsumerImpl.this.pullAPIWrapper.processPullResult(pullRequest.getMessageQueue(), pullResult,
                  subscriptionData);

          switch (pullResult.getPullStatus()) {
            case FOUND:
              long prevRequestOffset = pullRequest.getNextOffset();
              pullRequest.setNextOffset(pullResult.getNextBeginOffset());
              long pullRT = System.currentTimeMillis() - beginTimestamp;
              DefaultMQPushConsumerImpl.this.getConsumerStatsManager().incPullRT(pullRequest.getConsumerGroup(),
                      pullRequest.getMessageQueue().getTopic(), pullRT);

              long firstMsgOffset = Long.MAX_VALUE;
              if (pullResult.getMsgFoundList() == null || pullResult.getMsgFoundList().isEmpty()) {
                DefaultMQPushConsumerImpl.this.executePullRequestImmediately(pullRequest);
              } else {
                firstMsgOffset = pullResult.getMsgFoundList().get(0).getQueueOffset();

                DefaultMQPushConsumerImpl.this.getConsumerStatsManager().incPullTPS(pullRequest.getConsumerGroup(),
                        pullRequest.getMessageQueue().getTopic(), pullResult.getMsgFoundList().size());

                boolean dispatchToConsume = processQueue.putMessage(pullResult.getMsgFoundList());
                DefaultMQPushConsumerImpl.this.consumeMessageService.submitConsumeRequest(
                        pullResult.getMsgFoundList(),
                        processQueue,
                        pullRequest.getMessageQueue(),
                        dispatchToConsume);

                if (DefaultMQPushConsumerImpl.this.defaultMQPushConsumer.getPullInterval() > 0) {
                  DefaultMQPushConsumerImpl.this.executePullRequestLater(pullRequest,
                          DefaultMQPushConsumerImpl.this.defaultMQPushConsumer.getPullInterval());
                } else {
                  DefaultMQPushConsumerImpl.this.executePullRequestImmediately(pullRequest);
                }
              }

              if (pullResult.getNextBeginOffset() < prevRequestOffset
                      || firstMsgOffset < prevRequestOffset) {
                log.warn(
                        "[BUG] pull message result maybe data wrong, nextBeginOffset: {} firstMsgOffset: {} prevRequestOffset: {}",
                        pullResult.getNextBeginOffset(),
                        firstMsgOffset,
                        prevRequestOffset);
              }

              break;
            case NO_NEW_MSG:
            case NO_MATCHED_MSG:
              pullRequest.setNextOffset(pullResult.getNextBeginOffset());

              DefaultMQPushConsumerImpl.this.correctTagsOffset(pullRequest);

              DefaultMQPushConsumerImpl.this.executePullRequestImmediately(pullRequest);
              break;
            case OFFSET_ILLEGAL:
              log.warn("the pull request offset illegal, {} {}",
                      pullRequest.toString(), pullResult.toString());
              pullRequest.setNextOffset(pullResult.getNextBeginOffset());

              pullRequest.getProcessQueue().setDropped(true);
              DefaultMQPushConsumerImpl.this.executeTaskLater(new Runnable() {

                @Override
                public void run() {
                  try {
                    DefaultMQPushConsumerImpl.this.offsetStore.updateOffset(pullRequest.getMessageQueue(),
                            pullRequest.getNextOffset(), false);

                    DefaultMQPushConsumerImpl.this.offsetStore.persist(pullRequest.getMessageQueue());

                    DefaultMQPushConsumerImpl.this.rebalanceImpl.removeProcessQueue(pullRequest.getMessageQueue());

                    log.warn("fix the pull request offset, {}", pullRequest);
                  } catch (Throwable e) {
                    log.error("executeTaskLater Exception", e);
                  }
                }
              }, 10000);
              break;
            default:
              break;
          }
        }
      }

      @Override
      public void onException(Throwable e) {
        if (!pullRequest.getMessageQueue().getTopic().startsWith(MixAll.RETRY_GROUP_TOPIC_PREFIX)) {
          log.warn("execute the pull request exception", e);
        }

        DefaultMQPushConsumerImpl.this.executePullRequestLater(pullRequest, pullTimeDelayMillsWhenException);
      }
    };

    boolean commitOffsetEnable = false;
    long commitOffsetValue = 0L;
    if (MessageModel.CLUSTERING == this.defaultMQPushConsumer.getMessageModel()) {
      commitOffsetValue = this.offsetStore.readOffset(pullRequest.getMessageQueue(), ReadOffsetType.READ_FROM_MEMORY);
      if (commitOffsetValue > 0) {
        commitOffsetEnable = true;
      }
    }

    String subExpression = null;
    boolean classFilter = false;
    SubscriptionData sd = this.rebalanceImpl.getSubscriptionInner().get(pullRequest.getMessageQueue().getTopic());
    if (sd != null) {
      if (this.defaultMQPushConsumer.isPostSubscriptionWhenPull() && !sd.isClassFilterMode()) {
        subExpression = sd.getSubString();
      }

      classFilter = sd.isClassFilterMode();
    }

    int sysFlag = PullSysFlag.buildSysFlag(
            commitOffsetEnable, // commitOffset
            true, // suspend
            subExpression != null, // subscription
            classFilter // class filter
    );
    try {
      this.pullAPIWrapper.pullKernelImpl(
              pullRequest.getMessageQueue(),
              subExpression,
              subscriptionData.getExpressionType(),
              subscriptionData.getSubVersion(),
              pullRequest.getNextOffset(),
              this.defaultMQPushConsumer.getPullBatchSize(),
              this.defaultMQPushConsumer.getPullBatchSizeInBytes(),
              sysFlag,
              commitOffsetValue,
              BROKER_SUSPEND_MAX_TIME_MILLIS,
              CONSUMER_TIMEOUT_MILLIS_WHEN_SUSPEND,
              CommunicationMode.ASYNC,
              pullCallback
      );
    } catch (Exception e) {
      log.error("pullKernelImpl exception", e);
      this.executePullRequestLater(pullRequest, pullTimeDelayMillsWhenException);
    }
  }
}
```


#### concurrent

```java
public class ConsumeMessageConcurrentlyService implements ConsumeMessageService {
  private static final InternalLogger log = ClientLogger.getLog();
  private final DefaultMQPushConsumerImpl defaultMQPushConsumerImpl;
  private final DefaultMQPushConsumer defaultMQPushConsumer;
  private final MessageListenerConcurrently messageListener;
  private final BlockingQueue<Runnable> consumeRequestQueue;
  private final ThreadPoolExecutor consumeExecutor;
  private final String consumerGroup;

  private final ScheduledExecutorService scheduledExecutorService;
  private final ScheduledExecutorService cleanExpireMsgExecutors;

  public ConsumeMessageConcurrentlyService(DefaultMQPushConsumerImpl defaultMQPushConsumerImpl,
                                           MessageListenerConcurrently messageListener) {
    this.defaultMQPushConsumerImpl = defaultMQPushConsumerImpl;
    this.messageListener = messageListener;

    this.defaultMQPushConsumer = this.defaultMQPushConsumerImpl.getDefaultMQPushConsumer();
    this.consumerGroup = this.defaultMQPushConsumer.getConsumerGroup();
    this.consumeRequestQueue = new LinkedBlockingQueue<Runnable>();

    String consumeThreadPrefix = null;
    if (consumerGroup.length() > 100) {
      consumeThreadPrefix = new StringBuilder("ConsumeMessageThread_").append(consumerGroup, 0, 100).append("_").toString();
    } else {
      consumeThreadPrefix = new StringBuilder("ConsumeMessageThread_").append(consumerGroup).append("_").toString();
    }
    this.consumeExecutor = new ThreadPoolExecutor(
            this.defaultMQPushConsumer.getConsumeThreadMin(),
            this.defaultMQPushConsumer.getConsumeThreadMax(),
            1000 * 60,
            TimeUnit.MILLISECONDS,
            this.consumeRequestQueue,
            new ThreadFactoryImpl(consumeThreadPrefix));

    this.scheduledExecutorService = Executors.newSingleThreadScheduledExecutor(new ThreadFactoryImpl("ConsumeMessageScheduledThread_"));
    this.cleanExpireMsgExecutors = Executors.newSingleThreadScheduledExecutor(new ThreadFactoryImpl("CleanExpireMsgScheduledThread_"));
  }
}
```

### PullConsumer




## Links

- [MQ](/docs/CS/MQ/MQ.md?id=RocketMQ)

## References

1. [RocketMQ技术内幕](https://book.douban.com/subject/35626441/)
