## Introduction

InfluxDB 3 是 2024 年 GA 的重写版本，基线 **3.12.1**（2026-10-14），Rust 实现，底层全部基于 FDAP 栈：Apache **Flight**（数据传输与 FlightSQL）+ Apache **DataFusion**（向量化查询引擎）+ Apache **Arrow**（内存列式）+ Apache **Parquet**（持久化列式）。1.x/2.x 是 Go 写的旧版本，已进入维护期（只修 bug 不加新功能），新负载一律建在 3.x 上。

本页讲进程拓扑与写入链路：谁接收请求、数据在内存里怎么流动、什么时候落盘、挂掉会不会丢。存储格式与压缩见 [Storage_Engine](/docs/CS/DB/InfluxDB/Storage_Engine.md)，查询接口见 [Query](/docs/CS/DB/InfluxDB/Query.md)，库内计算见 [Processing_Engine](/docs/CS/DB/InfluxDB/Processing_Engine.md)。

## Product Lines

3.x 按部署形态分成五条产品线，共享同一个 v3 引擎：

| 产品线 | 形态 | 协议 | 定位 |
| :-- | :-- | :-- | :-- |
| **Core** | 单二进制 `influxdb3`，单节点 | MIT / Apache-2.0 双许可 | 免费开源，edge、开发测试、实时仪表盘 |
| **Enterprise** | 同一单二进制，单节点或多节点 | 商业（Trial / Home / Commercial license） | 生产自托管：HA、读副本、compaction、长期历史查询 |
| **Clustered** | Kubernetes 容器集合，Router / Ingester / Querier / Compactor 解耦 | 商业 | 大规模自托管，冷热分层 |
| **Cloud Serverless** | InfluxData 托管，多租户 | 商业 | 从 Cloud TSM 迁移过来的云用户 |
| **Cloud Dedicated** | InfluxData 托管，单租户 | 商业 | 托管单租户云 |

Enterprise 是 Core 的超集——Core 的每个 feature 和 bugfix 都自动进入 Enterprise，Enterprise 的发布说明只列独有变更。Core 单节点跑全部子进程；Enterprise 用 `--cluster-id` 把多个节点编成一个逻辑集群，共享同一个对象存储。Clustered 与 Enterprise 的区别是部署形态而非引擎：Clustered 把摄入层与查询层拆成独立容器，摄入数据先落在 hot 层即可查，冷数据自动 evict 到对象存储。

## Server Modes

`influxdb3 serve` 启动的进程内部再按 `--mode` 拆分子进程（逗号分隔多选）：

| mode | 子进程 | 职责 |
| :-- | :-- | :-- |
| `all` | 全部 | 默认值，Core 只能用这个 |
| `ingest` | 摄入 | 处理写入请求，buffer + WAL + snapshot |
| `query` | 查询 | 处理查询请求，读 buffer、cache 与对象存储 |
| `process` | Processing Engine | 执行 Python 插件 |
| `compact` | Compactor | 合并对象存储上的小文件成大文件 |

**一个集群里只能有一个节点跑 `compact` 模式**。典型生产拆分：两个节点跑 `ingest,query` 互为主备（都接写接查），一个节点跑 `compact`；读压力大时再加 `query` 节点做只读副本。默认 HTTP 端口 **8181**。

## Write Path

一个 point 从进来到持久化，经过四层，各层间隔都是出厂默认值而非调优值：

```
line protocol ──▶ validation ──▶ write buffer ──▶ WAL ──▶ Parquet snapshot ──▶ 对象存储
                   (拒绝畸形点)    (内存 Arrow)    (对象存储   (每 10 分钟       (S3 / GCS /
                                               上的小文件,   最旧的数据)        Azure / 本地盘)
                                                每秒 flush)
```

