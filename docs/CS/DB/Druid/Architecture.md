## Introduction

Druid 的架构可以用一个反差概括：**存储是最激进的不可变列存，部署是最保守的多角色进程组**。数据一旦写成分片（segment）就不再改，查询按时间维度被天然切分到持有对应分片的节点上并行执行；而集群侧则沿用一套经得起 decade 考验的「角色 + 外部协调」组合——深存储放文件、元数据库放目录、ZooKeeper/Consul 做选主与发现。本页讲清这台机器的骨架：六类角色、三条链路（摄取/服务/查询）、协调层的收缩史，以及 Dart 引擎带来的查询拓扑变化。分片文件格式在 [Storage_Format](/docs/CS/DB/Druid/Storage_Format.md) 展开，查询执行细节在 [Query_Engine](/docs/CS/DB/Druid/Query_Engine.md)。

## Process Roles

一个生产集群通常由六类进程组成，外加跑在 Router 上的 Web 控制台。它们都是同一个发行包里用不同 `role` 参数起来的 JVM 进程：

| 角色 | 职责 | 关键点 |
| :--- | :--- | :--- |
| **Coordinator** | 管理分片在 Historical 上的分布：执行负载规则、触发负载/卸载/淘汰 | 通过 API 读元数据库；leader 选举失败时集群只读不写 |
| **Overlord** | 接收摄取任务（ingestion task）并分配给 worker 执行 | 任务锁、任务锁竞争、supervisor 的常驻管理都在这 |
| **MiddleManager / Peon** | MiddleManager 是 worker 的管理者，Peon 是实际跑任务的 JVM（每个任务一个独立 Peon 进程，隔离故障） | K8s 部署可用 overlord-extensions 直接起 pod，绕开 MiddleManager |
| **Historical** | 从深存储加载分片到本地，回答涉及这些分片的查询 | 缓存分片在本地磁盘；按 tier 分组 |
| **Broker** | 接收查询，fan-out 到相关 Historical/实时任务，合并结果（scatter/gather） | 持有查询缓存；自身不存分片（Dart 模式除外） |
| **Router**（可选） | 查询的统一入口，按数据源/策略路由到 Broker；托管 Web 控制台 | 控制台依赖它的 managementProxy |

三处容易混淆的边界：

- **Coordinator 不服务查询，Broker 不服务分片**。Coordinator 只回答「哪些段在哪些节点上」，Broker 拿这个答案去 scatter。所以 Coordinator 挂了不影响在途查询（有缓存），Broker 挂了等于查询入口没了。
- **实时任务（Peon 上跑的流摄取任务）在发布（publish）前也服务查询**——这就是「实时段」（realtime segments）的来源；发布后段交给 Historical，任务退出。
- **MiddleManager 与 Peon 是一对多**：MiddleManager 负责启停 Peon、上报状态，Peon 是任务的沙箱。一个 Peon 挂掉只损失它正在跑的任务。

## The Three Planes

### Ingestion Plane

```
外部源 ──► Overlord ──► MiddleManager/Peon ──► 生成分片 ──► 深存储
(Kafka/  (任务分配、   (执行 task：           (写入 S3/
 Kinesis/  任务锁)     解析、转换、聚合、        HDFS) ──► 元数据库
 文件/S3)                写分片)                     (段记录)
```

摄取任务的产物是深存储里的分片文件 + 元数据库里的段记录。任务本身不长期持有数据——这是「任务失败可以重跑、节点宕机不丢数据」的原因。批摄取（native batch / SQL-based ingestion）与流摄取（supervisor 常驻）的任务类型差异见 [Ingestion](/docs/CS/DB/Druid/Ingestion.md)。

### Serving Plane

```
Coordinator ──► 规则计算 ──► HTTP 通知 Historical「加载/卸载这些段」
Historical  ──► 从深存储下载段 ──► 本地缓存 ──► 向 Coordinator 上报已加载集合
```

Historical 启动时先从元数据库同步全量段清单，再按 Coordinator 的指令增量加载。这条链路自 25.0.0 起完全走 HTTP：`druid.serverview.type=http`、`druid.coordinator.loadqueuepeon.type=http` 是默认值，ZooKeeper 的段加载路径（`loadQueuePath`）在 30.0.0 被移除。

### Query Plane

```
Client ──► Broker ──► 查询缓存命中？ ──► 按段时间线拆分查询
                                    └─► scatter 到持有相关段的 Historical / 实时任务
                                    └─► gather 合并结果 ──► 返回
```

Broker 的查询拆分单位是段：一个跨三个月的时间范围查询会被拆成「分别打向持有各月分片的节点」再合并。段未完全加载（block 不完整）时，默认会等——线性分片（linear shardSpec）是例外，允许不完整即返回。结果按段粒度缓存（per-segment result cache），这也是「同一看板重复查询几乎免费」的原因。

## Coordination: From ZooKeeper to HTTP to Consul

Druid 早期重度依赖 ZooKeeper：选主、段公告、段加载队列、任务分配全在上面。三代版本把 ZK 的职责搬空了：

