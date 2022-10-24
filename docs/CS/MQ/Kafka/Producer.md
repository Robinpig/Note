## Introduction

Load balancing

The client controls which partition it publishes messages to. This can be done at random, implementing a kind of random load balancing, or it can be done by some semantic partitioning function.

Asynchronous send
Batching is one of the big drivers of efficiency, and to enable batching the Kafka producer will attempt to accumulate data in memory and to send out larger batches in a single request.
The batching can be configured to accumulate no more than a fixed number of messages and to wait no longer than some fixed latency bound (say 64k or 10 ms).
This allows the accumulation of more bytes to send, and few larger I/O operations on the servers.
This buffering is configurable and gives a mechanism to trade off a small amount of additional latency for better throughput.

A Kafka client that publishes records to the Kafka cluster.
The producer is **thread safe** and sharing a **single producer instance** across threads will generally be faster than having multiple instances.

Here is a simple example of using the producer to send records with strings containing sequential numbers as the key/value pairs.

```java
 Properties props = new Properties();
 props.put("bootstrap.servers", "localhost:9092");
 props.put("linger.ms", 1);
 props.put("key.serializer", "org.apache.kafka.common.serialization.StringSerializer");
 props.put("value.serializer", "org.apache.kafka.common.serialization.StringSerializer");

 Producer<String, String> producer = new KafkaProducer<>(props);
 for (int i = 0; i < 100; i++)
     producer.send(new ProducerRecord<String, String>("my-topic", Integer.toString(i), Integer.toString(i)));

 producer.close();
```

The producer consists of a pool of buffer space that holds records that haven't yet been transmitted to the server as well as a background I/O thread that is responsible for turning these records into requests and transmitting them to the cluster.
Failure to close the producer after use will leak these resources.

acks




## send


```plantuml
participant Actor
Actor -> KafkaProducer : send
activate KafkaProducer
KafkaProducer -> ProducerInterceptors : onSend
activate ProducerInterceptors
ProducerInterceptors --> KafkaProducer: ProducerRecord
deactivate ProducerInterceptors
KafkaProducer -> KafkaProducer : doSend
activate KafkaProducer
KafkaProducer -> KafkaProducer : waitOnMetadata
activate KafkaProducer
deactivate KafkaProducer
KafkaProducer -> Serializer : serialize key and value
activate Serializer
Serializer --> KafkaProducer
deactivate Serializer
KafkaProducer -> KafkaProducer : partition
activate KafkaProducer
deactivate KafkaProducer
KafkaProducer -> RecordAccumulator : append
activate RecordAccumulator
RecordAccumulator --> KafkaProducer
deactivate RecordAccumulator
KafkaProducer -> Sender : wakeup if batchIsFull or newBatchCreated
activate Sender
Sender --> KafkaProducer
deactivate Sender
deactivate KafkaProducer
return
```

The `send()` method is asynchronous.
When called, it adds the record to a buffer of pending record sends and immediately returns.
This allows the producer to batch together individual records for efficiency.

```java
public class KafkaProducer<K, V> implements Producer<K, V> {
    @Override
    public Future<RecordMetadata> send(ProducerRecord<K, V> record, Callback callback) {
        // intercept the record, which can be potentially modified; this method does not throw exceptions
        ProducerRecord<K, V> interceptedRecord = this.interceptors.onSend(record);
        return doSend(interceptedRecord, callback);
    }
}
```

### ProducerInterceptor

A container that holds the list ProducerInterceptor and wraps calls to the chain of custom interceptors.

A plugin interface that allows you to intercept (and possibly mutate) the records received by the producer before they are published to the Kafka cluster.
This class will get producer config properties via configure() method, including clientId assigned by KafkaProducer if not specified in the producer config. The interceptor implementation needs to be aware that it will be sharing producer config namespace with other interceptors and serializers, and ensure that there are no conflicts.

**Exceptions thrown by ProducerInterceptor methods will be caught, logged, but not propagated further.** 
As a result, if the user configures the interceptor with the wrong key and value type parameters, the producer will not throw an exception, just log the errors.
ProducerInterceptor callbacks may be called from multiple threads. Interceptor implementation must ensure thread-safety, if needed.

Implement org.apache.kafka.common.ClusterResourceListener to receive cluster metadata once it's available. Please see the class documentation for ClusterResourceListener for more information.

