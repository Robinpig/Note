## Introduction

A Kafka producer sends messages to a topic, and messages are distributed to partitions according to a mechanism such as key hashing (more on it below).

There are many reasons an application might need to write messages to Kafka: recording user activities for auditing or analysis, recording metrics, storing log messages, 
recording information from smart appliances, communicating asynchronously with other applications, buffering information before writing to a database, and much more.

Those diverse use cases also imply diverse requirements: is every message critical, or can we tolerate loss of messages? Are we OK with accidentally duplicating messages? 
Are there any strict latency or throughput requirements we need to support?


The client controls which partition it publishes messages to.
This can be done at random, implementing a kind of random load balancing, or it can be done by some semantic partitioning function.


Batching is one of the big drivers of efficiency, and to enable batching the Kafka producer will attempt to accumulate data in memory and to send out larger batches in a single request.
The batching can be configured to accumulate no more than a fixed number of messages and to wait no longer than some fixed latency bound (say 64k or 10 ms).
This allows the accumulation of more bytes to send, and few larger I/O operations on the servers.
This buffering is configurable and gives a mechanism to trade off a small amount of additional latency for better throughput.

The producer is **thread safe** and sharing a **single producer instance** across threads will generally be faster than having multiple instances.

Here is a simple example of using the producer to send records with strings containing sequential numbers as the key/value pairs.

```java
public class ProducerDemo {
    public static void main(String[] args) {
        Properties props = new Properties();
        props.put("bootstrap.servers", "localhost:9092");
        props.put("linger.ms", 1);
        props.put("key.serializer", "org.apache.kafka.common.serialization.StringSerializer");
        props.put("value.serializer", "org.apache.kafka.common.serialization.StringSerializer");

        Producer<String, String> producer = new KafkaProducer<>(props);
        for (int i = 0; i < 100; i++)
            producer.send(new ProducerRecord<String, String>("my-topic", Integer.toString(i), Integer.toString(i)));
       // flush and close producer
        producer.close();
    }
}
```

The producer consists of a pool of buffer space that holds records that haven't yet been transmitted to the server as well as a background I/O thread that is responsible for turning these records into requests and transmitting them to the cluster.
Failure to close the producer after use will leak these resources.



new KafkaThread with Sender

```java
public class KafkaProducer<K, V> implements Producer<K, V> {

   KafkaProducer(ProducerConfig config) {
      try {
         this.producerConfig = config;
         this.clientId = config.getString(ProducerConfig.CLIENT_ID_CONFIG);

         this.partitioner = config.getConfiguredInstance(
                 ProducerConfig.PARTITIONER_CLASS_CONFIG,
                 Partitioner.class,
                 Collections.singletonMap(ProducerConfig.CLIENT_ID_CONFIG, clientId));
         this.partitionerIgnoreKeys = config.getBoolean(ProducerConfig.PARTITIONER_IGNORE_KEYS_CONFIG);
         this.keySerializer = keySerializer;
         this.valueSerializer = valueSerializer;
         this.interceptors = interceptors;

         // As per Kafka producer configuration documentation batch.size may be set to 0 to explicitly disable
         // batching which in practice actually means using a batch size of 1.
         int batchSize = Math.max(1, config.getInt(ProducerConfig.BATCH_SIZE_CONFIG));
         this.accumulator = new RecordAccumulator(logContext,
                 batchSize,
                 this.compressionType,
                 lingerMs(config),
                 retryBackoffMs,
                 deliveryTimeoutMs,
                 partitionerConfig,
                 metrics,
                 PRODUCER_METRIC_GROUP_NAME,
                 time,
                 apiVersions,
                 transactionManager,
                 new BufferPool(this.totalMemorySize, batchSize, metrics, time, PRODUCER_METRIC_GROUP_NAME));

         this.metadata = metadata;

         this.sender = newSender(logContext, kafkaClient, this.metadata);
         String ioThreadName = NETWORK_THREAD_PREFIX + " | " + clientId;
         this.ioThread = new KafkaThread(ioThreadName, this.sender, true);
         this.ioThread.start();

         AppInfoParser.registerAppInfo(JMX_PREFIX, clientId, metrics, time.milliseconds());
      } catch (Throwable t) {
         throw new KafkaException("Failed to construct kafka producer", t);
      }
   }
}
```

