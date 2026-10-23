> [!NOTE]
> 每条按「现象 → 根因 → 排查 → 处置」组织。涉及的参数默认值看 [config](/docs/CS/Framework/eureka/config.md)，时间链路推导看 [cache](/docs/CS/Framework/eureka/cache.md?id=感知时延的完整推导)。

## Dashboard 出现 EMERGENCY 红字

> EMERGENCY! EUREKA MAY BE INCORRECTLY CLAIMING INSTANCES ARE UP WHEN THEY'RE NOT...

**根因**：进入[自我保护](/docs/CS/Framework/eureka/self_preservation.md)——最近一分钟收到的续约数低于阈值（默认 `1.7 × 实例数`）。

**排查**：对比 Dashboard 上 `Renews threshold` 与 `Renews (last min)` 两个值；Server 日志会出现 `DS: lease expiration is currently disabled.`。

**处置**：先判断是真的人数变少了还是网络问题。发布/缩容期间属于正常现象，恢复后会自动退出（观察窗口至少一分钟）；长期停滞则检查 Server 侧到各实例的网络连通性，以及有没有把 `lease-renewal-interval-in-seconds` 改大过。开发环境可直接关掉自我保护。

## 实例已停止但仍在列表里被调用

**根因**（三选一，按概率）：

1. 进程被 `kill -9`，没有发 DELETE，只能等租约过期。注意 `Lease` 的历史 bug 让实际过期窗口是 **`2 × duration` = 180s**（见 [registry](/docs/CS/Framework/eureka/registry.md?id=lease)），再加上 EvictionTask 60s 轮询、readOnly 30s 回填、客户端 30s 拉取，总计可达 5 分钟；
2. 正处于[自我保护](/docs/CS/Framework/eureka/self_preservation.md)，`evict()` 直接 return，**一个实例都不剔除**；
3. 调用方本地缓存尚未刷新，或服务列表被上层负载均衡器二次缓存。

**排查**：`curl http://<server>/eureka/apps` 看服务端是否还有该实例——若服务端已清除而调用方仍在调用，问题在客户端缓存或上层负载均衡。

**处置**：优雅下线（确保 `should-unregister-on-shutdown` 为 true 且 JVM 有机会执行 shutdown hook）；生产环境关闭只读缓存；**下游必须有超时重试与熔断**——Eureka 契约本来就允许返回已失效实例。

## 新实例上线迟迟不可见

**根因**：注册是客户端主动推送，Server 侧即刻生效，但读路径要过 readOnly 回填（30s）+ 客户端拉取（30s）。

**排查**：直接 `curl` Server 的 `/eureka/apps/{appId}` 确认是否已注册；若 Server 已有而客户端没有，开客户端 DEBUG 日志看 `Getting all instance registry info` / `Got delta update` 的节奏。

**处置**：`use-read-only-response-cache: false` + 适当下调 `registry-fetch-interval-seconds`（如 15s）。容器环境下还要确认 `prefer-ip-address` / `instance-id` 是否正确，否则调用方会拿到不可达地址。

## DS Replicas 为空 / unavailable-replicas 列出所有 peer

**根因**：最常见的是**每个节点的 `defaultZone` 没有把集群所有成员（含彼此）列全**，或使用了 `localhost` / 容器 hostname 导致 `isThisMyUrl` 判定失败——节点会把识别不了的地址当成 peer 反复重试，或在列表中找不到自己。

**排查**：Dashboard 的 `DS Replicas` 区块；启动日志里 `Replica node URL: ...` 各行；`/{version}/status` 端点。

**处置**：统一使用可解析的真实主机名或 IP；每份配置写全量地址列表；确保主机名正向/反向解析可用。

## Cannot execute request on any known server

**根因**：除了地址写错（最常见：保留了默认的 `http://localhost:8761/eureka/`），还有两类容易被忽略：

- Spring Cloud 部署的默认前缀是 **`/eureka/`**（`EurekaServerAutoConfiguration` 注册的 Jersey Filter 挂在 `EurekaConstants.DEFAULT_PREFIX + "/*"`），直接写 `http://host:8761/` 会打不到；
- 手工拼 URL 带了奇怪的 context-path，撞上服务端把非 `/eureka/v2` 请求重写的版本 Filter。

**排查**：`curl -v http://<host>:8761/eureka/apps` 应返回 200 与 JSON/XML。

## 服务注册成 UNKNOWN

**根因**：没有配置 `spring.application.name`。`EurekaInstanceConfigBean` 的 `appname` 字段默认 `"unknown"`，只在 `spring.application.name` 存在时才被回填。