```java
public interface ProducerInterceptor<K, V> extends Configurable, AutoCloseable {
  
    ProducerRecord<K, V> onSend(ProducerRecord<K, V> record);
  
    void onAcknowledgement(RecordMetadata metadata, Exception exception);

    void close();
}
```
### doSend
doSend():

1. make sure the metadata for the topic is available
2. serializedKey and value
3. get partition
4. ensureValidRecordSize
5. new interceptCallback
6. append into buffer
7. if buffer if full or new buffer, wakeup [Sender](/docs/CS/MQ/Kafka/Network.md?id=Sender)(actually wakeup the Selector in KafkaClient).

```java
public class KafkaProducer<K, V> implements Producer<K, V> {
    private Future<RecordMetadata> doSend(ProducerRecord<K, V> record, Callback callback) {
        TopicPartition tp = null;
        try {
            throwIfProducerClosed();
  
            // first make sure the metadata for the topic is available
            ClusterAndWaitTime clusterAndWaitTime;
            clusterAndWaitTime = waitOnMetadata(record.topic(), record.partition(), maxBlockTimeMs);
            long remainingWaitMs = Math.max(0, maxBlockTimeMs - clusterAndWaitTime.waitedOnMetadataMs);
            Cluster cluster = clusterAndWaitTime.cluster;
  
            byte[] serializedKey;
            serializedKey = keySerializer.serialize(record.topic(), record.headers(), record.key());
            byte[] serializedValue;
            serializedValue = valueSerializer.serialize(record.topic(), record.headers(), record.value());
   
            int partition = partition(record, serializedKey, serializedValue, cluster);
            tp = new TopicPartition(record.topic(), partition);

            setReadOnly(record.headers());
            Header[] headers = record.headers().toArray();

            int serializedSize = AbstractRecords.estimateSizeInBytesUpperBound(apiVersions.maxUsableProduceMagic(),
                    compressionType, serializedKey, serializedValue, headers);
            ensureValidRecordSize(serializedSize);
            long timestamp = record.timestamp() == null ? time.milliseconds() : record.timestamp();
            // producer callback will make sure to call both 'callback' and interceptor callback
            Callback interceptCallback = new InterceptorCallback<>(callback, this.interceptors, tp);

            if (transactionManager != null && transactionManager.isTransactional())
                transactionManager.maybeAddPartitionToTransaction(tp);

            RecordAccumulator.RecordAppendResult result = accumulator.append(tp, timestamp, serializedKey,
                    serializedValue, headers, interceptCallback, remainingWaitMs);
            if (result.batchIsFull || result.newBatchCreated) {
                this.sender.wakeup();
            }
            return result.future;
        } catch (Exception e) {
            // we notify interceptor about all exceptions, since onSend is called before anything else in this method
            this.interceptors.onSendError(record, tp, e);
            throw e;
        }
    }
}
```

#### append

The acks config controls the criteria under which requests are considered complete.
The default setting "all" will result in blocking on the full commit of the record, the slowest but most durable setting.

If the request fails, the producer can automatically retry.
The retries setting defaults to Integer.MAX_VALUE, and it's recommended to use delivery.timeout.ms to control retry behavior, instead of retries.

The producer maintains buffers of unsent records for each partition. These buffers are of a size specified by the batch.size config.
Making this larger can result in more batching, but requires more memory (since we will generally have one of these buffers for each active partition).

> [!NOTE]
>
> new Sender and start ioThread in the constructor of Producer. And create connections with all of cluster brokers.

Add a record to the accumulator, return the append result
The append result will contain the future metadata, and flag for whether the appended batch is full or a new batch is created

