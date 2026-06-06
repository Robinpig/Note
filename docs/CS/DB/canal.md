## Introduction

Canal 通过伪装成数据库的从库，读取主库发来的 binlog，用来实现数据库增量订阅和消费服务

用途

- 数据库镜像
- 数据库实时备份
- 索引构建和实时维护（拆分异构索引、倒排索引等）
- 业务cache刷新
- 带业务逻辑的增量数据处理



## Architecture

canal 模拟 MySQL slave 的交互协议，向 MySQL master 发送 dump 协议，MySQL master  收到 dump 请求，开始推送 binlog 给 slave， canal 解析 binlog




真实场景中，canal 高可用依赖 zookeeper ，笔者将客户端模式可以简单划分为：TCP 模式 和 MQ 模式 。

实战中我们经常会使用 MQ 模式 。因为 MQ 模式的优势在于解耦 ，canal server 将数据变更信息发送到消息队列 kafka 或者 RocketMQ ，消费者消费消息，顺序执行相关逻辑即可。


## Tuning

监听中文表会乱码出现问题


有缓存 与数据库实际表column不一致 column size is not match for table xxxx 8 vs 9, 删除meta.dat并重启解决

## Links

- [MySQL binlog](/docs/CS/DB/MySQL/binlog.md)