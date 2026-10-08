## Introduction

| 项 | 值 |
| :--- | :--- |
| 正文默认版本 | MySQL 9.7.x LTS（最新 9.7.3，2026-08-18） |
| 源码核实基线 | tag `mysql-9.7.2`（`storage/innobase/lock/lock0wait.cc`、`lock/lock0lock.cc`、`include/lock0lock.h`、`include/trx0trx.h`） |
| 次要兼容目标 | MySQL 8.4.x LTS |
| 已停止支持 | MySQL 8.0（EOL **2026-04-30**）、MySQL 5.7（EOL 2023-10） |
| 核实日期 | 2026-10-07 |

> [!NOTE]
> 本篇带「旧版本」标记的小节保留 8.0.18 以前的叙述作为历史脉络，当前行为以 `Lock Scheduling CATS` 与 `Detection In MySQL 9.7` 两节为准。本目录的版本坐标与勘误见 [Version Migration](/docs/CS/DB/MySQL/Version_Migration.md)。

InnoDB 事务执行过程中，加表锁或者行锁之后，释放锁最常见的时机是事务提交或者回滚即将完成时。

因为事务的生命周期结束，它加的锁的生命周期也随之结束。

有一种情况，加锁只是权宜之计，临时为之。如果这种锁也要等到事务提交或者回滚即将完成时才释放，阻塞其它事务的时间也可能更长，这就有点不合理了。所以，这种锁会在事务运行过程中及时释放。

还有一种情况，虽然是在事务提交过程中释放锁，但是并不会等到提交即将完成时才释放，而是在二阶段提交的 prepare 阶段就提前释放。

最后，有点特殊的就是 AUTO-INC 锁了




我们先来看看只是权宜之计的加锁场景。

select、update、delete 语句执行过程中，不管 where 条件是否命中索引，也不管是等值查询还是范围查询，只要扫描过的记录，都会加行锁。

> 和 update、delete 不一样，select 只在需要加锁时，才会按照上面的逻辑加锁。




## Two-Phase Locking

InnoDB uses a two-phase locking protocol. It can acquire locks at any time during a transaction, but it does not
release them until a `COMMIT` or `ROLLBACK`.

> ⚠️ 严格说「同一时刻释放所有锁」只对 `REPEATABLE READ` 成立。`lock0lock.h` 的锁生命周期注释明确写了：
> 在 Read Committed 及更弱隔离级别下，第 3 步与第 4 步之间还有一步，InnoDB 会**提前释放部分 gap 上的读锁**，
> 目的是降低复制时的死锁风险。原表述照抄自 5.7 时代资料，未区分隔离级别。

## Locking Types

```sql
mysql> select * from information_schema.innodb_locks;
mysql> select * from information_schema.innodb_lock_waits;
mysql> select * from information_schema.innodb_trx;
```

row-level locking only be implemented at server level.

### Shared and Exclusive Locks

`InnoDB` implements standard **row-level locking** where there are two types of locks, shared (`S`) locks and exclusive (`X`) locks.

- A shared (`S`) lock permits the transaction that holds the lock to read a row.
- An exclusive (`X`) lock permits the transaction that holds the lock to update or delete a row.

If transaction `T1` holds a shared (`S`) lock on row `r`, then requests from some distinct transaction `T2` for a lock on row `r` are handled as follows:

- A request by `T2` for an `S` lock can be granted immediately. As a result, both `T1` and `T2` hold an `S` lock on `r`.
- A request by `T2` for an `X` lock cannot be granted immediately.

If a transaction `T1` holds an exclusive (`X`) lock on row `r`, a request from some distinct transaction `T2` for a lock of either type on `r` cannot be granted immediately.
Instead, transaction `T2` has to wait for transaction `T1` to release its lock on row `r`.

### Intention Locks

`InnoDB` supports *multiple granularity locking* which permits coexistence of row locks and table locks.
For example, a statement such as `LOCK TABLES ... WRITE` takes an exclusive lock (an `X` lock) on the specified table.
To make locking at multiple granularity levels practical, `InnoDB` uses intention locks.
Intention locks are **table-level** locks that indicate which type of lock (shared or exclusive) a transaction requires later for a row in a table.
There are two types of intention locks:

- An intention shared lock (`IS`) indicates that a transaction intends to set a *shared* lock on individual rows in a table.
- An intention exclusive lock (`IX`) indicates that a transaction intends to set an exclusive lock on individual rows in a table.

For example, `SELECT ... FOR SHARE` sets an `IS` lock, and `SELECT ... FOR UPDATE` sets an `IX` lock.

The intention locking protocol is as follows:

- Before a transaction can acquire a shared lock on a row in a table, it must first acquire an `IS` lock or stronger on the table.
- Before a transaction can acquire an exclusive lock on a row in a table, it must first acquire an `IX` lock on the table.

Table-level lock type compatibility is summarized in the following matrix.


|      | `X`      | `IX`       | `S`        | `IS`       |
| :--- | :------- | :--------- | :--------- | :--------- |
| `X`  | Conflict | Conflict   | Conflict   | Conflict   |
| `IX` | Conflict | Compatible | Conflict   | Compatible |
| `S`  | Conflict | Conflict   | Compatible | Compatible |
| `IS` | Conflict | Compatible | Compatible | Compatible |

### Record Locks

A record lock is a lock on an index record.
For example, `SELECT c1 FROM t WHERE c1 = 10 FOR UPDATE;` prevents any other transaction from inserting, updating, or deleting rows where the value of `t.c1` is `10`.

**Record locks always lock index records**, even if a table is defined with no indexes.
For such cases, `InnoDB` creates a hidden clustered index and uses this index for record locking.

### Gap Locks

**A gap lock is a lock on a gap between index records, or a lock on the gap before the first or after the last index record.**
For example, `SELECT c1 FROM t WHERE c1 BETWEEN 10 and 20 FOR UPDATE;` prevents other transactions from inserting a value of `15` into column `t.c1`,
whether or not there was already any such value in the column, because the gaps between all existing values in the range are locked.

**A gap might span a single index value, multiple index values, or even be empty.**

Gap locks are part of the tradeoff between performance and concurrency, and are used in some transaction isolation levels and not others.

