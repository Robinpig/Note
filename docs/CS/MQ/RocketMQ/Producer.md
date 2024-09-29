## Introduction

The producers of Apache RocketMQ are underlying resources that can be reused, like the connection pool of a database.
You do not need to create producers each time you send messages or destroy the producers after you send messages.
If you regularly create and destroy producers, a large number of short connection requests are generated on the broker.
We recommend that you create and initialize the minimum number of producers that your business scenarios require, and reuse as many producers as you can.

DefaultMQProducerImpl 封装了大部分 Producer 的业务逻辑，
MQClientInstance 封装了客户端一些通用的业务逻辑，MQClientAPIImpl 封装了客户端与服务端的 RPC，NettyRemotingClient 实现了底层网络通信。


```java
public class DefaultMQProducer extends ClientConfig implements MQProducer {
    public void start() throws MQClientException {
        this.setProducerGroup(withNamespace(this.producerGroup));
        this.defaultMQProducerImpl.start();
        if (this.produceAccumulator != null) {
            this.produceAccumulator.start();
        }
        if (enableTrace) {
            try {
                AsyncTraceDispatcher dispatcher = new AsyncTraceDispatcher(producerGroup, TraceDispatcher.Type.PRODUCE, traceTopic, rpcHook);
                dispatcher.setHostProducer(this.defaultMQProducerImpl);
                dispatcher.setNamespaceV2(this.namespaceV2);
                traceDispatcher = dispatcher;
                this.defaultMQProducerImpl.registerSendMessageHook(
                        new SendMessageTraceHookImpl(traceDispatcher));
                this.defaultMQProducerImpl.registerEndTransactionHook(
                        new EndTransactionTraceHookImpl(traceDispatcher));
            } catch (Throwable e) {
                logger.error("system mqtrace hook init failed ,maybe can't send msg trace data");
            }
        }
        if (null != traceDispatcher) {
            if (traceDispatcher instanceof AsyncTraceDispatcher) {
                ((AsyncTraceDispatcher) traceDispatcher).getTraceProducer().setUseTLS(isUseTLS());
            }
            try {
                traceDispatcher.start(this.getNamesrvAddr(), this.getAccessChannel());
            } catch (MQClientException e) {
                logger.warn("trace dispatcher start failed ", e);
            }
        }
    }
}
```


```java
public class DefaultMQProducerImpl implements MQProducerInner {
    public void start() throws MQClientException {
        this.start(true);
    }

    public void start(final boolean startFactory) throws MQClientException {
        switch (this.serviceState) {
            case CREATE_JUST:
                this.serviceState = ServiceState.START_FAILED;

                this.checkConfig();

                if (!this.defaultMQProducer.getProducerGroup().equals(MixAll.CLIENT_INNER_PRODUCER_GROUP)) {
                    this.defaultMQProducer.changeInstanceNameToPID();
                }

                this.mQClientFactory = MQClientManager.getInstance().getOrCreateMQClientInstance(this.defaultMQProducer, rpcHook);

                boolean registerOK = mQClientFactory.registerProducer(this.defaultMQProducer.getProducerGroup(), this);
                if (!registerOK) {
                    this.serviceState = ServiceState.CREATE_JUST;
                    throw new MQClientException("The producer group[" + this.defaultMQProducer.getProducerGroup()
                            + "] has been created before, specify another name please." + FAQUrl.suggestTodo(FAQUrl.GROUP_NAME_DUPLICATE_URL),
                            null);
                }

                if (startFactory) {
                    mQClientFactory.start();
                }

                this.initTopicRoute();

                this.mqFaultStrategy.startDetector();

                log.info("the producer [{}] start OK. sendMessageWithVIPChannel={}", this.defaultMQProducer.getProducerGroup(),
                        this.defaultMQProducer.isSendMessageWithVIPChannel());
                this.serviceState = ServiceState.RUNNING;
                break;
            case RUNNING:
            case START_FAILED:
            case SHUTDOWN_ALREADY:
                throw new MQClientException("The producer service state not OK, maybe started once, "
                        + this.serviceState
                        + FAQUrl.suggestTodo(FAQUrl.CLIENT_SERVICE_NOT_OK),
                        null);
            default:
                break;
        }

        this.mQClientFactory.sendHeartbeatToAllBrokerWithLock();

        RequestFutureHolder.getInstance().startScheduledTask(this);
    }
}
```
## send

