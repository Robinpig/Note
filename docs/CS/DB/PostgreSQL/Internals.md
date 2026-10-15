## Introduction

本章从源码层面梳理 PostgreSQL 的实现机制，目标读者是希望理解 PG 内部协作原理与扩展切入点的开发者，而非完整的代码逐行阅读指引。所有路径相对于 PostgreSQL 源码根目录 `src/`。

> 推荐先阅读一遍 PG 官方手册的 *"Overview of PostgreSQL Internals"*，再回看本章会更有体感。

> [!NOTE]
>
> 存储、MVCC、WAL、事务、索引、锁、VACUUM、复制、扩展等**机制细节已拆到专题**：[Storage](/docs/CS/DB/PostgreSQL/Storage.md) / [MVCC](/docs/CS/DB/PostgreSQL/MVCC.md) / [WAL](/docs/CS/DB/PostgreSQL/WAL.md) / [Transaction](/docs/CS/DB/PostgreSQL/Transaction.md) / [Index](/docs/CS/DB/PostgreSQL/Index.md) / [Lock](/docs/CS/DB/PostgreSQL/Lock.md) / [Vacuum](/docs/CS/DB/PostgreSQL/Vacuum.md) / [Replication](/docs/CS/DB/PostgreSQL/Replication.md) / [Extensions](/docs/CS/DB/PostgreSQL/Extensions.md)。本章聚焦源码布局、构建调试、进程/查询生命周期、内存上下文、Catalog 缓存等"如何读源码"的内容。

## Source Layout

> 基于 PostgreSQL 18.0（REL_18_STABLE）的实际目录布局。源码主要由 C 与少量汇编组成。

### Top-Level Structure

```
postgresql/                       # git clone 后根目录
├── configure                     # 编译入口脚本（autotools）
├── contrib/                      # 扩展模块（pg_stat_statements、pgcrypto 等）
├── src/
│   ├── backend/                  # 【核心】后端代码
│   ├── bin/                      # 工具程序（pg_ctl / initdb / pg_dump / psql）
│   ├── common/                   # 前后端共享（日志、配置解析、字符串）
│   ├── interfaces/               # 客户端接口（libpq / ecpg）
│   ├── port/                     # 平台适配层（Linux / Darwin / Win32）
│   ├── test/                     # 回归与隔离测试
│   └── timezone/                 # 时区数据与解析
└── src/Makefile.global.in
```

### Architecture Module → Source File Mapping (PG 18)

> 这是 GDB 调试与源码定位的关键速查表。

| 架构模块 | 子模块 | 关键源码文件 | 说明 |
| :--- | :--- | :--- | :--- |
| 主进程 | Postmaster | `src/backend/postmaster/postmaster.c` | 启动后台进程、监听连接、信号处理 |
|  | autovacuum | `src/backend/postmaster/autovacuum.c` | 自动 VACUUM 调度 |
| 解析器 | SQL 解析 | `src/backend/parser/gram.y` | Bison 语法 → `gram.c` |
|  | 词法 | `src/backend/parser/scan.l` | Flex 词法 → `scan.c` |
| 优化器 | 路径生成 | `src/backend/optimizer/path/allpaths.c` | `set_rel_pathlist` |
|  | 计划生成 | `src/backend/optimizer/plan/planner.c` | `standard_planner()` |
| 执行器 | 调度 | `src/backend/executor/execProcnode.c` | 递归执行 Plan 树 |
| 存储管理 | Buffer Manager | `src/backend/storage/buffer/bufmgr.c` | `BufferAlloc()`、`ReadBuffer()` |
| 事务系统 | MVCC | `src/backend/access/transam/xact.c` | Begin/Commit/Abort |
|  | CLOG | `src/backend/access/transam/clog.c` | 事务提交状态 |
| WAL | XLog 核心 | `src/backend/access/transam/xlog.c` | `XLogInsert()`、`XLogFlush()` |
| 索引 | B-Tree | `src/backend/access/nbtree/` | 插入/搜索/分裂 |
| 锁管理 | 主锁表 | `src/backend/storage/lmgr/lock.c` | `LockAcquire` / `LockRelease` |
| Catalog | 系统表 | `src/backend/catalog/pg_*.c` | `pg_class` / `pg_attribute` ... |
| 复制 | 物理复制 | `src/backend/replication/walsender.c` | WAL 发送 |
| 公共库 | 日志 | `src/common/elog.c` | `ereport()` |
|  | 内存上下文 | `src/backend/utils/mmgr/mcxt.c` | `MemoryContextAlloc()` |

