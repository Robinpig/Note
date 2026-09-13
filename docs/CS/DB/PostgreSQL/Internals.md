## Introduction

本章从源码层面梳理 PostgreSQL 的实现机制，目标读者是希望理解 PG 内部协作原理与扩展切入点的开发者，而非完整的代码逐行阅读指引。所有路径相对于 PostgreSQL 源码根目录 `src/`。

> 推荐先阅读一遍 PG 官方手册的 *"Overview of PostgreSQL Internals"*，再回看本章会更有体感。

## Source Layout

> 基于 PostgreSQL 18.0（REL_18_STABLE）的实际目录布局。源码主要由 C 与少量汇编组成。

### 顶层结构

```
postgresql/                       # git clone 后根目录
├── configure                     # 编译入口脚本（autotools）
├── config/                       # autotools 配置脚本
├── doc/                          # 官方文档（SGML → HTML/PDF）
├── contrib/                      # 扩展模块（pg_stat_statements、pgcrypto 等）
├── src/
│   ├── backend/                  # 【核心】后端代码
│   ├── bin/                      # 工具程序（pg_ctl / initdb / pg_dump / psql）
│   ├── common/                   # 前后端共享（日志、配置解析、字符串）
│   ├── fe_utils/                 # 前端命令行工具复用库
│   ├── include/                  # 全局头文件
│   ├── interfaces/               # 客户端接口（libpq / ecpg）
│   ├── port/                     # 平台适配层（Linux / Darwin / Win32）
│   ├── template/                 # 平台模板（linux / solaris）
│   ├── test/                     # 回归与隔离测试
│   ├── tools/                    # 构建工具（pgindent / msvc）
│   └── timezone/                 # 时区数据与解析
└── src/Makefile.global.in
```

### 架构模块 → 源码文件映射（PG 18）

> 这是 GDB 调试与源码定位的关键速查表。

| 架构模块 | 子模块 | 关键源码文件 | 说明 |
| --- | --- | --- | --- |
| 主进程 | Postmaster | `src/backend/postmaster/postmaster.c` | 启动后台进程、监听连接、信号处理 |
|  | pgstat | `src/backend/postmaster/pgstat.c` | 统计信息收集器 |
|  | autovacuum | `src/backend/postmaster/autovacuum.c` | 自动 VACUUM 调度 |
| 连接与协议 | FE/BE 协议 | `src/backend/libpq/` | 服务端 libpq |
|  | 主循环 | `src/backend/tcop/postgres.c` | `PostgresMain()` 接收查询 |
| 解析器 | SQL 解析 | `src/backend/parser/gram.y` | Bison 语法 → `gram.c` |
|  | 词法 | `src/backend/parser/scan.l` | Flex 词法 → `scan.c` |
|  | 入口 | `src/backend/parser/parser.c` | `raw_parser()` |
| 重写器 | 规则系统 | `src/backend/rewrite/rewriteHandler.c` | `RewriteQuery()` 处理 VIEW/RULE |
| 优化器 | 路径生成 | `src/backend/optimizer/path/allpaths.c` | `set_rel_pathlist` |
|  | 代价估算 | `src/backend/optimizer/path/costsize.c` | 代价模型 |
|  | 计划生成 | `src/backend/optimizer/plan/planner.c` | `standard_planner()` |
|  | 计划创建 | `src/backend/optimizer/plan/createplan.c` | 从路径生成 Plan |
|  | 遗传优化 | `src/backend/optimizer/geqo/` | GEQO |
| 执行器 | 调度 | `src/backend/executor/execProcnode.c` | 递归执行 Plan 树 |
|  | 顺序扫描 | `src/backend/executor/nodeSeqscan.c` | |
|  | 索引扫描 | `src/backend/executor/nodeIndexscan.c` | |
|  | Nestloop | `src/backend/executor/nodeNestloop.c` | |
|  | HashJoin | `src/backend/executor/nodeHashjoin.c` | |
| 存储管理 | Buffer Manager | `src/backend/storage/buffer/bufmgr.c` | `BufferAlloc()`、`ReadBuffer()` |
|  | 缓冲初始化 | `src/backend/storage/buffer/buf_init.c` | |
|  | Page | `src/backend/storage/page/bufpage.c` | `PageGetItem` |
|  | SMGR 抽象 | `src/backend/storage/smgr/smgr.c` | 存储管理器接口 |
|  | 磁碟后端 | `src/backend/storage/smgr/md.c` | md = magnetic disk |
|  | LMGR | `src/backend/storage/lmgr/lmgr.c` | 锁管理 |
| 事务系统 | MVCC | `src/backend/access/transam/xact.c` | Begin/Commit/Abort |
|  | CLOG | `src/backend/access/transam/clog.c` | 事务提交状态 |
|  | MultiXact | `src/backend/access/transam/multixact.c` | 行级锁共享 |
|  | Lazy VACUUM | `src/backend/access/transam/vacuumlazy.c` | |
| WAL | XLog 核心 | `src/backend/access/transam/xlog.c` | `XLogInsert()`、`XLogFlush()` |
|  | WAL 构造 | `src/backend/access/transam/xloginsert.c` | 记录构建 |
|  | 崩溃恢复 | `src/backend/access/transam/xlogrecovery.c` | |
|  | WAL 解析 | `src/bin/pg_waldump/` | 工具 |
| 索引 | B-Tree | `src/backend/access/nbtree/` | 插入/搜索/分裂 |
|  | GIN | `src/backend/access/gin/` | 倒排索引（全文搜索） |
|  | GiST | `src/backend/access/gist/` | 空间索引 |
|  | Hash | `src/backend/access/hash/` | 哈希索引 |
| 锁管理 | 主锁表 | `src/backend/storage/lmgr/lock.c` | `LockAcquire` / `LockRelease` |
|  | PROC | `src/backend/storage/lmgr/proc.c` | 后端进程结构 |
|  | 死锁 | `src/backend/storage/lmgr/deadlock.c` | 死锁检测 |
| Catalog | 系统表 | `src/backend/catalog/pg_*.c` | `pg_class` / `pg_attribute` ... |
|  | 表命令 | `src/backend/commands/tablecmds.c` | CREATE TABLE 实现 |
| 复制 | 物理复制 | `src/backend/replication/walsender.c` | WAL 发送 |
|  |  | `src/backend/replication/walreceiver.c` | WAL 接收 |
|  | 逻辑复制 | `src/backend/replication/logical/` | 逻辑解码 |
| 公共库 | 日志 | `src/common/elog.c` | `ereport()` |
|  | 字符串 | `src/common/string.c` | |
|  | 内存上下文 | `src/backend/utils/mmgr/mcxt.c` | `MemoryContextAlloc()` |
| 工具 | pg_ctl | `src/bin/pg_ctl/pg_ctl.c` | 启停控制 |
|  | initdb | `src/bin/initdb/initdb.c` | 初始化数据目录 |
|  | psql | `src/bin/psql/` | 交互式客户端 |

### PG 18 新增/变更目录

| 路径 | 新功能 |
| --- | --- |
| `src/backend/storage/buffer/vacuum_buffer.c` | VACUUM 专用缓冲区 |
| `src/backend/executor/node_incremental_sort.c` | 增量排序 Plan 节点 |
| `src/backend/utils/sort/tuplesort_incremental.c` | 增量排序实现 |
| `src/backend/access/common/toast_compression.c` | 新压缩算法（pglz → lz4） |
| `src/backend/storage/io_direct.c` | I/O 子系统优化 |

## Build & Debug

> 来源：知乎用户 *bcAndCarl* 的「PostgreSQL 源码分析 01 / 02」系列，文章 03 中"学习路径"部分也补充了相关调试建议。下文以 PG 18 为示例，PG 13+ 基本通用。

### 1. 编译安装

依赖包（RHEL 9 / CentOS 9 / Fedora）：

```bash
sudo dnf update -y
sudo dnf install -y gcc make readline-devel zlib-devel flex bison \
                    libxml2-devel libxslt-devel openssl-devel \
                    perl-devel perl-ExtUtils-Embed python3-devel tcl-devel \
                    openldap-devel pam-devel systemd-devel uuid-devel
```

获取源码（任选其一）：

```bash
# 1) 官方 FTP
wget https://ftp.postgresql.org/pub/source/v18.0/postgresql-18.0.tar.gz
tar -xzf postgresql-18.0.tar.gz
cd postgresql-18.0

# 2) Git 仓库（推荐用于跟踪更新）
git clone https://git.postgresql.org/git/postgresql.git
cd postgresql
git checkout REL_18_STABLE
```

配置：开启调试符号、断言、可选模块：

```bash
./configure \
  --prefix=/usr/local/pgsql \
  --enable-debug \
  --enable-cassert \
  --with-openssl --with-perl --with-python --with-tcl \
  --with-libxml --with-libxslt --with-ldap --with-pam \
  --with-uuid=e2fs \
  CFLAGS="-O0 -g3"
```

- `--enable-debug`：生成调试符号，便于 GDB
- `--enable-cassert`：启用断言，帮助发现逻辑错误
- `CFLAGS="-O0 -g3"`：关闭优化 + 最详细调试信息，否则 GDB 单步会跳来跳去

编译与安装：

```bash
make -j$(nproc)
sudo make install
echo 'export PATH=/usr/local/pgsql/bin:$PATH' >> ~/.bashrc
source ~/.bashrc

psql --version    # 应输出 psql (PostgreSQL) 18.0
```

### 2. 初始化数据目录

```bash
sudo mkdir -p /usr/local/pgsql/data
sudo chown $USER /usr/local/pgsql/data
/usr/local/pgsql/bin/initdb -D /usr/local/pgsql/data
```

RHEL/CentOS 上注意 SELinux：

```bash
sudo semanage fcontext -a -t postgresql_db_t "/usr/local/pgsql/data(/.*)?"
sudo restorecon -R /usr/local/pgsql/data
```

### 3. 启动与停止

```bash
# 服务器模式（推荐用于联调）
/usr/local/pgsql/bin/pg_ctl -D /usr/local/pgsql/data -l logfile start

# 单用户模式（适合 GDB 调试单条 SQL）
/usr/local/pgsql/bin/postgres --single -D /usr/local/pgsql/data

# 验证
psql -U $USER -d postgres

# 停止
pg_ctl -D /usr/local/pgsql/data stop              # smart：等待客户端断开
pg_ctl -D /usr/local/pgsql/data -m fast stop      # fast：立即断开
```

### 4. 用 GDB 命令行调试

PG 的多进程模型下调试单条 SQL，最简单的方式是 **单用户模式 + GDB attach**：

```bash
# 终端 1：GDB 启动 postgres（单用户模式）
gdb --args /usr/local/pgsql/bin/postgres --single -D /usr/local/pgsql/data

# 终端 2：在 GDB 中设置断点
(gdb) break exec_simple_query
(gdb) break standard_planner
(gdb) break heap_insert
(gdb) run
```

调试多进程（服务器模式）：

```bash
# 启动
pg_ctl -D /usr/local/pgsql/data start

# 查找目标 backend
ps -aux | grep postgres

# 附加
gdb -p <PID>
```

GDB 中常用命令：

```
break <func>           # 在函数入口设断点
break file.c:123       # 在指定行设断点
watch variable         # 写断点
condition 1 xid > 100  # 条件断点
print/x p MyStruct     # 打印结构体
backtrace              # 调用栈
step / next / finish   # 单步
```

### 5. 用 CLion 远程调试（Windows + Linux）

