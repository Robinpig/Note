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
### optimizer
The parsed query is passed to the query optimizer, which first eliminates impossible and redundant parts of the query, 
and then attempts to find the most efficient way to execute it based on internal statistics (index cardinality, approximate intersection size, etc.) and data placement (which nodes in the cluster hold the data and the costs associated with its transfer).
The optimizer handles both relational operations required for query resolution, usually presented as a dependency tree, and optimizations, such as index ordering, cardinality estimation, and choosing access methods.

The query is usually presented in the form of an execution plan (or query plan): a sequence of operations that have to be carried out for its results to be considered complete.

Since the same query can be satisfied using different execution plans that can vary in efficiency, the optimizer picks the best available plan.

One of the long-standing advantages of relational databases has been that data is requested with little or no thought for the way in which the data is to be accessed.
This decision is made by a component of the DBMS called the optimizer. 
These have varied widely across different relational systems and probably always will, but they all try to access the data in the most effective way possible, using statistics stored by the system collected on the data.


Before an SQL statement can be executed, the optimizer must first decide how to access the data; which index, if any, should be used; how the index should be used; should assisted random read be used; and so forth. 
All of this information is embodied in the access path.



<div style="text-align: center;">

![Traditional index scan](./img/Traditional-Index-Scan.png)

</div>

<p style="text-align: center;">
Fig.2. Traditional index scan.
</p>

Index Slices and Matching Columns
Thus a thin slice of the index, depicted in Figure 3.1, will be sequentially scanned,
and for each index row having a value between 100 and 110, the corresponding
row will be accessed from the table using a synchronous read unless the page
is already in the buffer pool. The cost of the access path is clearly going to
depend on the thickness of the slice, which in turn will depend on the range
predicate; a thicker slice will, of course, require more index pages to be read
sequentially and more index rows will have to be processed. The real increase
in cost though is going to come from an increase in the number of synchronous
reads to the table at a cost of perhaps 10 ms per page. Similarly, a thinner slice
will certainly reduce the index costs, but again the major saving will be due to
fewer synchronous reads to the table. The size of the index slice may be very
important for this reason.

The term index slice is not one that is used by any of the relational database
systems; these all use their own terminology, but we feel that an index slice
is a much more descriptive term and one that we can use regardless of DBMS.
Another way that is often used to describe an index slice is to define the number of
matching columns used in the processing of the index. In our example (having
a value between 100 and 110), we have only a single matching column. 
This single matching column in fact defines the thickness of our slice. If there had
been a second column, both in the WHERE clause and in the index, such that the
two columns together were able to define an even thinner slice of the index, we
would have two matching columns. Less index processing would be required,
but of even greater importance, fewer synchronous reads to the table would
be required.


#### Index Screening and Screening Columns

Sometimes a column may indeed be in both the WHERE clause and in the index, suffice it to say at this time that not all columns in the index are able to define the index slice.
Such columns, however, may still be able to reduce the number of synchronous reads to the table and so play the more important part.
We will call these columns screening columns, as indeed do some relational database systems, because this is exactly what they do. 
They avoid the necessity of accessing the table rows because they are able to determine that it is not necessary to do so by their very presence in the index.

Examine index columns from leading to trailing
1. In the WHERE clause, does a column have at least one simple enough predicate referring to it?
   If yes, the column is an M column.
   If not, this column and the remaining columns are not M columns.
2. If the predicate is a range predicate, the remaining columns are not M columns.
3. Any column after the last M column is an S column if there is a simple enough predicate referring to that column.

#### Access Path Terminology

Unfortunately, the terminology used to describe access paths is far from standardized—even the term access path itself, another term that is often used being the execution plan.
We will use access path when referring to the way the data is actually accessed; we will use execution plan when referring to the output provided by the DBMS by means of an `EXPLAIN` facility (described below). 
This is a subtle distinction, and it is really of no consequence if the terms are used interchangeably.

The execution plan is handled by the execution engine, which collects the results of the execution of local and remote operations. Remote execution can involve writing and reading data to and from other nodes in the cluster, and replication.

Matching predicates are sometimes called range delimiting predicates. 
If a predicate is simple enough for an optimizer in the sense that it is a matching predicate when a suitable index is available, it is called indexable or sargable. 
The opposite term is nonindexable or nonsargable.

SQL Server uses the term table lookup for an access path that uses an index but also reads table rows. This is the opposite of index only. 
The obvious way to eliminate the table accesses is to add the missing columns to the index. 
Many SQL Server books call an index a covering index when it makes an index-only access path possible for a SELECT call. 
SELECT statements that use a covering index are sometimes called covering SELECTs.



### Transaction manager
Local queries (coming directly from clients or from other nodes) are executed by the storage engine.
The storage engine has several components with dedicated responsibilities:


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


