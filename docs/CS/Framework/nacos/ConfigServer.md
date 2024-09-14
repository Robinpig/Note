## Introduction




ConfigServer 中文名为非持久配置中心，主要用于非持久数据的发布和订阅，数据的生命周期和长连接的生命周期绑定，产品架构基于发布订阅模型，采用了去中心无 master 设计，保证了系统的可扩展性、高可用。 在集团内为分布式消息系统 Notify、RPC 框架 HSF 提供地址发现服务


无 Master 架构
ConfigServer 是去中心化架构，不存在单点失败问题，通过特定的算法进行数据增量同步
-- Raft？去中心 Gossip

自动聚合
ConfigServer 支持数据的自动聚合配置数据的聚合功能。每台机器向 ConfigServer 注册自己的服务元信息，ConfigServer 会根据服务名和分组自动聚合所有元数据，提供给服务订阅方使用。
实时
ConfigServer 是推模型 (Push-Mode)， ConfigServer 的服务端与客户端基于长连接通信，在客户端订阅关系确定后，配置信息一旦发生变化，会主动推送配置数据到客户端，并回调客户端的业务监听器


SOFARegistry 是蚂蚁集团开源的一个生产级、高时效、高可用的服务注册中心。SOFARegistry 最早源自于淘宝的 ConfigServer，十年来，随着蚂蚁金服的业务发展，注册中心架构已经演进至第六代。目前 SOFARegistry 不仅全面服务于蚂蚁集团的自有业务，还随着蚂蚁金融科技服务众多合作伙伴，同时也兼容开源生态。SOFARegistry 采用 AP 架构，支持秒级时效性推送，同时采用分层架构支持无限水平扩展。

SOFARegistry 是蚂蚁集团开源的一个生产级、高时效、高可用的服务注册中心。SOFARegistry 最早源自于淘宝的 ConfigServer，十年来，随着蚂蚁金服的业务发展，注册中心架构已经演进至第六代。目前 SOFARegistry 不仅全面服务于蚂蚁集团的自有业务，还随着蚂蚁金融科技服务众多合作伙伴，同时也兼容开源生态。SOFARegistry 采用 AP 架构，支持秒级时效性推送，同时采用分层架构支持无限水平扩展。
高可扩展性
采用分层架构、数据分片存储等方式，突破单机性能与容量瓶颈，接近理论上的“无限水平扩展”。经受过蚂蚁集团生产环境海量节点数与服务数的考验。
高时效性
借助 SOFABolt 通信框架，实现基于 TCP 长连接的节点判活与推模式的变更推送，服务上下线通知时效性在秒级以内。
高可用性
不同于 Zookeeper、Consul、Etcd 等 CP 架构注册中心产品，SOFARegistry 针对服务发现的业务特点，采用 AP 架构，最大限度地保证网络分区故障下注册中心的可用性。通过集群多副本等方式，应对自身节点故障


https://www.sofastack.tech/projects/sofa-registry/overview