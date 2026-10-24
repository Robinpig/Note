## Introduction

TiDB 生态的工具可以按「集群生命周期」分成四段：部署运维（TiUP / TiDB Operator）、数据迁移（DM / Lightning / Dumpling）、持续同步（TiCDC）、备份恢复与诊断（BR / Dashboard / sync-diff-inspector）。理解它们分工的最快方式是记住：**哪些动的是逻辑数据，哪些动的是物理文件。**

## TiUP：部署与运维的统一入口

TiUP 是一个用 Go 写的组件管理器 + 集群运维工具，`tiup cluster` 子命令是生产部署的事实标准：

- `tiup playground`：单机一键起一个最小集群（开发调试）。
- `tiup cluster deploy` / `start` / `display` / `reload`：多机部署与滚动运维，拓扑写在 YAML 里。
- `tiup cluster scale-in/out`、`scale-out` 后 PD 自动把 Region 副本调度过去。
- `tiup cluster upgrade`：滚动升级，逐台停服、换二进制、拉起，其余节点继续服务。

TiUP 本身也是一个「组件仓库」——`tiup install br tidb-lightning tikv` 可以拉取各组件的对应版本二进制，版本与集群绑定。生产上常与 TiDB Operator（K8s）二选一，二者不是叠加关系。

## BR：物理备份与恢复

BR（Backup & Restore）是**物理备份**工具，直接读 TiKV 的 SST 文件并记录备份时刻的 TS 与 MVCC 版本：

- `br backup full`：全量快照备份，输出到共享存储（S3 / NFS / GCS）。
- `br backup log` + `restore point`：日志备份实现 **PITR（时间点恢复）**，恢复到任意秒级时间点。
- 恢复是「物理重放」：把 SST 写回新集群的 TiKV，速度快、不走 SQL 层，适合大集群。
- 与逻辑备份（Dumpling/mydumper 出的 SQL）相比：BR 快且保一致性，但恢复目标必须是全新集群；逻辑备份慢但可跨引擎、可挑选库表。

## Lightning：本地高速导入

TiDB Lightning 解决「把大量外部数据快速灌进 TiDB」：

- **local 模式**（v8.5 主流）：先在自己的节点排序、生成 SST，再通过 `ingest` 接口直接写 TiKV 的 RocksDB。绕开 SQL 层，单机可达 TiB/小时级，且对在线集群影响小。
- **backend 模式**：老模式，走 SQL 层 `load data`，速度慢、对集群冲击大，v8.5 已不推荐。
- **冲突检测**：`conflict.strategy` 处理唯一键冲突（`error` / `replace` / `ignore`），导入前可用 `checksum` 校验源与目标一致性。
- 常与 Dumpling 配对使用：Dumpling 从 MySQL 导出，Lightning 导入 TiDB。

## DM：MySQL/MariaDB → TiDB 迁移

DM（Data Migration）面向**存量 MySQL 库迁到 TiDB**的全链路场景：

- 全量阶段：Dumpling 导出 + Lightning 导入。
- 增量阶段：DM 伪装成 MySQL slave 拉 binlog，解析成行事件应用到 TiDB。
- **shard 合并**：上游分库分表的多张表可以合并成 TiDB 单表，DM 处理分片间 DDL 的协调与一致性（悲观/乐观模式）。
- 同步进度以 `relay` + checkpoint 形式持久化，断点续传。

DM 是「迁移一次性完成」的工具，适合割接场景；长期的增量分发用 TiCDC。

## TiCDC：增量同步与 changefeed

TiCDC 通过 TiKV 的 CDC 接口（基于 Raft log 的增量 KV 变化）构建 **changefeed**，把变更以行事件的形式流式分发到下游：

- **下游类型**：TiDB、MySQL、Kafka、Pulsar、对象存储、Webhook。Kafka 分发时可配 canal / open-protocol / Maxwell 等协议格式。
- **架构演进**：v8.5 的 TiCDC 仍是「一个 changefeed 一个 owner 拉取 + 多 sorter 分发」的结构；从 v9 起官方提出了同步能力接近线性扩展的新架构（多 owner/分布式调度方向），开源版本尚未 GA。
- **与 DM 的分界**：DM 管「迁过来」，TiCDC 管「持续同步、多活、旁路数仓」。
- TiCDC 同时取代了历史上 `tidb-binlog`（pump + drainer）的角色——pump/drainer 自 v4.0.2 起废弃、v5.x 已不推荐使用，新方案一律走 TiCDC。

## 其他

- **Dumpling**：逻辑导出工具，从 MySQL/TiDB 导出 SQL 或 CSV，配合 Lightning 使用。
- **TiDB Dashboard**：集群 Web 控制台，看慢查询、拓扑、流量、Key 热力图、诊断报告。
- **sync-diff-inspector**：校验两库数据一致性（迁移/同步后的对账）。
- **TiDB Operator**：K8s 上的 Operator，以 CRD（TidbCluster）管理集群，适合云原生环境；与 TiUP 是两种部署路径，不叠加。

## 工具之间的替代关系（容易搞混的点）

| 已废弃 | 替代者 |
| --- | --- |
| `mydumper` / `loader` | Dumpling + Lightning（或 DM 全量阶段） |
| `syncer` | DM（增量） |
| `tidb-binlog`（pump + drainer） | TiCDC |

## Links

- [TiDB 整体架构](/docs/CS/DB/TiDB/Architecture.md)
- [PD](/docs/CS/DB/TiDB/PD.md)
- [TiKV 存储引擎](/docs/CS/DB/TiDB/TiKV.md)

## References

- https://docs.pingcap.com/zh/tidb/v8.5/tiup-overview/
- https://docs.pingcap.com/zh/tidb/v8.5/backup-and-restore-overview/
- https://docs.pingcap.com/zh/tidb/v8.5/tidb-lightning-overview/
- https://docs.pingcap.com/zh/tidb/v8.5/dm-overview/
- https://docs.pingcap.com/zh/tidb/v8.5/ticdc-overview/
