## Introduction

RabbitMQ 是一个可靠且成熟的消息和流媒体代理，易于部署在云环境、本地环境和本地机器上，目前已被全球数百万人使用。

```shell
docker pull rabbitmq

docker run -d -p 15673:15672 -p 5674:5672 --restart=always -e RABBITMQ_DEFAULT_VHOST=my_vhost -e RABBITMQ_DEFAULT_USER=admin -e RABBITMQ_DEFAULT_PASS=admin123456 --hostname myRabbit --name rabbitmq-new rabbitmq:latest
```

仅队列模型

- **生产者**是发送消息的用户应用程序。
- **队列**是存储消息的缓冲区。
- **消费者**是接收消息的用户应用程序。

### Exchange

RabbitMQ 消息模型的核心思想是生产者从不直接将消息发送到队列。
实际上，通常情况下生产者甚至不知道消息是否会被投递到任何队列。

**相反，生产者只能将消息发送到 exchange（交换机）**。交换机是一个非常简单的组件。
它一方面接收来自生产者的消息，另一方面将消息推送到队列。
交换机必须确切知道如何处理接收到的消息。

exchange 的目的是将所有流经它们的消息路由到一个或多个 [queues](https://www.rabbitmq.com/docs/queues)、[streams](https://www.rabbitmq.com/docs/streams) 或其他 exchange

## Links

- [MQ](/docs/CS/MQ/MQ.md?id=RocketMQ)