CLion 支持远程开发，可以在 Windows 上编辑 Linux 上的 PG 源码并直接调试。

服务端准备：

```bash
sudo dnf install -y gcc make gdb libuuid-devel
gdb --version   # 需 ≥ 10.2
```

CLion 端配置：

1. `File > Open` 选择 PG 源码目录下的 `CMakeLists.txt`，以 Project 形式打开
2. `Settings > Build, Execution, Deployment > CMake`：
   - `Build type`: Debug
   - `CMake options`: `-DCMAKE_C_FLAGS="-O0 -g3"`
3. `Run > Edit Configurations` 添加 `Application`：
   - Executable: `/usr/local/pgsql/bin/postgres`
   - Program arguments: `--single -D ~/pgdata`
   - Working directory: 源码根目录
   - Debugger: GDB

调试技巧：

- 推荐断点：
  - `exec_simple_query` in `src/backend/tcop/postgres.c`
  - `standard_planner` in `src/backend/optimizer/plan/planner.c`
  - `heap_insert` in `src/backend/access/heap/heapam.c`
  - `BufferAlloc` in `src/backend/storage/buffer/bufmgr.c`
  - `XLogInsert` in `src/backend/access/transam/xloginsert.c`
- 配合 `postgresql.conf` 打开 debug 日志：

  ```
  log_statement = 'all'
  debug_print_plan = on
  debug_print_parse = on
  log_min_messages = debug5
  ```

- 多进程调试：用 `SELECT pg_backend_pid();` 拿到 backend PID，CLion 中 `Run > Attach to Process` 选择对应 PID
- 性能分析：`perf record -p $(pidof postgres)` 后导入 CLion 查看热点
- 内存检查：`valgrind --leak-check=full /usr/local/pgsql/bin/postgres --single -D ~/pgdata`

### 6. 推荐学习路径（5 天）

```
第 1 天：postmaster → tcop → parser
第 2 天：optimizer  → executor
第 3 天：storage/buffer + page
第 4 天：access/transam + WAL
第 5 天：access/nbtree + lmgr
```

## Design Principles

PG 源码在演化中沉淀出几条贯穿全局的设计准则：

- **进程级隔离而非线程**：默认 one-process-per-connection（`postmaster` fork 出 `postgres` 子进程），稳定性高、调试简单；代价是连接数膨胀时内存吃紧
- **可插拔的访问方法**：所有表/索引最终都通过 Storage Manager（`smgr.c`）抽象操作文件；新增存储引擎（如 OrioleDB）只需实现 SMGR 接口并注册到 `smgr_relations`
- **多层 hook / 扩展点**：`Plan hook`、`Executor hook`、`ProcessUtility hook`、`Prometheus 系列 exporter` 使用的 `PG_STAT_*` 视图等都可以被外部 C 函数替换——这也是 PG 生态强大的根源
- **WAL/存储/快照/锁分层清晰**：每个模块都是单进程内的内存子系统，相互通过显式接口通信，便于独立理解
- **系统表即 catalog**：系统表（pg_class、pg_attribute...）与用户表同构，元数据即数据，所以优化器、解析器可以直接用普通 SQL/索引读取

## Process & Connection Model

### 启动流程（PostmasterMain 调用链）

> 来源：bcAndCarl「PostgreSQL 源码分析 04：postgres 启动工作流程」（PG 18 实际代码位置，行号会随版本漂移）

`main()`（`src/backend/main/main.c`）：

```
main(argc, argv)
├── 检查 root / 初始化内存
├── MemoryContextInit()           // 创建 TopMemoryContext + ErrorContext
├── 设置 LC_* locale
├── 根据 argv[1] 分派：
│   ├── "--boot"        → BootstrapModeMain()     // initdb
│   ├── "--describe-config" → GucInfoMain()
│   └── "--single"      → PostgresSingleUserMain()
└── 其他 → PostmasterMain(argc, argv)
```

`PostmasterMain()`（`src/backend/postmaster/postmaster.c`）核心步骤：

```
PostmasterMain()
├── pqinitmask()                              // 创建 UnBlockSig / BlockSig / StartupBlockSig 信号集
├── sigprocmask(BlockSig) + pqsignal(...)      // 注册 SIGHUP/SIGINT/SIGQUIT/SIGTERM/SIGCHLD/SIGUSR1...
├── InitializeGUCOptions()                     // 注册 300+ GUC 变量为默认值（不读配置）
├── getopt 解析命令行参数
├── SelectConfigFiles()                        // 两次 ProcessConfigFile（PG 18 设计）
│   ├── 第1次：仅解析 data_directory
│   └── 第2次：完整解析 postgresql.conf + postgresql.auto.conf
├── checkDataDir() → checkControlFile() → ChangeToDataDir()
├── CreateDataDirLockFile()                    // 写 postmaster.pid，防止重复启动
├── LocalProcessControlFile(false)             // 读 pg_control，赋值 ControlFile
├── CreateSharedMemoryAndSemaphores()           // 见「Shared Buffer」章节
├── set_max_safe_fds()                         // 受 max_files_per_process 控制
├── InitPostmasterDeathWatchHandle()           // pipe() 创建死锁观察管道
├── ListenServerPort()                         // TCP / IPv6 / Unix Socket
└── StartChildProcess() + ServerLoop()         // 见下
```

关键信号处理：

- `SIGHUP` → `handle_pm_reload_request_signal`（重新加载配置）
- `SIGINT` / `SIGTERM` / `SIGQUIT` → 三种关闭模式（smart / fast / immediate）
- `SIGUSR1` → `handle_pm_pmsignal_signal`（来自子进程的 pmsignal）
- `SIGCHLD` → `handle_pm_child_exit_signal`（子进程退出）

### ServerLoop（epoll 主循环）

> 来源：bcAndCarl 04

`ServerLoop()` 是 Postmaster 的主事件循环，基于 **epoll** 实现 IO 多路复用：

```
epoll_create() → epoll_ctl() → epoll_wait()
                  ▲                        │
                  └──── 监听 socket / 子进程管道 / 后端管道 / latch ─────┘
```

主要动作：

- 新连接到达 → `BackendStartup` → fork → 子进程 `PostgresMain`
- 子进程退出 → SIGCHLD → `handle_pm_child_exit_signal` → `waitpid()` 回收
- 子进程请求 → SIGUSR1 → 处理 pmsignal（promote / logrotate / cancel）
- Latch 唤醒 → ServerLoop 重新评估

GDB 调试启动流程：

```bash
gdb /usr/local/pgsql/bin/postgres
(gdb) set args -D /home/yiming/pgdata
(gdb) set follow-fork-mode child   # 跟踪 fork 出的子进程
(gdb) set detach-on-fork off       # 父进程保留控制权
(gdb) b PostmasterMain
(gdb) r
```

### Backend 启动

```
postgres -D $PGDATA
└── main()
    └── PostmasterMain()                  # src/backend/postmaster/postmaster.c
        ├── pq_init / sockets setup       # 监听 TCP / Unix socket
        ├── StartupDataBase               # 启动期回放 WAL 至一致状态
        ├── pgstat_init / autovacuum launcher fork
        └── 死循环：
            ├── select() 等待连接
            ├── BackendStartup / ClientConnection
            ├── fork() 一个 backend 子进程
            └── postmaster 回到 accept 循环
```

### Backend 启动

子进程由 `PostmasterMain` → `BackendStartup` → `fork_process` 创建，进入 `PostgresMain`（`src/backend/tcop/postgres.c`）：

```
PostgresMain
├── 协议握手（V2/V3 协议解析）
├── sigsetjmp 进入错误恢复点
└── 主循环：
    ├── ReadCommand / pg_parse
    ├── ProcessQuery / ProcessUtility
    └── 处理客户端 async 消息
```

### 客户端通信协议

PG 使用 V3 消息协议，主要消息类型（`src/backend/libpq/pqcomm.c`）：

| 字节 | 消息 |
| --- | --- |
| 'Q' | 简单查询（Query） |
| 'P' / 'B' / 'D' / 'E' / 'C' / 'S' | 扩展查询（Parse/Bind/Describe/Execute/Close/Sync） |
| 'X' | 终止连接（Terminate） |
| 'D' | 数据行（DataRow） |

扩展查询流水线允许多语句单往返，是高并发驱动和 ORM 的首选路径。

### JDBC prepareStatement 全链路（PG 18 实战）

> 来源：bcAndCarl「PostgreSQL 源码分析 09：JDBC prepareStatement SQL 的执行流程」

简单 prepare/execute 对应四个 FE/BE 消息：

```
客户端 (JDBC)                    服务端 (postgres backend)
   │                                   │
   │── Parse(name, sql, types) ────────► exec_parse_message
   │                                   │   └── pg_parse_query → Query
   │◄── ParseComplete ──────────────────
   │── Bind(name→portal, params) ──────► exec_bind_message
   │                                   │   └── 参数绑定 + 参数表达式求值
   │◄── BindComplete ───────────────────
   │── Describe(portal) ───────────────► exec_describe_message
   │◄── RowDescription ─────────────────
   │── Execute(portal, max_rows) ──────► exec_execute_message
   │                                   │   └── PortalRun → ExecutorRun
   │◄── DataRow* ──────────────────────
   │◄── CommandComplete ───────────────
   │── Sync ───────────────────────────► 无意义，告诉 backend 处理 pending 状态
```

对应 `PostgresMain` 主循环里连续 4 次 `ReadCommand → dispatch`：

```text
1 ReadCommand → PqMsg_Parse   → exec_parse_message
2 ReadCommand → PqMsg_Bind    → exec_bind_message
3 ReadCommand → PqMsg_Describe → exec_describe_message  (可省略)
4 ReadCommand → PqMsg_Execute → exec_execute_message → PortalRun → ExecutorRun
```

**实战：用 JDBC 取出 backend PID + gdb attach**

用一个自打印 PID 的 JDBC demo（用 `pg_backend_pid()` 拿到当前服务的 backend 进程号），再开另一个终端 `sudo gdb -p <PID>` 即可在服务端打断点：

```java
try (PreparedStatement st = conn.prepareStatement("SELECT pg_backend_pid()")) {
    ResultSet rs = st.executeQuery();
    if (rs.next()) {
        int pid = rs.getInt(1);
        // 立刻 sudo gdb -p pid
    }
}
```

`PortalRun` 是扩展查询的执行入口（`src/backend/tcop/pquery.c`），debug 时必打的几个断点：

```bash
break PostgresMain                   # 进入主循环
break exec_parse_message             # 处理 Parse 消息
break exec_bind_message              # 处理 Bind 消息
break exec_execute_message           # 处理 Execute 消息
break PortalRun                      # Portal 执行入口
break ExecutorRun                    # 执行器真正启动
break pg_plan_query                  # 规划器入口
break PortalDrop                     # Portal 清理
```

每次 `executeQuery()` 会跑完 4 帧主循环；extended query 协议正是利用这种状态机实现高效复用：同一段 Parse 树可以绑定不同参数、多次 Execute，无需重传 SQL 字符串。

## Query Lifecycle

### 综合视图：5 个阶段

> 来源：bcAndCarl「PostgreSQL 查询处理阶段全面概述」（翻译自 highgo.ca）

