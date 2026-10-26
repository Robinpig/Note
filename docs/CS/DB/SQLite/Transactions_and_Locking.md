## Introduction

SQLite 的并发形状一句话能说完：**任意多个读者、至多一个写者**。这不是缺陷而是设计选择——它换来的是零配置、无守护进程、崩溃自恢复，以及「数据库就是一个文件」的全部便利。本页讲清楚这个形状是怎么落地的：回滚日志模式下的五档文件锁、WAL 模式下的读者快照，以及两者共用的 `SQLITE_BUSY` 家族错误码。默认隔离级别是 **SERIALIZABLE**（官方 pragma 文档原话），读事务看到的是开始时刻的一致快照。

## Transactions and Autocommit

除少数 PRAGMA 外，任何访问数据库的语句不在事务中时都会**自动开启一个隐式事务**，并在最后一条语句结束时自动提交。语句「结束」的判据是游标关闭——`sqlite3_reset()` 或 `sqlite3_finalize()` 才保证它发生；开着的增量 BLOB I/O 句柄（`sqlite3_blob`）同样让语句悬着。

`BEGIN` 关掉的就是这个自动提交。三种开头语义差别很大：

| 开头 | 行为 |
| :--- | :--- |
| `BEGIN DEFERRED`（默认） | 只置标志，首条语句到了才真正起事务；首条是 SELECT 则起读事务，之后的写语句尝试**升级**为写事务 |
| `BEGIN IMMEDIATE` | 立即起写事务；别的连接已有写事务则直接 `SQLITE_BUSY` |
| `BEGIN EXCLUSIVE` | 立即起写事务；WAL 下与 IMMEDIATE 等价，其它模式下还禁止他人读 |

「先读后写」的应用在 DEFERRED 下有个隐蔽陷阱：读了一堆，写的时候发现快照已过期（WAL 下报 `SQLITE_BUSY_SNAPSHOT`），整段逻辑白做。预知要写就用 `BEGIN IMMEDIATE`——把冲突前移到事务开头，是官方给出的标准解法。

升级失败、或 `COMMIT` 时撞上别人的读事务，都会返回 `SQLITE_BUSY`；此时**事务仍然活着**，COMMIT 可以稍后重试。另有一类错误（`SQLITE_FULL`、`SQLITE_IOERR`、`SQLITE_INTERRUPT`、`SQLITE_NOMEM`）可能触发自动回滚——SQLite 会尽量只撤当前语句保留事务，但撤不干净时整事务回滚。应用可用 `sqlite3_get_autocommit()` 或 `sqlite3_txn_state()` 判断实际落在了哪种，然后补一条显式 `ROLLBACK` 把状态归一（对已回滚的事务再 ROLLBACK 只是报错，无害）。

## Rollback Journal and Locking

默认 journal 模式 DELETE：写事务先把**原始页**拷进同目录的 `<db>-journal`，改内存页，提交时刷盘并**删除 journal——删除动作即提交**。数据库文件上维护五种锁：

| 锁 | 语义 |
| :--- | :--- |
| UNLOCKED | 未持锁，缓存数据一律可疑 |
| SHARED | 可读；任意多连接同时持有，但存在期间无人可写 |
| RESERVED | 唯一；表示「计划写」，期间**仍允许新读者加入** |
| PENDING | 唯一；挡住新读者、等既有读者撤离，是拿 EXCLUSIVE 的垫脚石 |
| EXCLUSIVE | 唯一；写盘必需，与任何其它锁不共存 |

两个设计细节值得记住。**PENDING 锁是为消灭写者饥饿**：若读者络绎不绝，只靠 SHARED 锁写者永远等不到机会，PENDING 挡住新读者即可保证既有读者终将排空（v2 曾在这里翻车，v3 的解法）。**锁升级被压到最后一刻**：首个 SELECT 才取 SHARED、首个写才取 RESERVED、直到 spill 或提交才升 EXCLUSIVE——把阻塞读方的窗口缩到最小。

崩溃留下的是**热日志**：文件存在、大于 512 字节、头部合法、其上无 RESERVED 锁。之后任何连接**读之前必先回滚**：取 SHARED → 发现热日志 → PENDING + EXCLUSIVE → 回滚 → 等落盘 → 删日志 → 释放、保留 SHARED。回滚完成后多数场景自动把 journal 模式体现为三种提交收尾：DELETE（删文件）、TRUNCATE（截为零）、PERSIST（用零覆写头）。ATTACH 多库事务另有一个只记文件名的 super-journal，提交时刻 = 删 super-journal。

## WAL Mode

WAL 把「先拷原页再改原页」颠倒成「原页不动、变更追加到日志」：数据库旁多出 `-wal`（追加写）与 `-shm`（wal-index 的共享内存载体，mmap、通常不超过 32 KiB、从不 fsync）。二进制布局见 [File_Format](/docs/CS/DB/SQLite/File_Format.md)。

