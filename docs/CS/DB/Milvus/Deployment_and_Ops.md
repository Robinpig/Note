## Introduction

Milvus 没有为 Standalone 或 Cluster 各维护一套代码：同一个二进制按 `milvus run <serverType>` 装配不同的角色组合，就变成 Lite（embedded 发行）、Standalone、Cluster 三种形态。进程模型与角色职责见 [Milvus](/docs/CS/DB/Milvus/Milvus.md)，本篇只讲「装配」这一层：哪些角色在哪个进程里、装配差异、关停顺序，以及 MixCoord 如何用一个进程承载四个协调者。

真正的分水岭在外部依赖。3.0 的查询与写入机制在所有形态里完全相同，生产可用性由三个选型决定：WAL 后端（RocksMQ / Pulsar / Kafka / Woodpecker）、元数据 KV（内嵌 etcd / 外置 etcd / TiKV）、对象存储（MinIO / S3 系 / 本地盘）。WAL 的协议与内部机制归 [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)，本篇只给选型矩阵与固化语义。

第二层分水岭是配置与观测：Milvus 的配置是 yaml、环境变量、etcd 动态覆盖三层叠加，且 `mq.type` 这类不可变键在首次启动就被钉死进 etcd；可观测性集中在每个进程都开的 9091 管理端口（metrics、healthz、WebUI、动态改配置、eventlog）。配额与限流（QuotaCenter）是写请求被拒的第一嫌疑组件，它的事实代码在 rootcoord 包里、运行于 MixCoord 进程，执行却发生在 Proxy。

单机三节点实操（etcd + Kafka KRaft 集群搭建、端口规划、验证命令）是用户自己的手册，见 [Deploy](/docs/CS/DB/Milvus/Deploy.md)，本篇不重复任何 compose 或脚本内容。

## Role Assembly and Deployment Modes

### Role Assembly by milvus run

入口 `cmd/main.go` 调 `milvus.RunMilvus`，`cmd/milvus/util.go` 的 `GetMilvusRoles` 按第二个参数 `serverType` 直接决定启用哪些角色：`proxy` / `querynode` / `datanode` / `mixcoord` / `cdc` 各启用单一角色；`streamingnode` 会**强制附带一个 QueryNode**（`sessionutil.EnableEmbededQueryNodeLabel` 打 embedded-QN 标签）；`standalone` 与 `embedded` 启用 MixCoord + Proxy + QueryNode + DataNode + StreamingNode 全角色并置 `Local=true`；`mixture` 则逐角色由命令行 flags（`-rootcoord true -querynode true ...`）拼装，用于自定义混合部署。注意 `MilvusRoles` 结构体上的 `env:"ENABLE_PROXY"` 等 tag 在 v3.0.1 **没有任何反射消费者**，是 2.x 遗留——角色装配不看环境变量，只看子命令与 flags；`Run()` 反而会把 `DEPLOY_MODE` 写成 `STANDALONE` 或 `CLUSTER` 供指标标签使用。

`Run()` 的启动次序里有两个装配级细节：其一，协调者进程（`EnableMixCoord` 或三个 coord 齐开）负责 `util.InitAndSelectWALName()` 解析出实际 WAL 并用 `ProcessImmutableConfigs` 把 `mq.type` 的 `default` 渲染成具体名字**创建式写入 etcd**；其二，`streaming.Init()` 的判据是 `mr.ServerType == StandaloneRole || !mr.EnableDataNode`（`cmd/roles/roles.go`）：standalone 进程恒执行，其余进程只要没启用 DataNode 角色就执行——所以 Proxy / QueryNode / MixCoord 这些单角色进程都会初始化 WAL 客户端，但**任何启用了 DataNode 角色的非 standalone 进程都会跳过**，不限于「纯 DataNode」，`mixture -datanode true -proxy true` 这类组合同样不执行。组件创建并发（`runComponent` 先 Prepare 后 Run），`waitForAllComponentsReady` 采取 fast-fail：任一角色起不来整个进程退出。

### Deployment Mode Differences