## OLAP

Table. Comparing characteristics of transaction processing versus analytic systems


| Property             | Transaction processing systems (OLTP)             | Analytic systems (OLAP)                   |
| ---------------------- | --------------------------------------------------- | ------------------------------------------- |
| Main read pattern    | Small number of records per query, fetched by key | Aggregate over large number of records    |
| Main write pattern   | Random-access, low-latency writes from user input | Bulk import (ETL) or event stream         |
| Primarily used by    | End user/customer, via web application            | Internal analyst, for decision support    |
| What data represents | Latest state of data (current point in time)      | History of events that happened over time |
| Dataset size         | Gigabytes to terabytes                            | Terabytes to petabytes                    |

At first, the same databases were used for both transaction processing and analytic queries.
SQL turned out to be quite flexible in this regard: it works well for OLTPtype queries as well as OLAP-type queries. 
Nevertheless, in the late 1980s and early 1990s, there was a trend for companies to stop using their OLTP systems for analytics purposes, and to run the analytics on a separate database instead. 
This separate database was called a *data warehouse*

### Data Warehousing

An enterprise may have dozens of different transaction processing systems: systems powering the customer-facing website, controlling point of sale (checkout) systems in physical stores, 
tracking inventory in warehouses, planning routes for vehicles, managing suppliers, administering employees, etc. 
Each of these systems is complex and needs a team of people to maintain it, so the systems end up operating mostly autonomously from each other.
These OLTP systems are usually expected to be highly available and to process transactions with low latency, since they are often critical to the operation of the business. 
Database administrators therefore closely guard their OLTP databases. 
They are usually reluctant to let business analysts run ad hoc analytic queries on an OLTP database, since those queries are often expensive, scanning large parts of the dataset, which can harm the performance of concurrently executing transactions.

A data warehouse, by contrast, is a separate database that analysts can query to their hearts’ content, without affecting OLTP operations. 
The data warehouse contains a read-only copy of the data in all the various OLTP systems in the company.
Data is extracted from OLTP databases (using either a periodic data dump or a continuous stream of updates), transformed into an analysis-friendly schema, cleaned up, and then loaded into the data warehouse. 
This process of getting data into the warehouse is known as Extract–Transform–Load (ETL).

A big advantage of using a separate data warehouse, rather than querying OLTP systems directly for analytics, is that the data warehouse can be optimized for analytic access patterns. 
It turns out that the indexing algorithms work well for OLTP, but are not very good at answering analytic queries.

The data model of a data warehouse is most commonly relational, because SQL is generally a good fit for analytic queries.
There are many graphical data analysis tools that generate SQL queries, visualize the results, and allow analysts to explore the data(through operations such as drill-down and slicing and dicing).
On the surface, a data warehouse and a relational OLTP database look similar, because they both have a SQL query interface. 
However, the internals of the systems can look quite different, because they are optimized for very different query patterns.
Many database vendors now focus on supporting either transaction processing or analytics workloads, but not both.
Some databases, such as Microsoft SQL Server and SAP HANA, have support for transaction processing and data warehousing in the same product. However, they are increasingly becoming two separate storage and query engines, which happen to be accessible through a common SQL interface.




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

A document is usually stored as a single continuous string, encoded as JSON, XML, or a binary variant thereof (such as MongoDB’s BSON).
If your application often needs to access the entire document (for example, to render it on a web page), there is a performance advantage to this storage locality.
If data is split across multiple tables, multiple index lookups are required to retrieve it all, which may require more disk seeks and take more time.

The locality advantage only applies if you need large parts of the document at the same time.
The database typically needs to load the entire document, even if you access only a small portion of it, which can be wasteful on large documents.
On updates to a document, the entire document usually needs to be rewritten—only modifications that don’t change the encoded size of a document can easily be performed in place.
For these reasons, it is generally recommended that you keep documents fairly small and avoid writes that increase the size of a document.
These performance limitations significantly reduce the set of situations in which document databases are useful.

New nonrelational “NoSQL” datastores have diverged in two main directions:

1. Document databases target use cases where data comes in self-contained documents and relationships between one document and another are rare.
2. Graph databases go in the opposite direction, targeting use cases where anything is potentially related to everything.

### Inmemory DB

