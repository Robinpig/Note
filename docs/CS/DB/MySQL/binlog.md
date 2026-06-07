## Binlog

binlog 是 MySQL Server 层的日志。
它记录 MySQL 中数据变更相关的所有事件。
binlog 可配置为三种格式：

- **STATEMENT**：记录 SQL 语句，在从库执行相同 SQL。
- **ROW**：记录行的变更（前镜像和后镜像）。
- **MIXED**：混合模式，MySQL 自动选择合适的格式。

### 写入机制

binlog 在事务提交时写入。
写入过程涉及三个步骤：

1. **写入 binlog 缓存**：事务执行期间，日志写入一个内存缓冲区（binlog_cache）。
2. **写入 binlog 文件**：事务提交时，缓存中的内容写入 binlog 文件（通过 OS 缓存）。
3. **同步到磁盘**：根据 `sync_binlog` 设置的策略执行 fsync。

### 两阶段提交

为了使 binlog 和 redo log 保持一致，MySQL 使用了两阶段提交（2PC）：

1. InnoDB 执行 prepare（将 redo log 写入磁盘）。
2. MySQL Server 写入 binlog。
3. InnoDB 执行 commit（在 redo log 中标记事务为已提交）。

如果步骤 1 和步骤 2 之间发生崩溃，则事务回滚。
如果步骤 2 和步骤 3 之间发生崩溃，则事务将自动提交，因为 binlog 已写入（用于复制）。

### 配置

```ini
# binlog 格式
binlog_format=ROW
# binlog 文件大小上限
max_binlog_size=1G
# binlog 保留天数
expire_logs_days=7
# 同步策略（0=OS 缓存, 1=每次提交同步, N=N 次提交后同步）
sync_binlog=1
```

### xid Event

两阶段提交的核心事件。MySQL 在处理崩溃恢复时通过 xid event 来判断 binlog 中的事务是否完整。

```c
// 在 binlog 中写入 xid event
int ha_commit_trans(THD *thd, bool all, bool ignore_global_read_lock) {
    if ((error=mysql_bin_log.write(thd, thd->query(), thd->query_length())))
        DBUG_RETURN(error);
    if ((error=ha_commit_low(thd, all, ignore_global_read_lock)))
        DBUG_RETURN(error);
    ...
}
```

### 崩溃恢复

崩溃恢复过程中，MySQL 检查 binlog 和 redo log 的状态：

1. 扫描最后一个 binlog 文件，收集所有 xid。
2. 扫描 redo log，检查每个 prepared 事务的 xid。
3. 如果事务的 xid 在 binlog 中，则提交；否则回滚。

### 清理策略

- `expire_logs_days`：自动删除超过指定天数的 binlog 文件。
- `PURGE BINARY LOGS`：手动清理 binlog。
- 基于空间利用率的清理（MySQL 8.0 引入的 `binlog_expire_logs_seconds`）。

### 从库回放

从库从 binlog 读取事件并回放：

1. I/O 线程：从主库拉取 binlog 事件并写入中继日志（relay log）。
2. SQL 线程：读取中继日志中的事件并执行。
3. 多线程回放：从库可使用多个工作线程并行回放不同数据库的事件，提高性能。

## 链接

- [MySQL 复制](/docs/CS/DB/MySQL/replica.md)
- [MySQL Server](/docs/CS/DB/MySQL/MySQL.md)