| 形态 | 入口 | 进程内角色 | etcd | 对象存储 | WAL 默认 |
| --- | --- | --- | --- | --- | --- |
| Lite（Milvus Lite） | `pymilvus[milvus-lite]`，`MilvusClient("xx.db")` | 全部（embedded 形态发行，另仓维护） | 另仓维护，不由本仓库源码背书 | 另仓维护，不由本仓库源码背书 | 另仓维护，不由本仓库源码背书 |
| Embedded | `milvus run embedded`（`cmd/embedded` 导出 c-shared） | MixCoord+Proxy+QN+DN+StreamingNode | 内嵌（`ETCD_USE_EMBED`） | `COMMON_STORAGETYPE=local` | RocksMQ |
| Standalone | `milvus run standalone` | 同上 | 可内嵌可外置（默认外置 `localhost:2379`） | MinIO 或 local | RocksMQ（仅 standalone 允许） |
| Cluster | `milvus run <role>` 每角色独立进程（`scripts/start_cluster.sh` 起 mixcoord/datanode/querynode/streamingnode/proxy 五进程） | 单角色或 mixture 组合 | 必须外置（或至少独立可达） | MinIO/S3 系 | Pulsar（default 优先级）；新装建议显式 Woodpecker |

Embedded 与 Standalone 的差异只在 `Embedded=true` 时改从 `MILVUSCONF` 指定目录加载名为 `embedded-milvus.yaml` 的配置——`cmd/roles/roles.go` 只按文件名引用它，该文件不在源码仓库、其内容与生效项不由本仓库背书；`scripts/standalone_embed.sh` 则是另一个概念——Docker 单容器跑 Standalone，用内嵌 etcd（自造 `embedEtcd.yaml`，`quota-backend-bytes` 4 GiB、按 revision 1000 自动 compaction）加本地盘存储，零外部依赖。Milvus Lite 作为 pip 包由独立仓库 milvus-io/milvus-lite 维护，本仓库能核实的只有「embedded 装配形态」这一点，Lite 的内部行为不在此断言。

### Graceful Shutdown Order

收到 SIGINT/SIGTERM 后 `Run()` 的收尾顺序是**先协调者、再节点、最后 Proxy**：`mixCoord.Stop()`（内部先 `GracefulStop` 停 StreamingCoord，再 queryCoord → dataCoord → rootCoord，全部停完才释放共享 etcd session）→ StreamingNode / QueryNode / DataNode / CDC 并行 Stop → Proxy Stop → 关闭复用的 etcd client。理由是依赖方向：协调者是调度与 fencing 的源头，先停它就止住了任务再分配与元数据写入，避免节点在 drain 过程中又被安排新任务；工作节点随后台账落清、session 注销；Proxy 是纯无状态入口，最后关可把客户端「连接被拒」的窗口压到最短。每级都有超时兜底：`rootCoord.gracefulStopTimeout` 5s、`proxy.gracefulStopTimeout` 30s、DataNode 1800s，超时即强杀。

### MixCoord Hosting Four Coordinators

`internal/coordinator/mix_coord.go` 的 `mixCoordImpl` 聚合 `rootcoord.Core`、`datacoord.Server`、`querycoordv2.Server`、`streamingcoord.Server` 四个协调者，对外只监听一个 gRPC 端口（复用 `rootCoord.port`，默认 22125），同一 server 上注册三种 pb service 加 streaming coord 的 gRPC service。

- **选主**：一个 `MixCoordRole` etcd session 代表整个进程。`Register()` 里 `ProcessActiveStandBy(activateFunc)` **无条件启用** active-standby——部署多个 mixcoord 进程即天然主备，不看任何 `enableActiveStandby` 配置键；v3.0.1 里 `mixCoord.enableActiveStandby` 已无消费者，`rootCoord.enableActiveStandby` 同样没有读者、只是这个已死键的 FallbackKey（见 `pkg/util/paramtable/component_param.go` 的 `FallbackKeys`）。全仓唯一还读取 `enableActiveStandby` 的地方是 `queryCoord.enableActiveStandby`（`Params.QueryCoordCfg.EnableActiveStandby`），且只在 QueryCoord 以独立角色进程自建 session 的路径里生效，MixCoord 承载时因共享 session 而跳过。未选上的进程停在 `StateCode_StandBy`，注意 `/healthz` 把 StandBy 也判为健康，「ready」不等于「active」。
- **激活顺序**：抢到主后按 `streamingCoord.Start` → rootCoord Init+Start → `errgroup` 并行 Init+Start dataCoord 与 queryCoord。顺序有因果：DDL 与元数据变更要写 WAL，所以 streaming 必须先于 RootCoord；DataCoord 与 QueryCoord 彼此独立、只依赖 RootCoord 就绪。
- **共享 session 生命周期**：`initSession` 后把同一 session 注入三个子协调者并 `SetMixCoordMode(true)`，防止某个子协调者的 Stop 提前 cancel 掉整个 session；MixCoord 在全部子协调者停止后才真正停 session。子协调者自带的 `initSession` 因 session 非 nil 而整体跳过。