*Gap locking is not needed for statements that lock rows using a unique index to search for a unique row.*
(This does not include the case that the search condition includes only some columns of a multiple-column unique index; in that case, gap locking does occur.)

If `id` is not indexed or has a nonunique index, the statement does lock the preceding gap.

It is also worth noting here that conflicting locks can be held on a gap by different transactions.
For example, transaction A can hold a shared gap lock (gap S-lock) on a gap while transaction B holds an exclusive gap lock (gap X-lock) on the same gap.
The reason conflicting gap locks are allowed is that if a record is purged from an index, the gap locks held on the record by different transactions must be merged.

Gap locks in `InnoDB` are “purely inhibitive”, which means that their only purpose is to prevent other transactions from inserting to the gap.
Gap locks can co-exist. A gap lock taken by one transaction does not prevent another transaction from taking a gap lock on the same gap.
**There is no difference between shared and exclusive gap locks. They do not conflict with each other, and they perform the same function.**

Gap locking can be disabled explicitly. This occurs if you change the transaction isolation level to `READ COMMITTED`.
In this case, gap locking is disabled for searches and index scans and is used only for foreign-key constraint checking and duplicate-key checking.

There are also other effects of using the `READ COMMITTED` isolation level.
*Record locks for nonmatching rows are released after MySQL has evaluated the `WHERE` condition. For `UPDATE` statements, `InnoDB` does a “semi-consistent” read,
such that it returns the latest committed version to MySQL so that MySQL can determine whether the row matches the `WHERE` condition of the `UPDATE`.*

### Next-Key Locks

**A next-key lock is a combination of a record lock on the index record and a gap lock on the gap before the index record.**

`InnoDB` performs row-level locking in such a way that when it searches or scans a table index, it sets shared or exclusive locks on the index records it encounters.
Thus, **the row-level locks are actually index-record locks**.
*A next-key lock on an index record also affects the “gap” before that index record.*
That is, a next-key lock is an index-record lock plus a gap lock on the gap preceding the index record.
If one session has a shared or exclusive lock on record `R` in an index, another session cannot insert a new index record in the gap immediately before `R` in the index order.

For the last interval, the next-key lock locks the gap above the largest value in the index and the “supremum” pseudo-record having a value higher than any value actually in the index.
The supremum is not a real index record, so, in effect, this next-key lock locks only the gap following the largest index value.

> [!NOTE]
>
> By default, `InnoDB` operates in `REPEATABLE READ` transaction isolation level.
> In this case, **`InnoDB` uses next-key locks for searches and index scans, which prevents `phantom rows`**.

### Insert Intention Locks

**An insert intention lock is a type of gap lock set by `INSERT` operations prior to row insertion**.
This lock signals the intent to insert in such a way that multiple transactions inserting into the same index gap need not wait for each other if they are not inserting at the same position within the gap.
Suppose that there are index records with values of 4 and 7.
Separate transactions that attempt to insert values of 5 and 6, respectively, each lock the gap between 4 and 7 with insert intention locks prior to obtaining the exclusive lock on the inserted row,
but do not block each other because the rows are nonconflicting.

### AUTO-INC Locks

An `AUTO-INC` lock is a special table-level lock taken by transactions inserting into tables with `AUTO_INCREMENT` columns.
In the simplest case, if one transaction is inserting values into the table, any other transactions must wait to do their own inserts into that table,
so that rows inserted by the first transaction receive consecutive primary key values.

The `innodb_autoinc_lock_mode` variable controls the algorithm used for auto-increment locking.
It allows you to choose how to trade off between predictable sequences of auto-increment values and maximum concurrency for insert operations.


```sql
SHOW VARIABLES LIKE 'innodb_autoinc_lock_mode'; -- 2
```

We cannot create yet another interval as we already contain one. 
This situation can happen. 
Assume innodb_autoinc_lock_mode>=1 and 
CREATE TABLE T(A INT AUTO_INCREMENT PRIMARY KEY) ENGINE=INNODB;

INSERT INTO T VALUES (NULL),(NULL),(1025),(NULL);
      
Then InnoDB will reserve [1,4] (because of 4 rows) then [1026,1026]. 
Only the first interval is important for statement-based binary logging as it tells the starting point. 
So we ignore the second interval:


Update & Delete 加锁

ClusterIndex

命中 都是X锁

未命中 只有RR加GAP锁

Second Unique Index
命中 二级索引和聚簇索引都是X锁

未命中 只有RR在二级索引加GAP锁

二级非唯一索引

命中 RC对两个索引加X锁 RR对二级索引加X和GAP锁 对Cluster索引加X锁

未命中 只有RR在二级索引加GAP锁


INSERT语句加锁

- 为了防止幻读，如果记录之间加有GAP锁，此时不能INSERT。
- 如果INSERT的记录和已有记录造成唯一键冲突，此时不能INSERT。


## Lock System Source Code

```cpp

/** Lock modes and types */
/** @{ */
#define LOCK_MODE_MASK                          \
  0xFUL /*!< mask used to extract mode from the \
        type_mode field in a lock */
/** Lock types */
#define LOCK_TABLE 16 /*!< table lock */
#define LOCK_REC 32   /*!< record lock */
#define LOCK_TYPE_MASK                                \
  0xF0UL /*!< mask used to extract lock type from the \
         type_mode field in a lock */
#if LOCK_MODE_MASK & LOCK_TYPE_MASK
#error "LOCK_MODE_MASK & LOCK_TYPE_MASK"
#endif

#define LOCK_WAIT                          \
  256 /*!< Waiting lock flag; when set, it \
      means that the lock has not yet been \
      granted, it is just waiting for its  \
      turn in the wait queue */
/* Precise modes */
#define LOCK_ORDINARY                     \
  0 /*!< this flag denotes an ordinary    \
    next-key lock in contrast to LOCK_GAP \
    or LOCK_REC_NOT_GAP */
#define LOCK_GAP                                     \
  512 /*!< when this bit is set, it means that the   \
      lock holds only on the gap before the record;  \
      for instance, an x-lock on the gap does not    \
      give permission to modify the record on which  \
      the bit is set; locks of this type are created \
      when records are removed from the index chain  \
      of records */
#define LOCK_REC_NOT_GAP                            \
  1024 /*!< this bit means that the lock is only on \
       the index record and does NOT block inserts  \
       to the gap before the index record; this is  \
       used in the case when we retrieve a record   \
       with a unique key, and is also used in       \
       locking plain SELECTs (not part of UPDATE    \
       or DELETE) when the user has set the READ    \
       COMMITTED isolation level */
#define LOCK_INSERT_INTENTION                                             \
  2048                       /*!< this bit is set when we place a waiting \
                          gap type record lock request in order to let    \
                          an insert of an index record to wait until      \
                          there are no conflicting locks by other         \
                          transactions on the gap; note that this flag    \
                          remains set when the waiting lock is granted,   \
                          or if the lock is inherited to a neighboring    \
                          record */
#define LOCK_PREDICATE 8192  /*!< Predicate lock */
#define LOCK_PRDT_PAGE 16384 /*!< Page lock */
```

