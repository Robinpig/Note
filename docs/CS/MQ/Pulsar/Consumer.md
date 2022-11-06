## Introduction


Create a consumer builder with no schema (Schema.BYTES) for subscribing to one or more topics.
```java
Consumer<byte[]> consumer = client.newConsumer()
        .topic("my-topic")         
        .subscriptionName("my-subscription-name")         
        .subscribe();  

while (true) {      
    Message<byte[]> message = consumer.receive();      
    System.out.println("Got message: " + message.getValue());      
    consumer.acknowledge(message);  
}
```


```dot
digraph "Consumer" {

splines  = ortho;
fontname = "Inconsolata";

node [colorscheme = ylgnbu4];
edge [colorscheme = dark28, dir = both];

"Consumer<T>"                       [shape = record, label = "{ \<\<interface\>\>\nConsumer\<T\> |  }"];
"ConsumerBase<T>"                   [shape = record, label = "{ ConsumerBase\<T\> |  }"];
"ConsumerImpl<T>"                   [shape = record, label = "{ ConsumerImpl\<T\> |  }"];
"MultiTopicsConsumerImpl<T>"        [shape = record, label = "{ MultiTopicsConsumerImpl\<T\> |  }"];
"PatternMultiTopicsConsumerImpl<T>" [shape = record, label = "{ PatternMultiTopicsConsumerImpl\<T\> |  }"];
RawConsumerImpl                     [shape = record, label = "{ RawConsumerImpl |  }"];
RawReaderImpl                       [shape = record, label = "{ RawReaderImpl |  }"];
"ZeroQueueConsumerImpl<T>"          [shape = record, label = "{ ZeroQueueConsumerImpl\<T\> |  }"];

"ConsumerBase<T>"                   -> "Consumer<T>"                       [color = "#008200", style = dashed, arrowtail = none    , arrowhead = normal  , taillabel = "", label = "", headlabel = ""];
"ConsumerImpl<T>"                   -> "ConsumerBase<T>"                   [color = "#000082", style = solid , arrowtail = none    , arrowhead = normal  , taillabel = "", label = "", headlabel = ""];
"MultiTopicsConsumerImpl<T>"        -> "ConsumerBase<T>"                   [color = "#000082", style = solid , arrowtail = none    , arrowhead = normal  , taillabel = "", label = "", headlabel = ""];
"PatternMultiTopicsConsumerImpl<T>" -> "MultiTopicsConsumerImpl<T>"        [color = "#000082", style = solid , arrowtail = none    , arrowhead = normal  , taillabel = "", label = "", headlabel = ""];
RawConsumerImpl                     -> "ConsumerImpl<T>"                   [color = "#000082", style = solid , arrowtail = none    , arrowhead = normal  , taillabel = "", label = "", headlabel = ""];
RawConsumerImpl                     -> RawReaderImpl                       [color = "#820000", style = solid , arrowtail = odot    , arrowhead = none    , taillabel = "", label = "", headlabel = ""];
"ZeroQueueConsumerImpl<T>"          -> "ConsumerImpl<T>"                   [color = "#000082", style = solid , arrowtail = none    , arrowhead = normal  , taillabel = "", label = "", headlabel = ""];

}

```





Dispatcher


### ConsumerBase

```java
public abstract class ConsumerBase<T> extends HandlerState implements Consumer<T> {
    final BlockingQueue<Message<T>> incomingMessages;

    protected final ExecutorProvider executorProvider;
    protected final ScheduledExecutorService externalPinnedExecutor;
    protected final ScheduledExecutorService internalPinnedExecutor;
}
```

internalPinnedExecutor 