```java
public SendResult send(Message msg,
      long timeout) throws MQClientException, RemotingException, MQBrokerException, InterruptedException {
      return this.sendDefaultImpl(msg, CommunicationMode.SYNC, null, timeout);
  }
```

1. tryToFindTopicPublishInfo -> update Topic
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



### tryToFindTopicPublishInfo
从本地缓存(ConcurrentMap< String/\* topic \*/, TopicPublishInfo>)中尝试获取，第一次肯定为空
尝试从 NameServer 获取配置信息并更新本地缓存配置。
如果找到可用的路由信息并返回。
如果未找到路由信息，则再次尝试使用默认的 topic 去找路由配置信息。
```java
private TopicPublishInfo tryToFindTopicPublishInfo(final String topic) {
    TopicPublishInfo topicPublishInfo = this.topicPublishInfoTable.get(topic);
    if (null == topicPublishInfo || !topicPublishInfo.ok()) {
        this.topicPublishInfoTable.putIfAbsent(topic, new TopicPublishInfo());
        this.mQClientFactory.updateTopicRouteInfoFromNameServer(topic);
        topicPublishInfo = this.topicPublishInfoTable.get(topic);
    }

    if (topicPublishInfo.isHaveTopicRouterInfo() || topicPublishInfo.ok()) {
        return topicPublishInfo;
    } else {
        this.mQClientFactory.updateTopicRouteInfoFromNameServer(topic, true, this.defaultMQProducer);
        topicPublishInfo = this.topicPublishInfoTable.get(topic);
        return topicPublishInfo;
    }
}
```
代码@1：为了避免重复从 NameServer 获取配置信息，在这里使用了ReentrantLock,并且设有超时时间。固定为3000s。
代码@2，@3的区别，一个是获取默认 topic 的配置信息，一个是获取指定 topic 的配置信息，该方法在这里就不跟踪进去了，具体的实现就是通过与 NameServer 的长连接 Channel 发送 GET_ROUTEINTO_BY_TOPIC (105)命令，获取配置信息。注意，次过程的超时时间为3s，由此可见，NameServer的实现要求高效。
代码@4、@5、@6：从这里开始，拿到最新的 topic 路由信息后，需要与本地缓存中的 topic 发布信息进行比较，如果有变化，则需要同步更新发送者、消费者关于该 topic 的缓存。
代码@7：更新发送者的缓存。
代码@8：更新订阅者的缓存（消费队列信息）。
至此tryToFindTopicPublishInfo 运行完毕，从 NameServe r获取 TopicPublishData，继续消息发送的第二个步骤，选取一个消息队列


