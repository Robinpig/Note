## Introduction

Druid 的运维关键词是**进程角色 + 外部依赖 + 在线配置**：集群形态从单机 micro-quickstart 到多角色集群到 K8s，配置以 `common.runtime.properties` 为中心、多数管理操作走 HTTP API 无需重启。本页按「部署形态 → 容量与内存 → 监控 → 安全 → 升级 → 排障」的顺序给出可落地的那一层；机制原理在 [Architecture](/docs/CS/DB/Druid/Architecture.md)，数据生命周期在 [Data_Management](/docs/CS/DB/Druid/Data_Management.md)，扩展装配在 [Extensions](/docs/CS/DB/Druid/Extensions.md)。

## Deployment Shapes

- **micro-quickstart**：单进程跑全部角色（`bin/start-micro-quickstart`），元数据用内嵌 Derby、深存储用本地盘。只用于学习与冒烟，**任何生产指标都别引用它的数字**。
- **多角色集群**：一类角色一组进程，共享一份 `common.runtime.properties` + 每角色 `runtime.properties`。最小生产集 = Coordinator×2 + Overlord×2 + MiddleManager（按需扩）+ Historical（按容量扩）+ Broker（按 QPS 扩）+ Router + MySQL/PostgreSQL + 对象存储 + ZooKeeper（或 Consul）。
- **Kubernetes**：Druid Operator（37.0.0 起独立仓库 `apache/druid-operator`，CRD 管理）或 `druid-kubernetes-overlord-extensions`（Overlord 直接起 task pod，不经 MiddleManager）。38.0.0 起还支持按名选择 podTemplate。
- **容器化注意**：Druid 吃两套内存——JVM 堆（`druid.*` 服务的对象）与**直接内存**（处理缓冲、merge buffer、mmap 段文件）。容器 limit 必须同时覆盖两者，只设 `-Xmx` 会被 cgroup OOM kill；36.0.0 起 cgroup v2 的监控指标可用（`cgroupversion` 字段标注版本）。

## Sizing and Memory

按角色拆：

| 角色 | 内存重点 | 扩容信号 |
| :--- | :--- | :--- |
| Historical | 段 mmap + 段缓存（`druid.server.maxSize`）+ 查询处理缓冲 | 本地缓存打满、段加载排队 |
| Broker | 堆（查询合并、缓存）+ 段元数据缓存（37.0.0 起默认开，吃内存） | QPS 涨、查询排队 |
| MiddleManager/Peon | 每个 Peon 独立 JVM，摄取任务的处理缓冲 | 任务排队、摄取 lag |
| Coordinator/Overlord | 堆（元数据、规则计算），数据量大时随段数涨 | 均衡/分配周期变长 |

查询引擎侧的关键旋钮：`druid.processing.numThreads`（默认接近核数）、`druid.processing.buffer.sizeBytes`（单查询处理缓冲）、merge buffer 数量（并行合并上限，Dart 的 `concurrentQueries` 也受它约束）。** ingest 侧的对应物是 `maxRowsInMemory` / `targetRowsPerSegment`**——直接决定段大小，段大小甜点区 300–700 MB 的纪律见 [Storage_Format](/docs/CS/DB/Druid/Storage_Format.md)。具体默认值以官方 tuning 文档对应版本为准，不要跨版本照抄。

## Monitoring

- **指标管线**：monitors 采集 → emitter 外发（contrib 的 `prometheus-emitter` / `statsd-emitter` 等）。37.0.0 起所有指标带 `buildRevision` 字段，可校验集群里各节点是否跑同一构建；37.0.0 新增 `supervisor/count` 指标（SupervisorStatsMonitor 开启时上报 supervisor 状态）。
- **HTTP 端点**：`/status/health`、`/status/selfDiscovered`、各角色的 `/druid/...` API；查询报告（MSQ/Dart）可经 `/druid/v2/sql/queries/<id>/reports` 拉取（36.0.0 起），`sys.queries` 表用 SQL 查 Dart 查询（37.0.0，默认关）。
- **Web 控制台**：Router 托管的 Home/Datasources/Segments/Supervisors/Tasks/Services/Lookups 视图，是日常运维的主界面；37.0.0 起 Home 的 Services 卡片直接报各角色数量（无 SQL 权限时也可用），支持手动指定 Broker 路由（`consoleBrokerService`）。
- **日志**：任务日志（task log）经任务日志上传器落到深存储，MiddleManager 上 30.0.0 起 GoogleTaskLogs 上传缓冲从 15 MB 降到 1 MB（防 MM OOM）。

