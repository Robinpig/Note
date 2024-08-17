## Introduction

Diamond是阿里集团内广泛使用的配置中心，提供持久化管理和动态配置推送服务。应用方发布的配置会通过持久化存储保存，与发布者的生命周期无关。 动态配置推送，则是Diamond的核心功能，在阿里内部有很多应用场景，如数据库动态切换和扩容，业务系统开关配置运行时变更等。

> *Switch应用于简单值的配置，diamond通常用于复杂结构的配置。Switch中的全部配置项，是Diamond中的一项。*
>
> Switch是对diamond的封装结果

Diamond服务于淘宝内部几乎所有应用，因此，“可靠、易用、高效”便成为了Diamond的产品目标。 为了实现这个目标，我们定下了“make it simple”的原则，并在设计、实现以及运维各个阶段中尽力遵循着它。 本文会较详细的介绍Diamond的设计思路和实现原理，以此说明“可靠、易用、高效”的产品目标是如何实现的。

Diamond已完全以开源Nacos内核完成重构
使用场景

配置项动态变更推送
通过控制台、客户端 API，发布、变更配置值，借助 Diamond 提供配置变更推送功能，可以实现不重启应用而获取最新的配置值。
- 支持业务系统或中间件系统中与业务意义相关的配置动态变更
- 支持交易链路核心应用的双十一限流开关动态设置
- 支持 HSF 流控,调用超时时间等规则动态调整
- 预案、降级开关
- 支持 Notify 订阅关系的动态变更和感知
- 支持 TDDL、RTools 等数据源动态切换、数据库连接属性动态调整
- Tair 集群地址信息
- HBase 服务
- ZK 服务
- TbSession 会员服务
- Switch、限流、降级预案，紧急预案
- 单元化异地多活切流
- 服务域名存储
- MESH 流量拦截规则

业务规则
- 文案，公告
- 黑白名单
- 日志级别、采样率
- 消息订阅关系
- 权限数据
- 线程池、连接池大小等动态阈值调整
- 集群热点 key 统计
- 动态代码
- ARMS 任务采集点，用户开通状态
- AServer 安全，灰度规则
- Spring 配置


适用规则
- 小配置
  配置中心的主要作用是发布 meta-data，而不是数据的存储服务。所发布的单个配置数据内容大小宜在 100KB 以内，当前 diamond 对超过 1M 的配置禁止变更，后面会进一步减小该阈值，直到所有配置不超过 100KB。
- 低频变更
  Diamond 是个后台配置管理系统，不是流量链路产品，配置变更需小于 1 次/分钟，应急场景除外。如果同一个配置项的变更频率持续在分钟级，一般认为属于异常的场景。
  配置发布频率过高是最常见的 Diamond 误用场景，Diamond 对此有严格的限流
  单配置超过 1 MB 禁止更新
  单配置分钟级变更流量大小超过 1MB 禁止更新
  单个配置变更不超过 1 次 / 5s，分钟级不超过 20 次
- 低频查询
  如上条所述，Diamond 不是流量链路产品，和 Redis 等缓存也有着本质上的区别，所以请不要在流量链路内查询配置，正常情况下应用启动时需查询一次配置进行业务初始化，后续只需监听配置变化即可。
- 最终一致性
  Diamond 只保证最后一次推送的值一定会到达，但不保证中间的每一次变更都会送达订阅端。 配置项的值保存到 Diamond 数据库中是覆盖式写的，假如一个配置项很快连续变更多次，等客户端陆续来 Diamond 读取值的时候，很可能只拿到最新值，而感知不到中间的快速变更。配置中心本身也会对时间间隔很短的推送任务做优化，只推最新的版本。
  因为最终一致性的特性，在配置发布同步至服务端本地过程中，在某一个特定的时刻，肯定会出现 Diamond 服务端集群本地的配置没有达到完全一致，因此请在回调监听器内直接使用回调中的内容，而不是在回调中再查询一次配置
- 幂等性
  配置中心可能在某些时候会向订阅者发送重复的数据通知，订阅者对数据通知的处理应满足幂等性，支持重复推送，相同配置回调多次不应产生异常预期外的情况。
