> [!NOTE]
> 本页讨论的都是**默认值基础上的取舍**。改任何一项之前先明确目标到底是「感知更快」还是「开销更小」——这两者在 Eureka 里几乎永远相反。参数兵力见 [config](/docs/CS/Framework/eureka/config.md)。

## Introduction

Eureka 的调优空间其实很窄，因为它没有复杂的一致性协议和存储层。真正需要决策的只有四件事：

1. 能接受多久的实例感知时延（默认最坏约 5 分钟）；
2. 是否保留自我保护（可用性 vs 陈旧数据）；
3. 集群规模与写放大（每次写都要 fanout 给所有 peer）；
4. 版本栈是否要迁移到 jakarta（Spring Boot 3+ 强制）。

## Latency vs Cost

下线/上线的感知时延由四段构成，每段都有对应的压缩手段和代价：

| 环节                           | 默认     | 压缩手段                                                              | 代价                                       |
| :--------------------------- | :----- | :---------------------------------------------------------------- | :--------------------------------------- |
| 租约过期（`2 × duration`）         | 180 s  | 调小 `lease-expiration-duration-in-seconds`                          | 网络抖动时更容易误剔除；不建议低于 15s                     |
| EvictionTask 周期              | 60 s   | 调小 `eviction-interval-timer-in-ms`（如 30s / 5s）                     | 每轮要遍历整张 registry，CPU 开销随实例数线性上升           |
| readOnly 缓存回填                | 30 s   | `use-read-only-response-cache=false`（读直接落到 readWrite）              | 每次读可能触发 `generatePayload` 序列化；但正因为有 180s TTL，实际可接受 |
| 客户端拉取周期                      | 30 s   | 调小 `registry-fetch-interval-seconds`（如 15s / 5s）                    | 客户端数与 ×频率 直接放大 Server 读 QPS 与网络           |

一个跨 minor版的经验：**先把 `use-read-only-response-cache` 关掉**，这是收益/代价比最高的一步——省 30s 且几乎无副作用（除了消除了 readOnly 层，序列化压力由 180s 的 readWrite TTL 兜住）。至于 `lease-renewal-interval-in-seconds`，务必保持 30s：它被硬编码进[自我保护阈值](/docs/CS/Framework/eureka/self_preservation.md)公式的分母，改它会让阈值与实际续约节奏脱节。

## Self Preservation

| 场景                    | 建议                                                                        |
| :-------------------- | :------------------------------------------------------------------------ |
| 本地开发 / CI            | 关闭（`enable-self-preservation: false`），实例少时几乎必然误触发                         |
| 生产                    | **保留开启**。它是 Eureka 唯一的网络分区保护；关掉后大规模心跳中断会把整张表清空                           |
| 实例总数很少（< 5）           | 阈值太低容易反复进出保护态。要么接受，要么把 `renewalPercentThreshold` 下调到 0.5 左右并明确接受「少剔」的后果    |
| 长期停在保护态              | 检查 `Renews (last min)` 与 `Renews threshold` 的差距是真心跳不足（实例真的少了）还是网络问题；必要时重启 Server 让其重新 `syncUp()` |

自动化/systemd 环境下最常见的是「灰度发布期间实例数下降」触发保护——这是预期行为，不要为了消除红字去关保护。

## Cluster Sizing

写放大是 Eureka 集群的核心成本：一个注册请求在 N 个节点的集群里会产生 `N-1` 次转发（每个节点把收到的**非复制**请求转发给其余 peer）。缓解它靠两件事：

- **批处理队列**：同一个 target 的任务先按 taskId 去重，再攒够 250 条或等待 500ms 打包发送。高频注册场景（如批量扩容）下这条链路能显著降低请求数，但也会带来最多 500ms 的复制延迟。
- **队列容量**：`max-elements-in-peer-replication-pool`（默认 10000）是单 peer 队列上限。长时间网络分区会让积压迅速打满，超出后新任务被丢弃，只能靠后续心跳重新同步——**监控不足时这是最容易被忽略的一致性问题**。

集群规模建议：

- 3 个节点足够覆盖绝大多数场景（可用性 + 有限的写放大），Netflix 自身用的是一个 region 内多个 AZ + 多节点；
- 不要试图通过扩 Server 节点来提升写性能——每加一个节点，写请求反而更多；写压力大时应拆集群（按业务线 / 按 AZ）；
- 每个节点必须在 `defaultZone` 里**列出所有 peer（包括自己）**，否则会出现 peer 列表不完整、拒绝写等问题，详见 [troubleshooting](/docs/CS/Framework/eureka/troubleshooting.md)。

