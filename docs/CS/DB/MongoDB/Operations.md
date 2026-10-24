## Introduction

MongoDB 的日常运维围绕四件事：**部署与配置、监控与排障、备份与恢复、升级与变更**。它没有传统关系库那么多需要手工调优的参数，但"缓存与工作集、oplog 窗口、索引与分片键"这三处一旦失配，问题往往以延迟抖动、复制延迟或磁盘打满的形式出现。

## Deployment Baseline

| 场景 | 形态 | 最低建议 |
| :--- | :--- | :--- |
| 本地开发 | standalone | 单进程、无鉴权（仅本机） |
| 生产 | replica set | 3 个数据节点，跨机架/可用区 |
| 大数据量 | sharded cluster | 每 shard 一个副本集 + 3 个 config server（或 config shard） |

关键配置：

| 配置 | 说明 |
| :--- | :--- |
| `storage.wiredTiger.engineConfig.cacheSizeGB` | WT 缓存；容器内必须显式设置 |
| `replication.oplogSizeMB` | oplog 大小；决定断线容忍窗口 |
| `net.maxIncomingConnections` | 最大连接数，默认 65536 |
| `net.bindIp` | 监听地址，生产不要 `0.0.0.0` 裸奔 |
| `security.authorization: enabled` | 开启鉴权 |
| `operationProfiling.slowms` | 慢查询阈值，默认 100ms |

启动参数集中在 `/etc/mongod.conf`（YAML），`mongosh` 连接后用 `db.adminCommand({ getCmdLineOpts: 1 })` 可核对生效配置。

## Monitoring

| 工具 | 用途 |
| :--- | :--- |
| `db.serverStatus()` | 全量运行指标：连接、锁、缓存、复制、游标 |
| `mongostat` | 每秒操作数、脏页、连接、复制延迟 |
| `mongotop` | 按集合统计读写耗时 |
| FTDC（`diagnostic.data/`） | 每秒采集的时序诊断数据，排障首选 |
| `db.currentOp()` / `db.killOp()` | 查看/终止长操作 |
| profiler | 记录慢查询与执行计划，级别 0/1/2 |
| 日志 | 结构化日志（8.0 起支持 OCSF schema） |

重点指标：

- **连接数**：接近上限会出现连接拒绝；连接风暴常来自驱动未复用连接池。
- **WT 缓存**：`wiredTiger.cache.bytes currently in the cache` 与淘汰/脏页比例；应用线程参与淘汰时延迟上升。
- **队列**：`globalLock.currentQueue`、`queues.execution`。
- **复制延迟**：`rs.printSecondaryReplicationInfo()`、`replSetGetStatus` 的 `optimeDate`。
- **oplog 窗口**：`rs.printReplicationInfo()`；窗口小于业务断线容忍时间就要扩容。
- **磁盘**：数据 + journal + 索引构建临时空间；磁盘满会让写入直接失败。

```javascript
// 打开 profiler 记录超过 200ms 的操作
db.setProfilingLevel(1, { slowms: 200 })
db.system.profile.find().sort({ ts: -1 }).limit(5)
```

## Backup and Restore

| 方式 | 一致性 | 适用 |
| :--- | :--- | :--- |
| `mongodump` / `mongorestore` | 逻辑备份；副本集加 `--oplog` 可一致 | 中小数据量、跨版本迁移 |
| 文件系统快照 | 物理备份，需 dbPath 与 journal 同卷、快照时 fsync 锁 | 大数据量、快速恢复 |
| PITR（oplog 重放） | 恢复到任意时间点 | 企业版 / Atlas |
| `mongosync` | 在线迁移/双写同步 | 集群迁移、上云 |

```bash
# 副本集一致性逻辑备份
mongodump --uri="mongodb://rs0/host1,host2/?replicaSet=rs0" --oplog --out=/backup/2026-10-23
mongorestore --uri="mongodb://..." --oplogReplay /backup/2026-10-23
```

备份的三条铁律：**备份要在 secondary 上做**（避免影响主库）、**必须定期演练恢复**、**恢复后的 oplog/Change Streams 起点要重新评估**。8.0 起支持对分片集群做自管理备份。

## Maintenance

**索引**

- 大集合建索引放在低峰期；8.0 优化了构建流程，但仍会占用 IO 与磁盘。
- 先在隐藏索引上验证，再转正；删除前用 `$indexStats` 确认无人使用。

**空间回收**

- 删除大量文档不会自动把空间还给操作系统；`compact` 可重写数据文件，但会阻塞该集合（8.0 支持后台压缩与 `dryRun`）。
- 分片集群的 `compact` 需要逐 shard 执行。

**校验**

```javascript
db.runCommand({ validate: "orders", full: true })
```

**升级**

1. 先备份并确认 oplog 窗口足够；
2. 滚动升级二进制：先 secondary，再 stepdown primary，最后升级原 primary；
3. 所有节点二进制一致后，再 `setFeatureCompatibilityVersion` 升 FCV；
4. 8.2 起 Minor Release 必须逐版本升级（8.1 → 8.2 → 8.3），不能跳版；Major 之间可先降回上一 Major 再升。

## Capacity and Sizing

- **内存**：让 WT 缓存 + 文件系统缓存覆盖**工作集**（热数据与热索引），而不是全量数据。
- **磁盘**：按压缩后的数据量估算，再预留 journal、oplog、索引构建与 compaction 的峰值空间。
- **IOPS**：写入放大来自 journal + checkpoint + oplog + 索引；随机写能力比顺序吞吐更关键。
- **连接**：按应用实例数 × 连接池大小估算，并留出运维连接余量。

## Troubleshooting

| 症状 | 优先排查 |
| :--- | :--- |
| 查询变慢、CPU 高 | 慢查询日志 → `explain` → 是否 COLLSCAN / SORT / 索引选择性差 |
| 写入延迟抖动 | WT 缓存淘汰、checkpoint、磁盘 IO、是否有大文档/无界数组 |
| 复制延迟 | 从节点 IO/CPU、oplog 应用瓶颈、网络、大事务 |
| 连接被打满 | 驱动连接池配置、慢查询占住连接、是否缺少 `maxTimeMS` |
| 分片不均衡 | shard key 热点、jumbo chunk、balancer 窗口 |
| 磁盘快速增长 | oplog 过大、TTL 未生效、索引冗余、删除后未 compact |

## Links

- [MongoDB](/docs/CS/DB/MongoDB.md)
- [Replication](/docs/CS/DB/MongoDB/Replication.md)
- [Sharding](/docs/CS/DB/MongoDB/Sharding.md)
- [Storage Engine](/docs/CS/DB/MongoDB/StorageEngine.md)
- [Index](/docs/CS/DB/MongoDB/Index.md)
- [Security](/docs/CS/DB/MongoDB/Security.md)

## References

- [MongoDB Production Notes](https://www.mongodb.com/docs/manual/administration/production-notes/)
- [Monitoring for Self-Managed Deployments](https://www.mongodb.com/docs/manual/administration/monitoring/)
- [Back Up and Restore with MongoDB Tools](https://www.mongodb.com/docs/manual/tutorial/back-up-and-restore-with-mongodb-tools/)
- [Upgrade MongoDB](https://www.mongodb.com/docs/manual/release-notes/8.0-upgrade-standalone/)
