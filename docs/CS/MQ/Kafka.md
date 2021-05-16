# Kafka

[Apache Kafka](https://kafka.apache.org/) is an open-source distributed **event streaming** platform used by thousands of companies for high-performance data pipelines, streaming analytics, data integration, and mission-critical applications.



## event streaming

> Event streaming is the digital equivalent of the human body's central nervous system. It is the technological foundation for the 'always-on' world where businesses are increasingly software-defined and automated, and where the user of software is more software.
>
> Technically speaking, event streaming is the practice of capturing data in real-time from event sources like databases, sensors, mobile devices, cloud services, and software applications in the form of streams of events; storing these event streams durably for later retrieval; manipulating, processing, and reacting to the event streams in real-time as well as retrospectively; and routing the event streams to different destination technologies as needed. Event streaming thus ensures a continuous flow and interpretation of data so that the right information is at the right place, at the right time.



## 基本组成

- **Broker**

  ​				一台服务器即为一个Broker，Broker集群中没有主从区别，一个Broker有多个Topic。

- **Topic**

  ​				Topic 队列实现 可逻辑上分布在多个Broker中，但不需关心数据实际存放位置 但只能保证在一个Broker上topic顺序

- **Partition**

  ​				Topic可被分布成多个Partition到多台Broker中，每条消息分配一个自增Id（Offset），保证一个Partition中顺序，但不保证单个Topic中多个Partition之间顺序。

- **Offset**

  自增Id

- **Replica**

  Partition含有N个Replia，一个为Leader，其余为Follower，Leader处理读写请求，Follower定期同步Leader数据。

- **Message**

- **Producer**

- **Consumer**

- **Consumer Group**

- **Zookeeper**

- 存放Kafka集群相关元数据的组件，保存组件的信息。

## 拓扑结构



## 内部通信协议

## Broker

### KafkaServer



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

paritition内部有序

消息重试:消息存储 异步重试

消息积压: 减小传输数据大小 IO压力 路由分配规则



高并发下重复主键是否需加锁

消息重复:幂等性



环境隔离

消息恢复

## quorum replace zookeeper

why
1. 强依赖 维护困难
2. Zookeeper CP 影响性能
