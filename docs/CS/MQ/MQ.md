## Introduction



In computer science, message queues and mailboxes are software-engineering components typically used for inter-process communication (IPC), or for inter-thread communication within the same process. 
They use a queue for messaging – the passing of control or of content. Group communication systems provide similar kinds of functionality.


Half Message




- 解耦：A系统依赖B,C,D系统，A只需要发送topic，B,C,D后期不需要消息自行取消消费即可，类似消息总线
- 消峰：应对突发的流量高峰时段（错峰与流控）


issues

- 系统复杂度提高
- 系统可用性降低

## Model

Queue

Pub/Sub



### Pull/Push

#### push



#### pull

Long waiting





## Mq怎么选型，各个Mq中间件的优缺点？

- 开源产品，市场任何度
- 消息可靠性
- 跨语言支持
- 性能
- 功能

![img](https://p3-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/83347d6db01b43269235e1130753f1d8~tplv-k3u1fbpfcp-zoom-1.image?imageslim)





## issues


- At most one
- At least one
- exactly one



### High Avaliability

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



### Duplicate Consume

Based on no message losing


- Redis is always idempotent.
- DB primary key is unique.
- update wehn exist, insert when not exist.
- every request has own id, check if has consumed(a set).



### message ordering

Kafka partition -> queue -> thread


### Backlog and recover



### Consistency

 使用可靠消息最终一致性的分布式事务方案来保障

### Ordering

一笔订单产生了3条消息，分别是订单创建、订单付款、订单完成。消费时，要按照顺序依次消费才有意义

出现原因：

- 一个queue，有多个consumer去消费。因为每个consumer的执行时间是不固定的，先读到消息的consumer不一定先完成操作
- 一个queue对应一个consumer，但是consumer里面进行了多线程消费，这样也会造成消息消费顺序错误

解决：

- 有关联的同一组消息1、2、3发到queue1中，然后消费者1消费，因为消息队列本来就是有序的，所以这样就有序。为了提高性能，搞多个queue，有关联的同一组消息发到同一队列，每个队列都有唯一的消费者
- 一个queue但是对应一个consumer，然后这个consumer内部用内存队列做排队，然后分发给底层不同的worker来处理。原理和上面一样，都是保证同一组消息发给同一队列，然后被同一消费者消费
- 既然要求“同一组消息发给同一队列，然后被同一消费者消费”，那最好的办法是把同一组消息合并成一条。这样性能更好，无论多线程、还是多消费者都ok。

有人可能说合并后会不会数据量太大？ 大多数场景都不要求顺序执行。比如电商支付完后需要：App推送、短信推送、加积分、给仓库发发货的消息、修改购物推荐；比如支付宝抢红包，先抢到的不要求先到账。

总结：涉及到发送方集群，mq集群，接收方集群

- 保证发送方是顺序发送
- 保证同一个唯一标识（订单号）只发送到指定Mq Server上
- 保证同一个唯一标识（订单号）只在一个接收方节点上消费

### Backlog

- 临时扩容，以更快的速度去消费数据了，先修复consumer的问题，确保其恢复消费速度，然后将现有consumer都停掉。临时建立好原先10倍或者20倍的queue数量(新建一个topic，partition是原来的10倍)。然后写一个临时分发消息的consumer程序，这个程序部署上去消费积压的消息，消费之后不做耗时处理，直接均匀轮询写入临时建好分10数量的queue里面。紧接着征用10倍的机器来部署consumer，每一批consumer消费一个临时queue的消息。

这种做法相当于临时将queue资源和consumer资源扩大10倍，以正常速度的10倍来消费消 等快速消费完了之后，恢复原来的部署架构，重新用原来的consumer机器来消费消息 ![image](https://p3-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/b2ff06bc09994c55bac44a807535bbd7~tplv-k3u1fbpfcp-zoom-1.image)

- 临时写个程序，连接到mq里面消费数据，收到消息之后直接存redis，后续重发
- mq完全放不下,快挂了,写个程序，连接到mq里面消费数据，收到消息之后直接将其丢弃，快速消费掉积压的消息，降低MQ的压力，然后走第二种方案
- 堆积引起的丢失，高峰期过后手动去查询丢失的那部分数据，然后将消息重新发送到mq里面，把丢失的数据重新补回来

### 消息重复发送问题（消息幂等性）

uuid-redis，唯一索引，状态机判断

### 消息丢失问题

- rabbitMq

```
生产者：
开启confirm模式（异步），写的消息都会分配一个唯一的id，rabbitmq会给你回传一个ack消息

mq server：
queue持久化，可以保证rabbitmq持久化queue的元数据，但是不会持久化queue里面的数据
deliveryMode设置为2，这样消息就会被设为持久化方式，此时rabbitmq就会将消息持久化到磁盘上。
就算是在持久化之前rabbitmq挂了，数据丢了，生产者收不到ack回调也会进行消息重发

消费者：
使用rabbitmq提供的ack机制，首先关闭rabbitmq的自动ack，然后每次在确保处理完这个消息之后，
在代码里手动调用ack。这样就可以避免消息还没有处理完就ack
复制代码
```

- kafka

```
消费者：
关闭自动提交offset，在自己处理完毕之后手动提交offset，这样就不会丢失数据。

mq server：
一般要求设置4个参数来保证消息不丢失：
给topic设置 replication.factor参数：这个值必须大于1，要求每个partition必须至少有2个副本。
在kafka服务端设置min.isync.replicas参数：这个值必须大于1， 要求一个leader至少感知到有至少一个follower
在跟自己保持联系正常同步数据，这样才能保证leader挂了之后还有一个follower。
在生产者端设置acks=all：表示要求每条每条数据，必须是写入所有replica副本之后，才能认为是写入成功了
在生产者端设置retries=MAX(很大的一个值，表示无限重试)：表示 这个是要求一旦写入事变，就无限重试

生产者：
如果按照上面设置了ack=all，则一定不会丢失数据，要求是，你的leader接收到消息，
所有的follower都同步到了消息之后，才认为本次写成功了。如果没满足这个条件，
生产者会自动不断的重试，重试无限次
复制代码
```

## Mq集群方式

- rabbitMq

1. 单机模式
2. 普通集群 每次写消息到queue的时候，都会自动把消息到多个queue里进行消息同步，每个节点都有queue队列的元数据，还需要去对应节点拉数据再返回
3. 镜像集群模式 每次写消息到queue的时候，都会自动把消息到多个queue里进行消息同步，每个节点都有queue队列的完整数据

- kafka

1. 多个broker组成，一个broker是一个节点；你创建一个topic，这个topic可以划分成多个partition，每个partition可以存在于不同的broker上面，每个partition存放一部分数据。这是天然的分布式消息队列

## Mq知识点

### 数据交互模式：

Push（推模式）、Pull（拉模式）

push更关注实时性，pull更关注消费者消费能力

推模式指的是客户端与服务端建立好网络长连接，服务方有相关数据，直接通过长连接通道推送到客户端。其优点是及时，一旦有数据变更，客户端立马能感知到；另外对客户端来说逻辑简单，不需要关心有无数据这些逻辑处理。缺点是不知道客户端的数据消费能力，可能导致数据积压在客户端，来不及处理。

拉模式指的是客户端主动向服务端发出请求，拉取相关数据。其优点是此过程由客户端发起请求，故不存在推模式中数据积压的问题。缺点是可能不够及时，对客户端来说需要考虑数据拉取相关逻辑，何时去拉，拉的频率怎么控制等等。

拉模式中，为了保证消息消费的实时性，采取了长轮询消息服务器拉取消息的方式。每隔一定时间，客户端想服务端发起一次请求，服务端有数据就返回数据，服务端如果此时没有数据，保持连接。等到有数据返回（相当于一种push），或者超时返回。长轮询Pull的好处就是可以减少无效请求，保证消息的实时性，又不会造成客户端积压。

推模式是最常用的，但是有些情况下推模式并不适用的，比如说： 由于某些限制，消费者在某个条件成立时才能消费消息 需要批量拉取消息进行处理

rabbitMq推模式实现SimpleMessageListenerContainer 拉模式：basicGet

### 消费关系处理

- 单播，就是点到点
- 广播，是一点对多点，一个生产者，对应对个消费者消费-发布订阅Publish\Subscribe

为了实现广播功能，我们必须要维护消费关系，通常消息队列本身不维护消费订阅关系，可以利用zookeeper等成熟的系统维护消费关系，在消费关系发生变化时下发通知



## RabbitMq

based on Erang, and it's hard to deploy the environment. 

![image](https://p3-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/ebf2c7e68c0148808fcc5798e7b7711f~tplv-k3u1fbpfcp-zoom-1.image)

```
工作模式
Exchange有常见以下3种类型：
Fanout：广播，将消息交给所有绑定到交换机的队列
Direct：组播，定向，把消息交给符合指定routing key 的队列
Topic：规则播，通配符，把消息交给符合routing pattern（路由模式） 的队列
Header

1、简单模式 HelloWorld
一个生产者、一个消费者，不需要设置交换机（使用默认的交换机）

2、工作队列模式 Work Queue
一个生产者、多个消费者（竞争关系），不需要设置交换机（使用默认的交换机）

3、发布订阅模式 Publish/subscribe--对应广播-消息总线
需要设置类型为fanout的交换机，并且交换机和队列进行绑定，当发送消息到交换机后，交换机会将消息发送到绑定的队列

4、路由模式 Routing
需要设置类型为direct的交换机，交换机和队列进行绑定，并且指定routing key，当发送消息到交换机后，交换机会根据routing key将消息发送到对应的队列

5、通配符模式 Topic
需要设置类型为topic的交换机，交换机和队列进行绑定，并且指定通配符方式的routing key，当发送消息到交换机后，交换机会根据routing key将消息发送到对应的队列
复制代码
```

优点：

- 消费方可以选择消费方式为pull或者是broker主动push
- 支持的消费模式也有多种，点对点，广播，正则匹配，订阅发布
- 消息需要通过复杂的路由到消费者
- 性能20k/sec

缺点：

- 吞吐量不高，分布式弱

### Kafka

![image](https://p3-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/de26665eea7948b88f0d6316ac0989ed~tplv-k3u1fbpfcp-zoom-1.image) ![image](https://p3-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/71d72da5834c48cd842cc46d3dd3ec7c~tplv-k3u1fbpfcp-zoom-1.image) ![image](https://p3-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/c30f338fe0094db69d643346ca533dac~tplv-k3u1fbpfcp-zoom-1.image)

```
Kafka是一种高吞吐量的分布式发布订阅消息系统，使用Scala编写。默认端口9092
依赖zk，每个topic里面都有一个leader，topic，leader信息存zk。
每个分区是有顺序性，可以将一类，比如某个人的订单hash到同一分区（就可以保证顺序性，可以制定某个key来hash）
Topic一种逻辑分类的概念到不同的分区（类似queue），消息不会删除，默认8天自动删除
一个分区对应一个消费者，单播
可以用消费组来实现多播，1个分区对应多个消费组
备份因子：必须小于等于节点数
kafka选举原理：就是利用zk临时节点，断开即删除，
然后flower监听watcher的副节点有变化就重新创建一个临时节点，谁建成功谁就是leader
复制代码
```

优点：

- 从A系统到B系统的消息没有复杂的传递规则，并且具有较高的吞吐量要求。性能100k/sec
- 需要访问消息的历史记录的场景，因为kafak是持久化消息的，所以可以通过偏移量访问到那些已经被消费的消息
- 流处理的场景。处理源源不断的流式消息
- 高性能原因：集群。消息是顺序存磁盘（比随机内存性能高）。消息消费不需要ack删除消息。全异步

缺点：

- 客户端发送一条消息的时候，Kafka并不会立即发送出去，先攒一波再一起处理，Kafka 不太适合在线业务场景

自己设计一个Mq需要考虑哪些东西？

- 优先级队列，延迟队列，死性队列，重试队列
- 消息回踪，消息丢失
- 跨语言，安全机制，多协议支持
- 消费模式
- 消费关系处理
- 可以参考Pulsar，存储和计算分离的设计

## MQs

### Kafka

[Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md) is an open-source distributed event streaming platform used by thousands of companies for high-performance data pipelines, streaming analytics, data integration, and mission-critical applications.

### RocketMQ

[RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)

## Links
- [Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
- [Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md)