## Lock Scheduling CATS

先分清两件事：**锁调度**决定「一把锁被释放时，队列里多个 WAITING 锁先给谁」；**死锁检测**决定「等待关系成环时回滚谁」。9.7 里它们的实现完全分开，CATS 是前者，不是死锁算法——把 CATS 说成死锁检测算法是常见误读。

CATS 的权威描述内嵌在源码注释里，位置是 `storage/innobase/include/lock0lock.h` 的 `@section sect_lock_sys_scheduling The scheduling algorithm`：

```c++
We use a variant of the algorithm described in paper "Contention-Aware Lock
Scheduling for Transactional Databases" by Boyu Tian, Jiamin Huang, Barzan
Mozafari and Grant Schoenebeck.
The algorithm, "CATS" for short, analyzes the Wait-for graph, and assigns a
weight to each WAITING transaction, equal to the number of transactions which
it (transitively) blocks. The idea being that favoring heavy transactions will
help to make more progress by helping more transactions to become eventually
runnable.
```

给每个 WAITING 事务算一个 weight = 它**传递性阻塞**的事务数，放行 weight 高的那个，因为这样一次授予能让更多的、最终可被调度的事务动起来。热点行场景（大量事务挤在同一条锁队列上）收益最大。weight 由谁算出来？正是后文 `Detection In MySQL 9.7` 一节里，每轮扫等待图时顺手发布的（`lock_wait_compute_and_publish_weights_except_cycles()`）。

### Grant Group And Wait Group

同一条锁队列在逻辑上分成两组：已授予的从 HEAD 进，等待中的从 TAIL 进。源码注释直接画了示意图：

```text
                                           |
Grows <---- [HEAD] [G7 -- G3 -- G2 -- G1] -|- [W4 -- W5 -- W6] [TAIL] ---> Grows
                         Grant Group       |         Wait Group

        G - Granted W - waiting,
        suffix number is the chronological order of requests.
```

两个分组对「顺序」的态度截然不同：

```c++
    - In the Wait Group the locks are in chronological order. We will not assert
      this invariant as there is no significance of the order (and hence the
      position) as the locks are re-ordered based on CATS weight while making a
      choice for grant, and CATS weights change constantly to reflect current
      shape of the Wait-for graph.
    - In the Grant Group the locks are in reverse chronological order. We will
      assert this invariant. CATS algorithm doesn't need it, but deadlock
      detection does, as explained further below.
```

Wait Group 顺序**没有意义**：每次决定授予时都会按 CATS weight 重排，而 weight 又随等待图形状持续变化，所以源码刻意不给它加断言。Grant Group 是**逆时间序且有 `ut_ad` 断言**——但 CATS 本身不需要它，需要它的是死锁检测，原因见 [Why Grant Group Is Reverse Chronological](/docs/CS/DB/MySQL/lock.md?id=why-grant-group-is-reverse-chronological)。

### Blocking Transaction

新锁请求进来时，与队列里**所有**锁（GRANTED 和 WAITING 都算）做冲突检查：

- 有冲突 → 新请求置为 WAITING 追加到 TAIL，并把与它冲突的那个事务记为它的 Blocking Transaction；
- 无冲突 → 直接授予，插到 HEAD。

每个事务至多只有一个 WAITING 锁，因此至多只有一个 Blocking Transaction，这份信息就直接挂在事务对象上（`trx->lock.blocking_trx`，是个 atomic 指针，读取无需持有 latch）：

```c++
The transaction which requested the conflicting lock found is said to be the
Blocking Transaction for the incoming transaction. As each transaction
can have at most one WAITING lock, it also can have at most one Blocking
Transaction, and thus we store the information about Blocking Transaction
(if any) in the transaction object itself (as opposed to: separately for
each lock request).
```

「每个事务只记一个 Blocking Transaction」是 9.7 死锁检测能做轻量的前提：等待图每人最多一条出边，扫一遍 slot 就能拼出图。

但注意第 2 步是与 GRANTED + WAITING 两者查冲突，而释放锁时的重新评估只与 GRANTED 查冲突，这里藏着一个饿死问题，源码用保留 Blocking Transaction 约束来堵住它：

```c++
Such "bypassing of waiters" is
intentionally prevented to avoid starvation of a WAITING LOCK_X, by a steady
stream of LOCK_S requests. Respecting the rule that a Blocking Transaction has
to finish before a lock can be granted implies that at least one of WAITING
LOCK_Xs will be granted before a LOCK_S can be granted.
```

即：WAITING 的 `LOCK_X` 不会被源源不断的 `LOCK_S` 绕过——必须先放行至少一个 WAITING `LOCK_X`。

唯一的例外是 Group Replication 的高优先级事务，它绕过 CATS 排序：

```c++
High Priority transactions in Wait Group are unconditionally kept ahead while
sorting the wait queue. The HP is a concept related to Group Replication, and
currently has nothing to do with CATS weight.
```

### Why Grant Group Is Reverse Chronological

授予锁时选 Blocking Transaction，新请求按队列自然序扫、取第一个冲突者；而**旧**请求（因别人释放锁而被重新评估）只扫 Grant Group，并且**从队列中部往 HEAD 方向**按时间序扫。这段注释同时回答了「为什么 Grant Group 的逆时间序值得加断言」：