pendingBatchReceiveTask
```java
public abstract class ConsumerBase<T> extends HandlerState implements Consumer<T> {
    private void pendingBatchReceiveTask(Timeout timeout) {
        internalPinnedExecutor.execute(() -> doPendingBatchReceiveTask(timeout));
    }

    private void doPendingBatchReceiveTask(Timeout timeout) {
        if (timeout.isCancelled()) {
            return;
        }

        long timeToWaitMs;

        synchronized (this) {
            // If it's closing/closed we need to ignore this timeout and not schedule next timeout.
            if (getState() == State.Closing || getState() == State.Closed) {
                return;
            }

            timeToWaitMs = batchReceivePolicy.getTimeoutMs();
            OpBatchReceive<T> opBatchReceive = pendingBatchReceives.peek();

            while (opBatchReceive != null) {
                // If there is at least one batch receive, calculate the diff between the batch receive timeout and the elapsed time since the operation was created.
                long diff = batchReceivePolicy.getTimeoutMs()
                        - TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - opBatchReceive.createdAt);

                if (diff <= 0) {
                    completeOpBatchReceive(opBatchReceive);

                    // remove the peeked item from the queue
                    OpBatchReceive<T> removed = pendingBatchReceives.poll();

                    if (removed != opBatchReceive) {
                        // regression check, if this were to happen due to incorrect code changes in the future,
                        // (allowing multi-threaded calls to poll()), then ensure that the polled item is completed
                        // to avoid blocking user code

                        log.error("Race condition in consumer {} (should not cause data loss). "
                                + " Concurrent operations on pendingBatchReceives is not safe", this.consumerName);
                        if (removed != null && !removed.future.isDone()) {
                            completeOpBatchReceive(removed);
                        }
                    }
                } else {
                    // The diff is greater than zero, set the timeout to the diff value
                    timeToWaitMs = diff;
                    break;
                }

                opBatchReceive = pendingBatchReceives.peek();
            }
            batchReceiveTimeout = client.timer().newTimeout(this::pendingBatchReceiveTask,
                    timeToWaitMs, TimeUnit.MILLISECONDS);
        }
    }
}
```

triggerListener

The messages are added into the receiver queue by the internal pinned executor, so need to use internal pinned executor to avoid race condition which message might be added into the receiver queue but not able to read here.
```java
public abstract class ConsumerBase<T> extends HandlerState implements Consumer<T> {
    private void triggerListener() {
        internalPinnedExecutor.execute(() -> {
            try {
                Message<T> msg;
                do {
                    msg = internalReceive(0, TimeUnit.MILLISECONDS);
                    if (msg != null) {
                        // Trigger the notification on the message listener in a separate thread to avoid blocking the
                        // internal pinned executor thread while the message processing happens
                        final Message<T> finalMsg = msg;
                        if (SubscriptionType.Key_Shared == conf.getSubscriptionType()) {
                            executorProvider.getExecutor(peekMessageKey(msg)).execute(() ->
                                    callMessageListener(finalMsg));
                        } else {
                            getExternalExecutor(msg).execute(() -> {
                                callMessageListener(finalMsg);
                            });
                        }
                    }
                } while (msg != null);
            } catch (PulsarClientException e) {
                log.warn("[{}] [{}] Failed to dequeue the message for listener", topic, subscription, e);
            }
        });
    }
}
```


ConsumerImpl

```java

public class ConsumerImpl<T> extends ConsumerBase<T> implements ConnectionHandler.Connection {
    private final UnAckedMessageTracker unAckedMessageTracker;
    private final AcknowledgmentsGroupingTracker acknowledgmentsGroupingTracker;
    private final NegativeAcksTracker negativeAcksTracker;

}
```

BlockingQueue.take

```java
 @Override
    public Message<T> receive() throws PulsarClientException {
        if (listener != null) {
            throw new PulsarClientException.InvalidConfigurationException(
                    "Cannot use receive() when a listener has been set");
        }
        verifyConsumerState();
        return internalReceive();
    }

@Override
protected Message<T> internalReceive() throws PulsarClientException {
        Message<T> message;
        try {
        message = incomingMessages.take();
        messageProcessed(message);
        return beforeConsume(message);
        } catch (InterruptedException e) {
        stats.incrementNumReceiveFailed();
        throw PulsarClientException.unwrap(e);
        }
        }

@Override
protected synchronized void messageProcessed(Message<?> msg) {
        ClientCnx currentCnx = cnx();
        ClientCnx msgCnx = ((MessageImpl<?>) msg).getCnx();
        lastDequeuedMessageId = msg.getMessageId();

        if (msgCnx != currentCnx) {
        // The processed message did belong to the old queue that was cleared after reconnection.
        } else {
        if (listener == null && !parentConsumerHasListener) {
        increaseAvailablePermits(currentCnx);
        }
        stats.updateNumMsgsReceived(msg);

        trackMessage(msg);
        }
        decreaseIncomingMessageSize(msg);
        }
```


```java
protected Message<T> beforeConsume(Message<T> message) {
        if (interceptors != null) {
            return interceptors.beforeConsume(this, message);
        } else {
            return message;
        }
    }
```
This is called just before the message is returned by Consumer.receive(), MessageListener.received(Consumer, Message) or the java.util.concurrent.CompletableFuture returned by Consumer.receiveAsync() completes.

This method calls ConsumerInterceptor.beforeConsume(Consumer, Message) for each interceptor. Messages returned from each interceptor get passed to beforeConsume() of the next interceptor in the chain of interceptors.

This method does not throw exceptions. 
If any of the interceptors in the chain throws an exception, it gets caught and logged, and next interceptor in int the chain is called with 'messages' returned by the previous successful interceptor beforeConsume call.

