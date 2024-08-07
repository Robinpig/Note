## Introduction

Diamond是阿里集团内广泛使用的配置中心，提供持久化管理和动态配置推送服务。应用方发布的配置会通过持久化存储保存，与发布者的生命周期无关。 动态配置推送，则是Diamond的核心功能，在阿里内部有很多应用场景，如数据库动态切换和扩容，业务系统开关配置运行时变更等。

> *Switch应用于简单值的配置，diamond通常用于复杂结构的配置。Switch中的全部配置项，是Diamond中的一项。*
>
> Switch是对diamond的封装结果

Diamond服务于淘宝内部几乎所有应用，因此，“可靠、易用、高效”便成为了Diamond的产品目标。 为了实现这个目标，我们定下了“make it simple”的原则，并在设计、实现以及运维各个阶段中尽力遵循着它。 本文会较详细的介绍Diamond的设计思路和实现原理，以此说明“可靠、易用、高效”的产品目标是如何实现的。

Diamond已完全以开源Nacos内核完成重构



## Architecture





Diamond在整个流程中包含一下几个核心部分：

- - diamond-server：diamond最核心的服务端应用，向外提供功能接口
  - diamond-client : 用户用于访问diamond服务的客户端，包括查询配置，监听配置，发布配置等
  - 数据库：diamond服务端背后有一个中心化的数据库，用于存储所有用户的配置内容，保证强一致性的关键组件
  - 地址服务器：保存每个diamond集群的服务端列表，向diamond客户端提供查询服务，向diamond服务端提供注册地址和注销地址的服务，是diamond客户端访问diamond服务端的一个broker。
  - Diamond控制台：diamond配置的管理控制台，提供基础的查询配置，创建，发布配置等运维层面的接口。

为了便于理解，在原理图中，按照数字顺序标注了一个完整的流程

1. 1. diamond-server部署集群，向地址服务器注册自身IP地址，扩容缩容都会持续更新列表
   2. 用户应用服务器启动，触发diamond-client客户端初始化，向地址服务器获取服务列表，因为集团的线上业务规模过于庞大，对业务进行了Region级容灾，同城容灾，单元化等，diamond有接近60+集群，地址服务器在集群间隔离扮演非常重要的角色
   3. 获取列表成功后向diamond服务端发起请求，查询配置并且监听配置，只有监听配置后才会收到变更通知
   4. 用户登录diamond控制台，对配置进行变更，diamond先将配置更新到数据库，然后把最新配置拉取到服务器本地缓存
   5. 服务器本地缓存变更时，会通知对该配置进行监听的客户端
   6. 客户端收到变更通知时，向Diamond服务端发起配置查询请求，服务端将本地缓存的内容返回给客户端。客户端查询到最新配置后，回调业务的监听器



## Implements

开发人员可以通过控制台、客户端API，发布、变更配置值，借助Diamond提供配置变更推送功能，可以实现不重启应用而获取最新的配置值。目前Diamond在集团使用十分广泛，下面列一些集团典型应用场景：

- 支持业务系统或中间件系统中与业务意义相关的配置动态变更
- 支持交易链路核心应用的双十一限流开关动态设置。
- 支持HSF流控等规则动态调整。
- 预案、降级开关
- 支持Notify订阅关系的动态变更和感知。
- 支持数据源动态切换、数据库连接属性动态调整
- 淘内ZooKeeper应用方都会被推荐监听ZooKeeper服务连接串的配置变化，由此可以实现动态感知ZooKeeper集群扩容、下线。 Tair集群地址信息。
- json布局、静态资源url都可以动态定制UI





## Issues



配置没有监听/推送



## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)



## References

1. [阿里配置中心Diamond探索](https://developer.aliyun.com/article/912197)