```c++
For old lock requests we scan only the Grant Group, and we do so in the
chronological order, starting from the oldest lock requests [G1,G2,G3,G7] that
is from the middle of the queue towards HEAD. In particular we also check
against the locks which recently become GRANTED as they were processed before us
in the sorting order, and we do so in a chronological order as well.

@remark
The idea here is that if we chose G1 as the Blocking Transaction and if there
existed a dead lock with another conflicting transaction G3, the deadlock
detection would not be postponed indefinitely while new GRANTED locks are
added as they are going to be added to HEAD only.
In other words: each of the conflicting locks in the Grant Group will eventually
be set as the Blocking Transaction at some point in time, and thus it will
become visible for the deadlock detection.
If, by contrast, we were always picking the first one in the natural order, it
might happen that we never get to assign G3 as the Blocking Transaction
because new conflicting locks appear in front of the queue (and are released).
That might lead to the deadlock with G3 never being noticed.
```

因果链是：新授予的锁只会从 HEAD 进，如果永远只取自然序第一个冲突者，G3 可能一直排不到被设为 Blocking Transaction，与 G3 的死锁就永远不出现在等待图上。逆时间序扫描保证**每个冲突锁最终都会被设为 Blocking Transaction**，于是死锁不会被无限推迟。


## Deadlock

两个事务分别持有对方需要的锁，并等待对方释放锁（事务1持有a锁、请求b锁，事务2持有b锁、请求a锁），导致程序无法继续进行

MySQL自动监测死锁并回滚其中一个事务：

- MySQL默认开启死锁检测（innodb_deadlock_detect默认为on），发现死锁后主动回滚死锁链条中的某一个事务，让其他事务得以继续执行
- 如果死锁监测被关闭，InnoDB依赖innodb_lock_wait_timeout 进行事务回滚以避免死锁，请求锁的默认最长等待时间是50s
- 如果要查看InnoDB用户事务中的最后一个死锁，可以使用 SHOW ENGINE INNODB STATUS
- 如果频繁的出现死锁，可以启用innodb_print_all_deadlocks将所有死锁的有关信息打印到mysqld错误日志中

数据库死锁常见原因：
多个事务通过uptade或者select..for share / update锁定了多个表中的行记录，但锁定的顺序相反



ERROR 40001: Deadlock found when trying to get lock; try restarting transaction

show engine innodb status查看到最近的一次死锁日志



MySQL官方提供了InnoDB引擎下，事务死锁的主动检测与丢弃机制，官方允许通过innodb_deadlock_detect这个参数进行控制，默认开启。
同时如果禁用此选项，依旧可以通过锁超时参数innodb_lock_wait_timeout来进行控制
innodb死锁检测只能针对innodb引擎级别死锁，innodb死锁检测不能检测到应用层级别死锁


### Deadlock Detection Status In 9.7

先给结论，避免把新旧两版混为一谈：

- `innodb_deadlock_detect` 在 9.7 **仍然存在，默认 ON**——变量 `bool innobase_deadlock_detect = true;` 定义在 `storage/innobase/lock/lock0lock.cc`，sysvar 注册在 `storage/innobase/handler/ha_innodb.cc`。关掉它则完全依赖 `innodb_lock_wait_timeout`。
- 但**检测的实现早已不是「每次上锁前持大锁对整个等待图做 DFS」**。9.7 把两件事彻底分开：锁调度是 CATS（见上一节），死锁检测改到 `storage/innobase/lock/lock0wait.cc`，由一个后台线程周期性对等待 slot 取快照、拼等待图、找环、验环、选牺牲者。
- 类名层面：**`DeadlockChecker` 在 9.7 全树 grep 无命中，已经不存在**；负责对外通报死锁的是 `class Deadlock_notifier`（`lock/lock0lock.cc`），入口函数 `lock_notify_about_deadlock(trxs_on_cycle, victim_trx)`。

### Old DFS Based Detector

> [!WARNING]
> 以下只描述 8.0.18 以前的行为。旧资料里「详细代码可参考 MySQL 8.0 DeadlockChecker 类中相关实现」这条指引已经失效——该类在 9.7 源码树里不存在。

在 8.0.18 以前（旧版本），InnoDB 的死锁检测机制是最常见的深度优先搜索（DFS）算法来搜索等待关系图。
如果开启了死锁检测，那么在每次上锁之前，都会进行一次死锁检测，我们会持有 lock_sys->mutex，然后对整个等待关系图进行 DFS 遍历，当发现等待关系图成环的时候，说明有死锁存在，我们根据 undo 大小与持锁数量（即 `TRX_WEIGHT`）等因素选择一个事务进行回滚。

老的死锁检测机制主要存在的问题是性能问题。在 DFS 搜索等待关系图的时候，是会持有 lock_sys->mutex 这把大锁的，在 lock_sys->mutex 持有期间所有的新加行锁和释放全部会被阻塞。当出现大量锁等待的时候（例如电商热点行场景等），等待关系图会变的特别的大，导致每一次加锁 DFS 遍历整个等待关系图的时间变得非常的长，从而导致 lock_sys->mutex 竞争过于剧烈，引发大量线程等待 lock_sys->mutex，从而导致数据库在此场景下雪崩。

### The innodb_deadlock_detect Sysvar

下面三段在 9.7 原样保留（文件已改名 `lock/lock0lock.cc`、`handler/ha_innodb.cc`），语义未变：

```c++
static MYSQL_SYSVAR_BOOL(
    deadlock_detect, innobase_deadlock_detect, PLUGIN_VAR_NOCMDARG,
    "Enable/disable InnoDB deadlock detector (default ON)."
    " if set to OFF, deadlock detection is skipped,"
    " and we rely on innodb_lock_wait_timeout in case of deadlock.",
    nullptr, innobase_deadlock_detect_update, true);
```


```c++
static void innobase_deadlock_detect_update(THD *, SYS_VAR *, void *,
                                            const void *save) {
  innobase_deadlock_detect = *(bool *)save;
  /* In case deadlock detection was disabled for a long time it could happen
  that all clients have deadlocked with each other and thus they stopped
  changing the wait-for graph, which in turn causes deadlock detection to not
  observe any action and thus it will not search for deadlocks. So if we now
  change from OFF to ON we need to "kick-start" the process. It never hurts to
  do so, so we do it even if we check from ON to OFF */
  lock_wait_request_check_for_cycles();
}
```