同一 region 多 AZ 部署时，客户端的 zone 亲和（`prefer-same-zone-eureka`）会把请求优先打到本 AZ 的 Server，跨 AZ 只是备份，这与 [Zone 偏好](/docs/CS/Framework/Higress/Service_Registry_Internals.md)的思路一致。

## Memory and GC

Server 的内存增长主要由三部分组成：

1. **注册表对象**：`registry` 里每个实例一个 `Lease<InstanceInfo>`，开销与实例元数据大小成正比（metadata 塞太多会显著放大）；
2. **响应缓存副本**：[cache](/docs/CS/Framework/eureka/cache.md) 按「EntityType × KeyType × Version × EurekaAccept × region 组合」分 key，每个组合一份**已序列化且 gzip/非 gzip 各一份**的字节。key 数量随「服务数 × 视图数」线性增长，监控里表现为堆在缓慢增长且 GC 后不回落，这不是泄漏而是设计如此；
3. **写入缓冲**：`recentlyChangedQueue`（3 分钟窗口）+ 批量复制队列（10000 上限）。

因此：

- **不要在 metadata 里放大对象**（别把整份配置、证书内容塞进去）；
- 实例数超过数千后，给 Server 单独配置堆（`-Xms`/`-Xmx` 相等避免运行时扩缩），并开启 GC 日志；
- `EvictionTask` 与 `CacheFillTimer` 都是单线程 Timer——**长时间的 GC 停顿会直接表现为感知时延抖动**，这就是 `getCompensationTimeMs()` 存在的原因。

## Client Threads

每个 `DiscoveryClient` 实例自己 `new` 三个执行器：`scheduler`（2 线程，用于两个周期性调度）、`heartbeatExecutor`、`cacheRefreshExecutor`（core 1、max = `*-executor-thread-pool-size`，Spring Cloud 默认 **2**、`SynchronousQueue` 直传）。这意味着：

- 同一 JVM 里有多个 DiscoveryClient（多注册中心、多 namespace）时线程数按倍数增长；
- 线程池满时任务会走 `RejectedExecutionException`（被 `TimedSupervisorTask` 捕获计数而不抛出），表现为心跳/拉取静默停止——把 Servo/Spectator 的 `DiscoveryClient-Heartbeat` 相关指标接出来才能发现；
- 任务超时后 `TimedSupervisorTask` 会把间隔翻倍，直到 `*.-exponential-back-off-bound` 倍为止（默认 10 倍），成功则立刻复位。这是 Server 抖动时客户端自我保护的方式，不要误以为是 hang。

## Version Migration

| 目标                            | 要求                                                                                       |
| :---------------------------- | :--------------------------------------------------------------------------------------- |
| 继续用 Eureka 1.x                | 停留在 `javax.*` 栈：Netflix `1.10.19`，客户端默认 Jersey 1.19.1                                   |
| 升到 Spring Boot 3 / Cloud 4.x+ | **必须**用 Eureka `2.0.x`（jakarta + Jersey 3）。Spring Cloud 5.0.3 已固定依赖 `eureka-client:2.0.6`，不需要手工指定 |
| 自住引入 eureka-core             | 显式核对 `xstream` / `jersey` 版本，避免反序列化 CVE                                                   |

协议与数据模型在两个版本之间没有变化，因此 1.x 的 Server 与 2.x 的 Client 在理论上仍可互通（同一套 REST 契约），但官方从未承诺这种混跑，生产建议整体升级。

## Checklist

- [ ] `use-read-only-response-cache: false`（除非明确需要 readOnly 层）
- [ ] `service-url.defaultZone` 显式列出全部 peer 地址，不要留 `localhost:8761`
- [ ] `spring.application.name` 已设置（否则注册为 `UNKNOWN`）
- [ ] 容器环境显式指定 `instance-id`（避免 host+port 撞车）
- [ ] `lease-renewal-interval-in-seconds` 保持 30s
- [ ] Dashboard 的 `Renews threshold` 与 `Renews (last min)` 已在监控里
- [ ] 版本栈明确：Spring Boot 3+ ⇒ Eureka 2.0.x

## Links

- [Config](/docs/CS/Framework/eureka/config.md)
- [Troubleshooting](/docs/CS/Framework/eureka/troubleshooting.md)
- [Self Preservation](/docs/CS/Framework/eureka/self_preservation.md)
- [Cache](/docs/CS/Framework/eureka/cache.md)
- [Replication](/docs/CS/Framework/eureka/replication.md)
- [Spring Cloud](/docs/CS/Framework/eureka/spring_cloud.md)

## References

1. [Netflix/eureka Wiki · Configuring Eureka](https://github.com/Netflix/eureka/wiki/Configuring-Eureka)
2. [Spring Cloud Netflix 文档](https://docs.spring.io/spring-cloud-netflix/reference/)
