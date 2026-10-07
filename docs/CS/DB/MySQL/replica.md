## Introduction

MySQL 复制（replication）让一个 server（source，旧称 master）把自己写入 binlog 的数据变更传递给一个或多个 server（replica，旧称 slave），由 replica 回放这些变更以保持数据一致。本文以 MySQL 9.7 的术语为主，旧术语按「≤8.0.22 写法 / 仍作为弃用别名可用」标注。

| 项 | 值 |
| :--- | :--- |
| 正文默认版本 | MySQL 9.7.x LTS（最新 9.7.3，2026-08-18） |
| 源码核实基线 | tag `mysql-9.7.2` |
| 次要兼容目标 | 8.4.x LTS |
| 已停止支持 | 8.0（EOL 2026-04-30）、5.7（EOL 2023-10） |
| 核实日期 | 2026-10-07 |

## Terminology Migration

复制相关的文件名、命令、状态列与系统变量在 9.7 已全面改名，旧写法是弃用别名但仍可执行。旧系统变量以 `static Sys_var_deprecated_alias` 形式保留在 `sql/sys_vars.cc` 中，例如 `Sys_init_slave("init_slave", Sys_init_replica)`、`Sys_rpl_stop_slave_timeout`、`Sys_log_slow_slave_statements`、`Sys_slave_max_allowed_packet`、`Sys_slave_compressed_protocol`、`Sys_slave_exec_mode`、`Sys_slave_type_conversions`、`Sys_slave_sql_verify_checksum`。

| 旧写法 | 9.7 实际 |
| :--- | :--- |
| `rpl_slave.cc` | `sql/rpl_replica.cc` |
| `SHOW SLAVE STATUS` | `SHOW REPLICA STATUS` |
| `Seconds_Behind_Master` | `Seconds_Behind_Source` |
| `CHANGE MASTER TO` | `CHANGE REPLICATION SOURCE TO` |
| `master_*` / `slave_*` 系统变量 | `source_*` / `replica_*` |

## Replication Workflow

source 把数据变更记录写入 binlog；replica 侧的 I/O 线程连接 source 读取 binlog 事件并写入本地 relay log；applier 线程（旧称 coordinator / SQL 线程）读取 relay log 并分发事务；当 `replica_parallel_workers` 大于 1 时，事务再交给多个 worker 线程并行应用到 replica。

## Replica Lag

replica lag（主从延迟）指同一事务在 replica 执行完成的时刻与在 source 执行完成的时刻之差，通常以 `Seconds_Behind_Source`（≤8.0.22 为 `Seconds_Behind_Master`）度量，取自 `SHOW REPLICA STATUS`；当 replica 已追平 source 时该列为 0。其计算与「已追平」的判定逻辑在源码 `sql/rpl_replica.cc` 与 `sql/rpl_applier_reader.cc` 中实现。

最直接的表现是 source 产生 binlog 的速度高于 replica 消费 relay log 的速度。

## Sources of Replica Lag

- **Replica 机器性能弱于 source**：同步速度慢。尽量选用相同规格的机器、对称部署（同 OS、同硬件）。
- **大事务**：source 需等事务执行完（比如 10 分钟）才写 binlog 并传给 replica；replica 回放同样耗时约 10 分钟，此时主备延迟可达 10 分钟。可拆分大事务、避免长事务一次性提交。
- **Replica 读压力大**：replica 承担读流量时 I/O 压力大，按 relay log 同步变更的速度变慢。用一主多从分散读压力，或让专用 replica 不承担读。
- **Source 与 replica 索引不一致**：例如 source 走索引更新数据，replica 回放时却走全表扫描。MySQL 版本、参数配置不同都可能导致索引定义或优化器行为不一致——保持两侧同版本、同参数、同数据基线，并为每个 server 配置唯一 `server_id`。

## Links

- [binlog 二进制日志](/docs/CS/DB/MySQL/binlog.md)
- [redo log](/docs/CS/DB/MySQL/redolog.md)
- [MySQL](/docs/CS/DB/MySQL/MySQL.md)
- [版本迁移](/docs/CS/DB/MySQL/Version_Migration.md)

## References

- [MySQL 8.4 Reference Manual: Replication](https://dev.mysql.com/doc/refman/8.4/en/replication.html)