### Producer acks setting

Kafka producers only write data to the current leader broker for a partition.

Kafka producers must also specify a level of acknowledgment acks to specify if the message must be written to a minimum number of replicas before being considered a successful write.

> [!NOTE]
>
> The default value of acks has changed with Kafka v3.0:
> 
> - if using Kafka < v3.0, acks=1
> - if using Kafka >= v3.0, acks=all


<!-- tabs:start -->

##### **acks=0**

When `acks=0` producers consider messages as ”written successfully“ the moment the message was sent without waiting for the broker to accept it at all.


<div style="text-align: center;">

![acks = 0](./img/acks0.png)

</div>

<p style="text-align: center;">
acks = 0
</p>

If the broker goes offline or an exception happens, we won’t know and will lose data. 
This is useful for data where it’s okay to potentially lose messages, such as metrics collection, 
and produces the highest throughput setting because the network overhead is minimized.

##### **acks=1**

When `acks=1` , producers consider messages as ”written successfully“ when the message was acknowledged by only the leader.

<div style="text-align: center;">

![acks = 1](./img/acks1.png)

</div>

<p style="text-align: center;">
acks = 1
</p>

Leader response is requested, but replication is not a guarantee as it happens in the background.
If an ack is not received, the producer may retry the request. 
If the leader broker goes offline unexpectedly but replicas haven’t replicated the data yet, we have a data loss.

##### **acks = all**

When `acks=all`, producers consider messages as ”written successfully“ when the message is accepted by all in-sync replicas (ISR).


<div style="text-align: center;">

![acks = all](./img/acksall.png)

</div>

<p style="text-align: center;">
acks = all
</p>

The lead replica for a partition checks to see if there are enough in-sync replicas for safely writing the message (controlled by the broker setting min.insync.replicas).
The request will be stored in a buffer until the leader observes that the follower replicas replicated the message, 
at which point a successful acknowledgement is sent back to the client.

The `min.insync.replicas` can be configured both at the topic and the broker-level. 
The data is considered committed when it is written to all in-sync replicas - `min.insync.replicas`. 
A value of 2 implies that at least 2 brokers that are ISR (including leader) must respond that they have the data.



<div style="text-align: center;">

![Kafka Topic Replication, ISR & Message Safety](./img/ISR.png)

</div>

<p style="text-align: center;">
Kafka Topic Replication, ISR & Message Safety
</p>


If you would like to be sure that committed data is written to more than one replica, you need to set the minimum number of in-sync replicas to a higher value.
If a topic has three replicas and you set `min.insync.replicas` to 2, then you can only write to a partition in the topic if at least two out of the three replicas are in-sync. 
When all three replicas are in-sync, everything proceeds normally. 
This is also true if one of the replicas becomes unavailable.
However, if two out of three replicas are not available, the brokers will no longer accept produce requests.
Instead, producers that attempt to send data will receive `NotEnoughReplicasException`.



<!-- tabs:end -->

#### Topic Durability & Availability

For a topic replication factor of 3, topic data durability can withstand 2 brokers loss. 
As a general rule, for a replication factor of N, you can permanently lose up to N-1 brokers and still recover your data.

Regarding availability, let’s consider a replication factor of 3:

- Reads: As long as one partition is up and considered an ISR, the topic will be available for reads
- Writers:
  - `acks=0` & `acks=1` : as long as one partition is up and considered an ISR, the topic will be available for writes.
  - `acks=all`: when `acks=all` with a `replication.factor=N` and `min.insync.replicas=M` we can tolerate `N-M` brokers going down for topic availability purposes.

> [!TIP]
>
> acks=all and min.insync.replicas=2 is the most popular option for data durability and availability and allows you to withstand at most the loss of one Kafka broker



When the producer sends messages to a broker, the broker can return either a success or an error code.
Those error codes belong to two categories.

Retriable errors. Errors that can be resolved after retrying. 
For example, if the broker returns the exception NotEnoughReplicasException, 
the producer can try sending the message again - maybe replica brokers will come back online and the second attempt will succeed.