```java
public class ConsumerInterceptors<T> implements Closeable {
    public Message<T> beforeConsume(Consumer<T> consumer, Message<T> message) {
        Message<T> interceptorMessage = message;
        for (int i = 0, interceptorsSize = interceptors.size(); i < interceptorsSize; i++) {
            try {
                interceptorMessage = interceptors.get(i).beforeConsume(consumer, interceptorMessage);
            } catch (Throwable e) {
                if (consumer != null) {
                    log.warn("Error executing interceptor beforeConsume callback topic: {} consumerName: {}", consumer.getTopic(), consumer.getConsumerName(), e);
                } else {
                    log.warn("Error executing interceptor beforeConsume callback", e);
                }
            }
        }
        return interceptorMessage;
    }
}
```



```java
@Override
    protected CompletableFuture<Message<T>> internalReceiveAsync() {
        CompletableFutureCancellationHandler cancellationHandler = new CompletableFutureCancellationHandler();
        CompletableFuture<Message<T>> result = cancellationHandler.createFuture();
        internalPinnedExecutor.execute(() -> {
            Message<T> message = incomingMessages.poll();
            if (message == null) {
                pendingReceives.add(result);
                cancellationHandler.setCancelAction(() -> pendingReceives.remove(result));
            } else {
                messageProcessed(message);
                result.complete(beforeConsume(message));
            }
        });

        return result;
    }
```


### retry

reconsumeLater the consumption of Messages.
When a message is "reconsumeLater" it will be marked for redelivery after some custom delay.

Example of usage:
```java
  while (true) {
      Message<String> msg = consumer.receive();
 
      try {
           // Process message...
 
           consumer.acknowledge(msg);
      } catch (Throwable t) {
           log.warn("Failed to process message");
           consumer.reconsumeLater(msg, 1000 , TimeUnit.MILLISECONDS);
      }
  }
```
reconsumeLater

```java
public abstract class ConsumerBase<T> extends HandlerState implements Consumer<T> {
    @Override
    public void reconsumeLater(Message<?> message, long delayTime, TimeUnit unit) throws PulsarClientException {
        if (!conf.isRetryEnable()) {
            throw new PulsarClientException("reconsumeLater method not support!");
        }
        try {
            reconsumeLaterAsync(message, delayTime, unit).get();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw PulsarClientException.unwrap(e);
        } catch (ExecutionException e) {
            throw PulsarClientException.unwrap(e);
        }
    }

    @Override
    public CompletableFuture<Void> reconsumeLaterAsync(Message<?> message, long delayTime, TimeUnit unit) {
        if (!conf.isRetryEnable()) {
            return FutureUtil.failedFuture(new PulsarClientException("reconsumeLater method not support!"));
        }
        try {
            validateMessageId(message);
        } catch (PulsarClientException e) {
            return FutureUtil.failedFuture(e);
        }
        return doReconsumeLater(message, AckType.Individual, Collections.emptyMap(), delayTime, unit);
    }
}
```

