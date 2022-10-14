## Introduction


- Producer
- Consumer
  - DefaultLitePullConsumer
  - DefaultMQPushConsumer
- Broker
- NameServer


Topic -> multi message queue(like partition)




PushConumser

Actually a pull





RebalanceService thread

pullRequestQueue





PullMessageProcessor of broker

## NameServer

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

## Links

- [MQ](/docs/CS/MQ/MQ.md?id=RocketMQ)



