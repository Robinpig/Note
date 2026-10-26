> [!NOTE]
> 本子树基于 Netflix/eureka **v1.10.19**（tag `v1.10.19`，2026-08-24）逐文件核对源码；涉及 Spring Cloud 的事实基于 **spring-cloud-netflix 5.0.3**（2026-10-22 GA，依赖 `com.netflix.eureka:eureka-client:2.0.6`）。分册见[目录索引](/docs/CS/Framework/eureka/README.md)。

## Introduction

Eureka 是 Netflix 开源的服务注册与发现组件，设计为一组**地位完全对等的 Server + 一个内嵌到业务进程里的 Client**。Server 侧没有 Leader、没有选举、没有日志复制，节点之间只是把收到的写请求原样转发给所有 peer；Client 侧把整份注册表缓存到本地内存，之后每 30 秒增量拉取一次，并每 30 秒向 Server 续约一次。这套组合决定了它的三个基本特征：**可用性优先、服务端无强一致、客户端承担发现逻辑**。

Eureka 与 Nacos / ZooKeeper / Consul / etcd 的根本分野不在 API 而在取舍：后者用 quorum 保证线性一致或强一致读（CP），前者接受几分钟级别的数据陈旧，换的是「部分节点不可用时不阻塞任何写、网络分区时不摘除实例」。理解这一点之后，注册表写路径、二级缓存、自我保护这三处设计才显得自洽——它们都是同一个取舍在不同位置的体现。

## Design Trade-off

Eureka 的选择可以概括为三条：

1. **AP / 最终一致**：任何一台 Server 都能接受写（注册、续约、下线），写完后异步转发给 peer。转发失败不影响本次写成功，只由 peer 后续重试补齐。
2. **服务端无 Leader**：没有选主、没有复制状态机。集群成员变更通过 DNS 或配置动态发现（`PeerEurekaNodes` 每 10 分钟刷新一次），新增节点靠启动时向邻居 `syncUp()` 全量拉取。
3. **发现逻辑在客户端**：Server 只提供注册表快照与增量；过滤（`UP` 实例）、shuffle、zone 偏好选择、故障重试与黏连都由客户端的 `DiscoveryClient` + 上层负载均衡（早期 Ribbon、现在 Spring Cloud LoadBalancer）完成。

代价也很清晰，见**[自我保护](/docs/CS/Framework/eureka/self_preservation.md)**：当 Server 在短时间内丢失大量心跳（网络抖动、分区、大规模重启），它无法区分「实例真的挂了」和「网络不可达」，于是选择**保留**注册表而不是摘除。这意味着客户端可能拿到已经不存在的实例——Eureka 官方明确要求客户端必须能容忍这一点：快速超时并换下一台。

## Roles and Data Model

| 概念          | 载体                                                                                   | 说明                                                              |
| :---------- | :----------------------------------------------------------------------------------- | :-------------------------------------------------------------- |
| 服务实例        | `com.netflix.appinfo.InstanceInfo`                                                    | 一条注册记录：`appName`、`id`（实例 ID）、`vipAddress`、`hostName`、`ipAddr`、`port`、`status`、`leaseInfo`、`metadata`、`lastDirtyTimestamp` |
| 服务（应用）      | `com.netflix.appinfo.Application`                                                     | 同一 `appName` 下的 `InstanceInfo` 集合，Server 端交给 `Application` 管理 |
| 租约          | `com.netflix.eureka.lease.Lease<InstanceInfo>`                                         | `lastUpdateTimestamp` / `duration`（默认 90s）/ `serviceUpTimestamp`；`renew()` 把 `lastUpdateTimestamp` 置为 `now + duration` |
| 状态          | `InstanceStatus`：`UP / DOWN / STARTING / OUT_OF_SERVICE / UNKNOWN`                      | 客户端 `ApplicationInfoManager` 通过健康检查或 API 变更，Server 侧可用 status override 覆盖 |
| 增量条目        | `RecentlyChangedItem`                                                                 | 写路径产生 `ADDED / MODIFIED / DELETED` 三种 Action，进 `recentlyChangedQueue`，保留 3 分钟 |

服务端注册表是一个两层 Map：`ConcurrentHashMap<appName, Map<instanceId, Lease<InstanceInfo>>>`，详见 [registry](/docs/CS/Framework/eureka/registry.md)。

## Core Flow

注册、续约、拉增量、下线四条主链路：