do
```java
public class ConsumerImpl<T> extends ConsumerBase<T> implements ConnectionHandler.Connection {
    @Override
    protected CompletableFuture<Void> doReconsumeLater(Message<?> message, AckType ackType,
                                                       Map<String, Long> properties,
                                                       long delayTime,
                                                       TimeUnit unit) {
        MessageId messageId = message.getMessageId();
        if (messageId == null) {
            return FutureUtil.failedFuture(new PulsarClientException
                    .InvalidMessageException("Cannot handle message with null messageId"));
        }

        if (messageId instanceof TopicMessageIdImpl) {
            messageId = ((TopicMessageIdImpl) messageId).getInnerMessageId();
        }
        checkArgument(messageId instanceof MessageIdImpl);
        if (getState() != State.Ready && getState() != State.Connecting) {
            stats.incrementNumAcksFailed();
            PulsarClientException exception = new PulsarClientException("Consumer not ready. State: " + getState());
            if (AckType.Individual.equals(ackType)) {
                onAcknowledge(messageId, exception);
            } else if (AckType.Cumulative.equals(ackType)) {
                onAcknowledgeCumulative(messageId, exception);
            }
            return FutureUtil.failedFuture(exception);
        }
        if (delayTime < 0) {
            delayTime = 0;
        }
        if (retryLetterProducer == null) {
            createProducerLock.writeLock().lock();
            try {
                if (retryLetterProducer == null) {
                    retryLetterProducer = client.newProducer(schema)
                            .topic(this.deadLetterPolicy.getRetryLetterTopic())
                            .enableBatching(false)
                            .blockIfQueueFull(false)
                            .create();
                }
            } catch (Exception e) {
                log.error("Create retry letter producer exception with topic: {}",
                        deadLetterPolicy.getRetryLetterTopic(), e);
                return FutureUtil.failedFuture(e);
            } finally {
                createProducerLock.writeLock().unlock();
            }
        }
        CompletableFuture<Void> result = new CompletableFuture<>();
        if (retryLetterProducer != null) {
            try {
                MessageImpl<T> retryMessage = (MessageImpl<T>) getMessageImpl(message);
                String originMessageIdStr = getOriginMessageIdStr(message);
                String originTopicNameStr = getOriginTopicNameStr(message);
                SortedMap<String, String> propertiesMap
                        = getPropertiesMap(message, originMessageIdStr, originTopicNameStr);
                int reconsumetimes = 1;
                if (propertiesMap.containsKey(RetryMessageUtil.SYSTEM_PROPERTY_RECONSUMETIMES)) {
                    reconsumetimes = Integer.parseInt(propertiesMap.get(RetryMessageUtil.SYSTEM_PROPERTY_RECONSUMETIMES));
                    reconsumetimes = reconsumetimes + 1;
                }
                propertiesMap.put(RetryMessageUtil.SYSTEM_PROPERTY_RECONSUMETIMES, String.valueOf(reconsumetimes));
                propertiesMap.put(RetryMessageUtil.SYSTEM_PROPERTY_DELAY_TIME, String.valueOf(unit.toMillis(delayTime)));

                MessageId finalMessageId = messageId;
                if (reconsumetimes > this.deadLetterPolicy.getMaxRedeliverCount() && StringUtils.isNotBlank(deadLetterPolicy.getDeadLetterTopic())) {
                    initDeadLetterProducerIfNeeded();
                    deadLetterProducer.thenAccept(dlqProducer -> {
                        TypedMessageBuilder<byte[]> typedMessageBuilderNew =
                                dlqProducer.newMessage(Schema.AUTO_PRODUCE_BYTES(retryMessage.getReaderSchema().get()))
                                        .value(retryMessage.getData())
                                        .properties(propertiesMap);
                        typedMessageBuilderNew.sendAsync().thenAccept(msgId -> {
                            doAcknowledge(finalMessageId, ackType, properties, null).thenAccept(v -> {
                                result.complete(null);
                            }).exceptionally(ex -> {
                                result.completeExceptionally(ex);
                                return null;
                            });
                        }).exceptionally(ex -> {
                            result.completeExceptionally(ex);
                            return null;
                        });
                    }).exceptionally(ex -> {
                        result.completeExceptionally(ex);
                        deadLetterProducer = null;
                        return null;
                    });
                } else {
                    TypedMessageBuilder<T> typedMessageBuilderNew = retryLetterProducer.newMessage()
                            .value(retryMessage.getValue())
                            .properties(propertiesMap);
                    if (delayTime > 0) {
                        typedMessageBuilderNew.deliverAfter(delayTime, unit);
                    }
                    if (message.hasKey()) {
                        typedMessageBuilderNew.key(message.getKey());
                    }
                    typedMessageBuilderNew.sendAsync()
                            .thenCompose(__ -> doAcknowledge(finalMessageId, ackType, properties, null))
                            .thenAccept(v -> result.complete(null))
                            .exceptionally(ex -> {
                                result.completeExceptionally(ex);
                                return null;
                            });
                }
            } catch (Exception e) {
                result.completeExceptionally(e);
            }
        }
        MessageId finalMessageId = messageId;
        result.exceptionally(ex -> {
            log.error("Send to retry letter topic exception with topic: {}, messageId: {}",
                    retryLetterProducer.getTopic(), finalMessageId, ex);
            Set<MessageId> messageIds = Collections.singleton(finalMessageId);
            unAckedMessageTracker.remove(finalMessageId);
            redeliverUnacknowledgedMessages(messageIds);
            return null;
        });
        return result;
    }
}
```


```java
 protected void increaseAvailablePermits(ClientCnx currentCnx, int delta) {
        int available = AVAILABLE_PERMITS_UPDATER.addAndGet(this, delta);

        while (available >= receiverQueueRefillThreshold && !paused) {
            if (AVAILABLE_PERMITS_UPDATER.compareAndSet(this, available, 0)) {
                sendFlowPermitsToBroker(currentCnx, available);
                break;
            } else {
                available = AVAILABLE_PERMITS_UPDATER.get(this);
            }
        }
    }
```

## message Retention


```
defaultRetentionSizeInMB
defaultRetentionTimeInMinutes
```


backlog



## Reader





## Links

- [Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md)