- 轻回调
  在接受到配置变更的消息时，不要在回调中执行消耗较大的逻辑，比如读取文件，执行远程 RPC 等其他逻辑复杂的程序，容易把回调线程阻塞住，影响其他配置的推送回调。对于重回调的场景，请自定义业务线程进行配置回调处理

错误使用案例
- 热点 key 更新
  应用系统作为一个缓存系统使用 Diamond 来存储热点 key，系统的每台机器都在内存统计访问流量的 key，将热点 key 更新到 Diamond 中，当洪峰流量打到系统时，热点 key 会不断更新，从而不断更新 Diamond 配置，对 Diamond 形成洪峰流量，同一个配置频繁变更，造成数据库锁等待排队，连接池耗尽。
- 基于事件更新
  应用系统某台机器发生某种事件的时候，需要将这个事件通知到其他的机器，从而会更新 Diamond 配置，当事件发生频率很高的时候，多台机器会同时不断更新配置，导致写 Diamond 频率过高，配置频繁变更，造成数据库锁等待排队，连接池耗尽
- 配置大批量定时更新
  应用系统使用 Diamond 来做配置的持久化存储，对应的管控系统也有缓存很多数据，管控系统会定期将本地的数据批量的更新到 Diamond 中，以让应用系统配置能定时生效。当配置的数量很大的时候，管控系统会定时大批量更新 Diamond 配置，打满数据库 CPU
- 大配置
  Diamond 配置管理系统存储的应该是应用所需的元数据，这个数据量应该是比较小的。应用存储很多非元数据到 Diamond 中，导致配置非常大（超过 100KB），大配置的变更和推送都会对 Diamond 服务造成很大的压力，造成数据库 IO hang



## Architecture




<div style="text-align: center;">

![Fig.1. Diamond架构](./img/Diamond.png)

</div>

<p style="text-align: center;">
Fig.1. Diamond架构
</p>


Diamond在整个流程中包含一下几个核心部分：

- diamond-server：diamond最核心的服务端应用，向外提供功能接口
- diamond-client : 用户用于访问diamond服务的客户端，包括查询配置，监听配置，发布配置等
- 数据库：diamond服务端背后有一个中心化的数据库，用于存储所有用户的配置内容，保证强一致性的关键组件
- 地址服务器：保存每个diamond集群的服务端列表，向diamond客户端提供查询服务，向diamond服务端提供注册地址和注销地址的服务，是diamond客户端访问diamond服务端的一个broker。
- Diamond控制台：diamond配置的管理控制台，提供基础的查询配置，创建，发布配置等运维层面的接口。

简述一下diamond的整体流程：

1. diamond-server部署集群，向地址服务器注册自身IP，扩容缩容会持续更新列表
1. 用户应用服务启动，触发diamond-client初始化，向地址服务器获取diamond-server地址。diamond对业务进行了region级容灾，同城容灾，单元化等
1. 获取列表成功后，diamond-client向服务器发起请求，查询配置并监听，只有监听配置后才会收到变更通知，即实现“ManagerListener”接口，重写“receiveConfigInfo”方法
1. 用户通过diamond-ops变更配置，diamond-server会现将配置更新到数据库，然后把最新的配置刷新到服务器本地缓存，并通知所有diamond-server同步数据
1. diamond-server本地缓存变更时，会通知对该配置进行监听的diamond-client
1. diamond-client收到变更通知，向diamond-server发起配置查询请求，服务端将本地缓存的内容返回给diamond-client，diamond-client查询到最新配置后，回调业务的监听器，即通过“receiveConfigInfo”方法将数据传递给用户应用
1. diamond通过心跳检测机制来保证http-server列表是可用的


diamond最重要的功能是配置变更后，不需要用户应用客重启就能快速感知到，其核心是动态配置推送服务，接下来我们分析下diamond是如何实现动态推送的。
实时的动态配置推送，本质上是考虑如何将服务器上的配置变更动作实时发送给客户端。如果有一种机制可以使服务器源源不断的“推送”信息给客户端，那这个问题就解决了。TCP长连接是最自然的一种解决方案，但是由于设计上diamond选择了http协议提供服务，如何在Http协议的Request-Response通信模型下解决这个问题，是Diamond面临的难题。