```java
public boolean updateTopicRouteInfoFromNameServer(final String topic, boolean isDefault,
    DefaultMQProducer defaultMQProducer) {
    try {
        if (this.lockNamesrv.tryLock(LOCK_TIMEOUT_MILLIS, TimeUnit.MILLISECONDS)) {
            try {
                TopicRouteData topicRouteData;
                if (isDefault && defaultMQProducer != null) {
                    topicRouteData = this.mQClientAPIImpl.getDefaultTopicRouteInfoFromNameServer(clientConfig.getMqClientApiTimeout());
                    if (topicRouteData != null) {
                        for (QueueData data : topicRouteData.getQueueDatas()) {
                            int queueNums = Math.min(defaultMQProducer.getDefaultTopicQueueNums(), data.getReadQueueNums());
                            data.setReadQueueNums(queueNums);
                            data.setWriteQueueNums(queueNums);
                        }
                    }
                } else {
                    topicRouteData = this.mQClientAPIImpl.getTopicRouteInfoFromNameServer(topic, clientConfig.getMqClientApiTimeout());
                }
                if (topicRouteData != null) {
                    TopicRouteData old = this.topicRouteTable.get(topic);
                    boolean changed = topicRouteData.topicRouteDataChanged(old);
                    if (!changed) {
                        changed = this.isNeedUpdateTopicRouteInfo(topic);
                    } else {
                        log.info("the topic[{}] route info changed, old[{}] ,new[{}]", topic, old, topicRouteData);
                    }

                    if (changed) {

                        for (BrokerData bd : topicRouteData.getBrokerDatas()) {
                            this.brokerAddrTable.put(bd.getBrokerName(), bd.getBrokerAddrs());
                        }

                        // Update endpoint map
                        {
                            ConcurrentMap<MessageQueue, String> mqEndPoints = topicRouteData2EndpointsForStaticTopic(topic, topicRouteData);
                            if (!mqEndPoints.isEmpty()) {
                                topicEndPointsTable.put(topic, mqEndPoints);
                            }
                        }

                        // Update Pub info
                        {
                            TopicPublishInfo publishInfo = topicRouteData2TopicPublishInfo(topic, topicRouteData);
                            publishInfo.setHaveTopicRouterInfo(true);
                            for (Entry<String, MQProducerInner> entry : this.producerTable.entrySet()) {
                                MQProducerInner impl = entry.getValue();
                                if (impl != null) {
                                    impl.updateTopicPublishInfo(topic, publishInfo);
                                }
                            }
                        }

                        // Update sub info
                        if (!consumerTable.isEmpty()) {
                            Set<MessageQueue> subscribeInfo = topicRouteData2TopicSubscribeInfo(topic, topicRouteData);
                            for (Entry<String, MQConsumerInner> entry : this.consumerTable.entrySet()) {
                                MQConsumerInner impl = entry.getValue();
                                if (impl != null) {
                                    impl.updateTopicSubscribeInfo(topic, subscribeInfo);
                                }
                            }
                        }
                        TopicRouteData cloneTopicRouteData = new TopicRouteData(topicRouteData);
                        log.info("topicRouteTable.put. Topic = {}, TopicRouteData[{}]", topic, cloneTopicRouteData);
                        this.topicRouteTable.put(topic, cloneTopicRouteData);
                        return true;
                    }
                } else {
                    log.warn("updateTopicRouteInfoFromNameServer, getTopicRouteInfoFromNameServer return null, Topic: {}. [{}]", topic, this.clientId);
                }
            } catch (MQClientException e) {
                if (!topic.startsWith(MixAll.RETRY_GROUP_TOPIC_PREFIX) && !topic.equals(TopicValidator.AUTO_CREATE_TOPIC_KEY_TOPIC)) {
                    log.warn("updateTopicRouteInfoFromNameServer Exception", e);
                }
            } catch (RemotingException e) {
                log.error("updateTopicRouteInfoFromNameServer Exception", e);
                throw new IllegalStateException(e);
            } finally {
                this.lockNamesrv.unlock();
            }
        } else {
            log.warn("updateTopicRouteInfoFromNameServer tryLock timeout {}ms. [{}]", LOCK_TIMEOUT_MILLIS, this.clientId);
        }
    } catch (InterruptedException e) {
        log.warn("updateTopicRouteInfoFromNameServer Exception", e);
    }

    return false;
}
```
sendLatencyFaultEnable，是否开启消息失败延迟规避机制，该值在消息发送者那里可以设置，如果该值为false,直接从 topic 的所有队列中选择下一个，而不考虑该消息队列是否可用（比如Broker挂掉）。
代码@2-start--end,这里使用了本地线程变量 ThreadLocal 保存上一次发送的消息队列下标，消息发送使用轮询机制获取下一个发送消息队列。
代码@2对 topic 所有的消息队列进行一次验证，为什么要循环呢？因为加入了发送异常延迟，要确保选中的消息队列(MessageQueue)所在的Broker是正常的。
代码@3：判断当前的消息队列是否可用。
要理解代码@2，@3 处的逻辑，我们就需要理解 RocketMQ 发送消息延迟机制，具体实现类：MQFaultStrategy
latencyMax：最大延迟时间数值，在消息发送之前，先记录当前时间（start），然后消息发送成功或失败时记录当前时间（end），(end-start)代表一次消息延迟时间，发送错误时，updateFaultItem 中 isolation 为 true，与 latencyMax 中值进行比较时得值为 30s,也就时该 broke r在接下来得 600000L，也就时5分钟内不提供服务，等待该 Broker 的恢复