```c++
// lock0wait.cc
void lock_wait_request_check_for_cycles() { lock_set_timeout_event(); }

// lock0lock.cc
void lock_set_timeout_event() { os_event_set(lock_sys->timeout_event); }
```

### Detection In MySQL 9.7

上面那段 `innobase_deadlock_detect_update()` 里调用的 `lock_wait_request_check_for_cycles()` 就是新机制的入口之一：开关每改一次，就把 `lock_sys->timeout_event` 踢一下，让后台线程 `lock_wait_timeout_thread()` 立刻重扫等待图。也就是说，**检测已经从「加锁路径里同步做」搬到了这个后台线程**，加锁线程只负责排队并记下自己的 Blocking Transaction：

RecLock::add_to_waitq -> RecLock::create ->  RecLock::lock_alloc ->  RecLock::lock_add

新的死锁检测机制变的比较轻量：
1. 在持有 lock_sys->wait_mutex 的情况下，构造稀疏等待关系图，lock_wait_snapshot_waiting_threads
   a. 其实 lock_sys->wait_mutex 也不需要全程持有，只需要分段持有即可，其正确性我们在下文 `Validate Candidate Cycle` 讨论
2. 对稀疏等待关系图进行 DFS 扫描，得到成环的子图，lock_wait_find_and_handle_deadlocks
3. 对成环的子图进行有效性检测，lock_wait_check_candidate_cycle
   a. 确保其版本号是一致的
   b. 确保其还在继续等待
4. 选择牺牲事务，并进行死锁处理（回滚）
   a. lock_wait_choose_victim / lock_wait_handle_deadlock

同一轮里还会顺手算并发布 CATS 的调度权重：`lock_wait_compute_and_publish_weights_except_cycles()`。所以「等待图的遍历」一次同时喂给了两个消费者——死锁检测与锁调度，这正是 CATS 与 slot 快照机制被放在同一个后台循环里的原因。

```c++
static uint64_t lock_wait_snapshot_waiting_threads(
    ut::vector<waiting_trx_info_t> &infos) {
  ut_ad(!lock_wait_mutex_own());
  infos.clear();
  lock_wait_mutex_enter();
  /*
  We own lock_wait_mutex, which protects lock_wait_table_reservations and
  reservation_no.
  We want to make a snapshot of the wait-for graph as quick as possible to not
  keep the lock_wait_mutex too long.
  Anything more fancy than push_back seems to impact performance.

  Note: one should be able to prove that we don't really need a "consistent"
  snapshot - the algorithm should still work if we split the loop into several
  smaller "chunks" snapshotted independently and stitch them together. Care must
  be taken to "merge" duplicates keeping the freshest version (reservation_no)
  of slot for each trx.
  So, if (in future) this loop turns out to be a bottleneck (say, by increasing
  congestion on lock_wait_mutex), one can try to release and require the lock
  every X iterations and modify the lock_wait_build_wait_for_graph() to handle
  duplicates in a smart way.
  */
  const auto table_reservations = lock_wait_table_reservations;
  for (auto slot = lock_sys->waiting_threads; slot < lock_sys->last_slot;
       ++slot) {
    if (slot->in_use) {
      auto from = thr_get_trx(slot->thr);
      auto to = from->lock.blocking_trx.load();
      if (to != nullptr) {
        infos.push_back({from, to, slot, slot->reservation_no});
      }
    }
  }
  lock_wait_mutex_exit();
  return table_reservations;
}
```

这段注释里最值钱的一句是「其实不需要一致性快照」：只要合并重复项时保留 `reservation_no` 最新的那个 slot，把整段循环拆成若干小块、每块独立取快照再拼接，算法依然成立。也就是说 `lock_wait_mutex` 未来还能进一步分段持有，现在没做只是因为实测没成为瓶颈。

快照元素是 `{trx, waits_for, slot, reservation_no}`：`waits_for` 直接原子读 `trx->lock.blocking_trx`，**不需要持有 global latch**——这正是 CATS 把 Blocking Transaction 存在事务对象上（每个事务至多一个）换来的收益。`slot` 与 `reservation_no` 则是下文验环时判断「这个指针还算不算数」的凭据。

### Find Cycles

Assuming that `infos` contains information about all waiting transactions, and `outgoing[i]` is the endpoint of wait-for edge going out of infos[i].trx,
or -1 if the transaction is not waiting, it identifies and handles all cycles in the wait-for graph

```c++
static void lock_wait_find_and_handle_deadlocks(
    const ut::vector<waiting_trx_info_t> &infos,
    const ut::vector<int> &outgoing,
    ut::vector<trx_schedule_weight_t> &new_weights) {
  ut_ad(infos.size() == new_weights.size());
  ut_ad(infos.size() == outgoing.size());
  /** We are going to use int and uint to store positions within infos */
  ut_ad(infos.size() < std::numeric_limits<uint>::max());
  const auto n = static_cast<uint>(infos.size());
  ut_ad(n < static_cast<uint>(std::numeric_limits<int>::max()));
  ut::vector<uint> cycle_ids;
  cycle_ids.clear();
  ut::vector<uint> colors;
  colors.clear();
  colors.resize(n, 0);
  uint current_color = 0;
  for (uint start = 0; start < n; ++start) {
    if (colors[start] != 0) {
      /* This node was already fully processed*/
      continue;
    }
    ++current_color;
    for (int id = start; 0 <= id; id = outgoing[id]) {
      /* We don't expect transaction to deadlock with itself only
      and we do not handle cycles of length=1 correctly */
      ut_ad(id != outgoing[id]);
      if (colors[id] == 0) {
        /* This node was never visited yet */
        colors[id] = current_color;
        continue;
      }
      /* This node was already visited:
      - either it has current_color which means we've visited it during current
        DFS descend, which means we have found a cycle, which we need to verify,
      - or, it has a color used in a previous DFS which means that current DFS
        path merges into an already processed portion of wait-for graph, so we
        can stop now */
      if (colors[id] == current_color) {
        /* found a candidate cycle! */
        lock_wait_extract_cycle_ids(cycle_ids, id, outgoing);
        if (lock_wait_check_candidate_cycle(cycle_ids, infos, new_weights)) {
          MONITOR_INC(MONITOR_DEADLOCK);
        } else {
          MONITOR_INC(MONITOR_DEADLOCK_FALSE_POSITIVES);
        }
      }
      break;
    }
  }
  MONITOR_INC(MONITOR_DEADLOCK_ROUNDS);
  MONITOR_SET(MONITOR_LOCK_THREADS_WAITING, n);
}
```