## Build & Debug

> 来源：知乎用户 *bcAndCarl* 的「PostgreSQL 源码分析」系列，下文以 PG 18 为示例，PG 13+ 基本通用。

### Compile and Install

依赖包（RHEL 9 / CentOS 9 / Fedora）：

```bash
sudo dnf update -y
sudo dnf install -y gcc make readline-devel zlib-devel flex bison \
                    libxml2-devel libxslt-devel openssl-devel \
                    perl-devel perl-ExtUtils-Embed python3-devel tcl-devel \
                    openldap-devel pam-devel systemd-devel uuid-devel
```

获取源码：

```bash
git clone https://git.postgresql.org/git/postgresql.git
cd postgresql && git checkout REL_18_STABLE
```

配置（开启调试符号与断言，便于 GDB）：

```bash
./configure \
  --prefix=/usr/local/pgsql \
  --enable-debug \
  --enable-cassert \
  --with-openssl --with-perl --with-python --with-tcl \
  CFLAGS="-O0 -g3"
make -j$(nproc) && sudo make install
```

### Initialize / Start / Stop

```bash
sudo mkdir -p /usr/local/pgsql/data && sudo chown $USER /usr/local/pgsql/data
/usr/local/pgsql/bin/initdb -D /usr/local/pgsql/data
/usr/local/pgsql/bin/pg_ctl -D /usr/local/pgsql/data -l logfile start

# 单用户模式（适合 GDB 调试单条 SQL）
/usr/local/pgsql/bin/postgres --single -D /usr/local/pgsql/data
```

### Debug with GDB

多进程模型下调试单条 SQL，最简单的方式是**单用户模式 + GDB attach**；调试服务器模式则 `gdb -p <backend_pid>`。常用断点：

```
break exec_simple_query       # SQL 总入口
break standard_planner        # 规划器
break heap_insert             # 堆插入
break BufferAlloc             # 共享缓冲
break XLogInsert              # WAL 写入
```

### Recommended Learning Path (5 Days)

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
- **可插拔的访问方法**：所有表/索引最终都通过 Storage Manager（`smgr.c`）抽象操作文件；新增存储引擎只需实现 SMGR 接口
- **多层 hook / 扩展点**：`Plan hook`、`Executor hook`、`ProcessUtility hook`、`PG_STAT_*` 视图等都可以被外部 C 函数替换——这也是 PG 生态强大的根源
- **WAL/存储/快照/锁分层清晰**：每个模块都是单进程内的内存子系统，相互通过显式接口通信
- **系统表即 catalog**：系统表（pg_class、pg_attribute...）与用户表同构，元数据即数据

## Process & Connection Model

### Startup Flow (PostmasterMain Call Chain)

`PostmasterMain()`（`src/backend/postmaster/postmaster.c`）核心步骤：

```
PostmasterMain()
├── pqinitmask()                              // 创建信号集
├── InitializeGUCOptions()                     // 注册 300+ GUC 变量为默认值
├── SelectConfigFiles()                        // 两次 ProcessConfigFile（PG 18 设计）
├── checkDataDir() → checkControlFile()
├── CreateDataDirLockFile()                    // 写 postmaster.pid
├── CreateSharedMemoryAndSemaphores()
├── ListenServerPort()                         // TCP / Unix Socket
└── StartChildProcess() + ServerLoop()
```

关键信号处理：`SIGHUP`→重载配置；`SIGINT`/`SIGTERM`/`SIGQUIT`→三种关闭模式；`SIGUSR1`→pmsignal；`SIGCHLD`→回收子进程。

### ServerLoop (epoll Main Loop)

`ServerLoop()` 基于 **epoll** 实现 IO 多路复用：新连接到达 → `BackendStartup` → fork → `PostgresMain`；子进程退出 → SIGCHLD → `waitpid()` 回收。

### Backend Startup

