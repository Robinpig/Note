## Introduction

[Grafana Mimir](https://grafana.com/oss/mimir/) 是 Grafana Labs 开源的**水平可扩展、高可用、多租户的 Prometheus 长期存储（long-term TSDB）**。它是 Grafana LGTM 栈里的 **M**（Metrics），与 [Loki](/docs/CS/Distributed/Tracing/Loki.md)、[Tempo](/docs/CS/Distributed/Tracing/Tempo.md)、[Grafana](/docs/CS/Distributed/Tracing/Grafana.md) 一道覆盖可观测性三支柱。

一句话定位：Mimir 把 [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md) 的 remote_write 协议接进来，用**对象存储里的 Prometheus TSDB block** 做无限期、低成本的长期存储，同时对外暴露与原生 Prometheus 完全兼容的查询 API（PromQL / Query API）。它源自 Cortex 项目（2022 年 fork），但今天的存储模型已经是「原生 Prometheus TSDB block + 对象存储」，而非 Cortex 早期的 chunk+index 分离模型。

> [!NOTE]
> 本页为**源码级**笔记，关键结论已对照 **Mimir `mimir-3.2.5`**（tag `mimir-3.2.5`，浅克隆于 `mimir-3.2.5/`）逐条核实。下面讲解直接贴真实源码片段，路径相对仓库根，不再标注行号。Ring 实现位于 vendored `dskit`，路径以 `vendor/github.com/grafana/dskit/...` 表示。

## Components / Targets

Mimir 沿用 Cortex 的「模块（module）」装配机制：每个 `-target` 名对应一个可独立部署的组件。全部 target 名称定义为常量（见 `pkg/mimir/modules.go`，含 `Distributor`/`Ingester`/`Querier`/`QueryFrontend`/`QueryScheduler`/`StoreGateway`/`Ruler`/`Compactor`/`AlertManager`），而 `All` 虚拟目标的依赖表也定义在 `pkg/mimir/modules.go`，直接列出了九个核心组件。二进制入口在 `cmd/mimir/main.go`，装配应用后启动：

```go
// cmd/mimir/main.go
t, err := mimir.New(cfg, reg)
util_log.CheckFatal("initializing application", err)
// ...
err = t.Run()
```

| target | 角色 |
| --- | --- |
| Distributor | 接收 remote_write，按一致性哈希分发给 ingester，施加复制因子 |
| Ingester | 在内存中维护每租户 Prometheus TSDB head + WAL，flush 成 block 上传对象存储 |
| Query Frontend | 查询入口，按时间区间切分（split-by-interval）+ 结果缓存 |
| Query Scheduler | 每租户的查询队列，保证租户间公平 |
| Querier | 执行 PromQL：合并 ingester（近期）与 store-gateway（历史 block） |
| Store Gateway | 从对象存储加载已 flush 的 block，服务历史数据查询 |
| Compactor | block 压缩 + 租户级保留（retention） |
| Ruler | 评估 recording/alerting rule（Prometheus rule 语义） |
| Alertmanager | 告警分发 |

## Write Path

```
Prometheus / Agent / OTel Collector
        │  remote_write (Prometheus protobuf)
        ▼
  Distributor  (pkg/distributor/distributor.go — Push)
        │  tokenForLabels → ring 一致性哈希
        │  ring.DoBatchWithOptions (subring) 复制转发
        ▼
  Ingester   (pkg/ingester/ingester.go — struct)
        │  每租户 TSDB head + WAL (ingester_tsdb.go — createTSDB / tsdb.Open)
        │  flush → shipper.Sync 上传 block
        ▼
  ┌─────────────────────────────────────────┐
  │  对象存储 (S3/GCS/Azure) 里的 TSDB block  │
  └─────────────────────────────────────────┘
```

- **入口**：`pkg/api/api.go` 的 `RegisterDistributor` 把 HTTP 路由 `/api/v1/push` 注册到 `distributor.Handler`；`pkg/distributor/distributor.go` 的 `Push` 是写入请求的处理函数：

```go
// pkg/api/api.go — RegisterDistributor
a.RegisterRoute(PrometheusPushEndpoint, distributor.Handler(
    pushConfig.MaxRecvMsgSize, newRequestBuffers, a.sourceIPs, a.cfg.SkipLabelNameValidationHeader,
    a.cfg.SkipLabelCountValidationHeader, limits, pushConfig.RetryConfig, d.PushWithMiddlewares, d.PushMetrics, a.logger,
), true, false, "POST")
```

```go
// pkg/distributor/distributor.go — Push
// Push is gRPC method registered as client.IngesterServer and distributor.DistributorServer.
func (d *Distributor) Push(ctx context.Context, req *mimirpb.WriteRequest) (*mimirpb.WriteResponse, error) {
    pushReq := NewParsedRequest(req, req.Size())
    pushReq.AddCleanup(func() {
        req.FreeBuffer()
        mimirpb.ReuseSlice(req.Timeseries)
    })

    pushErr := d.PushWithMiddlewares(ctx, pushReq)
    if pushErr == nil {
        return &mimirpb.WriteResponse{}, nil
    }
    handledErr := d.handlePushError(pushErr)
    return nil, handledErr
}
```

- **分片与复制**：`tokenForLabels` 对 `tenantID + labels` 计算 32 位一致性哈希 token；`push` 内部构造 `ingestersSubring`（`ring.DoBatchRing`），再由 ring 的 `DoBatchWithOptions` 按 token 批量转发并施加复制因子：

```go
// pkg/distributor/distributor.go
func tokenForLabels(userID string, labels []mimirpb.LabelAdapter) uint32 {
    return mimirpb.ShardByAllLabelAdapters(userID, labels)
}
```

```go
// pkg/distributor/distributor.go — push
var (
    ingestersSubring  ring.DoBatchRing
    partitionSubrings []*ring.ActivePartitionBatchRing
)
// ...
if !d.cfg.IngestStorageConfig.Enabled || d.cfg.IngestStorageConfig.Migration.DistributorSendToIngestersEnabled {
    // 用 ingestersSubring 做 DoBatchWithOptions 按 token 复制转发
}
```

- **Ingester 落盘**：`type Ingester struct`（`pkg/ingester/ingester.go`）持有每租户 TSDB。`createTSDB`（`pkg/ingester/ingester_tsdb.go`）为每租户建 TSDB 并配置 WAL，`tsdb.Open`（直接 import `prometheus/prometheus/tsdb`）打开/恢复。flush 时通过 `userDB.shipper.Sync(ctx)`（`pkg/ingester/ingester_compaction.go`）把 block 同步上传到对象存储：

```go
// pkg/ingester/ingester_tsdb.go — createTSDB
func (i *Ingester) createTSDB(userID string, walReplayConcurrency int) (*userTSDB, error) {
    tsdbPromReg := prometheus.NewRegistry()
    udir := i.cfg.BlocksStorageConfig.TSDB.BlocksDir(userID)
    // ...
    db, err := tsdb.Open(udir, util_log.SlogFromGoKit(userLogger), tsdbPromReg, &tsdb.Options{
        RetentionDuration: i.cfg.BlocksStorageConfig.TSDB.Retention.Milliseconds(),
        // ...
        WALReplayConcurrency: walReplayConcurrency,
        // ...
    })
    // ...
}
```

```go
// pkg/ingester/ingester_compaction.go — flush 时上传 block
uploaded, err := userDB.shipper.Sync(ctx)
```

## Read Path

```
Grafana / PromQL client
        ▼
  Query Frontend  (split_and_cache.go — splitRequestByInterval)
        │  按 interval 切分 + 结果缓存
        ▼
  Query Scheduler  (每租户公平队列)
        ▼
  Querier  (pkg/querier/querier.go — newMultiQueryable)
        ├── DistributorQueryable  → ingester（近期、未 flush 的数据）
        └── StoreQueryable        → Store Gateway（历史 block）
                                        │
                                        ▼
                                  对象存储里的 TSDB block
```

- **切分**：`splitAndCacheMiddleware`（`pkg/frontend/querymiddleware/split_and_cache.go`）做按区间切分 + 缓存；`splitRequestByInterval` 按配置间隔把大查询切成小查询，结果合并后返回：

```go
// pkg/frontend/querymiddleware/split_and_cache.go
// splitRequestByInterval splits the given MetricsQueryRequest by configured interval.
func (s *splitAndCacheMiddleware) splitRequestByInterval(req MetricsQueryRequest) (splitRequests, error) {
    if !s.splitEnabled {
        return splitRequests{{orig: req}}, nil
    }

    splitReqs, err := splitQueryByInterval(req, s.splitInterval)
    if err != nil {
        return nil, err
    }
    // ...
    return out, nil
}
```

- **合并双数据源**：`pkg/querier/querier.go` 用 `newMultiQueryable(cfg, distributorQueryable, storeQueryable, ...)` 同时查询 ingesters（近期）与 store-gateway（历史）：

```go
// pkg/querier/querier.go
exemplarQueryable := newDistributorExemplarQueryable(distributor, logger)
distributorQueryable := NewDistributorQueryable(distributor, limits, queryMetrics, logger)
queryable := newMultiQueryable(cfg, distributorQueryable, storeQueryable, limits, queryMetrics, logger)
```

## Ring / Sharding / Replication

Mimir 的分片与复制由 vendored `dskit` 的一致性哈希环承担（**不在 `pkg/ring`**）：每个实例持有排序后的 token 区间（`model.go` 的 `InstanceDesc.Tokens`）实现分片；`Ring.Get` 按 key 选出复制集合；`ReplicationFactor` 默认 3。读写都先算 token 再在环上定位目标 ingester 副本集：

```go
// vendor/github.com/grafana/dskit/ring/ring.go
// Ring is a Service that maintains an in-memory copy of a ring and watches for changes.
type Ring struct {
    services.Service

    key      string
    cfg      Config
    KVClient kv.Client
    strategy ReplicationStrategy
    // ...
}
```

```go
// vendor/github.com/grafana/dskit/ring/ring.go
// Get returns n (or more) instances which form the replicas for the given key.
func (r *Ring) Get(key uint32, op Operation, bufDescs []InstanceDesc, bufHosts, _ []string) (ReplicationSet, error) {
    return r.getReplicationSetForKey(key, op, bufDescs, bufHosts, r.cfg.ReplicationFactor)
}
```

```go
// vendor/github.com/grafana/dskit/ring/ring.go — ReplicationFactor 默认 3
f.IntVar(&cfg.ReplicationFactor, prefix+"distributor.replication-factor", 3, "The number of ingesters to write to and read from.")
```

```go
// vendor/github.com/grafana/dskit/ring/model.go — 实例持有自己的 token 区间
ingester := InstanceDesc{
    Id:     id,
    Addr:   addr,
    State:  state,
    Tokens: tokens, // 排序后的 token 区间，用于分片
    Zone:   zone,
    // ...
}
```

## Storage: Prometheus TSDB Blocks in Object Storage

Mimir 的核心存储选择是**把原生 Prometheus TSDB block 直接存进对象存储**（S3 / GCS / Azure / Swift / filesystem），而不是 Cortex 早期的 chunk+index 分离格式：

- `pkg/ingester/ingester_tsdb.go` 的 `tsdb.Open(...)`（见上文）直接使用 Prometheus TSDB，证明 block 格式与开源 Prometheus 一致。
- 后端分发点在 `pkg/storage/bucket/client.go`，按 `cfg.Backend` 分流到 S3/GCS/Azure 各自的 `NewBucketClient`（`pkg/storage/bucket/{s3,gcs,azure}/`）：

```go
// pkg/storage/bucket/client.go
func (cfg *StorageBackendConfig) Validate() error {
    if !slices.Contains(cfg.supportedBackends(), cfg.Backend) {
        return ErrUnsupportedStorageBackend
    }

    if cfg.Backend == S3 {
        if err := cfg.S3.Validate(); err != nil {
            return err
        }
    }
    return nil
}
```

- Mimir 在 Prometheus block 之上扩展了一个 `index-header` 文件（`pkg/storage/tsdb/block/block.go` 的 `IndexHeaderFilename` / `SparseIndexHeaderFilename`），供 store-gateway 快速定位 block 内的 series，而不必每次全量读 index：

```go
// pkg/storage/tsdb/block/block.go
const (
    // IndexHeaderFilename is the canonical name for binary index header file that stores essential information.
    IndexHeaderFilename = "index-header"
    // SparseIndexHeaderFilename is the canonical name for sparse index header file that stores abbreviated slices of index-header.
    SparseIndexHeaderFilename = "sparse-index-header"
    // ...
)
```

这一选择带来的好处：block 是不可变、自描述的，天然适配对象存储的最终一致性；压缩（compaction）与保留（retention）都是对象存储上的 block 级操作。

## Compactor

`type MultitenantCompactor struct`（`pkg/compactor/compactor.go`，注释明确「multi-tenant TSDB block compactor based on Thanos」），`running` 主循环（内部 `compactUsers`）在对象存储上合并 block（降采样/合并）、执行租户级保留（`CompactorBlocksRetentionPeriod`，定义在 `ConfigProvider` 接口上）：

```go
// pkg/compactor/compactor.go
// MultitenantCompactor is a multi-tenant TSDB block compactor based on Thanos.
type MultitenantCompactor struct {
    services.Service

    compactorCfg Config
    storageCfg   mimir_tsdb.BlocksStorageConfig
    cfgProvider  ConfigProvider
    logger       log.Logger
    // ...
}
```

```go
// pkg/compactor/compactor.go
func (c *MultitenantCompactor) running(ctx context.Context) error {
    return c.executor.run(ctx, c)
}

// ConfigProvider 上的租户级保留接口
type ConfigProvider interface {
    bucket.TenantConfigProvider
    // CompactorBlocksRetentionPeriod returns the retention period for a given user.
    CompactorBlocksRetentionPeriod(user string) time.Duration
    // ...
}
```

Compactor 与 Store Gateway 配合，保证历史 block 既被压缩又被按需回收。

## Mimir vs Prometheus / Cortex / Thanos

| 维度 | Prometheus（单机） | Mimir | Cortex（前身） | Thanos |
| --- | --- | --- | --- | --- |
| 存储 | 本地 TSDB | 对象存储 TSDB block | 早期 chunk+index，后亦迁 TSDB | 对象存储 block |
| 长期存储 | 受限（本地盘） | 原生支持、无限期 | 支持 | 支持 |
| 分片/复制 | 无（HA 靠两份） | ring 一致性哈希 + RF3 | ring | sidecar + 查询层 |
| 写入模型 | 本地 scrape | remote_write 接入 | remote_write | sidecar 转发 |
| 查询兼容 | PromQL | PromQL / Query API 兼容 | PromQL 兼容 | PromQL 兼容 |

Mimir 的独特点是「完全兼容 Prometheus 语义 + 对象存储长期化 + 工业级多租户与限流」，代价是组件数与运维面（ring、store-gateway、compactor 都要管）。它适合「已有 Prometheus，但要突破单机存储上限、做多租户/长期保留」的团队。

## 关键源码文件

想继续深挖，按下面路径直接打开仓库即可（相对 `grafana/mimir` 根，不再标注行号）：

- **启动装配 / 模块**：`cmd/mimir/main.go`、`pkg/mimir/modules.go`
- **写入路径**：`pkg/api/api.go`、`pkg/distributor/distributor.go`、`pkg/ingester/ingester.go`、`pkg/ingester/ingester_tsdb.go`、`pkg/ingester/ingester_compaction.go`
- **读取路径**：`pkg/frontend/querymiddleware/split_and_cache.go`、`pkg/querier/querier.go`
- **分片 / 复制（vendored dskit）**：`vendor/github.com/grafana/dskit/ring/ring.go`、`vendor/github.com/grafana/dskit/ring/model.go`
- **对象存储**：`pkg/storage/bucket/client.go`、`pkg/storage/tsdb/block/block.go`、`pkg/storage/bucket/{s3,gcs,azure}/`
- **压缩**：`pkg/compactor/compactor.go`

## Links

- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md) — Mimir 完全兼容的指标体系事实标准
- [Loki](/docs/CS/Distributed/Tracing/Loki.md) — LGTM 栈的 L（日志），同源对象存储思路
- [Tempo](/docs/CS/Distributed/Tracing/Tempo.md) — LGTM 栈的 T（追踪），Parquet block + 对象存储
- [Grafana](/docs/CS/Distributed/Tracing/Grafana.md) — LGTM 枢纽，把三支柱关联进同一视图
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) — Mimir 也可作为 OTel Metrics 的后端

## References

- Grafana Mimir documentation：https://grafana.com/docs/mimir/latest/
- Mimir architecture：https://grafana.com/docs/mimir/latest/references/architecture/
- Prometheus TSDB：https://prometheus.io/docs/prometheus/latest/storage/
- dskit ring（一致性哈希环实现）：https://github.com/grafana/dskit/tree/main/ring