## Configuration System and Defaults

### Configuration Sources and Precedence

配置由 `pkg/config.Manager` 聚合四个来源，优先级从低到高：**yaml 文件**（`MILVUSCONF` 指定目录，默认 `./configs/milvus.yaml`）< **环境变量** < **etcd 动态覆盖**（键在 `<etcd.rootPath>/config/` 下，watch 同步）< **进程内 runtime overlay**（最高，如 `METRICS_PORT` 写入时的临时值）。环境变量匹配的写法比较宽松：键名会被小写并去掉 `.` `_` `/` 后比对，`ROOTCOORD_PORT`、`rootCoord.port` 与带 `MILVUS_CONF_` 前缀的形式都能命中同一配置项。动态改配置的正规入口是 MixCoord 的 `POST /management/config/alter`（批量、可 reset，落到 etcd 后全集群生效），配套 `GET /management/config/get` 查当前值。

### Hot Reload Versus Restart

源码里 `refreshable:"true/false"` 的 tag 只被文档生成工具 `cmd/tools/config/generate.go` 消费，**不产生运行时约束**；真正决定热不热的是消费方什么时候读值。已核实的谱系：`log.level` 有显式 Watch 回调即时生效、`trace.*` 前缀 watch 会重建 tracer、`quotaAndLimits.*` 各水位限值每轮 QuotaCenter 循环重读；反之 `quotaAndLimits.quotaCenterCollectInterval` 在主循环开始时读一次、端口与 gRPC buffer 尺寸建连时缓存、WAL 连接参数只在启动时用——都要重启。最特殊的是 `mq.type`：被标记 Immutable，协调者首次启动就把解析结果**创建式**钉进 etcd 且永不覆盖，之后改 yaml 无效——这是「实例出生后换 WAL 后端必须走迁移」的机制根源（参见 [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)）。

### Defaults Worth Memorizing

下表全部核对自 v3.0.1 的 `configs/milvus.yaml` 与 paramtable 注册代码（yaml 与代码默认值不一致处单独注明）：

| 配置键 | 默认值 | 说明 |
| --- | --- | --- |
| `mq.type` | `default` | 按形态优先级解析后钉进 etcd，不可热换 |
| `common.storageType` | `remote` | embedded/单机实操常用 `local`；`minio` 为废弃别名 |
| `etcd.use.embed` / `etcd.auth.enabled` | `false` / `true` | auth 默认开，用户名密码是占位的 `etcdadmin/etcdadmin`，生产必改 |
| `metastore.type` / `maxEtcdTxnNum` | `etcd` / `64` | 可切 `tikv`；单事务操作数上限 |
| `rootCoord.dmlChannelNum` | `16` | 初始 PChannel（DML channel）数，同时封顶单集合 shard 上限 |
| `rootCoord.maxPartitionNum` / `maxDatabaseNum` | `1024` / `64` | 元数据规模上限 |
| `proxy.maxShardNum` / `maxFieldNum` / `maxDimension` | `16` / `256` / `32768` | 建集合硬限制 |
| `dataCoord.segment.maxSize` / `sealProportion` | `1024` MB / `0.12` | 封口双条件：约 111~123 MB 起封（0.108~0.12 倍，jitter 向下浮动） |
| `dataCoord.segment.diskSegmentMaxSize` | `2048` MB | 磁盘索引集合的 segment 上限 |
| `streaming.flush.l0.maxRowNum` / `maxSize` / `maxLifetime` | `500000` / `32m` / `10m` | L0 删除段落盘阈值 |
| `dataCoord.gc.interval` / `dropTolerance` / `missingTolerance` | `3600s` / `10800s` / `86400s` | 对象存储回收节奏，详见 [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md) |
| `dataCoord.compaction.taskPrioritizer` / `clustering.autoEnable` | `level` / `false` | L0 → mix → clustering 队列优先；聚簇需手动或属性开启 |
| `quotaAndLimits.enabled` | yaml `true`（代码默认 `false`） | 以随包 yaml 为准；关掉后 QuotaCenter 不启动 |
| `quotaAndLimits.limitWriting.memProtection` | `true`，水位 `0.85/0.95` | 写限流最常见的默认触发源 |
| `common.security.authorizationEnabled` | `false` | RBAC 默认关，生产裸奔是默认状态 |
| `common.session.ttl` | `15`（秒） | 节点失联判定 |
| `proxy.slowQuerySpanInSeconds` / `accessLog.enable` | `1` / `false` | 慢查询阈值；访问日志默认不开 |
| `trace.exporter` / `sampleFraction` | `noop` / `0` | 分布式追踪默认全关 |