子进程由 `PostmasterMain` → `BackendStartup` → `fork_process` 创建，进入 `PostgresMain`（`src/backend/tcop/postgres.c`）：协议握手 → `sigsetjmp` 错误恢复 → 主循环 `ReadCommand`/`ProcessQuery`。

### Client Communication Protocol

PG 使用 V3 消息协议（主要类型，`src/backend/libpq/pqcomm.c`）：

| 字节 | 消息 |
| :--- | :--- |
| 'Q' | 简单查询（Query） |
| 'P'/'B'/'D'/'E'/'C'/'S' | 扩展查询（Parse/Bind/Describe/Execute/Close/Sync） |
| 'X' | 终止连接（Terminate） |
| 'D' | 数据行（DataRow） |

扩展查询流水线允许多语句单往返，是高并发驱动和 ORM 的首选路径。

### JDBC prepareStatement Full Link (PG 18 Practice)

简单 prepare/execute 对应四个 FE/BE 消息：

```
客户端 (JDBC)                    服务端 (postgres backend)
   │── Parse(name, sql, types) ───────► exec_parse_message
   │◄── ParseComplete ──────────────────
   │── Bind(name→portal, params) ──────► exec_bind_message
   │◄── BindComplete ───────────────────
   │── Describe(portal) ───────────────► exec_describe_message
   │◄── RowDescription ─────────────────
   │── Execute(portal, max_rows) ──────► exec_execute_message
   │◄── DataRow* / CommandComplete ─────
   │── Sync ───────────────────────────►
```

`PortalRun` 是扩展查询的执行入口（`src/backend/tcop/pquery.c`），debug 必打断点：`PostgresMain` / `exec_parse_message` / `exec_bind_message` / `exec_execute_message` / `PortalRun` / `ExecutorRun` / `pg_plan_query` / `PortalDrop`。

## Query Lifecycle

### Comprehensive View: 5 Stages

| # | 阶段 | 入口 | 责任 |
| :--- | :--- | :--- | :--- |
| 1 | **Parser** | `raw_parser()` | flex/bison 检查字面语法错误 → 输出 raw_parsetree |
| 2 | **Analyzer** | `parse_analyze_fixedparams()` | 表名/字段名解析、OID 转换、类型检查 → query tree |
| 3 | **Rewriter** | `QueryRewrite()` | 把 VIEW/RULE 引用展开 → 重写后的 query tree |
| 4 | **Planner** | `pg_plan_queries()` | 估算成本、生成多条 path → 最优 PlannedStmt |
| 5 | **Executor** | `ExecutorRun()` | 拉取 TupleTableSlot → 通过 Portal/DestReceiver 输出 |

辅助模块：`get_relation_info()`（`optimizer/util/plancat.c`）告诉规划器每张表的页数/元组数/索引/列类型；HeapAccessMethod（`access/heap/`）是执行器最终读写 Heap 数据页的层。

### End-to-End Path Under Simple Query Protocol

```
字符串 (Query)
   │ pg_parse_query
   ▼ parsenodes
   │ parse_analyze (analyzer)
   ▼ Query ← pg_rewrite_query (rewriter)
   │ planner (optimizer)
   ▼ PlannedStmt
   │ CreatePortal / PortalRun
   ▼ Executor ← ExecutorRun / ExecutorStart
   ▼ 结果集 / 消息流回客户端
```

每一步都可以被 hook 拦截：`planner_hook` / `set_rel_pathlist_hook` / `ProcessUtility_hook` / `ExplainOneQuery_hook`。

### Parser

`src/backend/parser/`：`scan.l`（flex）词法 → `scan.c`；`gram.y`（bison）语法 → `gram.c`；`analyze.c` 语义分析注入列类型/权限/命名空间。输出 `List *parsetree`，每个元素为 `RawStmt`/`SelectStmt`/...，再被 `parse_analyze` 包成 `Query`。

### Analyzer

`parse_analyze` 把 `SELECT *` 展开、解析子查询为子 `Query`、解析 RTE、进行 `pg_*` 系统表查询。这一步大量命中 `pg_class` / `pg_attribute` / `pg_proc`，PG 用 `syscache`（`utils/cache/syscache.c`）缓存系统表查询结果。

### Rewriter