### Validate Candidate Cycle

Given an array with information about all waiting transactions and indexes in it which form a deadlock cycle,
checks if the transactions allegedly forming the deadlock cycle, indeed are still waiting, and if so, chooses a victim and handles the deadlock.


```c++
static bool lock_wait_check_candidate_cycle(
    ut::vector<uint> &cycle_ids, const ut::vector<waiting_trx_info_t> &infos,
    ut::vector<trx_schedule_weight_t> &new_weights) {
  ut_ad(!lock_wait_mutex_own());
  ut_ad(!locksys::owns_exclusive_global_latch());
  lock_wait_mutex_enter();
  /*
  We have released all mutexes after we have built the `infos` snapshot and
  before we've got here. So, while it is true that the edges form a cycle, it
  may also be true that some of these transactions were already rolled back, and
  memory pointed by infos[i].trx or infos[i].waits_for is no longer the trx it
  used to be (as we reuse trx_t objects). It may even segfault if we try to
  access it (because trx_t object could be freed). So we need to somehow verify
  that the pointer is still valid without accessing it. We do that by checking
  if slot->reservation_no has changed since taking a snapshot.
  If it has not changed, then we know that the trx's pointer still points to the
  same trx as the trx is sleeping, and thus has not finished and wasn't freed.
  So, we start by first checking that the slots still contain the trxs we are
  interested in. This requires lock_wait_mutex, but does not require the
  exclusive global latch. */
  if (!lock_wait_trxs_are_still_in_slots(cycle_ids, infos)) {
    lock_wait_mutex_exit();
    return false;
  }
  /*
  At this point we are sure that we can access memory pointed by infos[i].trx
  and that transactions are still in their slots. (And, as `cycle_ids` is a
  cycle, we also know that infos[cycle_ids[i]].wait_for is equal to
  infos[cycle_ids[i+1]].trx, so infos[cycle_ids[i]].wait_for can also be safely
  accessed).
  This however does not mean necessarily that they are still waiting.
  They might have been already notified that they should wake up (by calling
  lock_wait_release_thread_if_suspended()), but they had not yet chance to act
  upon it (it is the trx being woken up who is responsible for cleaning up the
  `slot` it used).
  So, the slot can be still in use and contain a transaction, which was already
  decided to be rolled back for example. However, we can recognize this
  situation by looking at trx->lock.wait_lock, as each call to
  lock_wait_release_thread_if_suspended() is performed only after
  lock_reset_lock_and_trx_wait() resets trx->lock.wait_lock to NULL.
  Checking trx->lock.wait_lock in reliable way requires global exclusive latch.
  */
  locksys::Global_exclusive_latch_guard gurad{UT_LOCATION_HERE};
  if (!lock_wait_trxs_are_still_waiting(cycle_ids, infos)) {
    lock_wait_mutex_exit();
    return false;
  }

  /*
  We can now release lock_wait_mutex, because:

  1. we have verified that trx->lock.wait_lock is not NULL for cycle_ids
  2. we hold exclusive global lock_sys latch
  3. lock_sys latch is required to change trx->lock.wait_lock to NULL
  4. only after changing trx->lock.wait_lock to NULL a trx can finish

  So as long as we hold exclusive global lock_sys latch we can access trxs.
  */

  lock_wait_mutex_exit();

  trx_t *const chosen_victim = lock_wait_choose_victim(cycle_ids, infos);
  ut_a(chosen_victim);

  lock_wait_handle_deadlock(chosen_victim, cycle_ids, infos, new_weights);

  return true;
}
```

验环这一步是整套「不用大锁」机制的正确性支点：取完快照到此刻之间所有 latch 都已放开，环上的 `trx_t*` 可能已经被回收复用（`trx_t` 对象是池化重用的），直接解引用甚至可能 segfault。`lock_wait_trxs_are_still_in_slots()` 的招法是**不解引用指针**，只比对 slot 里的 `reservation_no` 有没有变。`reservation_no` 是 slot 的预约序号，只要事务还睡在当初那个 slot 里它就不会变，于是「指针仍指向当初那个事务」就在只持有 `lock_wait_mutex` 的前提下成立了——这是典型的 ABA 防护。

确认 slot 仍然有效之后，还得再拿一次 exclusive global latch 检查 `trx->lock.wait_lock` 非空，才能断定它们「仍在等待」，而不是已经被通知醒来去走回滚清理流程（`lock_wait_release_thread_if_suspended()` 一定先把 `trx->lock.wait_lock` 置空）。

### Victim Selection

排好起点后两两比较：

1. `lock_wait_order_for_choosing_victim()` 把环上的事务排序，取 `reservation_no` 最大者为起点；
2. 若比较的双方有一方是 high priority 事务（Group Replication 概念），走 `trx_arbitrate()`；
3. 否则比 `trx_weight_ge()`，谁「小」谁当牺牲者。

事务权重的定义在 `include/trx0trx.h`，是「改动行数 + 持锁数量」：

```c++
/** Calculates the "weight" of a transaction. The weight of one transaction
 is estimated as the number of altered rows + the number of locked rows.
 @param t transaction
 @return transaction weight */
static inline uint64_t TRX_WEIGHT(const trx_t *t) {
  return t->undo_no + UT_LIST_GET_LEN(t->lock.trx_locks);
}
```

比较函数还多了一条**前置判据**，定义在 `trx/trx0trx.cc`：