## WAL Backend Selection

### Selection Algorithm

`mq.type` 显式指定时直接采用（校验失败即 panic）；保持 `default` 时按「是否已配置该后端」推断——判据分别是 `rocksmq.path`、`pulsar.address`、`kafka.brokerList`、`woodpecker.meta.prefix` 非空，standalone 优先级 rocksmq > pulsar > kafka > woodpecker，cluster 优先级 pulsar > kafka > woodpecker。两条硬约束：RocksMQ 在 cluster 模式直接 panic；Woodpecker 配 `storage.type: local` 在 cluster 也 panic（本地盘不共享），除非显式 `forceLocalStorage`。随包 yaml 里 kafka 段整段注释、pulsar 有默认地址，因此 cluster 的 `default` 实际几乎总落在 Pulsar——yaml 注释明确建议**新实例显式写 `woodpecker`**。

### Backend Comparison

| 后端 | 部署拓扑 | 持久化路径 | 运维成本 | 适用 |
| --- | --- | --- | --- | --- |
| RocksMQ | 进程内 RocksDB | 本地盘；ack 后按 `retentionTimeInMinutes` 4320 / 8192 MB 清理，zstd compaction | 零，但单机不可横向扩展 | Standalone 默认、开发测试 |
| Pulsar | 独立集群（broker+bookkeeper） | broker→bookies；`maxMessageSize` 2 MB，`backlogAutoClearBytes` 防积压卡写 | 高：两套组件 + 多租户规划 | 存量集群（cluster 默认） |
| Kafka | 独立集群 | broker 日志；retention 需按 WAL 语义调（恢复要能回放） | 高：broker + controller + 客户端调参（producer 上限改动需重启） | 已有 Kafka 基建的存量集群 |
| Woodpecker Embed | 无额外组件，logstore 以库形式运行在 Milvus 进程内 | 内存攒批直写对象存储（`minio` 或 `local`）；fence 靠对象存储条件写 `conditionWrite: auto` | 最低：复用 etcd + 对象存储 | 单机与小集群；攒批窗口（sync 200 ms）换吞吐 |
| Woodpecker Service | 独立 LogStore 集群（quorum `replicas: 3|5`，节点按 `quorumBufferPools` 的 seeds 分组，`affinityMode: soft|hard` + 放置策略） | 写 LogStore 本地盘（低延迟）→ staged 上传对象存储；`retentionPolicy.ttl` 72h；`directRead` 从对象存储直读 sealed 段 | 中：多一组无状态化趋势的节点要运维 | v3.0 新路径，官方 yaml 注释推荐的新建默认 |

选型逻辑：先问能否接受外置 MQ 的运维（不能→Woodpecker）；再问延迟预算（高频小批量写要低 append 延迟→Service 模式，吞吐优先可攒批→Embed）；最后看扩缩容诉求——PChannel 与节点的再平衡由 StreamingCoord 负责，后端只决定写放大与故障域（机制细节归 [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)；Woodpecker 两模式的内部取舍见 [Woodpecker](/docs/CS/DB/Milvus/Woodpecker.md)）。

### MILVUS_STREAMING_SERVICE_ENABLED Is Always 1