`rewrite/rewriteHandler.c` + `rewrite/rewriteManip.c`：视图展开、RULE 系统（`CREATE RULE`）、`COPY` 折叠。简单 SELECT 通常不触发重写，带视图/规则的 SQL 必然经过。

### Planner / Optimizer

`src/backend/optimizer/`：`plan/planner.c` 主入口；`paths/allpaths.c` 路径生成；`paths/costsize.c` 代价估算；`plan/createplan.c` 从路径生成 Plan。典型流程：`planner → subquery_planner → grouping_planner → query_planner → generate_paths → create_plan`。

### Executor

`src/backend/executor/`：`execMain.c`（`ExecutorStart/Run/Finish/End`）、`execProcnode.c`（Plan 节点分发）、`nodeSeqscan.c`/`nodeIndexscan.c`/...、`execQual.c`（表达式求值）、`execTuples.c`（TupleTableSlot）。每个 Plan 节点遵循同一范式：`Exec<Name>Node` 每次返回一条 tuple。

PG 11+ 引入了 LLVM JIT 编译表达式：`src/backend/jit/`（`jit.c`/`llvmjit.c`/`llvmjit_expr.c`/`llvmjit_deform.c`）。

### Parallel Query and JIT

> 这两个能力是 PG 执行层近年的重要演进，归在 Query Lifecycle 一并说明。

**并行查询**（PG 9.6 引入 seq scan 并行，PG 10+ 增强）：规划器在顶层插入 `Gather` / `Gather Merge` 节点，并行 worker 通过 `RegisterDynamicBackgroundWorker` 派生（dynamic bgworker，见 Background Workers），各自扫描分片后由 Gather 汇总。受 `max_parallel_workers_per_gather`、`min_parallel_table_scan_size` 控制；worker 数与表大小、并行度设置相关。

**JIT**（PG 11 引入）：当查询估算代价超过 `jit_above_cost` 时，把表达式求值（`ExecInterpExpr` 的字节码）与 tuple deform 编译为 LLVM 机器码，降低热点循环的解析开销。更激进的内联/优化由 `jit_inline_above_cost` / `jit_optimize_above_cost` 控制；`jit` 扩展需编译期 `--with-llvm` 启用。

### Plan Tree and Portal

`pg_plan_queries()` 把 Query 链表变 PlannedStmt 链表，`PlannedStmt.planTree` 是根节点（`Plan *`，多态）。所有 SQL 执行都通过 Portal：

```
CreatePortal → PortalDefineQuery → PortalStart → PortalRun → PortalDrop
```

策略选择 `ChoosePortalStrategy`：`PORTAL_ONE_SELECT` / `PORTAL_ONE_RETURNING` / `PORTAL_UTIL_SELECT` / `PORTAL_MULTI_QUERY`。

## Memory Context

`src/backend/utils/mmgr/`：`mcxt.c`（框架）、`aset.c`（默认 allocset 分配器）、`dsa.c`（动态共享内存）、`slab.c`、`generation.c`。每次语句执行都在 `ExecutorStart` 创建 `ExecutorState`，结束后 `MemoryContextDelete` 一次性回收。

```c
typedef struct MemoryContextData {
    NodeTag     type;
    bool        isReset;
    bool        allowInCritSection;
    const MemoryContextMethods *methods;
    MemoryContext parent;
    MemoryContext firstchild;
    MemoryContext prevchild;
    MemoryContext nextchild;
    char       *name;
} MemoryContextData;
```

典型进程内 MemoryContext 树：`TopMemoryContext` → `CacheMemoryContext`（各 syscache）/ `TopTransactionContext`（事务提交回滚销毁）/ `PortalContext` / `ExecutorState`（含 Per-Tuple-Context，每 1000 条 tuple 重建）。

### AllocSetContext

`AllocSetContext` 含 12 个 freelist 桶（按 chunk 大小分桶，16B 起翻倍至 64KB）。`palloc` 对小 chunk 直接从对应 freelist 弹出（5~6 条指令），`MemoryContextReset` 一行清空所有 chunk 不需逐个 free。

## Catalog & Cache

`src/backend/catalog/`：`catalog.c`/`system_views.h`（系统表 schema）、`pg_proc.dat`/`pg_operator.dat` 等数据驱动元数据声明、`genbki.pl` 将 `.dat` 转 C、`aclchk.c` 权限。

