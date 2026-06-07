## 简介

双写缓冲区（doublewrite buffer）是一个存储区域，`InnoDB` 在将页面写入 `InnoDB` 数据文件中正确位置之前，先将缓冲池中刷出的页面写入该区域。
只有缓冲区安全刷写到磁盘后，InnoDB 才会将页面写入最终目的地。
恢复时，InnoDB 扫描双写缓冲区，对缓冲区中每个有效页面，检查数据文件中的页面是否也有效。

虽然数据被写入两次，但双写缓冲区不需要两倍的 I/O 开销或两倍的 I/O 操作。
数据以大的连续块写入双写缓冲区，通过单个 `fsync()` 调用写入操作系统（除非 `innodb_flush_method` 设置为 `O_DIRECT_NO_FSYNC`）。

> 在 MySQL 8.0.20 之前，双写缓冲区存储区域位于 `InnoDB` 系统表空间中。
> 从 MySQL 8.0.20 开始，双写缓冲区存储区域位于双写文件中。

以下是用于双写缓冲区配置的变量：

- `innodb_doublewrite` 变量控制双写缓冲区是否启用。
- `innodb_doublewrite_dir` 变量（MySQL 8.0.20 中引入）定义 `InnoDB` 创建双写文件的目录。
- `innodb_doublewrite_files` 变量定义双写文件的数量。
  默认情况下，为每个缓冲池实例创建两个双写文件：一个 flush list 双写文件和一个 LRU list 双写文件。

```c++
// buf0dblwr.cc
```

> [!NOTE]
> [生产服务器绝不应禁用双写缓冲区。](https://dba.stackexchange.com/questions/86636/when-is-it-safe-to-disable-innodb-doublewrite-buffering)
> 如果为了更快加载数据（当然是在维护期间）而禁用它，请在重新加载数据库服务器后立即重新启用。

## 链接

- [InnoDB 存储引擎](/docs/CS/DB/MySQL/InnoDB.md?id=innodb-on-disk-structures)
