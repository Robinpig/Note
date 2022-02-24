## Introduction


### Transactional Properties
- The relational world
- Multi-user
- Distributed systems


## ACID

### Properties

A transaction is a unit of work enjoying the following properties:

- Atomicity
- Consistency
- Isolation
- Durability


#### Atomicity
A transaction is an atomic transformation from the initial state to the final state
Possible behaviors:
1. Commit work: SUCCESS
2. Rollback work or error prior to commit: UNDO
3. Fault after commit: REDO


#### Consistency
The transaction satisfies the integrity constraints Consequence:
- If the initial state is consistent
- Then the final state is also consistent

#### Isolation
A transaction is not affected by the behavior of other, concurrent transactions Consequence:
- Its intermediate states are not exposed
- The “domino effect” is avoided


#### Durability
The effect of a transaction that has successfully committed will
last “forever”
- Independently of any system fault

### Isolation Levels

- Atomicity
  - Abort-rollback-restart
  - Commit protocols
- Consistency
  - Integrity checking of the DBMS
- Isolation
  - Concurrency control
- Durability
  - Recovery management


| Isolation level  | Dirty Read               | Non-Repeatable Read | Phantom Read |
| ---------------- | ------------------------ | ------------------- | ------------ |
| READ-UNCOMMITTED | :white_check_mark:  | :white_check_mark: | :white_check_mark: |
| READ-COMMITTED   | :x:    | :white_check_mark: | :white_check_mark: |
| REPEATABLE-READ  | :x: | :x: | :white_check_mark: |
| SERIALIZABLE     | :x: | :x: | :x: |

### Phenomena

#### Dirty Read

A dirty read happens when a transaction is **allowed to read uncommitted changes of some other running transaction**. This happens because there is no locking preventing it. 

Taking a business decision on a value that has not been committed is risky because uncommitted changes might get rolled back.

#### Non-Repeatable Read

A non-repeatable read manifests when consecutive reads yield **different results due to a concurring transaction that has just updated the record we’re reading**. This is undesirable since we end up using stale data. 

This is prevented by holding a shared lock (read lock) on the read record for the whole duration of the current transaction.

#### Phantom Read

A phantom read happens when **a subsequent transaction inserts a row that matches the filtering criteria of a previous query executed by a concurrent transaction**.

The so-called phantom problem occurs within a transaction when the same query produces different sets of rows at different times. For example, if a `SELECT` is executed twice, but returns a row the second time that was not returned the first time, the row is a “phantom” row.

The `2PL-based` Serializable isolation prevents Phantom Reads through the use of predicate locking while MVCC (Multi-Version Concurrency Control) database engines address the Phantom Read anomaly by returning consistent snapshots.



#### Lost updates

Read Committed accommodates more concurrent transactions than other stricter isolation levels, but less locking leads to better chances of losing updates.

- Using Repeatable Read (as well as Serializable which offers an even stricter isolation level) can prevent lost updates across concurrent database transactions.
- Another solution would be to use the `FOR UPDATE` with the default Read Committed isolation level. This locking clause acquires the same write locks as with `UPDATE` and `DELETE` statements.
- Replace pessimistic locking with an optimistic locking mechanism. Like MVCC. optimistic locking defines a versioning concurrency control model that works without acquiring additional database write locks.

MySQL avoids this issue at all isolation levels.

#### Read skew

Using **Repeatable Read** (as well as Serializable which offers an even stricter isolation level) can prevent read skews across concurrent database transactions.



#### Write skew

- Write skew is prevalent among MVCC (Multi-Version Concurrency Control) mechanisms and Oracle cannot prevent it even when claiming to be using Serializable, which in fact is just the Snapshot Isolation level.
- SQL Server default locking-based isolation levels can prevent write skews when using Repeatable Read and Serializable. Neither one of its MVCC-based isolation levels ([MVCC-based) can prevent/detect it instead.
- PostgreSQL prevents it by using its more advanced Serializable Snapshot Isolation level.
- MySQL employs shared locks when using Serializable so the write skew can be prevented even if InnoDB is also MVCC-based.





mysql use Next-Key Lock algorithm avoid Phantom Read like SERIALIZABLE.


```mysql
mysql>SELECT @@tx_isolation;
REPEATABLE-READ
```



other dbs(Oracle,SQL Server) are `READ-COMMITTED `



Innodb in distribution-transaction is SERIALIZABLE.



## CAP Theorem (Brewer’s Theorem)
It is impossible for a distributed computer system to simultaneously provide all three of the following guarantees:
- **Consistency**: all nodes see the same data at the same time
- **Availability**: Node failures do not prevent other survivors from continuing to operate (a guarantee that every request receives a response about whether it succeeded or failed)
- **Partition tolerance**: the system continues to operate despite arbitrary partitioning due to network failures (e.g., message loss)
A distributed system can satisfy any two of these guarantees at the same time but not all three.

## BASE
(Basically Available, Soft-State, Eventually Consistent)
• Basic Availability: fulfill request, even in partial consistency.
• Soft State: abandon the consistency requirements of the ACID model pretty much completely
• Eventual Consistency: at some point in the future, data will converge to a consistent state; delayed consistency, as opposed to immediate consistency of the ACID properties.
• purely a liveness guarantee (reads eventually return the requested value); but
• does not make safety guarantees, i.e.,
• an eventually consistent system can return any value before it converges


### ACID vs. BASE trade-off
• No general answer to whether your application needs an ACID versus BASE
consistency model.
• Given BASE’s loose consistency, developers need to be more
knowledgeable and rigorous about consistent data if they choose a BASE
store for their application.
• Planning around BASE limitations can sometimes be a major disadvantage
when compared to the simplicity of ACID transactions.
• A fully ACID database is the perfect fit for use cases where data reliability
and consistency are essential.


## Two-phased Commit
A two-phase commit protocol is an algorithm that lets all clients in a distributed system agree either to commit a transaction or abort.



## Links

- [MySQL Transaction](/docs/CS/DB/MySQL/Transaction.md)

## References
1. [ACID vs. BASE and SQL vs. NoSQL](https://marcobrambillapolimi.files.wordpress.com/2019/01/01-nosql-overview.pdf)
2. [A Critique of ANSI SQL Isolation Levels](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-95-51.pdf)