计算出来的延迟值+加上本次消息的延迟值，设置 为FaultItem 的 startTimestamp,表示当前时间必须大于该 startTimestamp 时，该 broker 才重新参与 MessageQueue 的负载。
从@2--@3，一旦一个 MessageQueue 符合条件，即刻返回，但该 Topic 所在的所 有Broker全部标记不可用时，进入到下一步逻辑处理。（在此处，我们要知道，标记为不可用，并不代表真的不可用，Broker 是可以在故障期间被运营管理人员进行恢复的，比如重启）。
代码@4，5：根据 Broker 的 startTimestart 进行一个排序，值越小，排前面，然后再选择一个，返回（此时不能保证一定可用，会抛出异常，如果消息发送方式是同步调用，则有重试机制）。
接下来将进入到消息发送的第三步，发现消息


executeAsyncMessageSend


```java
public class DefaultMQProducerImpl implements MQProducerInner {
    public void executeAsyncMessageSend(Runnable runnable, final Message msg, final BackpressureSendCallBack sendCallback,
                                        final long timeout, final long beginStartTime)
            throws MQClientException, InterruptedException {
        ExecutorService executor = this.getAsyncSenderExecutor();
        boolean isEnableBackpressureForAsyncMode = this.getDefaultMQProducer().isEnableBackpressureForAsyncMode();
        boolean isSemaphoreAsyncNumbAcquired = false;
        boolean isSemaphoreAsyncSizeAcquired = false;
        int msgLen = msg.getBody() == null ? 1 : msg.getBody().length;

        try {
            if (isEnableBackpressureForAsyncMode) {
                long costTime = System.currentTimeMillis() - beginStartTime;
                isSemaphoreAsyncNumbAcquired = timeout - costTime > 0
                        && semaphoreAsyncSendNum.tryAcquire(timeout - costTime, TimeUnit.MILLISECONDS);
                if (!isSemaphoreAsyncNumbAcquired) {
                    sendCallback.onException(
                            new RemotingTooMuchRequestException("send message tryAcquire semaphoreAsyncNum timeout"));
                    return;
                }
                costTime = System.currentTimeMillis() - beginStartTime;
                isSemaphoreAsyncSizeAcquired = timeout - costTime > 0
                        && semaphoreAsyncSendSize.tryAcquire(msgLen, timeout - costTime, TimeUnit.MILLISECONDS);
                if (!isSemaphoreAsyncSizeAcquired) {
                    sendCallback.onException(
                            new RemotingTooMuchRequestException("send message tryAcquire semaphoreAsyncSize timeout"));
                    return;
                }
            }
            sendCallback.isSemaphoreAsyncSizeAcquired = isSemaphoreAsyncSizeAcquired;
            sendCallback.isSemaphoreAsyncNumbAcquired = isSemaphoreAsyncNumbAcquired;
            sendCallback.msgLen = msgLen;
            executor.submit(runnable);
        } catch (RejectedExecutionException e) {
            if (isEnableBackpressureForAsyncMode) {
                runnable.run();
            } else {
                throw new MQClientException("executor rejected ", e);
            }
        }
    }
}
```


### sendKernelImpl

