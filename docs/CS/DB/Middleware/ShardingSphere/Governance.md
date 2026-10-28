## Introduction

治理层回答「多实例怎么协同」：元数据存哪、配置怎么下发、状态怎么协调、流量怎么看见、数据怎么搬家。本页覆盖运行模式与元数据仓库、注册中心数据结构、DistSQL、可观测性 Agent 与数据迁移四阶段。它是集群模式与混合部署的地基。

## Running Modes and Metadata Repositories

| 模式 | 元数据仓库 | 适用 |
| :--- | :--- | :--- |
| Standalone | `File`（默认路径 `.shardingsphere`，可配 `path`） | 本地开发、测试 |
| Cluster | `ZooKeeper` | 生产 |
| Cluster | `Etcd` | 生产 |

- **Standalone**：元数据落本地文件，实例间不共享、互不感知——单机改配置，别的实例不会同步。
- **Cluster**：元数据进注册中心，多实例共享配置、协调状态，支撑算力水平扩展与高可用。**生产环境与 JDBC+Proxy 混合部署都必须用集群模式**（混合部署要求两端按同一份注册中心配置行动）。
- 仓库配置带 `overwrite` 语义：是否让本地配置覆盖注册中心配置（可覆盖时每次启动以本地为准）。

ZooKeeper 仓库的常用调优属性：`retryIntervalMilliseconds`（默认 500）、`maxRetries`（默认 3）、`timeToLiveSeconds`（默认 60，临时数据失效秒数）、`operationTimeoutMilliseconds`（默认 500）、`digest`（认证令牌）。Etcd 仓库：`timeToLiveSeconds`（默认 30）、`connectionTimeout`（默认 30）。

## Registry Data Structure

集群模式的注册中心不是黑盒，数据结构官方公开（以命名空间为根）：

```
namespace
 ├── rules        # 全局规则配置（YAML）
 ├── props        # 属性配置
 ├── metadata     # 元数据配置
 │    └── ${schema}          # 按 schema 分头
 │         ├── dataSources   # 数据源配置
 │         ├── rules         # 规则配置
 │         └── schema        # 表配置
 └── status       # 运行时状态
      ├── compute_nodes      # 计算节点（Proxy/JDBC 实例）在线状态
      ├── circuit_breaker    # 熔断状态位
      └── storage_nodes      # 存储节点（数据源）状态，含 disable
```

- 改 `rules`/`props`/`metadata` 节点 = 动态刷新配置，这是「配置中心」职能；
- `status` 树是治理的状态面：实例上下线、数据源禁用/恢复、熔断位——读写分离的 HA 与流量治理都落在这棵树上（见 [Readwrite Splitting](/docs/CS/DB/Middleware/ShardingSphere/Readwrite_Splitting.md)）；
- 注册中心同时承担分布式锁，协调集群内的独占操作（如切换、禁用）。

## DistSQL

DistSQL 是 ShardingSphere 的**SQL 式配置接口**：连接接入端后用标准 SQL 语句管理数据源、规则与元数据，而不是手改 YAML。官方把它归入 Connect 能力——「通过内置 DistSQL 为应用提供标准化连接模式」。它的实践价值在集群模式：规则变更走 SQL 下发，经注册中心广播到全部实例，避免逐节点改文件。具体语句语法随版本演进较快，用时以当前版本文档的语法页为准。

## Observability

可观测性由 **ShardingSphere-Agent** 提供——基于 Java Agent（ByteBuddy 字节码增强）的独立框架，Metrics/Tracing/Logging 全部以插件形式集成：

| 类别 | 插件 | 说明 |
| :--- | :--- | :--- |
| Metrics | Prometheus | 默认支持；JVM 采集器 `jvm-information-collector-enabled` 默认开 |
| Tracing | Jaeger、Zipkin、OpenTelemetry、OpenTracing（SkyWalking） | SQL 解析与执行各阶段链路耗时 |
| Logging | BaseLogging | 额外日志记录示例 |

