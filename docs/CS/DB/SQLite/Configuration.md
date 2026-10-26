## Introduction

SQLite 的默认值没有一条是随便定的，但也没有一条替你考虑了应用场景。本页把「值得拧的开关」分三类摆清楚：**PRAGMA**（运行时可调，但要分清哪些写进数据库文件、哪些只活一个连接）、**线程模型**（编译期定基调、运行时可改档）、**编译期选项**（构建那一刻的决定，事后只能重编）。

版本锚点 3.54.1（2026-10-16）。

## PRAGMA Defaults

| PRAGMA | 默认 | 作用域 | 要点 |
| :--- | :--- | :--- | :--- |
| `journal_mode` | DELETE | 持久（WAL 跨重启） | 内存库只能 MEMORY/OFF；事务中不可改 |
| `page_size` | 4096 | 持久 | 仅建库时或 `VACUUM` 时可改 |
| `auto_vacuum` | NONE | 持久 | 必须在建任何表**之前**决定；只截 freelist、不整理碎片 |
| `encoding` | UTF-8 | 持久 | ATTACH 的库编码必须一致，否则 ATTACH 失败 |
| `foreign_keys` | **OFF** | 每连接 | 最大的坑，每个连接都要单独开 |
| `synchronous` | FULL | 每连接 | WAL 推荐 NORMAL，但要知道它丢什么 |
| `cache_size` | -2000（约 2 MB） | 每连接 | 负数 = KiB |
| `busy_timeout` | 0（不等待） | 每连接 | 并发写场景必调 |
| `wal_autocheckpoint` | 1000 页 | 每连接 | 0 = 关闭自动 checkpoint |
| `secure_delete` | OFF | 每连接 | 删除时零覆盖旧内容，防取证残留，有 I/O 开销 |
| `locking_mode` | NORMAL | 每连接 | EXCLUSIVE 可免共享内存跑 WAL |
| `mmap_size` | 0（禁用） | 每连接 | mmap I/O 上限 |
| `journal_size_limit` | -1（不限） | 每数据库 | 超限则截断残留日志/WAL；0 = 总是截到最小 |
| `read_uncommitted` | SERIALIZABLE | 每连接 | 除共享缓存连接之间外，选了也不生效 |

「持久」四项（`journal_mode`、`page_size`、`auto_vacuum`、`encoding`）写进数据库文件，任何连接、任何重启都认；其余只活在当前连接里——ORM 连接池每换一次连接就重置一遍，这是「明明设过却像没设」的根源。另有一批**信息类 PRAGMA**（`freelist_count`、`page_count`、`table_list`、`function_list`、`compile_options`、`database_list`）只读不写，自 3.16.0 起还能加 `pragma_` 前缀当表值函数用（`SELECT * FROM pragma_table_info('t1')`），可直接 WHERE 过滤与 JOIN，排障时比点命令好用。

## Threading Modes

三档，由编译期 `SQLITE_THREADSAFE`、启动期 `sqlite3_config`、开连接时 `sqlite3_open_v2` 标志共同决定，后者逐级覆盖前者：

| 模式 | 语义 |
| :--- | :--- |
| single-thread | 无互斥，单线程外使用即不安全；一旦选定不可升级 |
| multi-thread | 不同线程可用不同连接，但同一连接及其派生对象不可被两个线程同时用 |
| serialized（**默认**） | 每对象加锁，任意线程可调任意 API，效果等价于串行 |

`sqlite3_threadsafe()` 返回的是**编译期**值，不反映运行时改档。共享缓存模式（`sqlite3_enable_shared_cache()`，默认关）额外放开多连接共享页缓存与表级锁，但它把「保证连接级线程安全」的责任推回应用——官方态度一贯是「别用」，`SQLITE_OMIT_SHARED_CACHE` 甚至进了推荐编译选项。

## Compile Options