```java

    private SendResult sendKernelImpl(final Message msg,
        final MessageQueue mq,
        final CommunicationMode communicationMode,
        final SendCallback sendCallback,
        final TopicPublishInfo topicPublishInfo,
        final long timeout) throws MQClientException, RemotingException, MQBrokerException, InterruptedException {
        long beginStartTime = System.currentTimeMillis();
        String brokerName = this.mQClientFactory.getBrokerNameFromMessageQueue(mq);
        String brokerAddr = this.mQClientFactory.findBrokerAddressInPublish(brokerName);
        if (null == brokerAddr) {
            tryToFindTopicPublishInfo(mq.getTopic());
            brokerName = this.mQClientFactory.getBrokerNameFromMessageQueue(mq);
            brokerAddr = this.mQClientFactory.findBrokerAddressInPublish(brokerName);
        }

        SendMessageContext context = null;
        if (brokerAddr != null) {
            brokerAddr = MixAll.brokerVIPChannel(this.defaultMQProducer.isSendMessageWithVIPChannel(), brokerAddr);

            byte[] prevBody = msg.getBody();
            try {
                //for MessageBatch,ID has been set in the generating process
                if (!(msg instanceof MessageBatch)) {
                    MessageClientIDSetter.setUniqID(msg);
                }

                boolean topicWithNamespace = false;
                if (null != this.mQClientFactory.getClientConfig().getNamespace()) {
                    msg.setInstanceId(this.mQClientFactory.getClientConfig().getNamespace());
                    topicWithNamespace = true;
                }

                int sysFlag = 0;
                boolean msgBodyCompressed = false;
                if (this.tryToCompressMessage(msg)) {
                    sysFlag |= MessageSysFlag.COMPRESSED_FLAG;
                    sysFlag |= compressType.getCompressionFlag();
                    msgBodyCompressed = true;
                }

                final String tranMsg = msg.getProperty(MessageConst.PROPERTY_TRANSACTION_PREPARED);
                if (Boolean.parseBoolean(tranMsg)) {
                    sysFlag |= MessageSysFlag.TRANSACTION_PREPARED_TYPE;
                }

                if (hasCheckForbiddenHook()) {
                    CheckForbiddenContext checkForbiddenContext = new CheckForbiddenContext();
                    checkForbiddenContext.setNameSrvAddr(this.defaultMQProducer.getNamesrvAddr());
                    checkForbiddenContext.setGroup(this.defaultMQProducer.getProducerGroup());
                    checkForbiddenContext.setCommunicationMode(communicationMode);
                    checkForbiddenContext.setBrokerAddr(brokerAddr);
                    checkForbiddenContext.setMessage(msg);
                    checkForbiddenContext.setMq(mq);
                    checkForbiddenContext.setUnitMode(this.isUnitMode());
                    this.executeCheckForbiddenHook(checkForbiddenContext);
                }

                if (this.hasSendMessageHook()) {
                    context = new SendMessageContext();
                    context.setProducer(this);
                    context.setProducerGroup(this.defaultMQProducer.getProducerGroup());
                    context.setCommunicationMode(communicationMode);
                    context.setBornHost(this.defaultMQProducer.getClientIP());
                    context.setBrokerAddr(brokerAddr);
                    context.setMessage(msg);
                    context.setMq(mq);
                    context.setNamespace(this.defaultMQProducer.getNamespace());
                    String isTrans = msg.getProperty(MessageConst.PROPERTY_TRANSACTION_PREPARED);
                    if (isTrans != null && isTrans.equals("true")) {
                        context.setMsgType(MessageType.Trans_Msg_Half);
                    }

                    if (msg.getProperty("__STARTDELIVERTIME") != null || msg.getProperty(MessageConst.PROPERTY_DELAY_TIME_LEVEL) != null) {
                        context.setMsgType(MessageType.Delay_Msg);
                    }
                    this.executeSendMessageHookBefore(context);
                }

                SendMessageRequestHeader requestHeader = new SendMessageRequestHeader();
                requestHeader.setProducerGroup(this.defaultMQProducer.getProducerGroup());
                requestHeader.setTopic(msg.getTopic());
                requestHeader.setDefaultTopic(this.defaultMQProducer.getCreateTopicKey());
                requestHeader.setDefaultTopicQueueNums(this.defaultMQProducer.getDefaultTopicQueueNums());
                requestHeader.setQueueId(mq.getQueueId());
                requestHeader.setSysFlag(sysFlag);
                requestHeader.setBornTimestamp(System.currentTimeMillis());
                requestHeader.setFlag(msg.getFlag());
                requestHeader.setProperties(MessageDecoder.messageProperties2String(msg.getProperties()));
                requestHeader.setReconsumeTimes(0);
                requestHeader.setUnitMode(this.isUnitMode());
                requestHeader.setBatch(msg instanceof MessageBatch);
                if (requestHeader.getTopic().startsWith(MixAll.RETRY_GROUP_TOPIC_PREFIX)) {
                    String reconsumeTimes = MessageAccessor.getReconsumeTime(msg);
                    if (reconsumeTimes != null) {
                        requestHeader.setReconsumeTimes(Integer.valueOf(reconsumeTimes));
                        MessageAccessor.clearProperty(msg, MessageConst.PROPERTY_RECONSUME_TIME);
                    }

                    String maxReconsumeTimes = MessageAccessor.getMaxReconsumeTimes(msg);
                    if (maxReconsumeTimes != null) {
                        requestHeader.setMaxReconsumeTimes(Integer.valueOf(maxReconsumeTimes));
                        MessageAccessor.clearProperty(msg, MessageConst.PROPERTY_MAX_RECONSUME_TIMES);
                    }
                }

                SendResult sendResult = null;
                switch (communicationMode) {
                    case ASYNC:
                        Message tmpMessage = msg;
                        boolean messageCloned = false;
                        if (msgBodyCompressed) {
                            //If msg body was compressed, msgbody should be reset using prevBody.
                            //Clone new message using commpressed message body and recover origin massage.
                            //Fix bug:https://github.com/apache/rocketmq-externals/issues/66
                            tmpMessage = MessageAccessor.cloneMessage(msg);
                            messageCloned = true;
                            msg.setBody(prevBody);
                        }

                        if (topicWithNamespace) {
                            if (!messageCloned) {
                                tmpMessage = MessageAccessor.cloneMessage(msg);
                                messageCloned = true;
                            }
                            msg.setTopic(NamespaceUtil.withoutNamespace(msg.getTopic(), this.defaultMQProducer.getNamespace()));
                        }

                        long costTimeAsync = System.currentTimeMillis() - beginStartTime;
                        if (timeout < costTimeAsync) {
                            throw new RemotingTooMuchRequestException("sendKernelImpl call timeout");
                        }
                        sendResult = this.mQClientFactory.getMQClientAPIImpl().sendMessage(
                            brokerAddr,
                            brokerName,
                            tmpMessage,
                            requestHeader,
                            timeout - costTimeAsync,
                            communicationMode,
                            sendCallback,
                            topicPublishInfo,
                            this.mQClientFactory,
                            this.defaultMQProducer.getRetryTimesWhenSendAsyncFailed(),
                            context,
                            this);
                        break;
                    case ONEWAY:
                    case SYNC:
                        long costTimeSync = System.currentTimeMillis() - beginStartTime;
                        if (timeout < costTimeSync) {
                            throw new RemotingTooMuchRequestException("sendKernelImpl call timeout");
                        }
                        sendResult = this.mQClientFactory.getMQClientAPIImpl().sendMessage(
                            brokerAddr,
                            brokerName,
                            msg,
                            requestHeader,
                            timeout - costTimeSync,
                            communicationMode,
                            context,
                            this);
                        break;
                    default:
                        assert false;
                        break;
                }

                if (this.hasSendMessageHook()) {
                    context.setSendResult(sendResult);
                    this.executeSendMessageHookAfter(context);
                }

                return sendResult;
            } catch (RemotingException e) {
                if (this.hasSendMessageHook()) {
                    context.setException(e);
                    this.executeSendMessageHookAfter(context);
                }
                throw e;
            } catch (MQBrokerException e) {
                if (this.hasSendMessageHook()) {
                    context.setException(e);
                    this.executeSendMessageHookAfter(context);
                }
                throw e;
            } catch (InterruptedException e) {
                if (this.hasSendMessageHook()) {
                    context.setException(e);
                    this.executeSendMessageHookAfter(context);
                }
                throw e;
            } finally {
                msg.setBody(prevBody);
                msg.setTopic(NamespaceUtil.withoutNamespace(msg.getTopic(), this.defaultMQProducer.getNamespace()));
            }
        }

        throw new MQClientException("The broker[" + brokerName + "] not exist", null);
    }

```
batch does not support compressing right now

