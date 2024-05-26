## Introduction





Snowflake is a network service for generating unique ID numbers at high scale with some simple guarantees.

id is composed of:
- time - 41 bits (millisecond precision w/ a custom epoch gives us 69 years)
- configured machine id - 10 bits - gives us up to 1024 machines
- sequence number - 12 bits - rolls over every 4096 per machine (with protection to avoid rollover in the same ms)


http://mongodb.github.io/node-mongodb-native/2.0/tutorials/objectid/

http://www.infoq.com/cn/articles/wechat-serial-number-generator-architecture

https://github.com/nebula-im/seqsvr

https://github.com/baidu/uid-generator/blob/master/README.zh_cn.md

https://tech.meituan.com/MT_Leaf.html



Clock Skew


## References

1. [Snowflake](https://github.com/twitter-archive/snowflake)