`cmd/main.go` 在任何分支前调用 `streamingutil.SetStreamingServiceEnabled()` 把该 env 写死为 `1`，源码注释写明这是 2.6 后全量开启流式服务、等待清理所有 `IsStreamingServiceEnabled()` 调用点的过渡物。它现在**不是用户开关**：残余消费点集中在三处——QueryCoord 的 balance/assign/checker（决定 channel 以 StreamingCoord 的 PChannel 归属为准、识别 embedded-QN 标签）、rootcoord 的 2.x 遗留分支，以及 datacoord 与 flushcommon 里的旧落盘管路（`internal/datacoord/services.go` 的 flush 仍据此决定是否走 `SealAllSegments` 老路径、`internal/flushcommon` 的 writebuffer 与 flow-graph 节点据此选择落盘模型，正是 [Milvus](/docs/CS/DB/Milvus/Milvus.md) 枢纽页所说「两套落盘模型」的残骸所在）；`MustEnableStreamingService()` 仅用于「以 streamingnode 角色启动却绕过正常入口」的防御 panic。用户唯一能表达的意图是部署或省略 StreamingNode 角色。`cmd/embedded` 的 c-shared 导出不经过 `cmd/main.go`、不设置该 env，milvus-lite 的对应行为不由本仓库背书。

## Metadata KV and Object Storage

元数据 KV 装的内容：集合/分区/segment 索引等 meta（`metaSubPath`）、TSO 与时间戳（`kvSubPath`）、全部角色的 session 与选主 election、动态配置、以及 Woodpecker 的元数据（前缀 `woodpecker`）。**内嵌 etcd** 只适合单机（embedded/standalone_embed 形态），脚本给它显式设了 4 GiB backend quota 与 revision 型自动 compaction；数据量增长后需要按计划 compaction + defrag（见 References 的 etcd 运维文档），且它是元数据一致性与选主的单点。**外置 etcd** 用独立 3/5 节点集群，与 Milvus 生命周期解耦；多套 Milvus 共用一个 etcd 时必须错开 `etcd.rootPath` 与 `msgChannel.chanNamePrefix.cluster`。**TiKV**（`metastore.type: tikv`）解决的是「元数据规模需要横向扩展」：集合/segment 数量大到 etcd backend 吃紧时换它，注意服务发现与会话**仍然依赖 etcd**（yaml 注释明示），切换属于元数据迁移（`deployments/migrate-meta/`）。性能口径：etcd 请求超时 10s，慢 etcd 会直接拖住协调者调度循环与 Proxy 的缓存失效广播；`metastore.maxEtcdTxnNum: 64` 限制单事务批量。对象存储侧（MinIO/S3/GCS/OSS 或 local）是数据与索引的持久层，多实例共桶用 `minio.rootPath` / `localStorage.path` 前缀隔离；存储格式与三层模型见 [Storage Layer](/docs/CS/DB/Milvus/Storage_Layer.md)。

## Observability

### Metrics Healthz and Management Port

每个进程都起一个管理 HTTP 服务，默认 `:9091`（`METRICS_PORT` 可覆盖）：`/metrics` 输出 Milvus 自己的 registry（Go runtime 与业务指标隔离在 `/metrics_default`）、`/healthz` 汇总本进程全部角色的健康状态（StandBy 视为健康；协调者 standby 部署时探针不会误杀）、`/livez` 是零依赖的轻量存活探针（源码明确禁止在这里触碰 etcd/对象存储，专为 K8s liveness 设计，K8s 语义见 [K8s](/docs/CS/Container/k8s/K8s.md)）、`/log/level` 运行时读写日志级别、`/eventlog` 返回本进程 event 流 gRPC 端口、`/webui` 内嵌调试界面、pprof 默认开启。指标命名空间 `milvus`，按角色分 subsystem（`milvus_proxy_*`、`milvus_querycoord_*`、`milvus_datacoord_*`、streaming 的 WAL produce/consume 字节与时延、`pchannel_info` 等）；官方 Grafana dashboard JSON 在 `deployments/monitor/grafana/`。Grafana 面板之外，MixCoord 的 management 路由提供了运维动作面：GC 暂停/恢复、QueryCoord balance 暂停/恢复、配置 alter、WAL alter——排查与干预都在 9091 上。

### Logs Slow Query Tracing and EventLog