```c++
/** Compares the "weight" (or size) of two transactions. Transactions that
 have edited non-transactional tables are considered heavier than ones
 that have not.
 @return true if weight(a) >= weight(b) */
bool trx_weight_ge(const trx_t *a, /*!< in: transaction to be compared */
                   const trx_t *b) /*!< in: transaction to be compared */
{
  /* To read TRX_WEIGHT we need a exclusive global lock_sys latch */
  ut_ad(locksys::owns_exclusive_global_latch());

  /* If mysql_thd is NULL for a transaction we assume that it has
  not edited non-transactional tables. */

  auto a_notrans_edit =
      a->mysql_thd != nullptr && thd_has_edited_nontrans_tables(a->mysql_thd);

  auto b_notrans_edit =
      b->mysql_thd != nullptr && thd_has_edited_nontrans_tables(b->mysql_thd);

  if (a_notrans_edit != b_notrans_edit) {
    return (a_notrans_edit);
  }

  /* Either both had edited non-transactional tables or both had
  not, we fall back to comparing the number of altered/locked
  rows. */

  return (TRX_WEIGHT(a) >= TRX_WEIGHT(b));
}
```

先比**谁编辑过非事务表**（`thd_has_edited_nontrans_tables`），这一项不同就直接判定编辑过的一方更重；只有双方相同，才落到 `TRX_WEIGHT` 的比较。旧资料里「根据事务优先级 / undo 大小 / 锁数量等因素选择牺牲者」这句话方向对但不精确：9.7 的 `trx_weight_ge` 里没有「事务优先级」这一项，high priority 是 `trx_arbitrate()` 的独立分支；weight 的准确定义是 `undo_no + trx_locks 长度`；而且漏掉了非事务表这条优先级更高的判据。

```c++
static trx_t *lock_wait_choose_victim(
    const ut::vector<uint> &cycle_ids,
    const ut::vector<waiting_trx_info_t> &infos) {
  /* We are iterating over various transactions comparing their trx_weight_ge,
  which is computed based on number of locks held thus we need exclusive latch
  on the whole lock_sys. In theory number of locks should not change while the
  transaction is waiting, but instead of proving that they can not wake up, it
  is easier to assert that we hold the mutex */
  ut_ad(locksys::owns_exclusive_global_latch());
  ut_ad(!cycle_ids.empty());
  trx_t *chosen_victim = nullptr;
  auto sorted_trxs = lock_wait_order_for_choosing_victim(cycle_ids, infos);

  for (auto *trx : sorted_trxs) {
    if (chosen_victim == nullptr) {
      chosen_victim = trx;
      continue;
    }

    if (trx_is_high_priority(chosen_victim) || trx_is_high_priority(trx)) {
      auto victim = trx_arbitrate(trx, chosen_victim);

      if (victim != nullptr) {
        if (victim == trx) {
          chosen_victim = trx;
        } else {
          ut_a(victim == chosen_victim);
        }
        continue;
      }
    }

    if (trx_weight_ge(chosen_victim, trx)) {
      /* The joining transaction is 'smaller',
      choose it as the victim and roll it back. */
      chosen_victim = trx;
    }
  }

  ut_a(chosen_victim);
  return chosen_victim;
}
```

### Notify And Rollback

Handles a deadlock found, by notifying about it, rolling back the chosen victim and updating schedule weights of transactions on the deadlock cycle.


```c++
static void lock_wait_handle_deadlock(
    trx_t *chosen_victim, const ut::vector<uint> &cycle_ids,
    const ut::vector<waiting_trx_info_t> &infos,
    ut::vector<trx_schedule_weight_t> &new_weights) {
  /*  We now update the `schedule_weight`s on the cycle taking into account that
  chosen_victim will be rolled back.
  This is mostly for "correctness" as the impact on performance is negligible
  (actually it looks like it is slowing us down). */
  lock_wait_update_weights_on_cycle(chosen_victim, cycle_ids, infos,
                                    new_weights);

  lock_notify_about_deadlock(
      lock_wait_trxs_rotated_for_notification(cycle_ids, infos), chosen_victim);

  lock_wait_rollback_deadlock_victim(chosen_victim);
}
```

三个动作的顺序值得留意：先更新环上的 schedule weight，再通报，最后回滚牺牲者。通报由 `class Deadlock_notifier`（定义在 `storage/innobase/lock/lock0lock.cc`）负责，对外入口是 `lock_notify_about_deadlock(trxs_on_cycle, victim_trx)`；传入的环先经 `lock_wait_trxs_rotated_for_notification()` 重排顺序，这一步只为让通报内容可读，不参与牺牲者选择（victim 在上一步已经定下）。默认它只把最近一次死锁留给 `SHOW ENGINE INNODB STATUS`，要全部落 error log 得开 `innodb_print_all_deadlocks`。


```c++
void lock_wait_timeout_thread() {
  int64_t sig_count = 0;
  os_event_t event = lock_sys->timeout_event;

  ut_ad(!srv_read_only_mode);

  /** The last time we've checked for timeouts. */
  auto last_checked_for_timeouts_at = std::chrono::steady_clock::now();
  do {
    auto current_time = std::chrono::steady_clock::now(); /* Calling this more
    often than once a second isn't needed, as lock timeouts are specified with
    one second resolution, so probably nobody cares if we wake up after T or
    T+0.99, when T itself can't be precise. */
    if (std::chrono::seconds(1) <=
        current_time - last_checked_for_timeouts_at) {
      last_checked_for_timeouts_at = current_time;
      lock_wait_check_slots_for_timeouts();
    }

    lock_wait_update_schedule_and_check_for_deadlocks();

    /* When someone is waiting for a lock, we wake up every second (at worst)
    and check if a timeout has passed for a lock wait */
    os_event_wait_time_low(event, std::chrono::seconds{1}, sig_count);
    sig_count = os_event_reset(event);

  } while (srv_shutdown_state.load() < SRV_SHUTDOWN_CLEANUP);
}
```
Note: I was tempted to declare `infos` as `static`, or at least declare it in lock_wait_timeout_thread() 
and reuse the same instance over and over again to avoid allocator calls caused by push_back() calls inside lock_wait_snapshot_waiting_threads() while we hold lock_sys->lock_wait_mutex.
I was afraid, that allocator might need to block on some internal mutex in order to synchronize with other threads using allocator, and this could in turn cause contention on lock_wait_mutex. 
I hoped, that since vectors never shrink, and only grow, then keeping a single instance of `infos` alive for the whole lifetime of the thread should increase performance,
because after some initial period of growing, the allocations will never have to occur again.
But, I've run many many various experiments, with/without static, with infos declared outside, with reserve(n) using various values of n (128, srv_max_n_threads, even a simple ML predictor), and nothing, 
NOTHING was faster than just using local vector as we do here (at least on tetra01, tetra02, when comparing ~70 runs of each algorithm on uniform, pareto, 128 and 1024 usrs).