compression related

```java
 private int compressLevel = Integer.parseInt(System.getProperty(MixAll.MESSAGE_COMPRESS_LEVEL, "5"));
private CompressionType compressType = CompressionType.of(System.getProperty(MixAll.MESSAGE_COMPRESS_TYPE, "ZLIB"));
// Compress message body threshold, namely, message body larger than 4k will be compressed on default.
private int compressMsgBodyOverHowmuch = 1024 * 4;
```

default not enable batch message

retry

```java
 /**
     * Maximum number of retry to perform internally before claiming sending failure in synchronous mode. </p>
     * <p>
     * This may potentially cause message duplication which is up to application developers to resolve.
     */
    private int retryTimesWhenSendFailed = 2;

    /**
     * Maximum number of retry to perform internally before claiming sending failure in asynchronous mode. </p>
     * <p>
     * This may potentially cause message duplication which is up to application developers to resolve.
     */
    private int retryTimesWhenSendAsyncFailed = 2;

    /**
     * Indicate whether to retry another broker on sending failure internally.
     */
    private boolean retryAnotherBrokerWhenNotStoreOK = false;

    /**
     * Maximum allowed message body size in bytes.
     */
    private int maxMessageSize = 1024 * 1024 * 4; // 4M


```

#### sendMessage

```java
public class MQClientAPIImpl implements NameServerUpdateCallback {
    public SendResult sendMessage(
            final String addr,
            final String brokerName,
            final Message msg,
            final SendMessageRequestHeader requestHeader,
            final long timeoutMillis,
            final CommunicationMode communicationMode,
            final SendCallback sendCallback,
            final TopicPublishInfo topicPublishInfo,
            final MQClientInstance instance,
            final int retryTimesWhenSendFailed,
            final SendMessageContext context,
            final DefaultMQProducerImpl producer
    ) throws RemotingException, MQBrokerException, InterruptedException {
        long beginStartTime = System.currentTimeMillis();
        RemotingCommand request = null;
        String msgType = msg.getProperty(MessageConst.PROPERTY_MESSAGE_TYPE);
        boolean isReply = msgType != null && msgType.equals(MixAll.REPLY_MESSAGE_FLAG);
        if (isReply) {
            if (sendSmartMsg) {
                SendMessageRequestHeaderV2 requestHeaderV2 = SendMessageRequestHeaderV2.createSendMessageRequestHeaderV2(requestHeader);
                request = RemotingCommand.createRequestCommand(RequestCode.SEND_REPLY_MESSAGE_V2, requestHeaderV2);
            } else {
                request = RemotingCommand.createRequestCommand(RequestCode.SEND_REPLY_MESSAGE, requestHeader);
            }
        } else {
            if (sendSmartMsg || msg instanceof MessageBatch) {
                SendMessageRequestHeaderV2 requestHeaderV2 = SendMessageRequestHeaderV2.createSendMessageRequestHeaderV2(requestHeader);
                request = RemotingCommand.createRequestCommand(msg instanceof MessageBatch ? RequestCode.SEND_BATCH_MESSAGE : RequestCode.SEND_MESSAGE_V2, requestHeaderV2);
            } else {
                request = RemotingCommand.createRequestCommand(RequestCode.SEND_MESSAGE, requestHeader);
            }
        }
        request.setBody(msg.getBody());

        switch (communicationMode) {
            case ONEWAY:
                this.remotingClient.invokeOneway(addr, request, timeoutMillis);
                return null;
            case ASYNC:
                final AtomicInteger times = new AtomicInteger();
                long costTimeAsync = System.currentTimeMillis() - beginStartTime;
                if (timeoutMillis < costTimeAsync) {
                    throw new RemotingTooMuchRequestException("sendMessage call timeout");
                }
                this.sendMessageAsync(addr, brokerName, msg, timeoutMillis - costTimeAsync, request, sendCallback, topicPublishInfo, instance,
                        retryTimesWhenSendFailed, times, context, producer);
                return null;
            case SYNC:
                long costTimeSync = System.currentTimeMillis() - beginStartTime;
                if (timeoutMillis < costTimeSync) {
                    throw new RemotingTooMuchRequestException("sendMessage call timeout");
                }
                return this.sendMessageSync(addr, brokerName, msg, timeoutMillis - costTimeSync, request);
            default:
                assert false;
                break;
        }

        return null;
    }
}
```