日志统一走 `mlog`，级别热调；Proxy 访问日志（`proxy.accessLog`，默认关，可按方法定制字段）与慢查询日志（阈值 `proxy.slowQuerySpanInSeconds` 默认 1s，Search 按 nq 摊薄计时）是请求级排障的两条线，慢查询同时进 WebUI 与指标。分布式追踪默认 `noop`+采样 0，配 `trace.exporter: otlp/jaeger` 后改配置即热重建 provider，segcore（C++）侧同步。EventLog（`pkg/eventlog`）是结构化事件通道：QueryCoord/QueryNode 把 collection、partition、segment 的加载进度事件记录到进程内 gRPC listener，外部工具 GET `/eventlog` 拿端口后 `Listen` 成流，适合观察「这个集合到底加载到哪了」。

### What to Look at When Debugging

一次写入变慢的排查路径应当是：先看 WAL 层——streaming 的 produce 时延与错误、`streaming.logging.appendSlowThreshold`（默认 1s，Woodpecker 下最低 3s）触发的慢 append 日志，判断是后端 MQ 抖还是 StreamingNode flush 不过来（`streaming.flush` 的水位指标与 growing 段字节）；再看配额层——Proxy 的限流计数与被拒错误码分布，确认不是 memProtection 水位把写入压低；读侧问题先看一致性等待（QueryNode tSafe / TimeTick 延迟）与 QueryCoord 的 task 积压、target checkpoint 推进；资源面盯 QueryNode/DataNode 内存水位（就是 QuotaCenter 做决策的那两个数）与对象存储用量（diskQuota 决策依据）；最后是元数据面——etcd 请求时延与 leader 切换事件，它异常时所有协调动作都会变得迟缓。命令与面板链接不在此展开，实操见 [Deploy](/docs/CS/DB/Milvus/Deploy.md)；定位到瓶颈之后的具体取舍面（每个旋钮的收益与代价）见 [Performance Tuning](/docs/CS/DB/Milvus/Performance_Tuning.md)。

## Quota and Rate Limiting

QuotaCenter 的代码在 `internal/rootcoord/quota_center.go`、运行于 MixCoord 进程，仅当 `quotaAndLimits.enabled=true` 时随 RootCoord 启动。主循环每 3s（`quotaCenterCollectInterval`）四步：从 QueryNode / DataNode / Proxy 拓扑**采集**真实负载指标 → 重建 cluster → database → collection → partition 四级限流树并计算各 RateType 速率 → **广播 SetRates 给所有 Proxy** → 记录指标。执行端在 Proxy 的 gRPC 拦截器：insert/delete 按请求字节数、search 按 nq、query 按 1 取 token，逐层扣减、失败回滚。

**写请求为什么被限**（这是最常见的一类用户投诉，答案基本都在默认开关里）：默认生效的保护是 memProtection——任一 QueryNode/DataNode 内存越过 0.85 低水位，DML 速率按 `(high-cur)/(high-low)` 线性衰减；越过 0.95 高水位则整体拒绝。StreamingNode 侧另有一道独立阀门 `streaming.walRateLimit.nodeMemory.*`（0.85 削速 / 0.90 硬拒 / 0.80 恢复），未导出到随包 yaml 但代码默认即生效——**硬拒早于 0.95**，排查「写入被拒」时两手都要看。diskProtection 默认开但 `diskQuota=-1`（无限），配了配额且超限会 force deny 写（delete 仍放行）；ttProtection（TimeTick 延迟超 `maxTimeTickDelay` 1200s 拒写）与 DML 吞吐上限、DDL/DQL QPS 限流默认**关**，要显式打开。错误语义：令牌不足返回 `ErrServiceRateLimit`（码 8，**可重试**，映射旧码 `RateLimit`），强制拒绝返回 `ErrServiceQuotaExceeded`（码 9，**不可重试**，附 QuotaState 原因）；REST v2 入口的限流拒绝则包装成业务码 1807 的响应——排障时看到的「429 式」被限，落到实处就是这几层错误码之一，SDK 重试策略应区分对待（merr 的分类、码区间与跨协议映射见 [Error Model](/docs/CS/DB/Milvus/Error_Model.md)）。所有水位与限值都可被 collection/database 属性覆盖（`database.diskQuota.mb`、`database.force.deny.writing` 等），这也是多租户配额的正确落点。

## High Availability and Replication

