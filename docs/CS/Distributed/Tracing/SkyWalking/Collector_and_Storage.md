## Introduction

本篇展开 [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) 的**服务端 OAP（Observability Analysis Platform）**：数据如何被 Receiver 接纳，如何用 **OAL / MAL / LAL** 三类分析语言做流式聚合，存储后端的选型取舍（默认 BanyanDB），以及基于指标的告警。这是 SkyWalking 作为 APM 区别于纯追踪后端的主体。

## Receiver and Analysis Core

OAP 收到 Segment / 指标 / 日志后，先按类型路由到对应 receiver（`receiver-trace` / `receiver-meter` / `receiver-log` / `receiver-event` / `receiver-profile` / `service-mesh` 等），再进入**分析核心**：

- **L1 / L2 聚合**：先按分钟（Minute）聚合，再下采样到小时（Hour）/ 天（Day），由 `core/downsampling` 配置。
- **拓扑自动构建**：服务 / 实例 / 端点之间的依赖由 OAP 内核自动从流量推导，**无需显式 OAL**。
- **指标可定制**：通过 OAL 脚本把 trace / mesh 流量计算成 Service / Instance / Endpoint 维度指标。

OAP 是**纯模块化**设计，行为完全由 `config/application.yml` 驱动：每一级是「模块名 → provider 选择器 → provider 配置」，end-user 按需开关 / 组装 collector 能力；启动日志会打印关键参数（`module.xxx.provider`、`oap.external.grpc.port=11800`、`oap.external.http.port=12800`）。代表性模块 / provider：

- **core**：提供 gRPC（11800）与 REST/HTTP（12800）通道，及内部集群通信。
- **receiver-\***：按遥测类型拆分——`receiver-trace` / `receiver-jvm` / `receiver-meter` / `receiver-otel` / `receiver-register` / `receiver-log` / `receiver-event` / `receiver-profile` / `receiver-ebpf` / `service-mesh`（Envoy access log）/ `receiver-browser` 等。
- **agent-analyzer / event-analyzer / log-analyzer**：对应 trace / event / log 分析。
- **alarm**：基于指标的告警。
- **query**：`graphql` provider，对外暴露 GraphQL。
- **cluster**：集群协调 provider（standalone / zookeeper / consul / etcd / kubernetes）。
- **configuration**：动态配置（none / zookeeper / consul / etcd / nacos / k8s-configmap）。

OAP 原生支持集群：多个节点通过 **cluster provider** 选主与发现彼此，内部用 gRPC/HTTP2 在 `oap.internal.comm` 通信（默认 11800，集群模式需改掉默认 `0.0.0.0` 绑定，除非在 k8s 中部署）；指标 / 拓扑由所有节点共同计算，存储后端承担最终落地与去重；动态配置（告警规则、采样率）经 configuration provider 热更新，无需重启。

## Analysis Languages: OAL / MAL / LAL

SkyWalking 提供三套原生分析语言，覆盖不同信号源：

| 语言 | 作用域 | 典型用途 |
| --- | --- | --- |
| **OAL**（Observability Analysis Language） | 原生 trace + service mesh 流量 | 构建实体指标与拓扑 |
| **MAL**（Meter Analysis Language） | 原生 meter、Prometheus、OTel metrics | 指标计算 |
| **LAL**（Log Analysis Language） | 日志内容 | 格式化 / 打标，并抽取指标喂给 MAL |

OAL 语法以 `from` 声明数据源（Scope），`filter` 加条件，`.FUNCTION` 做聚合，编译成 Java 动态执行：

```oal
// 每个端点的平均响应时间
endpoint_resp_time = from(Endpoint.latency).longAvg()

// 每个服务的每分钟调用数（CPM）
service_cpm = from(Service.*).cpm()

// 端点名以 serv 开头的 p50/p75/p90/p95/p99
serv_Endpoint_p99 = from(Endpoint.latency).filter(name like "serv%").percentile2(10)

// HTTP 方法为 GET 的服务 CPM（tag 匹配两种写法）
service_cpm_http_get = from(Service.*).filter(tags contain "http.method:GET").cpm()
```

