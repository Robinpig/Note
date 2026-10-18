# Nacos Config Push Mechanism Deep Dive

## Introduction

配置中心的核心价值不只是「能存」，更是「**变了客户端能马上知道**」。Nacos 客户端感知配置变更的机制，随大版本从 HTTP 长轮询演进到 gRPC 长连接推送——这是注册发现之外 Nacos 的第二大实时能力。服务端把 DB 落盘的 dump 机制见 [Config](/docs/CS/Framework/nacos/config.md) 的 `### dump`；本文聚焦**变更如何触达客户端**。

## Design Philosophy: Lightweight Notification + Active Pull

Nacos 的推送刻意「小」：推送消息只携带变更标识（`dataId + group`），**不携带内容**。客户端收到通知后，重新发起一次配置查询拿最新内容。

> [!NOTE]
> 关键原则：**不要把变更推送当作配置内容本身**。收到通知必须重新查询，以防推送丢包或内容不完整。这与 etcd 的 watch 不同——etcd watch 直接返回变更后的 KV（见 [etcd Watch](/docs/CS/Framework/etcd/watch.md)）。

这套设计两个好处：推送消息极小、网络开销低；最终内容仍走正常查询路径，保证一致性。

## 2.x Long Polling (HTTP)

2.x 及以前，客户端用 HTTP 长轮询监听（`/nacos/v1/cs/configs/listener`）。服务端 `LongPollingService`（3.2.4 里的类名；很多文章写作 `ConfigLongPollingService`，**该名字在 3.x 全树 0 命中**）用 `AsyncContext` 把请求**挂起**：

- 客户端把订阅的 dataId 列表（每批最多 3000 个）连同本地 **MD5 摘要**发到服务端，请求超时设 **30 s**。
- 服务端收到后比对本地 MD5：已变更则立即返回变更项；未变更则挂起，**最多等 29.5 s**（提前 500 ms 响应，防止网络延迟导致客户端 `SocketTimeoutException`）。
- 挂起期间若发生配置发布，`LocalDataChangeEvent` 唤醒对应挂起任务，提前返回变更 dataId。
- 客户端拿到变更 dataId 后，立即发 `GET /v1/cs/configs` 拉取完整内容，然后发起下一轮 30 s 长轮询。

```java
// ConfigLongPollingService 内部以 ClientLongPolling 持有 AsyncContext
// 超时 29.5s 响应；LocalDataChangeEvent 触发提前返回
```

局限：

- 每个客户端一条独立 HTTP 连接，连接数随客户端规模线性增长，资源消耗高。
- 感知延迟受轮询空档影响，最长接近一个轮询周期（秒级）。
- 订阅项极多时，单次长轮询请求 body 很大。

> [!NOTE]
> 「30 s 超时 / 29.5 s 提前返回」是 **2.x 客户端的默认值**。3.2.4 服务端不再写死这个数：
> 超时取 `max(开关 MIN_LONG_POOLING_TIMEOUT 默认 10000 ms, 请求头 Long-Pulling-Timeout - delayTime)`，
> 由客户端通过 `Long-Pulling-Timeout` 头申报（见 `LongPollingService.addLongPollingClient`），
> 「提前 500 ms 返回避免客户端 SocketTimeout」的策略保留。
> 另外 3.x 用的是 `jakarta.servlet.AsyncContext`（Jakarta EE），不再是 `javax.*`。

## 3.x gRPC Long-Connection Push

2.x 起通信协议从 HTTP 短连接升级为 gRPC 双向流，配置监听改为长连接推送：

- 客户端启动后建一条 gRPC 长连接（`ConfigBatchListenRequest` 批量注册关心的 dataId 列表）。
- 服务端用 `ConfigChangeListenContext`（`config/server/remote/`）维护「哪些连接关注哪些配置」——**不是** `ClientWatchContext`（该名在 3.x 全树 0 命中）。
- 配置发布后，拥有客户端长连接的节点发 `ConfigChangeNotifyRequest` 把变更推下去。
- 客户端收到通知**不直接塞内容**，而是内部再发一次 `ConfigQueryRequest` 查最新内容，与本地缓存比对，确认确实变了才回调 `Listener`。

