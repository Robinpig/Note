## Introduction

[MySQL Server](https://www.mysql.com/), the world's most popular open source database, and MySQL Cluster, a real-time, open source transactional database.

### [Installing and Upgrading MySQL](https://dev.mysql.com/doc/refman/8.0/en/installing.html)

with docker

```shell
docker pull mysql:5.7

docker image ls

docker run --name test-mysql -e MYSQL_ROOT_PASSWORD=123456 -p 3306:3306 -d mysql:5.7

```

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

#### main loop

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

#### srv_master_do_idle_tasks

per 10 seconds

- flush log buffer
- merge max 5 change buffer
- flush max 100 buffer pool pages(might)
- purge unused undo log

#### srv_master_do_active_tasks

per second

- flush log buffer
- merge change buffer(might)
- flush max 100 buffer pool pages(might)
- jump into background loop

```cpp

/** Perform the tasks that the master thread is supposed to do when the
 server is active. There are two types of tasks. The first category is
 of such tasks which are performed at each inovcation of this function.
 We assume that this function is called roughly every second when the
 server is active. The second category is of such tasks which are
 performed at some interval e.g.: purge, dict_LRU cleanup etc. */
static void srv_master_do_active_tasks(void) {
  const auto cur_time = ut_time_monotonic();
  auto counter_time = ut_time_monotonic_us();

  /* First do the tasks that we are suppose to do at each
  invocation of this function. */

  ++srv_main_active_loops;

  MONITOR_INC(MONITOR_MASTER_ACTIVE_LOOPS);

  /* ALTER TABLE in MySQL requires on Unix that the table handler
  can drop tables lazily after there no longer are SELECT
  queries to them. */
  srv_main_thread_op_info = "doing background drop tables";
  row_drop_tables_for_mysql_in_background();
  MONITOR_INC_TIME_IN_MICRO_SECS(MONITOR_SRV_BACKGROUND_DROP_TABLE_MICROSECOND,
                                 counter_time);

  ut_d(srv_master_do_disabled_loop());

  if (srv_shutdown_state.load() >=
      SRV_SHUTDOWN_PRE_DD_AND_SYSTEM_TRANSACTIONS) {
    return;
  }

  /* Do an ibuf merge */
  srv_main_thread_op_info = "doing insert buffer merge";
  counter_time = ut_time_monotonic_us();
  ibuf_merge_in_background(false);
  MONITOR_INC_TIME_IN_MICRO_SECS(MONITOR_SRV_IBUF_MERGE_MICROSECOND,
                                 counter_time);

  /* Flush logs if needed */
  log_buffer_sync_in_background();

  /* Now see if various tasks that are performed at defined
  intervals need to be performed. */

  if (srv_shutdown_state.load() >=
      SRV_SHUTDOWN_PRE_DD_AND_SYSTEM_TRANSACTIONS) {
    return;
  }

  srv_update_cpu_usage();

  if (trx_sys->rseg_history_len.load() > 0) {
    srv_wake_purge_thread_if_not_active();
  }

  if (cur_time % SRV_MASTER_DICT_LRU_INTERVAL == 0) {
    srv_main_thread_op_info = "enforcing dict cache limit";
    ulint n_evicted = srv_master_evict_from_table_cache(50);
    if (n_evicted != 0) {
      MONITOR_INC_VALUE(MONITOR_SRV_DICT_LRU_EVICT_COUNT, n_evicted);
    }
    MONITOR_INC_TIME_IN_MICRO_SECS(MONITOR_SRV_DICT_LRU_MICROSECOND,
                                   counter_time);
  }
}
```

#### purge

```
innodb_purge_batch_size	300
innodb_purge_rseg_truncate_frequency	128
innodb_purge_threads	4
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

## Files

### [Server Log](/docs/CS/DB/MySQL/serverlog.md)

### [Redo Log](/docs/CS/DB/MySQL/redolog.md)

### [undo Log](/docs/CS/DB/MySQL/undolog.md)

### [File](/docs/CS/DB/MySQL/file.md)

redo log prepare -> binlog write -> redo log commit


## Character Sets, Collations, Unicode

MySQL includes character set support that enables you to store data using a variety of character sets and perform comparisons according to a variety of collations. The default MySQL server character set and collation are `latin1` and `latin1_swedish_ci`, but you can specify character sets at the server, database, table, column, and string literal levels.

## Architecture
The MySQL pluggable storage engine architecture enables a database professional to select a specialized storage engine for a particular application need while being completely shielded from the need to manage any specific application coding requirements. The MySQL server architecture isolates the application programmer and DBA from all of the low-level implementation details at the storage level, providing a consistent and easy application model and API. Thus, although there are different capabilities across different storage engines, the application is shielded from these differences.

The MySQL pluggable storage engine architecture is shown in figure.



<div style="text-align: center;">

![Fig.1. MySQL Architecture with Pluggable Storage Engines](img/Storage-Engine.png)

</div>

<p style="text-align: center;">
Fig.1. MySQL Architecture with Pluggable Storage Engines.
</p>



### Server

- Connector 身份认证 权限管理 连接不断 即使修改了权限 此连接不受影响
- 查询缓存 8.0后移除 缓存select语句及结果集 因在频繁更新情况下经常失效
- 分析器 无命中缓存进入 词法分析 提出关键字段 语法分析 检验语句是否正确
- 优化器 内部实现 执行计划 选择索引
- 执行器 检验有权限后调用引擎接口 返回执行结果
- 日志模块 binlog公有 redolog只InnoDB有

wait_timeout 8h

mysql_reset_connection

### Storage Engine

Storage engines are MySQL components that handle the SQL operations for different table types. [InnoDB](/docs/CS/DB/MySQL/InnoDB.md) is the default and most general-purpose storage engine.


```MySQL
Show engines

```



[Alternative Storage Engines](/docs/CS/DB/MySQL/Engine.md)







MyISAM vs InnoDB

| Feature                      | MyISAM Support |   InnoDB Support            |
| :————————— | :-———— |:-———— |
| **B-tree indexes**           | Yes            |      Yes         |
| **Cluster database support** | No             |         Yes      |
| **Clustered indexes**        | No             |      Yes         |
| **Data caches**              | No             |       Yes        |
| **Foreign key support**      | No             |       Yes        |
| **Full-text search indexes** | Yes            |       Yes        |
| **Hash indexes**             | No             |       No (InnoDB utilizes hash indexes internally for its Adaptive Hash Index feature.)        |
| **Index caches**             | Yes            |        Yes       |
| **Locking granularity**      | Table          |          Row     |
| **MVCC**                     | No             |        Yes       |
| **Storage limits**           | 256TB          |        64TB       |
| **Transactions**             | No             |      Yes         |




## Master-Slave

MySQL is designed for accepting writes on one node at any given time. 
This has advantages in managing consistency but leads to trade-offs when you need the data written in multiple servers or multiple locations. 
MySQL offers a native way to dis‐ tribute writes that one node takes to additional nodes. This is referred to as replication. 
In MySQL, the source node has a thread per replica that is logged in as a replication client that wakes up when a write occurs, sending new data.

### replication

master write to binary log
slaves get binary log events by I/O threads and write to relay log
slaves SQL threads replay SQL from relay log

Notes:

- same OS version
- same DB version
- same data
- same server id

## [Optimization](/docs/CS/DB/MySQL/Optimization.md)



### Performance Schema


Performance Schema provides low-level metrics on operations running inside MySQL server. 
To explain how Performance Schema works, there are two concepts I need to introduce early.

- The first is an instrument. An instrument refers to any portion of the MySQL code that we want to capture information about. 
  For example, if we want to collect information about metadata locks, we would need to enable the wait/lock/meta data/sql/mdl instrument.
- The second concept is a consumer, which is simply a table that stores the information about what code was instrumented.
  If we instrument queries, the consumer will record information like the total number of executions, how many times no index was used, the time spent, and so forth. 
  The consumer is what most people closely associate with Performance Schema.





Performance Schema stores data in tables that use the PERFORMANCE_SCHEMA engine. This engine stores data in memory. 
Some of the performance_schema tables are autosized by default; others have a fixed number of rows. You can adjust these options by changing startup variables.



Since version 5.7, Performance Schema is enabled by default with most of the instru‐ ments disabled. Only global, thread, statements, and transaction instrumentation is enabled. Since version 8.0, metadata lock and memory instrumentation are addition‐ ally enabled by default.

The mysql, information_schema, and performance_schema databases are not instru‐ mented. All other objects, threads, and actors are instrumented.

Most of the instances, handles, and setup tables are autosized. For the _history tables, the last 10 events per thread are stored. For the _history_long tables, the lat‐ est 10,000 events per thread are stored. The maximum stored SQL text length is 1,024 bytes. The maximum SQL digest length is also 1,024 bytes. Everything that is larger is right-trimmed.

### What Limits MySQL’s Performance?
Many different hardware components can affect MySQL’s performance, but the most frequent bottleneck we see is CPU exhaustion. CPU saturation can happen when MySQL tries to execute too many queries in parallel or when a smaller number of queries runs for too long on the CPU.

Broadly speaking, you have two goals for your server:
- *Low latency (fast response time)*<br>
  To achieve this, you need fast CPUs because each query will use only a single CPU.
- *High throughput*<br>
  If you can run many queries at the same time, you might benefit from multiple CPUs to service the queries.

If your workload doesn’t utilize all of your CPUs, MySQL can still use the extra CPUs for background tasks such as purging InnoDB buffers, network operations, and so on. 
However, these jobs are usually minor compared to executing queries.


I/O saturation can still happen but much less frequently than CPU exhaustion. This is largely because of the transition to using solid-state drives (SSDs).
Historically, the performance penalty of no longer working in memory and going to the hard disk drive (HDD) was extreme. SSDs are generally 10 to 20 times faster than SSH.
Nowadays, if queries need to hit disk, you’re still going to see decent performance from them.

Memory exhaustion can still happen but usually only when you try to allocate too much memory to MySQL.


The main reason to have a lot of memory isn’t so you can hold a lot of data in mem‐ ory: it’s ultimately so you can avoid disk I/O, which is orders of magnitude slower than accessing data in memory. 
The trick is to balance the memory and disk size, speed, cost, and other qualities so you get good performance for your workload.

If you have enough memory, you can insulate the disk from read requests completely. If all your data fits in memory, every read will be a cache hit once the server’s caches are warmed up.
There will still be logical reads from memory but no physical reads from disk. Writes are a different matter, though. 
A write can be performed in mem‐ ory just as a read can, but sooner or later it has to be written to the disk so it’s perma‐ nent. 
In other words, a cache can delay writes, but caching cannot eliminate writes as it can for reads.

In fact, in addition to allowing writes to be delayed, caching can permit them to be grouped together in two important ways:
- *Many writes, one flush*<br>
  A single piece of data can be changed many times in memory without all of the new values being written to disk. 
  When the data is eventually flushed to disk, all the modifications that happened since the last physical write are permanent. 
  For example, many statements could update an in-memory counter. If the counter is incremented one hundred times and then written to disk, one hundred modifica‐ tions have been grouped into one write.
- *I/O merging*<br>
  Many different pieces of data can be modified in memory, and the modifications can be collected together, so the physical writes can be performed as a single disk operation.

## Links

- [DataBases](/docs/CS/DB/DB.md?id=MySQL)
