# ConfigServer (Alibaba Internal Origin)

## Introduction

ConfigServer 是阿里内部自 2008 年起自研的**非持久服务注册中心（AP）**，以发布订阅 + 服务端主动推送为核心，是 Nacos 注册中心（AP / Distro）这条技术线的直接来源。

> 版本基线：本篇是历史演进篇，事实以阿里官方技术博客与 Nacos 官方文档为准；对照的产品能力锚定 Nacos 3.2.4（commit 2c587c0）。ConfigServer 本身未开源，无源码可摘。

反直觉点：

- ConfigServer **从 V1.0 起就选了 push 而非 pull**——比 Eureka 1.x 的客户端轮询早得多，这个取舍后来原样进了 Nacos 的服务发现推送。
- 它并非「简单地去中心化」：V2.0 每台节点存全量数据、靠客户端模式同步；V3.0 才拆成 **session / data 两层**做读写分离，思路与 Eureka 2.0 设想高度相似。
- 所谓「非持久」指数据生命周期与长连接绑定；**客户端磁盘缓存是 V1.5 就加的**（2009 年），用来解耦服务端发布与应用发布，不是后来才补的特性。

## The Domain Model (V1.0, 2008)

单机版第一次定义了沿用至今的服务发现领域模型：**服务发布、服务订阅、健康检查、数据变更主动推送**。应用以内嵌 SDK 接入，当时 HSF 与 Notify 分别用它做服务发现与 topic 发现，把请求从 F5 硬件负载牵引到端到端直连，从而解决负载不均、流量瓶颈、单点故障三个问题。

关键决策是 push 而非 pull：服务端在订阅关系确定后，配置 / 地址一旦变化就主动推给客户端并回调业务监听器。这一点与 Eureka 1.x 的周期性拉取形成鲜明对比，也解释了为什么 Nacos 的服务发现与配置推送都坚持「订阅而非轮询」（见 [Client SDK](/docs/CS/Framework/nacos/client.md)）。

## Ten Years of Evolution

| 版本 | 时间 | 关键变化 |
| :-- | :-- | :-- |
| V1.0 | 2008 | 单机版，确立发布 / 订阅 / 健康检查 / 主动推送模型 |
| V1.5 | 2009 初 | 加**本地磁盘缓存**，解耦 ConfigServer 发布与应用发布 |
| V2.0 | 2009.07 | 集群化，每节点存全量数据，服务端用客户端模式转发请求做同步 |
| V2.5 | 2010 底 | 改为批量长连接同步 + 周期性 renew（申请国家专利），合并同步 / 推送任务、压缩数据 |
| V3.0 | 2012 底 | 拆成 **session（分片、可水平扩容）与 data（全量、聚合）** 两层，读写分离 |
| V3.5 | 2014 | 引入服务元数据打标，支撑异地多活、同机房调用、灰度流量调拨 |
| V4.0 | 2017 | data 层也做分片，每分片按集群部署并带 failover |

V2.5 的瓶颈很典型：双十一后服务数剧增，应用发布时网卡打满、CMS GC 频繁；单纯扩容会让每台节点写能力下降，即「按下葫芦浮起瓢」。V3.0 的 session/data 分层正是对此的结构性回应——data 稳定少扩容，session 按推送需求弹性扩容且不给 data 增压。

> [!WARNING]
> 旧笔记里「通过特定算法做增量同步 —— Raft？去中心 Gossip」是**猜测而非事实**。官方博客明确记载的集群同步机制是：V2.0 客户端模式转发、V2.5 批量长连接同步 + 周期性 renew。ConfigServer 是 AP 系统，没有 Raft；「无 Master」应理解为没有强一致选主中心，而非采用 Gossip 协议。不要把这些猜测写进结论。

## Automatic Aggregation and Real-time Push

两台机器向 ConfigServer 注册各自的服务元信息后，ConfigServer 按服务名与分组**自动聚合**，再推给订阅方。配合长连接上的推模型与客户端磁盘缓存，形成了「服务端聚合 + 主动推 + 客户端本地兜底」的组合——这套思路在 Nacos 里对应 Distro（AP）的全量可读 + 推送 + 本地缓存（见 [Registry](/docs/CS/Framework/nacos/registry.md) 与 [Distro](/docs/CS/Framework/nacos/distro.md)）。

## From ConfigServer to Nacos

Nacos 来源于阿里内部三个产品：**ConfigServer（非持久注册中心）**、**VIPServer（持久注册中心）**、**Diamond（配置中心）**。ConfigServer 贡献的是 AP 服务发现这条线：

- 非持久 / 临时实例 → Nacos `ephemeral=true`，走 Distro（AP），内存态、心跳保活、重启会抖。
- 持久实例那条线来自 VIPServer → Nacos `ephemeral=false`，走 JRaft（CP）落库。
- 配置那条线来自 Diamond → Nacos config 模块（CP），见 [Diamond](/docs/CS/Framework/nacos/Diamond.md)。

官方博客原话是「计划通过 Nacos 把生产实践经验贡献给社区」，并称 Nacos「扛着 AP 系注册中心的旗帜继续前行」，强调其更关注 DNS-based Service Discovery 与 Kubernetes 体系的融合。

## SOFARegistry: Another Descendant

SOFARegistry 是蚂蚁集团开源的生产级服务注册中心，同样源自淘宝 ConfigServer，经多年演进至第六代。它采用 **AP 架构 + 分层架构 + 数据分片**，强调高时效性（基于 TCP 长连接的推模式，秒级上下线感知）与高可扩展性（分片存储逼近水平扩展）。它与 Nacos 是同源不同分支的两次开源表达。

## Links

- [Diamond](/docs/CS/Framework/nacos/Diamond.md)
- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Distro（AP 协议深潜）](/docs/CS/Framework/nacos/distro.md)
- [Registry](/docs/CS/Framework/nacos/registry.md)
- [config](/docs/CS/Framework/nacos/config.md)

## References

- <https://nacos.io/zh-cn/blog/alibaba-configserver.html>
- <https://www.sofastack.tech/projects/sofa-registry/overview>
