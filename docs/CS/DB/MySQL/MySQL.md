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


innodb_old_blocks_pct 37  -- 3/8
innodb_old_blocks_time	1000


buffer pool
```mysql
mysql> SELECT * FROM information_schema.INNODB_BUFFER_POOL_STATS;
```

LRU list

```mysql
mysql> SELECT TABLE_NAME,PAGE_NUMBER,PAGE_TYPE,INDEX_NAME,SPACE FROM information_schema.INNODB_BUFFER_PAGE_LRU WHERE SPACE = 1;
```

Free List


Flush List
```mysql
mysql> SELECT COUNT(*) FROM information_schema.INNODB_BUFFER_PAGE_LRU  WHERE OLDEST_MODIFICATION > 0;
```

```
// using SHOW ENGINE INNODB STATUS;
Modified db pages
```


checkpoint

```
Log sequence number
```


```
innodb_max_dirty_pages_pct	75.000000
innodb_max_dirty_pages_pct_lwm	0.000000
```

### Threads
Master

```
// using SHOW ENGINE INNODB STATUS;
srv_master_thread loops: 177 srv_active, 0 srv_shutdown, 2772864 srv_idle
srv_master_thread log flush and writes: 2773038
```

```cpp
// srv0srv.cc
/** The master thread controlling the server. */
void srv_master_thread() {

  srv_slot_t *slot;

  THD *thd = create_thd(false, true, true, 0);

  ut_ad(!srv_read_only_mode);

  srv_main_thread_process_no = os_proc_get_number();
  srv_main_thread_id = std::this_thread::get_id();

  slot = srv_reserve_slot(SRV_MASTER);
  ut_a(slot == srv_sys->sys_threads);

  srv_master_main_loop(slot);

  srv_master_pre_dd_shutdown_loop();

  os_event_set(srv_threads.m_master_ready_for_dd_shutdown);

  /* This is just for test scenarios. */
  srv_thread_delay_cleanup_if_needed(true);

  while (srv_shutdown_state.load() < SRV_SHUTDOWN_MASTER_STOP) {
    srv_master_wait(slot);
  }

  srv_master_shutdown_loop();

  srv_main_thread_op_info = "exiting";
  destroy_thd(thd);
}
```


```cpp

/** Executes the main loop of the master thread.
@param[in]   slot     slot reserved as SRV_MASTER */
static void srv_master_main_loop(srv_slot_t *slot) {
  if (srv_force_recovery >= SRV_FORCE_NO_BACKGROUND) {
    /* When innodb_force_recovery is at least SRV_FORCE_NO_BACKGROUND,
    we avoid performing active/idle master's tasks. However, we still
    need to ensure that:
      srv_shutdown_state >= SRV_SHUTDOWN_PRE_DD_AND_SYSTEM_TRANSACTIONS,
    after we exited srv_master_main_loop(). Keep waiting until that
    is satisfied and then exit. */
    while (srv_shutdown_state.load() <
           SRV_SHUTDOWN_PRE_DD_AND_SYSTEM_TRANSACTIONS) {
      srv_master_wait(slot);
    }
    return;
  }

  ulint old_activity_count = srv_get_activity_count();

  while (srv_shutdown_state.load() <
         SRV_SHUTDOWN_PRE_DD_AND_SYSTEM_TRANSACTIONS) {
    srv_master_sleep();

    MONITOR_INC(MONITOR_MASTER_THREAD_SLEEP);

    /* Just in case - if there is not much free space in redo,
    try to avoid asking for troubles because of extra work
    performed in such background thread. */
    srv_main_thread_op_info = "checking free log space";
    log_free_check();

    if (srv_check_activity(old_activity_count)) {
      old_activity_count = srv_get_activity_count();
      srv_master_do_active_tasks();
    } else {
      srv_master_do_idle_tasks();
    }

    /* Let clone wait when redo/undo log encryption is set. If clone is already
    in progress we skip the check and come back later. */
    if (!clone_mark_wait()) {
      continue;
    }

    /* Allow any blocking clone to progress. */
    clone_mark_free();

    /* Purge any deleted tablespace pages. */
    fil_purge();
  }
}
```

```cpp

void fil_purge() { fil_system->purge(); }

/** Clean up the shards. */
void purge() {
  for (auto shard : m_shards) {
    shard->purge();
  }
}


/** Purge entries from m_deleted_spaces that are no longer referenced by a
buffer pool page. This is no longer required to be done during checkpoint -
this is done here for historical reasons - it has to be done periodically
somewhere. */
void purge() {
  /* Avoid cleaning up old undo files while this is on. */
  DBUG_EXECUTE_IF("ib_undo_trunc_checkpoint_off", return;);

  mutex_acquire();
  for (auto it = m_deleted_spaces.begin(); it != m_deleted_spaces.end();) {
    auto space = it->second;

    if (space->has_no_references()) {
      ut_a(space->files.front().n_pending == 0);

      space_free_low(space);

      it = m_deleted_spaces.erase(it);
    } else {
      ++it;
    }
  }

  mutex_release();
}  
  
  
/** Free a tablespace object on which fil_space_detach() was invoked.
There must not be any pending I/O's or flushes on the files.
@param[in,out]	space		tablespace */
void Fil_shard::space_free_low(fil_space_t *&space) {
#ifndef UNIV_HOTBACKUP
  {
    /* Temporary and undo tablespaces IDs are assigned from a large but
    fixed size pool of reserved IDs. Therefore we must ensure that a
    fil_space_t instance can't be dropped until all the pages that point
    to it are also purged from the buffer pool. */

    ut_a(srv_shutdown_state.load() == SRV_SHUTDOWN_LAST_PHASE ||
         space->has_no_references());
  }
#endif /* !UNIV_HOTBACKUP */

  for (auto &file : space->files) {
    ut_d(space->size -= file.size);

    os_event_destroy(file.sync_event);

    ut_free(file.name);
  }

  call_destructor(&space->files);

  ut_ad(space->size == 0);

  rw_lock_free(&space->latch);
  ut_free(space->name);
  ut_free(space);

  space = nullptr;
}
  
```

### insert buffer
for secondary non_unique index
```
// using SHOW ENGINE INNODB STATUS;
Ibuf: size 1, free list len 0, seg size 2, 0 merges
merged operations:
insert 0, delete mark 0, delete 0
discarded operations:
insert 0, delete mark 0, delete 0
```

```cpp

/** Maximum on-disk size of change buffer in terms of percentage
of the buffer pool. */
uint srv_change_buffer_max_size = CHANGE_BUFFER_DEFAULT_SIZE; // 25

```

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


```
long_query_time	10.000000
log_slow_admin_statements	ON
log_slow_disabled_statements	sp
log_slow_filter	admin,filesort,filesort_on_disk,filesort_priority_queue,full_join,full_scan,query_cache,query_cache_miss,tmp_table,tmp_table_on_disk
log_slow_rate_limit	1
log_slow_slave_statements	ON
log_slow_verbosity
slow_launch_time	2

slow_query_log	ON // must be ON
log_queries_not_using_indexes	ON

slow_query_log_file	demo-slow.log
```

```mysql

mysql> SELECT * FROM mysql.slow_log;
```


### general log
log_output	FILE


show status

explain 

show profiles
show profile


    show profile source for



```mysql

mysql> SELECT * FROM mysql.general_log;
```

### error log

```
log_error	/var/log/mariadb/mariadb.log
```

## [Optimization](/docs/CS/DB/MySQL/Optimization.md)
