## Introduction

In computer science, message queues and mailboxes are software-engineering components typically used for inter-process communication (IPC), or for inter-thread communication within the same process.
They use a queue for messaging – the passing of control or of content. Group communication systems provide similar kinds of functionality.

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

### Pub/Sub

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

## Issues

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

## MQs

### Kafka

[Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md) is an open-source distributed event streaming platform used by thousands of companies for high-performance data pipelines, streaming analytics, data integration, and mission-critical applications.

### RocketMQ

[RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)

## Links

- [Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
- [Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md)