| # | 阶段 | 入口 | 入口源文件 | 责任 |
| --- | --- | --- | --- | --- |
| 1 | **Parser**（解析器） | `raw_parser()` | `src/backend/parser/parser.c` | flex/bison 检查字面语法错误 → 输出 raw_parsetree（解析树） |
| 2 | **Analyzer**（分析器） | `parse_analyze_fixedparams()` | `src/backend/parser/analyze.c` | 表名/字段名解析、OID 转换、类型检查 → 输出 query tree |
| 3 | **Rewriter**（重写器） | `QueryRewrite()` | `src/backend/rewrite/rewriteHandler.c` | 把 VIEW/RULE 引用展开成对应语句 → 输出重写后的 query tree |
| 4 | **Planner**（规划器） | `pg_plan_queries()` | `src/backend/optimizer/plan/planner.c` + `tcop/postgres.c` | 估算成本、生成多条 execution path → 输出最优 PlannedStmt |
| 5 | **Executor**（执行器） | `ExecutorRun()` | `src/backend/executor/execMain.c` | 拉取 TupleTableSlot → 通过 Portal/DestReceiver 输出 |

辅助模块：
- **`get_relation_info()`**（`optimizer/util/plancat.c`）：告诉规划器每张表的页数/元组数/索引/列类型等基础信息，是代价估算的"数据库字典接口"。
- **`HeapAccessMethod`**（`access/heap/`）：执行器最终依赖访问方法层完成对 Heap 数据页的读写；堆表元组只有 `HeapTuple` 一种类型。

### 简单查询协议下的端到端路径

```
字符串 (Query)
   │
   ▼
parsenodes ← pg_parse_query
   │       （词法/语法：scan.l + gram.y → raw_parse_tree）
   │
   ▼
parse tree ← parse_analyze (parser/analyze.c)
   │       （语义分析：列类型、函数重载、权限等）
   │
   ▼
Query ← pg_rewrite_query (rewrite/rewriteHandler.c)
   │     （视图展开、规则系统、应用 COPY）
   │
   ▼
PlannedStmt ← planner (optimizer/plan/planner.c)
   │     └── planner_preprocess
   │     └── plan_base_rels → query_planner
   │          └── generate_paths → find_cheapest_path
   │     └── create_plan_plan (生成 Plan tree)
   │
   ▼
Portal ← CreatePortal / PortalRun
   │
   ▼
Executor ← ExecutorRun / ExecutorStart
   │
   ▼
结果集 / 消息流回客户端
```

每一步都可以被 hook 拦截：

- `planner_hook` 接管整个规划器
- `set_rel_pathlist_hook` 仅接管单关系的路径生成
- `ProcessUtility_hook` 接管 DDL/DML utilities
- `ExplainOneQuery_hook` 注入 EXPLAIN 内容

### Parser

`src/backend/parser/`：

- `scan.l`（flex）：词法分析，生成 token
- `gram.y`（bison）：语法分析，输出 `RawStmt` 链表
- `parse_clause.c` / `parse_expr.c` / `parse_type.c`：子句与表达式解析
- `analyze.c`：语义分析，注入列类型、列权限、命名空间解析

输出是 `List *parsetree`，每个元素为 `RawStmt`/`SelectStmt`/`InsertStmt`/...，再被 `parse_analyze` 包成 `Query`。

#### exec_simple_query 解析阶段（PG 18 实际代码）

> 来源：bcAndCarl「PostgreSQL 源码分析 05：SQL 解析和语法树」

`src/backend/tcop/postgres.c::exec_simple_query()` 是简单查询协议的总入口，每条 SQL 的执行都从这里开始：

```c
exec_simple_query(const char *query_string)
{
    debug_query_string = query_string;
    start_xact_command();                   // 启动事务
    drop_unnamed_stmt();                    // 清缓存防止与上次 SQL 冲突
    parsetree_list = pg_parse_query(query_string);
    if (check_log_statement(parsetree_list))    // log_statement='all'
        ereport(LOG, ...);
    ...
}
```

- 词法分析器：`scan.l`（Flex） → 生成 `scan.c`
- 语法分析器：`gram.y`（Bison） → 生成 `gram.c`
- 入口函数：`raw_parser()`，返回 `List *`（最多 5 个元素，对应 PG 单次接收最多 5 条 SQL）

**语法树结构（自顶向下）**：

```
List *raw_parsetree_list
└── elements[i].ptr_value
    └── RawStmt           // 顶层包装（包含 stmt_location / stmt_len）
        └── SelectStmt    // 真正的 SELECT 树
            ├── targetList   (List *ResTarget)
            ├── fromClause   (List *RangeVar)
            ├── whereClause  (Node *)
            ├── groupClause
            └── sortClause
```

> 设计哲学：Node 结构体的首个字段是 `NodeTag type`，通过类型字段实现"多态"——`castNode(SelectStmt, node)` 可以根据 type 安全转换。

### Analyzer

`parse_analyze` 的关键工作：

- 把 `SELECT *` 展开成具体的 targetlist
- 解析子查询为子 `Query`
- 解析 RTE（Range Table Entry）：基表、子查询、函数结果集、VALUES、CTE
- 进行 `pg_*` 系统表查询：列类型、是否存在、权限

这一步会大量命中 `pg_class` / `pg_attribute` / `pg_proc`，所以 PG 用 `syscache`（`utils/cache/syscache.c`）缓存系统表的查询结果。

#### pg_analyze_and_rewrite 流程细节（PG 18 实际代码）

> 来源：bcAndCarl「PostgreSQL 源码分析 06：SQL 语义分析和查询树」

`exec_simple_query` 完成 `pg_parse_query` 得到 `parsetree_list` 后，紧接着调用：

```c
pg_analyze_and_rewrite_fixedparams(parsetree_list, query_string, ...,
                                   &query_list);   // 最终得到 Query 列表
```

其内部流程：

```
pg_analyze_and_rewrite_fixedparams
├── foreach(parsetree_list)
│     └── parse_analyze_fixedparams()            ← 语义分析，生成 Query 树
│     └── pg_rewrite_query()                     ← 查询重写（视图展开等）
└── 返回 query_list
```

每条 SQL 对应输出一个 `Query` 结构，关键字段：

```text
struct Query
├── type          (T_Query)
├── commandType   (CMD_SELECT/INSERT/UPDATE/DELETE/UTILITY)
├── targetList    (List *TargetEntry)  ← 投影列
├── rtable        (List *RangeTblEntry)← from 子句涉及的范围表
├── jointree      (FromExpr)           ← JOIN 关系树
├── qual          (Node *)             ← WHERE 条件
├── sortClause / groupClause
└── hasSubLinks / ...
```

`parse_analyze_fixedparams` 内部走下面这条调用链组装 SELECT 的 Query 树：

```
parse_analyze_fixedparams
└── transformTopLevelStmt
    └── transformOptionalSelectInto
        └── transformStmt
            └── transformSelectStmt            ← SELECT 的核心组装
                ├── transformTargetList         ← 生成 TargetEntry
                ├── transformFromClause         ← from 子句 → RangeTblEntry
                │     └── addRangeTableEntry
                ├── transformWhereClause
                ├── transformSortClause
                └── ...
```

##### 关键点 1：transformFromClause 与 table metadata

为 from 子句里的每个表名生成 `RangeTblEntry`：

```
transformFromClause
└── transformFromClauseItem
    └── transformTableEntry
        └── addRangeTableEntry                  ← 写到 RangeTblEntry + pstate
              ├── parserOpenTable → table_openrv_extended
              │     └── relation_openrv_extended
              │           ├── RelnameGetRelid → get_relname_relid
              │           │     └── 用 SysCache 按 schema 搜索表名 → 拿到 oid
              │           └── RelationIdGetRelation → RelationIdCacheLookup
              │                 └── 用 Hash 按 oid 查 relcache → 拿到 Relation
              └── RTE 字段：relid / ref / access permission / ...
```

> **`parserOpenTable` 是生成查询树的"公共入口"**：
> 几乎所有子句（WHERE、ORDER BY、HAVING、投影列）的语义分析都要通过它拿到表元数据；元数据缓存（relcache）是 PG 每个 backend 私有的 KV 缓存，对于 OLTP 这种共享资源竞争激烈的场景，元数据保护机制非常重要。

默认 schema 由 `pg_catalog.pg_namespace` 提供，搜索顺序由当前 session 的 `search_path` 决定（即 `activeSearchPath`）。

##### 关键点 2：transformTargetList 与 TargetEntry

```
transformTargetList
└── transformTargetEntry / makeTargetEntry      ← 生成 TargetEntry 节点
    └── 节点属性：expr / resno / ressortname / resorigtbl / resorigcol
```

生成的 TargetEntry 被组成 List，最终由 `transformSelectStmt` 写入 `Query.targetList`。

> 调试技巧：用 gdb 在 `transformSelectStmt` 结尾处 `p *qry` 即可看到完整的查询树。Rewriter 之后，再 `p *query_list_head->ptr_value` 可以查看重写后的最终 Query。

##### 关键点 3：pg_rewrite_query 查询重写

最常见的重写场景是把视图引用展开为视图定义对应的子查询。规则系统（`src/backend/rewrite/rewriteDefine.c`，如 `CREATE RULE ... ON ... DO INSTEAD ...`）在重写阶段被展开。**简单的 SELECT 通常不触发任何重写**，但带视图或规则的 SQL 必然经过此环节。

Rewriter 输出仍是一个 Query 列表，进入下一阶段的 Planner。

### Rewriter

`rewrite/rewriteHandler.c` + `rewrite/rewriteManip.c`：

- 视图展开（把视图引用替换为其定义查询）
- RULE 系统（`CREATE RULE ... ON ...`）
- `COPY` 折叠

### Planner / Optimizer

`src/backend/optimizer/` 关键文件：

- `plan/planner.c`：`planner()` 主入口
- `plan/planmain.c`：老 API（被 planner.c 替代）
- `plan/subselect_planner.c`：子查询规划
- `paths/allpaths.c`：路径生成主入口
- `paths/costsize.c`：代价估算
- `pathnodes.h`：路径节点定义（`Path` / `IndexPath` / `NestPath` / `MergePath` ...）
- `plan/createplan.c`：从路径生成 Plan

典型规划步骤：

```
planner
├── subquery_planner
│   ├── pull_up_subqueries        # 上拉可上拉子查询
│   ├── preprocess_targetlist     # PHV/MRV 处理
│   ├── qual_push_down            # 条件压入
│   ├── grouping_planner
│   │   ├── query_planner
│   │   │   ├── build_base_rel_tlist
│   │   │   ├── extract_restrict_clauses
│   │   │   ├── generate_paths → find_cheapest_path
│   │   │   └── make_rel_from_joinlist
│   │   └── create_plan_plan_path
│   └── final_plan
└── create_plan
```

### Executor

`src/backend/executor/`：

- `executor.h`：Plan 节点接口
- `execMain.c`：`ExecutorStart / ExecutorRun / ExecutorFinish / ExecutorEnd`
- `execProcnode.c`：Plan 节点分发（每个节点类型一个 `Exec<Name>Node`）
- `nodeSeqscan.c` / `nodeIndexscan.c` / `nodeNestloop.c` / ...：每个节点类型一个文件
- `execQual.c`：表达式求值
- `execTuples.c`：TupleTableSlot
- `execJunk.c`：Junk filter
- `functions.c`：SQL 函数

每个 Plan 节点都遵循同一范式：

```
Exec<Name>Node(PlanState *state)
├── 每次被调用返回一条结果 Tuple
├── 内部维护状态机（已打开扫描、当前游标等）
└── EXPLAIN ANALYZE 累计 Instr + InstrStartTimer / InstrStopTimer
```