`utils/cache/` 是 backend 私有的元数据缓存层，避免每条查询都查系统表：

- **syscache**（`syscache.c`）：基于 OID 哈希缓存系统表行（`pg_class`/`pg_attribute`/`pg_proc`/...），`SearchSysCache` 是执行器/解析器最常用的查元数据入口
- **relcache**（`relcache.c`）：缓存 `RelationData`（表结构、属性、索引、约束），`table_open`/`relation_open` 走它
- **typcache**（`typcache.c`）：类型缓存（类型 IO 函数、数组/域类型信息）
- **inval**（`inval.c` / `inval_messages`）：缓存失效广播（`CacheInvalidateHeapTuple` 等），DDL 修改系统表后通知各 backend 丢弃本地缓存

> [!NOTE]
>
> syscache/relcache 是每个 backend 私有的 KV 缓存——OLTP 这种共享资源竞争激烈的场景，缓存保护机制非常重要（如 `parserOpenTable` 走 relcache 拿 `Relation`，再查 syscache 拿列类型）。缓存失效是 DDL 后"为什么新会话才看到表结构变更"的根本原因。

## Background Workers

`src/backend/postmaster/` 与 `src/backend/storage/bgworker/` 提供通用 worker 框架，启动顺序在 `PostmasterMain` 中：先启动 startup 回放（崩溃恢复），再 fork 自定义 `bgworkers`。除内置 bgwriter/checkpointer/autovacuum/逻辑复制 launcher 外，用户可用 `RegisterBackgroundWorker` / `RegisterDynamicBackgroundWorker` 注册自定义 worker（并行查询的 worker 即 dynamic bgworker）。

## How to Read the Source

- 学会用 `git log --grep=<符号>` 跟踪某特性演化
- 学会用 `git grep -n <symbol>` 跨目录定位
- 配合官方手册的 *"Overview of PostgreSQL Internals"* 阅读
- 阅读 `src/backend/storage/bufmgr.c` 的 `ReadBuffer_internal`，理解 Buffer Pool 与 Heap 交互
- 阅读 `src/backend/optimizer/plan/planner.c` 的 `planner()`，理解规划全貌
- 阅读 `src/backend/executor/execMain.c` 的 `ExecutorRun`，看 Plan 节点如何被调度
- 阅读 `src/backend/access/transam/xlog.c::XLogInsert` 了解 WAL 写入路径

## Mechanisms Detail Elsewhere

以下机制的源码细节已拆到独立专题（机制原理 + 源码路径）：

- 存储页与 Buffer Pool：[Storage](/docs/CS/DB/PostgreSQL/Storage.md)
- 多版本与可见性：[MVCC](/docs/CS/DB/PostgreSQL/MVCC.md)
- WAL 记录与崩溃恢复：[WAL](/docs/CS/DB/PostgreSQL/WAL.md)
- 状态机与 CLOG：[Transaction](/docs/CS/DB/PostgreSQL/Transaction.md)
- B-Tree 物理组织：[Index](/docs/CS/DB/PostgreSQL/Index.md)
- LOCK/PROCLOCK 与死锁：[Lock](/docs/CS/DB/PostgreSQL/Lock.md)
- autovacuum 与 freeze：[Vacuum](/docs/CS/DB/PostgreSQL/Vacuum.md)
- 逻辑解码与复制槽：[Replication](/docs/CS/DB/PostgreSQL/Replication.md)
- 扩展 hook 与 FDW：[Extensions](/docs/CS/DB/PostgreSQL/Extensions.md)

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [MySQL Mvcc](/docs/CS/DB/MySQL/Mvcc.md)
- [Undo Log](/docs/CS/DB/MySQL/undolog.md)
- [Architecture](/docs/CS/DB/PostgreSQL/Architecture.md)
- [Query Lifecycle 相关: Storage](/docs/CS/DB/PostgreSQL/Storage.md)

## References

1. [PostgreSQL 官方文档: Overview of PostgreSQL Internals](https://www.postgresql.org/docs/current/overview.html)
2. [PostgreSQL 源码](https://git.postgresql.org/gitweb/?p=postgresql.git)