## Security Baseline

生产集群的最低集：

1. **必须开认证授权**：未配置时 Web 控制台权限 = 运行 Druid 的系统用户。`druid-basic-security`（Basic + RBAC）或 `druid-pac4j`（OIDC）；MSQ 读外部数据记得授 `EXTERNAL READ`。
2. **进程间 TLS**：`simple-client-sslcontext` 或自建；对公网暴露的 Router 尤其要配。
3. **收紧管理面**：Coordinator/Overlord 的管理 API（规则、kill、supervisor）不要对公网开放；37.0.0 的查询黑名单是紧急刹车，不是访问控制。
4. **审计**：`druid.audit.manager.type=sql|log` 落审计事件（29.0.0 引入）。
5. **多租户隔离**：RBAC 的数据源级权限 + 37.0.0 的 `ReadOnly` authorizer（注意它对部分只读端点也要求 WRITE 的已知限制）。

## Upgrades

顺序与断点比步骤更重要：

- **滚动升级下限**：37.0.0 起明确**不能从 0.23 以前的版本直接滚动升级**，先离线跳到 0.23+。
- **跨版本升级先读 upgrade notes 的「多版本合并清单」**，每个大版本都有不兼容变更，容易踩的几处：28.0.0 元数据表要加 `used_status_last_updated` 列；31.0.0 `arrayIngestMode` 默认 `array`；37.0.0 流摄取 `parser` 移除 + front-coding v1 默认 + 压实元数据表变更；38.0.0 Java 17 移除 + 残留 ZK 属性直接启动失败。
- **段格式是硬门**：36.0.0 的 v10 段与旧版互不兼容，开了 `buildV10` 就降不回去（必须 reindex）；front-coding v1 同理。
- **升级顺序**：先 Coordinator/Overlord（管理面），再 Historical/Broker（数据面），最后 Router；ZK 属性清理放在滚动升级前（38.0.0 启动即校验）。

## Troubleshooting Order

线上问题按这个次序收敛，比随机翻日志快：

1. **查询变慢/超时**：先看是不是段问题——`sys.segments` 查 block 是否完整、Historical 是否在加载；再看缓存命中与 laning/优先级；最后看 37.0.0 的查询黑名单有没有误伤。段级计划用 `EXPLAIN PLAN FOR`。
2. **流摄取 lag**：supervisor 状态（`/druid/indexer/v1/supervisor/status`）→ 任务数是否够（`taskCount*`）→ Kafka 侧 consumer lag → 36.0.0 起的成本扩缩是否把任务数压太低。
3. **数据查不到**：实时段是否发布（`realtimeSegmentsMode`）→ 段是否 overshadowed → 时间列解析（`timestampSpec` 丢行）→ rollup 粒度是否吞掉了明细。
4. **磁盘不释放**：kill 任务是否跑（37.0.0 起任务前缀 `auto`）→ 段是否被标记 unused（kill 只在显式指定时标记）→ 深存储与 Historical 本地盘两头查。
5. **任务反复失败**：38.0.0 起 ingestion 对「数据类型不匹配」更健壮、任务日志上传失败不再让任务失败——先看是不是这两类历史误报；再看 Thrift/自定义 InputFormat 的版本兼容。
6. **升级后起不来**：九成是 38.0.0 的 ZK 属性残留、37.0.0 的 parser、或 Java 版本——错误信息都带明确指引。

## CLI Tools Worth Knowing

- `bin/dump-segment`：导段元数据为 JSON，排查段内容与格式版本的第一工具（36.0.0 起 V10 段也能看）。
- `bin/pull-deps`（`tools pull-deps`）：拉 contrib 扩展。
- `bin/run-java`：启动包装脚本，38.0.0 起认 `DRUID_JAVA_HOME`/`JAVA_HOME`。

## Links

- [Druid](/docs/CS/DB/Druid.md)
- [Architecture](/docs/CS/DB/Druid/Architecture.md)
- [Data Management](/docs/CS/DB/Druid/Data_Management.md)
- [Extensions](/docs/CS/DB/Druid/Extensions.md)
- [cgroup](/docs/CS/OS/Linux/cgroup.md)

## References

1. [Druid Operations: Cluster Tuning](https://druid.apache.org/docs/latest/operations/tuning/)
2. [Druid Operations: Security Overview](https://druid.apache.org/docs/latest/operations/security-overview.html)
3. [Druid Upgrade Notes](https://druid.apache.org/docs/latest/release-info/upgrade-notes)
4. [Apache Druid Operator](https://github.com/apache/druid-operator)
