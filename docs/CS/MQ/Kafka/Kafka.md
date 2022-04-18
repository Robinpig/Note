## Introduction



[Apache Kafka](https://kafka.apache.org/) is an open-source distributed **event streaming** platform used by thousands of companies for high-performance data pipelines, streaming analytics, data integration, and mission-critical applications.



### Event Streaming

Event streaming is the digital equivalent of the human body's central nervous system. 
It is the technological foundation for the 'always-on' world where businesses are increasingly software-defined and automated, and where the user of software is more software.

Technically speaking, event streaming is the practice of capturing data in real-time from event sources like databases, sensors, mobile devices, cloud services, 
and software applications in the form of streams of events; storing these event streams durably for later retrieval; manipulating, processing, and reacting to the event streams in real-time as well as retrospectively; 
and routing the event streams to different destination technologies as needed. 
Event streaming thus ensures a continuous flow and interpretation of data so that the right information is at the right place, at the right time.

Kafka combines three key capabilities so you can implement your use cases for event streaming end-to-end with a single battle-tested solution:

- To publish (write) and subscribe to (read) streams of events, including continuous import/export of your data from other systems.
- To store streams of events durably and reliably for as long as you want.
- To process streams of events as they occur or retrospectively.

### quick start
[Install](https://kafka.apache.org/quickstart)

Notes:

1. check the `server.properties` before start Kafka




- Consumer Group improve TPS

Rebalance





#### SocketServer

监听Socket请求，提供Socket服务模块。

##### Acceptor 

监听Socket连接，Acceptor初始化主要步骤如下：

- 开启Socket服务
- 注册Accept事件
- 监听此ServerChannel上ACCEPT事件，事件发生时轮询把对应SocketChannel转交给Processor处理线程

##### Processor

转发Socket请求与响应，Processor初始化。

##### RequestChannel

缓存Socket请求和响应

#### KafkaRequestHandlerPool

处理Socket请求线程池，默认为8个。

循环调用requestChannel的Request阻塞队列中获取请求，

判断请求类型

#### LogManager

日志管理模块。

#### ReplicaManager

#### OffsetManager

偏移量管理模块

#### TopicConfigManager

#### KafkaController



Topic 无序

paritition内部有序, 同一个key只会散列到同一个parition, 可以设置业务唯一性的key来保证消费顺序



消息重试:消息存储 异步重试

消息积压: 减小传输数据大小 IO压力 路由分配规则



高并发下重复主键是否需加锁

消息重复:幂等性



环境隔离

消息恢复



## Zookeeper


controller


1. Register Brokers
2. Register Topics
3. load Balance 



### quorum replace zookeeper

why
1. 强依赖 维护困难
2. Zookeeper CP 影响性能



## Producer

A Kafka client that publishes records to the Kafka cluster.
The producer is thread safe and sharing a single producer instance across threads will generally be faster than having multiple instances.

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

The producer consists of a pool of buffer space that holds records that haven't yet been transmitted to the server as well as a background I/O thread that is responsible for turning these records into requests and transmitting them to the cluster. Failure to close the producer after use will leak these resources.

The send() method is asynchronous. When called, it adds the record to a buffer of pending record sends and immediately returns. This allows the producer to batch together individual records for efficiency.

The acks config controls the criteria under which requests are considered complete. The default setting "all" will result in blocking on the full commit of the record, the slowest but most durable setting.

If the request fails, the producer can automatically retry. The retries setting defaults to Integer.MAX_VALUE, and it's recommended to use delivery.timeout.ms to control retry behavior, instead of retries.

The producer maintains buffers of unsent records for each partition. These buffers are of a size specified by the batch.size config. Making this larger can result in more batching, but requires more memory (since we will generally have one of these buffers for each active partition).

> [!NOTE]
>
> new Sender and start ioThread in the constructor of Producer. And create connections with all of cluster brokers.



TODO: 
1. Connection with brokers
2. Connection close
    - Kafka will close idle timeout connection if clients set `connections.max.idle.ms!=-1`.
    - Otherwise, clients don't explicit close() and will keep CLOSE_WAIT until it send again.
 
### Idempotence

single partition, single session



### Transaction

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

## Consumer

### Consumer Group

Best Practice: Consumer Number == Partition Number


## Rebalance

1. Partitions
2. Topics
3. Consumers

All consumers stop and wait until rebalanced finished.


### Consumer Offset

K,V

K: Topic, Partition, GroupId


offsets.topic.num.partitions


Compact commmitted ack



## Interceptor

### ProducerInterceptor

### ConsumerInterceptor



### Record


RecordAccumulator

This class acts as a queue that accumulates records into MemoryRecords instances to be sent to the server.
The accumulator uses a bounded amount of memory and append calls will block when that memory is exhausted, unless this behavior is explicitly disabled.


## Configuration


## Performance

- disk
- bandwidth

## References

1. [Kafka Documentation](https://kafka.apache.org/documentation/#design)
