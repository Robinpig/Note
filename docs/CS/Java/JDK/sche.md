## Introduction


实现定时任务

[Timer](/docs/CS/Java/JDK/Basic/Timer.md) 是JDK内置的定时器, 单线程搭配小顶堆的设计 


从Timer的实现总结分析 对任务的优先级排序需要有一个优先级队列 JDK内置的DelayQueue可以实现 
在此基础上封装的 [SchedulerThreadPoolExecutor](/docs/CS/Java/JDK/Concurrency/ScheduledThreadPoolExecutor.md)



而在中间件的场景中，同样也存在很多定时任务的需求。比如，网络连接的心跳检测， 网络请求超时或失败的重试机制，网络连接断开之后的重连机制
和业务场景不同的是，这些中间件场景的定时任务特点是逻辑简单，执行时间非常短，而且对时间精度的要求比较低。
比如，心跳检测以及失败重试这些定时任务，其实晚执行个几十毫秒或者 100 毫秒也无所谓
中间件场景定时任务特点
1. 海量任务
2. 逻辑简单
3. 执行时间短
4. 任务调度的及时性要求不高

多数中间件针对此种类型的定时任务设计了时间轮调度机制 


Netty的 [HashedWheelTimer](/docs/CS/Framework/Netty/HashedWheelTimer.md) 是一个单层时间轮设计 
通过一个 workerThread 每隔 tickDuration（100ms）将时钟 tick 向前推进一格




Kafka的 [Hierarchical Timing Wheels](/docs/CS/MQ/Kafka/Timer.md) 的多层时间轮设计，巧妙地解决了时间轮的空推进现象和海量延时任务时间跨度大的管理问题




## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)
