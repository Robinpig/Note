## Introduction

PostgreSQL 通过在每行上保存 `xmin`（插入事务 ID）和 `xmax`（删除/更新事务 ID）实现多版本并发控制：读者按自己的快照判断哪一行版本对自己可见，写者从不阻塞读者。本文覆盖可见性判定、快照结构、XID 回绕与 freeze。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18（REL_18_STABLE） |
| 源码核实基线 | `REL_18_STABLE` |
| 核实日期 | 2026-10-15 |

## MVCC Basics

PG 在每行保存：

- `t_xmin`：插入该版本的事务 ID
- `t_xmax`：删除/锁定该版本的事务 ID（未删除时为 0；UPDATE 即旧行打 xmax + 新插入）

一个事务的快照记录当时活跃 xid 列表，决定哪些行版本对它可见：

- 行 `t_xmin` 在快照中已提交且不在活跃集合 → 可见
- 行 `t_xmax` 未提交或属于当前事务 → 仍可见
- 行 `t_xmax` 已提交 → 不可见（被删除或被新版本替代）

> [!NOTE]
>
> PG 与 Oracle/MySQL 不同：**存储引擎只有 WAL 没有 undo log**——旧版本完全留在数据文件里，靠 VACUUM 回收 dead tuples（见 [Vacuum](/docs/CS/DB/PostgreSQL/Vacuum.md)）。这也是 PG 表膨胀的根因：长事务或落后 autovacuum 会让 dead tuple 长期不被回收。

## Visibility Functions

可见性判定主入口在 `src/backend/utils/time/tqual.c`（PG 16 起分散到 `heapam_visibility.c`），按隔离级别走不同函数：

| 函数 | 用途 |
| :--- | :--- |
| `HeapTupleSatisfiesMVCC` | Read Committed / Repeatable Read 默认 |
| `HeapTupleSatisfiesSelf` | 构建 catalog 时 |
| `HeapTupleSatisfiesToast` | TOAST 内部 |
| `HeapTupleSatisfiesUpdate` / `HeapTupleSatisfiesDirty` | DML 路径 |
| `HeapTupleSatisfiesVacuum` | VACUUM 路径 |
| `HeapTupleSatisfiesHistoricMVCC` | 已结束事务的快照回溯（逻辑解码） |

`t_infomask` 中的 hint bit（`HEAP_XMIN_COMMITTED`/`HEAP_XMAX_INVALID` 等）可加速判定，绕过 clog/SLRU 读——但这些是"提示"而非真相来源，未被设置时仍要查 CLOG。

## SnapshotData

```c
typedef struct SnapshotData {
    SnapshotType   snapshot_type;
    TransactionId  xmin;     // 活跃事务中最小 xid（< xmin 全部已结束）
    TransactionId  xmax;     // 已分配 max xid + 1（>= xmax 都未开始）
    TransactionId *xip;      // 活跃顶层事务 ID 列表
    TransactionId *subxip;   // 活跃子事务 ID 列表（缓存未溢出时）
    bool           suboverflowed;
    ...
} SnapshotData;
```

基本规则：`xmin <= t_xmin < xmax` 的 insert 提交状态查 `xip`；`t_xmax != 0` 时按 xmax 也走查 `xip`；hint bit 可加速。

## GetSnapshotData

`GetSnapshotData()` 是所有快照采集源头，持 `ProcArrayLock`：

- 普通快照：`LW_SHARED`（多个并发读快照可并行，但阻塞 VACUUM 拿 EXCLUSIVE）
- 事务注册/注销/VACUUM：`LW_EXCLUSIVE`
- 复用快照（`GetSnapshotDataReuse`）：可提前释放

它遍历 `PGPROC` 全局数组拷贝所有活跃事务 xid 到 `snap->xip`，计算 `xmin`/`xmax` 后释放锁。`ProcArrayLock` 是快照采集的全局热点。

## XID Wraparound and FrozenTransactionId

XID 是 32-bit 环形递增，达到 2^31 后会"穿过"过去。为避免把旧行误判为"未提交事务"，PG 引入 `FrozenTransactionId`（常量 2）：

- 行 `t_xmin = FrozenTransactionId` 的"创建事务"永远视为已提交
- VACUUM 把足够老的 xmin 替换为 `FrozenTransactionId`
- 防回绕：`autovacuum` 在 `age(relfrozenxid) > autovacuum_freeze_max_age` 时强制 VACUUM

> [!WARNING]
>
> XID 回绕会导致数据静默损坏且不可逆。生产环境必须监控 `age()` 与 autovacuum，必要时手动 `VACUUM FREEZE` 大表，避免单表 xid 年龄逼近 2^31。

## Observing MVCC Across Sessions

```sql
-- Session 1
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT lp, lp_off, t_xmin, t_xmax, t_ctid, t_data
  FROM heap_page_items(get_raw_page('test', 0));

-- Session 2
BEGIN; UPDATE test SET c1='BBBB' WHERE id=3; COMMIT;

-- Session 1 再查仍看到旧值，COMMIT 后才看到新值
```

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [PostgreSQL Internals](/docs/CS/DB/PostgreSQL/Internals.md)
- [Storage](/docs/CS/DB/PostgreSQL/Storage.md)
- [Transaction](/docs/CS/DB/PostgreSQL/Transaction.md)
- [WAL](/docs/CS/DB/PostgreSQL/WAL.md)
- [MySQL Mvcc](/docs/CS/DB/MySQL/Mvcc.md)

## References

1. [PostgreSQL 官方文档: MVCC](https://www.postgresql.org/docs/current/mvcc.html)
2. [PostgreSQL 官方文档: Routine Vacuuming (Preventing Transaction ID Wraparound)](https://www.postgresql.org/docs/current/routine-vacuuming.html)
3. [MySQL Mvcc](/docs/CS/DB/MySQL/Mvcc.md)
