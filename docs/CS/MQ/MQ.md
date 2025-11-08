## Introduction

In computer science, message queues and mailboxes are software-engineering components typically used for inter-process communication (IPC), or for inter-thread communication within the same process.
They use a queue for messaging – the passing of control or of content. Group communication systems provide similar kinds of functionality.

## Message System

Within this publish/subscribe model, different systems take a wide range of approaches, and there is no one right answer for all purposes.
To differentiate the systems, it is particularly helpful to ask the following two questions:

1. What happens if the producers send messages faster than the consumers can process them?
   Broadly speaking, there are three options: the system can drop messages, buffer messages in a queue, or apply backpressure (also known as flow control; i.e., blocking the producer from sending more messages).
   For example, Unix pipes and TCP use backpressure: they have a small fixed-size buffer, and if it fills up, the sender is blocked until the recipient takes data out of the buffer.
   If messages are buffered in a queue, it is important to understand what happens as that queue grows.
   Does the system crash if the queue no longer fits in memory, or does it write messages to disk?
   If so, how does the disk access affect the performance of the messaging system?
2. What happens if nodes crash or temporarily go offline—are any messages lost?
   As with databases, durability may require some combination of writing to disk and/or replication, which has a cost.
   If you can afford to sometimes lose messages, you can probably get higher throughput and lower latency on the same hardware.

Whether message loss is acceptable depends very much on the application.
For example, with sensor readings and metrics that are transmitted periodically, an occasional missing data point is perhaps not important, since an updated value will be sent a short time later anyway.
However, beware that if a large number of messages are dropped, it may not be immediately apparent that the metrics are incorrect.
If you are counting events, it is more important that they are delivered reliably, since every lost message means incorrect counters.

### Direct messaging from producers to consumers

A number of messaging systems use direct network communication between producers and consumers without going via intermediary nodes.

### Message brokers

A widely used alternative is to send messages via a message broker (also known as a message queue), which is essentially a kind of database that is optimized for handling message streams.
It runs as a server, with producers and consumers connecting to it as clients.
Producers write messages to the broker, and consumers receive them by reading them from the broker.

By centralizing the data in the broker, these systems can more easily tolerate clients that come and go (connect, disconnect, and crash), and the question of durability is moved to the broker instead.
Some message brokers only keep messages in memory, while others (depending on configuration) write them to disk so that they are not lost in case of a broker crash. Faced with slow consumers, they generally allow unbounded queueing (as opposed to dropping messages or backpressure), although this choice may also depend on the configuration.

A consequence of queueing is also that consumers are generally asynchronous: when a producer sends a message, it normally only waits for the broker to confirm that it has buffered the message and does not wait for the message to be processed by consumers.
The delivery to consumers will happen at some undetermined future point in time—often within a fraction of a second, but sometimes significantly later if there is a queue backlog.

#### Message brokers compared to databases

Some message brokers can even participate in two-phase commit protocols using XA or JTA.
This feature makes them quite similar in nature to databases, although there are still important practical differences between message brokers and databases:

- Databases usually keep data until it is explicitly deleted, whereas most message brokers automatically delete a message when it has been successfully delivered to its consumers.
  Such message brokers are not suitable for long-term data storage.
- Since they quickly delete messages, most message brokers assume that their working set is fairly small—i.e., the queues are short.
  If the broker needs to buffer a lot of messages because the consumers are slow (perhaps spilling messages to disk if they no longer fit in memory), each individual message takes longer to process, and the overall throughput may degrade.
- Databases often support secondary indexes and various ways of searching for data, while message brokers often support some way of subscribing to a subset of topics matching some pattern.
  The mechanisms are different, but both are essentially ways for a client to select the portion of the data that it wants to know about.
- When querying a database, the result is typically based on a point-in-time snapshot of the data; if another client subsequently writes something to the database that changes the query result,
  the first client does not find out that its prior result is now outdated (unless it repeats the query, or polls for changes).
  By contrast, message brokers do not support arbitrary queries, but they do notify clients when data changes (i.e., when new messages become available).

#### Multiple consumers

When multiple consumers read messages in the same topic, two main patterns of messaging are used:

- Load balancing
  Each message is delivered to one of the consumers, so the consumers can share the work of processing the messages in the topic. The broker may assign messages to consumers arbitrarily.
  This pattern is useful when the messages are expensive to process, and so you want to be able to add consumers to parallelize the processing.
  (In AMQP, you can implement load balancing by having multiple clients consuming from the same queue, and in JMS it is called a shared subscription.)
- Fan-out
  Each message is delivered to all of the consumers.
  Fan-out allows several independent consumers to each “tune in” to the same broadcast of messages, without affecting each other—the streaming equivalent of having several different batch jobs that read the same input file.
  (This feature is provided by topic subscriptions in JMS, and exchange bindings in AMQP.)

The two patterns can be combined: for example, two separate groups of consumers may each subscribe to a topic, such that each group collectively receives all messages, but within each group only one of the nodes receives each message.

## Protocols

从功能支持、迭代速度、灵活性上考虑 大多数消息队列的核心通信协议都会选择自定义的私有协议

私有协议的设计