表达式求值的核心数据结构：

- `Expr` / `ExprState`（编译后 IR）
- `ExprContext`：求值时的内存与输入 tuple
- `TupleTableSlot`：tuple 在节点间传递的容器

PG 11+ 引入了 LLVM JIT 编译表达式：

- `src/backend/jit/`：`jit.c` / `llvmjit.c` / `llvmjit_expr.c` / `llvmjit_deform.c`

#### 执行计划树与 Portal

> 来源：bcAndCarl「PostgreSQL 源码分析 07：SQL 执行计划树和执行器」

**Plan 树结构**：`pg_plan_queries()` 把 Query 链表变成 PlannedStmt 链表。`PlannedStmt.planTree` 是 `Plan *` 类型的根节点：

```c
struct PlannedStmt {
    Plan *planTree;       // 根节点
    ...
};
struct Plan {
    NodeTag     type;     // 实际类型由 type 字段决定（多态）
    int         plan_node_id;
    List       *targetlist;
    List       *qual;
    struct Plan *lefttree;
    struct Plan *righttree;
};
```

每个具体节点（Sort、HashJoin、SeqScan 等）都"继承" Plan——在内存布局上，前几个字节就是 Plan，再附加自己的字段。`castNode(Sort, planTree)` 即完成"向下转型"。

**Portal 生命周期**：所有 SQL 执行都通过 Portal：

```
CreatePortal(name)               // 创建干净 Portal（仅分配内存）
   ↓
PortalDefineQuery(...)           // 设置 sourceText / stmts，状态 → PORTAL_DEFINED
   ↓
PortalStart(...)                 // 初始化：ChoosePortalStrategy + CreateQueryDesc，状态 → PORTAL_READY
   ↓
PortalRun(...)                   // 实际执行
   ↓
PortalDrop(...)                  // 释放结果缓存等资源
```

策略选择 `ChoosePortalStrategy`：

- `PORTAL_ONE_SELECT`：单 SELECT → ExecutorRun
- `PORTAL_ONE_RETURNING`：INSERT/UPDATE/DELETE RETURNING
- `PORTAL_UTIL_SELECT`：EXPLAIN / COPY RETURNING
- `PORTAL_MULTI_QUERY`：多语句

#### GDB 跟踪 SQL 完整路径

```bash
# 启动 PG 服务器
pg_ctl -D /home/yiming/pgdata start

# 客户端获取 backend PID
psql -U postgres -c "SELECT pg_backend_pid();"
# 假设输出 3336

# GDB attach 到该 backend
gdb -p 3336

# 设置关键断点
(gdb) b exec_simple_query       # SQL 总入口
(gdb) b pg_parse_query          # 词法语法分析
(gdb) b pg_analyze_and_rewrite  # 语义分析+重写
(gdb) b pg_plan_queries         # 规划器
(gdb) b ExecutorRun             # 执行器

# 在 psql 中执行 SQL，回到 gdb 查看调用链
```

## Storage Layer

PG 把磁盘持久化抽象为几层，每一层都对上层只暴露最小接口：

```
SQL Plan  ──>  Access Method (heap/btree/gin/...)  ──>  Storage Manager (smgr.c)
                                                       │
                                                       ▼
                                              Page Cache (bufmgr.c)
                                                       │
                                                       ▼
                                              File I/O (fd.c / md.c)
                                                       │
                                                       ▼
                                                   Filesystem
```

### Storage Manager（SMGR）

`src/backend/storage/smgr/`：

- `smgr.c`：SMGR 抽象 API 与调度
- `md.c`：磁碟（磁带？）实现，最常见
- `fd.c`：底层 vfd（虚拟文件描述符）层
- `sync.c`：fsync 协调

每个表/索引对应一个 `SMgrRelation`，持有 `RELSEG_SIZE`（默认 1 GB）大小切分的 segment 文件（如 `16384.1`, `16384.2`）。

### Buffer Pool

`src/backend/storage/buffer/`：

- `bufmgr.c`：`ReadBuffer / MarkBufferDirty / ReleaseBuffer / FlushBuffer`
- `buf_table.c`：BufferTag → BufferDescriptor 哈希表
- `freelist.c`：共享 freelist（Clock-sweep）
- `localbuf.c`：临时表的本地 buffer
- `buf_init.c`：共享缓冲池初始化
- `buf_internals.h`：Buffer 描述符 + Buffer Tag 结构

关键结构：

- `BufferTag = { rnode, forkNum, blockNum }` 唯一定位一个磁盘页
- `BufferDescriptor` 持有 refcount、flags、io_in_progress_lock
- 内容锁（`CONTENT_LOCK`、`BM_LOCKED`）：共享/独占保护
- 替换策略：`strategy_point` 指向 clock hand

#### BufferAlloc：Shared Buffer 的唯一入口

> 来源：bcAndCarl「PostgreSQL 源码分析 16：PG 的 Shared Buffer」

```c
// src/backend/storage/buffer/bufmgr.c
static Buffer BufferAlloc(SMgrRelation reln, ForkNumber forkNum,
                          BlockNumber blockNum,
                          BufferAccessStrategy strategy, bool *foundPtr);
```

`BufferAlloc` 是所有"逻辑读"的源头——任何 backend 想访问 8 KB 页面都必须经过它：

```
1.  ResourceOwnerEnlarge + ReservePrivateRefCountEntry
2.  InitBufferTag(&newTag, smgr, forkNum, blockNum)
3.  newHash = BufTableHashCode(&newTag)
    newPartitionLock = BufMappingPartitionLock(newHash)    // 128 把分区锁之一
4.  LWLockAcquire(newPartitionLock, LW_SHARED)            // 第一次快速查找
5.  existing_buf_id = BufTableLookup(&newTag, newHash)
6.  命中 → PinBuffer() → 释放共享锁 → return foundPtr=true
7.  未命中 → 释放共享锁，进入 miss 路径
8.  victim_buffer = GetVictimBuffer(strategy, io_context)  // Clock-sweep 4 轮
9.  LWLockAcquire(newPartitionLock, LW_EXCLUSIVE)          // race-to-fill 关键路径
10. existing_buf_id = BufTableInsert(&newTag, newHash, victim_buf_hdr->buf_id)
11. 别人已插 → UnpinBuffer / StrategyFreeBuffer → 用别人准备的 → return foundPtr=true
12. 插入成功 → 设置 BM_TAG_VALID/BUF_USAGECOUNT_ONE → return foundPtr=false（此处产生 blks_read）
```

#### 128 把分区锁（BufMappingPartitionLock）

`BufTable` 是所有 backend 共享的唯一全局结构。PG 用 **128 把** LWLock 把哈希表切成 128 个分片，极大降低并发争用：

- 逻辑读之间 **不阻塞**（不同分片）
- 逻辑读与物理读 **互相阻塞**（同一分片）
- 物理读与物理读 **互相阻塞**

#### Shared Buffer 与 MemoryContext 对比

| 维度 | Shared Buffer | MemoryContext |
| --- | --- | --- |
| 内存类型 | 公共内存 | 私有内存 |
| 访问权限 | 所有后端进程共享 | 仅所属进程可见 |
| 管理机制 | Buffer Manager 统一管理 | 进程内部自行管理 |
| 主要用途 | 缓存磁盘数据页（Table/Index） | 进程内部临时数据分配 |
| 容量建议 | 物理内存的 25%~33% | 由查询复杂度决定 |

#### HTAB 结构（动态哈希表）

`buf_table.c::SharedBufHash` 是 Shared Buffer 的全局哈希表：

```c
struct HTAB {
    HASHHDR    *hctl;              // 共享控制块
    HASHSEGMENT *dir;              // 一级目录
    HashValueFunc hash;
    HashCompareFunc match;
    bool       isshared;          // 是否在共享内存
    bool       isfixed;           // 是否禁止扩容
    Size       keysize;
    long       ssize;
    int        sshift;
};
```

`HASH_FIND` 仅读，`HASH_ENTER` 写入分配桶——这是 race-to-fill 的关键。

#### Shared Buffer 实战指标

- **逻辑读命中率**：99.9% 及格、99.99% 优秀、99.999% 顶级
- `shared_buffers` 提到 16~32 GB 时 `blks_read` 几乎归零
- 大顺序扫描会被 `BAS_BULKREAD` 策略指引使用 256 KB 环形缓冲区，不污染 Buffer Pool

### Heap Access Method

`src/backend/access/heap/`：

- `heapam.c`：`heap_insert / heap_delete / heap_update / heap_lock_tuple`
- `heapam_visibility.c`：MVCC 可见性
- `hio.c`：FSM-aware 插入路径
- `tuptoaster.c`：TOAST 编码
- `rewriteheap.c`：表改写

每行数据 `HeapTuple` 由 `HeapTupleHeaderData` + 用户数据组成。`HeapTupleHeaderData` 中关键字段：

- `t_xmin`（4B）：插入此行的事务 ID
- `t_xmax`（4B）：删除/锁定此行的事务 ID
- `t_infomask`（2B）：位标志（HEAP_HASNULL、HEAP_XMIN_COMMITTED、HEAP_XMAX_INVALID...）
- `t_infomask2`（2B）：属性数 / 二级位标志
- `t_ctid`（6B）：当前版本行指针，UPDATE 形成链表

#### HeapTupleHeaderData 完整布局

> 来源：bcAndCarl「PostgreSQL 的堆表的存储结构」

```c
typedef struct ItemIdData {
    unsigned    lp_off:15,    /* offset to tuple (from start of page) */
                lp_flags:2,   /* state of line pointer:
                                * 0 = unused, 1 = normal, 2 = redirect, 3 = dead */
                lp_len:15;    /* byte length of tuple */
} ItemIdData;
```

每一行记录在磁盘页的开头是 `ItemIdData`（即 `LinePointer`），指向真正的 tuple。

```text
HeapTupleHeaderData (固定 23 字节)
├── t_choice (union)                   ← 12 字节，双重身份
│   ├── HeapTupleFields (磁盘上)
│   │   ├── t_xmin    (4B)            插入事务 ID
│   │   ├── t_xmax    (4B)            删除/锁定事务 ID
│   │   └── t_field3  (4B, union)     t_cid 或 t_xvac
│   └── DatumTupleFields (内存中)
│       ├── datum_len_    (4B)         varlena 长度头
│       ├── datum_typmod  (4B)         类型修饰符
│       └── datum_typeid  (4B)         复合类型 OID
├── t_ctid           (6B)             当前/新版元组 TID
├── t_infomask2      (2B)             属性数量 + 标志位
├── t_infomask       (2B)             可见性/锁/状态标志
├── t_hoff           (1B)             头部总大小（含 bitmap + 填充）
├── t_bits[]         (柔性数组)       NULL 位图
└── 用户数据 ...
```

完整结构定义在 `src/include/access/htup_details.h`，关键要点：

| 字段 | 字节 | 含义 |
| --- | --- | --- |
| `t_xmin` | 4 | 插入此行的事务号；tuple 的"出生证" |
| `t_xmax` | 4 | 删除/锁定此行的事务号；UPDATE 后旧行的 xmax 被设上 |
| `t_field3` | 4 | union，存 `t_cid` 或老式 `t_xvac`（VACUUM FULL 标记） |
| `t_ctid` | 6 | 当前/更新后新行的 TID；多版本靠它形成链表 |
| `t_infomask2` | 2 | 高位：列数；低位：HASH/LIMIT 等二级标志 |
| `t_infomask` | 2 | 可见性标志核心：HEAP_XMIN_COMMITTED / HEAP_XMAX_INVALID / HEAP_HASNULL / HEAP_HOT_UPDATED 等 |
| `t_hoff` | 1 | 整个头部长度（bitmap + padding），决定用户数据起点 |