1. **Validation**：检查 line protocol 格式与 schema 兼容性。畸形点、重复 tag key（如 `m,t=a,t=a f=1i`）、超出 ns 上限（2262-04-11T23:39:59.999999999Z）的时间戳在入口处就被拒绝。
2. **Write buffer**：通过验证的点进入内存 write buffer，以 Arrow 格式按 builder 追加，**写入即可查**。
3. **WAL persistence**：write buffer 每秒 flush 一次到对象存储上的 WAL，服务器在 flush 完成后才 ack 写入——这是持久化点。延迟敏感的管线可以设 `no_sync=true` 在验证后立即 ack，代价是崩溃丢失最近一秒。queryable buffer 在内存里保留最多 **900 个 WAL 文件（约 15 分钟）** 供查询。
4. **Snapshot**：每 10 分钟，queryable buffer 里最旧的数据被持久化为 Parquet 文件写进对象存储，随后从 buffer 清除并写入内存 Parquet cache。snapshot 完成会删除已被覆盖的 WAL 文件并写 snapshot 清单文件，控制 WAL 体积。

一次写入大约 **1 秒内持久化、验证后立即可查**——这个间隔是"能监控的数据库"与"能对其自动化的数据库"的分界。

## Caches

查询最近数据时目标是**完全不碰对象存储**。3.x 为此做了四层缓存：

| 缓存 | 内容 | 暴露方式 |
| :-- | :-- | :--- |
| **queryable buffer** | 未 snapshot 的 Arrow 数据 | 查询引擎直接读 |
| **Parquet file cache** | 最近持久化的 Parquet 文件（`MemCachedObjectStore`） | 透明代理对象存储 |
| **Last Value Cache (LVC)** | 指定列层级上每个 key 的最近 N 个值 | DataFusion UDTF `last_cache` |
| **Distinct Value Cache (DVC)** | 指定列上的去重值集合 | DataFusion UDTF `distinct_cache` |

LVC 与 DVC 都在 **WAL flush 时同步填充**（默认每秒一次），因此数据一落 WAL 就进缓存。典型用法：LVC 配置 `site_name → machine_id → sensor_id` 层级，一个 SQL 就能取回某站点下所有传感器的最新读数，用于实时面板；DVC 支撑 UI 下拉框和探索式查询的标签值补全。两者都支持按 `max_age` 与 `max_cardinality` 淘汰。

**TableIndexCache** 是查询规划的辅助缓存：每张表的持久化 Parquet 文件清单由 `CoreTableIndex` 维护，LRU 缓存避免每次查询规划都去列对象存储目录。

## Ingester and Querier

Clustered 形态下写读彻底分离，但引擎相同：

- **Router**：接收入写请求，按标签过滤和路由表决定发给哪个 Ingester；查询侧拆分并分发给 Querier 聚合。
- **Ingester**：写入侧核心，职责就是上面 Write Path 的四层。它本身**无状态**——持久化数据全在对象存储，进程挂了用同一个 node identifier 重启就能从 WAL 恢复现场。
- **Querier**：查询侧核心，从各 Ingester 拉实时数据、从对象存储拉历史 Parquet，交给 DataFusion 向量化执行后合并。

Core 是这三者在单进程内的形态；Enterprise 多节点则是同一套子进程按节点粒度组合，节点间只通过共享对象存储交换数据。

## Links

- [InfluxDB 枢纽](/docs/CS/DB/InfluxDB.md)
- [Storage_Engine](/docs/CS/DB/InfluxDB/Storage_Engine.md)
- [Query](/docs/CS/DB/InfluxDB/Query.md)
- [Processing_Engine](/docs/CS/DB/InfluxDB/Processing_Engine.md)
- [Deployment](/docs/CS/DB/InfluxDB/Deployment.md)

## References

1. [InfluxDB 3 Enterprise Multi-Server Setup](https://docs.influxdata.com/influxdb3/enterprise/get-started/multi-server/)
2. [InfluxDB 3 Internals Reference](https://docs.influxdata.com/influxdb3/enterprise/reference/internals/)
3. [Which InfluxDB 3 should I use](https://docs.influxdata.com/influxdb3/which-influxdb-3/)
4. [InfluxDB 3 Open Source Public Alpha](https://www.influxdata.com/blog/influxdb3-open-source-public-alpha)
5. [InfluxDB 3 Core and Enterprise GA](https://www.influxdata.com/blog/influxdb-3-oss-ga)
