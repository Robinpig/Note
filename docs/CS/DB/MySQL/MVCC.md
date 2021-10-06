## Inroduction

In Concurrency Control theory, there are two ways you can deal with conflicts:

- You can avoid them, by employing a pessimistic locking mechanism (e.g. Read/Write locks, Two-Phase Locking)
- You can allow conflicts to occur, but you need to detect them using an optimistic locking mechanism (e.g. logical clock, MVCC)

Because MVCC (Multi-Version Concurrency Control) is such a prevalent Concurrency Control technique (not only in relational database systems, in this article, I’m going to explain how it works.



When the [ACID transaction properties](/docs/CS/Transaction.md?id=ACID) were first defined, Serializability was assumed. And to provide a Strict Serializable transaction outcome, the [2PL (Two-Phase Locking)](https://vladmihalcea.com/2pl-two-phase-locking/) mechanism was employed. When using 2PL, every read requires a shared lock acquisition, while a write operation requires taking an exclusive lock.

- a shared lock blocks Writers, but it allows other Readers to acquire the same shared lock
- an exclusive lock blocks both Readers and Writers concurring for the same lock

However, locking incurs contention, and contention affects scalability. The [Amdhal’s Law](https://en.wikipedia.org/wiki/Amdahl's_law) or the [Universal Scalability Law](http://www.perfdynamics.com/Manifesto/USLscalability.html) demonstrate how contention can affect response Time speedup.

For this reason, database researchers have come up with a different Concurrency Control model which tries to reduce locking to a bare minimum so that:

- Readers don’t block Writers
- Writers don’t block Readers

The only use case that can still generate contention is when two concurrent transactions try to modify the same record since, once modified, a row is always locked until the transaction that modified this record either commits or rolls back.

In order to specify the aforementioned Reader/Writer non-locking behavior, the Concurrency Control mechanism must operate on multiple versions of the same record, hence this mechanism is called Multi-Version Concurrency Control (MVCC).

While 2PL is pretty much standard, there’s no standard MVCC implementation, each database taking a slightly different approach. In this article, we are going to use PostgreSQL since its MVCC implementation is the easiest one to visualize.





While Oracle and MySQL use the [undo log](https://vladmihalcea.com/how-does-a-relational-database-work/) to capture uncommitted changes so that rows can be reconstructed to their previously committed version, PostgreSQL stores all row versions in the table data structure.

## InnoDB MVCC

`InnoDB` is a multi-version storage engine. It keeps information about old versions of changed rows to support transactional features such as concurrency and rollback. **This information is stored in undo tablespaces in a data structure called a rollback segment.** See [Section 15.6.3.4, “Undo Tablespaces”](https://dev.mysql.com/doc/refman/8.0/en/innodb-undo-tablespaces.html). `InnoDB` uses the information in the rollback segment to perform the undo operations needed in a transaction rollback. It also uses the information to build earlier versions of a row for a consistent read. See [Section 15.7.2.3, “Consistent Nonlocking Reads”](https://dev.mysql.com/doc/refman/8.0/en/innodb-consistent-read.html).

Internally, `InnoDB` adds three fields to each row stored in the database:

- A 6-byte `DB_TRX_ID` field indicates the transaction identifier for the last transaction that inserted or updated the row. Also, a deletion is treated internally as an update where a special bit in the row is set to mark it as deleted.
- A 7-byte `DB_ROLL_PTR` field called the roll pointer. The roll pointer points to an undo log record written to the rollback segment. If the row was updated, the undo log record contains the information necessary to rebuild the content of the row before it was updated.
- A 6-byte `DB_ROW_ID` field contains a row ID that increases monotonically as new rows are inserted. If `InnoDB` generates a clustered index automatically, the index contains row ID values. Otherwise, the `DB_ROW_ID` column does not appear in any index.

Undo logs in the rollback segment are divided into insert and update undo logs. Insert undo logs are needed only in transaction rollback and can be discarded as soon as the transaction commits. Update undo logs are used also in consistent reads, but they can be discarded only after there is no transaction present for which `InnoDB` has assigned a snapshot that in a consistent read could require the information in the update undo log to build an earlier version of a database row. For additional information about undo logs, see [Section 15.6.6, “Undo Logs”](https://dev.mysql.com/doc/refman/8.0/en/innodb-undo-logs.html).

It is recommend that you commit transactions regularly, including transactions that issue only consistent reads. Otherwise, `InnoDB` cannot discard data from the update undo logs, and the rollback segment may grow too big, filling up the undo tablespace in which it resides. For information about managing undo tablespaces, see [Section 15.6.3.4, “Undo Tablespaces”](https://dev.mysql.com/doc/refman/8.0/en/innodb-undo-tablespaces.html).

The physical size of an undo log record in the rollback segment is typically smaller than the corresponding inserted or updated row. You can use this information to calculate the space needed for your rollback segment.

In the `InnoDB` multi-versioning scheme, a row is not physically removed from the database immediately when you delete it with an SQL statement. `InnoDB` only physically removes the corresponding row and its index records when it discards the update undo log record written for the deletion. This removal operation is called a purge, and it is quite fast, usually taking the same order of time as the SQL statement that did the deletion.

If you insert and delete rows in smallish batches at about the same rate in the table, the purge thread can start to lag behind and the table can grow bigger and bigger because of all the “dead” rows, making everything disk-bound and very slow. In such cases, throttle new row operations, and allocate more resources to the purge thread by tuning the [`innodb_max_purge_lag`](https://dev.mysql.com/doc/refman/8.0/en/innodb-parameters.html#sysvar_innodb_max_purge_lag) system variable. For more information, see [Section 15.8.9, “Purge Configuration”](https://dev.mysql.com/doc/refman/8.0/en/innodb-purge-configuration.html).

### Multi-Versioning and Secondary Indexes

`InnoDB` multiversion concurrency control (MVCC) treats secondary indexes differently than clustered indexes. Records in a clustered index are updated in-place, and their hidden system columns point undo log entries from which earlier versions of records can be reconstructed. Unlike clustered index records, secondary index records do not contain hidden system columns nor are they updated in-place.

When a secondary index column is updated, old secondary index records are delete-marked, new records are inserted, and delete-marked records are eventually purged. When a secondary index record is delete-marked or the secondary index page is updated by a newer transaction, `InnoDB` looks up the database record in the clustered index. In the clustered index, the record's `DB_TRX_ID` is checked, and the correct version of the record is retrieved from the undo log if the record was modified after the reading transaction was initiated.

If a secondary index record is marked for deletion or the secondary index page is updated by a newer transaction, the [covering index](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_covering_index) technique is not used. Instead of returning values from the index structure, `InnoDB` looks up the record in the clustered index.

However, if the [index condition pushdown (ICP)](https://dev.mysql.com/doc/refman/8.0/en/index-condition-pushdown-optimization.html) optimization is enabled, and parts of the `WHERE` condition can be evaluated using only fields from the index, the MySQL server still pushes this part of the `WHERE` condition down to the storage engine where it is evaluated using the index. If no matching records are found, the clustered index lookup is avoided. If matching records are found, even among delete-marked records, `InnoDB` looks up the record in the clustered index.



### **MVCC 可以解决什么问题？**

- 读写之间阻塞的问题，通过 MVCC 可以让读写互相不阻塞
- 降低了死锁的概率，这个是因为 MVCC 采用了乐观锁的方式，读取数据时，不需要加锁，写操作，只需要锁定必要的行。
- 解决了一致性读的问题，当我们朝向某个数据库在时间点的快照是，只能看到这个时间点之前事务提交更新的结果，不能看到时间点之后事务提交的更新结果。



<高性能MySQL>中对MVCC的部分介绍

- MySQL的大多数事务型存储引擎实现的其实都不是简单的行级锁。**基于提升并发性能的考虑**, 它们一般都同时实现了多版本并发控制(MVCC)。不仅是MySQL, 包括Oracle,PostgreSQL等其他数据库系统也都实现了MVCC, 但各自的实现机制不尽相同, 因为MVCC没有一个统一的实现标准。
- 可以认为MVCC是行级锁的一个变种, 但是它在很多情况下避免了加锁操作, 因此开销更低。虽然实现机制有所不同, 但大都实现了非阻塞的读操作，写操作也只锁定必要的行。
- MVCC的实现方式有多种, 典型的有乐观(optimistic)并发控制 和 悲观(pessimistic)并发控制。
- MVCC只在 `READ COMMITTED` 和 `REPEATABLE READ` 两个隔离级别下工作。其他两个隔离级别够和MVCC不兼容, 因为 `READ UNCOMMITTED` 总是读取最新的数据行, 而不是符合当前事务版本的数据行。而 `SERIALIZABLE` 则会对所有读取的行都加锁。





事务快照是用来存储数据库的事务运行情况。一个事务快照的创建过程可以概括为：
查看当前所有的未提交并活跃的事务，存储在数组中
选取未提交并活跃的事务中最小的XID，记录在快照的xmin中
**选取所有已提交事务中最大的XID，加1后记录在xmax中**









另外, 对于read view快照的生成时机, 也非常关键, **正是因为生成时机的不同, 造成了RC,RR两种隔离级别的不同可见性**;

- With **REPEATABLE READ** **isolation level**, the snapshot is based on the time when the first read operation is performed. 
- With **READ COMMITTED** isolation level, the snapshot is reset to the time of each consistent read operation.



InnoDB 是如何存储记录多个版本的？这些数据是 事务版本号，行记录中的隐藏列和Undo Log

System version number



4.undo-log

- Undo log是InnoDB MVCC事务特性的重要组成部分。当我们对记录做了变更操作时就会产生undo记录，Undo记录默认被记录到系统表空间(ibdata)中，但从5.6开始，也可以使用独立的Undo 表空间。
- Undo记录中存储的是老版本数据，当一个旧的事务需要读取数据时，为了能读取到老版本的数据，需要顺着undo链找到满足其可见性的记录。当版本链很长时，通常可以认为这是个比较耗时的操作（例如bug#69812）。
- 大多数对数据的变更操作包括INSERT/DELETE/UPDATE，其中INSERT操作在事务提交前只对当前事务可见，因此产生的Undo日志可以在事务提交后直接删除（谁会对刚插入的数据有可见性需求呢！！），而对于UPDATE/DELETE则需要维护多版本信息，在InnoDB里，UPDATE和DELETE操作产生的Undo日志被归成一类，即update_undo
- 另外, 在回滚段中的undo logs分为: `insert undo log` 和 `update undo log`
  - insert undo log : 事务对insert新记录时产生的undolog, 只在事务回滚时需要, 并且在事务提交后就可以立即丢弃。
  - update undo log : 事务对记录进行delete和update操作时产生的undo log, 不仅在事务回滚时需要, 一致性读也需要，所以不能随便删除，只有当数据库所使用的快照中不涉及该日志记录，对应的回滚日志才会被purge线程删除。

5.InnoDB存储引擎在数据库每行数据的后面添加了三个字段

- 6字节的`事务ID`(`DB_TRX_ID`)字段: 用来标识最近一次对本行记录做修改(insert|update)的事务的标识符, 即最后一次修改(insert|update)本行记录的事务id。
  至于delete操作，在innodb看来也不过是一次update操作，更新行中的一个特殊位将行表示为deleted, **并非真正删除**。
- 7字节的`回滚指针`(`DB_ROLL_PTR`)字段: 指写入回滚段(rollback segment)的 `undo log` record (撤销日志记录记录)。
  如果一行记录被更新, 则 `undo log` record 包含 '重建该行记录被更新之前内容' 所必须的信息。
- 6字节的`DB_ROW_ID`字段: 包含一个随着新行插入而单调递增的行ID, 当由innodb自动产生聚集索引时，聚集索引会包括这个行ID的值，否则这个行ID不会出现在任何索引中。
  结合聚簇索引的相关知识点, 我的理解是, 如果我们的表中没有主键或合适的唯一索引, 也就是无法生成聚簇索引的时候, InnoDB会帮我们自动生成聚集索引, 但聚簇索引会使用DB_ROW_ID的值来作为主键; 如果我们有自己的主键或者合适的唯一索引, 那么聚簇索引中也就不会包含 DB_ROW_ID 了 。



可见性比较算法（这里每个比较算法后面的描述是建立在rr级别下，rc级别也是使用该比较算法,此处未做描述）
设要读取的行的最后提交事务id(即当前数据行的稳定事务id)为 `trx_id_current`
当前新开事务id为 `new_id`
当前新开事务创建的快照`read view` 中最早的事务id为`up_limit_id`, 最迟的事务id为`low_limit_id`(注意这个low_limit_id=未开启的事务id=当前最大事务id+1)
比较:

- 1.`trx_id_current < up_limit_id`, 这种情况比较好理解, 表示, 新事务在读取该行记录时, 该行记录的稳定事务ID是小于, 系统当前所有活跃的事务, 所以当前行稳定数据对新事务可见, 跳到步骤5.
- 2.`trx_id_current >= trx_id_last`, 这种情况也比较好理解, 表示, 该行记录的稳定事务id是在本次新事务创建之后才开启的, 但是却在本次新事务执行第二个select前就commit了，所以该行记录的当前值不可见, 跳到步骤4。
- 3.`trx_id_current <= trx_id_current <= trx_id_last`, 表示: 该行记录所在事务在本次新事务创建的时候处于活动状态，从up_limit_id到low_limit_id进行遍历，如果trx_id_current等于他们之中的某个事务id的话，那么不可见, 调到步骤4,否则表示可见。
- 4.从该行记录的 DB_ROLL_PTR 指针所指向的回滚段中取出最新的undo-log的版本号, 将它赋值该 `trx_id_current`，然后跳到步骤1重新开始判断。
- 5.将该可见行的值返回



## 当前读和快照读

1.MySQL的InnoDB存储引擎默认事务隔离级别是RR(可重复读), 是通过 "行排他锁+MVCC" 一起实现的, 不仅可以保证可重复读, 还可以**部分**防止幻读, 而非完全防止;

2.为什么是部分防止幻读, 而不是完全防止?

- 效果: 在如果事务B在事务A执行中, insert了一条数据并提交, 事务A再次查询, 虽然读取的是undo中的旧版本数据(防止了部分幻读), 但是事务A中执行update或者delete都是可以成功的!!
- 因为在innodb中的操作可以分为`当前读(current read)`和`快照读(snapshot read)`:

3.快照读(snapshot read)

```
简单的select操作(当然不包括 select ... lock in share mode, select ... for update)
```

4.当前读(current read) [官网文档 Locking Reads](https://dev.mysql.com/doc/refman/5.7/en/innodb-locking-reads.html)

- select ... lock in share mode
- select ... for update
- insert
- update
- delete

在RR级别下，快照读是通过MVVC(多版本控制)和undo log来实现的，当前读是通过加record lock(记录锁)和gap lock(间隙锁)来实现的。
innodb在快照读的情况下并没有真正的避免幻读, 但是在当前读的情况下避免了不可重复读和幻读!!!



1. 一般我们认为MVCC有下面几个特点：
   - 每行数据都存在一个版本，每次数据更新时都更新该版本
   - 修改时Copy出当前版本, 然后随意修改，各个事务之间无干扰
   - 保存时比较版本号，如果成功(commit)，则覆盖原记录, 失败则放弃copy(rollback)
   - 就是每行都有版本号，保存时根据版本号决定是否成功，**听起来含有乐观锁的味道, 因为这看起来正是，在提交的时候才能知道到底能否提交成功**
2. 而InnoDB实现MVCC的方式是:
   - 事务以排他锁的形式修改原始数据
   - 把修改前的数据存放于undo log，通过回滚指针与主数据关联
   - 修改成功（commit）啥都不做，失败则恢复undo log中的数据（rollback）
3. **二者最本质的区别是**: 当修改数据时是否要`排他锁定`，如果锁定了还算不算是MVCC？

- Innodb的实现真算不上MVCC, 因为并没有实现核心的多版本共存, `undo log` 中的内容只是串行化的结果, 记录了多个事务的过程, 不属于多版本共存。但理想的MVCC是难以实现的, 当事务仅修改一行记录使用理想的MVCC模式是没有问题的, 可以通过比较版本号进行回滚, 但当事务影响到多行数据时, 理想的MVCC就无能为力了。
- 比如, 如果事务A执行理想的MVCC, 修改Row1成功, 而修改Row2失败, 此时需要回滚Row1, 但因为Row1没有被锁定, 其数据可能又被事务B所修改, 如果此时回滚Row1的内容，则会破坏事务B的修改结果，导致事务B违反ACID。 这也正是所谓的 `第一类更新丢失` 的情况。
- 也正是因为InnoDB使用的MVCC中结合了排他锁, 不是纯的MVCC, 所以第一类更新丢失是不会出现了, 一般说更新丢失都是指第二类丢失更新。





### **事务版本号**

每开启一个日志，都会从数据库中获得一个事务ID（也称为事务版本号），这个事务 ID 是自增的，通过 ID 大小，可以判断事务的时间顺序。

### **行记录的隐藏列**

1. row_id :隐藏的行 ID ,用来生成默认的聚集索引。如果创建数据表时没指定聚集索引，这时 InnoDB 就会用这个隐藏 ID 来创建聚集索引。采用聚集索引的方式可以提升数据的查找效率。
2. trx_id: 操作这个数据事务 ID ，也就是最后一个对数据插入或者更新的事务 ID 。
3. roll_ptr:回滚指针，指向这个记录的 Undo Log 信息。

InnoDB 将行记录快照保存在 Undo Log 里

数据行通过快照记录都通过链表的结构的串联了起来，每个快照都保存了 trx_id 事务ID，如果要找到历史快照，就可以通过遍历回滚指针的方式进行查找

## **Read View 是啥？**

如果一个事务要查询行记录，需要读取哪个版本的行记录呢？ Read View 就是来解决这个问题的。Read View 可以帮助我们解决可见性问题。 Read View 保存了**当前事务开启时所有活跃的事务列表**。换个角度，可以理解为: **Read View 保存了不应该让这个事务看到的其他事务 ID 列表。**

1. trx_ids 系统当前正在活跃的事务ID集合。
2. low_limit_id ,活跃事务的最大的事务 ID。
3. up_limit_id 活跃的事务中最小的事务 ID。
4. creator_trx_id，创建这个 ReadView 的事务ID

如果当前事务的 creator_trx_id 想要读取某个行记录，这个行记录ID 的trx_id ，这样会有以下的情况：

- 如果 trx_id < 活跃的最小事务ID（up_limit_id）,也就是说这个行记录在**这些活跃的事务创建前就已经提交了，那么这个行记录对当前事务是可见的。**
- 如果trx_id > 活跃的最大事务ID（low_limit_id），这个说明行记录在这些活跃的事务之后才创建，说明**这个行记录对当前事务是不可见的。**
- 如果 up_limit_id < trx_id <low_limit_id,说明该记录需要在 trx_ids 集合中，可能还处于活跃状态，因此我们需要在 trx_ids 集合中遍历 ，如果trx_id 存在于 trx_ids 集合中，证明这个事务 trx_id 还处于活跃状态，不可见，否则 ，trx_id 不存在于 trx_ids 集合中，说明事务trx_id 已经提交了，这行记录是可见的。



已提交读每次都是新的Read View, 可重复读会复用第一次读的Read  View



## **如何查询一条记录**

1. 获取事务自己的版本号，即 事务ID
2. 获取 Read View
3. 查询得到的数据，然后 Read View 中的事务版本号进行比较。
4. 如果不符合 ReadView 规则， 那么就需要 UndoLog 中历史快照；
5. 最后返回符合规则的数据

InnoDB 实现多版本控制 （MVCC）是通过 ReadView+ UndoLog 实现的，UndoLog 保存了历史快照，ReadView 规则帮助判断当前版本的数据是否可见。



- 如果事务隔离级别是 ReadCommit ，一个事务的每一次 Select 都会去查一次ReadView ，每次查询的Read View 不同，就可能会造成不可重复读或者幻读的情况。
- 如果事务的隔离级别是可重读，为了避免不可重读读，一个事务只在第一次 Select 的时候会获取一次Read View ，然后后面索引的Select 会复用这个 ReadView.