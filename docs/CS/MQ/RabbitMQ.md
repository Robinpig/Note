## Introduction

RabbitMQ 是一个可靠且成熟的消息与流式代理（broker），易于在云环境、本地数据中心以及个人机器上部署，目前全球有数百万用户。

```shell
docker pull rabbitmq

docker run -d -p 15673:15672 -p 5674:5672 --restart=always -e RABBITMQ_DEFAULT_VHOST=my_vhost -e RABBITMQ_DEFAULT_USER=admin -e RABBITMQ_DEFAULT_PASS=admin123456 --hostname myRabbit --name rabbitmq-new rabbitmq:latest
```

RabbitMQ 只支持队列模型（Queue model）：

- **生产者（producer）** 是发送消息的用户应用。
- **队列（queue）** 是存储消息的缓冲区。
- **消费者（consumer）** 是接收消息的用户应用。

### Exchange

RabbitMQ 消息模型的核心思想是：**生产者从不直接把消息发送到队列**。实际上，很多时候生产者甚至不知道消息最终会不会被投递到任何队列。

**生产者只能把消息发送到交换机（exchange）**。交换机非常简单：一边接收来自生产者的消息，另一边把它们推送到队列。交换机必须确切地知道该拿收到的消息怎么办。

交换机的作用是把流经它的所有消息路由到一个或多个[队列](https://www.rabbitmq.com/docs/queues)、[流](https://www.rabbitmq.com/docs/streams)或其他交换机。

## Links

- [MQ 总纲](/docs/CS/MQ/MQ.md)
- [消息系统（发布/订阅与消息代理）](/docs/CS/MQ/MQ.md?id=message-system)
- [消息代理与数据库的对比](/docs/CS/MQ/MQ.md?id=message-brokers)
