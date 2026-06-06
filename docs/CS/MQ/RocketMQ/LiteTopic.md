## Introduction

RocketMQ  5.5.0 版本推出了 RIP-83 消息模型，面向AI Agent、异步任务和海量轻量会话场景



每个Agent会话使用独立的Group订阅独立topic会导致topic巨量膨胀，Broker轮询全量topic检查新消息的无效扫描会导致CPU开销线性增长，传统topic需要提前定义，无法很好适配按需动态分配；group模型天生不适合会话级独占订阅



LiteTopic 采用 父Topic命名空间+子topic会话通道

底层RocksDB 替代 ConsumeQueue文件 提升承载能力



## Links

- [RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