读者开始一次读时记下 WAL 中最后一个有效提交帧的位置（wal-index 里的 **mxFrame**），整个读事务看到单一时间点快照；读某页先查 mxFrame 之前 WAL 里有没有新副本，没有才回源数据库文件。由此得到 WAL 的并发形状：**读者永不阻塞、读者不阻塞写者，但同一时刻仍只有一个写者**。代价是所有进程必须在同一台机器上——WAL 不能用于网络文件系统。若开库前设 `PRAGMA locking_mode=EXCLUSIVE`，单进程场景可以完全不用共享内存跑 WAL。

**journal_mode=WAL 是持久设置**（写进数据库头第 18/19 字节，1 改 2），跨连接、跨重启生效；用命令行工具 `PRAGMA journal_mode=WAL;` 执行一次即全库切换，无需改代码。这个字节同时是个版本闸门：3.7.0 之前的老库见到版本号 2 会报「file is encrypted or is not a database」，防止它们错误恢复。

Checkpoint 把 WAL 搬回数据库文件，四种强度：PASSIVE（尽力而为、默认）、FULL、RESTART（顺带重置 WAL）、TRUNCATE（保证跑完但期间阻塞读者）。**自动 checkpoint 阈值默认 1000 页**（默认页大小下约 4 MB）。两个副作用要提前知道：checkpoint 遇到超过任一读者 mxFrame 的页必须停步——**长期读者会让 checkpoint 饥饿、WAL 无界增长**；checkpoint 本身必须 sync，繁忙磁盘上会造成「latch-up」，可关掉自动 checkpoint 改到独立线程做。

`-wal` 是持久状态的一部分：拷贝/移动数据库必须连同它一起带走，否则丢已提交事务；唯一安全的删除方式是开库后立即关库，让最后一个连接做完整 checkpoint 再删。已知缺陷一例：WAL-reset 竞态（影响 3.7.0~3.51.2，两个以上连接同时写/checkpoint 时第二个可能漏事务）修于 **3.51.3**。

## Busy Handling and Error Codes

拿不到锁时的默认行为是**直接返回 `SQLITE_BUSY`**——默认没有 busy handler（等价超时 0）。要排队等，用 `PRAGMA busy_timeout=<ms>` 或 `sqlite3_busy_timeout()`。WAL 下仍会 `SQLITE_BUSY` 的三种情况：对端以 exclusive 锁模式开库、最后连接关闭清理 WAL/shm、崩溃后首个连接正在恢复。

| 错误码 | 何时出现 |
| :--- | :--- |
| `SQLITE_BUSY`(5) | **别的连接**（通常是别的进程）持锁；可出现在事务开始、写过程中或提交时 |
| `SQLITE_BUSY_RECOVERY`(261) | 别的进程正在崩溃后恢复 WAL 数据库 |
| `SQLITE_BUSY_SNAPSHOT`(517) | WAL 下把读事务升级为写事务时，发现自己的快照已被别人的写入作废——**回滚重试，或一开始就用 BEGIN IMMEDIATE** |
| `SQLITE_LOCKED`(6) | **同一连接内部**冲突（如同连接另一线程正读某表时 DROP 它），或共享缓存连接间冲突 |
| `SQLITE_LOCKED_SHAREDCACHE`(262) | 共享缓存模式下另一连接正在改同一记录 |

BUSY 与 LOCKED 的分界线就是「跨连接」与「连接内」：前者等一等能好，后者基本是代码写错了。

## Facts Worth Pinning Down

1. **`BEGIN` 本身不取锁**；`BEGIN IMMEDIATE` 才立刻占写位。并发写场景下的第一条军规。
2. **`COMMIT` 失败不等于事务结束**——事务还活着，可以重试；但应用必须知道自己在重试什么。
3. **自动回滚只覆盖四类错误**，且未来版本可能扩展清单；正确姿势是事后显式 `ROLLBACK` 归一，别赌 SQLite 撤到了哪一步。
4. **「删 journal = 提交」是回滚模式的字面事实**：管理员把 `-journal` 当垃圾删掉，等于替 SQLite 做了它永远不会做的「提交」，数据库直接损坏。
5. **WAL 下 `synchronous=NORMAL` 提交不 fsync**，掉电可能丢最近提交；要全持久用 FULL，代价是每次提交一次 fsync。跨模式语义见 [Configuration](/docs/CS/DB/SQLite/Configuration.md)。

## Links

- [SQLite](/docs/CS/DB/SQLite.md)
- [DataBases](/docs/CS/DB/DB.md)
- [WAL](/docs/CS/DB/Concept/WAL.md)
- [File_Format](/docs/CS/DB/SQLite/File_Format.md)
- [H2 Transactions_and_Locks](/docs/CS/DB/h2/Transactions_and_Locks.md)
- [MySQL MVCC](/docs/CS/DB/MySQL/Mvcc.md)

## References

1. [Write-Ahead Logging](https://sqlite.org/wal.html)
2. [File Locking And Concurrency In SQLite Version 3](https://sqlite.org/lockingv3.html)
3. [Transaction](https://sqlite.org/lang_transaction.html)
4. [Result and Error Codes](https://sqlite.org/rescode.html)
