## Introduction

Knowledge Base of Relational and NoSQL Database Management Systems in [DB-Engines](https://db-engines.com/en/ranking)

## Architecture

Database management systems use a client/server model, where database system instances (nodes) take the role of servers, and application instances take the role of clients.

Client requests arrive through the transport subsystem. Requests come in the form of queries, most often expressed in some query language.
The transport subsystem is also responsible for communication with other nodes in the database cluster.

<div style="text-align: center;">

![Architecture of a database management system](./img/DB.png)

</div>

<p style="text-align: center;">
Fig.1. Architecture of a database management system
</p>

Upon receipt, the transport subsystem hands the query over to a query processor, which parses, interprets, and validates it.
Later, access control checks are performed, as they can be done fully only after the query is interpreted.

“The parsed query is passed to the query optimizer, which first eliminates impossible and redundant parts of the query, and then attempts to find the most efficient way to execute it based on internal statistics (index cardinality, approximate intersection size, etc.) and data placement (which nodes in the cluster hold the data and the costs associated with its transfer).
The optimizer handles both relational operations required for query resolution, usually presented as a dependency tree, and optimizations, such as index ordering, cardinality estimation, and choosing access methods.

“The query is usually presented in the form of an execution plan (or query plan): a sequence of operations that have to be carried out for its results to be considered complete.”

“Since the same query can be satisfied using different execution plans that can vary in efficiency, the optimizer picks the best available plan.

The execution plan is handled by the execution engine, which collects the results of the execution of local and remote operations. Remote execution can involve writing and reading data to and from other nodes in the cluster, and replication.

Local queries (coming directly from clients or from other nodes) are executed by the storage engine.
The storage engine has several components with dedicated responsibilities:”

“Transaction manager

This manager schedules transactions and ensures they cannot leave the database in a logically inconsistent state.

Lock manager

This manager locks on the database objects for the running transactions, ensuring that concurrent operations do not violate physical data integrity.

Access methods (storage structures)

These manage access and organizing data on disk. Access methods include heap files and storage structures such as B-Trees (see “Ubiquitous B-Trees”) or LSM Trees (see “LSM Trees”).

Buffer manager

This manager caches data pages in memory (see “Buffer Management”).

Recovery manager

This manager maintains the operation log and restoring the system state in case of a failure (see “Recovery”).

Together, transaction and lock managers are responsible for concurrency control (see “Concurrency Control”):
they guarantee logical and physical data integrity while ensuring that concurrent operations are executed as efficiently as possible.

Storage data layer

Cache Layer

Transport Layer

Execute Layer

Log Layer

Authority Layer

Tolerance

concurrency

A version of the tree that would be better suited for disk implementation has to exhibit the following properties:

- High fanout to improve locality of the neighboring keys.
- Low height to reduce the number of seeks during traversal.

> [!TIP]
>
> Fanout and height are inversely correlated: the higher the fanout, the lower the height.
> If fanout is high, each node can hold more children, reducing the number of nodes and, subsequently, reducing height.

## Concurrency Control

### Why is concurrency control needed?

If transactions are executed *serially*, i.e., sequentially with no overlap in time, no transaction concurrency exists. However, if concurrent transactions with interleaving operations are allowed in an uncontrolled manner, some unexpected, undesirable results may occur, such as:

1. The lost update problem: A second transaction writes a second value of a data-item (datum) on top of a first value written by a first concurrent transaction, and the first value is lost to other transactions running concurrently which need, by their precedence, to read the first value. The transactions that have read the wrong value end with incorrect results.
2. The dirty read problem: Transactions read a value written by a transaction that has been later aborted. This value disappears from the database upon abort, and should not have been read by any transaction ("dirty read"). The reading transactions end with incorrect results.
3. The incorrect summary problem: While one transaction takes a summary over the values of all the instances of a repeated data-item, a second transaction updates some instances of that data-item. The resulting summary does not reflect a correct result for any (usually needed for correctness) precedence order between the two transactions (if one is executed before the other), but rather some random result, depending on the timing of the updates, and whether certain update results have been included in the summary or not.

Most high-performance transactional systems need to run transactions concurrently to meet their performance requirements. Thus, without concurrency control such systems can neither provide correct results nor maintain their databases consistently.

### Concurrency control mechanisms

#### Categories

The main categories of concurrency control mechanisms are:

- **[Optimistic](https://en.wikipedia.org/wiki/Optimistic_concurrency_control)** - Delay the checking of whether a transaction meets the isolation and other integrity rules (e.g., [serializability](https://en.wikipedia.org/wiki/Serializability) and [recoverability](https://en.wikipedia.org/wiki/Serializability#Correctness_-_recoverability)) until its end, without blocking any of its (read, write) operations ("...and be optimistic about the rules being met..."), and then abort a transaction to prevent the violation, if the desired rules are to be violated upon its commit. An aborted transaction is immediately restarted and re-executed, which incurs an obvious overhead (versus executing it to the end only once). If not too many transactions are aborted, then being optimistic is usually a good strategy.
- **Pessimistic** - Block an operation of a transaction, if it may cause violation of the rules, until the possibility of violation disappears. Blocking operations is typically involved with performance reduction.
- **Semi-optimistic** - Block operations in some situations, if they may cause violation of some rules, and do not block in other situations while delaying rules checking (if needed) to transaction's end, as done with optimistic.

Different categories provide different performance, i.e., different average transaction completion rates (*throughput*), depending on transaction types mix, computing level of parallelism, and other factors. If selection and knowledge about trade-offs are available, then category and method should be chosen to provide the highest performance.

The mutual blocking between two transactions (where each one blocks the other) or more results in a [deadlock](https://en.wikipedia.org/wiki/Deadlock), where the transactions involved are stalled and cannot reach completion. Most non-optimistic mechanisms (with blocking) are prone to deadlocks which are resolved by an intentional abort of a stalled transaction (which releases the other transactions in that deadlock), and its immediate restart and re-execution. The likelihood of a deadlock is typically low.

Blocking, deadlocks, and aborts all result in performance reduction, and hence the trade-offs between the categories.

#### Methods

Many methods for concurrency control exist. Most of them can be implemented within either main category above. The major methods,[[1\]](https://en.wikipedia.org/wiki/Concurrency_control#cite_note-Bern2009-1) which have each many variants, and in some cases may overlap or be combined, are:

1. Locking (e.g., **[Two-phase locking](https://en.wikipedia.org/wiki/Two-phase_locking)** - 2PL) - Controlling access to data by [locks](https://en.wikipedia.org/wiki/Lock_(computer_science)) assigned to the data. Access of a transaction to a data item (database object) locked by another transaction may be blocked (depending on lock type and access operation type) until lock release.
2. **Serialization [graph checking](https://en.wikipedia.org/wiki/Serializability#Testing_conflict_serializability)** (also called Serializability, or Conflict, or Precedence graph checking) - Checking for [cycles](https://en.wikipedia.org/wiki/Cycle_(graph_theory)) in the schedule's [graph](https://en.wikipedia.org/wiki/Directed_graph) and breaking them by aborts.
3. **[Timestamp ordering](https://en.wikipedia.org/wiki/Timestamp-based_concurrency_control)** (TO) - Assigning timestamps to transactions, and controlling or checking access to data by timestamp order.
4. **[Commitment ordering](https://en.wikipedia.org/wiki/Commitment_ordering)** (or Commit ordering; CO) - Controlling or checking transactions' chronological order of commit events to be compatible with their respective [precedence order](https://en.wikipedia.org/wiki/Serializability#Testing_conflict_serializability).

Other major concurrency control types that are utilized in conjunction with the methods above include:

- **[Multiversion concurrency control](https://en.wikipedia.org/wiki/Multiversion_concurrency_control)** (MVCC) - Increasing concurrency and performance by generating a new version of a database object each time the object is written, and allowing transactions' read operations of several last relevant versions (of each object) depending on scheduling method.
- **[Index concurrency control](https://en.wikipedia.org/wiki/Index_locking)** - Synchronizing access operations to [indexes](https://en.wikipedia.org/wiki/Index_(database)), rather than to user data. Specialized methods provide substantial performance gains.
- **Private workspace model** (**Deferred update**) - Each transaction maintains a private workspace for its accessed data, and its changed data become visible outside the transaction only upon its commit (e.g., [Weikum and Vossen 2001](https://en.wikipedia.org/wiki/Concurrency_control#Weikum01)). This model provides a different concurrency control behavior with benefits in many cases.

The most common mechanism type in database systems since their early days in the 1970s has been *[Strong strict Two-phase locking](https://en.wikipedia.org/wiki/Two-phase_locking)* (SS2PL; also called *Rigorous scheduling* or *Rigorous 2PL*) which is a special case (variant) of both [Two-phase locking](https://en.wikipedia.org/wiki/Two-phase_locking) (2PL) and [Commitment ordering](https://en.wikipedia.org/wiki/Commitment_ordering) (CO). It is pessimistic. In spite of its long name (for historical reasons) the idea of the **SS2PL** mechanism is simple: "Release all locks applied by a transaction only after the transaction has ended." SS2PL (or Rigorousness) is also the name of the set of all schedules that can be generated by this mechanism, i.e., these are SS2PL (or Rigorous) schedules, have the SS2PL (or Rigorousness) property.

### Optimistic concurrency control

**Optimistic concurrency control** (**OCC**) is a [concurrency control](https://en.wikipedia.org/wiki/Concurrency_control) method applied to transactional systems such as [relational database management systems](https://en.wikipedia.org/wiki/Relational_database_management_systems) and [software transactional memory](https://en.wikipedia.org/wiki/Software_transactional_memory). OCC assumes that multiple transactions can frequently complete without interfering with each other. While running, transactions use data resources without acquiring locks on those resources. Before committing, each transaction verifies that no other transaction has modified the data it has read. If the check reveals conflicting modifications, the committing transaction rolls back and can be restarted.[[1\]](https://en.wikipedia.org/wiki/Optimistic_concurrency_control#cite_note-1) Optimistic concurrency control was first proposed by [H. T. Kung](https://en.wikipedia.org/wiki/H._T._Kung) and John T. Robinson.[[2\]](https://en.wikipedia.org/wiki/Optimistic_concurrency_control#cite_note-KungRobinson1981-2)

OCC is generally used in environments with low [data contention](https://en.wikipedia.org/wiki/Block_contention). When conflicts are rare, transactions can complete without the expense of managing locks and without having transactions wait for other transactions' locks to clear, leading to higher throughput than other concurrency control methods. However, if contention for data resources is frequent, the cost of repeatedly restarting transactions hurts performance significantly, in which case other [concurrency control](https://en.wikipedia.org/wiki/Concurrency_control) methods may be better suited. However, locking-based ("pessimistic") methods also can deliver poor performance because locking can drastically limit effective concurrency even when deadlocks are avoided.

#### Phases of optimistic concurrency control

Optimistic concurrency control transactions involve these phases:

- **Begin**: Record a timestamp marking the transaction's beginning.
- **Modify**: Read database values, and tentatively write changes.
- **Validate**: Check whether other transactions have modified data that this transaction has used (read or written). This includes transactions that completed after this transaction's start time, and optionally, transactions that are still active at validation time.
- **Commit/Rollback**: If there is no conflict, make all changes take effect. If there is a conflict, resolve it, typically by aborting the transaction, although other resolution schemes are possible. Care must be taken to avoid a [time-of-check to time-of-use](https://en.wikipedia.org/wiki/Time-of-check_to_time-of-use) bug, particularly if this phase and the previous one are not performed as a single [atomic](https://en.wikipedia.org/wiki/Linearizability) operation.

### Two-phase locking

In [databases](https://en.wikipedia.org/wiki/Database) and [transaction processing](https://en.wikipedia.org/wiki/Transaction_processing), **two-phase locking** (**2PL**) is a [concurrency control](https://en.wikipedia.org/wiki/Concurrency_control) method that guarantees [serializability](https://en.wikipedia.org/wiki/Serializability).[[1\]](https://en.wikipedia.org/wiki/Two-phase_locking#cite_note-Bern1987-1)[[2\]](https://en.wikipedia.org/wiki/Two-phase_locking#cite_note-Weikum2001-2) It is also the name of the resulting set of [database transaction](https://en.wikipedia.org/wiki/Database_transaction) [schedules](https://en.wikipedia.org/wiki/Schedule_(computer_science)) (histories). The protocol utilizes [locks](https://en.wikipedia.org/wiki/Lock_(computer_science)), applied by a transaction to data, which may block (interpreted as signals to stop) other transactions from accessing the same data during the transaction's life.

By the 2PL protocol, locks are applied and removed in two phases:

1. Expanding phase: locks are acquired and no locks are released.
2. Shrinking phase: locks are released and no locks are acquired.

Two types of locks are utilized by the basic protocol: *Shared* and *Exclusive* locks. Refinements of the basic protocol may utilize more lock types. Using locks that block processes, 2PL may be subject to [deadlocks](https://en.wikipedia.org/wiki/Deadlock) that result from the mutual blocking of two or more transactions.

## Replication

When thinking about replication we need to make a decision on two different categories of configurations:

* Algorithm for performing replication
  * Leader-Follower Replication
  * Multi Leader Replication
  * Leaderless Replication
* Process in which replication is performed
  * Synchronous Replication
  * Asynchronous Replication
  * Combination of both synchronous & asynchronous replication

## Shard

[Shard](/docs/CS/DB/Shard.md)

[Granularity of Locks and Degrees of Consistency in a Shared DataBase](http://jimgray.azurewebsites.net/papers/granularity%20of%20locks%20and%20degrees%20of%20consistency%20rj%201654.pdf)

Atomic Commitment Protocl(ACP)

## DBs

Document databases reverted back to the hierarchical model in one aspect: storing nested records (one-to-many relationships) within their parent record rather than in a separate table.

When it comes to representing many-to-one and many-to-many relationships, relational and document databases are not fundamentally different:
in both cases, the related item is referenced by a unique identifier, which is called a foreign key in the relational model and a document reference in the document model.
That identifier is resolved at read time by using a join or follow-up queries.

The main arguments in favor of the document data model are schema flexibility, better performance due to locality, and that for some applications it is closer to the data structures used by the application.
The relational model counters by providing better support for joins, and many-to-one and many-to-many relationships.

If the data in your application has a document-like structure (i.e., a tree of one-tomany relationships, where typically the entire tree is loaded at once), then it’s probably a good idea to use a document model.
The relational technique of shredding—splitting a document-like structure into multiple tables can lead to cumbersome schemas and unnecessarily complicated application code.
The document model has limitations: for example, you cannot refer directly to a nested item within a document, but instead you need to say something like “the second item in the list of positions for user 251” (much like an access path in the hierarchical model).
However, as long as documents are not too deeply nested, that is not usually a problem.

Document databases are called schema-on-read (the structure of the data is implicit, and only interpreted when the data is read), in contrast with schema-on-write (the traditional approach of relational databases, where the schema is explicit and the database ensures all written data conforms to it).
Schema-on-read is similar to dynamic (runtime) type checking in programming lanuages, whereas schema-on-write is similar to static (compile-time) type checking.

The difference between the approaches is particularly noticeable in situations where an application wants to change the format of its data.
For example, say you are currently storing each user’s full name in one field, and you instead want to store the first name and last name separately.
In a document database, you would just start writing new documents with the new fields and have code in the application that handles the case when old documents are read.
For example:

```
if (user && user.name && !user.first_name) {
// Documents written before Dec 8, 2013 don't have first_name
user.first_name = user.name.split(" ")[0];
}
```

On the other hand, in a “statically typed” database schema, you would typically perform a migration along the lines of:

```sql
ALTER TABLE users ADD COLUMN first_name text;
UPDATE users SET first_name = split_part(name, ' ', 1); -- PostgreSQL
UPDATE users SET first_name = substring_index(name, ' ', 1); -- MySQL
```

Schema changes have a bad reputation of being slow and requiring downtime.
This reputation is not entirely deserved: most relational database systems execute the ALTER TABLE statement in a few milliseconds.
MySQL is a notable exception—it copies the entire table on ALTER TABLE, which can mean minutes or even hours of downtime when altering a large table—although various tools exist to work around this limitation.

Running the UPDATE statement on a large table is likely to be slow on any database, since every row needs to be rewritten.
If that is not acceptable, the application can leave first_name set to its default of NULL and fill it in at read time, like it would with a document database.

The schema-on-read approach is advantageous if the items in the collection don’t all have the same structure for some reason (i.e., the data is heterogeneous)—for example, because:

- There are many different types of objects, and it is not practical to put each type of object in its own table.
- The structure of the data is determined by external systems over which you have no control and which may change at any time.

In situations like these, a schema may hurt more than it helps, and schemaless documents can be a much more natural data model. But in cases where all records are expected to have the same structure, schemas are a useful mechanism for documenting and enforcing that structure.

### MySQL

[MySQL Server](/docs/CS/DB/MySQL/MySQL.md), the world's most popular open source database, and MySQL Cluster, a real-time, open source transactional database.

### Redis

[Redis](/docs/CS/DB/Redis/Redis.md) is an open source (BSD licensed), in-memory data structure store, used as a database, cache, and message broker.

### LevelDB

[LevelDB](/docs/CS/DB/LevelDB/LevelDB.md) is a fast key-value storage library written at Google that provides an ordered mapping from string keys to string values.
LevelDB is a widely used key-value store based on [LSMtrees](/docs/CS/Algorithms/LSM.md) that is inspired by [BigTable](/docs/CS/Distributed/Bigtable.md).
LevelDB supports range queries, snapshots, and other features that are useful in modern applications.

## Links

## References

1. [NoSQL Database Systems - A Survey and Decision Guidance](https://www.baqend.com/files/nosql-survey.pdf)