Nonretriable error. Errors that won’t be resolved. 
For example, if the broker returns an INVALID_CONFIG exception, 
trying the same producer request again will not change the outcome of the request.

It is desirable to enable retries in order to ensure that no messages are dropped when sent to Apache Kafka.
Allowing retries without setting max.in.flight.requests.per.connection to 1 will potentially change the ordering of records because if two batches are sent to a single partition, 
and the first fails and is retried but the second succeeds, then the records in the second batch may appear first. 
If you rely on key-based ordering, that can be an issue. 
By limiting the number of in-flight requests to 1 (default being 5), i.e., max.in.flight.requests.per.connection = 1,
we can guarantee that Kafka will preserve message order in the event that some messages will require multiple retries before they are successfully acknowledged.

if we enable idempotence enable=idempotence=true, then it is required for max.in.flight.requests.per.connection to be less than or equal to 5 with message ordering preserved for any allowable value!!



Retrying to send a failed message often includes a small risk that both messages were successfully written to the broker, leading to duplicates.

Producer idempotence ensures that duplicates are not introduced due to unexpected retries.
When enable.idempotence is set to true, each producer gets assigned a Producer Id (PID) and the PIDis included every time a producer sends messages to a broker. 
Additionally, each message gets a monotonically increasing sequence number (different from the offset - used only for protocol purposes). 
A separate sequence is maintained for each topic partition that a producer sends messages to. 
On the broker side, on a per partition basis, it keeps track of the largest PID-Sequence Number combination that is successfully written. 
When a lower sequence number is received, it is discarded.


## send


The `send()` method is asynchronous.
When called, it adds the record to a buffer of pending record sends and immediately returns.
This allows the producer to batch together individual records for efficiency.

1. make sure the metadata for the topic is available
2. serialize the key and value objects to ByteArrays so they can be sent over the network
3. get partition
4. ensureValidRecordSize
5. new interceptCallback
6. append into buffer
7. if buffer if full or new buffer, wakeup [Sender](/docs/CS/MQ/Kafka/Network.md?id=Sender) which is responsible for sending those batches of records to the appropriate Kafka brokers.

```plantuml
actor Actor
Actor -> KafkaProducer : send
activate KafkaProducer
participant ProducerInterceptors
participant RecordAccumulator
KafkaProducer -> ProducerInterceptors : onSend
activate ProducerInterceptors
ProducerInterceptors --> KafkaProducer: ProducerRecord
deactivate ProducerInterceptors
KafkaProducer -> KafkaProducer : doSend
KafkaProducer -> KafkaProducer : waitOnMetadata
KafkaProducer -> KafkaProducer : serialize key and value
KafkaProducer -> KafkaProducer : partition
KafkaProducer -> RecordAccumulator : append
activate RecordAccumulator
RecordAccumulator --> KafkaProducer
deactivate RecordAccumulator
KafkaProducer -> Sender : wakeup
activate Sender
Sender --> KafkaProducer
deactivate Sender
deactivate KafkaProducer
```


```java
public class KafkaProducer<K, V> implements Producer<K, V> {
   @Override
   public Future<RecordMetadata> send(ProducerRecord<K, V> record, Callback callback) {
      // intercept the record, which can be potentially modified; this method does not throw exceptions
      ProducerRecord<K, V> interceptedRecord = this.interceptors.onSend(record);
      return doSend(interceptedRecord, callback);
   }

   private Future<RecordMetadata> doSend(ProducerRecord<K, V> record, Callback callback) {
      TopicPartition tp = null;
      try {
         // first make sure the metadata for the topic is available
         ClusterAndWaitTime clusterAndWaitTime;
         clusterAndWaitTime = waitOnMetadata(record.topic(), record.partition(), maxBlockTimeMs);
         long remainingWaitMs = Math.max(0, maxBlockTimeMs - clusterAndWaitTime.waitedOnMetadataMs);
         Cluster cluster = clusterAndWaitTime.cluster;

         byte[] serializedKey = keySerializer.serialize(record.topic(), record.headers(), record.key());
         byte[] serializedValue = valueSerializer.serialize(record.topic(), record.headers(), record.value());

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
         this.interceptors.onSendError(record, tp, e);
         throw e;
      }
   }
}
```