| 选项 | 默认 | 说明 |
| :--- | :--- | :--- |
| `SQLITE_THREADSAFE` | 1（serialized） | 0 完全移除互斥代码（快约 2%、小约 2%），此后无法再开线程模式 |
| `SQLITE_DQS` | 3（DDL/DML 都容忍双引号字符串） | **0 是文档推荐值**；运行时也可用 `SQLITE_DBCONFIG_DQS_DDL/DML` 调 |
| `SQLITE_ENABLE_FTS3/4/5`、`RTREE`、`DBSTAT_VTAB`、`SESSION`、`RBU` | 全关 | 按需开；定义 FTS3 会同时带入 FTS4 |
| JSON 函数 | **3.38.0（2022-02-22）起默认内置** | `SQLITE_ENABLE_JSON1` 已成 no-op；要省略得 `-DSQLITE_OMIT_JSON` |
| `SQLITE_DEFAULT_AUTOMATIC_INDEX` | 开 | 只决定新连接的初始 `PRAGMA automatic_index`；要连功能一起去掉用 `SQLITE_OMIT_AUTOMATIC_INDEX` |
| `SQLITE_DEFAULT_WAL_AUTOCHECKPOINT` | 1000 页 | 自动 checkpoint 默认阈值 |
| `SQLITE_SECURE_DELETE` | 关 | 定义则 `secure_delete` 默认开 |
| `SQLITE_DEFAULT_FOREIGN_KEYS` | 0 | 设 1 则新连接默认强制外键——比每连接 PRAGMA 可靠 |
| `SQLITE_ENABLE_ICU` | 关 | 完整 Unicode 大小写折叠，须链 ICU 库 |
| `SQLITE_ENABLE_STAT4` | 关 | `ANALYZE` 收集全列直方图；**但违反 QPSG** |
| `SQLITE_OMIT_*` | 未定义 | 官方明言「mostly unsupported」，只在与规范源码构建合用时可靠，配 amalgamation 不保证有效 |

文档的「推荐编译选项」清单（全用上约小 3% 库、少 5% CPU 周期）：`SQLITE_DQS=0`、`SQLITE_THREADSAFE=0`（仅单线程场景）、`SQLITE_DEFAULT_MEMSTATUS=0`、`SQLITE_DEFAULT_WAL_SYNCHRONOUS=1`（WAL 下用 NORMAL 同步，兼得速度与不损坏）、`SQLITE_LIKE_DOESNT_MATCH_BLOBS`、`SQLITE_MAX_EXPR_DEPTH=0`、`SQLITE_OMIT_DECLTYPE`、`SQLITE_OMIT_DEPRECATED`、`SQLITE_OMIT_PROGRESS_CALLBACK`、`SQLITE_OMIT_SHARED_CACHE`、`SQLITE_OMIT_AUTOINIT`（**须先手动 `sqlite3_initialize()`，否则可能段错误**）、`SQLITE_STRICT_SUBTYPE=1`。这些库级选项可写进自定义头文件，经 `-DSQLITE_CUSTOM_INCLUDE=myconfig.h` 一次引入，不必逐条传编译器。启用非标准组合后，官方建议先跑测试套件。

## Distribution Forms

**amalgamation**：100 多个源文件拼成单个 `sqlite3.c`（内含 `sqlite3.h`），截至 3.37.0 约 238K 行、8.4 MB；单翻译单元带来 5%~10% 的跨过程内联收益。**split amalgamation**（`sqlite3-1.c`…`sqlite3-7.c` + `sqlite3-all.c`）是为绕开调试器 32768 行号限制的等价形态，功能完全相同。对调试器行号不敏感就用单文件，少一个编译单元是一个编译单元。

## Links

- [SQLite](/docs/CS/DB/SQLite.md)
- [DataBases](/docs/CS/DB/DB.md)
- [WAL](/docs/CS/DB/Concept/WAL.md)
- [H2](/docs/CS/DB/h2/H2.md)
- [Transactions_and_Locking](/docs/CS/DB/SQLite/Transactions_and_Locking.md)

## References

1. [Pragma statements supported by SQLite](https://sqlite.org/pragma.html)
2. [Compile-time Options](https://sqlite.org/compile.html)
3. [Using SQLite In Multi-Threaded Applications](https://sqlite.org/threadsafe.html)
4. [The SQLite Amalgamation](https://sqlite.org/amalgamation.html)
