## Introduction

SQLite 是一个**实现 SQL 数据库引擎的 C 语言库**：没有独立进程、没有监听端口，应用把 `sqlite3.c` 编进自己体内，通过函数调用直接读写数据库文件。官方对它的定位原话是「small, fast, reliable, choose any three」，而它真正的竞争对手不是 MySQL、PostgreSQL，而是 `fopen()`——SQLite 解决的是「单个应用在一台设备上的本地数据存储」这个问题，与客户端/服务器数据库面对的问题本就不同。

三条常被忽略的底色：**源码公有领域（public domain）**，可以嵌入任何商业产品而不产生任何许可义务；**部署形态是单个跨平台文件**，字节序与字长差异都被文件格式吸收；**部署量是主流数据库中最大的**——所有手机与大多数计算机里都有它，官方称 the most deployed database engine in the world。

本页是 SQLite 的**枢纽页**：只放定位、架构总览、选型与最要紧的几条反直觉事实；文件格式、事务与锁、查询规划、类型系统、配置、运维六个方向各有分册展开。版本锚点 **3.54.1（2026-10-16）**，全部结论以 sqlite.org 官方文档与发布日志为准。需要警惕「文档滞后于代码」在这个项目里是常态：`vdbe.html` 描述的仍是 2.8.0 的栈式虚拟机（3.x 起已是寄存器式），`amalgamation.html` 的代码行数截至 3.37.0，凡涉版本数字都在分册中标注了出处时点。

## Architecture

一次查询在 SQLite 内部走完全在进程内的四段流水线，中间没有任何网络边界：

```
应用代码
  │  sqlite3_prepare_v2() / sqlite3_step() / sqlite3_bind_*()
  ▼
SQL 编译器 ── tokenizer → Lemon 生成的 LALR(1) 解析器 → 代码生成器
  │            产出：一条 VDBE 字节码程序（虚拟计算机的指令序列）
  ▼
VDBE（Virtual Database Engine） ── 寄存器虚拟机，逐条执行 OP_* 指令
  │
  ▼
B-tree + Pager ── 页缓存（默认约 2 MB）→ 文件锁管理 → OS 文件接口（VFS）
  │
  ▼
单个数据库文件（+ 可选的 -journal / -wal / -shm 伴随文件）
```

- **SQL 编译器**把每条语句编译成 VDBE 程序；解析器由 Lemon 生成，文法在源码 `src/parse.y`。同一连接里反复执行同一条 SQL 只需编译一次（prepared statement）。
- **VDBE 是 SQLite 的心脏**，几乎所有子系统都以某种方式支撑它。3.x 的 VDBE 是寄存器式虚拟机：每条指令带 5 个操作数。执行模型与观测手段见 [Query_Planner](/docs/CS/DB/SQLite/Query_Planner.md)。
- **Pager** 以页为单位读写、管理页缓存与文件锁，把上层的 B-tree 与底下的文件系统隔开。VFS 可替换，使 SQLite 能跑在内存、压缩文件乃至某些特殊介质上。
- **扩展以虚拟表形态挂进来**：FTS5（全文检索）、JSON1（SQL 里的 JSON 函数）、RTREE（空间索引）、SESSION/RBU 等默认编进 amalgamation 但由 `#ifdef` 关断，编译开关见 [Configuration](/docs/CS/DB/SQLite/Configuration.md)。

源码分发形态是 **amalgamation（聚合单文件）**：100 多个源文件拼成单个 `sqlite3.c`，内含 `sqlite3.h`，拷进项目直接编译即可；单翻译单元让编译器能做跨过程内联，官方实测快 5%~10%。对调试器不友好（行号超 32768）时可用 split amalgamation。

## Map of This Section

六个分册对应六类问题，也对应使用 SQLite 时六种不同的翻车方式：

