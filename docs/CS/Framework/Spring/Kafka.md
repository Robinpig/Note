## Introduction

The Spring for Apache Kafka (spring-kafka) project applies core Spring concepts to the development of Kafka-based messaging solutions. 
It provides a "template" as a high-level abstraction for sending messages. 
It also provides support for Message-driven POJOs with `@KafkaListener` annotations and a "listener container". 
These libraries promote the use of dependency injection and declarative.
In all of these cases, you will see similarities to the JMS support in the Spring Framework and RabbitMQ support in Spring AMQP.


Single-threaded Message listener container using the Java Consumer supporting auto-partition assignment or user-configured assignment.


```java
@Override  
protected void doStart() {  
    if (!isRunning()) {  
       checkTopics();  
       ContainerProperties containerProperties = getContainerProperties();  
       TopicPartitionOffset[] topicPartitions = containerProperties.getTopicPartitions();  
       if (topicPartitions != null && this.concurrency > topicPartitions.length) {  
          this.logger.warn(() -> "When specific partitions are provided, the concurrency must be less than or "  
                + "equal to the number of partitions; reduced from " + this.concurrency + " to "  
                + topicPartitions.length);  
          this.concurrency = topicPartitions.length;  
       }  
       setRunning(true);  
  
       for (int i = 0; i < this.concurrency; i++) {  
          KafkaMessageListenerContainer<K, V> container =  
                constructContainer(containerProperties, topicPartitions, i);  
          configureChildContainer(i, container);  
          if (isPaused()) {  
             container.pause();  
          }  
          container.start();  
          this.containers.add(container);  
       }  
    }  
}
```



## pollAndInvoke

```java
  
protected void pollAndInvoke() {  
    doProcessCommits();  
    fixTxOffsetsIfNeeded();  
    idleBetweenPollIfNecessary();  
    if (!this.seeks.isEmpty()) {  
       processSeeks();  
    }  
    enforceRebalanceIfNecessary();  
    pauseConsumerIfNecessary();  
    pausePartitionsIfNecessary();  
    this.lastPoll = System.currentTimeMillis();  
    if (!isRunning()) {  
       return;  
    }  
    this.polling.set(true);  
    ConsumerRecords<K, V> records = doPoll();  
    if (!this.polling.compareAndSet(true, false) && records != null) {  
       /*  
        * There is a small race condition where wakeIfNecessaryForStop was called between        * exiting the poll and before we reset the boolean.        */       if (records.count() > 0) {  
          this.logger.debug(() -> "Discarding polled records, container stopped: " + records.count());  
       }  
       return;  
    }  
    if (!this.firstPoll && this.definedPartitions != null && this.consumerSeekAwareListener != null) {  
       this.firstPoll = true;  
       this.consumerSeekAwareListener.onFirstPoll();  
    }  
    if (records != null && records.count() == 0 && this.isCountAck && this.count > 0) {  
       commitIfNecessary();  
       this.count = 0;  
    }  
    debugRecords(records);  
  
    invokeIfHaveRecords(records);  
    if (this.remainingRecords == null) {  
       resumeConsumerIfNeccessary();  
       if (!this.consumerPaused) {  
          resumePartitionsIfNecessary();  
       }  
    }  
}


private void invokeIfHaveRecords(@Nullable ConsumerRecords<K, V> records) {  
    if (records != null && records.count() > 0) {  
       this.receivedSome = true;  
       savePositionsIfNeeded(records);  
       notIdle();  
       notIdlePartitions(records.partitions());  
       invokeListener(records);  
    }  
    else {  
       checkIdle();  
    }  
    if (records == null || records.count() == 0  
          || records.partitions().size() < this.consumer.assignment().size()) {  
       checkIdlePartitions();  
    }  
}

private void doInvokeWithRecords(final ConsumerRecords<K, V> records) {  
    Iterator<ConsumerRecord<K, V>> iterator = records.iterator();  
    while (iterator.hasNext()) {  
       if (this.stopImmediate && !isRunning()) {  
          break;  
       }  
       final ConsumerRecord<K, V> cRecord = checkEarlyIntercept(iterator.next());  
       if (cRecord == null) {  
          continue;  
       }  
       this.logger.trace(() -> "Processing " + KafkaUtils.format(cRecord));  
       doInvokeRecordListener(cRecord, iterator);  
       if (this.commonRecordInterceptor !=  null) {  
          this.commonRecordInterceptor.afterRecord(cRecord, this.consumer);  
       }  
       if (this.nackSleepDurationMillis >= 0) {  
          handleNack(records, cRecord);  
          break;  
       }  
       if (checkImmediatePause(iterator)) {  
          break;  
       }  
    }  
}

@Nullable  
private RuntimeException doInvokeRecordListener(final ConsumerRecord<K, V> cRecord, // NOSONAR  
       Iterator<ConsumerRecord<K, V>> iterator) {  
  
    Object sample = startMicrometerSample();  
    Observation observation = KafkaListenerObservation.LISTENER_OBSERVATION.observation(  
          this.containerProperties.getObservationConvention(),  
          DefaultKafkaListenerObservationConvention.INSTANCE,  
          () -> new KafkaRecordReceiverContext(cRecord, getListenerId(), this::clusterId),  
          this.observationRegistry);  
    return observation.observe(() -> {  
       try {  
          invokeOnMessage(cRecord);  
          successTimer(sample, cRecord);  
          recordInterceptAfter(cRecord, null);  
       }  
       catch (RuntimeException e) {  
          failureTimer(sample, cRecord);  
          recordInterceptAfter(cRecord, e);  
          if (this.commonErrorHandler == null) {  
             throw e;  
          }  
          observation.error(e);  
          try {  
             invokeErrorHandler(cRecord, iterator, e);  
             commitOffsetsIfNeededAfterHandlingError(cRecord);  
          }  
          catch (KafkaException ke) {  
             ke.selfLog(ERROR_HANDLER_THREW_AN_EXCEPTION, this.logger);  
             return ke;  
          }  
          catch (RuntimeException ee) {  
             this.logger.error(ee, ERROR_HANDLER_THREW_AN_EXCEPTION);  
             return ee;  
          }  
          catch (Error er) { // NOSONAR  
             this.logger.error(er, "Error handler threw an error");  
             throw er;  
          }  
       }  
       return null;  
    });  
}
```


## Links

- [Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md)