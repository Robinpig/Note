## Introduction

分库分表方案中，首先我们要有两个算法。
- 一个分库字段和分库算法，即在进行数据查询、数据写入时，根据分库字段的值算出要
路由到哪个数据库实例上；
- 一个分表字段和分表算法，即在进行数据查询、数据写入时，根据分表字段的值算出要
路由到哪个表上。

SQL 解析




MyCat 服务端代理模式 对业务代码无侵入 有性能损耗 中心化 容易成为瓶颈 数据库适配性

ShardingJDBC 客户端代理模式 性能损耗小 通过jar扩展 适配性强 没有统一视图 运维成本高

[ShardingSphere](/docs/CS/DB/ShardingSphere.md) 类似MyCat 搭配




## Links

- [DataBases](/docs/CS/DB/DB.md)