- **[File_Format](/docs/CS/DB/SQLite/File_Format.md)**——「库文件到底长什么样」。100 字节头、b-tree 页、记录 serial type、varint、溢出阈值，以及 `-wal` 与 `-journal` 两种伴随文件的二进制布局。要敢用十六进制编辑器排障、要把库当数据交换格式、或者评估「拷贝文件就算备份」的风险，都从这页读起。
- **[Transactions_and_Locking](/docs/CS/DB/SQLite/Transactions_and_Locking.md)**——「并发为什么是这个形状」。回滚日志的五档锁、热日志回滚、WAL 的读者快照与 checkpoint、以及 `SQLITE_BUSY` 家族错误码。单写者不是缺陷而是设计，理解它才能设计出不炸的重试策略。
- **[Query_Planner](/docs/CS/DB/SQLite/Query_Planner.md)**——「SQL 是怎么跑的」。VDBE 寄存器机、嵌套循环规划器、覆盖索引 / LIKE / OR 三类优化、自动索引的触发条件与 N3 规划器。慢查询调优的唯一入口。
- **[Type_System](/docs/CS/DB/SQLite/Type_System.md)**——「为什么本地全绿、上线即炸」。柔性类型、五档亲和性、rowid 三种行模型，以及官方自己列出的怪癖清单。从 MySQL/PostgreSQL 迁过来的应用，问题十有八九出在这页。
- **[Configuration](/docs/CS/DB/SQLite/Configuration.md)**——「哪些开关值得拧」。PRAGMA 默认值与作用域（哪些写进文件、哪些只活一个连接）、三档线程模型、编译期选项表。默认值没有一条是随便定的，但也没有一条替你考虑了应用场景。
- **[Operations](/docs/CS/DB/SQLite/Operations.md)**——「日常怎么养」。在线备份 API 与 `VACUUM INTO`、VACUUM 与空间回收、checkpoint 运维、integrity_check 与 `.recover`、CLI 的 `--safe` 模式与 SQLAR 归档。

## Applicable Scenarios

官方给的判据朴素得可爱：**数据与应用是否被网络分开、是否有许多并发写者、数据是否大到放不进单个文件**——三个都答「否」，就选 SQLite。

适合：手机/机顶盒/车载/工控/医疗设备等无人值守环境的嵌入式存储；桌面应用的**应用文件格式**（File/Open 就是 `sqlite3_open`，Save 变多余，Save As 用 backup API）；中低流量网站（保守线约 10 万次/天，SQLite 官网自身每天 40~50 万请求、单物理机与 23 台 VM 共享、负载低于 0.1）；本地数据分析（CSV 导入 + SQL 处理，结果单文件可邮件）；企业库的本地缓存；数据传输与归档格式（SQLAR 可平替 ZIP）；以及替代自造格式的临时/内部数据文件。

不适合：多客户端跨网写同一库文件（POSIX advisory lock 在许多 NFS 上有缺陷，官方原话是不要在网络文件系统上用）、写密集型高并发（任意时刻单写者，典型写事务几十毫秒，靠 `busy_timeout` 排队）、接近 TB 级且还要继续长的数据集。

| 条件 | 选择 |
| :--- | :--- |
| 数据与应用通过网络分离？ | 客户端/服务器 |
| 许多并发写入者？ | 客户端/服务器 |
| 数据量大到无法放入单个磁盘文件？ | 客户端/服务器 |
| 其他情况（设备本地存储、低写入并发、小于 1TB） | SQLite |

数据库体积的硬顶约 **281 TB**（2^48 字节），但多数文件系统对单文件的上限先到。

## Facts Worth Pinning Down

最容易被默认值坑到的几条，完整清单在 [Type_System](/docs/CS/DB/SQLite/Type_System.md)：

1. **`foreign_keys` 默认 OFF**。每个连接都要单独 `PRAGMA foreign_keys=ON`——ORM 连接池换连接即失效，是最经典的「本地全绿、上线失约束」。
2. **PRIMARY KEY 允许 NULL**（历史 bug，太多库依赖故保留），要真约束须显式 `NOT NULL`。
3. **`SELECT 1='1'` 为 false**：整数字面量与文本字面量是两类，主流引擎都返回 true。
4. **`upper()/lower()` 只折叠 ASCII**；要完整 Unicode 支持须编译进 ICU。
5. **WAL 的 `-wal` 必须和库一起拷贝**，删除它的唯一安全方式是开库即关库；反过来，干净关闭的库不应残留 `-wal`。
6. **WAL 下 `synchronous=NORMAL` 会丢最近提交**——这是特性不是 bug，但把它当「全持久配置」用就是事故。
7. **`page_size` 与 `auto_vacuum` 是创建时决策**，事后改只能 `VACUUM` 重建（详见 [Operations](/docs/CS/DB/SQLite/Operations.md)）。
8. **默认没有 busy handler**（等价超时 0），锁冲突直接 `SQLITE_BUSY`；并发写场景必须显式设 `busy_timeout`。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [WAL](/docs/CS/DB/WAL.md)
- [H2](/docs/CS/DB/h2/H2.md)
- [RocksDB](/docs/CS/DB/RocksDB/RocksDB.md)
- [Indexes](/docs/CS/DB/Index.md)

## References

1. [Appropriate Uses For SQLite](https://sqlite.org/whentouse.html)
2. [The SQLite Amalgamation](https://sqlite.org/amalgamation.html)
3. [Using SQLite In Multi-Threaded Applications](https://sqlite.org/threadsafe.html)
4. [Release History Of SQLite](https://sqlite.org/changes.html)
5. [SQLite Copyright](https://sqlite.org/copyright.html)
