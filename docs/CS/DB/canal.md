## Introduction


真实场景中，canal 高可用依赖 zookeeper ，笔者将客户端模式可以简单划分为：TCP 模式 和 MQ 模式 。

实战中我们经常会使用 MQ 模式 。因为 MQ 模式的优势在于解耦 ，canal server 将数据变更信息发送到消息队列 kafka 或者 RocketMQ ，消费者消费消息，顺序执行相关逻辑即可。


## Links

- [MySQL binlog](/docs/CS/DB/MySQL/binlog.md)