### FaultStrategy

if sendLatencyFaultEnable = true

```java
public class MQFaultStrategy {
  public MessageQueue selectOneMessageQueue(final TopicPublishInfo tpInfo, final String lastBrokerName) {
    if (this.sendLatencyFaultEnable) {
      try {
        int index = tpInfo.getSendWhichQueue().incrementAndGet();
        for (int i = 0; i < tpInfo.getMessageQueueList().size(); i++) {
          int pos = Math.abs(index++) % tpInfo.getMessageQueueList().size();
          if (pos < 0)
            pos = 0;
          MessageQueue mq = tpInfo.getMessageQueueList().get(pos);
          if (latencyFaultTolerance.isAvailable(mq.getBrokerName()))
            return mq;
        }

        final String notBestBroker = latencyFaultTolerance.pickOneAtLeast();
        int writeQueueNums = tpInfo.getQueueIdByBroker(notBestBroker);
        if (writeQueueNums > 0) {
          final MessageQueue mq = tpInfo.selectOneMessageQueue();
          if (notBestBroker != null) {
            mq.setBrokerName(notBestBroker);
            mq.setQueueId(tpInfo.getSendWhichQueue().incrementAndGet() % writeQueueNums);
          }
          return mq;
        } else {
          latencyFaultTolerance.remove(notBestBroker);
        }
      } catch (Exception e) {
        log.error("Error occurred when selecting message queue", e);
      }

      return tpInfo.selectOneMessageQueue();
    }

    return tpInfo.selectOneMessageQueue(lastBrokerName);
  }
}
```

