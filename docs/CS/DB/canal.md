## Introduction


真实场景中，canal 高可用依赖 zookeeper ，笔者将客户端模式可以简单划分为：TCP 模式 和 MQ 模式 。

实战中我们经常会使用 MQ 模式 。因为 MQ 模式的优势在于解耦 ，canal server 将数据变更信息发送到消息队列 kafka 或者 RocketMQ ，消费者消费消息，顺序执行相关逻辑即可。


## Tuning

监听中文表会乱码出现问题


有缓存 与数据库实际表column不一致 column size is not match for table xxxx 8 vs 9, 删除meta.dat并重启解决

## Links

- [MySQL binlog](/docs/CS/DB/MySQL/binlog.md)