#### pageinspect 实战

编译并加载 `contrib/pageinspect`，可直接 dump 堆表的物理页面：

```bash
cd postgresql-*/contrib/pageinspect
make PG_CONFIG=$PG_INSTALL/bin/pg_config CPPFLAGS="-I$(pg_config --includedir-server)"
make install PG_CONFIG=$PG_INSTALL/bin/pg_config

psql -c 'CREATE EXTENSION pageinspect;'
```

核心函数：

| 函数 | 作用 |
| --- | --- |
| `heap_page_items(get_raw_page('t', 0))` | 列出页内所有 line pointer + tuple 头 |
| `heap_page_item_attrs(...)` | 解析用户数据列 |
| `tuple_data_split(...)` | 把 toast 元组拆解 |
| `bt_page_stats('idx', blkno)` | B-Tree 页统计 |
| `fsm_page_contents(bytea)` | FSM 内容 |
| `brin_metapage_info()` / `gin_metapage_info()` | 各 AM 的 metapage |

实战中 `SELECT lp, lp_off, t_xmin, t_xmax, t_ctid, t_data FROM heap_page_items(get_raw_page('test', 0));` 即可看到 MVCC 中一行多个版本的物理布局。

### B-Tree Access Method

`src/backend/access/nbtree/`：

- `nbtinsert.c` / `nbtsplitloc.c` / `nbtpage.c` / `nbtsearch.c`
- 物理页结构：Meta Page / Internal Page / Leaf Page
- 高效删除：标记 LP_DEAD；空间在 VACUUM 时回收

## WAL

`src/backend/access/transam/` 和 `src/backend/storage/ipc/`：

- `xlog.c`：核心 XLog 记录、插入、刷盘、Checkpoint
- `xloginsert.c`：WAL 构造（注册各 RMGR）
- `xlogreader.c`：用于 logical decoding 的 WAL 读取
- `xlogutils.c`：WAL 期间的回放工具

### XLogRecord 结构

```
XLogRecord {
    xl_prev      64-bit  // 上一条 record 的 LSN（构成反向链表）
    xl_xid       32-bit  // 该 record 的事务 ID
    xl_tot_len   32-bit  // 整条 record 长度（含 main_data 和 block_image）
    xl_len       32-bit  // main_data 长度（不含 block_image）
    xl_info      16-bit  // flags（含资源管理器 ID）
    xl_rmid      8-bit   // 资源管理器 ID
    xl_crc       32-bit  // CRC32C 校验
    // (可选) BlockReference + BlockImage
    // main_data[]
}
```

### Resource Manager（RMGR）

`src/backend/access/transam/rmgr.c` 维护一张数组，注册所有 RMGR：

| RMGR ID | 模块 | 作用 |
| --- | --- | --- |
| RM_XLOG_ID | xlog | WAL 自指记录（bootstrap） |
| RM_XACT_ID | xact.c | 事务提交/回滚 |
| RM_SMGR_ID | smgr | 表创建/截断 |
| RM_HEAP_ID | heap | DML/事务/INPLACE/REWRITE |
| RM_HEAP2_ID | heap2 | freeze 等 |
| RM_BTREE_ID | nbtree | 索引插入/分裂/删除 |
| RM_HASH_ID | hash | hash 索引 |
| RM_GIN_ID | gin | GIN 索引 |
| RM_GIST_ID | gist | GiST 索引 |
| RM_SEQ_ID | sequence | 序列 |
| RM_REPLORIGIN_ID | replorigin | 复制起点 |
| RM_STANDBY_ID | standby | 热备运行所需记录 |
| RM_LOGICALMSG_ID | logical | logical decoding 的自定义消息 |

### 崩溃恢复

`StartupXLOG`（启动期执行）：

1. 读 `pg_control` 找到最新 checkpoint
2. 从 checkpoint redo 起点开始重放 WAL
3. 应用 ReorderBuffer 的逻辑消息（如 logical replication）
4. 完成一致点后切换为正常模式

### XLOG / WAL 概述与文件命名

> 来源：bcAndCarl「PostgreSQL 源码分析 13/14：XLOG 事务日志」

- `XLog` 是历史命名，**XLog == WAL**（Write-Ahead Logging），代码层继续沿用 XLog 字样，对外统一叫 WAL。
- WAL 文件位于 `data/pg_wal/`（PG 10 前叫 `pg_xlog/`），默认每段 **16 MB**。
- 文件名是 **24 个十六进制字符**，由三个 8 字节字段拼接：

```text
00000001 00000000 00000004
└─────┘ └─────┘ └─────┘
timeline  logId    logSegNo

timeline: TimeLineID，从 1 开始递增（一次 promote 增加 1）
logId:    逻辑日志号，PG 18 几乎固定是 0
logSegNo: 段号，从 0 起递增（注意：当 logId=0 时 logSegNo 从 1 起）
```

例：`000000010000000000000004` 表示 timeline 1，第 0 号日志文件的第 4 个 16MB 段。

### LSN（Log Sequence Number）

LSN 是 64-bit 单调递增的"字节偏移"，表示当前 WAL 的写入位置：

```text
LSN = (高 32 位) 逻辑文件号 ‖ (低 32 位) 文件内字节偏移
```

每条 WAL 记录都有自己的创建 LSN，崩溃恢复时通过比较 LSN 决定从何处开始 redo。

核心用途：
- 数据页 Page Header 记录当前 page 的 `lsn`，写到该 page 上时 `page_lsn <= flush_lsn`
- 红/重做（redo）以最新 checkpoint 的 redo LSN 为起点

### Checkpoint

Checkpoint 是"将 Shared Buffer 中的所有脏页刷到数据文件，并记录这个位置"的过程：

- 由独立的 `checkpointer` 后台进程周期性触发
- Checkpoint 完成后，把 redo LSN 写入 `pg_control`，下次崩溃恢复从这里开始
- "按热度刷脏页"原则：usage_count 低（冷脏页）优先刷盘，越热的页越晚刷

### Shared Buffer 与 WAL Buffer 的协作

数据修改与 WAL 的写入顺序是 PG 的根本：

```text
1. 数据页 → 加独占锁（块锁）
2. 在 Shared Buffer 中读取 oldtup
3. 修改 oldtup，得到 newtup
4. 修改 Shared Buffer 中页面
5. 插入 newtup
6. 标记脏页
7. 生成 WAL record，写入 WAL Buffer
8. 释放独占锁
```

为什么要先写 WAL？PG 数据页写入是**随机 IO**，WAL 是**顺序 IO**，先写 WAL 可以保证事务提交后即使 Shared Buffer 数据丢失也能通过 WAL 恢复。

### XLogInsertRecord 流程与两把锁

`XLogInsert` 是 PG 的核心 WAL 入口：

```c
void XLogInsert(RmgrId rmid, uint8 info, ...) {
    ... = GetFullPageWriteInfo(...);           // 决定是否要 full_page_write
    record = XLogRecordAssemble(rmid, info, ...);  // 组装 WAL record
    XLogInsertRecord(record, ...);             // 插入 WAL buffer
}
```

共享结构：

```c
typedef struct XLogCtlData {
    XLogCtlInsert Insert;
    XLogwrtRqst   LogwrtRqst;          // 哪些 LSN 需要刷盘
    XLogRecPtr    RedoRecPtr;          // redo 起点
    pg_atomic_uint64 logInsertResult;  // 最后插入位置
    pg_atomic_uint64 logWriteResult;   // 最后写盘位置
    pg_atomic_uint64 logFlushResult;   // 最后刷盘位置
    char          *pages;              // WAL buffer 起始
    pg_atomic_uint64 *xlblocks;
    slock_t        info_lck;            // 保护 info_lck 内部的字段
} XLogCtlData;

typedef struct XLogCtlInsert {
    slock_t       insertpos_lck;       // 保护 CurrBytePos 和 PrevBytePos
    uint64        CurrBytePos;
    uint64        PrevBytePos;
    char          pad[PG_CACHE_LINE_SIZE];
    XLogRecPtr    RedoRecPtr;
    bool          fullPageWrites;
    WALInsertLockPadded *WALInsertLocks;   // 8 个，NUM_XLOGINSERT_LOCKS
} XLogCtlInsert;
```

`XLogInsertRecord` 涉及两把锁的严格配合：

| 锁 | 类型 | 作用 |
| --- | --- | --- |
| **WALInsertLock**（8 把） | 通知/同步机制 | 保护 copy_data_to WAL_buffer，组提交语义 |
| **insertpos_lck**（XLogCtlInsert 内 spinlock） | 全局唯一 | 串行化对 XLogCtl 的写入，竞争热点 |

### XLogFlush 落盘

事务提交或后台刷脏页时调用：

```c
void XLogFlush(XLogRecPtr record);    // 把 record LSN 之前的 WAL 全部强制刷盘
```

调用时机：
- 后端进程 COMMIT / ROLLBACK
- Checkpointer 发起 checkpoint
- background writer 写脏页
- VACUUM

`XLogFlush` 内部走 LWLock 排队与 `pg_write()`/`pg_fsync()`，对单个 16MB 段会选用更省成本的 write-behind。

## MVCC & Visibility

可见性判断的"主入口"在 `src/backend/utils/time/tqual.c`（PG 16 起分散到 `heapam_visibility.c`）。

可见性判定根据隔离级别走不同函数：

- `HeapTupleSatisfiesMVCC`（Read Committed 默认）
- `HeapTupleSatisfiesSelf`（构建 catalog 时）
- `HeapTupleSatisfiesToast`（TOAST 内部）
- `HeapTupleSatisfiesUpdate` / `HeapTupleSatisfiesDirty` / `HeapTupleSatisfiesVacuum`（DML 路径）
- `HeapTupleSatisfiesHistoricMVCC`（已结束事务的快照回溯）

### SnapshotData 字段详解

> 来源：bcAndCarl「PostgreSQL 源码分析 17：PG 的快照」

```c
typedef struct SnapshotData {
    SnapshotType   snapshot_type;       // SNAPSHOT_MVCC / TOAST / SELF
    TransactionId  xmin;                // 活跃事务中最小的 xid（< xmin 全部已结束）
    TransactionId  xmax;                // 已分配的 max xid + 1（>= xmax 都未开始）
    TransactionId *xip;                 // 活跃顶层事务 ID 列表
    TransactionId *subxip;              // 活跃子事务 ID 列表（缓存未溢出时）
    bool           suboverflowed;       // 子事务 ID 是否溢出（部分未记录）
    uint32         xcnt;                // xip 元素个数
    int            subxcnt;
    CommandId      curcid;              // 快照采集时的 CommandId
    int            activeCount;
    bool           takenDuringRecovery; // 物理恢复期间采集
} SnapshotData;
```

基本规则：
- `xmin <= t_xmin < xmax` 的 insert 提交状态查 xip
- `t_xmax != 0` 时按 xmax 也走查 xip（同上）
- `t_infomask & HEAP_XMIN_COMMITTED` 等 hint bit 可加速（绕过 clog/SLRU 读）

### GetSnapshotData 流程

`GetSnapshotData()` 是所有快照采集的源头：

