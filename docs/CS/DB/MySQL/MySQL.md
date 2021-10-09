## Introduction

[MySQL Server](https://www.mysql.com/), the world's most popular open source database, and MySQL Cluster, a real-time, open source transactional database.

## [Installing and Upgrading MySQL](https://dev.mysql.com/doc/refman/8.0/en/installing.html)

```shell
cat /etc/sysconfig/selinux

```


## databases
information_schema
- tables
- processlist
- global_status
- global_variables
- partitions
innodb
- innodb_trx
- innodb_locks
- innodb_lock_waits


innodb shutdown handler
innodb purge coordinator
innodb purge worker * 3

max_delayed_threads 20
thread_stack 299008

thread_pool_idle_timeout 60
thread_pool_max_threads 65536
innodb_purge_threads 4
innodb_write_io_threads 4
innodb_read_io_threads 4
innodb_undo_logs 128


innodb_adaptive_hash_index_parts 8
innodb_adaptive_hash_index ON

## Files
- config
  - my.cnf
- data




![image-20210430214713744](./images/SQL.png)

Table

笛卡尔积

Forever table

temp table

- union union all
- Temptable algorithm
- distinct and order by



virtual table

2

### Server




- 连接器 身份认证 权限管理 连接不断 即使修改了权限 此连接不受影响
- 查询缓存 8.0后移除 缓存select语句及结果集 因在频繁更新情况下经常失效
- 分析器 无命中缓存进入 词法分析 提出关键字段 语法分析 检验语句是否正确
- 优化器 内部实现 执行计划 选择索引 
- 执行器 检验有权限后调用引擎接口 返回执行结果
- 日志模块 binlog公有 redolog只InnoDB有



## Character Sets, Collations, Unicode

MySQL includes character set support that enables you to store data using a variety of character sets and perform comparisons according to a variety of collations. The default MySQL server character set and collation are `latin1` and `latin1_swedish_ci`, but you can specify character sets at the server, database, table, column, and string literal levels.

## Storage Engine

Storage engines are MySQL components that handle the SQL operations for different table types. `InnoDB` is the default and most general-purpose storage engine.

### [The InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md)

### [Alternative Storage Engines](/docs/CS/DB/MySQL/Engine.md)




### InnoDB memcached Plugin

## Master-Slave
### replication

master write to binary log
slaves get binary log events by I/O threads and write to relay log
slaves SQL threads replay SQL from relay log


Notes:
- same OS version
- same DB version
- same data
- same server id


## log

### binary log

log_bin
log_bin_basename
log_bin_compress
log_bin_compress_min_len 256
log_bin_index
log_bin_trust_function_creators
sql_log_bin


binlog_annotate_row_events	ON
binlog_cache_size	32768 32KB
binlog_checksum	CRC32
binlog_commit_wait_count	0
binlog_commit_wait_usec	100000
binlog_direct_non_transactional_updates	OFF
binlog_file_cache_size	16384
binlog_format	MIXED
binlog_optimize_thread_scheduling	ON
binlog_row_image	FULL
binlog_stmt_cache_size	32768
encrypt_binlog	OFF
gtid_binlog_pos
gtid_binlog_state
innodb_locks_unsafe_for_binlog	OFF
max_binlog_cache_size	18446744073709547520
max_binlog_size	1073741824 1G
max_binlog_stmt_cache_size	18446744073709547520
read_binlog_speed_limit	0
sync_binlog	0
wsrep_forced_binlog_format	NONE

### slow log

log_slow_admin_statements	ON
log_slow_disabled_statements	sp
log_slow_filter	admin,filesort,filesort_on_disk,filesort_priority_queue,full_join,full_scan,query_cache,query_cache_miss,tmp_table,tmp_table_on_disk
log_slow_rate_limit	1
log_slow_slave_statements	ON
log_slow_verbosity
slow_launch_time	2
slow_query_log	OFF
slow_query_log_file	demo-slow.log


### general log
log_output	FILE


show status

explain 

show profiles
show profile

    show profile source for

## [Optimization](/docs/CS/DB/MySQL/Optimization.md)
