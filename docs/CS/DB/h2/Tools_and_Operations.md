## Introduction

H2 是嵌入式库，所以「运维」的含义是：用一批随 jar 附带的命令行工具完成备份、导入导出、加密换密、损坏救援与诊断。这一页按 `tutorial.html#Command Line Tools` 的官方清单整理，并用源码校正了几处常被引用的不存在工具。锚定 2.5.252。

## Command Line Tools

官方清单是 **12 个**，全部可以 `java -cp h2-2.5.252.jar org.h2.tools.<名字> -?` 取帮助，也都可以从程序里调 `main` 或公开方法：

| 工具 | 用途 | 备注 |
| :--- | :--- | :--- |
| `Server` | 起 Web Console / TCP / PG server | 参数与默认端口见 [Connection_and_Servers](/docs/CS/DB/h2/Connection_and_Servers.md) |
| `Shell` | 命令行 SQL 客户端 | |
| `Console` | 浏览器/终端 Console（内含 Server） | |
| `Script` | 导出为 SQL 脚本 | 见下文选项 |
| `RunScript` | 执行 SQL 脚本 | 支持 `FROM_1X`，见 [Compatibility_Modes](/docs/CS/DB/h2/Compatibility_Modes.md) |
| `Backup` / `Restore` | 打成 zip / 还原 | 只读打包场景**只能用** Backup 工具，不能用 `BACKUP TO` |
| `Recover` | 从（可能损坏的）库导出 `*.mv.txt` + `*.h2.sql` | 未压缩，约占数据库两倍盘 |
| `DeleteDbFiles` | 按前缀删除某库的所有文件 | 程序化签名 `DeleteDbFiles.execute(dir, name, true)` |
| `ChangeFileEncryption` | 加/解密、换口令 | 参数只有 `-dir -db -cipher -encrypt -decrypt -quiet`；**改密要先解密** |
| `CreateCluster` | 重建简单 HA 集群 | |
| `ConvertTraceFile` | 把 `*.trace.db` 转成可查询的 SQL | 配合 `-trace` 使用 |

`org.h2.tools` 包里另有一批**非命令行**助手：`Csv`、`CompressTool`、`SimpleResultSet`、`TriggerAdapter`、`MultiDimension`（多维坐标的 Z-order 折叠工具）、`DirectRecover`（较新的直读恢复路径）与内部的 `Upgrade`。

> [!WARNING]
> 三件常被当成存在的事：① **`MVStoreTool` 不在 `org.h2.tools`**，它在 `org.h2.mvstore`，因此不在这 12 个工具之列；② **`ShrinkDatabase`、`ConvertFile`、`FileLockTool` 都不存在**（tools 目录与源码检索均无）；③ 缩库不是靠工具，而是 `SHUTDOWN COMPACT`——`SHUTDOWN DEFRAG` 等价于 COMPACT，`SHUTDOWN IMMEDIATELY` 跳过一切清理，而正常关闭默认只给 **200 ms** 压缩时间（`features.html#compacting_a_database`）。

## Script and RunScript

导出侧：

```sql
SCRIPT [NODATA | SIMPLE [COLUMNS]] [NOPASSWORDS] [NOSETTINGS] [DROP]
       [BLOCKSIZE n] [TO 'file' [scriptCompressionEncryption]]
       [TABLE t ...] [SCHEMA s ...]
```

导入侧：

```sql
RUNSCRIPT FROM 'file' [scriptCompressionEncryption]
        [QUIRKS_MODE | VARIABLE_BINARY | FROM_1X]
```

`scriptCompressionEncryption` 由 `CIPHER ... PASSWORD ... COMPRESSION ... BLOCKSIZE ...` 组合而成，所以「脚本文件本身加密 + 压缩」是一等操作。ZIP 例子（命令行形式）：

```bash
java -cp h2-2.5.252.jar org.h2.tools.Script \
     -url jdbc:h2:~/test -user sa -script test.zip -options compression zip
```

## CSV Import and Export

`CSVREAD(file [, columns [, options]])` 是**表函数**（可直接 `SELECT * FROM CSVREAD(...)`），`CSVWRITE(file, query [, options])` 反向导出。选项集：`charset`、`fieldSeparator`、`arraySeparator`、`commentRowPrefix`、`escapeCharacter`、`nullString`、`quoteCharacter`、`quoteAll`、`writeBOM`、`caseSensitiveColumnNames`、`strictQuotes`、`lineSeparator`、`suffixFilter`。

两个坑：**CSV 的所有列都被当作 `VARCHAR`**（要类型就 `CAST` 或 `INSERT ... SELECT` 转一道），以及 **BOM 会被忽略**但可用 `writeBOM` 主动写出。

## Diagnostics and Monitoring

H2 的可观测面全部走 SQL 查询，没有旁路进程：

| 视图 / 语句 | 看到什么 |
| :--- | :--- |
| `INFORMATION_SCHEMA.SESSIONS` | 活动会话（连接）、命令与事务状态 |
| `INFORMATION_SCHEMA.SESSION_STATE` | 每会话的读写计数、内存、事务数等统计 |
| `INFORMATION_SCHEMA.LOCKS` | 谁持锁（`TABLE_SCHEMA, TABLE_NAME, SESSION_ID, LOCK_TYPE`） |
| `INFORMATION_SCHEMA.QUERY_STATISTICS` | 查询耗时与调用次数（需 `SET QUERY_STATISTICS TRUE`） |
| `INFORMATION_SCHEMA.SETTINGS` | 全部 `SET` 项的当前值 |
| `EXPLAIN` / `EXPLAIN ANALYZE` | 计划与执行代价（`OPTIMIZE_REUSE_RESULTS`、列 `SELECTIVITY` 会影响它） |
| `CALL READONLY()` / `Connection.isReadOnly()` | 是否只读打开 |