```java
public RecordAppendResult append(String topic,
                                     int partition,
                                     long timestamp,
                                     byte[] key,
                                     byte[] value,
                                     Header[] headers,
                                     AppendCallbacks callbacks,
                                     long maxTimeToBlock,
                                     boolean abortOnNewBatch,
                                     long nowMs,
                                     Cluster cluster) throws InterruptedException {
        TopicInfo topicInfo = topicInfoMap.computeIfAbsent(topic, k -> new TopicInfo(logContext, k, batchSize));

        // We keep track of the number of appending thread to make sure we do not miss batches in
        // abortIncompleteBatches().
        appendsInProgress.incrementAndGet();
        ByteBuffer buffer = null;
        if (headers == null) headers = Record.EMPTY_HEADERS;
        try {
            // Loop to retry in case we encounter partitioner's race conditions.
            while (true) {
                // If the message doesn't have any partition affinity, so we pick a partition based on the broker
                // availability and performance.  Note, that here we peek current partition before we hold the
                // deque lock, so we'll need to make sure that it's not changed while we were waiting for the
                // deque lock.
                final BuiltInPartitioner.StickyPartitionInfo partitionInfo;
                final int effectivePartition;
                if (partition == RecordMetadata.UNKNOWN_PARTITION) {
                    partitionInfo = topicInfo.builtInPartitioner.peekCurrentPartitionInfo(cluster);
                    effectivePartition = partitionInfo.partition();
                } else {
                    partitionInfo = null;
                    effectivePartition = partition;
                }

                // Now that we know the effective partition, let the caller know.
                setPartition(callbacks, effectivePartition);

                // check if we have an in-progress batch
                Deque<ProducerBatch> dq = topicInfo.batches.computeIfAbsent(effectivePartition, k -> new ArrayDeque<>());
                synchronized (dq) {
                    // After taking the lock, validate that the partition hasn't changed and retry.
                    if (partitionChanged(topic, topicInfo, partitionInfo, dq, nowMs, cluster))
                        continue;

                    RecordAppendResult appendResult = tryAppend(timestamp, key, value, headers, callbacks, dq, nowMs);
                    if (appendResult != null) {
                        // If queue has incomplete batches we disable switch (see comments in updatePartitionInfo).
                        boolean enableSwitch = allBatchesFull(dq);
                        topicInfo.builtInPartitioner.updatePartitionInfo(partitionInfo, appendResult.appendedBytes, cluster, enableSwitch);
                        return appendResult;
                    }
                }

                // we don't have an in-progress record batch try to allocate a new batch
                if (abortOnNewBatch) {
                    // Return a result that will cause another call to append.
                    return new RecordAppendResult(null, false, false, true, 0);
                }

                if (buffer == null) {
                    byte maxUsableMagic = apiVersions.maxUsableProduceMagic();
                    int size = Math.max(this.batchSize, AbstractRecords.estimateSizeInBytesUpperBound(maxUsableMagic, compression, key, value, headers));
                    log.trace("Allocating a new {} byte message buffer for topic {} partition {} with remaining timeout {}ms", size, topic, partition, maxTimeToBlock);
                    // This call may block if we exhausted buffer space.
                    buffer = free.allocate(size, maxTimeToBlock);
                    // Update the current time in case the buffer allocation blocked above.
                    // NOTE: getting time may be expensive, so calling it under a lock
                    // should be avoided.
                    nowMs = time.milliseconds();
                }

                synchronized (dq) {
                    // After taking the lock, validate that the partition hasn't changed and retry.
                    if (partitionChanged(topic, topicInfo, partitionInfo, dq, nowMs, cluster))
                        continue;

                    RecordAppendResult appendResult = appendNewBatch(topic, effectivePartition, dq, timestamp, key, value, headers, callbacks, buffer, nowMs);
                    // Set buffer to null, so that deallocate doesn't return it back to free pool, since it's used in the batch.
                    if (appendResult.newBatchCreated)
                        buffer = null;
                    // If queue has incomplete batches we disable switch (see comments in updatePartitionInfo).
                    boolean enableSwitch = allBatchesFull(dq);
                    topicInfo.builtInPartitioner.updatePartitionInfo(partitionInfo, appendResult.appendedBytes, cluster, enableSwitch);
                    return appendResult;
                }
            }
        } finally {
            free.deallocate(buffer);
            appendsInProgress.decrementAndGet();
        }
    }
```

#### ready

Get a list of nodes whose partitions are ready to be sent, and the earliest time at which any non-sendable partition will be ready;
Also return the flag for whether there are any unknown leaders for the accumulated partition batches.
A destination node is ready to send data if:

1. There is at least one partition that is not backing off its send
2. and those partitions are not muted (to prevent reordering if "max.in.flight.requests.per.connection" is set to one)
3. and any of the following are true
   - The record set is full
   - The record set has sat in the accumulator for at least lingerMs milliseconds
   - The accumulator is out of memory and threads are blocking waiting for data (in this case all partitions are immediately considered ready).
   - The accumulator has been closed