**处置**：显式设置 `spring.application.name`，其它应用才能按 VIP（`vipAddress`）找到它。

## 实例数莫名抖动 / 实例被互相顶替

**根因**：默认 `instance-id` 由 hostname + appName + port 组合而来。容器环境下多个容器 hostname 相同、容器内端口也相同时，**多个实例会共享同一个 instanceId**，注册表里后注册者覆盖先注册者，表现为实例数忽上忽下，还容易连带触发自我保护。

**处置**：容器环境显式指定 `eureka.instance.instance-id`（如 `${spring.application.name}:${random.value}`，或用 Pod IP），并配合 `prefer-ip-address: true`。

## 日志反复出现 Not Found (Renew) / Re-registering apps

**根因**：客户端续约（PUT）拿到 404，即进入 [REST API](/docs/CS/Framework/eureka/rest_api.md?id=renew-endpoint) 定义的「请重新注册」语义。两种触发：`renew()` 时 lease 不存在（Server 重启过 / 注册表被清空 / 该实例已被剔除过），或 override 状态被判为 `UNKNOWN`。

**处置**：偶发属于自愈机制，无需处理。持续刷屏则检查 Server 是否在反复重启、是否刚从长时间保护态退出而集中清理，或是否存在两个进程共用同一个 instanceId。

## Server 之间数据不一致

**根因**：写请求 fanout 是异步的，[replication](/docs/CS/Framework/eureka/replication.md) 队列在网络分区时积压，超过 `max-elements-in-peer-replication-pool`（10000）后被丢弃。

**排查**：逐个 `curl` 每个节点的 `/eureka/apps` 对比实例数；Server 日志里找 `Cannot replicate information to ...` 类错误。

**处置**：先恢复网络/端口连通性；积压清空后未补齐的实例通常会被下一轮心跳带着完整实例信息重新同步；实在卡死的实例由客户端重新注册。

## 客户端 healthcheck 与 Eureka 状态不符

**根因**：`eureka.client.healthcheck.enabled` **默认 false**——此时上报的状态是注册时的 `initial-status`，而不是 Spring Boot 的健康态。应用已经不可用（线程池打满、DB 断连）但 Eureka 仍显示 `UP`。

**处置**：开启该开关并确认 `/actuator/health` 可达。`EurekaHealthCheckHandler` 的映射是 `UP→UP`、`DOWN→DOWN`、`OUT_OF_SERVICE→DOWN`、`UNKNOWN→UNKNOWN`；聚合器在 5.x 里已从 `HealthAggregator` 更名为 `StatusAggregator`。

## Spring Boot 3 报 javax.* 的 NoClassDefFoundError

**根因**：Eureka 1.x 用 `javax.ws.rs` + Jersey 1，jakarta 栈下找不到类。

**处置**：升级到 Spring Cloud Netflix 4.x/5.x（它自动带 `com.netflix.eureka:eureka-client:2.0.x` 与 `jersey3` 包），不要手工引入 `eureka-client:1.10.x` 去覆盖依赖管理。

## delta 拉取不一致 / appsHashCode 不匹配

**根因**：增量队列只保留 3 分钟（`retentionTimeInMSInDeltaQueue`），客户端长时间失联会丢中间变更；或服务端被配置成禁用增量（`disableDelta=true` 时 `apps/delta` 返回 403）。

**处置**：客户端的 `reconcileAndLogDifference` 会自动退化为全量拉取，属于自愈；排查时打开 `eureka.client.log-delta-diff` 打印差异明细。

## XStream / Jersey 版本安全告警

**根因**：Server 端 XML codec 走 `XStreamXml`，历史上多次出现反序列化 CVE；Jersey 1.19.1 也已多年未更新。

**处置**：Spring Cloud 体系内交由依赖管理升级；自行组网务必核对 `xstream`、`jersey` 版本，必要时在 [codec 配置](/docs/CS/Framework/eureka/rest_api.md?id=filters-and-codecs)里只保留 JSON。

## Links

- [Config](/docs/CS/Framework/eureka/config.md)
- [Tuning](/docs/CS/Framework/eureka/tuning.md)
- [Self Preservation](/docs/CS/Framework/eureka/self_preservation.md)
- [Registry](/docs/CS/Framework/eureka/registry.md)
- [Replication](/docs/CS/Framework/eureka/replication.md)
- [Client](/docs/CS/Framework/eureka/Client.md)

## References

1. [Netflix/eureka Wiki](https://github.com/Netflix/eureka/wiki)
2. [Spring Cloud Netflix 文档](https://docs.spring.io/spring-cloud-netflix/reference/)