日志侧：`-trace` 或 `TRACE_LEVEL_FILE` 让 H2 写 `*.trace.db`（超限轮转为 `.trace.db.old`），再用 `ConvertTraceFile` 转回 SQL 便于分析。1.x 时代的一些统计视图（`TABLE_STATISTICS`、`INDEX_SCAN`、`ROWCOUNT`）在 2.x **已不存在**，见 [Transactions_and_Locks](/docs/CS/DB/h2/Transactions_and_Locks.md)。

## Performance Knobs

先排除噪音：`MULTI_THREADED`、`CACHE_ROWS`、`WRITE_BUFFER` 这些**在 2.x 不存在**；`MAX_MEMORY_UNDO` 与 `CACHE_TYPE` 是**语法保留但无人消费的死参数**（`CACHE_TYPE` 文档还在介绍 TQ / SOFT_LRU，实际永远走 LIRS）。真实可调的是：

- **`SET CACHE_SIZE`**（KB；默认按内存自动取 64 MB / 每 GB RAM 并向上取 2 的幂，持久化）→ 决定 MVStore 块缓存大小；注意 SQL 层是 KB、`MVStore.Builder.cacheSize()` 是 **MB**，单位混用过一次就懂得分层看（见 [MVStore](/docs/CS/DB/h2/MVStore.md)）。
- **`SET MAX_MEMORY_ROWS`**（默认 40 000 / 每 GB RAM，自动按内存缩放）与 `MAX_MEMORY_ROW_SIZE`：决定行对象是否在内存中缓存，影响 CPU/内存权衡。
- **`WRITE_DELAY`**（默认 500 ms）→ 映射到 MVStore 的 `autoCommitDelay`；**它不是 fsync 间隔**，真正的同步只有 `CHECKPOINT SYNC`。
- **`SET RETENTION_TIME`**（默认 45 s）→ 越大越抗长读事务、越小越快回收空间。
- **`nioMapped:` 文件前缀**：唯一的 mmap 通道（没有 `FILE_STORE_MMAP` 或 `h2.mmapUse`）。
- 无 `WHERE` 的 `COUNT(*)` 是 O(1)（走 `map.sizeAsLong()`），所以「用 count 做进度判断」在这里不是负担。
- 批量灌数据：**没有 `COPY` 语句**，用 `CSVREAD` 或事务包住的多行 `INSERT` / `BatchUpdate`；导入完成后 `ANALYZE` 更新列选择度（`Optimizer` 的连接顺序搜索依赖它，见 [Transactions_and_Locks](/docs/CS/DB/h2/Transactions_and_Locks.md)）。

## Windows Service and ODBC

`advanced.html` 还提供「Run as Windows Service」（Install / Start / Connect to the H2 Console / Stop / Uninstall 五步）与 **ODBC** 通道；后者本质是让 PG 的 ODBC 驱动连 PG Server，因此受 PG 协议那套限制约束（**不支持 SSL、语句不可取消、首个连接必须是 admin**），完整清单见 [Connection_and_Servers](/docs/CS/DB/h2/Connection_and_Servers.md) 的 PG Protocol 一节。构建时还有可选的 Apache Lucene 集成（`build.html`），对应 `org.h2.fulltext` 模块，见 [SQL_Language](/docs/CS/DB/h2/SQL_Language.md)。

## Pitfalls

1. 找不到 `ShrinkDatabase` / `ConvertFile` 工具是正常的——缩库用 `SHUTDOWN COMPACT`，迁版本用 `RUNSCRIPT ... FROM_1X`。
2. `MVStoreTool` 的包路径是 `org.h2.mvstore`，`-copy` 子命令不存在。
3. CSV 导入得到的一律是 VARCHAR。
4. 只读打包（zip 形态）必须用 Backup 工具而不是 `BACKUP TO`。
5. 监控靠 `INFORMATION_SCHEMA.*` 视图，1.x 的统计视图名已全部失效。
6. `CACHE_SIZE`（KB）与 `MVStore.Builder.cacheSize()`（MB）单位不同。

## Links

- [H2](/docs/CS/DB/h2/H2.md)
- [MVStore](/docs/CS/DB/h2/MVStore.md)
- [Connection and Servers](/docs/CS/DB/h2/Connection_and_Servers.md)
- [SQL Language](/docs/CS/DB/h2/SQL_Language.md)
- [Compatibility Modes](/docs/CS/DB/h2/Compatibility_Modes.md)
- [WAL](/docs/CS/DB/WAL.md)

## References

1. [H2 Database Engine - Command Line Tools](https://h2database.com/html/tutorial.html)
2. [H2 Database Engine - Advanced Features](https://h2database.com/html/advanced.html)
3. [H2 Database Engine - Commands](https://h2database.com/html/commands.html)
4. [H2 Database Engine - Build](https://h2database.com/html/build.html)