```text
GetSnapshotData(Snapshot snap)
├── 决定 ProcArrayLock 加 SHARED 还是 EXCLUSIVE
│     ├── 普通快照            → LW_SHARED
│     └── GetSnapshotDataReuse → 复用已采集快照，可能提前释放锁
├── 遍历 PGPROC 全局数组：当前所有活跃 backend
│     ├── 拷贝每个活跃事务的 xid 到 snap->xip
│     ├── 拷贝每个活跃子事务的 xid 到 snap->subxip
│     └── 处理 LAZY VACUUM / 逻辑解码的过滤
├── 拷贝最新复制槽的 xmin 到 snap
├── compute xmin / xmax
├── LWLockRelease(ProcArrayLock)
└── SetCommandIdForCurrentSnapshot
```

**ProcArrayLock（LWLock）** 规则：
- 采集快照：`LW_SHARED`（多个并发读快照可并行，但阻塞 Vac 拿 EXCLUSIVE）
- 事务注册 / 注销 / VACUUM：`LW_EXCLUSIVE`（等待正在采集的快照全部完成）
- 复用快照（`GetSnapshotDataReuse`）：可提前释放

### 实战：跨 session 观察 MVCC

```sql
-- Session 1
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT * FROM test;
SELECT lp, lp_off, t_xmin, t_xmax, t_ctid, t_data
  FROM heap_page_items(get_raw_page('test', 0));

-- Session 2
BEGIN; UPDATE test SET c1='BBBB5559' WHERE id=3; COMMIT;

-- Session 1 再查
SELECT * FROM test WHERE id=3;   -- 仍看到旧值
COMMIT;
SELECT * FROM test WHERE id=3;   -- 提交后看到新值
```

`heap_page_items` 输出样例：

```text
 lp | lp_off | t_xmin | t_xmax | t_ctid  | t_data
----+--------+--------+--------+---------+----------------
  1 |   8160 |    748 |      0 | (0,1)   | (3,AAAAA5559)
  2 |   8112 |    749 |    750 | (0,3)   | (3,BBBB5559)
```

中间这行的 `t_xmax=750, t_ctid=(0,3)` 即指向 Session 2 新版本的指针——MVCC 版本链。

### Snapshot

`src/backend/utils/time/snapmgr.c`：

- `SnapshotData` 含 `xmin` / `xmax` / `xip[]`（活跃 xid 数组）/ `xcid[]`（子事务）/ `commandId` / `takenDuringRecovery`
- `GetTransactionSnapshot()`：事务级快照
- `GetLatestSnapshot()`：语句级快照
- `PushTransactionSnapshot()` / `PopTransactionSnapshot()`：嵌套

CLOG（`src/backend/access/transam/clog.c`）记录 xid 的提交状态。`pg_xact/` 目录下每页（默认 8 KB）保存 32K × 2 bit 的提交状态。

### MVCC 与并发控制流派

> 来源：bcAndCarl「PostgreSQL 源码分析 10：1-事务的要点」

```
1976   Jim Gray 论文：锁与一致性 → 事务成数据库基石
1990   对象模型挑战关系模型（Stonebraker 发起）→ 仅增加对象类型
2010+  NoSQL 兴起宣称抛弃 ACID → 因 NewSQL 证明事务不可或缺而退潮
```

两种并发流派：

| 流派 | 机制 | 适用 | 代表 |
| --- | --- | --- | --- |
| 悲观锁 | 先加锁再操作 | 高并发、复杂 OLTP | PostgreSQL / MySQL / Oracle |
| 乐观锁 | 先操作、提交时校验 | 读多写少 | LSM-Tree 引擎 |

PG 在通用 OLTP 场景仍以悲观锁为基础，结合 MVCC 让读写互不阻塞。

### HeapTupleHeader 字段详解

| 字段 | 含义 |
| --- | --- |
| `t_xmin` | 插入该行版本的事务 ID |
| `t_xmax` | 删除/更新该行版本的事务 ID（未删除时为 0） |
| `t_cid` | 命令 ID（Command ID），用于同一事务内多语句的可见性 |
| `t_infomask` | 位掩码，存储行状态标志（HEAP_XMIN_COMMITTED / HEAP_XMAX_INVALID / ...） |
| `t_infomask2` | 扩展标志位 + 属性数 |
| `t_ctid` | 当前或新版本物理位置（指向自身 = 最新；指向他处 = 链表） |

### pageinspect 实战

```sql
CREATE EXTENSION pageinspect;

-- 取表的物理页
SELECT * FROM heap_page_items(get_raw_page('orders', 0));
-- 列：lp, lp_off, lp_flags, lp_len, t_xmin, t_xmax, t_field3, t_ctid

-- B-Tree 索引页
SELECT * FROM bt_page_stats('idx_orders_id', 1);
```

### HOT Update

`Heap-Only Tuples`（`src/backend/access/heap/hio.c` + `heapam.c`）：

- UPDATE 产生的新版本只追加到同一页（若能容纳），避免索引膨胀
- 通过 `HEAP_HOT_UPDATED` / `HEAP_ONLY_TUPLE` 位标记

## Transactions & Subtransactions

事务相关代码集中在 `src/backend/access/transam/`：

- `xact.c`：主事务状态机（BeginTransaction / CommitTransaction / AbortTransaction）
- `xlog.c` 中的 XLOG_XACT_* 记录
- `subtrans.c`：子事务页式状态存储（每个父事务占用一个子事务页）
- `multixact.c`：多事务锁（行级 FOR SHARE / FOR UPDATE）
- `twophase.c`：两阶段提交

事务状态栈：`TransactionState` 链表（栈）。每个事务保存：

- 事务 ID
- 顶层与父事务 xid
- CommandId
- 优先级、隔离级别、是否同步提交标志
- 子事务级数限制由 `transaction_stack_depth` 限制（默认 64）

子事务结束 SAVEPOINT 时通过 `xact.c::CommitSubTransaction` 提交，再触发一次 xact commit 的 WAL 记录。

### 事务子系统结构

> 来源：bcAndCarl「PostgreSQL 源码分析 11/12：2/3-事务基本操作」

事务管理器由三个组件构成：

```text
事务管理器
├── 日志管理器
│     ├── CLOG 管理器   (commit log)
│     └── XLOG 管理器   (write-ahead log)
└── 锁管理器
      └── 进程管理 (PGPROC)
```

**任何 SQL 都必须在事务中执行**。PG 自动开启（隐式）事务，单条 SQL 自身就是一个事务；多语句必须用 BEGIN 显式开启。

分层：上层 *Transaction Block* 负责语法块（BEGIN/COMMIT）识别与状态维护，下层 *Xact* 负责 MVCC、WAL、CLOG、锁管理与崩溃恢复。

### 双状态机

PG 用两个独立的状态机分别管理"语法块"与"底层事务状态"：

**上层 TBlockState**（`src/include/tcop/tcopprot.h`）：

| 状态 | 含义 |
| --- | --- |
| `TBLOCK_DEFAULT` | 空闲 |
| `TBLOCK_STARTED` | 单查询事务运行 |
| `TBLOCK_BEGIN` | BEGIN 收到 |
| `TBLOCK_INPROGRESS` | 显式事务进行中 |
| `TBLOCK_IMPLICIT_INPROGRESS` | 隐式事务进行中 |
| `TBLOCK_PARALLEL_INPROGRESS` | 并行 worker 内事务 |
| `TBLOCK_END` / `TBLOCK_ABORT` | COMMIT / 失败等待 ROLLBACK |
| `TBLOCK_PREPARE` | PREPARE 收到（两阶段） |
| `TBLOCK_SUBBEGIN` / `TBLOCK_SUBINPROGRESS` | 子事务状态 |
| `TBLOCK_SUBRELEASE` / `TBLOCK_SUBCOMMIT` | RELEASE / COMMIT 收到 |
| `TBLOCK_SUBABORT` 等 | 子事务异常路径 |

**底层 TransState**（`src/include/access/xact.h`）：

| 状态 | 含义 |
| --- | --- |
| `TRANS_DEFAULT` | 空闲 |
| `TRANS_START` | 事务启动中 |
| `TRANS_INPROGRESS` | 有效事务进行中 |
| `TRANS_COMMIT` | 提交中 |
| `TRANS_ABORT` | 回滚中 |
| `TRANS_PREPARE` | 预提交中 |

### 核心数据结构 TransactionStateData

```c
typedef struct TransactionStateData {
    FullTransactionId fullTransactionId;   // 64bit: XID(32) + epoch(32)
    SubTransactionId  subTransactionId;   // 子事务 ID
    char             *name;               // 当前 SAVEPOINT 名
    int               savepointLevel;
    TransState        state;              // 底层事务状态机
    TBlockState       blockState;         // 上层 BEGIN/COMMIT 块状态
    int               nestingLevel;       // 嵌套深度（顶层 = 1，每 PushTransaction +1）
    int               gucNestLevel;       // GUC 嵌套深度（SET LOCAL 自动回滚）
    MemoryContext     curTransactionContext;
    ResourceOwner     curTransactionOwner;
    MemoryContext     priorContext;
    TransactionId    *childXids;          // 已提交的子事务 XID 数组
    int               nChildXids;
    int               maxChildXids;
    Oid               prevUser;
    int               prevSecContext;
    bool              prevXactReadOnly;
    bool              startedInRecovery;
    bool              didLogXid;          // XID 是否已写入 WAL
    int               parallelModeLevel;
    bool              parallelChildXact;
    bool              chain;              // COMMIT 后是否立即开新事务
    bool              topXidLogged;
    struct TransactionStateData *parent;  // 子事务链
} TransactionStateData;
```

调试技巧：`gdb 中 p CurrentTransactionState->state` 99% 时间是 `TRANS_INPROGRESS`，COMMIT 那瞬间会闪现 `TRANS_COMMITTING`。

### StartTransaction 启动流程

调用链：`exec_simple_query → start_xact_command → StartTransactionCommand → StartTransaction`

StartTransaction 关键步骤：

1. 初始化事务状态结构（指向 `TopTransactionStateData`，state = TRANS_START）
2. 重置内部环境、设置 nestingLevel = 1、gucNestLevel = 1
3. `AtStart_Memory()` 创建事务专属 MemoryContext；`AtStart_ResourceOwner()` 初始化资源跟踪器
4. 通过 `GetNextLocalTransactionId()` 分配 `VirtualTransactionId`（BackendId + LocalTransactionId）
5. 初始化时间戳 xactStartTimestamp
6. 切换 state 到 `TRANS_INPROGRESS`

> **关键观察**：事务"真正"开始并不是 StartTransaction，而是第一条 DML 执行时。`heap_update` 在写入前调用 `GetCurrentTransactionId()` → `AssignTransactionId()`，那里才把 XID 真正分配下来。

### AssignTransactionId / GetNewTransactionId

```c
// src/backend/access/transam/varsup.c
static FullTransactionId
GetNewTransactionId(bool isSubXact) {
    ... 获取 XidGenLock ...
    fullXid = ShmemVariableCache->nextFullXid;
    ShmemVariableCache->nextFullXid = FullTransactionIdAdvance(fullXid);
    ... 检查 XID 是否接近 xidVacLimit ...
    ... 必要时 ExtendCLOG() / ExtendCommitTs() / ExtendSUBTRANS() ...
    return fullXid;
}
```

XID 分配的关键步骤（`xact.c::AssignTransactionId`）：

