## Introduction

PostgreSQL 的锁分多个层级：表级、行级、页级、LWLock、Spinlock。主锁表（LOCK/PROCLOCK）与按 backend 局部的 Fast Path 机制协同，既保证正确性又在高并发下避免全局争用。本文覆盖锁层级、核心数据结构、Fast Path 优化与死锁检测，以及锁等待诊断。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18 |
| 核实日期 | 2026-10-15 |

## Lock Hierarchy

1. 表级锁：AccessShare / RowShare / RowExclusive / ShareUpdateExclusive / Share / ShareRowExclusive / Exclusive / AccessExclusive
2. 行级锁：FOR KEY SHARE / FOR SHARE / FOR NO KEY UPDATE / FOR UPDATE
3. 页面级锁：extension 内（heap_page_prune 等）
4. LWLock：内存结构同步
5. Spinlock：极短临界区

`Fast Path` 行锁：单事务内对同一行加锁时直接走 backend 局部数组，避免主锁表争用；超过阈值后才升级到主锁表。

## LOCK and PROCLOCK

```c
typedef struct LOCK {
    LOCKTAG      tag;             // 唯一标识锁对象
    LOCKMASK     grantMask;       // 已授予锁类型位掩码
    LOCKMASK     waitMask;        // 等待锁类型位掩码
    dclist_head  waitProcs;       // 睡眠的 PGPROC 链表
    int          requested[MAX_LOCKMODES];
    int          granted[MAX_LOCKMODES];
} LOCK;

typedef struct PROCLOCK {
    PROCLOCKTAG  tag;             // (LOCK*, PGPROC*)
    LOCKMASK     holdMask;        // 当前已持有锁类型
    LOCKMASK     releaseMask;     // 待释放掩码（无锁优化）
    dlist_node   lockLink;        // 挂到 LOCK->procLocks
    dlist_node   procLink;        // 挂到 PGPROC->procLocks
} PROCLOCK;
```

关键设计：PROCLOCK.tag 直接存 `LOCK*` 与 `PGPROC*` 指针，避免悬空与复杂 ID 映射；双重链表让锁管理器与事务退出清理都能快速遍历。

## Lock Manager Internal Synchronization

主锁表与 PROCLOCK 表对 hash 分区（default 16 个），每个分区配一把 LWLock：

- 普通加锁/解锁：仅锁目标锁所在分区
- 死锁检测：按分区编号**从小到大**顺序锁住所有分区，避免 LWLock 死锁
- LOCALLOCK（本地哈希表）：不分区，直接拿内部 spinlock

> [!NOTE]
>
> 避免 LWLock 死锁的规则：任何后端若需同时对多个分区加锁，必须按分区编号顺序执行。

## Fast Path Locking

针对"高频获取/释放、极少冲突"的锁做的优化，覆盖两类：

1. 弱关系锁（Weak relation locks）：如 SELECT 的 AccessShareLock
2. 轻量级行锁：单事务多行的 FOR KEY SHARE / FOR SHARE

超过阈值（如 `FP_LOCK_SLOTS_PER_BACKEND`）后升级到主锁表。这极大降低了简单查询的加锁开销，是 PG 高并发下仍保持高吞吐的关键。

## Diagnosing Lock Waits

```sql
SELECT pid, usename, state, wait_event_type, wait_event, query
  FROM pg_stat_activity
 WHERE wait_event_type = 'Lock' OR state = 'active'
 ORDER BY pid;

SELECT a.pid, a.usename, l.locktype, l.mode, l.granted, a.query
  FROM pg_locks l JOIN pg_stat_activity a ON l.pid = a.pid
 WHERE NOT l.granted;
```

`pg_locks` 视图直接暴露 LOCK/PROCLOCK 的全局状态，是排查锁等待与死锁的第一入口。

## Advisory Locks

`pg_advisory_lock` / `pg_advisory_xact_lock` 提供应用层自定义的会话/事务级锁，不关联任何表，常用于分布式协调或应用互斥（如单机任务调度去重）。

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [PostgreSQL Internals](/docs/CS/DB/PostgreSQL/Internals.md)
- [Transaction](/docs/CS/DB/PostgreSQL/Transaction.md)
- [MySQL lock](/docs/CS/DB/MySQL/lock.md)

## References

1. [PostgreSQL 官方文档: Explicit Locking](https://www.postgresql.org/docs/current/explicit-locking.html)
2. [PostgreSQL 源码: src/backend/storage/lmgr/lock.c](https://git.postgresql.org/gitweb/?p=postgresql.git;a=blob;f=src/backend/storage/lmgr/lock.c)
3. [MySQL lock](/docs/CS/DB/MySQL/lock.md)