常用聚合函数：`longAvg` / `doubleAvg`、`count`、`cpm`、`percent`、`rate`、`histogram`、`apdex`、`percentile2`（标签化 p50/p75/p90/p95/p99）、`labelCount` / `labelAvg`。OAL 脚本位于 `/config`，**是编译型语言**——改动后需重启 OAP，且集群模式下各节点脚本须保持一致；可设 `SW_DYNAMIC_CLASS_ENGINE_DEBUG=Y` 把生成的 `.class` dump 到磁盘调试。

## Storage Backends

SkyWalking 存储是**可插拔**的，由 `application.yml` 的 `storage.selector` 选择（默认 `banyandb`）：

| 后端 | 定位 | 备注 |
| --- | --- | --- |
| **BanyanDB** | 原生 APM 数据库，**默认推荐** | 专为 SkyWalking 场景设计，约 200 服务 / 200+ cps 下 2 liaison + 2 data 节点即可稳定；支持全量 trace 采样 |
| **Elasticsearch / OpenSearch** | 生产、大规模 | 检索能力强、生态成熟；资源成本较高（内存与副本要求高） |
| **MySQL / PostgreSQL / TiDB / Aurora** | 生产、中规模 | 低 trace / log 采样率场景合适；TiDB / Aurora 等兼容库可支撑更大规模，但日志与 trace 性能显著低于 BanyanDB / ES，且难以靠扩容线性提升 |
| H2 | **已移除** | **10.2.0 起永久移除**，不再作为默认或可选存储 |

> H2 移除是 **10.2.0（2025-03）** 的 breaking change：BanyanDB 0.8.0 已成稳定生产级，故不再需要 H2 作默认。升级前需先把存储切到 BanyanDB / ES / MySQL 之一。

## Alarm

SkyWalking 的告警是**基于指标**的：规则写在 `config/alarm-settings.yml`，把 OAL 产出的指标（如 `service_resp_time`、`endpoint_abnormal`）与阈值、持续周期绑定，触发时通过 **webhook / Slack / 钉钉 / 飞书 / WeChat** 等钩子推送；也可配置「当告警触发时存储并查询指标快照」以便复盘。告警规则与动态配置均可经 configuration provider 热更新。

## Operational Notes

- OAP 运行需 **Java 11 / 17 / 21 / 25**；官方 Docker 镜像提供 `-java11` / `-java17` / `-java21` 变体，默认（无后缀）基于 **Java 25**。
- **版本基线**：**v11.0.0（2026-08-28，最新）/ v10.4.0（2026-04-01）**；10.2.0 移除 H2、默认 BanyanDB；v11 引入下一代 **Horizon UI**。
- BanyanDB 需先于 OAP 启动；兼容版本号见 `config/bydb.yml` 的 `SW_STORAGE_BANYANDB_COMPATIBLE_SERVER_API_VERSIONS`。
- OAP 监听 `0.0.0.0/11800`（gRPC 上报）与 `0.0.0.0/12800`（HTTP 上报 + GraphQL）；UI 监听 `8080`，向 `127.0.0.1/12800` 查询。

## Links

- [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) — 枢纽页
- [SkyWalking Transport](/docs/CS/Distributed/Tracing/SkyWalking/Transport.md) — Receiver 与 Kafka 通道
- [SkyWalking Query and UI](/docs/CS/Distributed/Tracing/SkyWalking/Query_and_UI.md) — GraphQL 与拓扑可视化
- [SkyWalking Internals](/docs/CS/Distributed/Tracing/SkyWalking/Internals.md) — OAL 编译、聚合 worker、TimeBucket 与 BanyanDB 模型
- [Elasticsearch](/docs/CS/Framework/ES/ES.md) — ES 存储后端对照
- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) — 多进程追踪后端对照

## References

1. [Backend storage](https://skywalking.apache.org/docs/main/next/en/setup/backend/backend-storage/) — 存储后端选型
2. [Observability Analysis Language](https://skywalking.apache.org/docs/main/next/en/concepts-and-designs/oal) — OAL 语法与函数
3. [Release 10.2.0](https://skywalking.apache.org/events/release-apache-skywalking-apm-10.2.0) — H2 移除、BanyanDB 0.8.0
4. [Backend setup](https://skywalking.apache.org/docs/main/next/en/setup/backend/backend-setup/) — 端口、Java 版本与启动