高可用是分层拼出来的：协调层靠 MixCoord active-standby（多进程抢同一 etcd 选主；接管方要走完整的激活初始化与元数据恢复，并非瞬时）；节点层无状态，session 租约 15s 失联即被剔除，StreamingCoord 把失去的 PChannel 恢复/迁移到其他 StreamingNode，WAL 的 Term 栅栏保证旧节点无法僵尸写入（机制见 [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)）；**replica 是读侧语义**——load 时的副本数决定同一份 sealed 数据铺在几组 QueryNode 上，副本 ≥2 分摊读 QPS 并在节点故障时保住可用性，但写入永远单点于 PChannel，replica 不提高写可用性；副本分布受 Resource Group 约束，RG 数量只能是 0、1 或等于副本数。`proxy.partialResultRequiredDataRatio` 默认 1，意为数据不全时宁可失败也不返回部分结果，想要降级读需显式调低。跨集群复制由独立的 CDC 角色承担（`milvus run cdc`）：主集群从 WAL 读消息推给从集群 Proxy 再落入从集群 WAL，从集群对 replication 拓扑的变更走 `AlterReplicateConfig` 广播；复制消息类型可用 `streaming.replication.skipMessageTypes` 屏蔽（默认含 RG DDL，从集群本地应用），复制中的集群默认禁用 import。复制一致性与切换流程见 [CDC and Replication](/docs/CS/DB/Milvus/CDC_and_Replication.md)。

## Multi-Tenancy Layers

四层各管一段，**事实所在组件不同**——这是排查「为什么隔离没生效」时最容易走错门的地方：

| 层 | 隔离什么 | 事实在哪个组件 | 关键入口 |
| --- | --- | --- | --- |
| Database | 元数据命名空间 + 库级配额与冻结 | RootCoord（DDL 经 WAL 广播）；配额决策在 QuotaCenter、执行在 Proxy | `maxDatabaseNum` 64；`database.diskQuota.mb` / `database.replica.number` / `database.force.deny.*` 属性 |
| RBAC | 谁能对什么做什么（身份与权限） | 用户/角色/授权存 RootCoord（`meta_rbac`、`ddl_callbacks_rbac_*`）；认证、特权校验、列表按 grant 过滤都在 Proxy | `common.security.authorizationEnabled` 默认 false、root 默认密码 `Milvus` 必须改 |
| Resource Group | 哪些 QueryNode 为某个集合服务（算力切分） | **QueryCoord**（`internal/querycoordv2/meta/`），RootCoord 只校验名字存在 | 声明式 `UpdateResourceGroups`（requests/limits 收敛）；一节点只属一组，默认组 `__default_resource_group` 不可删；session label `MILVUS_SERVER_LABEL_RESOURCE_GROUP` 钉组；StreamingNode 的 WAL 归属也可按 RG 隔离（`streaming.primaryResourceGroup`） |
| Partition Key | 集合内数据按 key 落分区、查询按 key 裁剪（数据切分） | schema 与 `partitionKeyIsolation` 校验在 Proxy；物理聚集靠 clustering compaction（见 [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)），段裁剪在 QueryNode | `common.usePartitionKeyAsClusteringKey`；隔离属性开启后跨 key 查询被拒 |

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)
- [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)
- [Deploy](/docs/CS/DB/Milvus/Deploy.md)
- [etcd](/docs/CS/Framework/etcd/README.md)
- [MQ](/docs/CS/MQ/MQ.md)

## References

- [Milvus v3.0.1 Release Notes](https://github.com/milvus-io/milvus/releases/tag/v3.0.1)
- [milvus.yaml Default Configuration](https://github.com/milvus-io/milvus/blob/master/configs/milvus.yaml)
- [standalone_embed.sh](https://github.com/milvus-io/milvus/blob/master/scripts/standalone_embed.sh)
- [milvus-lite](https://github.com/milvus-io/milvus-lite)
- [Woodpecker](https://github.com/zilliztech/woodpecker)
- [Woodpecker Documentation](https://zilliztech.github.io/woodpecker/docs.html)
- [etcd Maintenance and Defrag](https://etcd.io/docs/latest/op-guide/maintenance/)
- [Milvus Grafana Dashboard](https://github.com/milvus-io/milvus/blob/master/deployments/monitor/grafana/milvus-dashboard.json)