```java
public ReadyCheckResult ready(Cluster cluster, long nowMs) {
        Set<Node> readyNodes = new HashSet<>();
        long nextReadyCheckDelayMs = Long.MAX_VALUE;
        Set<String> unknownLeaderTopics = new HashSet<>();
        // Go topic by topic so that we can get queue sizes for partitions in a topic and calculate
        // cumulative frequency table (used in partitioner).
        for (Map.Entry<String, TopicInfo> topicInfoEntry : this.topicInfoMap.entrySet()) {
            final String topic = topicInfoEntry.getKey();
            nextReadyCheckDelayMs = partitionReady(cluster, nowMs, topic, topicInfoEntry.getValue(), nextReadyCheckDelayMs, readyNodes, unknownLeaderTopics);
        }
        return new ReadyCheckResult(readyNodes, nextReadyCheckDelayMs, unknownLeaderTopics);
    }
```

TODO:

1. Connection with brokers
2. Connection close
   - Kafka will close idle timeout connection if clients set `connections.max.idle.ms!=-1`.
   - Otherwise, clients don't explicit close() and will keep CLOSE_WAIT until it send again.



## Sender



The main run loop for the sender thread
```java
public class Sender implements Runnable {
    public void run() {

        // main loop, runs until close is called
        while (running) {
            try {
                runOnce();
            } catch (Exception e) {
                log.error("Uncaught error in kafka producer I/O thread: ", e);
            }
        }

        // okay we stopped accepting requests but there may still be
        // requests in the transaction manager, accumulator or waiting for acknowledgment,
        // wait until these are completed.
        while (!forceClose && ((this.accumulator.hasUndrained() || this.client.inFlightRequestCount() > 0) || hasPendingTransactionalRequests())) {
            try {
                runOnce();
            } catch (Exception e) {
            }
        }

        // Abort the transaction if any commit or abort didn't go through the transaction manager's queue
        while (!forceClose && transactionManager != null && transactionManager.hasOngoingTransaction()) {
            if (!transactionManager.isCompleting()) {
                transactionManager.beginAbort();
            }
            try {
                runOnce();
            } catch (Exception e) {
            }
        }

        if (forceClose) {
            // We need to fail all the incomplete transactional requests and batches and wake up the threads waiting on
            // the futures.
            if (transactionManager != null) {
                transactionManager.close();
            }
            this.accumulator.abortIncompleteBatches();
        }
        try {
            this.client.close();
        } catch (Exception e) {
        }
    }
}
```

runOnce():
1. Transaction Management
2. sendProducerData
3. [KafkaClient.poll()](/docs/CS/MQ/Kafka/Network.md?id=poll)

```java
public class Sender implements Runnable {
    void runOnce() {
        if (transactionManager != null) {
            try {
                transactionManager.maybeResolveSequences();

                // do not continue sending if the transaction manager is in a failed state
                if (transactionManager.hasFatalError()) {
                    RuntimeException lastError = transactionManager.lastError();
                    if (lastError != null)
                        maybeAbortBatches(lastError);
                    client.poll(retryBackoffMs, time.milliseconds());
                    return;
                }

                // Check whether we need a new producerId. If so, we will enqueue an InitProducerId
                // request which will be sent below
                transactionManager.bumpIdempotentEpochAndResetIdIfNeeded();

                if (maybeSendAndPollTransactionalRequest()) {
                    return;
                }
            } catch (AuthenticationException e) {
                // This is already logged as error, but propagated here to perform any clean ups.
                transactionManager.authenticationFailed(e);
            }
        }

        long currentTimeMs = time.milliseconds();
        long pollTimeout = sendProducerData(currentTimeMs);
        client.poll(pollTimeout, currentTimeMs);
    }
}
```

### batch


5 max uncompleted batches batch.size

buffer size


delay




## Idempotence

single partition, single session

## Transaction

all partitions, all sessions

```java
producer.initTransactions();
try {
            producer.beginTransaction();
            producer.send(record1);
            producer.send(record2);
            producer.commitTransaction();
} catch (KafkaException e) {
            producer.abortTransaction();
}
```

kafka.consumer.isolation-level: read_committed

## Links

- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