```sequence
participant App as 业务进程
participant DC as DiscoveryClient
participant R as InstanceResource
participant Reg as PeerAwareInstanceRegistry
participant Cache as ResponseCache
participant Peer as 对端 Server

App->>DC: @PostConstruct / InstanceRegisteredEvent
DC->>R: POST /eureka/v2/apps/{appId} (InstanceInfo)
R->>Reg: register(info, isReplication=false)
Reg->>Reg: Lease 写入 registry + recentlyChangedQueue
Reg->>Cache: invalidate(appName, vip, svip)
Reg->>Peer: batchreplication/Register
loop 每 30s
  DC->>R: PUT /apps/{appId}/{instanceId} (status, lastDirtyTimestamp)
  R->>Reg: renew(appName, id, isReplication)
  Reg->>Reg: lease.renew() + renewsLastMin.increment()
  Reg->>Peer: batchreplication/Heartbeat
end
loop 每 30s
  DC->>R: GET /apps/delta
  R->>Cache: readOnlyCacheMap -> readWriteCacheMap -> 实时算
  Cache-->>DC: Applications(delta)
  DC->>DC: updateDelta() + appsHashCode 校验，不一致则全量重拉
end
App->>DC: shutdown()
DC->>R: DELETE /apps/{appId}/{instanceId}
R->>Reg: cancel() -> internalCancel()
```

四条链路的源码分别在 [Client](/docs/CS/Framework/eureka/Client.md)（发起侧）、[REST API](/docs/CS/Framework/eureka/rest_api.md)（契约侧）、[registry](/docs/CS/Framework/eureka/registry.md)（写路径）与 [replication](/docs/CS/Framework/eureka/replication.md)（向 peer 扩散）。

### Default Time Constants

这些数字决定了 Eureka 的「体感」，也是调优的第一抓手（详见 [Tuning](/docs/CS/Framework/eureka/tuning.md)）：

| 参数                                       | 默认值   | 出处与含义                                                    |
| :--------------------------------------- | :----- | :-------------------------------------------------------- |
| `leaseInfo.renewalIntervalInSecs`          | 30 s   | 客户端续约间隔（`InstanceInfo` default lease info）              |
| `Lease.DEFAULT_DURATION_IN_SECS`           | 90 s   | 租约时长；`renew()` 时把过期时间设为 `now + duration`               |
| `evictionIntervalTimerInMs`                | 60 s   | Server 剔除任务周期（`postInit()` 里 schedule）                 |
| `registryFetchIntervalSeconds`             | 30 s   | 客户端拉取注册表间隔（[Client](/docs/CS/Framework/eureka/Client.md) 的 `CacheRefreshThread`） |
| `responseCacheUpdateIntervalMs`            | 30 s   | readOnly 缓存回填周期                                          |
| `responseCacheAutoExpirationInSeconds`     | 180 s  | readWrite 缓存 TTL（Guava `expireAfterWrite`）                |
| `retentionTimeInMSInDeltaQueue`            | 3 min  | 增量条目保留时长（[registry](/docs/CS/Framework/eureka/registry.md?id=delta-队列)） |
| `renewalPercentThreshold`                  | 0.85   | 自我保护阈值系数                                               |
| `renewalThresholdUpdateIntervalMs`         | 15 min | `expectedNumberOfClientsSendingRenews` 的重新评估周期           |
| `peerEurekaNodesUpdateIntervalMs`          | 10 min | peer 节点列表刷新周期                                          |
| `waitTimeInMsWhenSyncEmpty`                | 5 min  | 集群未就绪时 Server 等待窗口                                     |

由这些默认值可以推出一个常被问到的数字：**一个实例宕机后，其它实例最长需要约 210 秒才有感知**——服务端 90s 租约 + 90s 补偿余量 + 客户端 30s 拉取间隔。完整推导见 [cache](/docs/CS/Framework/eureka/cache.md?id=感知时延的完整推导)。

## 版本线与两个 2.0

> [!WARNING]
> 网上大量旧资料写的「Eureka 2.0：从 pull 改成 push、读写分离、增加审计日志」是 **2015 年的设计蓝图，从未交付**。Netflix 已把当年的开源实验放进 `2.x-archive` 分支并明确不再维护；今天 Maven Central 上的 `2.0.x` 是**另一回事**——它是把 Eureka 1 移植到 jakarta 命名空间 + Jersey 3 的版本，`2.0.0` 发布于 2022-12-14，最新 `2.0.6`（2026-03-27），协议与数据模型没有变化。写文档或做版本选型时务必区分两者。

