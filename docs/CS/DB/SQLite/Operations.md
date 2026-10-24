## Introduction

SQLite 的运维面小到容易让人忘记它存在，但该有的都有：在线备份、空间回收、检查点、完整性检查、崩溃恢复。这一页按「备份 → 空间 → checkpoint → 体检 → CLI」排下来，覆盖日常养护的完整回路。核心提示先说：**任何「拷贝文件」式的备份在 WAL 模式下都是错的**，见下节。

## Backup and Restore

**在线备份 API**（`sqlite3_backup_init/step/finish`）是备份活动数据库的原始方法：分页把源库拷成目标库，目标整体替换，完成时它是源库开始备份时刻的**逐位快照**。它解决了「加共享锁 + cp 文件」的三个缺陷：写者不必久等（只在真正读页时短暂加锁）、能备份内存库、拷贝中途掉电不会留下损坏的备份文件。

- `sqlite3_backup_step(p, n)` 每次拷 n 页，**-1 表示一次拷完**；分页 + 睡眠的写法让源库读锁在间隙里释放，其他连接可继续用。错误码一律挂在**目标连接**上，从 `sqlite3_errcode(pTo)` 统一读。
- **源库在备份期间被改会怎样**：外部连接写文件型源库 → 下次 step 时**整个备份重新开始**；同进程同句柄写文件型源库 → 目标随源自动同步，备份继续。所以频繁重写的库可能让分页备份永远完不成——这是 API 的已知边界，不是 bug。
- 内存库当目标时，若源与目标页大小不同会以 `SQLITE_READONLY` 失败；先把空的内存目标 `PRAGMA page_size` 对齐即可。

**`VACUUM INTO 'file'`**（3.27.0 起）是 SQL 层的替代：产出的是**清理过**的副本——体积最小、无取证残留；备份 API 则省 CPU、可增量。两者取舍就是「要干净还是要快」。`sqlite3_rsync` 程序走 SSH 做远程复制，是第三种选择。CLI 侧对应 `.backup` / `.restore` 点命令。

## VACUUM and Space Reclamation

`VACUUM` 把库内容拷进临时文件再整体覆盖回原文件（因此**需要约两倍磁盘空间**，且必须独占、事务中跑不了）。它一次解决三件事：回收 freelist 空闲页缩小文件、把每张表/索引重排成连续存储消碎片、**抹掉已删内容的取证残留**（等于全库级 `secure_delete`）。

几个必须知道的行为：

- 它会**改变没有显式 INTEGER PRIMARY KEY 的表的 rowid**——依赖 rowid 稳定性的应用要么显式声明主键，要么别 VACUUM。
- 非 WAL 模式下，`page_size` 与 `auto_vacuum` 可以在 VACUUM 前一并改掉再重建；WAL 模式下只有 `auto_vacuum` 能这么改。
- 未 finalize 的语句会持着读事务让 VACUUM 失败；别的连接持写锁同样失败。
- 对 ATTACH 的库加 schema 名即可真空（3.15.0 起，之前 schema 名被静默忽略）。

**auto_vacuum** 是另一条路：`FULL` 每事务提交把 freelist 页挪到文件尾并截断；`INCREMENTAL` 只记录页映射、由 `PRAGMA incremental_vacuum(N)` 显式触发。它省掉全库重建，但**不做重排、不压半满页**，反而可能加剧碎片——官方对 auto_vacuum 的态度一向冷淡。前提同样是建任何表之前决定。

## Checkpoint Operations

WAL 模式下的日常：默认自动 checkpoint（1000 页）多数场景够用，需要控制时用 `PRAGMA wal_checkpoint`（PASSIVE/FULL/RESTART/TRUNCATE 四档，见 [Transactions_and_Locking](/docs/CS/DB/SQLite/Transactions_and_Locking.md)）。`PRAGMA journal_size_limit=N`（默认 -1 不限，0 = 总是截到最小）限制提交或 checkpoint 后残留的 `-journal` / `-wal` 体积——exclusive 锁模式与 PERSIST journal 模式下日志文件会被反复覆盖复用，大事务后可能留个巨大的尾巴，这条 pragma 就是管这个的。注意它**只能对单个数据库设**，ATTACH 了的库要分别设。

## Integrity and Recovery