| # | 步骤 |
| --- | --- |
| 1 | 并行模式判断（并行 worker 中禁止分配 XID） |
| 2 | 子事务处理：把子事务 parent 记录到 subtrans |
| 3 | 获取 `XidGenLock`（LWLock） |
| 4 | 调用 GetNewTransactionId 得到 XID，推进全局 XID |
| 5 | 检查 xidVacLimit，达到时强制 ExtendCLOG / ExtendCommitTs / ExtendSUBTRANS |
| 6 | 推进 `XactTopFullTransactionId` |
| 7 | 处理子事务（XID 父级记录） |
| 8 | RegisterPredicateLockingXid()（SSI 用） |
| 9 | 资源组切换 curTransactionOwner |
| 10 | 释放 XidGenLock |

调试：在 gdb attach 到 backend PID 后，断点 `GetCurrentTransactionId`、`AssignTransactionId` 可观察到 DML 执行前 XID 才被分配，第二条 SQL 不再调用。

### heap_update 三阶段

`heap_update` 在事务中执行的完整流程：

```text
1 更新前
1-1  GetCurrentTransactionId()           ← 事务真正开始
1-2  得到修改列的 Bitmap 映像
1-3  搜索 Buffer 并加锁
1-4  拼装 heapTuple
1-5  判断是否使用 HOT Update

2 更新中
2-1  准备工作
2-2  计算新行行号
2-3  插入新行（heap_insert 路径）
2-4  修改页头、行头（含 xmin / xmax）
2-5  标志脏页
2-6  自旋等待（SpinLock）

3 更新后
3-1  修改锁状态（保留）
3-2  增加 pgstat 性能计数
3-3  释放内存
```

### CommitTransaction 三段式

调用链：`exec_simple_query → finish_xact_command → CommitTransactionCommand → CommitTransactionCommandInternal → CommitTransaction`

```text
提交前
  ├── 并行事务处理
  ├── 检查事务状态
  ├── 处理触发器
  ├── 关闭 Portal
  ├── 清理用户定义代码
  ├── PreCommit_* 系列钩子
  ├── 元数据相关
  └── AtEOXact_LargeObject（大对象）

提交中
  ├── state: TRANS_INPROGRESS → TRANS_COMMIT
  ├── RecordTransactionCommit   （处理 CLOG）
  └── ProcArrayEndTransaction   （更新全局共享结构）

提交后
  ├── CallXactCallbacks         （XACT_EVENT_COMMIT）
  ├── ResourceOwnerRelease
  ├── AtEOXact_Buffers          （释放 Buffer 上的 Pin 锁）
  ├── 清理元数据缓存
  ├── AtCommit_Notify
  ├── AtEOXact_* 系列收尾
  └── CleanupTransaction        （重置为 TRANS_DEFAULT/TBLOCK_DEFAULT）
```

> 代码命名约定：PG 源码常用 `Xact` 代替 `Transaction`；`AtEOXact_*` = "At End Of Transaction"，COMMIT / ROLLBACK 时统一调用的清理函数。

### RecordTransactionCommit / CLOG

`RecordTransactionCommit` 关键步骤：

```text
1 准备工作（XID、时间戳、子事务列表）
2 判断是否需要写 xlog（wrote_xlog）
3 当 XID 有效时：
  3-1 设置提交时间戳
  3-2 XactLogCommitRecord() → 写入 WAL buffer
  3-3 TransactionTreeSetCommitIsData() → 在 xlog 流记录时间戳
4 当 wrote_xlog 时：
  4-1 XLogFlush() → 把 WAL 强制刷盘
  4-2 TransactionIdCommitTree → TransactionIdSetTreeStatus → 处理 CLOG
       4-2-1 计算 clog 页号：pageno = xid / (8192*4)
       4-2-2 TransactionIdSetPageStatus
              ├── XactSLRULock (独占)
              ├── SimpleLruReadPage → XactCtlData.shared->page_buffer[slotno]
              ├── 子事务处理
              └── TransactionIdSetStatusBit
                    ├── byteno = XID % (8192*4) / 4
                    ├── bshift = XID % 4 * 2
                    ├── 修改 XactCtlData.shared->page_buffer[slotno][byteno] 字节
                    └── 组提交检查
5 处理子事务 → 得到 latestXid
```

**CLOG 状态编码（每 XID 占 2 bit）**：

| 值 | 含义 |
| --- | --- |
| 0x00 | IN_PROGRESS |
| 0x01 | COMMITTED |
| 0x02 | ABORTED |
| 0x03 | SUB_COMMITTED |

文件在 `pg_xact/` 下，理论最多 20 亿个事务，文件约 512 MB。读取无需锁（SALR 锁），但写状态时需要 XactSLRULock（page 级 SLRU 锁，是热点争用源）。

**CLOG 页内位置计算**：

```c
pageno  = xid / (8192 * 4);     // 8KB 页 = 32K xid，每 xid 2 bit
byteno  = xid % (8192 * 4) / 4; // 字节偏移
bshift  = xid % 4 * 2;          // 位偏移
```

### XID 回绕与 FrozenTransactionId

XID 是 32-bit 环形递增，达到 2^31 后会"穿过"过去；为了避免把已经存在于表里的旧行误判为"未提交事务"，PG 引入了 FrozenTransactionId（常量 2）：

- 行 `t_xmin = FrozenTransactionId` 的"创建事务" 永远视为已提交
- VACUUM 把足够老的 xmin 替换为 FrozenTransactionId
- 防止回绕：autovacuum 会在 `age(relfrozenxid) > autovacuum_freeze_max_age` 时强制 VACUUM

## Lock Manager

`src/backend/storage/lmgr/`：

- `lock.c`：主锁表
- `proc.c`：每个 backend 的锁队列
- `deadlock.c`：死锁检测
- `lwlock.c`：轻量锁（缓冲池 latch、partition lock 等）
- `lwlocknames.txt`：LWLock 名称定义
- `predicate.c`：SSI 谓词锁

锁层级（由 `LOCK_*` 常量标识）：

1. 表级锁：AccessShare / RowShare / RowExclusive / ShareUpdateExclusive / Share / ShareRowExclusive / Exclusive / AccessExclusive
2. 行级锁：FOR KEY SHARE / FOR SHARE / FOR NO KEY UPDATE / FOR UPDATE
3. 页面级锁：extension 内（heap_page_prune 等）
4. LWLock：内存结构同步
5. Spinlock：极短临界区

`Fast Path` 行锁：单事务内对同一行加锁时直接走 backend 局部数组，避免主锁表争用；超过阈值后才升级到主锁表。

### LOCK 与 PROCLOCK 详细结构

> 来源：bcAndCarl「PostgreSQL Lock 锁总览」（参考自 `src/backend/storage/lmgr/README`）

```c
typedef struct LOCK {
    /* hash key */
    LOCKTAG      tag;             // 唯一标识锁对象
    /* data */
    LOCKMASK     grantMask;       // 已经授予的锁类型位掩码
    LOCKMASK     waitMask;        // 正在等待的锁类型位掩码
    dlist_head   procLocks;       // 该 LOCK 关联的所有 PROCLOCK 链表
    dclist_head  waitProcs;       // 因锁而处于睡眠的 PGPROC 链表
    int          requested[MAX_LOCKMODES];
    int          nRequested;
    int          granted[MAX_LOCKMODES];
    int          nGranted;
} LOCK;
```

```c
typedef struct PROCLOCK {
    /* hash key */
    PROCLOCKTAG  tag;             // (LOCK*, PGPROC*)
    /* data */
    LOCKMASK     holdMask;        // 当前 PGPROC 已持有锁类型
    LOCKMASK     releaseMask;     // 待释放掩码（无锁优化）
    dlist_node   lockLink;        // 挂到 LOCK->procLocks
    dlist_node   procLink;        // 挂到 PGPROC->procLocks
} PROCLOCK;
```

**关键设计**：

1. **tag 唯一性由指针保证**：PROCLOCK.tag 直接存 `LOCK*` 与 `PGPROC*`，只要 PROCLOCK 活着，被指向的对象就一定活着——避免悬空指针，省去复杂 ID 映射。
2. **双重链表归属**：
   - `lockLink` 让 PROCLOCK 挂在 LOCK 维度上，方便锁管理器扫描
   - `procLink` 让 PROCLOCK 挂在 PGPROC 维度上，方便事务退出时清理
3. **`releaseMask` 无锁优化**：持有者改自己 PROCLOCK 的字段不需要加锁，配合事务清理阶段快速回收锁资源

### 锁管理器的内部同步

```c
static HTAB *LockMethodLockHash;     // LOCK 全局表（共享内存）
static HTAB *LockMethodProcLockHash; // PROCLOCK 全局表（共享内存）
static HTAB *LockMethodLocalHash;    // LOCALLOCK 表（每 backend 私有）
```

主锁表与 PROCLOCK 表都对 hash 进行分区（**default 16 个**），每个分区配一把 LWLock：

- 普通加锁/解锁：只需对目标锁所在分区加锁
- 死锁检测：按分区编号**从小到大**的顺序遍历锁住所有分区（避免 LWLock 死锁）
- LOCALLOCK（本地哈希表）：不分区，直接拿 `LockMethodLocalHash` 内部 spinlock

**避免 LWLock 死锁的规则**：任何后端进程若需要同时对多个分区加锁，必须按分区编号顺序执行加锁。

### Fast Path Locking（快速路径锁）

> `src/backend/storage/lmgr/lock.c`

针对 **"高频获取/释放、极少冲突"** 的特定类型锁做的优化，目前覆盖两类：

1. **弱关系锁（Weak relation locks）**：如 SELECT 的 AccessShareLock
2. **轻量级行锁**：单事务多行的 FOR KEY SHARE / FOR SHARE

Fast Path 的实现：
- 行锁：直接缓存在 `MyProc->fpRelId[]` 与 `MyProc->prfd` 数组，加锁时 `LWLockDeferRelease` 让 LWLocks 也走快速
- 关系锁：每个 backend 持有一个 `fastpath` 数组记录本地持有状态
- 超过阈值（如 `FP_LOCK_SLOTS_PER_BACKEND`）后升级到主锁表

这极大降低了简单查询在加锁/解锁阶段的开销，是 PG 在高并发下仍能保持高吞吐的关键。

## VACUUM

> 来源：bcAndCarl「PostgreSQL 源码分析 15：PG 的 VACUUM」

### 前映像（Before Image）

前映像 = "行在被修改之前的旧版本"，是 MVCC 三大特性（事务回滚、MVCC 一致性读、崩溃恢复）的基础。

对比两大流派：

| 流派 | 实现 | 代表数据库 |
| --- | --- | --- |
| **Undo 派** | 数据页原地修改，旧版存到专用 Undo 区域 | Oracle / SQLServer / MySQL / DB2 / OceanBase / TiDB / 达梦 |
| **Append-only 派** | 行永不原地修改；UPDATE = 新增一行 + 旧行打 xmax；版本链在数据文件 | **PostgreSQL** / CockroachDB / YugabyteDB / Greenplum |

> PG 是"Append-only 派"代表：旧版本完全留在数据文件里，靠 VACUUM 清理 dead tuples。

**PG 的崩溃恢复与前映像无关** —— 完全依赖 WAL；Oracle/MySQL 用 UNDO 既做 MVCC 也做回滚/恢复。

### VACUUM 三大工作

1. **清理 dead tuples**：回收对所有事务都已不可见的旧版本数据
2. **更新统计信息**（VACUUM ANALYZE 时）
3. **冻结行 XID**：将极旧提交的 `t_xmin` 改写为 `FrozenTransactionId`（常量 2），防止 XID 回绕