当前淘宝生产环境中的Diamond服务，采用了这种基于推模型的客户端长轮询的方案来实现动态配置实时推送。 基于Http长轮询模型，实现了让客户端在没有发生动态配置变更的时候减少轮询。这样减少了无意义的轮询请求量，提高了轮询的效率；也降低了系统负载，提升了整个系统的资源利用率。
另外，这种推拉结合的策略，做到了在长连接和短连接之间的平衡，实现上让服务端不用太关注连接的管理，效果上又获得了类似TCP长连接的信息推送的实时性


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



配置没有推送 / 没有监听

明确上下文
首先，第一点需要明确 ，你所遇到的问题具体是什么，是配置真的没有推送，还是只是看到你的客户端业务不符合预期。客户端的表现不符合预期，并不一定是底层配置没有推送，也有可能是推送了，但是没有在回调中正确地处理业务逻辑。
二. 明确环境
请确认你发起变更的配置对应的环境是否和你的客户端在同一个环境下。如何确认？请在你的客户端机器上执行 curl jmenv.tbsite.net:8080/env，获得你的客户端所在的环境，示例：

这个接口会返回你的客户端所在的环境标识，然后拿到这个标识，去 diamond 控制台 查看对应的环境的配置是否真实发生了变更。
如果可以在配置的变更历史中查看变更历史，下一步明确你的客户端是否正常监听了该配置


可以在 diamond 控制台查看你的配置被哪些 IP 监听，也可以通过 IP 查看所监听的配置。
1. 确认配置被哪些客户端 IP 监听
2. 确认你的客户端 IP 地址是否监听了配置
   IP 监听了该配置
   看到对应 IP 的推送状态是 ok，那么说明客户端本地缓存的值和服务器的值是一致的，diamond 已经正常回调给了客户端，这种情况下请排查监听器里的回调逻辑，是不是回调方法里的 bug。
   另外还有一种比较常见的情况是，客户端有其他的入口把业务内存值给修改了，导致业务不符合预期。
   控制台监听查询中看到状态持续为 error ,请确定你是否有 beta 发布或者 Tag 发布的工单正在进行中。客户端查到的配置的优先级是：beta > tag > 分批 > 持久化

IP 没有监听任何配置
如果 IP 没有监听任何一个配置，那么有三种可能
在控制台中选择了错误的环境，IP 并不属于这个环境
你的这个 IP 确实因为代码 bug 没有监听配置
你的客户端因为推送线程被阻塞，导致和服务端断连，可以通过 /opt/taobao/java/bin/jstack {pid} | grep -20 'longPullingdefault' 查看当前推送线程是否阻塞。如果线程当前一直堵塞在你的业务回调逻辑中，请尝试解锁或者直接重启解决。


IP 有监听配置
如果你的 IP 有监听配置，但是监听列表里没有你期望的配置，那么有两种可能
你的客户端确实没有监听该配置 —— 99% 都是这种情况
为啥？找下自己代码的原因，是不是没有走到 addListener 的逻辑


你的客户端监听了超过 3000 个配置，其中一条推送线程阻塞，导致监听列表不全，可以通过 /opt/taobao/java/bin/jstack {pid} | grep -20 'receiveConfigInfo' 查看当前回调线程是否被回调方法 receiveConfigInfo 阻塞，如果线程当前一直堵塞在业务回调逻辑中，请尝试解锁或者直接重启解决



客户端本地日志
如果无法通过控制台定位你的问题，那么需要通过你的客户端日志进行进一步排查。
diamond 客户端对配置的监听，推送，回调都有明确的日志
/home/admin/logs/diamond-client/diamond-client.log (3.x 版本)，
/home/admin/logs/diamond-client/config.log (4.x 版本)
日志文件中查看推送日志。示例如下：
grep 'com.taobao.diamond.config' /home/admin/logs/diamond-client/diamond-client.log --col

NoClassDefFoundError
- 查看下是否有不同版本 jar 包冲突，保留最新版本
- Diamond 类初始化的时候，会尝试连接到当前环境的地址服务器获取 diamond 服务列表，如果失败了会导致类无法初始化，也是导致该报错，查看 fail to get diamond-server serverlist


## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)



## References

1. [阿里配置中心Diamond探索](https://developer.aliyun.com/article/912197)