| 工具 | 作用 |
| :--- | :--- |
| `PRAGMA integrity_check` | 底层格式与一致性全查：记录错序、页缺失、索引条目缺失或多余、UNIQUE/CHECK/NOT NULL 违例、freelist 完整性、区域重复使用。O(N log N)，最多报 N 个错误（默认 100）后停；**不查外键**（那是 `foreign_key_check`）。3.33.0 起可带表名只查单表 |
| `PRAGMA quick_check` | 同上但不验 UNIQUE 与索引-表匹配，O(N)，快得多 |
| CLI `.recover` | 绕过 SQL 接口直接解析页面，从损坏库里尽可能捞数据；`.dump` 遇损即停，`.recover` 不会。捞不动的孤儿行进 `lost_and_found` 表 |
| CLI `.dbinfo` / `.stats` | 页大小、页数、freelist、编码等文件级状态与语句级统计 |

怀疑文件损坏时的顺序：`.dbinfo` 看文件级事实 → `quick_check` 快速定性 → `integrity_check` 定位 → 确认修不了就 `.recover` + `VACUUM INTO` 重建，而不是继续读写。

## The CLI

`sqlite3` shell 与库是两回事：点命令由 CLI 自己解释，不过 `sqlite3_prepare` 接口。最常用的一批：

| 命令 | 用途 |
| :--- | :--- |
| `.mode box/csv/json/markdown...` | 输出格式；`.mode --once box` 只生效一条 |
| `.import FILE TABLE` | 导 CSV；先设 `.mode`，`--skip 1` 跳表头 |
| `.dump` / `.read` | 全库转 SQL 文本 / 从文件回灌，管道即可迁移 |
| `.schema ?PATTERN?` | 看 CREATE 语句 |
| `.backup` / `.restore` | 文件级备份恢复 |
| `.eqp on` / `.explain on` | 每条语句自动跟 EXPLAIN QUERY PLAN / EXPLAIN |
| `.archive`（`-A`） | SQLAR/ZIP 归档管理，接口像 tar；`.ar -c` 创建、`-x` 解包、`-t` 列表 |
| `.recover` | 见上节 |
| `.diskused` | 空间占用分析（3.54.0 新增，替代 sqlite3_analyzer） |
| `.expert` | 实验性索引推荐 |
| `.connection` / `.conn` | 多连接管理（3.37.0 起，编号 0~9） |
| `.parameter set` | 命名参数绑定管理（经 `sqlite_parameters` 临时表） |

命令行侧：`-readonly`、`-init FILE`、`-batch`、`-json`、`-A ARGS`。**`--safe` 模式**禁掉一切可能改动宿主机的功能（`.open`、ATTACH、`load_extension`、`readfile`/`writefile`、`.backup`/`.import`/`.shell` 等），用于跑来源不明的 SQL 脚本；确需放行单条已审计命令时用 `--nonce NONCE` + `.nonce NONCE` 精确解禁——滥用它有风险，当最后手段。

另一个 CLI 特有技巧：ZIP/JAR/DOCX 可直接当库打开，呈现为 `zip(name, mode, mtime, sz, rawdata, data, method)` 虚表——排障时翻 Office 文档结构比解压快。

## Monitoring

常看的两条：`PRAGMA freelist_count` / `PRAGMA page_count` 的比值（空闲页占比，决定要不要 VACUUM）与 `-wal` 文件体积（决定 checkpoint 是否被长读者饿死）。`PRAGMA table_list`（3.37.0 起，带 `strict` / `wr` 标记）与 dbstat 虚表（需 `SQLITE_ENABLE_DBSTAT_VTAB`）回答「空间被谁占了」。判断「库还能不能信」用 `integrity_check`，见上节。

## Links

- [SQLite](/docs/CS/DB/SQLite.md)
- [DataBases](/docs/CS/DB/DB.md)
- [WAL](/docs/CS/DB/WAL.md)
- [Transactions_and_Locking](/docs/CS/DB/SQLite/Transactions_and_Locking.md)
- [H2 Tools_and_Operations](/docs/CS/DB/h2/Tools_and_Operations.md)
- [RocksDB Operations](/docs/CS/DB/RocksDB/Operations.md)

## References

1. [SQLite Backup API](https://sqlite.org/backup.html)
2. [VACUUM](https://sqlite.org/lang_vacuum.html)
3. [Command Line Shell For SQLite](https://sqlite.org/cli.html)
4. [Pragma statements supported by SQLite](https://sqlite.org/pragma.html)