- **默认不启用任何插件**，`agent.yaml` 里显式打开；`ignoredPluginNames` 可反向屏蔽插件。
- 采样参数按插件配置：Jaeger `jaeger-sampler-type`（const/probabilistic/ratelimiting/remote）、Zipkin `sampler-type`（const/counting/ratelimiting/boundary）、OpenTelemetry `otel-traces-exporter`（zipkin/jaeger）。
- **边界**：官方明确 ShardingSphere 只负责**生产**可观测数据并通过标准协议/插件提交，不负责采集、存储与展示——存储展示交给 Prometheus/Jaeger/Zipkin/SkyWalking 那侧。
- Tracing 的粒度正好覆盖本库 [SQL Pipeline](/docs/CS/DB/Middleware/ShardingSphere/SQL_Pipeline.md) 的五阶段，慢查询定位先看耗时落在解析、路由、执行还是归并。

## Data Migration

数据迁移（Pipeline，前身 Scaling）把传统单库平滑切换到 ShardingSphere 分片集群，**整体迁到一套全新集群**：不影响原数据、失败无风险、不受旧分片策略限制；代价是过渡期冗余服务器与全量搬迁。四个阶段：

1. **Preparation（准备）**：校验源库连通性与权限、统计存量数据、按数据量与用户设定的并行度切分任务。
2. **Stock data migration（存量迁移）**：JDBC 直读源库、按分片规则写入目标节点。
3. **Incremental synchronization（增量同步）**：迁存量期间业务持续写入，靠复制协议/WAL 追平——**MySQL 订阅解析 binlog；PostgreSQL 用官方逻辑复制 `test_decoding`**。
4. **Traffic switching（流量切换）**：设一个只读窗口（源库置只读或控流）确保增量追平；**一致性校验是独立任务**，可单独启停、断点续传；确认后把读写流量切到 ShardingSphere。

迁移期间增量流不中断（业务不停），只读窗口长度取决于是否做一致性校验与数据量。

## Facts Worth Pinning Down

1. **生产与混合部署必须集群模式**：Standalone 的元数据不共享，多实例配置漂移无感知。
2. **注册中心数据结构是公开契约**：`rules`/`props`/`metadata`/`status` 四棵树，配置动态刷新与状态治理都通过它。
3. **Agent 默认全关**：不配 `agent.yaml` 就没有任何指标与链路；采样类型按插件各有一套参数。
4. **增量同步按库分化**：MySQL 走 binlog 订阅解析，PostgreSQL 走 `test_decoding` 逻辑复制——没有通用 WAL 抽象。
5. **一致性校验是独立任务**：可单独启停与断点续传，切换窗口的长度由「是否校验 + 数据量」决定。

## Links

- [Architecture](/docs/CS/DB/Middleware/ShardingSphere/Architecture.md)
- [Operations](/docs/CS/DB/Middleware/ShardingSphere/Operations.md)
- [MySQL binlog](/docs/CS/DB/MySQL/binlog.md)

## References

1. [Metadata Repository (built-in algorithm, v5.2)](https://shardingsphere.apache.org/document/5.2.0/cn/user-manual/common-config/builtin-algorithm/metadata-repository)
2. [Observability :: ShardingSphere](https://shardingsphere.apache.org/document/current/en/features/observability/)
3. [Observability (Proxy user manual, v5.3)](https://shardingsphere.apache.org/document/5.3.0/en/user-manual/shardingsphere-proxy/observability/)
4. [Data Migration :: ShardingSphere](https://shardingsphere.apache.org/document/current/en/reference/migration/)
5. [Apache ShardingSphere document v5.0.0](https://shardingsphere.apache.org/document/5.0.0/en/shardingsphere_docs_en.pdf)
6. [Your Detailed Guide to Apache ShardingSphere's Operating Modes](https://shardingsphere.apache.org/blog/en/material/jan_28_your_detailed_guide_to_apache_shardingspheres_operating_modes)
