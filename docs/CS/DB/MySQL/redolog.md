## 简介

重做日志（redo log）是在 `InnoDB` 存储引擎层面产生的。
重做日志用于崩溃恢复。
**重做日志是物理日志，记录的是"在某个数据页上做了什么修改"**。

写入机制：`InnoDB` 先写重做日志，再更新内存（Buffer Pool），最后将内存中的脏页刷入磁盘。
**WAL（Write-Ahead Logging）**：在将数据页写入磁盘之前，先确保重做日志已写入磁盘。

### 基本概念

- `LSN`（Log Sequence Number）日志序列号，单调递增
- `log group` 日志组，是一个逻辑概念，由多个重做日志文件组成
- `redo log file` 存储重做日志的物理文件

### 配置

```ini
# 指定重做日志文件组中文件的数量，默认为 2
innodb_log_files_in_group=2
# 指定每个 redo log file 的大小，默认 48M
innodb_log_file_size=50331648
# 指定重做日志所在的路径
innodb_log_group_home_dir=./
```

### 关键特性

1. **崩溃安全**：即使数据库崩溃，重启后可通过重做日志恢复未写入磁盘的修改。
2. **顺序写入**：重做日志是顺序追加写入的，性能优于随机写磁盘。
3. **循环写入**：重做日志文件是固定大小的，采用循环写入方式。

```c
// log0log.cc
```

### Mini-Transaction (mtr)

```c
/** A mini-transaction. */
class mtr_t {
    struct mtr_log_t {
        /** log section allocated from xc_buf for log */
        mlog_buf_t m_log;
        /** log section for short term use like log data collection */
        mlog_buf_t m_short_log;
        /** log section for long term use like log data collection */
        mlog_buf_t m_long_log;
    };
    /** Log */
    mtr_log_t m_log;
    /** Memo stack for storing pointers to objects that have been latched */
    mtr_memo_t m_memo;
    /** List of modifications */
    mtr_buf_t m_modifications;
    /** Nested calls */
    ulint m_nested;
    /** User provided */
    trx_t *m_user_trx;
    /** Indicates if the mtr made any modifications */
    bool m_made_dirty;
    /** Flags */
    ulint m_flags;
    /** Log mode */
    mtr_log_mode_t m_log_mode;
    /** Inside ibuf or not */
    bool m_inside_ibuf;
    /** Whether we have modified the page and will write the block to the tablespace later */
    bool m_modified_ht;
};
```

### 2PC

Redo Log 的两阶段提交：

1. **Prepare 阶段**：将事务的修改写入 redo log，并将事务标记为 prepare 状态。
2. **Commit 阶段**：将事务的修改写入 binlog，然后将 redo log 中对应的事务标记为 commit 状态。

```c
// Include/xa.h
struct xid_t {
    long gtrid;
    long bqual;
    long formatID;
};
```

### 写入流程

1. 事务修改数据页（在 Buffer Pool 中）。
2. 将修改操作记录到 redo log buffer 中。
3. 事务提交时，将 redo log buffer 中的日志刷入 redo log file（磁盘）。
4. 将脏页刷入磁盘（由 checkpoint 或后台线程完成）。

MySQL 8.0 对 redo log 做了一些优化，包括：

1. **并发写入优化**：通过引入 `log_writer`、`log_flusher`、`log_write_notifier`、`log_flush_notifier` 和 `log_closer` 等线程，将 redo log 的写入、刷盘、通知等操作解耦，提高并发性能。
2. **Dedicated Log Writer Threads**：引入专门的日志写入线程，减轻用户线程的负担。
3. **Lock-free 读取**：通过无锁数据结构，提升 log buffer 的读取性能。

## 链接

- [InnoDB Redo Log](/docs/CS/DB/MySQL/InnoDB.md?id=redolog)
