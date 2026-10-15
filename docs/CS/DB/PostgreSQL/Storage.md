## Introduction

PostgreSQL 的默认存储引擎是 **Heap（堆表）**：数据以 8 KB 页为单位组织，行版本（tuple）追加写入、从不原地覆盖，旧版本由 VACUUM 回收。所有表与索引最终都通过 Storage Manager（`smgr`）抽象落到文件，再经 Buffer Pool 与文件系统交互。本文覆盖页与元组布局、TOAST、FSM/VM、Full Page Writes，以及 SMGR/Buffer Pool 的源码层组织。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18（REL_18_STABLE） |
| 页面默认大小 | 8 KB（`--with-blocksize` 可调 1/2/4/8/16/32 KB） |
| 段文件大小 | 1 GB（`RELSEG_SIZE`） |
| 核实日期 | 2026-10-15 |

## Heap and Page Layout

一个 Heap 页（block）默认 8 KB，内部布局如下：

```
+-----------+----------------+---------------+
|   Header  |   ItemPointer  |   Free Space  |
|  24 byte  |      Array     |               |
+-----------+----------------+---------------+ <-- lower
|                                                 |
|              Tuple Data                          |
|                                                 |
+-------------------------------------------------+ <-- upper
|   Special Space (索引相关)                          |
+-------------------------------------------------+
```

- Header 含 `pd_lsn`（页面最新 WAL LSN）、`pd_checksum`（可选）、`pd_lower`、`pd_upper`、`pd_special`
- 每行由 `HeapTupleHeaderData`（含 `t_xmin`/`t_xmax`/`t_infomask`/`t_ctid` 等）与用户数据组成
- `ItemPointer`（行指针）记录 tuple 在页内的偏移与长度，是 `ctid` 的物理来源

## Tuple Header

每行记录的磁盘头部 `HeapTupleHeaderData`（固定 23 字节）是 MVCC 的物理载体：

| 字段 | 字节 | 含义 |
| :--- | :--- | :--- |
| `t_xmin` | 4 | 插入此行版本的事务 ID；tuple 的"出生证" |
| `t_xmax` | 4 | 删除/锁定此行版本的事务 ID；UPDATE 后旧行的 xmax 被设上 |
| `t_field3` | 4 | union，存 `t_cid` 或老式 `t_xvac`（VACUUM FULL 标记） |
| `t_ctid` | 6 | 当前/更新后新行的 TID；多版本靠它形成链表 |
| `t_infomask2` | 2 | 高位：列数；低位：二级标志 |
| `t_infomask` | 2 | 可见性/锁/状态标志（`HEAP_XMIN_COMMITTED`/`HEAP_XMAX_INVALID`/`HEAP_HOT_UPDATED` 等） |
| `t_hoff` | 1 | 整个头部长度（bitmap + padding），决定用户数据起点 |

> [!NOTE]
>
> 行内字段按定义顺序紧凑排列，NULL 列用 `t_infomask2` 后的 NULL bitmap 标记，不占数据宽度。`UPDATE` 在 PG 中等价于"旧行打 `t_xmax` + 插入新版本"，新版本通过 `t_ctid` 链到旧版本形成版本链（详见 [MVCC](/docs/CS/DB/PostgreSQL/MVCC.md)）。

## TOAST

超出行存储边界（默认约 2 KB）的字段会被自动拆出存到独立的 TOAST 表，原始行只留 18 字节指针。存储策略由 `ALTER TABLE ... SET STORAGE` 控制：

| 策略 | 行为 |
| :--- | :--- |
| `PLAIN` | 禁止压缩/行外，仅用于定长类型 |
| `EXTENDED` | 先压缩，超大再行外（默认） |
| `MAIN` | 先尝试不压缩，超大才行外 |
| `EXTERNAL` | 不压缩，超大行外（行外读更快但无压缩收益） |

## FSM and VM

- **FSM（Free Space Map）**：记录每个表文件每个页面的空闲空间大小，INSERT 时据此选择目标页
- **VM（Visibility Map）**：记录每个页面上所有 tuple 是否对所有事务可见，加速 `VACUUM` 跳过干净页，以及 index-only scan 免去回表可见性检查

## Full Page Writes

PG 默认开启 `full_page_writes`：每次 checkpoint 后第一次修改某页时，把**整页**写入 WAL。目的是防止崩溃恢复时遇到半写的"撕裂页"（partial write）。代价是 WAL 体积膨胀，常通过 `wal_compression = zstd`（或 `lz4`，PG 15+）缓解。

## Storage Manager and Relation Segments

`src/backend/storage/smgr/`：

- `smgr.c`：SMGR 抽象 API 与调度
- `md.c`：磁盘实现（md = magnetic disk），最常见
- `fd.c`：底层 vfd（虚拟文件描述符）层
- `sync.c`：fsync 协调

每个表/索引对应一个 `SMgrRelation`，持有按 `RELSEG_SIZE`（默认 1 GB）切分的 segment 文件（如 `16384.1`、`16384.2`）。超过 1 GB 的表自动切到下一个 segment，避免单文件过大。

> [!NOTE]
>
> `relfilenode` 是文件命名标识，通常等于 `pg_class.relfilenode`；`TRUNCATE`/`VACUUM FULL`/`CLUSTER` 会分配新的 relfilenode，物理文件名随之改变，但逻辑表名不变。

## Buffer Pool

`src/backend/storage/buffer/`：

- `bufmgr.c`：`ReadBuffer`/`MarkBufferDirty`/`ReleaseBuffer`/`FlushBuffer`
- `buf_table.c`：BufferTag → BufferDescriptor 哈希表
- `freelist.c`：共享 freelist（clock-sweep 替换）
- `localbuf.c`：临时表的本地 buffer

关键结构：

- `BufferTag = { rnode, forkNum, blockNum }` 唯一定位一个磁盘页
- 替换策略为 clock-sweep（近似 LRU，多轮扫描）
- `BufferAlloc` 是所有"逻辑读"的源头——任何 backend 想访问 8 KB 页都必须经过它，未命中时 `GetVictimBuffer` 选 victim 并从磁盘读入

**128 把分区锁**：`BufTable` 用 128 把 LWLock 把哈希表切成 128 个分片，极大降低并发争用——逻辑读之间不阻塞（不同分片），但逻辑读与物理读、物理读与物理读之间在同一分片内互相阻塞。

## Inspecting Pages with pageinspect

编译并加载 `contrib/pageinspect`，可直接 dump 物理页面：

```sql
CREATE EXTENSION pageinspect;
SELECT lp, lp_off, t_xmin, t_xmax, t_ctid, t_data
  FROM heap_page_items(get_raw_page('orders', 0));
```

`heap_page_items` 列出页内所有 line pointer 与 tuple 头，是观察 MVCC 多版本物理布局最直接的手段。

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [PostgreSQL Internals](/docs/CS/DB/PostgreSQL/Internals.md)
- [MVCC](/docs/CS/DB/PostgreSQL/MVCC.md)
- [WAL](/docs/CS/DB/PostgreSQL/WAL.md)
- [B-Link Tree](/docs/CS/Algorithms/tree/B_Link_Tree.md)

## References

1. [PostgreSQL 官方文档: Database Physical Storage](https://www.postgresql.org/docs/current/storage.html)
2. [PostgreSQL 官方文档: TOAST](https://www.postgresql.org/docs/current/storage-toast.html)
3. [pageinspect — PostgreSQL 扩展](https://www.postgresql.org/docs/current/pageinspect.html)