When key=null, the producer has a default partitioner that varies: 

- Round Robin: for Kafka 2.3 and below
  This results in more batches and smaller batches. 
  And this is a problem because smaller batches lead to more requests as well as higher latency.
- Sticky Partitioner: for Kafka 2.4 and above
  Sticky Partitioner improves the performance of the producer especially with high throughput.
  “stick” to a partition until the batch is full or linger.ms has elapsed
  After sending the batch, change the partition that is "sticky"
  This will lead to larger batches and reduced latency (because we have larger requests, and the batch.size is more likely to be reached).
  Over time, the records are still spread evenly across partitions, so the balance of the cluster is not affected.



### append

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
public class RecordAccumulator {
   public RecordAppendResult append(String topic, int partition) throws InterruptedException {
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

            synchronized (dq) {
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

   private RecordAppendResult tryAppend(long timestamp, byte[] key, byte[] value, Header[] headers,
                                        Callback callback, Deque<ProducerBatch> deque, long nowMs) {
      ProducerBatch last = deque.peekLast();
      if (last != null) {
         int initialBytes = last.estimatedSizeInBytes();
         FutureRecordMetadata future = last.tryAppend(timestamp, key, value, headers, callback, nowMs);
         if (future != null) {
            int appendedBytes = last.estimatedSizeInBytes() - initialBytes;
            return new RecordAppendResult(future, deque.size() > 1 || last.isFull(), false, false, appendedBytes);
         }
      }
      return null;
   }

   private RecordAppendResult appendNewBatch(String topic, int partition) {
      RecordAppendResult appendResult = tryAppend(timestamp, key, value, headers, callbacks, dq, nowMs);
      if (appendResult != null) {
         // Somebody else found us a batch, return the one we waited for! Hopefully this doesn't happen often...
         return appendResult;
      }

      MemoryRecordsBuilder recordsBuilder = recordsBuilder(buffer, apiVersions.maxUsableProduceMagic());
      ProducerBatch batch = new ProducerBatch(new TopicPartition(topic, partition), recordsBuilder, nowMs);
      FutureRecordMetadata future = Objects.requireNonNull(batch.tryAppend(timestamp, key, value, headers,
              callbacks, nowMs));

      dq.addLast(batch);
      incomplete.add(batch);

      return new RecordAppendResult(future, dq.size() > 1 || batch.isFull(), true, false, batch.estimatedSizeInBytes());
   }
}
```


```
    public FutureRecordMetadata tryAppend(long timestamp, byte[] key, byte[] value, Header[] headers, Callback callback, long now) {
        if (!recordsBuilder.hasRoomFor(timestamp, key, value, headers)) {
            return null;
        } else {
            this.recordsBuilder.append(timestamp, key, value, headers);
            this.maxRecordSize = Math.max(this.maxRecordSize, AbstractRecords.estimateSizeInBytesUpperBound(magic(),
                    recordsBuilder.compressionType(), key, value, headers));
            this.lastAppendTime = now;
            FutureRecordMetadata future = new FutureRecordMetadata(this.produceFuture, this.recordCount,
                    timestamp,
                    key == null ? -1 : key.length,
                    value == null ? -1 : value.length,
                    Time.SYSTEM);
            // we have to keep every future returned to the users in case the batch needs to be
            // split to several new batches and resent.
            thunks.add(new Thunk(callback, future));
            this.recordCount++;
            return future;
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
public class RecordAccumulator {
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
}
```

TODO:

1. Connection with brokers
2. Connection close
   - Kafka will close idle timeout connection if clients set `connections.max.idle.ms!=-1`.
   - Otherwise, clients don't explicit close() and will keep CLOSE_WAIT until it send again.

## Sender



```plantuml
Sender ->  RecordAccumulator :ready
RecordAccumulator -->  Sender :readyCheckResults
Sender -> NetworkClient : client.poll()
activate NetworkClient
NetworkClient -> NetworkClient : maybeUpdateMetadata
NetworkClient -> KSelector : selector.poll()
activate KSelector
KSelector -> KSelector : clear()
KSelector -> Selector : select()
KSelector -> Selector : pollSelectionKeys()
KSelector -> KSelector : addToCompletedReceives()
NetworkClient -> NetworkClient : process completed actions
deactivate Sender
return
```


runOnce():

1. Transaction Management
2. sendProducerData
3. [KafkaClient.poll()](/docs/CS/MQ/Kafka/Network.md?id=poll)

```java
public class Sender implements Runnable {
   public void run() {
      // main loop, runs until close is called
      while (running) {
         runOnce();
      }

      // okay we stopped accepting requests but there may still be
      // requests in the transaction manager, accumulator or waiting for acknowledgment, wait until these are completed.
      while (!forceClose && ((this.accumulator.hasUndrained() || this.client.inFlightRequestCount() > 0) || hasPendingTransactionalRequests())) {
         runOnce();
      }

      // Abort the transaction if any commit or abort didn't go through the transaction manager's queue

      // We need to fail all the incomplete transactional requests and batches and wake up the threads waiting on the futures.
      if (forceClose) {
         if (transactionManager != null) {
            transactionManager.close();
         }
         this.accumulator.abortIncompleteBatches();
      }

      this.client.close();
   }

   void runOnce() {
      // transactionManager

      long currentTimeMs = time.milliseconds();
      long pollTimeout = sendProducerData(currentTimeMs);
      client.poll(pollTimeout, currentTimeMs);
   }
}
```

### sendProducerData

1. get the list of partitions with data ready to send
2. if there are any partitions whose leaders are not known yet, force metadata update
3. remove any nodes we aren't ready to send to
4. create produce requests
5. Reset the producer id if an expired batch has previously been sent to the broker
6. Transfer the record batches into a list of produce requests on a per-node basis

```java
public class Sender implements Runnable {
   private long sendProducerData(long now) {
      Cluster cluster = metadata.fetch();
      // get the list of partitions with data ready to send
      RecordAccumulator.ReadyCheckResult result = this.accumulator.ready(cluster, now);

      // if there are any partitions whose leaders are not known yet, force metadata update
      if (!result.unknownLeaderTopics.isEmpty()) {
         for (String topic : result.unknownLeaderTopics)
            this.metadata.add(topic, now);
         this.metadata.requestUpdate();
      }

      // remove any nodes we aren't ready to send to

      // create produce requests
      Map<Integer, List<ProducerBatch>> batches = this.accumulator.drain(cluster, result.readyNodes, this.maxRequestSize, now);
      addToInflightBatches(batches);
      if (guaranteeMessageOrder) {
         for (List<ProducerBatch> batchList : batches.values()) {
            for (ProducerBatch batch : batchList)
               this.accumulator.mutePartition(batch.topicPartition);
         }
      }

      accumulator.resetNextBatchExpiryTime();
      List<ProducerBatch> expiredInflightBatches = getExpiredInflightBatches(now);
      List<ProducerBatch> expiredBatches = this.accumulator.expiredBatches(now);
      expiredBatches.addAll(expiredInflightBatches);

      // Reset the producer id if an expired batch has previously been sent to the broker.
      for (ProducerBatch expiredBatch : expiredBatches) {
         failBatch(expiredBatch, new TimeoutException(errorMessage), false);
      }

      long pollTimeout = Math.min(result.nextReadyCheckDelayMs, notReadyTimeout);
      pollTimeout = Math.min(pollTimeout, this.accumulator.nextExpiryTimeMs() - now);
      pollTimeout = Math.max(pollTimeout, 0);
   
      sendProduceRequests(batches, now);
      return pollTimeout;
   }

   private void sendProduceRequest(long now, int destination, short acks, int timeout, List<ProducerBatch> batches) {
      final Map<TopicPartition, ProducerBatch> recordsByPartition = new HashMap<>(batches.size());

      // find the minimum magic version used when creating the record sets
      // down convert if necessary to the minimum magic used. 

      RequestCompletionHandler callback = response -> handleProduceResponse(response, recordsByPartition, time.milliseconds());

      String nodeId = Integer.toString(destination);
      ClientRequest clientRequest = client.newClientRequest(nodeId, requestBuilder, now, acks != 0,
              requestTimeoutMs, callback);
      client.send(clientRequest, now);
   }
}
```

drain

```java
public class RecordAccumulator {
   public Map<Integer, List<ProducerBatch>> drain(Cluster cluster, Set<Node> nodes, int maxSize, long now) {
      Map<Integer, List<ProducerBatch>> batches = new HashMap<>();
      for (Node node : nodes) {
         List<ProducerBatch> ready = drainBatchesForOneNode(cluster, node, maxSize, now);
         batches.put(node.id(), ready);
      }
      return batches;
   }

   private List<ProducerBatch> drainBatchesForOneNode(Cluster cluster, Node node, int maxSize, long now) {
      int size = 0;
      List<PartitionInfo> parts = cluster.partitionsForNode(node.id());
      List<ProducerBatch> ready = new ArrayList<>();
      /* to make starvation less likely each node has it's own drainIndex */
      int drainIndex = getDrainIndex(node.idString());
      int start = drainIndex = drainIndex % parts.size();
      do {
         PartitionInfo part = parts.get(drainIndex);
         TopicPartition tp = new TopicPartition(part.topic(), part.partition());
         updateDrainIndex(node.idString(), drainIndex);
         drainIndex = (drainIndex + 1) % parts.size();
         // Only proceed if the partition has no in-flight batches.
    

         Deque<ProducerBatch> deque = getDeque(tp);
         final ProducerBatch batch;
         synchronized (deque) {
            // invariant: !isMuted(tp,now) && deque != null
            ProducerBatch first = deque.peekFirst();
            // first != null
            boolean backoff = first.attempts() > 0 && first.waitedTimeMs(now) < retryBackoffMs;
            // Only drain the batch if it is not during backoff period.

               // there is a rare case that a single batch size is larger than the request size due to
               // compression; in this case we will still eventually send this batch in a single request

            batch = deque.pollFirst();

            if (producerIdAndEpoch != null && !batch.hasSequence()) {
               transactionManager.maybeUpdateProducerIdAndEpoch(batch.topicPartition);

               batch.setProducerState(producerIdAndEpoch, transactionManager.sequenceNumber(batch.topicPartition), isTransactional);
               transactionManager.incrementSequenceNumber(batch.topicPartition, batch.recordCount);

               transactionManager.addInFlightBatch(batch);
            }
         }

         batch.close();
         size += batch.records().sizeInBytes();
         ready.add(batch);

         batch.drained(now);
      } while (start != drainIndex);
      return ready;
   }
}
```

### batch

5 max uncompleted batches batch.size

buffer size

delay

### ProducerInterceptor

A container that holds the list ProducerInterceptor and wraps calls to the chain of custom interceptors.

A plugin interface that allows you to intercept (and possibly mutate) the records received by the producer before they are published to the Kafka cluster.
This class will get producer config properties via configure() method, including clientId assigned by KafkaProducer if not specified in the producer config. 
The interceptor implementation needs to be aware that it will be sharing producer config namespace with other interceptors and serializers, and ensure that there are no conflicts.

**Exceptions thrown by ProducerInterceptor methods will be caught, logged, but not propagated further.**
As a result, if the user configures the interceptor with the wrong key and value type parameters, the producer will not throw an exception, just log the errors.
ProducerInterceptor callbacks may be called from multiple threads. Interceptor implementation must ensure thread-safety, if needed.

Implement org.apache.kafka.common.ClusterResourceListener to receive cluster metadata once it's available. 
Please see the class documentation for ClusterResourceListener for more information.

```java
public interface ProducerInterceptor<K, V> extends Configurable, AutoCloseable {
  
    ProducerRecord<K, V> onSend(ProducerRecord<K, V> record);
  
    void onAcknowledgement(RecordMetadata metadata, Exception exception);

    void close();
}
```

## Idempotence

single partition, single session

## Transaction

all partitions, all sessions

```
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



## Examples

Spring Boot with Multiple producers


The producer is **thread safe** and sharing a **single producer instance** across threads will generally be faster than having multiple instances.

So mostly we use multiple producers for multiple servers.


## Links

- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