```c++
static void lock_wait_update_schedule_and_check_for_deadlocks() {
  ut::vector<waiting_trx_info_t> infos;
  ut::vector<int> outgoing;
  ut::vector<trx_schedule_weight_t> new_weights;

  auto table_reservations = lock_wait_snapshot_waiting_threads(infos);
  lock_wait_build_wait_for_graph(infos, outgoing);

  /* We don't update trx->lock.schedule_weight for trxs on cycles. */
  lock_wait_compute_and_publish_weights_except_cycles(infos, table_reservations,
                                                      outgoing, new_weights);

  if (innobase_deadlock_detect) {
    /* This will also update trx->lock.schedule_weight for trxs on cycles. */
    lock_wait_find_and_handle_deadlocks(infos, outgoing, new_weights);
  }
}
```


如何减少死锁：
- 当不同的事务同时访问数据资源时，尽量采用相同的操作顺序
- 如果能确定幻读和不可重复读对应用的影响不大，可以考虑将隔离级别从默认的RR改成 RC，可以避免 Gap 锁导致的死锁；
  - 为表添加合理的索引，如果不走索引，将会为表的每一行记录加锁，死锁的概率就会大大增大；
  - 避免大事务，尽量将大事务拆成多个小事务来处理；因为大事务占用资源多，耗时长，与其他事务冲突的概率也会变高；





A deadlock is a situation where different transactions are unable to proceed because each holds a lock that the other needs.
Because both transactions are waiting for a resource to become available, neither ever release the locks it holds.

## Minimizing and Handling Deadlocks

You can cope with deadlocks and reduce the likelihood of their occurrence with the following techniques:

- At any time, issue `SHOW ENGINE INNODB STATUS` to determine the cause of the most recent deadlock. That can help you to tune your application to avoid deadlocks.
- `SHOW FULL PROCESSLIST`
- table `INNODB_TRX`, `INNODB_LOCKS`, `INNODB_LOCK_WAITS` in information_schema
- If frequent deadlock warnings cause concern, collect more extensive debugging information by enabling the `innodb_print_all_deadlocks` variable.
  Information about each deadlock, not just the latest one, is recorded in the MySQL [error log](/docs/CS/DB/MySQL/serverlog.md).
  Disable this option when you are finished debugging.
- Always be prepared to re-issue a transaction if it fails due to deadlock. Deadlocks are not dangerous. Just try again.
- Keep transactions small and short in duration to make them less prone to collision.
- Commit transactions immediately after making a set of related changes to make them less prone to collision. In particular, do not leave an interactive **mysql** session open for a long time with an uncommitted transaction.
- If you use *locking reads* (`SELECT ... FOR UPDATE` or `SELECT ... FOR SHARE`), try using a lower isolation level such as `READ COMMITTED`.
- When modifying multiple tables within a transaction, or different sets of rows in the same table, do those operations in a consistent order each time.
  Then transactions form well-defined queues and do not deadlock.
  For example, organize database operations into functions within your application, or call stored routines, rather than coding multiple similar sequences of `INSERT`, `UPDATE`, and `DELETE` statements in different places.
- Add well-chosen indexes to your tables so that your queries scan fewer index records and set fewer locks. Use `EXPLAIN SELECT` to determine which indexes the MySQL server regards as the most appropriate for your queries.
- Use less locking. If you can afford to permit a `SELECT` to return data from an old snapshot, do not add a `FOR UPDATE` or `FOR SHARE` clause to it.
  Using the `READ COMMITTED` isolation level is good here, because each consistent read within the same transaction reads from its own fresh snapshot.
- If nothing else helps, serialize your transactions with table-level locks. The correct way to use `LOCK TABLES` with transactional tables,
  such as `InnoDB` tables, is to begin a transaction with `SET autocommit = 0` (not `START TRANSACTION`) followed by `LOCK TABLES`,
  and to not call `UNLOCK TABLES` until you commit the transaction explicitly. For example, if you need to write to table `t1` and read from table `t2`, you can do this:

  Table-level locks prevent concurrent updates to the table, avoiding deadlocks at the expense of less responsiveness for a busy system.
- Another way to serialize transactions is to create an auxiliary “semaphore” table that contains just a single row.
  Have each transaction update that row before accessing other tables. In that way, all transactions happen in a serial fashion.
  Note that the `InnoDB` instant deadlock detection algorithm also works in this case, because the serializing lock is a row-level lock.
  With MySQL table-level locks, the timeout method must be used to resolve deadlocks.

#### Diagnosing Deadlocks

`SHOW ENGINE INNODB STATUS` 的 `LATEST DETECTED DEADLOCK` 段给出最近一次死锁的两个事务、各自持有与等待的锁、
以及被选为 victim 的事务。要看**全部**死锁（而不只是最后一次），打开 `innodb_print_all_deadlocks`，
输出会进 error log；`data_locks` / `data_lock_waits` 是 8.0 起取代旧 `INNODB_LOCKS` /
`INNODB_LOCK_WAITS` 的 performance_schema 表。死锁本身不危险，**应用侧必须准备重试**。


## Links

- [B-Tree](/docs/CS/DB/MySQL/B-Tree.md)
- [Transaction](/docs/CS/DB/MySQL/Transaction.md)
- [InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md)
- [Undo Log](/docs/CS/DB/MySQL/undolog.md)




## References

1. [MySQL 死锁检测源码分析](https://leviathan.vip/2020/02/02/mysql-deadlock-check/)
2. [Contention-Aware Lock Scheduling for Transactional Databases](https://dl.acm.org/doi/10.1145/3341301.3359648)
3. [MySQL 源码分析 - MySQL deadlock cause by lock inherit](http://mysql.taobao.org/monthly/2024-03-02/)
4. [mysql-deadlocks - deadlock examples](https://github.com/aneasystone/mysql-deadlocks)
