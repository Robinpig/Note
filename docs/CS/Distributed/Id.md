## Introduction

Snowflake 是一个网络服务，用于在高并发规模下生成具备一些简单保证的唯一 ID 号码。

ID 由以下部分组成：
- 时间戳（time） - 41 位（毫秒精度，配合自定义纪元（epoch）可使用 69 年）
- 配置的机器 ID（configured machine id） - 10 位 - 最多支持 1024 台机器
- 序列号（sequence number） - 12 位 - 每台机器每 4096 溢出一次（有保护机制避免在同一毫秒内溢出）


http://mongodb.github.io/node-mongodb-native/2.0/tutorials/objectid/

http://www.infoq.com/cn/articles/wechat-serial-number-generator-architecture

https://github.com/nebula-im/seqsvr

https://github.com/baidu/uid-generator/blob/master/README.zh_cn.md

https://tech.meituan.com/MT_Leaf.html



时钟回拨（Clock Skew）

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed.md)
- [Time](/docs/CS/Distributed/Time.md) — 时钟回拨（Clock Skew）是 Snowflake 的核心约束
- [Dynamo](/docs/CS/Distributed/Dynamo.md) — 同样依赖时间戳/版本做因果排序

## References

1. [Snowflake](https://github.com/twitter-archive/snowflake)
