## Introduction

[Druid](https://github.com/alibaba/druid) 是一个 JDBC 组件库，包含数据库连接池、SQL Parser 等组件。
Druid连接池为监控而生，内置强大的监控功能，监控特性不影响性能。功能强大，能防SQL注入，内置Loging能诊断Hack应用行为。


Druid的监控统计功能是通过filter-chain扩展实现

Druid内置提供一个StatFilter，用于统计监控信息。



Druid锁的公平模式问题

如果配置了maxWait，在连接不够用争用时，unfair模式的ReentrantLock.tryLock方法存在严重不公的现象，个别线程会等到超时了还获取不到连接。

Since 0.2.8 缺省unfair，通过构造函数传入参数指定fair或者unfair；如果DruidDataSource还没有初始化，修改maxWait大于0，自动转换为fair模式

可以手工配置
```
  dataSouce.setUseUnfairLock(true)
```



## Links

- [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)