## Introduction



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

## PushConsumer
PUSH 模式是对 PULL 模式的封装，类似于一个高级 API

- RebalanceImpl
- 
### start
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



### pullMessage



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


    private void pullMessage(final PullRequest pullRequest) {
        final MQConsumerInner consumer = this.mQClientFactory.selectConsumer(pullRequest.getConsumerGroup());
        if (consumer != null) {
            DefaultMQPushConsumerImpl impl = (DefaultMQPushConsumerImpl) consumer;
            impl.pullMessage(pullRequest);
        } else {
            log.warn("No matched consumer for the PullRequest {}, drop it", pullRequest);
        }
    }
}
```

DefaultMQPushConsumerImpl#pullMessage
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

## PullConsumer





```java
public class PullMessageService extends ServiceThread {
  private void pullMessage(final PullRequest pullRequest) {
      final MQConsumerInner consumer = this.mQClientFactory.selectConsumer(pullRequest.getConsumerGroup());
      if (consumer != null) {
          DefaultMQPushConsumerImpl impl = (DefaultMQPushConsumerImpl) consumer;
          impl.pullMessage(pullRequest);
      } else {
          logger.warn("No matched consumer for the PullRequest {}, drop it", pullRequest);
      }
  }
}
```







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
            this.executePullRequestLater(pullRequest, PULL_TIME_DELAY_MILLS_WHEN_CACHE_FLOW_CONTROL);
            if ((queueFlowControlTimes++ % 1000) == 0) {
                log.warn(
                    "the cached message count exceeds the threshold {}, so do flow control, minOffset={}, maxOffset={}, count={}, size={} MiB, pullRequest={}, flowControlTimes={}",
                    this.defaultMQPushConsumer.getPullThresholdForQueue(), processQueue.getMsgTreeMap().firstKey(), processQueue.getMsgTreeMap().lastKey(), cachedMessageCount, cachedMessageSizeInMiB, pullRequest, queueFlowControlTimes);
            }
            return;
        }

        if (cachedMessageSizeInMiB > this.defaultMQPushConsumer.getPullThresholdSizeForQueue()) {
            this.executePullRequestLater(pullRequest, PULL_TIME_DELAY_MILLS_WHEN_CACHE_FLOW_CONTROL);
            if ((queueFlowControlTimes++ % 1000) == 0) {
                log.warn(
                    "the cached message size exceeds the threshold {} MiB, so do flow control, minOffset={}, maxOffset={}, count={}, size={} MiB, pullRequest={}, flowControlTimes={}",
                    this.defaultMQPushConsumer.getPullThresholdSizeForQueue(), processQueue.getMsgTreeMap().firstKey(), processQueue.getMsgTreeMap().lastKey(), cachedMessageCount, cachedMessageSizeInMiB, pullRequest, queueFlowControlTimes);
            }
            return;
        }

        if (!this.consumeOrderly) {
            if (processQueue.getMaxSpan() > this.defaultMQPushConsumer.getConsumeConcurrentlyMaxSpan()) {
                this.executePullRequestLater(pullRequest, PULL_TIME_DELAY_MILLS_WHEN_CACHE_FLOW_CONTROL);
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

        final MessageQueue messageQueue = pullRequest.getMessageQueue();
        final SubscriptionData subscriptionData = this.rebalanceImpl.getSubscriptionInner().get(messageQueue.getTopic());
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
                            DefaultMQPushConsumerImpl.this.executeTask(new Runnable() {

                                @Override
                                public void run() {
                                    try {
                                        DefaultMQPushConsumerImpl.this.offsetStore.updateAndFreezeOffset(pullRequest.getMessageQueue(),
                                            pullRequest.getNextOffset());

                                        DefaultMQPushConsumerImpl.this.offsetStore.persist(pullRequest.getMessageQueue());

                                        // removeProcessQueue will also remove offset to cancel the frozen status.
                                        DefaultMQPushConsumerImpl.this.rebalanceImpl.removeProcessQueue(pullRequest.getMessageQueue());
                                        DefaultMQPushConsumerImpl.this.rebalanceImpl.getmQClientFactory().rebalanceImmediately();

                                        log.warn("fix the pull request offset, {}", pullRequest);
                                    } catch (Throwable e) {
                                        log.error("executeTaskLater Exception", e);
                                    }
                                }
                            });
                            break;
                        default:
                            break;
                    }
                }
            }

            @Override
            public void onException(Throwable e) {
                if (!pullRequest.getMessageQueue().getTopic().startsWith(MixAll.RETRY_GROUP_TOPIC_PREFIX)) {
                    if (e instanceof MQBrokerException && ((MQBrokerException) e).getResponseCode() == ResponseCode.SUBSCRIPTION_NOT_LATEST) {
                        log.warn("the subscription is not latest, group={}, messageQueue={}", groupName(), messageQueue);
                    } else {
                        log.warn("execute the pull request exception, group={}, messageQueue={}", groupName(), messageQueue, e);
                    }
                }

                if (e instanceof MQBrokerException && ((MQBrokerException) e).getResponseCode() == ResponseCode.FLOW_CONTROL) {
                    DefaultMQPushConsumerImpl.this.executePullRequestLater(pullRequest, PULL_TIME_DELAY_MILLS_WHEN_BROKER_FLOW_CONTROL);
                } else {
                    DefaultMQPushConsumerImpl.this.executePullRequestLater(pullRequest, pullTimeDelayMillsWhenException);
                }
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

## pop

pop和push的差别是push可以在客户端和服务端都使用 而pop只在服务端使用

## Order



```java
public class ConsumeMessageOrderlyService implements ConsumeMessageService {
  	@Override
    public void submitConsumeRequest(
        final List<MessageExt> msgs,
        final ProcessQueue processQueue,
        final MessageQueue messageQueue,
        final boolean dispathToConsume) {
        if (dispathToConsume) {
            ConsumeRequest consumeRequest = new ConsumeRequest(processQueue, messageQueue);
            this.consumeExecutor.submit(consumeRequest);
        }
    }
}
```


## Rebalance

在 RocketMQ 客户端中会每隔 20s 去查询当前 Topic 的所有队列、消费者的个数，运用队列负载算法进行重新分配，然后与上一次的分配结果进行对比，如果发生了变化，则进行队列重新分配；如果没有发生变化，则忽略



**集群模式**下 消息消费进度存储在 Broker 端，`${ROCKETMQ_HOME}/store/config/consumerOffset.json` 是其具体的存储文件

消费进度的 Key 为 topic@consumeGroup，然后每一个队列一个偏移量。

**广播模式**的消费进度文件存储在用户的主目录，默认文件全路劲名：`${USER_HOME}/.rocketmq_offsets`。



RocketMQ 提供了并发消费、顺序消费两种消费模型。

- **并发消费**：对一个队列中消息，每一个消费者内部都会创建一个线程池，对队列中的消息多线程处理，即偏移量大的消息比偏移量小的消息有可能先消费。
- **顺序消费**：在某一项场景，例如 MySQL binlog 场景，需要消息按顺序进行消费。在 RocketMQ 中提供了基于队列的顺序消费模型，即尽管一个消费组中的消费者会创建一个多线程，但针对同一个 Queue，会加锁。

> 并发消费模型中，消息消费失败默认会重试 16 次，每一次的间隔时间不一样；而顺序消费，如果一条消息消费失败，则会一直消费，直到消费成功。故在顺序消费的使用过程中，应用程序需要区分系统异常、业务异常，如果是不符合业务规则导致的异常，则重试多少次都无法消费成功，这个时候一定要告警机制，及时进行人为干预，否则消费会积压。


## Links

- [RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)