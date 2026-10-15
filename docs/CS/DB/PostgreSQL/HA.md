## Introduction

PostgreSQL 的高可用围绕流复制 + 自动 failover 构建，连接池与监控是生产稳定的另外两根支柱。本文覆盖 Patroni/repmgr 高可用方案、pgbouncer 三种池化模式、关键监控指标与连接风暴处理。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18 |
| 核实日期 | 2026-10-15 |

## High Availability Stack

典型 HA 拓扑：多个 PG 实例（一主多备，基于 [物理流复制](/docs/CS/DB/PostgreSQL/Replication.md)）+ DCS（分布式协调服务）+ 管理组件（Patroni/repmgr）+ 负载层（HAProxy/pgpool-II/pgbouncer）。

### Patroni

Patroni 是社区主流的 HA 模板，用 **DCS**（etcd / Consul / ZooKeeper / Kubernetes / 内置 raft）做领导者选举与配置存储：

- 每个节点跑一个 Patroni agent，监控本地 PG 健康并写入 DCS
- 主库故障时，DCS 选举出新的主，Patroni 执行 promote
- 配合 `watchdog` 防止脑裂（fencing）
- 客户端通过 HAProxy / 服务发现获取当前主端点

### repmgr

repmgr 是更轻量的流复制管理工具，自带 `repmgrd` 守护进程做自动 failover 与节点管理（`repmgr cluster` 命令族），配置比 Patroni 简单，但需额外机制（如 `repmgrd` + 外部 VIP）补全 DCS 选举。

> [!NOTE]
>
> 无论哪种方案，failover 都依赖 [复制槽](/docs/CS/DB/PostgreSQL/Replication.md) 不丢 WAL、且应用端能透明切换主端点（连接串 / 服务发现）。

## Connection Pooling (pgbouncer)

PostgreSQL 是 one-process-per-connection 模型，连接数过高时 backend 私有内存（relcache/syscache/MemoryContext）线性膨胀。pgbouncer 在应用与 PG 间做池化，三种模式：

| 模式 | 语义 | 适用 |
| :--- | :--- | :--- |
| session | 连接绑定到会话结束 | 默认；支持所有特性（session 级临时表、预备语句） |
| transaction | 连接按事务借用/归还 | 多数 OLTP，连接复用率最高 |
| statement | 每条语句后归还 | 短查询且不支持多语句事务，少用 |

> [!WARNING]
>
> `transaction` / `statement` 模式下，session 级状态（临时表、`SET`、预备语句、`LISTEN`）不可跨事务复用——应用若依赖这些会出错。务必先在预发验证。

## Monitoring

| 指标 | 来源 | 告警含义 |
| :--- | :--- | :--- |
| 复制延迟 | `pg_stat_replication.replay_lag` | 备库落后主库，RPO 风险 |
| 未消费 WAL | `pg_replication_slots.confirmed_flush_lsn` vs `pg_current_wal_lsn()` | 复制槽堆积撑爆 `pg_wal` |
| 表膨胀 | `pg_stat_user_tables.n_dead_tup` | autovacuum 落后 |
| 连接数 | `pg_stat_activity` / `pgbouncer` | 接近 `max_connections` 或 client 等待 |
| 锁等待 | `pg_locks` + `pg_stat_activity` | 长事务阻塞 |
| XID 年龄 | `age(relfrozenxid)` | 逼近回绕（见 [MVCC](/docs/CS/DB/PostgreSQL/MVCC.md)） |

## Connection Storm

连接风暴（大量客户端瞬间建连）会拖垮 PG：每个 backend 都有私有内存与启动开销。应对：

- 前端强制池化（pgbouncer `transaction` 模式）
- 合理设 `max_connections` 并配合 `pgbouncer` 的 `pool_size` / `max_client_conn`
- 应用侧用连接池（HikariCP 等）而非每请求建连

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [Architecture](/docs/CS/DB/PostgreSQL/Architecture.md)
- [Replication](/docs/CS/DB/PostgreSQL/Replication.md)
- [Performance](/docs/CS/DB/PostgreSQL/Performance.md)
- [Lock](/docs/CS/DB/PostgreSQL/Lock.md)
- [MySQL replica](/docs/CS/DB/MySQL/replica.md)

## References

1. [Patroni 文档](https://patroni.readthedocs.io/)
2. [repmgr 文档](https://www.repmgr.org/)
3. [pgbouncer 文档](https://www.pgbouncer.org/)