The data structures discussed so far in this chapter have all been answers to the limitations of disks. Compared to main memory, disks are awkward to deal with.
With both magnetic disks and SSDs, data on disk needs to be laid out carefully if you want good performance on reads and writes.
However, we tolerate this awkwardness because disks have two significant advantages: they are durable (their contents are not lost if the power is turned off), and they have a lower cost per gigabyte than RAM.
As RAM becomes cheaper, the cost-per-gigabyte argument is eroded.
Many datasets are simply not that big, so it’s quite feasible to keep them entirely in memory, potenially distributed across several machines.
This has led to the development of *inmemory databases*.
Some in-memory key-value stores, such as Memcached, are intended for caching use only, where it’s acceptable for data to be lost if a machine is restarted.
But other inmemory databases aim for durability, which can be achieved with special hardware(such as battery-powered RAM), by writing a log of changes to disk, by writing periodic snapshots to disk, or by replicating the in-memory state to other machines.
When an in-memory database is restarted, it needs to reload its state, either from disk or over the network from a replica (unless special hardware is used).
Despite writing to disk, it’s still an in-memory database, because the disk is merely used as an append-only log for durability, and reads are served entirely from memory.
Writing to disk also has operational advantages: files on disk can easily be backed up, inspected, and analyzed by external utilities.

Products such as VoltDB, MemSQL, and Oracle TimesTen are in-memory databases with a relational model, and the vendors claim that they can offer big performance improvements by removing all the overheads associated with managing on-disk data structures.
RAMCloud is an open source, in-memory key-value store with durability (using a log-structured approach for the data in memory as well as the data on disk).
Redis and Couchbase provide weak durability by writing to disk asynchronously.

Counterintuitively, the performance advantage of in-memory databases is not due to the fact that they don’t need to read from disk.
Even a disk-based storage engine may never need to read from disk if you have enough memory, because the operating system caches recently used disk blocks in memory anyway.
Rather, they can be faster because they can avoid the overheads of encoding in-memory data structures in a form that can be written to disk.

Besides performance, another interesting area for in-memory databases is providing data models that are difficult to implement with disk-based indexes.
For example, Redis offers a database-like interface to various data structures such as priority queues and sets.
Because it keeps all data in memory, its implementation is comparatively simple.
Recent research indicates that an in-memory database architecture could be extended to support datasets larger than the available memory, without bringing back the over heads of a disk-centric architecture.

The so-called anti-caching approach works by evicting the least recently used data from memory to disk when there is not enough memory, and loading it back into memory when it is accessed again in the future.
This is similar to what operating systems do with virtual memory and swap files, but the database can manage memory more efficiently than the OS, as it can work at the granularity of individual records rather than entire memory pages.
This approach still requires indexes to fit entirely in memory, though (like the Bitcask example at the beginning of the chapter).

Further changes to storage engine design will probably be needed if non-volatile memory (NVM) technologies become more widely adopted.
At present, this is a new area of research, but it is worth keeping an eye on in the future.

### MySQL

[MySQL Server](/docs/CS/DB/MySQL/MySQL.md), the world's most popular open source database, and MySQL Cluster, a real-time, open source transactional database.

### Redis

[Redis](/docs/CS/DB/Redis/Redis.md) is an open source (BSD licensed), in-memory data structure store, used as a database, cache, and message broker.

### LevelDB

[LevelDB](/docs/CS/DB/LevelDB/LevelDB.md) is a fast key-value storage library written at Google that provides an ordered mapping from string keys to string values.
LevelDB is a widely used key-value store based on [LSMtrees](/docs/CS/Algorithms/LSM.md) that is inspired by [BigTable](/docs/CS/Distributed/Bigtable.md).
LevelDB supports range queries, snapshots, and other features that are useful in modern applications.

## Indexes

[Indexes](/docs/CS/DB/Index.md)

A *primary key* uniquely identifies one row in a relational table, or one document in a document database, or one vertex in a graph database.
Other records in the database can refer to that row/document/vertex by its primary key (or ID), and the index is used to resolve such references.

It is also very common to have *secondary indexes*.
In relational databases, you can create several secondary indexes on the same table using the CREATE INDEX command, and they are often crucial for performing joins efficiently.
A secondary index can easily be constructed from a key-value index.
The main difference is that keys are not unique; i.e., there might be many rows (documents, vertices) with the same key.
This can be solved in two ways: either by making each value in the index a list of matching row identifiers (like a postings list in a full-text index) or by making each key unique by appending a row identifier to it.
Either way, both B-trees and log-structured indexes can be used as secondary indexes.

### Storing values within the index

The key in an index is the thing that queries search for, but the value can be one of two things: it could be the actual row (document, vertex) in question, or it could be a reference to the row stored elsewhere.
In the latter case, the place where rows are stored is known as a heap file, and it stores data in no particular order (it may be append-only, or it may keep track of deleted rows in order to overwrite them with new data later).
The heap file approach is common because it avoids duplicating data when multiple secondary indexes are present: each index just references a location in the heap file, and the actual data is kept in one place.