- 为了保证性能和可靠性 几乎所有主流消息队列在核心生产、消费链路的网络通信协议都是基于可靠性高、长连接的 [TCP](/docs/CS/CN/TCP/TCP.md) 协议
- 应用通信协议分为请求和返回两种 协议包含协议头和协议体两部分
- 编解码在实现上分为自定义实现和使用现有的编解码框架两种 从零实现编解码器比较复杂 一些消息队列（如 RocketMQ5.0 和 Pulsar) 开始使用业界成熟的编解码器 如 Google 的 [ProtocolBuffer](/docs//CS/Distributed/RPC/ProtoBuf.md)


## Network

基于 IO 多路复用技术和 Reactor 模型，可以解决网络模块的性能问题

网络模块的特点是编码非常复杂，要考虑的细节
和边界条件非常多，一些异常情况的处理也很细节，需要经过长时间的打磨。但是一旦开发完
成，稳定后，代码几乎不需要再改动，因为需求是相对固定的
而 Java NIO 库开发一个 Server 需要的工作量非常大
为了提高稳定性或者降低成本，选择现成的、成熟的 NIO 框
架是一个更好的方案
Netty 就是这样一个基于 Java NIO 封装的成熟框架 当前业界主流消息队列 RocketMQ、Pulsar 也都是基于 Netty 开发
的网络模块，Kafka 因为历史原因是基于 Java NIO 实现的

## Storage

消息队列中的数据一般分为元数据和消息数据  

元数据信息的特点是数据量比较小，不会经常读写，但是需要保证数据的强一致和高可靠，不允许出现数据的丢失。同时，元数据信息一般需要通知到所有的 Broker 节点，Broker 会根据元数据信息执行具体的逻辑  

元数据信息的存储，一般有两个思路。

- 基于第三方组件来实现元数据的存储。
- 在集群内部实现元数据的存储

基于第三方组件来实现元数据的存储是目前业界的主流选择。

比如 Kafka ZooKeeper 版本、Pulsar、RocketMQ 用的就是这个思路，其中 Kakfa 和 Pulsar 的元数据存储在 ZooKeeper中，RocketMQ 存储在 NameServer 中（准确说是存储在 Broker+NameServer 中）

这个方案最大的优点是集成方便，开发成本低，能满足消息队列功能层面的基本要求，因为我们可以直接复用第三方组件已经实现的一致性存储、高性能的读写和存储、Hook 机制等能力，而且在后续集群构建中也可以复用这个组件，能极大降低开发难度和工作成本  

但也有缺点。引入第三方组件会增加系统部署和运维的复杂度，而且第三方组件自身的稳定性问题会增加系统风险，第三方组件和多台 Broker 之间可能会出现数据信息不一致的情况，导致读写异常  

另一种思路，集群内部实现元数据的存储是指在集群内部完成元数据的存储和分发。也就是在集群内部实现类似第三方组件一样的元数据服务，比如基于 Raft 协议实现内部的元数据存储模块或依赖一些内置的数据库。目前 Kafka 去 ZooKeeper 的版本、RabbitMQ 的 Mnesia、Kafka 的 C++ 版本 RedPanda 用的就是这个思路  

这个方案的优缺点跟第一个正好相反。优点是部署和运维成本低，不会因为依赖第三方服务导致稳定性问题，也不会有数据不一致的问题。但缺点是开发成本高，前期要投入大量的开发人力  

### 消息数据存储

消息数据的存储，分为存储结构、数据分段、数据存储格式、数据清理四个部分  

在消息队列中，跟存储有关的主要是 Topic 和分区两个维度。用户可以将数据写入 Topic 或直接写入到分区  不过如果写入 Topic，数据也是分发到多个分区去存储的。所以从实际数据存储的角度来看，Topic 和 Group 不承担数据存储功能，承担的是逻辑组织的功能，实际的数据存储是在在分区维度完成的



从技术架构的角度，数据的落盘存储也有两个思路  

- 每个分区单独一个存储"文件"
- 每个节点上所有分区的数据都存储在同一个"文件"

第一个思路，每个分区对应一个文件的形式去存储数据。具体实现时，每个分区上的数据顺序写到同一个磁盘文件中，数据的存储是连续的。因为消息队列在大部分情况下的读写是有序的，所以这种机制在读写性能上的表现是最高的

但如果分区太多，会占用太多的系统 FD 资源，极端情况下有可能把节点的 FD 资源耗完，并且硬盘层面会出现大量的随机写情况，导致写入的性能下降很多，另外管理起来也相对复杂。Kafka 在存储数据的组织上用的就是这个思路



第二种思路，每个节点上所有分区的数据都存储在同一个文件中，这种方案需要为每个分区维护一个对应的索引文件，索引文件里会记录每条消息在 File 里面的位置信息，以便快速定位到具体的消息内容  

因为所有文件都在一份文件上，管理简单，也不会占用过多的系统 FD 资源，单机上的数据写入都是顺序的，写入的性能会很高

缺点是同一个分区的数据一般会在文件中的不同位置，或者不同的文件段中，无法利用到顺序读的优势，读取的性能会受到影响，但是随着 SSD 技术的发展，随机读写的性能也越来越高。如果使用 SSD 或高性能 SSD，一定程度上可以缓解随机读写的性能损耗，但 SSD 的成本比机械硬盘高很多

目前 RocketMQ、RabbitMQ 和 Pulsar 的底层存储 BookKeeper 用的就是这个方案

这种方案的数据组织形式一般是这样的。假设这个统一的文件叫 commitlog，则 commitlog就是用来存储数据的文件，.index 是每个分区的索引信息

选择呢哪种方案考虑是你对读和写的性能要求  

第一种方案，单个文件读和写都是顺序的，性能最高。但是当文件很多且都有读写的场景下，硬盘层面就会退化为随机读写，性能会严重下降

第二种方案，因为只有一个文件，不存在文件过多的情况，写入层面一直都会是顺序的，性能一直很高。但是在消费的时候，因为多个分区数据存储在同一个文件中，同一个分区的数据在底层存储上是不连续的，硬盘层面会出现随机读的情况，导致读取的性能降低

不过随机读带来的性能问题，可以通过给底层配备高性能的硬件来缓解。所以当前比较多的消息队列选用的是第二种方案，但是 Kafka 为了保证更高的吞吐性能，选用的是第一种方案  

不管是方案一还是方案二，在数据存储的过程中，如果单个文件过大，在文件加载、写入和检索的时候，性能就会有问题，并且消息队列有自动过期机制，如果单个文件过大，数据清理时会很麻烦，效率很低。所以，我们的消息数据都会分段存储  

数据分段的规则一般是根据大小来进行的，比如默认 1G 一个文件，同时会支持配置项调整分段数据的大小  

进行了分段，消息数据可能分布在不同的文件中。所以我们在读取数据的时候，就需要先定位消息数据在哪个文件中。为了满足这个需求，技术上一般有根据偏移量定位或根据索引定位两种思路  

根据偏移量（Offset）来定位消息在哪个分段文件中，是指通过记录每个数据段文件的起始偏移量、中止偏移量、消息的偏移量信息，来快速定位消息在哪个文件。

当消息数据存储时，通常会用一个自增的数值型数据（比如 Long）来表示这条数据在分区或commitlog 中的位置，这个值就是消息的偏移量

在实际的编码过程中，记录文件的起始偏移量一般有两种思路：单独记录每个数据段的起始和结束偏移量，在文件名称中携带起始偏移量信息。因为数据是顺序存储的，每个文件记录了本文件的起始偏移量，那么下一个文件的起始偏移量就是上一个文件的结束偏移量  

如果用索引定位，会直接存储消息对应的文件信息，而不是通过偏移量来定位到具体文件。

具体是通过维护一个单独的索引文件，记录消息在哪个文件和文件的哪个位置。读取消息的时候，先根据消息 ID 找到存储的信息，然后找到对应的文件和位置，读取数据。RabbitMQ 和RocketMQ 用的就是这个思路

这两种方案所面临的场景不一样。根据偏移量定位数据，通常用在每个分区各自存储一份文件的场景；根据索引定位数据，通常用在所有分区的数据存储在同一份文件的场景。因为在前一种场景，每一份数据都属于同一个分区，那么通过位点来二分查找数据的效率是最高的。第二种场景，这一份数据属于多个不同分区，则通过二分查找来查找数据效率很低，用哈希查找效率是最高的  

消息数据存储格式一般包含消息写入文件的格式和消息内容的格式两个方面  

从性能和空间冗余的角度来看，消息队列中的数据基本都是以二进制的格式写入到文件的  

消息内容的格式是指写入到文件中的数据都包含哪些信息。对于一个成熟的消息队列来说，消息内容格式不仅关系功能维度的扩展，还牵涉性能维度的优化
在数据的存储格式设计方面，内容的格式需要尽量完整且不要有太多冗余

消息数据的存储格式虽然没有统一的规范，但是一般包含通用信息和业务信息两部分。通用信息主要包括时间戳、CRC、消息头、消息体、偏移量、长度、大小等信息，业务信息主要跟业务相关，包含事务、幂等、系统标记、数据来源、数据目标等信息  

消息数据清理机制



消息队列中的数据最终都会删除，时间周期短的话几小时、甚至几分钟，正常情况一天、三天、七天，长的话可能一个月，基本很少有场景需要在消息队列中存储一年的数据。



消息队列的数据过期机制一般有手动删除和自动删除两种形式，从实现上看主要有三种思路

- 消费完成执行 ACK 删除数据
- 根据时间和保留大小删除
- ACK 机制和过期机制相结合  

消费完成执行 ACK 删除数据，技术上的实现思路一般是：当客户端成功消费数据后，回调服务端的 ACK 接口，告诉服务端数据已经消费成功，服务端就会标记删除该行数据，以确保消息不会被重复消费。ACK 的请求一般会有单条消息 ACK 和批量消息 ACK 两种形式  

纵观业界主流消息队列，三种方案都有在使用，RabbitMQ 选择的是第一个方案，Kafka 和RocketMQ 选择的是第二种方案，Pulsar 选择的是第三种方案  







## Partitioned Logs

A [log](/docs/CS/log/Log.md) is simply an append-only sequence of records on disk.

The same structure can be used to implement a message broker: a producer sends a message by appending it to the end of the log, and a consumer receives messages by reading the log sequentially.
If a consumer reaches the end of the log, it waits for a notification that a new message has been appended.

In order to scale to higher throughput than a single disk can offer, the log can be partitioned.
Different partitions can then be hosted on different machines, making each partition a separate log that can be read and written independently from other partitions.
A topic can then be defined as a group of partitions that all carry messages of the same type.

Within each partition, the broker assigns a monotonically increasing sequence number, or offset, to every message (in Figure 1, the numbers in boxes are message off‐sets).
Such a sequence number makes sense because a partition is append-only, so the messages within a partition are totally ordered. There is no ordering guarantee across different partitions.

<div style="text-align: center;">

![Fig.1. Partition logs](./img/Partition-Log.png)

</div>

<p style="text-align: center;">
Fig.1. Producers send messages by appending them to a topic-partition file, and consumers read these files sequentially.
</p>

[Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md), Amazon Kinesis Streams, and Twitter’s DistributedLog are log-based message brokers that work like this.
Google Cloud Pub/Sub is architecturally similar but exposes a JMS-style API rather than a log abstraction.
Even though these message brokers write all messages to disk, they are able to achieve throughput of millions of messages per second by partitioning across multiple machines, and fault tolerance by replicating messages [22, 23].

The log-based approach trivially supports fan-out messaging, because several consumers can independently read the log without affecting each other—reading a message does not delete it from the log.
To achieve load balancing across a group of consumers, instead of assigning individual messages to consumer clients, the broker can assign entire partitions to nodes in the consumer group.

Each client then consumes all the messages in the partitions it has been assigned.
Typically, when a consumer has been assigned a log partition, it reads the messages in the partition sequentially, in a straightforward single-threaded manner.
This coarsegrained load balancing approach has some downsides:

- The number of nodes sharing the work of consuming a topic can be at most the number of log partitions in that topic, because messages within the same partition are delivered to the same node.i
- If a single message is slow to process, it holds up the processing of subsequent messages in that partition (a form of head-of-line blocking.

Thus, in situations where messages may be expensive to process and you want to parallelize processing on a message-by-message basis, and where message ordering is not so important, the JMS/AMQP style of message broker is preferable.
On the other hand, in situations with high message throughput, where each message is fast to process and where message ordering is important, the log-based approach works very well.

### Compaction

If you only ever append to the log, you will eventually run out of disk space.
To reclaim disk space, the log is actually divided into segments, and from time to time old segments are deleted or moved to archive storage.
(We’ll discuss a more sophisticated way of freeing disk space later.)

This means that if a slow consumer cannot keep up with the rate of messages, and it falls so far behind that its consumer offset points to a deleted segment, it will miss some of the messages.
Effectively, the log implements a bounded-size buffer that discards old messages when it gets full, also known as a circular buffer or ring buffer.
However, since that buffer is on disk, it can be quite large.

Let’s do a back-of-the-envelope calculation. At the time of writing, a typical large hard drive has a capacity of 6 TB and a sequential write throughput of 150 MB/s.
If you are writing messages at the fastest possible rate, it takes about 11 hours to fill the drive.
Thus, the disk can buffer 11 hours’ worth of messages, after which it will start overwriting old messages.
This ratio remains the same, even if you use many hard drives and machines.
In practice, deployments rarely use the full write bandwidth of the disk, so the log can typically keep a buffer of several days’ or even weeks’ worth of messages.

Regardless of how long you retain messages, the throughput of a log remains more or less constant, since every message is written to disk anyway.
This behavior is in contrast to messaging systems that keep messages in memory by default and only write them to disk if the queue grows too large:
such systems are fast when queues are short and become much slower when they start writing to disk, so the throughput depends on the amount of history retained.

#### When consumers cannot keep up with producers

We discussed three choices of what to do if a consumer cannot keep up with the rate at which producers are sending messages: dropping messages, buffering, or applying backpressure.
In this taxonomy, the log-based approach is a form of buffering with a large but fixed-size buffer (limited by the available disk space).
If a consumer falls so far behind that the messages it requires are older than what is retained on disk, it will not be able to read those messages—so the broker effectively drops old messages that go back further than the size of the buffer can accommodate.
You can monitor how far a consumer is behind the head of the log, and raise an alert if it falls behind significantly.
As the buffer is large, there is enough time for a human operator to fix the slow consumer and allow it to catch up before it starts missing messages.

Even if a consumer does fall too far behind and starts missing messages, only that consumer is affected; it does not disrupt the service for other consumers.
This fact is a big operational advantage: you can experimentally consume a production log for development, testing, or debugging purposes, without having to worry much about disrupting production services.
When a consumer is shut down or crashes, it stops consuming resources—the only thing that remains is its consumer offset.

This behavior also contrasts with traditional message brokers, where you need to be careful to delete any queues whose consumers have been shut down—otherwise they continue unnecessarily accumulating messages and taking away memory from consumers that are still active.

#### Replaying old messages

We noted previously that with AMQP- and JMS-style message brokers, processing and acknowledging messages is a destructive operation, since it causes the messages to be deleted on the broker.
On the other hand, in a log-based message broker, consuming messages is more like reading from a file: it is a read-only operation that does not change the log.

The only side effect of processing, besides any output of the consumer, is that the consumer offset moves forward.
But the offset is under the consumer’s control, so it can easily be manipulated if necessary: for example, you can start a copy of a consumer with yesterday’s offsets and write the output to a different location, in order to reprocess the last day’s worth of messages.
You can repeat this any number of times, varying the processing code.



## Client

消息队列的客户端主要包含生产、消费、集群管控三类功能



### Producer

从客户端 SDK 实现的角度来看，生产模块包含客户端基础功能和生产相关功能两部分，其中基础功能是客户端中所有功能共用的 

生产模块基础功能包括请求连接管理、心跳检测、内容构建、序列化、重试、容错处理等等。生产功能是黄色部分，包括客户端寻址、分区选择、批量发送，生产错误处理、SSL、压缩、事务、幂等等等  

客户端和服务端之间基本都是通过各自语言的网络库，创建 TCP 长连接进行通信的。在大部分实现中，为了避免连接数膨胀，每个客户端实例和每台 Broker 只会维护一条 TCP 连接 

建立一条 TCP 连接很简单，更关键的是，什么情况下建立连接？一般有初始化创建连接和使用时创建链接两种方式  

因为客户端会有空闲连接回收机制，创建连接的耗时一般较短，所以在实际的架构实现中，两种方式都会用，优劣区别并不明显。不过，从资源利用率的角度考虑，建议你使用晚建立连接的方式。



因为连接并不是任何时候都有数据，可能出现长时间连接空闲。所以连接都会搭配连接回收机制，连接建立后如果连接出现长时间空闲，就回收连接。连接回收的策略一般是判断这段时间内是否有发送数据的行为，如果没有就判断是空闲，然后执行回收

因为单个 TCP 连接发送性能存在上限，我们就需要在客户端启动多个生产者，提高并发读写的能力。一般情况下，每个生产者会有一个唯一的 ID 或唯一标识来标识客户端，比如ProduceID 或客户端的 IP+Port  



客户端和服务端之间的心跳检测机制的实现，一般有基于 TCP 的 KeepAlive 保活机制和应用层主动探测两种形式  



 从请求的角度，有些错误是重试可以恢复的，比如连接断开、Leader 切换、发送偶尔超时、服务端某些异常等；有些错误是不可恢复的，比如 Topic/ 分区不存在、服务端 Broker 不存在、集群和 Broker 长时间无响应等。



所以，在客户端的处理中也会将错误分为可重试错误和不可重试错误两类

因为网络环境、架构部署的复杂性，集群可能出现短暂网络抖动、Leader 切换等异常，可重试错误就是这类通过一次或多次重试可能恢复的异常；不可重试的错误就是不管如何重试都无法恢复的异常

客户端收到可重试错误后，会通过一定的策略进行重试，尽量确保生产流程的顺利进行

虽然实现思路很直接、很简单，但在客户端 SDK 的实现过程中，错误处理是一个包含很多细节的工作，一般需要考虑下面几个点

如何定义可恢复错误和不可恢复错误。
完整的错误码的定义和枚举，好的错误码定义可以提高排查问题的效率。
错误后重试的代码实现方式是否合理高效。
判断哪些情况需要停止客户端，向上抛错，以免一些错误信息一直在 SDK 内空转，提高上层感知异常和排查异常的难度。
日志信息打印 debug、info、error 日志时，是否包含了完整的内容

重试机制

发生错误后，客户端一般会提供重试策略，接下来我们来看看重试机制的实现。

重试策略一般会支持重试次数和退避时间的概念。当消息失败，超过设置的退避时间后，会继续重试，当超过重试次数后，就会抛弃消息或者将消息投递到配置好的重试队列中。

退避时间是可以配置的，比如 1s、10s、1 分钟。当出现错误时，就会根据退避策略退避，再尝试写入。一般情况下，重试是有次数上限的，当然也支持配置无限重试。

退避策略影响的是重试的成功率，因为网络抖动正常是 ms 级，某些异常可能会抖动十几秒。此时，如果退避策略设置得太短，在退避策略和重试次数用完后，可能消息还没生产成功；如果退避时间设置太长，可能导致客户端发送堵塞消息堆积



客户端寻址机制  

业界提出了 Metadata（元数据）寻址机制和服务端内部转发两个思路  

服务端会提供一个获取全量的 Metadata 的接口，客户端在启动时，首先通过接口拿到集群所有的元数据信息，本地缓存这部分数据信息。然后，客户端发送数据的时候，会根据元数据信息的内容，得到服务端的地址是什么，要发送的分区在哪台节点上。最后根据这两部分信息，将数据发送到服务端  

在 Metadata 寻址机制中，元数据信息主要包括 Topic 及其对应的分区信息和 Node 信息两部分  

客户端一般通过定期全量更新 Metadata 信息和请求报错时更新元数据信息两种方式，来保证客户端的元数据信息是最新的。目前 Kafka、RocketMQ、Pulsar 用的都是这个方案



另外一种服务端内部转发机制，客户端不需要经过寻址的过程，写入的时候是随机把数据写入到服务端任意一台 Broker。

具体思路是服务端的每一台 Broker 会缓存所有节点的元数据信息，生产者将数据发送给Broker 后，Broker 如果判断分区不在当前节点上，会找到这个分区在哪个节点上，然后把数据转发到目标节点

这个方案的好处是分区寻址在服务端完成，客户端的实现成本比较低。但是生产流程多了一跳，耗时增加了。另外服务端因为转发多了一跳，会导致服务端的资源损耗多一倍，比如CPU、内存、网卡，在大流量的场景下，这种损耗会导致集群负载变高，从而导致集群性能降低。

所以这种方案不适合大流量、高吞吐的消息队列。目前业界只有 RabbitMQ 使用这个方案。



生产分区分配策略

我们知道，数据可以直接写入分区或者写入 Topic。写入 Topic 时，最终数据还是要写入到某个分区。这个数据选择写入到哪个分区的过程，就是生产数据的分区分配过程。过程中的分配策略就是生产分区分配策略



一般情况下，消息队列默认支持轮询、按 Key Hash、手动指定、自定义分区分配策略四种分区分配策略

轮询是所有消息队列的默认选项。消息通过轮询的方式依次写入到各个分区中，这样可以保证每个分区的数据量是一样的，不会出现分区数据倾斜  

但是如果我们需要保证数据的写入是有序的，轮询就满足不了。因为在消费模型中，每个分区的消费是独立的，如果数据顺序依次写入多个分区，在消费的时候就无法保持顺序。所以为了保证数据有序，就需要保证 Topic 只有一个分区。这是另外两种分配策略的思路  

按 Key Hash 是指根据消息的 Key 算出一个 Hash 值，然后跟 Topic 的分区数取余数，算出一个分区号，将数据写入到这个分区中  

这种方案的好处是可以根据 Key 来保证数据的分区有序。比如某个用户的访问轨迹，以客户的 AppID 为 Key，按 Key Hash 存储，就可以确保客户维度的数据分区有序。缺点是分区数量不能变化，变化后 Hash 值就会变，导致消息乱序。并且因为每个 Key 的数据量不一样，容易导致数据倾斜。



手动指定

很简单，就是在生产数据的时候，手动指定数据写入哪个分区。这种方案的好处就是灵活，用户可以在代码逻辑中根据自己的需要，选择合适的分区，缺点就是业务需要感知分区的数量和变化，代码实现相对复杂。



除了这 3 种默认策略，消息队列也支持

自定义分区分配策略，让用户灵活使用。内核提供Interface（接口）机制，用户如果需要指定自定义的分区分配策略，可以实现对应的接口，然后配置分区分配策略。比如 Kafka 可以通过实现org.apache.kafka.clients.producer.Partitioner 接口实现自定义分区策略

客户端支持批量写入数据的前提是，需要在协议层支持批量的语义。否则就只能在业务中自定义将多条消息组成一条消息。



批量发送的实现思路一般是在客户端内存中维护一个队列，数据写入的时候，先将其写到这个内存队列，然后通过某个策略从内存队列读取数据，发送到服务端

批量发送数据的策略和存储模块的刷盘策略很像，都是根据数据条数或时间聚合后，汇总发送到服务端，一般是满足时间或者条数的条件后触发发送操作，也会有立即发送的配置项。  

Kafka 是按照时间的策略批量发送的，提供了 linger.ms、max.request.size、batch.size 三个参数，来控制数据的批量发送  

Pulsar 也提供了 batchingEnabled, batchingMaxMessages, batchingMaxPublishDelayMicros 三个参数，来控制数据批量发送

数据发送方式



消息队列一般也会提供同步发送、异步发送、发送即忘三种形式。



同步和异步更多是语言语法的实现，同步发送主要解决数据发送的即时性和顺序性，异步发送主要考虑性能

发送即忘指消息发送后不关心请求返回的结果，立即发送下一条。这种方式因为不用关心发送结果，发送性能会提升很多。缺点是当数据发送失败时无法感知，可能有数据丢失的情况，所以适合用在发送不重要的日志等场景。Kafka 提供了 ack=0、RocketMQ 提供了sendOneway 来支持这种模式  

集群管控操作



集群管控操作一般是用来完成资源的创建、查询、修改、删除等集群管理动作。资源包括主题、分区、配置、消费分组等等。



从功能上来看，消息队列一般会提供多种集群管理方式，比如命令行、客户端、HTTP 接口等等。



命令行工具是最基本的支持方式

有的消息队列也会支持 HTTP 接口形式的管控操作。好处是因为 HTTP 协议的通用性，业务可以从各个环境发起管控的调用，不用非得使用 admin SDK。另外客户端封装 HTTP 接口实现命令行工具的成本也比较低。



### Consumer

消费端 SDK 和生产端 SDK 一样，主要包括客户端基础功能和消费相关功能两部分  

从实现来看，消费相关功能包括消费模型、分区消费模式、消费分组（订阅）、消费确认、消费失败处理五个部分  



为了满足不同场景的业务需求，从实现机制上来看，主流消息队列一般支持 Pull、Push、Pop 三种消费模型  



## Model

### Message Queue

A message queue is a form of asynchronous service-to-service communication used in serverless and microservices architectures.
Messages are stored on the queue until they are processed and deleted. Each message is processed only once, by a single consumer.
Message queues can be used to decouple heavyweight processing, to buffer or batch work, and to smooth spiky workloads.

In modern cloud architecture, applications are decoupled into smaller, independent building blocks that are easier to develop, deploy and maintain.
Message queues provide communication and coordination for these distributed applications.
Message queues can significantly simplify coding of decoupled applications, while improving performance, reliability and scalability.
Message queues allow different parts of a system to communicate and process operations asynchronously.
A message queue provides a lightweight buffer which temporarily stores messages, and endpoints that allow software components to connect to the queue in order to send and receive messages.
The messages are usually small, and can be things like requests, replies, error messages, or just plain information. To send a message, a component called a producer adds a message to the queue.
The message is stored on the queue until another component called a consumer retrieves the message and does something with it.

<div style="text-align: center;">

![Fig.1. Message queue](./img/P2P.png)

</div>

<p style="text-align: center;">
Fig.1. Message queue.
</p>

Many producers and consumers can use the queue, but each message is processed only once, by a single consumer.
For this reason, this messaging pattern is often called one-to-one, or point-to-point, communications.
When a message needs to be processed by more than one consumer, message queues can be combined with Pub/Sub messaging in a fanout design pattern.

### Pub-Sub

The Publish Subscribe model allows messages to be broadcast to different parts of a system asynchronously.
A sibling to a message queue, a message topic provides a lightweight mechanism to broadcast asynchronous event notifications, and endpoints that allow software components to connect to the topic in order to send and receive those messages.
To broadcast a message, a component called a publisher simply pushes a message to the topic.
Unlike message queues, which batch messages until they are retrieved, message topics transfer messages with no or very little queuing, and push them out immediately to all subscribers.
All components that subscribe to the topic will receive every message that is broadcast, unless a message filtering policy is set by the subscriber.

<div style="text-align: center;">

![Fig.2. Pub/Sub](./img/PubSub.png)

</div>

<p style="text-align: center;">
Fig.2. Pub/Sub.
</p>

The subscribers to the message topic often perform different functions, and can each do something different with the message in parallel.
The publisher doesn’t need to know who is using the information that it is broadcasting, and the subscribers don’t need to know who the message comes from.
This style of messaging is a bit different than message queues, where the component that sends the message often knows the destination it is sending to.

## Features

### Message Delivery Semantics

By message delivery semantics, we refer to the expected message delivery guaranties in the case of failure recovery.
After a failure recovery, we recognize these different message delivery guarantees:

- *At most once*
  Data may have been processed but will never be processed twice. In this case, data may be lost but processing will never result in duplicate records.
- *At-least-once*
  Data that has been processed may be replayed and processed again. In this case, each data record is guaranteed to be processed and may result in duplicate records.
- *Exactly once*
  Data is processed once and only once. All data is guaranteed to be processed and no duplicate records are generated.
  This is the most desirable guarantee for many enterprise applications, but it’s considered impossible to achieve in a distributed environment.
- *Effectively Exactly Once*
  is a variant of *exactly once* delivery semantics that tolerates duplicates during data processing and requires the producer side of the process to be idempotent.
  That is, producing the same record more than once is the same as producing it only once. In practical terms, this translates to writing the data to a system that can preserve the uniqueness of keys or use a deduplication process to prevent duplicate records from being produced to an external system.

### Push versus Pull

Most message queues provide both push and pull options for retrieving messages.

- Pull means continuously querying the queue for new messages.
- Push means that a consumer is notified when a message is available.

A push-based system has difficulty dealing with diverse consumers as the broker controls the rate at which data is transferred.
The goal is generally for the consumer to be able to consume at the maximum possible rate; unfortunately, in a push system this means the consumer tends to be overwhelmed when its rate of consumption falls below the rate of production (a denial of service attack, in essence).
A pull-based system has the nicer property that the consumer simply falls behind and catches up when it can.
This can be mitigated with some kind of backoff protocol by which the consumer can indicate it is overwhelmed, but getting the rate of transfer to fully utilize (but never over-utilize) the consumer is trickier than it seems.
Previous attempts at building systems in this fashion led us to go with a more traditional pull model.

Another advantage of a pull-based system is that it lends itself to aggressive batching of data sent to the consumer.
A push-based system must choose to either send a request immediately or accumulate more data and then send it later without knowledge of whether the downstream consumer will be able to immediately process it.
If tuned for low latency, this will result in sending a single message at a time only for the transfer to end up being buffered anyway, which is wasteful.
A pull-based design fixes this as the consumer always pulls all available messages after its current position in the log (or up to some configurable max size).
So one gets optimal batching without introducing unnecessary latency.

The deficiency of a naive pull-based system is that if the broker has no data the consumer may end up polling in a tight loop, effectively busy-waiting for data to arrive.

### Schedule or Delay Delivery

Many message queues support setting a specific delivery time for a message. If you need to have a common delay for all messages, you can set up a delay queue.

### Dead-letter Queues

Sometimes, messages can't be processed because of a variety of possible issues, such as erroneous conditions within the producer or consumer application or an unexpected state change that causes an issue with your application code.
For example, if a user places a web order with a particular product ID, but the product ID is deleted, the web store's code fails and displays an error, and the message with the order request is sent to a dead-letter queue.

Occasionally, producers and consumers might fail to interpret aspects of the protocol that they use to communicate, causing message corruption or loss. Also, the consumer's hardware errors might corrupt message payload.

A dead-letter queue is a queue to which other queues can send messages that can't be processed successfully.
This makes it easy to set them aside for further inspection without blocking the queue processing or spending CPU cycles on a message that might never be consumed successfully.

The main task of a dead-letter queue is handling message failure.
A dead-letter queue lets you set aside and isolate messages that can’t be processed correctly to determine why their processing didn’t succeed.
Setting up a dead-letter queue allows you to do the following:

- Configure an alarm for any messages delivered to a dead-letter queue.
- Examine logs for exceptions that might have caused messages to be delivered to a dead-letter queue.
- Analyze the contents of messages delivered to a dead-letter queue to diagnose software or the producer’s or consumer’s hardware issues.
- Determine whether you have given your consumer sufficient time to process messages.

When should I use a dead-letter queue?

- Do use dead-letter queues with high-throughput, unordered queues.
- You should always take advantage of dead-letter queues when your applications don’t depend on ordering. Dead-letter queues can help you troubleshoot incorrect message transmission operations.
- Note: Even when you use dead-letter queues, you should continue to monitor your queues and retry sending messages that fail for transient reasons.
- Do use dead-letter queues to decrease the number of messages and to reduce the possibility of exposing your system to poison-pill messages (messages that can be received but can’t be processed).
- Don’t use a dead-letter queue with high-throughput, unordered queues when you want to be able to keep retrying the transmission of a message indefinitely.
- For example, don’t use a dead-letter queue if your program must wait for a dependent process to become active or available.
- Don’t use a dead-letter queue with a FIFO queue if you don’t want to break the exact order of messages or operations.
- For example, don’t use a dead-letter queue with instructions in an Edit Decision List (EDL) for a video editing suite, where changing the order of edits changes the context of subsequent edits.

### Ordering

Most message queues provide best-effort ordering which ensures that messages are generally delivered in the same order as they're sent, and that a message is delivered at least once.



### Transaction Message



### Poison-pill Messages

Poison pills are special messages that can be received, but not processed.
They are a mechanism used in order to signal a consumer to end its work so it is no longer waiting for new inputs, and is similar to closing a socket in a client/server model.



### Message Tracing

消息轨迹

## Security

Message queues will authenticate applications that try to access the queue, and allow you to use encryption to encrypt messages over the network as well as in the queue itself.

## Architecture

最基础的消息队列应该具备五个模块。

- 通信协议：用来完成客户端（生产者和消费者）和 Broker 之间的通信，比如生产或消费
- 网络模块：客户端用来发送数据，服务端用来接收数据
- 存储模块：服务端用来完成持久化数据存储
- 生产者：完成生产相关的功能
- 消费者：完成消费相关的功能



消息队列的核心特性是高吞吐、低延时、高可靠，所以在协议上至少需要满足  

协议可靠性要高，不能丢数据。协议的性能要高，通信的延时要低  协议的内容要精简，带宽的利用率要高。协议需要具备可扩展能力，方便功能的增减  

大多数消息队列为了自身的功能支持、迭代速度、灵活性考虑，在核心通信协议的选择上不会选择公有协议，都会选择自定义私有协议  

私有协议的设计主要考虑网络通信协议选择、应用通信协议设计、编解码实现三个方面  

网络通信协议选型，基于可靠、低延时的需求，大部分情况下应该选择 TCP。

应用通信协议设计，分为请求协议和返回协议两方面。协议应该包含协议头和协议体两部分。协议头主要包含一些通用的信息，协议体包含请求维度的信息

RocketMQ 是业界唯一一个既支持自定义编解码，又支持成熟编解码框架的消息队列产品。RocketMQ 5.0 之前支持的 Remoting 协议是自定义编解码，5.0 之后支持的 gRPC 协议是基于 Protobuf 编解码框架  





## store



单文件/多文件

|              | 单文件               | 多文件       |
| ------------ | -------------------- | ------------ |
| 文件大小     | 大                   | 小           |
| 数据定位     | 需要索引辅助快速定位 | 需要索引辅助 |
| 读取速率     | 块                   | 非常快       |
| 内存映射空间 | 大                   | 小           |
| 内存映射频率 | 低                   | 高           |
| 实现难度     | 中等                 | 较高         |
| 使用场景     |                      |              |



根据topic分文件













存储消息体结构



Consumer Queue

多个Consumer Group 对应不同的 consume offset





注册中心 broker 元数据









## Issues

### Disk Access

#### PageCache

mmap

sendfile

- Write
- Tailing Read
- Catch-up Read

### High Availability

RabbitMQ

Mirroring Cluster

Kafka

Topic can be multiple partitions

partitions have replicate in other brokers

we can only read/write leader

leader will sync data to followers, return ack when most of followers sync successfully

### lost message

RabbitMQ

- producer confirm
- broker storage
- consumer confirm manually

Kafka

- broker
  - unclean.leader.election.enable = false
  - set topic repliaction factor > 1 : at least 2 partitions
  - set broker min.insync.replicas > 1 : at least 1 follower
  - replication.factor = min.insync.replicas + 1
- producer
  - set producer acks = all : must write to all replicas then ack
  - set producer retries = MAX : retry util success
- consumer
  - enable.auto.commit: false

Producer:

正确处理返回值或者捕获异常并重发，就可以保证这个阶段的消息不会丢

Broker:

如果
Broker 出现了故障，比如进程死掉了或者服务器宕机了，还是可能会丢失消息的

配置刷盘

至少将消息发送到 2 个以上的节点，再给客户端回复发送确认响应

Consumer:

在执行完所有消费业务逻辑之后，再发送消费确认。

### Duplicate Consume

Based on no message losing

- Redis is always idempotent.
- DB primary key is unique.
- update wehn exist, insert when not exist.
- every request has own message id, check if has consumed(a set).

### message ordering

Kafka partition -> queue -> thread



### 消息积压

消息积压问题通常是消费侧的问题 因为一个 Topic 通常会被多个消费端订阅，我们只要看看其他消费组是否也积压

## MQs



如果没有大消息和大流量等复杂场景，是可以选用非标准消息队列产品的。比如在用户状态审核的场景中，只需要向下游传递用户 ID 和审核结果，结构简单，数量有限。这时候选择非标准消息队列比如 Redis 和 MySQL 也是可以的  



早年业界消息队列演进的主要推动力在于功能（如延迟消息、事务消息、顺序消息等）、场景（实时场景、大数据场景等）、分布式集群的支持等等。近几年，随着云原生架构和Serverless 的普及，业界 MQ 主要向实时消息和流消息的融合架构、Serverless、Event、协议兼容等方面演进。从而实现计算、存储的弹性，实现集群的 Serverless 化  

- 从需求发展路径上看，消息队列的发展趋势是：消息 -> 流 -> 消息和流融合
- 从架构发展的角度来看，消息队列的发展趋势是：单机 -> 分布式 -> 云原生/Serverless

消息、流分开来看都比较好理解。

- 消息就是业务消息，在业务架构（比如微服务架构）中用来作消息传递，做系统的消息总线，比如用户提交订单的流程。

- 流，就是在大数据架构中用来做大流量时的数据削峰，比如日志的投递流转

消息和流融合就是这两个事情都能做。不过为什么会有消息和流融合的这个趋势呢

其实都是钱的原因。虽然消息队列是基础组件，但是功能比较单一，主要是缓冲作用，在消息、流的方向上，功能需求一直是相对固定的，细分的市场也都有领头组件，流领域目前是Kafka 一家独大，消息领域的头部玩家，国外是 RabbitMQ，国内是 RocketMQ  

当前开源社区用的较多的消息队列主要有 RabbitMQ、Kafka，RocketMQ 和Pulsar 四款  

When the message sending and consumption ends coexist, the increasing number of topics will cause a drastic decline of Kafka's throughput, while Apache RocketMQ delivers a stable performance.
Therefore, Kafka is more suitable for business scenarios with only a few topics and consumption ends, while Apache RocketMQ is a better choice for business scenarios with multiple topics and consumption ends.

The difference is attributable to the fact that every topic and partition of Kafka correspond to one physical file.
When the number of topics increases, the policy of deconcentrated storage of messages to disks will lead to disk IO competition to cause performance bottlenecks.
In contrast, all the messages in Apache RocketMQ are stored in the same physical file. The number of topics and partitions is just a logic division for Apache RocketMQ.
So the increasing number of topics won't generate a huge impact on the Apache RocketMQ performance.

The Cons of Using RabbitMQ:

- Once a message with RabbitMQ has been delivered it is removed from the queue.
- RabbitMQ scales vertically and relies on getting more powerful hardware to increase throughput.
- RabbitMQ stores messages in memory as long as there is space after which messages will be transferred to disk.
- RabbitMQ cannot deal with high throughput, as it doesn’t support message batching, and is optimized for one message at a time instead.
- Many of RabbitMQ’s disadvantages stem from being written in Erlang, however, it can also be difficult for a developer to read the source code and understand what’s going on when troubleshooting.

### Kafka

[Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md) is an open-source distributed event streaming platform used by thousands of companies for high-performance data pipelines, streaming analytics, data integration, and mission-critical applications.

### RocketMQ

[Apache RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)


### Pulsar

[Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md) is a distributed pub-sub messaging platform with a very flexible messaging model and an intuitive client API.


下一代消息队列 RobustMQ


### Comparison


| Messaging Product              | ActiveMQ                                                     | Kafka                                                        | RocketMQ                                                     | Pulsa |
| ------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ | ----- |
| Client SDK                     | Java, .NET, C++ etc.                                         | Java, Scala etc.                                             | Java, C++, Go                                                |       |
| Protocol and Specification     | Push model, support OpenWire, STOMP, AMQP, MQTT, JMS         | Pull model, support TCP                                      | Pull model, support TCP, JMS, OpenMessaging                  |       |
| Ordered Message                | Exclusive Consumer or Exclusive Queues can ensure ordering   | Ensure ordering of messages within a partition               | Ensure strict ordering of messages,and can scale out gracefully |       |
| Scheduled Message              | Supported                                                    | Not Supported                                                | Supported                                                    |       |
| Batched Message                | Not Supported                                                | Supported, with async producer                               | Supported, with sync mode to avoid message loss              |       |
| BroadCast Message              | Supported                                                    | Not Supported                                                | Supported                                                    |       |
| Message Filter                 | Supported                                                    | Supported, you can use Kafka Streams to filter messages      | Supported, property filter expressions based on SQL92        |       |
| Server Triggered Redelivery    | Not Supported                                                | Not Supported                                                | Supported                                                    |       |
| Message Storage                | Supports very fast persistence using JDBC along with a high performance journal，such as levelDB, kahaDB | High performance file storage                                | High performance and low latency file storage                |       |
| Message Retroactive            | Supported                                                    | Supported offset indicate                                    | Supported timestamp and offset two indicates                 |       |
| Message Priority               | Supported                                                    | Not Supported                                                | Not Supported                                                |       |
| High Availability and Failover | Supported, depending on storage,if using levelDB it requires a ZooKeeper server | Supported                                                    | Supported, Master-Slave model, without another kit           |       |
| Message Track                  | Not Supported                                                | Not Supported                                                | Supported                                                    |       |
| Configuration                  | The default configuration is low level, user need to optimize the configuration parameters | Kafka uses key-value pairs format for configuration. <br />These values can be supplied either from a file or programmatically. | Work out of box,user only need to pay attention to a few configurations |       |
| Management and Operation Tools | Supported                                                    | Supported, use terminal command to expose core metrics       | Supported, rich web and terminal command to expose core metrics |       |

Topic

Kafka partition -> segment -> .log, .index, .timeindex

RocketMQ all topics using single commitlog and multiple index




naming Service

- rocketmq ， client connect to the name server getting the topics and brokers 
- Kafka clients connect to the broker 


为什么 RocketMQ 参考了 Kafka 的架构，却无法与 Kafka 保持相同的性能呢

Kafka：使用 sendfile 函数进行零拷贝，以减少数据拷贝次数和系统内核切换次数，从而获得更高的性能。sendfile 返回的是发送成功的字节数，而应用层无法获取到消息内容。Kafka 以更少的拷贝次数以及系统内核切换次数，获得了更高的性能
RocketMQ：使用 mmap 技术进行零拷贝，返回的是数据的具体内容，应用层可以获取消息内容并进行一些逻辑处理。
RocketMQ 的一些功能需要了解具体这个消息内容，方便二次投递等，比如将消费失败的消息重新投递到死信队列中


RocketMQ 和 Kafka 相比，在架构上做了减法，在功能上做了加法：RocketMQ 简化了协调节点和分区以及备份模型，同时增强了消息过滤、消息回溯和事务能力，加入了延迟队列、死信队列等新特性

## Links

- [Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Apache RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
- [Apache Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md)

## References

1. [Kafka vs. Apache RocketMQ™- Multiple Topic Stress Test Results](https://www.alibabacloud.com/blog/kafka-vs-rocketmq--multiple-topic-stress-test-results_69781)
2. [OpenMessaging](https://openmessaging.cloud/design/2018/03/28/openmessaging-domain-architecture-v0.3/)
