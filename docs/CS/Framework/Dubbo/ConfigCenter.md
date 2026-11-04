## Introduction

在 Dubbo 3.3.6 中，`DynamicConfiguration`（`dubbo-common` 模块，`org.apache.dubbo.common.config.configcenter`）是**配置中心客户端**的统一抽象。Dubbo 在启动阶段通过它拉取全局/应用级配置（如 `dubbo.properties`、治理规则），并在运行时通过 `ConfigurationListener` 监听配置变更，以**动态下发治理规则**（路由规则、动态配置覆盖、Mesh 规则等），无需重启应用。

为什么需要它：注册中心（Registry）只负责服务发现（provider/consumer 地址），而配置中心负责"配置与规则"的集中管理与动态推送，两者职责分离。`DynamicConfiguration` 屏蔽了 Nacos / Zookeeper / Apollo 三种后端在订阅模型（SDK 长轮询 push vs ZK 服务端 watch push vs Apollo 应用侧 HTTP long-poll）上的差异，向上层（集群治理、路由链）提供一致的 `getConfig` / `addListener` 接口。

## DynamicConfiguration Interface

- 定义：`dubbo-common/src/main/java/org/apache/dubbo/common/config/configcenter/DynamicConfiguration.java:36`

  ```java
  public interface DynamicConfiguration extends Configuration, AutoCloseable {
  ```

- 默认 group 为 `"dubbo"`（`:38` `DEFAULT_GROUP`）。
- 核心方法：
  - `void addListener(String key, String group, ConfigurationListener listener)`（`:70`，抽象）—— 注册配置/治理监听
  - 便捷默认方法 `addListener(String key, ConfigurationListener)`（`:46`）/ `removeListener`（成对默认方法）→ 使用 `getDefaultGroup()` 兜底 group
  - `String getConfig(String key, String group, long timeout)`（`:115`，抽象）—— 拉取指定配置，带超时
  - `String getConfig(String key, String group)`（默认方法）→ 带 `getDefaultTimeout()`
  - `String getProperties(String key, String group)`（默认实现直接转调 `getConfig`）—— 常用拉取整份 `dubbo.properties`
  - `boolean publishConfig(...)`、`publishConfigCas(...)`、`removeConfig(...)`—— 写回能力（治理规则回写、CAS 覆盖）
- 回调接口：`ConfigurationListener`（`dubbo-common/.../configcenter/ConfigurationListener.java:24` `extends EventListener`）→ `void process(ConfigChangedEvent event)`（`:32`）。
- 事件：`ConfigChangedEvent`（注意是 `Changed` 不是 `Change`）携带 `key` / `group` / `content` / `changeType`（`ConfigChangedEvent.java:27`，字段 `changeType` 在 `:35`）。

> [!WARNING]
> 常见误以为接口里有 `getConfigsFromCache` 方法做本地缓存取数——**接口中不存在该方法**，全仓 grep 无定义。取数统一走 `getConfig(...)`，缓存只存在于各**实现**内部（见下文 Nacos 的 `cacheData`、ZK 的 `NodeCache`）。

## Nacos Implementation

- 文件：`dubbo-configcenter/dubbo-configcenter-nacos/src/main/java/org/apache/dubbo/configcenter/support/nacos/NacosDynamicConfiguration.java`
- 字段：`NacosConfigServiceWrapper configService`（`:84`，包装 `com.alibaba.nacos.api.config.ConfigService`）、`ConcurrentMap<String, NacosConfigListener> watchListenerMap`（`:91`）。
- 订阅模型：**Nacos SDK 长轮询 + 服务端 push**。`addListener`（`:232`）→ `configService.addListener(key, group, nacosConfigListener)`（`:238`）；`NacosConfigListener extends AbstractSharedListener`（`:333`），`innerReceive`（`:354`）收到推送后构造 `ConfigChangedEvent` 并 `listener.process(event)`（`:363`）。**不是 Dubbo 自己轮询**——轮询与长连接保活都在 Nacos SDK 的 `ClientWorker` 内部。
- 取数：`getConfig`（`:254`）→ `configService.getConfig(key, group, nacosTimeout)`（`:260`）直连远程，**无本地缓存层**；内部 `cacheData`（`:339`）仅用于计算 changeType（ADD/MOD/DEL），不对外暴露为 `getConfigsFromCache`。
- 客户端复用：配置中心通过 `NacosFactory.createConfigService`（`:109`）**独立**创建 `ConfigService`，与注册中心的 `NamingService` 是**不同实例、不同 API**，仅 server 地址相同（注册中心走 `dubbo-registry-nacos` 的 `NamingService`）。