```java
// 客户端 addListener -> CacheData 维护 Listener 列表（ConcurrentHashMap）
// 收到 ConfigChangeNotifyRequest -> 内部 ConfigQueryRequest 重新查询 -> 比对 -> 回调
```

优势：一条 gRPC 长连接复用所有请求，毫秒级延迟，连接数远低于长轮询。

## dump Full Sync

服务端启动时把 MySQL 的 `config_info` 全量 dump 到本地磁盘（`DumpService` / `DiskUtil`，落在 `nacos/data/config-data/tenant/...` 的 `worker_${port}` 目录），供客户端直读、降低 DB 压力。细节与定时全量（`DUMP_ALL_INTERVAL_IN_MINUTE`）见 [Config](/docs/CS/Framework/nacos/config.md) 的 `### dump`。dump 是「服务端 → 磁盘」的持久化同步，与「服务端 → 客户端」的推送是两条独立链路。

## Canary Watch (beta / tag)

Nacos 支持灰度发布。dump 阶段由 `DumpAllGrayProcessor`（+ `DumpAllGrayTask`）把灰度配置单独落盘；监听侧客户端可订阅灰度配置，验证无误后全量发布。灰度配置与主配置共用同一推送通道，只是 dataId 维度不同。

> [!WARNING]
> 2.x 的 `DumpAllBetaProcessor` / `DumpAllTagProcessor` 在 3.2.4 **已删除**（0 命中），
> 与 `config_info_beta` / `config_info_tag` 表被移除一致；3.x 只剩 `DumpAllProcessor` 与 `DumpAllGrayProcessor`。
> 灰度模型统一叫 **gray**（`ConfigCacheGray` / `config_info_gray` / `dumpGray`），不再叫 beta。

## 3.x Breaking Changes

Nacos 3.x 的 Client OpenAPI **不再提供 HTTP 长轮询的配置监听能力**——配置监听必须走官方 SDK 的 gRPC 长连接。迁移到 3.x 时，若仍用旧版 SDK 的 HTTP 长轮询监听，会收不到变更通知（见 [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md) 的版本错配段）。

> [!NOTE]
> 这条结论在 3.2.4 源码里可验证：路由 `configs/listener` **全树 0 命中**，
> 而 `LongPollingService` 唯一的生产调用方 `ConfigServletInner` **没有任何其它类引用**（死代码）。
> 注意 v3 的 `/listener` 是**管理员查询「哪些客户端在监听」**的接口（`ConfigControllerV3.getListeners`），别当成长轮询端点。
>
> 生态侧：Spring Cloud Alibaba **2025.1.0.0**（适配 Spring Boot 4.0 / Spring Cloud 2025.1）内置 **Nacos Client 3.1.1**，
> 并**正式移除 `bootstrap.yml`**，改用 `spring.config.import`——配置监听自此完全走 gRPC。

## Comparison with etcd Watch

| 维度 | Nacos 配置推送 | etcd Watch |
| :-- | :-- | :-- |
| 通道 | 2.x 长轮询 / 3.x gRPC 推送 | gRPC 续接流（watch stream） |
| 推送内容 | 仅 dataId（需再拉取） | 完整 KV |
| 一致性语义 | AP 通知 + 查询保证最终一致 | 线性一致（watch 从某 revision 连续） |
| 版本维度 | dataId 有发布历史 / 回滚 | revision 单调 |

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Config（dump / 服务端）](/docs/CS/Framework/nacos/config.md)
- [Client（SDK 最佳实践）](/docs/CS/Framework/nacos/client.md)
- [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)
- [etcd Watch](/docs/CS/Framework/etcd/watch.md)
- [etcd 横向对照](/docs/CS/Framework/etcd/compare.md)

## References

- <https://blog.csdn.net/weixin_29229261/article/details/164665410>
- <https://thomas-sir.blog.csdn.net/article/details/165117885>
- <https://nacos.io/docs/latest/manual/user/config/publish-query-listen/>