### 启动机制

```text
PG 启动
  └── autovacuum launcher（每 60s 醒来一次）
        └── do_start_worker()
              └── SendPostmasterSignal() → 发信号给 postmaster
                    └── postmaster fork → autovacuum worker（一个 worker / DB）
                          └── do_autovacuum()
                                └── vacuum_rel() (核心清理) / analyze_rel()
```

> `autovacuum launcher` 只控制"何时做"，并不执行清理；真正干活的是被 fork 出来的 `autovacuum worker`。

触发条件（任一满足）：

- 表上 dead tuples 数 > `autovacuum_vacuum_threshold + autovacuum_vacuum_scale_factor * n_live_tup`
- XID 接近 `autovacuum_freeze_max_age`，强制 VACUUM 防回绕

### do_autovacuum 核心流程

```text
1 StartTransactionCommand
2 加载 vacuum 相关 GUC 参数
3 table_open(pg_class) → 遍历所有 relation
   ├── 过滤表对象（普通 relkind='r' 或物化视图 'm'）
   ├── 跳过临时表（独立处理）
   ├── pgstat_fetch_stat_tabentry_ext() 拉取统计信息
   ├── relation_needs_vacanalyze() 决定是否要 vacuum/analyze
   └── 收集 OID 到 table_oids
4 缓存主表 → toast 的 hash
5 遍历 pg_class 中所有 toast 对象
6 table_close(pg_class)
7 处理孤儿表
8 遍历 table_oids：
   ├── LWLockAcquire(AutovacuumScheduleLock, EXCLUSIVE)
   ├── LWLockAcquire(AutovacuumLock, SHARED)
   ├── 检测是否有其他进程正在 vacuum
   ├── 释放 Autovacuum* 锁
   ├── table_recheck_autovac()（防止 race）
   ├── 计算 cost-based vacuum limit
   ├── autovacuum_do_vac_analyze()
   └── 释放内存
9 在共享 AutovacuumLock 保护下查看其他 worker 状态
10 CommitTransactionCommand
```

### vacuum_rel 内部动作（heap_vacuum_rel）

1. `lazy_vacuum` / `vacuum_heap` 顺序扫表，对每页：
   - 设置 PD_ALL_VISIBLE，重置 VM
   - FSM 重建空闲空间映射
   - 标记 LP_DEAD 的 line pointer
2. 如果有死行，确认是否需要 `PageRepairFragmentation` 收缩碎片
3. 更新 `pg_class.relpages/reltuples` 统计
4. 多趟进行 freeze：把 `t_xmin < FreezeLimit` 的行冻结为 `FrozenTransactionId`

### 多进程 vs autovacuum

- 用户手动 `VACUUM`（同 session）只持 `AUTOVACUUM_LOCK` 共享模式，不阻塞其它 worker
- `VACUUM FULL` 重写表（`rewriteheap.c`）独占 `ACCESS EXCLUSIVE` 锁，会阻塞所有读写
- 多个 worker 在同一表上通过 `AutovacuumScheduleLock` 互斥

## Background Workers

`src/backend/postmaster/` 与 `src/backend/storage/bgworker/`：

- `bgworker.c` / `bgworker.h`：通用 worker 框架
- 启动顺序在 `postmaster.c::PostmasterMain` 中：先启动 startup 回放，再 fork 自定义 `bgworkers`

包括：

- Startup process：恢复专用
- WAL writer / Background writer / Checkpointer
- Autovacuum launcher
- Logical replication launcher
- WAL receiver（流复制）
- 用户自定义 worker（`RegisterBackgroundWorker`/`RegisterDynamicBackgroundWorker`）

## Catalog & Cache

`src/backend/catalog/`：

- `catalog.c` / `system_views.h`：系统表 schema 定义
- `pg_proc.dat` / `pg_aggregate.dat` / `pg_operator.dat` / `pg_opclass.dat`：数据驱动的元数据声明
- `genbki.pl` + `bki_*`：将 `.dat` 转成 C 与 `header` 文件
- `dependency.c`：依赖处理
- `aclchk.c`：权限

`utils/cache/`：

- `syscache.c`：基于 OID 哈希的系统表缓存（`SYSCACHE`）
- `relcache.c`：表结构缓存（`RelationData`）
- `typcache.c`：类型缓存
- `inval.c` / `inval_messages`：缓存失效（`CacheInvalidateHeapTuple` 等）
- `lsyscache.c`：便捷 lookup API

## Replication Implementation

`src/backend/replication/`：

- `walsender.c`：主端把 WAL 推给备端
- `walreceiver.c`：备端接收并落盘
- `walwriter.c`：备端刷 WAL
- `logical/worker.c` / `logical/tablesync.c`：逻辑复制 worker
- `logical/decode.c`：ReorderBuffer（处理事务边界）
- `slot.c`：复制槽管理

逻辑解码：WAL → `XLogReadRecord` → 各 RMGR 的 `decode` 回调 → `ReorderBuffer` 按事务 ID 与 LSN 重新排序 → `pgoutput` 插件翻译为 protobuf → 订阅端 apply。

## Extensions 机制

扩展入口（`src/backend/utils/fmgr/` 与 `src/backend/commands/extension.c`）：

- `PG_MODULE_MAGIC` 宏：每个 `.so` 必须声明
- `_PG_init`：模块加载时调用
- `PG_FUNCTION_INFO_V1`：C 函数导出
- `fmgr.c`：fmgr_lookup / fmgr_builtins

常用 hook（可被扩展替换）：

- `planner_hook` / `set_rel_pathlist_hook`
- `ExecutorStart_hook` / `ExecutorRun_hook`
- `ProcessUtility_hook`
- `explain_get_index_clause_hook`
- `object_access_hook` / `post_parse_analyze_hook`
- `emit_log_hook`

Extension 注册到系统表 `pg_extension`，加载时通过 `$sharedir/extension/<name>.control` 描述。

## Memory Context

`src/backend/utils/mmgr/`：

- `mcxt.c`：内存上下文（MemoryContextData）框架
- `aset.c`：allocset 分配器（默认实现）
- `dsa.c`：动态共享内存（多 backend 共享）
- `slab.c`：slab 分配器
- `generation.c`：generation 分配器

每次语句执行都在 `ExecutorStart` 创建一个 `ExecutorState`，结束后 `MemoryContextDelete` 一次性回收。

### MemoryContextData 抽象类

> 来源：bcAndCarl「PostgreSQL 源码分析 08：pg 的本地内存管理」

```c
// src/include/utils/memutils.h
typedef struct MemoryContextData {
    NodeTag     type;            // T_AllocSetContext / T_SlabContext / ...
    bool        isReset;
    bool        allowInCritSection;   // 仅 ErrorContext 允许
    const MemoryContextMethods *methods; // 虚函数表：alloc / free / reset / delete ...
    MemoryContext parent;
    MemoryContext firstchild;
    MemoryContext prevchild;
    MemoryContext nextchild;
    char       *name;            // 用于 pg_backend_memory_contexts 视图
} MemoryContextData;

typedef struct MemoryContextMethods {
    void       *(*alloc)        (MemoryContext, Size);
    void        (*free_p)       (MemoryContext, void *);
    void        (*reset)        (MemoryContext);
    void        (*delete_context)(MemoryContext);
    void        (*init)         (MemoryContext);
    bool        (*is_empty)     (MemoryContext);
    void        (*stats)        (MemoryContext, int, bool, MemoryContextCounters *);
    MemoryContext (*checkpoint) (MemoryContext);
    MemoryContext (*trim)        (MemoryContext);
} MemoryContextMethods;
```

`methods` 是抽象接口，`mcxt_methods[]` 是所有实现的注册表。`MemoryContext` 是抽象类——目前仅 `AllocSetContext` 一个实现。

### 进程内典型 MemoryContext 树

```
TopMemoryContext                    // 进程整个生命周期（pg_class 缓存等）
├── ErrorContext                    // 错误恢复（pg_stat_activity 显示 query）
├── CacheMemoryContext               // 事务结束时 Reset
│   └── 各 syscache
├── TopTransactionContext            // 事务提交/回滚时销毁
├── PortalContext                    // Portal 生命周期
├── MessageContext                   // 命令信息
├── QueryContext                     // 单条 SQL 结束销毁
└── ExecutorState                    // ExecutorStart 时建，End 时回收
    ├── EState
    ├── exprcontexts（表达式求值）
    └── Per-Tuple-Context            // 每 1000 条 tuple 重建一次
```

### AllocSetContext 实现细节

```c
typedef struct AllocSetContext {
    MemoryContextData header;        // 头部（虚基类）
    AllocBlock  blocks;              // 一次申请的连续内存块链表
    MemoryChunk *freelist[ALLOCSET_NUM_FREELISTS];   // 12 个空闲链表
    uint32      initBlockSize;       // 初始块大小
    uint32      maxBlockSize;
    uint32      nextBlockSize;
    uint32      allocChunkLimit;     // 超过则单独申请一个块
    int         freeListIndex;
} AllocSetContext;
```

12 个 freelist 桶按 chunk 大小分桶（精确大小，含 16B header）：

| 桶 | chunk 总大小 | 备注 |
| --- | --- | --- |
| 0 | 32 B | |
| 1 | 64 B | |
| 2 | 128 B | |
| 3 | 256 B | 最常用 |
| 4 | 512 B | |
| 5 | 1024 B | 常见 Node |
| 6 | 2048 B | |
| 7 | 4096 B | |
| 8 | 8192 B | |
| 9 | 16384 B | |
| 10 | 32768 B | |
| 11 | 65536 B | |

### MemoryContext → Block → Chunk 三层关系

```
MemoryContext   生命周期管理者
└── Block        一次向 OS 申请的大块连续内存（8 KB~8 MB）
    └── Chunk    用户请求的最小单元（≤4 KB 进 freelist 复用）
```

> palloc 的速度优势来源于：用户请求 ≤ 4 KB 时直接从对应 freelist 桶中弹出（5~6 条指令）；`pfree` 把 chunk 重新挂回对应桶；`MemoryContextReset` 一行清空所有 chunk 不需要逐个 free。

## How to Read the Source

- 学会用 `git log --grep=<符号>` 跟踪某个特性的演化
- 学会用 `git grep -n <symbol>` 跨目录定位
- 配合官方手册的 *"Overview of PostgreSQL Internals"* 章节阅读
- 阅读 `src/backend/storage/bufmgr.c` 的 `ReadBuffer_internal`，理解 Buffer Pool 与 Heap 交互
- 阅读 `src/backend/optimizer/plan/planner.c` 的 `planner()` 函数，理解规划全貌
- 阅读 `src/backend/executor/execMain.c` 的 `ExecutorRun`，看 Plan 节点如何被调度
- 阅读 `src/backend/access/transam/xlog.c::XLogInsert` 了解 WAL 写入路径

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)

## References

1. [PostgreSQL Internals](https://www.postgresql.org/docs/current/internals.html)
2. [PostgreSQL Source Code (gitweb)](https://git.postgresql.org/gitweb/?p=postgresql.git;a=tree)
3. [Simple Dictionary of PostgreSQL Internals](https://wiki.postgresql.org/wiki/Developer_FAQ)
4. [PG Internals Mailing List Archive](https://www.postgresql.org/list/pgsql-hackers/)
5. *The Internals of PostgreSQL*（Hironobu Suzuki，电子书）
6. [bcAndCarl 文章](https://www.zhihu.com/people/neowu-99/posts)（知乎）