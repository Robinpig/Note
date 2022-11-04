## Introduction

Apache RocketMQ is a distributed middleware service that adopts an asynchronous communication model and a publish/subscribe message transmission model.
The asynchronous communication model of Apache RocketMQ features simple system topology and weak upstream-downstream coupling.
Apache RocketMQ is used in asynchronous decoupling and load shifting scenarios.

### Domain Model

<div style="text-align: center;">

![Fig.1. Domain model](./img/Domain-Model.png)

</div>

<p style="text-align: center;">
Fig.1. Domain model of Apache RocketMQ.
</p>

As shown in the preceding figure, the lifecycle of a Apache RocketMQ message consists of three stages: production, storage, and consumption.
A producer generates a message and sends it to a Apache RocketMQ [broker](/docs/CS/MQ/RocketMQ/Broker.md). The message is stored in a topic on the broker. 
A consumer subscribes to the topic to consume the message.

Message production

[Producer](/docs/CS/MQ/RocketMQ/Producer.md)：
The running entity that is used to generate messages in Apache RocketMQ. Producers are the upstream parts of business call links. Producers are lightweight, anonymous, and do not have identities.

Message storage

- Topic：
  The grouping container that is used for message transmission and storage in Apache RocketMQ. A topic consists of multiple message queues, which are used to store messages and scale out the topic.
- MessageQueue：
  The unit container that is used for message transmission and storage in Apache RocketMQ. Message queues are similar to partitions in Kafka. Apache RocketMQ stores messages in a streaming manner based on an infinite queue structure. Messages are stored in order in a queue.
- Message：
  The minimum unit of data transmission in Apache RocketMQ. Messages are immutable after they are initialized and stored.

Message consumption

- ConsumerGroup：
  An independent group of consumption identities defined in the publish/subscribe model of Apache RocketMQ. A consumer group is used to centrally manage consumers that run at the bottom layer. 
- Consumers in the same group must maintain the same consumption logic and configurations with each other, and consume the messages subscribed by the group together to scale out the consumption capacity of the group.
- [Consumer](/docs/CS/MQ/RocketMQ/Consumer.md)：
  The running entity that is used to consume messages in Apache RocketMQ. Consumers are the downstream parts of business call links, A consumer must belong to a specific consumer group.
- Subscription：
  The collection of configurations in the publish/subscribe model of Apache RocketMQ. The configurations include message filtering, retry, and consumer progress Subscriptions are managed at the consumer group level. You use consumer groups to specify subscriptions to manage how consumers in the group filter messages, retry consumption, and restore a consumer offset.
  The configurations in a Apache RocketMQ subscription are all persistent, except for filter expressions. Subscriptions are unchanged regardless of whether the broker restarts or the connection is closed.



Topic -> multi message queue(like partition)

[Name server](/docs/CS/MQ/RocketMQ/Namesrv.md)

## Links

- [MQ](/docs/CS/MQ/MQ.md?id=RocketMQ)

## References

1. [RocketMQ技术内幕](https://book.douban.com/subject/35626441/)