When updating a value without changing the key, the heap file approach can be quite efficient: the record can be overwritten in place, provided that the new value is not larger than the old value.
The situation is more complicated if the new value is larger, as it probably needs to be moved to a new location in the heap where there is enough space.
In that case, either all indexes need to be updated to point at the new heap location of the record, or a forwarding pointer is left behind in the old heap location.

In some situations, the extra hop from the index to the heap file is too much of a performance penalty for reads, so it can be desirable to store the indexed row directly within an index.
This is known as a clustered index.
For example, in MySQL’s InnoDB storage engine, the primary key of a table is always a clustered index, and secondary indexes refer to the primary key (rather than a heap file location).
In SQL Server, you can specify one clustered index per table.
A compromise between a clustered index (storing all row data within the index) and a nonclustered index (storing only references to the data within the index) is known as a covering index or index with included columns, which stores some of a table’s columns within the index.
This allows some queries to be answered by using the index alone (in which case, the index is said to cover the query).

As with any kind of duplication of data, clustered and covering indexes can speed up reads, but they require additional storage and can add overhead on writes.
Databases also need to go to additional effort to enforce transactional guarantees, because applications should not see inconsistencies due to the duplication.

### Multi-column indexes

The indexes discussed so far only map a single key to a value.
That is not sufficient if we need to query multiple columns of a table (or multiple fields in a document) simultaneously.
The most common type of multi-column index is called a concatenated index, which simply combines several fields into one key by appending one column to another (the index definition specifies in which order the fields are concatenated).
This is like an old-fashioned paper phone book, which provides an index from (lastname, firstname) to phone number.
Due to the sort order, the index can be used to find all the people with a particular last name, or all the people with a particular lastnamefirstname combination.
However, the index is useless if you want to find all the people with a particular first name.
Multi-dimensional indexes are a more general way of querying several columns at once, which is particularly important for geospatial data.
For example, a restaurantsearch website may have a database containing the latitude and longitude of each restaurant.
When a user is looking at the restaurants on a map, the website needs to search for all the restaurants within the rectangular map area that the user is currently viewing.
This requires a two-dimensional range query like the following:

```
SELECT * FROM restaurants WHERE latitude > 51.4946 AND latitude < 51.5079 AND longitude > -0.1162 AND longitude < -0.1004;
```

A standard B-tree or LSM-tree index is not able to answer that kind of query efficiently: it can give you either all the restaurants in a range of latitudes (but at any longitude), or all the restaurants in a range of longitudes (but anywhere between the North and South poles), but not both simultaneously.

One option is to translate a two-dimensional location into a single number using a space-filling curve, and then to use a regular B-tree index.
More commonly, specialized spatial indexes such as R-trees are used.
For example, PostGIS implements geospatial indexes as R-trees using PostgreSQL’s Generalized Search Tree indexing facility.
We don’t have space to describe R-trees in detail here, but there is plenty of literature on them.

An interesting idea is that multi-dimensional indexes are not just for geographic locations.
For example, on an ecommerce website you could use a three-dimensional index on the dimensions (red, green, blue) to search for products in a certain range of colors, or in a database of weather observations you could have a two-dimensional index on (date, temperature) in order to efficiently search for all the observations during the year 2013 where the temperature was between 25 and 30.
With a onedimensional index, you would have to either scan over all the records from 2013 (regardless of temperature) and then filter them by temperature, or vice versa.
A 2D index could narrow down by timestamp and temperature simultaneously.
This technique is used by HyperDex.

### Full-text search and fuzzy indexes

All the indexes discussed so far assume that you have exact data and allow you to query for exact values of a key, or a range of values of a key with a sort order.
What they don’t allow you to do is search for similar keys, such as misspelled words.
Such fuzzy querying requires different techniques.

For example, full-text search engines commonly allow a search for one word to be expanded to include synonyms of the word, to ignore grammatical variations of words, and to search for occurrences of words near each other in the same document, and support various other features that depend on linguistic analysis of the text.
To cope with typos in documents or queries, Lucene is able to search text for words within a certain edit distance (an edit distance of 1 means that one letter has been added, removed, or replaced).

As mentioned in “Making an LSM-tree out of SSTables” on page 78, Lucene uses a SSTable-like structure for its term dictionary.
This structure requires a small inmemory index that tells queries at which offset in the sorted file they need to look for a key.
In LevelDB, this in-memory index is a sparse collection of some of the keys, but in Lucene, the in-memory index is a finite state automaton over the characters in the keys, similar to a trie.
This automaton can be transformed into a Levenshtein automaton, which supports efficient search for words within a given edit distance.

Other fuzzy search techniques go in the direction of document classification and machine learning. See an information retrieval textbook for more detail.

## Links

## References

1. [NoSQL Database Systems - A Survey and Decision Guidance](https://www.baqend.com/files/nosql-survey.pdf)