- **1.x**：`com.netflix.eureka:eureka-client` 最新 `1.10.19`（2026-08-24），`javax.*` 命名空间，默认走 Jersey 1.19.1。仍在持续发版。
- **2.0.x**：jakarta 迁移版。Spring Cloud Netflix 从引入 Spring Boot 3 起使用它——`spring-cloud-netflix-dependencies/pom.xml` 的 `<eureka.version>2.0.6</eureka.version>`，并管理 `eureka-core-jersey3` / `eureka-client-jersey3`。详见 [Spring Cloud](/docs/CS/Framework/eureka/spring_cloud.md)。
- **2.x-archive**：2015–2018 年的重写分支（曾设想订阅式推送 + 读写集群分离），已废弃，不要作为事实来源。

## Horizontal Comparison

| 维度           | Eureka 1.10                  | Nacos 2.x/3.x                       | ZooKeeper                     | Consul                    | etcd                     |
| :----------- | :--------------------------- | :---------------------------------- | :--------------------------- | :------------------------ | :----------------------- |
| 一致性          | AP，peer 互转发的最终一致            | 命名 AP（Distro）/ 配置 CP（JRaft），混合     | CP（Zab + quorum）             | CP（Raft），但会话有 AP 兜底      | CP（Raft + MVCC）         |
| 健康检测          | 客户端主动续约（心跳），超时 90s 剔除       | 临时实例心跳 + 持久实例服务端主动探测               | 临时节点 + session timeout       | agent 本地健康检查（多种）          | lease TTL               |
| 发现方式          | 客户端定时拉全量/增量并本地缓存            | 2.x 起 gRPC 长连接推送 + UDP/http 兜底      | watch（一次性事件通知）                | blocking query / DNS / watch | watch（gRPC stream）     |
| 感知时延          | 分钟级（默认最坏约 210s）             | 秒级（推送）                              | 亚秒~秒级                        | 秒级                        | 亚秒级                     |
| 集群角色          | 完全对等，无 Leader               | 数据节点并存 Distro 责任分片 + JRaft Leader   | Leader/Follower/Observer      | Server Leader + Agent     | Leader/Follower         |
| 分区行为          | 自我保护：保留可能已死的实例              | AP 侧继续提供服务，分区后自愈                    | 少数派不可写                       | 少数派 stale read           | 少数派不可写                  |
| 生态现状          | Netflix/Spring 侧维护明显放缓，新项目少 | 活跃，中文生态好，兼具配置中心                     | 生态稳定，常作协调而非注册中心              | 活跃，多数据中心能力强               | K8s 底座事实标准              |

更细的服务端实现对照见 [nacos registry](/docs/CS/Framework/nacos/registry.md?id=tuning)、[etcd 横向对照](/docs/CS/Framework/etcd/compare.md)。

## Migration

Eureka 已进入事实上的**维护期**：GitHub 仓库仍在（1.x 会随依赖升级发补丁版），Spring Cloud 侧保留了 starter 但不再作为推荐起点。常见迁移去向：

- **同栈最小改动**：[Consul](/docs/CS/Framework/consul/Consul.md)（Spring Cloud 原生、CP、带健康检查）或 [Nacos](/docs/CS/Framework/nacos/Nacos.md)（附带配置中心，中文生态友好，`NacosSync` 等工具支持双向同步）。
- **K8s 原生**：直接用 Service + DNS，配合 [Spring Cloud Kubernetes](/docs/CS/Container/k8s/Service.md) 或网关侧的服务源（如 Higress 的 `McpBridge`，见[Higress 服务发现](/docs/CS/Framework/Higress/Service_Discovery.md)）。
- **迁移要点**：把「客户端自我保护 + 本地缓存」的假设换成对服务端一致性的依赖；下游需要重新评估超时重试与灰度开关；双注册期通常需要一个双向同步组件或双 Client。

迁移到 Spring Cloud 新版时的具体配置与兼容矩阵见 [Spring Cloud](/docs/CS/Framework/eureka/spring_cloud.md)。

## Links

- [目录索引](/docs/CS/Framework/eureka/README.md)
- [Server](/docs/CS/Framework/eureka/Server.md)
- [Client](/docs/CS/Framework/eureka/Client.md)
- [Registry](/docs/CS/Framework/eureka/registry.md)
- [Cache](/docs/CS/Framework/eureka/cache.md)
- [Self Preservation](/docs/CS/Framework/eureka/self_preservation.md)

## References

1. [Netflix/eureka](https://github.com/Netflix/eureka)
2. [Netflix/eureka Wiki](https://github.com/Netflix/eureka/wiki)
3. [Spring Cloud Netflix](https://github.com/spring-cloud/spring-cloud-netflix)
4. [com.netflix.eureka:eureka-client 版本列表](https://repo1.maven.org/maven2/com/netflix/eureka/eureka-client/)