else sendLatencyFaultEnable = false
#### selectOneMessageQueue


```java
public class TopicPublishInfo {
  public MessageQueue selectOneMessageQueue(final String lastBrokerName) {
    if (lastBrokerName == null) {
      return selectOneMessageQueue();
    } else {
      for (int i = 0; i < this.messageQueueList.size(); i++) {
        int index = this.sendWhichQueue.incrementAndGet();
        int pos = Math.abs(index) % this.messageQueueList.size();
        if (pos < 0)
          pos = 0;
        MessageQueue mq = this.messageQueueList.get(pos);
        if (!mq.getBrokerName().equals(lastBrokerName)) {
          return mq;
        }
      }
      return selectOneMessageQueue();
    }
  }

  public MessageQueue selectOneMessageQueue() {
    int index = this.sendWhichQueue.incrementAndGet();
    int pos = Math.abs(index) % this.messageQueueList.size();
    if (pos < 0)
      pos = 0;
    return this.messageQueueList.get(pos);
  }
}
```

### MQClientInstance

a JVM only has one MQClientInstance

DefaultMQProducerImpl#start -> MQClientManager#getAndCreateMQClientInstance

```java
public class MQClientInstance {
  
  
}
```

#### MQClientInstance#start

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
          // Start request-response channel, NettyRemotingClient
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


```java
public class ConsistentHashRouter<T extends Node> {
    private final SortedMap<Long, VirtualNode<T>> ring = new TreeMap<>();
    private final HashFunction hashFunction;
    public T routeNode(String objectKey) {
        if (ring.isEmpty()) {
            return null;
        }
        Long hashVal = hashFunction.hash(objectKey);
        SortedMap<Long, VirtualNode<T>> tailMap = ring.tailMap(hashVal);
        Long nodeHashVal = !tailMap.isEmpty() ? tailMap.firstKey() : ring.firstKey();
        return ring.get(nodeHashVal).getPhysicalNode();
    }
}
```

## Links

- [RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)