## Zookeeper Implementation

- 文件：`dubbo-configcenter/dubbo-configcenter-zookeeper/src/main/java/org/apache/dubbo/configcenter/support/zookeeper/ZookeeperDynamicConfiguration.java`
- 继承 `TreePathDynamicConfiguration`（`:42`），底层使用 `ZookeeperClient`（Curator5）。
- 订阅模型：**Curator `NodeCache` watch，ZK 服务端主动 push**。`doAddListener`（`:159`）→ `zkClient.addDataListener(pathKey, addedListener, executor)`（`:166`）；底层 `Curator5ZookeeperClient` 用 `new NodeCache(client, path)`（`:378`）+ `NodeCacheListenerImpl`（`:409`）。**非 long poll**，且是单层 `NodeCache`（非 `TreeCache`/`PathChildrenCache`）——只监听单节点数据变化。
- 路径层级：`/<namespace>/config/<group>/<key>`，默认 `/dubbo/config/<group>/<key>`（`TreePathDynamicConfiguration` 的 `DEFAULT_CONFIG_BASE_PATH = "/config"`，namespace 默认 `dubbo`）。
- 取数：`doGetConfig`（`:137`）→ `zkClient.getContent(pathKey)`（`:138`）→ 底层 `client.getData().forPath(path)`，直连 ZK 读，无本地缓存层。

## Apollo Implementation

- 文件：`dubbo-configcenter/dubbo-configcenter-apollo/src/main/java/org/apache/dubbo/configcenter/support/apollo/ApolloDynamicConfiguration.java`
- 订阅模型：**Apollo 客户端 HTTP 长轮询（long poll）拉取**。Dubbo 侧仅是薄封装：`addListener`（`:170`）→ `dubboConfig.addChangeListener(apolloListener, ...)`（`:174`）；`ApolloListener implements ConfigChangeListener`（`:250`），`onChange`（`:257`）→ `listener.process(event)`（`:272`）。真正的长轮询在 Apollo SDK（`RemoteConfigRepository`）内部，Dubbo 仓库内搜不到 `longPoll`/`ScheduledExecutorService` 是正常的。
- 取数：`getConfig`（`:189`）→ `dubboConfig.getProperty(...)`（`:197`）直连 Apollo 客户端。
- 三者差异一句话：Nacos 与 ZK 都是"服务端/配置侧 push"（Nacos 经 SDK 长轮询、ZK 经 watch），Apollo 是"应用侧 HTTP long-poll 拉取"；只有 ZK 是注册中心/配置中心共用的服务端原生 push 机制。

## Config Center vs Registry

当同一后端同时作为注册中心与配置中心时，Dubbo 通过**路径/命名空间**区分数据，但客户端是否共享取决于后端实现：