| 版本 | 变更 |
| :--- | :--- |
| 25.0.0 | 分片发现与任务管理默认改 HTTP：`druid.serverview.type` 默认 `http`、`druid.coordinator.loadqueuepeon.type` 默认 `http`、`druid.indexer.runner.type` 默认 `httpRemote` |
| 30.0.0 | 移除 ZK 段加载；`druid.zk.paths.loadQueuePath`/`servedSegmentsPath` 不再使用 |
| 31.0.0 | ZK 段加载路径彻底禁用 |
| 38.0.0 | 移除 ZK 段公告与发现（`druid.serverview.type` 非 `http` 直接启动失败）、移除 ZK RemoteTaskRunner（`druid.indexer.runner.type=remote` 启动失败） |

**38.0.0 的 ZooKeeper 只剩三件事**：Coordinator/Overlord 的 leader 选举、节点（服务）公告与发现、Overlord→MiddleManager 的任务管理。zk 集群本身仍要运维。想彻底去掉它：37.0.0 引入的 contrib 扩展 `druid-consul-extensions` 可用 Consul 承担服务发现与 leader 选举（支持 ACL 与 TLS/mTLS），前提是全集群先切到 `druid.serverview.type=http` + `druid.indexer.runner.type=httpRemote`；`druid-kubernetes-extensions` 则面向「不部署 ZK 的 K8s 集群」场景。

## Metadata Store and Deep Storage

两个外部依赖划清了 Druid 的「目录」与「文件库」：

- **元数据存储（metadata store）**：MySQL 或 PostgreSQL（生产必需；Derby 只够开发）。存段记录、任务记录、supervisor 状态、审计与压实状态（`druid_segments`、`druid_tasks`、`druid_rules`、`druid_indexingStates` 等表）。元数据库是集群的「事实来源」，挂了集群进入只读/不可分配状态。MySQL 扩展因许可不含 JDBC 驱动，需单独放入。
- **深存储（deep storage）**：S3、HDFS、GCS、Azure Blob 或本地盘。存分片文件本体。Historical 按需从这里拉段，任务把新段写到这里。本地盘模式只适合单机。

两者都可以是托管的：元数据库用云 RDS，深存储用对象存储——这是 Druid 在云上最主流的形态。

## Dart: A Second Query Topology

31.0.0 引入的实验性引擎 **Dart**（Distributed Asynchronous Runtime Topology）改的是查询拓扑而不是存储格式：**Broker 退化为控制器，Historical 直接当 worker 执行**。一个 SQL 查询以 `engine = 'msq-dart'`（或控制台选 SQL Dart）提交后，由 Broker 拆分 stage、Historical 多线程执行并在内存里 shuffle。

```
传统查询：  Client ─► Broker（scatter/gather + 合并）─► Historical（单查询单线程执行）
Dart：      Client ─► Broker（controller，只做调度）─► Historical（worker，多线程 + 内存 shuffle）
```

Dart 的甜点是大 join（并行 sort-merge）、高基数精确 groupBy、高基数精确 count distinct；代价是 Historical 的资源占用（`druid.msq.dart.worker.heapFraction` 默认 0.35）与「实验性」这三个字。机制细节见 [Query_Engine](/docs/CS/DB/Druid/Query_Engine.md)。

## High Availability and Scaling

- **无单点**：Coordinator/Overlord 多实例经 leader 选举只有一个 active，其余 standby；Broker/Historical/Router 无状态可随意加减；MiddleManager/Peon 挂了只丢在途任务，重提即可。
- **加数据容量 = 加 Historical**：新 Historical 启动后 Coordinator 自动按规则给它分配段；加查询吞吐 = 加 Broker。
- **tier 与优先级**：Historical 可按 tier 分组（hot/cold 不同硬件），负载规则指定副本落到哪些 tier；Broker 侧可配置 `druid.broker.select.tier` 选择策略（37.0.0 新增 `strict` 与 `pooled` 两种实现）。
- **分片复制**：负载规则的副本数决定每段存几份，跨 Historical 分布；一台挂掉，查询仍可从副本完成（block 完整的前提下）。

## Links

- [Druid](/docs/CS/DB/Druid.md)
- [Storage Format](/docs/CS/DB/Druid/Storage_Format.md)
- [Query Engine](/docs/CS/DB/Druid/Query_Engine.md)
- [Ingestion](/docs/CS/DB/Druid/Ingestion.md)
- [Operations](/docs/CS/DB/Druid/Operations.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)

## References

1. [Druid Design: Processes and Servers](https://druid.apache.org/docs/latest/design/processes/)
2. [Druid Design: ZooKeeper](https://druid.apache.org/docs/latest/design/zookeeper/)
3. [Druid Upgrade Notes](https://druid.apache.org/docs/latest/release-info/upgrade-notes)
4. [Druid: A Real-time Analytical Data Store](https://dl.acm.org/doi/10.14778/3021924.3021927)
