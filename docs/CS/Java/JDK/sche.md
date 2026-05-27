## Introduction

本文主要在基于 Java 语言下实现定时任务的方式

## 任务模型

- Cron
- Fixed Delay
- Fixed Rate
- One Time 一次性任务
  适用日历提醒, 订单超时自动关闭 因为Job占用资源较多 当任务量过大时 可使用MQ做定时消息, 或者秒级Map任务扫库处理


## 任务分配

- 单机
- 广播
- MapReduce 模型


## 单机定时任务

[Timer](/docs/CS/Java/JDK/Basic/Timer.md) 是JDK内置的定时器, 单线程搭配小顶堆的设计，已经不推荐使用

从Timer的实现总结分析 对任务的优先级排序需要有一个优先级队列 JDK内置的DelayQueue可以实现
在此基础上封装的 [ScheduledThreadPoolExecutor](/docs/CS/Java/JDK/Concurrency/sche.md) 能实现更精细地管理
Spring Task 底层是基于 JDK 的 ScheduledThreadPoolExecutor 线程池来实现的


| 维度             | `Timer`                                                      | `ScheduledThreadPoolExecutor`                                |
| ---------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| **线程模型**     | 单后台线程（所有任务串行执行）                               | 可配置线程池（支持并发执行）                                 |
| **异常处理**     | 脆弱：单个任务抛出未捕获异常会导致整个 Timer 线程终止，后续任务全部取消 | 健壮：捕获异常并记录，隔离故障任务，其他任务继续执行         |
| **API 设计**     | 继承 `TimerTask`，`schedule()` 返回 `void`                   | 直接接受 `Runnable`/`Callable`，返回 `ScheduledFuture<V>`（支持取消、查询状态） |
| **调度精度**     | 固定延迟/固定频率易受单线程阻塞影响，产生累积漂移            | 基于 `DelayedWorkQueue` + 纳秒时钟，固定频率模式支持自动“追赶”执行 |
| **生命周期管理** | `cancel()` 仅标记取消，线程可能常驻内存；不支持优雅关闭      | 完整实现 `ExecutorService` 生命周期，支持 `shutdown()`、`awaitTermination()`、线程池监控 |





在中间件的场景中，同样也存在很多定时任务的需求。比如，网络连接的心跳检测， 网络请求超时或失败的重试机制，网络连接断开之后的重连机制
和业务场景不同的是，这些中间件场景的定时任务特点是逻辑简单，执行时间非常短，而且对时间精度的要求比较低。
比如，心跳检测以及失败重试这些定时任务，其实晚执行个几十毫秒或者 100 毫秒也无所谓
中间件场景定时任务特点

1. 海量任务
2. 逻辑简单
3. 执行时间短
4. 任务调度的及时性要求不高

Kafka、Dubbo、ZooKeeper、Netty、Caffeine、Akka 中都有对时间轮的实现


Netty的 [HashedWheelTimer](/docs/CS/Framework/Netty/HashedWheelTimer.md) 是一个单层时间轮设计 
通过一个 workerThread 每隔 tickDuration（100ms）将时钟 tick 向前推进一格



Kafka的 [Hierarchical Timing Wheels](/docs/CS/MQ/Kafka/Timer.md) 的多层时间轮设计，巧妙地解决了时间轮的空推进现象和海量延时任务时间跨度大的管理问题



## 分布式定时任务

如果我们需要一些高级特性比如支持任务在分布式场景下的分片和高可用的话，我们就需要用到分布式任务调度框架了。

通常情况下，一个分布式定时任务的执行往往涉及到下面这些角色：

- 任务：首先肯定是要执行的任务，这个任务就是具体的业务逻辑比如定时发送文章。
- 调度器：其次是调度中心，调度中心主要负责任务管理，会分配任务给执行器。
- 执行器：最后就是执行器，执行器接收调度器分派的任务并执行



[Quartz](/docs/CS/Framework/Job/Quartz/Quartz.md) 可以说是 Java 定时任务领域的老大哥或者说参考标准，其他的任务调度框架基本都是基于 Quartz 开发的，
比如当当网的 [Elastic-job](/docs/CS/Framework/Job/ElasticJob.md) 就是基于 Quartz 二次开发之后的分布式调度解决方案
Quartz 虽然也支持分布式任务
但是，它是在数据库层面，通过数据库的锁机制做的，有非常多的弊端比如系统侵入性严重、节点负载不均衡。有点伪分布式的味道

[XXL-JOB](/docs/CS/Framework/Job/xxl-job.md) 于 2015 年开源，是一款优秀的轻量级分布式任务调度框架，支持任务可视化管理、弹性扩容缩容、任务失败重试和告警、任务分片等功能

[PowerJob](/docs/CS/Framework/Job/PowerJob.md)（原OhMyScheduler）是全新一代分布式任务调度与计算框架，参考了阿里的 SchedulerX

| **项目**     | **Quartz**                     | **Elastic-Job**                    | **XXL-JOB**                                | **SchedulerX**                                               | PowerJob |
| ------------ | ------------------------------ | ---------------------------------- | ------------------------------------------ | ------------------------------------------------------------ | --- |
| 定时调度     | Cron                           | Cron                               | Cron                                       | Cron、Fixed_Delay、Fixed_Rate、One_Time、OpenAPI             |Cron|
| 任务编排     | 不支持                         | 不支持                             | 不支持                                     | 支持，可以通过图形化配置，并且任务间可传递数据               |支持|
| 分布式跑批   | 不支持                         | 静态分片                           | 广播                                       | 广播、静态分片、MapReduce                                    |广播、静态分片、MapReduce|
| 多语言       | Java                           | Java、脚本任务                     | Java、Go、脚本任务                         | Java、Go、脚本任务、HTTP任务、K8s Job                        ||
| 可观测       | 无                             | 弱，只能查看无法动态创建、修改任务 | 历史记录、运行日志（不支持搜索）、监控大盘 | 历史记录、运行日志（支持搜索）、监控大盘、操作记录、查看堆栈、链路追踪 ||
| 可运维       | 无                             | 启用、禁用任务                     | 启用、禁用任务、手动运行任务、停止任务     | 启用、禁用任务、手动运行任务、停止任务、标记成功、重刷历史数据 ||
| 报警监控     | 无                             | 邮件                               | 邮件                                       | 邮件、钉钉、飞书、企业微信、自定义WebHook、短信、电话        ||
| 高可用及容灾 | 需要自己维护数据库的容灾       | 需要自己维护ZooKeeper的容灾        | 需要自己维护数据库和Server的容灾           | 默认支持同城多机房容灾                                       ||
| 用户权限     | 无                             | 无                                 | 用户隔离，通过账号密码登录                 | 支持单点登录、主子账号、角色账号、RAM精细化权限管理          ||
| 优雅下线     | 不支持                         | 不支持                             | 支持                                       | 支持                                                         ||
| 灰度测试     | 不支持                         | 不支持                             | 不支持                                     | 支持                                                         ||
| 性能         | 每次调度通过DB抢锁，对DB压力大 | ZooKeeper是性能瓶颈                | 由Master节点调度，Master节点压力大         | 可水平扩展，支持海量任务调度                                 ||



## Tuning


任务堆积

同MQ中消息堆积, 需考虑限流措施


任务超时


任务重试


重复消费


任务分配








## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)


## References

1. [闲鱼技术 浅谈任务分发中的机制与并发](https://mp.weixin.qq.com/s/nGMxR7QDnoolTU5SYIDy2A)