- **Nacos（独立实例）**：配置中心用 `ConfigService`、注册中心用 `NamingService`，各自 `NacosFactory` 创建（见上）。以 `namespace`+`group`+`dataId` 区分 config，以 `serviceName`+`group` 区分 registry——**两套独立客户端对象**。
- **Zookeeper（共享连接）**：配置中心与注册中心经 `ZookeeperClientManager.connect(url)`（`dubbo-remoting-zookeeper-curator5/.../ZookeeperClientManager.java:71`）**共享同一个 `ZookeeperClient`/`CuratorFramework` 实例**（按地址缓存复用，`:41` `Map<String, ZookeeperClient>`，`:89` `new Curator5ZookeeperClient`，`:91` 写入缓存）。数据靠路径隔离：注册中心写 `/dubbo/<service>/providers/...`，配置中心写 `/dubbo/config/<group>/<key>`。客户端 `close()` 时也不关闭共享连接（`ZookeeperDynamicConfiguration.java:108-112` 注释 `zkClient is shared in framework, should not close it here`）。

## Dynamic Configuration Consumers

`DynamicConfiguration.addListener` 的主要消费方均在 `dubbo-cluster`，用于治理规则与配置的热更新：

- `DefaultGovernanceRuleRepositoryImpl`（治理规则统一仓库）：`addListener`（`:32`）→ `dynamicConfiguration.addListener(...)`（`:35`）；`getConfig`（`:51`）。这是治理规则拉取/监听的统一入口。
- 各 `StateRouter` 实现 `ConfigurationListener`，在 `process(ConfigChangedEvent)` 中热更新规则并重建路由链：
  - `ListenableStateRouter`（条件路由）：`implements ConfigurationListener`，`process` 注册 `addListener(routerKey, this)`，本地无通知时也可手动 `process(new ConfigChangedEvent(...))` 强制刷新。
  - `TagStateRouter`（标签路由）：`addListener(key, this)`。
  - `MeshRuleManager`（Mesh 规则）：`addListener(appRuleDataId, DEFAULT_GROUP, meshAppRuleListener)`。
- 触发效果：`process` 回调重新 `getConfig` 拉取最新规则，驱动 `RouterChain` 重建 / `RegistryDirectory` 刷新，实现治理规则与配置的动态下发——这正是 3.x「配置与地址发现解耦」后的核心运行时链路。

## Pitfall List

1. **以为接口有 `getConfigsFromCache`**：`DynamicConfiguration` 接口中不存在该方法，全仓无定义；取数统一走 `getConfig(...)`，缓存只实现在各实现内部。
2. **混淆 `ConfigChangeEvent` 与 `ConfigChangedEvent`**：回调事件类名是 `ConfigChangedEvent`（带 d），`ConfigurationListener.process(ConfigChangedEvent)`。
3. **以为 Nacos 配置中心与注册中心共享同一客户端**：二者分别用 `ConfigService` 与 `NamingService`，是**独立实例**；而 **Zookeeper 反而通过 `ZookeeperClientManager` 共享同一个 Curator 连接**，仅路径隔离。
4. **以为 ZK 配置中心是 long poll**：ZK 用的是 Curator `NodeCache` watch（**服务端主动 push**），不是 long poll；long poll 模型只出现在 Nacos SDK 与 Apollo 客户端内部。

## Links

- [config](/docs/CS/Framework/Dubbo/config.md)
- [Governance](/docs/CS/Framework/Dubbo/Governance.md)
- [Router](/docs/CS/Framework/Dubbo/Router.md)
- [registry](/docs/CS/Framework/Dubbo/registry.md)
- [Mesh](/docs/CS/Framework/Dubbo/Mesh.md)

## References

- Dubbo 官方文档 - 动态配置中心: https://dubbo.apache.org/zh-cn/docs/3.3/user/configuration/center/
- Dubbo 配置中心源码 (dubbo-3.3.6 tag): https://github.com/apache/dubbo/tree/dubbo-3.3.6/dubbo-common/src/main/java/org/apache/dubbo/common/config/configcenter
- Nacos Config SDK: https://nacos.io/zh-cn/docs/sdk.html
- Apollo 客户端设计 (long poll): https://www.apolloconfig.com/#/zh/design/apollo-design
- Curator NodeCache / Watches: https://curator.apache.org/curator-recipes/NodeCache.html
