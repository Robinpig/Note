## Introduction

In the harsh reality of data systems, many things can go wrong:

- The database software or hardware may fail at any time (including in the middle of a write operation).
- The application may crash at any time (including halfway through a series of operations).
- Interruptions in the network can unexpectedly cut off the application from the database, or one database node from another.
- Several clients may write to the database at the same time, overwriting each other’s changes.
- A client may read data that doesn’t make sense because it has only partially been updated.
- Race conditions between clients can cause surprising bugs.

*Transactions* have been the mechanism of choice for simplifying these issues.
A transaction is a way for an application to group several reads and writes together into a logical unit.
Conceptually, all the reads and writes in a transaction are executed as one operation: either the entire transaction succeeds (*commit*) or it fails (*abort*, *rollback*).
If it fails, the application can safely retry.
With transactions, error handling becomes much simpler for an application, because it doesn’t need to worry about partial failure—i.e., the case where some operations succeed and some fail (for whatever reason).

Transactions are created to **simplify the programming model** for applications that access the database.
By using transactions, the application is free to ignore certain potential error scenarios and concurrency issues, because the database takes care of them instead (we call these *safety guarantees*).

Not every application needs transactions, and sometimes there are advantages to weakening transactional guarantees or abandoning them entirely (for example, to achieve higher performance or higher availability). Some safety properties can be achieved without transactions.

## ACID

The safety guarantees provided by transactions are often described by the wellknown acronym **ACID**, which stands for *Atomicity*, *Consistency*, *Isolation*, and *Durability*.
In practice, one database’s implementation of ACID does not equal another’s implementation.
For example, there is a lot of ambiguity around the meaning of isolation.
Today, when a system claims to be “ACID compliant,” it’s unclear what guarantees you can actually expect.
ACID has unfortunately become mostly a marketing term.
(Systems that do not meet the ACID criteria are sometimes called **BASE**, which stands for *Basically Available*, *Soft state*, and *Eventual consistency*.
This is even more vague than the definition of ACID.
It seems that the only sensible definition of BASE is “not ACID”; i.e., it can mean almost anything you want.)

### The Meaning of ACID

#### Atomicity

In the context of ACID, atomicity is not about concurrency.
It does not describe what happens if several processes try to access the same data at the same time, because that is covered under the letter I, for isolation.

Rather, ACID atomicity describes what happens if a client wants to make several writes, but a fault occurs after some of the writes have been processed—for example, a process crashes, a network connection is interrupted, a disk becomes full, or some integrity constraint is violated.
If the writes are grouped together into an atomic transaction, and the transaction cannot be completed (committed) due to a fault, then the transaction is aborted and the database must discard or undo any writes it has made so far in that transaction.

Without atomicity, if an error occurs partway through making multiple changes, it’s difficult to know which changes have taken effect and which haven’t.
The application could try again, but that risks making the same change twice, leading to duplicate or incorrect data.
Atomicity simplifies this problem: if a transaction was aborted, the application can be sure that it didn’t change anything, so it can safely be retried.
**The ability to abort a transaction on error and have all writes from that transaction discarded is the defining feature of ACID atomicity.**

#### Consistency

this idea of consistency depends on the application’s notion of invariants, and it’s the application’s responsibility to define its transactions correctly so that they preserve consistency.
This is not something that the database can guarantee: if you write bad data that violates your invariants, the database can’t stop you.
(Some specific kinds of invariants can be checked by the database, for example using foreign key constraints or uniqueness constraints.
However, in general, the application defines what data is valid or invalid—the database only stores it.)

Atomicity, isolation, and durability are properties of the database, whereas consistency (in the ACID sense) is a property of the application.
**The application may rely on the database’s atomicity and isolation properties in order to achieve consistency, but it’s not up to the database alone.**
Thus, the letter C doesn’t really belong in ACID.

#### Isolation

Most databases are accessed by several clients at the same time.
That is no problem if they are reading and writing different parts of the database, but if they are accessing the same database records, you can run into concurrency problems (race conditions).

Isolation in the sense of ACID means that concurrently executing transactions are isolated from each other: they cannot step on each other’s toes.
The classic database textbooks formalize isolation as serializability, which means that each transaction can pretend that it is the only transaction running on the entire database.
The database ensures that when the transactions have committed, the result is the same as if they had run serially (one after another), even though in reality they may have run concurrently.

However, in practice, serializable isolation is rarely used, because it carries a performance penalty.
Some popular databases, such as Oracle 11g, don’t even implement it.
In Oracle there is an isolation level called “serializable,” but it actually implements something called *snapshot isolation*, which is a weaker guarantee than serializability.

#### Durability

The purpose of a database system is to provide a safe place where data can be stored without fear of losing it.
Durability is the promise that once a transaction has committed successfully, any data it has written will not be forgotten, even if there is a hardware fault or the database crashes.

In a single-node database, durability typically means that the data has been written to nonvolatile storage such as a hard drive or SSD.
It usually also involves a write-ahead log or similar, which allows recovery in the event that the data structures on disk are corrupted.
In a replicated database, durability may mean that the data has been successfully copied to some number of nodes.
In order to provide a durability guarantee, a database must wait until these writes or replications are complete before reporting a transaction as successfully committed.

Perfect durability does not exist: if all your hard disks and all your backups are destroyed at the same time, there’s obviously nothing your database can do to save you.

### Multi-Object Operations

In ACID, atomicity and isolation describe what the database should do if a client makes several writes within the same transaction.
Those assume that you want to modify several objects (rows, documents, records) at once. Such *multi-object transactions* are often needed if several pieces of data need to be kept in sync.

Multi-object transactions require some way of determining which read and write operations belong to the same transaction.
In relational databases, that is typically done based on the client’s TCP connection to the database server: on any particular connection, everything between a BEGIN TRANSACTION and a COMMIT statement is considered to be part of the same transaction.

On the other hand, many nonrelational databases don’t have such a way of grouping operations together.
Even if there is a multi-object API (for example, a key-value store may have a multi-put operation that updates several keys in one operation),
that doesn’t necessarily mean it has transaction semantics: the command may succeed for some keys and fail for others, leaving the database in a partially updated state.

Many distributed datastores have abandoned multi-object transactions because they are difficult to implement across partitions, and they can get in the way in some scenarios where very high availability or performance is required.
However, there is nothing that fundamentally prevents transactions in a distributed database.

There are some use cases in which single-object inserts, updates, and deletes are sufficient.
However, in many other cases writes to several different objects need to be coordinated:

- In a relational data model, a row in one table often has a foreign key reference to a row in another table. (Similarly, in a graph-like data model, a vertex has edges to other vertices.)
  Multi-object transactions allow you to ensure that these references remain valid: when inserting several records that refer to one another, the foreign keys have to be correct and up to date, or the data becomes nonsensical.
- In a document data model, the fields that need to be updated together are often within the same document, which is treated as a single object—no multi-object transactions are needed when updating a single document.
  However, document databases lacking join functionality also encourage denormalization.
  When denormalized information needs to be updated, you need to update several documents in one go.
  Transactions are very useful in this situation to prevent denormalized data from going out of sync.
- In databases with secondary indexes (almost everything except pure key-value stores), the indexes also need to be updated every time you change a value.
  These indexes are different database objects from a transaction point of view: for example, without transaction isolation, it’s possible for a record to appear in one index but not another, because the update to the second index hasn’t happened yet.

Such applications can still be implemented without transactions.
**However, error handling becomes much more complicated without atomicity, and the lack of isolation can cause concurrency problems.**

### Handling errors and aborts

A key feature of a transaction is that it can be aborted and safely retried if an error
occurred. ACID databases are based on this philosophy: if the database is in danger of violating its guarantee of atomicity, isolation, or durability, it would rather aban‐
don the transaction entirely than allow it to remain half-finished.

Not all systems follow that philosophy, though.
In particular, datastores with leaderless replication work much more on a “best effort” basis, which could be summarized as “the database will do as much as it can, and if it runs into an error,
it won’t undo something it has already done”—so it’s the application’s responsibility to recover from errors.

Although retrying an aborted transaction is a simple and effective error handling mechanism, it isn’t perfect:

- If the transaction actually succeeded, but the network failed while the server tried to acknowledge the successful commit to the client (so the client thinks it failed),
  then retrying the transaction causes it to be performed twice—unless you have an additional application-level deduplication mechanism in place.
- If the error is due to overload, retrying the transaction will make the problem worse, not better.
  To avoid such feedback cycles, you can limit the number of retries, use exponential backoff, and handle overload-related errors differently from other errors (if possible).
- It is only worth retrying after transient errors (for example due to deadlock, isolation violation, temporary network interruptions, and failover); after a permanent error (e.g., constraint violation) a retry would be pointless.
- If the transaction also has side effects outside of the database, those side effects may happen even if the transaction is aborted.
  For example, if you’re sending an email, you wouldn’t want to send the email again every time you retry the transaction.
  If you want to make sure that several different systems either commit or abort together, two-phase commit can help.
- If the client process fails while retrying, any data it was trying to write to the
  database is lost.

## Isolation Levels

If two transactions don’t touch the same data, they can safely be run in parallel, because neither depends on the other.
Concurrency issues (race conditions) only come into play when one transaction reads data that is concurrently modified by another transaction, or when two transactions try to simultaneously modify the same data.
Concurrency bugs are hard to find by testing, because such bugs are only triggered when you get unlucky with the timing.
Such timing issues might occur very rarely, and are usually difficult to reproduce.
Concurrency is also very difficult to reason about, especially in a large application where you don’t necessarily know which other pieces of code are accessing the database.
Application development is difficult enough if you just have one user at a time; having many concurrent users makes it much harder still, because any piece of data could unexpectedly change at any time.
For that reason, databases have long tried to hide concurrency issues from application developers by providing transaction isolation.
In theory, isolation should make your life easier by letting you pretend that no concurrency is happening: serializable isolation means that the database guarantees that transactions have the same effect as if they ran serially (i.e., one at a time, without any concurrency).
In practice, isolation is unfortunately not that simple. Serializable isolation has a performance cost, and many databases don’t want to pay that price.
It’s therefore common for systems to use weaker levels of isolation, which protect against some concurrency issues, but not all.
Those levels of isolation are much harder to understand, and they can lead to subtle bugs, but they are nevertheless used in practice.

Concurrency bugs caused by weak transaction isolation are not just a theoretical problem.
They have caused substantial loss of money, led to investigation by financial auditors, and caused customer data to be corrupted.
A popular comment on revelations of such problems is “Use an ACID database if you’re handling financial data!”—but that misses the point.
Even many popular relational database systems (which are usually considered “ACID”) use weak isolation, so they wouldn’t necessarily have prevented these bugs from occurring.


| Isolation level  | Dirty Read         | Non-Repeatable Read | Phantom Read       |
| ------------------ | -------------------- | --------------------- | -------------------- |
| READ-UNCOMMITTED | :white_check_mark: | :white_check_mark:  | :white_check_mark: |
| READ-COMMITTED   | :x:                | :white_check_mark:  | :white_check_mark: |
| REPEATABLE-READ  | :x:                | :x:                 | :white_check_mark: |
| SERIALIZABLE     | :x:                | :x:                 | :x:                |

### Read Committed

The most basic level of transaction isolation is read committed.v It makes two guarantees:

1. When reading from the database, you will only see data that has been committed (no *dirty reads*).
2. When writing to the database, you will only overwrite data that has been committed (no *dirty writes*).

> Some databases support an even weaker isolation level called *read uncommitted*. It prevents dirty writes, but does not prevent dirty reads.

#### No dirty reads

Imagine a transaction has written some data to the database, but the transaction has not yet committed or aborted. Can another transaction see that uncommitted data?
<br>
If yes, that is called a *dirty read*
Transactions running at the read committed isolation level must prevent dirty reads.
This means that any writes by a transaction only become visible to others when that transaction commits (and then all of its writes become visible at once).
This is illustrated in Figure 4, where user 1 has set x = 3, but user 2’s get x still returns the old value, 2, while user 1 has not yet committed.

<div style="text-align: center;">

![Fig.8. Dirty reads](img/Dirty-Reads.png)

</div>

<p style="text-align: center;">
Fig.8. No dirty reads: user 2 sees the new value for x only after user 1’s transaction has committed.
</p>

There are a few reasons why it’s useful to prevent dirty reads:

- If a transaction needs to update several objects, a dirty read means that another transaction may see some of the updates but not others.
  Seeing the database in a partially updated state is confusing to users and may cause other transactions to take incorrect decisions.
- If a transaction aborts, any writes it has made need to be rolled back.
  If the database allows dirty reads, that means a transaction may see data that is later rolled back—i.e., which is never actually committed to the database.
  Reasoning about the consequences quickly becomes mind-bending.

#### No dirty writes

What happens if two transactions concurrently try to update the same object in a database?
We don’t know in which order the writes will happen, but we normally assume that the later write overwrites the earlier write.
However, what happens if the earlier write is part of a transaction that has not yet committed, so the later write overwrites an uncommitted value?
<br>
This is called a *dirty write*.
Transactions running at the read committed isolation level must prevent dirty writes, usually by delaying the second write until the first write’s transaction has committed or aborted.

By preventing dirty writes, this isolation level avoids some kinds of concurrency problems:

- If transactions update multiple objects, dirty writes can lead to a bad outcome.
  For example, consider Figure 7-5, which illustrates a used car sales website on which two people, Alice and Bob, are simultaneously trying to buy the same car.
  Buying a car requires two database writes: the listing on the website needs to be updated to reflect the buyer, and the sales invoice needs to be sent to the buyer.
  In the case of Figure 7-5, the sale is awarded to Bob (because he performs the winning update to the listings table), but the invoice is sent to Alice (because she performs the winning update to the invoices table).
  Read committed prevents such mishaps.
- However, read committed does not prevent the race condition between two counter increments in Figure 7-1.
  In this case, the second write happens after the first transaction has committed, so it’s not a dirty write.
  It’s still incorrect, but for a different reason—in “*Preventing Lost Updates*”.

<div style="text-align: center;">

![Fig.8. Dirty writes](img/Dirty-Writes.png)

</div>

<p style="text-align: center;">
Fig.8. With dirty writes, conflicting writes from different transactions can be mixed up.
</p>

#### Implementing read committed

Read committed is a very popular isolation level. It is the default setting in Oracle 11g, PostgreSQL, SQL Server 2012, MemSQL, and many other databases.

Most commonly, databases prevent dirty writes by using row-level locks: when a transaction wants to modify a particular object (row or document), it must first acquire a lock on that object.
It must then hold that lock until the transaction is committed or aborted.
Only one transaction can hold the lock for any given object; if another transaction wants to write to the same object, it must wait until the first transaction is committed or aborted before it can acquire the lock and continue.
This locking is done automatically by databases in read committed mode (or stronger isolation levels).

How do we prevent dirty reads?
<br>
One option would be to use the same lock, and to require any transaction that wants to read an object to briefly acquire the lock and then release it again immediately after reading.
This would ensure that a read couldn’t happen while an object has a dirty, uncommitted value (because during that time the lock would be held by the transaction that has made the write).
<br>
However, the approach of requiring read locks does not work well in practice, because one long-running write transaction can force many read-only transactions to wait until the long-running transaction has completed.
This harms the response time of read-only transactions and is bad for operability: a slowdown in one part of an application can have a knock-on effect in a completely different part of the application, due to waiting for locks.

### Snapshot Isolation and Repeatable Read

However, there are still plenty of ways in which you can have concurrency bugs when using read committed isolation.
For example, Figure 7-6 illustrates a problem that can occur with read committed.

<div style="text-align: center;">

![Fig.8. Read skew](img/Read-Skew.png)

</div>

<p style="text-align: center;">
Fig.8. Read skew: Alice observes the database in an inconsistent state.
</p>

Say Alice has $1,000 of savings at a bank, split across two accounts with $500 each.
Now a transaction transfers $100 from one of her accounts to the other.
If she is unlucky enough to look at her list of account balances in the same moment as that transaction is being processed,
she may see one account balance at a time before the incoming payment has arrived (with a balance of $500), and the other account after the outgoing transfer has been made (the new balance being $400).
To Alice it now appears as though she only has a total of $900 in her accounts—it seems that $100 has vanished into thin air.

This anomaly is called a *nonrepeatable read* or *read skew*: if Alice were to read the balance of account 1 again at the end of the transaction, she would see a different value ($600) than she saw in her previous query.
Read skew is considered acceptable under read committed isolation: the account balances that Alice saw were indeed committed at the time when she read them.

In Alice’s case, this is not a lasting problem, because she will most likely see consistent account balances if she reloads the online banking website a few seconds later.
<br>
However, some situations cannot tolerate such temporary inconsistency:

- Backups
  Taking a backup requires making a copy of the entire database, which may take hours on a large database.
  During the time that the backup process is running, writes will continue to be made to the database.
  Thus, you could end up with some parts of the backup containing an older version of the data, and other parts containing a newer version.
  If you need to restore from such a backup, the inconsistencies (such as disappearing money) become permanent.
- Analytic queries and integrity checks
  Sometimes, you may want to run a query that scans over large parts of the database.
  Such queries are common in analytics, or may be part of a periodic integrity check that everything is in order (monitoring for data corruption).
  These queries are likely to return nonsensical results if they observe parts of the database at different points in time.

*Snapshot isolation* is the most common solution to this problem.
The idea is that each transaction reads from a *consistent snapshot* of the database—that is, the transaction sees all the data that was committed in the database at the start of the transaction.
Even if the data is subsequently changed by another transaction, each transaction sees only the old data from that particular point in time.
Snapshot isolation is a boon for long-running, read-only queries such as backups and analytics.
It is very hard to reason about the meaning of a query if the data on which it operates is changing at the same time as the query is executing.
When a transaction can see a consistent snapshot of the database, frozen at a particular point in time, it is much easier to understand.

Snapshot isolation is a useful isolation level, especially for read-only transactions.
However, many databases that implement it call it by different names.
In Oracle it is called *serializable*, and in PostgreSQL and MySQL it is called *repeatable read*.

#### Implementing snapshot isolation

Like read committed isolation, implementations of snapshot isolation typically use write locks to prevent dirty writes, which means that a transaction that makes a write can block the progress of another transaction that writes to the same object. However, reads do not require any locks.
From a performance point of view, a key principle of snapshot isolation is *readers never block writers, and writers never block readers*.
This allows a database to handle long-running read queries on a consistent snapshot at the same time as processing writes normally, without any lock contention between the two.

To implement snapshot isolation, databases use a generalization of the mechanism we saw for preventing dirty reads in Figure 7-4.
The database must potentially keep several different committed versions of an object, because various in-progress transactions may need to see the state of the database at different points in time.
Because it maintains several versions of an object side by side, this technique is known as *multiversion concurrency control* (MVCC).

If a database only needed to provide read committed isolation, but not snapshot isolation, it would be sufficient to keep two versions of an object: the committed version and the overwritten-but-not-yet-committed version.
However, storage engines that support snapshot isolation typically use MVCC for their read committed isolation level as well.
A typical approach is that read committed uses a separate snapshot for each query, while snapshot isolation uses the same snapshot for an entire transaction.

Figure 7-7 illustrates how MVCC-based snapshot isolation is implemented in PostgreSQL (other implementations are similar).
When a transaction is started, it is given a unique, always-increasingvii transaction ID (txid).
Whenever a transaction writes anything to the database, the data it writes is tagged with the transaction ID of the writer.

<div style="text-align: center;">

![Fig.8. Implementing snapshot isolation using multi-version objects](img/MVCC.png)

</div>

<p style="text-align: center;">
Fig.8. Implementing snapshot isolation using multi-version objects.
</p>

Each row in a table has a created_by field, containing the ID of the transaction that inserted this row into the table.
Moreover, each row has a deleted_by field, which is initially empty.
If a transaction deletes a row, the row isn’t actually deleted from the database, but it is marked for deletion by setting the deleted_by field to the ID of the transaction that requested the deletion.
At some later time, when it is certain that no transaction can any longer access the deleted data, a garbage collection process in the database removes any rows marked for deletion and frees their space.

An update is internally translated into a delete and a create.
For example, in Figure 7-7, transaction 13 deducts $100 from account 2, changing the balance from $500 to $400. The accounts table now actually contains two rows for account 2: a row with a balance of $500 which was marked as deleted by transaction 13, and a row with a balance of $400 which was created by transaction 13.

When a transaction reads from the database, transaction IDs are used to decide which objects it can see and which are invisible.
By carefully defining visibility rules, the database can present a consistent snapshot of the database to the application.
<br>
This works as follows:

1. At the start of each transaction, the database makes a list of all the other transactions that are in progress (not yet committed or aborted) at that time.
   Any writes that those transactions have made are ignored, even if the transactions subsequently commit.
2. Any writes made by aborted transactions are ignored.
3. Any writes made by transactions with a later transaction ID (i.e., which started after the current transaction started) are ignored, regardless of whether those transactions have committed.
4. All other writes are visible to the application’s queries.

These rules apply to both creation and deletion of objects.
In Figure 7-7, when transaction 12 reads from account 2, it sees a balance of $500 because the deletion of the $500 balance was made by transaction 13
(according to rule 3, transaction 12 cannot see a deletion made by transaction 13), and the creation of the $400 balance is not yet visible (by the same rule).
Put another way, an object is visible if both of the following conditions are true:

- At the time when the reader’s transaction started, the transaction that created the object had already committed.
- The object is not marked for deletion, or if it is, the transaction that requested deletion had not yet committed at the time when the reader’s transaction started.

A long-running transaction may continue using a snapshot for a long time, continuing to read values that (from other transactions’ point of view) have long been overwritten or deleted.
By never updating values in place but instead creating a new version every time a value is changed, the database can provide a consistent snapshot while incurring only a small overhead.

#### Indexes and snapshot isolation

How do indexes work in a multi-version database? One option is to have the index simply point to all versions of an object and require an index query to filter out any object versions that are not visible to the current transaction.
When garbage collection removes old object versions that are no longer visible to any transaction, the corresponding index entries can also be removed.

In practice, many implementation details determine the performance of multiversion concurrency control.
For example, PostgreSQL has optimizations for avoiding index updates if different versions of the same object can fit on the same page.

Another approach is used in CouchDB, Datomic, and LMDB.
Although they also use B-trees, they use an append-only/copy-on-write variant that does not overwrite pages of the tree when they are updated, but instead creates a new copy of each modified page.
Parent pages, up to the root of the tree, are copied and updated to point to the new versions of their child pages.
Any pages that are not affected by a write do not need to be copied, and remain immutable.

With append-only B-trees, every write transaction (or batch of transactions) creates a new B-tree root, and a particular root is a consistent snapshot of the database at the point in time when it was created.
There is no need to filter out objects based on transaction IDs because subsequent writes cannot modify an existing B-tree; they can only create new tree roots.
However, this approach also requires a background process for compaction and garbage collection.

### Lost Updates

There are several other interesting kinds of conflicts that can occur between concurrently writing transactions.
The best known of these is the lost update problem, illustrated in Figure 7-1 with the example of two concurrent counter increments.
The lost update problem can occur if an application reads some value from the database, modifies it, and writes back the modified value (a read-modify-write cycle).
If two transactions do this concurrently, one of the modifications can be lost, because the second write does not include the first modification. (We sometimes say that the later write clobbers the earlier write.)
This pattern occurs in various different scenarios:

- Incrementing a counter or updating an account balance (requires reading the current value, calculating the new value, and writing back the updated value)
- Making a local change to a complex value, e.g., adding an element to a list within a JSON document (requires parsing the document, making the change, and writing back the modified document)
- Two users editing a wiki page at the same time, where each user saves their changes by sending the entire page contents to the server, overwriting whatever is currently in the database

#### Atomic write operations

Many databases provide atomic update operations, which remove the need to implement read-modify-write cycles in application code.
They are usually the best solution if your code can be expressed in terms of those operations.
For example, the following instruction is concurrency-safe in most relational databases:

```sql
UPDATE counters SET value = value + 1 WHERE key = 'foo';
```

Similarly, document databases such as MongoDB provide atomic operations for making local modifications to a part of a JSON document, and Redis provides atomic operations for modifying data structures such as priority queues.
Not all writes can easily be expressed in terms of atomic operations—for example, updates to a wiki page involve arbitrary text editingviii—but in situations where atomic operations can be used, they are usually the best choice.

Atomic operations are usually implemented by taking an exclusive lock on the object when it is read so that no other transaction can read it until the update has been applied.
This technique is sometimes known as cursor stability.
Another option is to simply force all atomic operations to be executed on a single thread.

Unfortunately, object-relational mapping frameworks make it easy to accidentally write code that performs unsafe read-modify-write cycles instead of using atomic operations provided by the database.
That’s not a problem if you know what you are doing, but it is potentially a source of subtle bugs that are difficult to find by testing.

#### Explicit locking

Another option for preventing lost updates, if the database’s built-in atomic opera‐
tions don’t provide the necessary functionality, is for the application to explicitly lock
objects that are going to be updated. Then the application can perform a readmodify-write cycle, and if any other transaction tries to concurrently read the same
object, it is forced to wait until the first read-modify-write cycle has completed.
For example, consider a multiplayer game in which several players can move the
same figure concurrently. In this case, an atomic operation may not be sufficient,
because the application also needs to ensure that a player’s move abides by the rules
of the game, which involves some logic that you cannot sensibly implement as a data‐
base query. Instead, you may use a lock to prevent two players from concurrently
moving the same piece, as illustrated in Example 7-1.

```sql
BEGIN TRANSACTION;
SELECT * FROM figures
WHERE name = 'robot' AND game_id = 222
FOR UPDATE;
-- Check whether move is valid, then update the position
-- of the piece that was returned by the previous SELECT.
UPDATE figures SET position = 'c4' WHERE id = 1234;
COMMIT;
```

This works, but to get it right, you need to carefully think about your application logic.
It’s easy to forget to add a necessary lock somewhere in the code, and thus introduce a race condition.

#### Automatically detecting lost updates

Atomic operations and locks are ways of preventing lost updates by forcing the readmodify-write cycles to happen sequentially. An alternative is to allow them to execute
in parallel and, if the transaction manager detects a lost update, abort the transaction
and force it to retry its read-modify-write cycle.
An advantage of this approach is that databases can perform this check efficiently in
conjunction with snapshot isolation. Indeed, PostgreSQL’s repeatable read, Oracle’s
serializable, and SQL Server’s snapshot isolation levels automatically detect when a
lost update has occurred and abort the offending transaction. However, MySQL/
InnoDB’s repeatable read does not detect lost updates [23]. Some authors [28, 30]
argue that a database must prevent lost updates in order to qualify as providing snap‐
shot isolation, so MySQL does not provide snapshot isolation under this definition.
Lost update detection is a great feature, because it doesn’t require application code to
use any special database features—you may forget to use a lock or an atomic opera‐
tion and thus introduce a bug, but lost update detection happens automatically and is
thus less error-prone.

#### Compare-and-set

In databases that don’t provide transactions, you sometimes find an atomic compareand-set operation (previously mentioned in “Single-object writes” on page 230). The
purpose of this operation is to avoid lost updates by allowing an update to happen
only if the value has not changed since you last read it. If the current value does not
match what you previously read, the update has no effect, and the read-modify-write
cycle must be retried.
For example, to prevent two users concurrently updating the same wiki page, you
might try something like this, expecting the update to occur only if the content of the
page hasn’t changed since the user started editing it:
-- This may or may not be safe, depending on the database implementation
UPDATE wiki_pages SET content = 'new content'
WHERE id = 1234 AND content = 'old content';
If the content has changed and no longer matches 'old content', this update will
have no effect, so you need to check whether the update took effect and retry if neces‐
sary. However, if the database allows the WHERE clause to read from an old snapshot,
this statement may not prevent lost updates, because the condition may be true even
though another concurrent write is occurring. Check whether your database’s
compare-and-set operation is safe before relying on it.

#### Conflict resolution and replication

In replicated databases (see Chapter 5), preventing lost updates takes on another
dimension: since they have copies of the data on multiple nodes, and the data can
potentially be modified concurrently on different nodes, some additional steps need
to be taken to prevent lost updates.
Locks and compare-and-set operations assume that there is a single up-to-date copy
of the data. However, databases with multi-leader or leaderless replication usually
allow several writes to happen concurrently and replicate them asynchronously, so
they cannot guarantee that there is a single up-to-date copy of the data. Thus, techni‐
ques based on locks or compare-and-set do not apply in this context. (We will revisit
this issue in more detail in “Linearizability” on page 324.)
Instead, as discussed in “Detecting Concurrent Writes” on page 184, a common
approach in such replicated databases is to allow concurrent writes to create several
conflicting versions of a value (also known as siblings), and to use application code or
special data structures to resolve and merge these versions after the fact.
Atomic operations can work well in a replicated context, especially if they are com‐
mutative (i.e., you can apply them in a different order on different replicas, and still
get the same result). For example, incrementing a counter or adding an element to a
set are commutative operations. That is the idea behind Riak 2.0 datatypes, which
prevent lost updates across replicas. When a value is concurrently updated by differ‐
ent clients, Riak automatically merges together the updates in such a way that no
updates are lost [39].
On the other hand, the last write wins (LWW) conflict resolution method is prone to
lost updates, as discussed in “Last write wins (discarding concurrent writes)” on page
186. Unfortunately, LWW is the default in many replicated databases.

### Write Skew and Phantoms

In the previous sections we saw dirty writes and lost updates, two kinds of race condi‐
tions that can occur when different transactions concurrently try to write to the same
objects. In order to avoid data corruption, those race conditions need to be prevented
—either automatically by the database, or by manual safeguards such as using locks
or atomic write operations.
However, that is not the end of the list of potential race conditions that can occur
between concurrent writes. In this section we will see some subtler examples of
conflicts.
To begin, imagine this example: you are writing an application for doctors to manage
their on-call shifts at a hospital. The hospital usually tries to have several doctors on
call at any one time, but it absolutely must have at least one doctor on call. Doctors can give up their shifts (e.g., if they are sick themselves), provided that at least one
colleague remains on call in that shift.
Now imagine that Alice and Bob are the two on-call doctors for a particular shift.
Both are feeling unwell, so they both decide to request leave. Unfortunately, they
happen to click the button to go off call at approximately the same time. What hap‐
pens next is illustrated in Figure 7-8.

<div style="text-align: center;">

![Fig.8. Write skew](img/Write-Skew.png)

</div>

<p style="text-align: center;">
Fig.8. Example of write skew causing an application bug.
</p>

In each transaction, your application first checks that two or more doctors are cur‐
rently on call; if yes, it assumes it’s safe for one doctor to go off call. Since the data‐
base is using snapshot isolation, both checks return 2, so both transactions proceed to
the next stage. Alice updates her own record to take herself off call, and Bob updates
his own record likewise. Both transactions commit, and now no doctor is on call.
Your requirement of having at least one doctor on call has been violated.

This anomaly is called write skew [28]. It is neither a dirty write nor a lost update,
because the two transactions are updating two different objects (Alice’s and Bob’s oncall records, respectively). It is less obvious that a conflict occurred here, but it’s defi‐
nitely a race condition: if the two transactions had run one after another, the second doctor would have been prevented from going off call. The anomalous behavior was
only possible because the transactions ran concurrently.
You can think of write skew as a generalization of the lost update problem. Write
skew can occur if two transactions read the same objects, and then update some of
those objects (different transactions may update different objects). In the special case
where different transactions update the same object, you get a dirty write or lost
update anomaly (depending on the timing).

We saw that there are various different ways of preventing lost updates. With write
skew, our options are more restricted:

- Atomic single-object operations don’t help, as multiple objects are involved.
- The automatic detection of lost updates that you find in some implementations
  of snapshot isolation unfortunately doesn’t help either: write skew is not auto‐
  matically detected in PostgreSQL’s repeatable read, MySQL/InnoDB’s repeatable
  read, Oracle’s serializable, or SQL Server’s snapshot isolation level [23]. Auto‐
  matically preventing write skew requires true serializable isolation (see “Serializa‐
  bility” on page 251).
- Some databases allow you to configure constraints, which are then enforced by
  the database (e.g., uniqueness, foreign key constraints, or restrictions on a partic‐
  ular value). However, in order to specify that at least one doctor must be on call,
  you would need a constraint that involves multiple objects. Most databases do
  not have built-in support for such constraints, but you may be able to implement
  them with triggers or materialized views, depending on the database [42].
- If you can’t use a serializable isolation level, the second-best option in this case is
  probably to explicitly lock the rows that the transaction depends on. In the doc‐
  tors example, you could write something like the following:

```sql
BEGIN TRANSACTION;

SELECT * FROM doctors
    WHERE on_call = true
    AND shift_id = 1234 FOR UPDATE;
  
UPDATE doctors
    SET on_call = false
    WHERE name = 'Alice'
    AND shift_id = 1234;
  
COMMIT;
```

Here are some more examples:

- Meeting room booking system
  Say you want to enforce that there cannot be two bookings for the same meeting room at the same time.
  When someone wants to make a booking, you first check for any conflicting bookings (i.e., bookings for the same room with an overlapping time range), and if none are found, you create the meeting.
- Multiplayer game
  In Example 7-1, we used a lock to prevent lost updates (that is, making sure that two players can’t move the same figure at the same time).
  However, the lock doesn’t prevent players from moving two different figures to the same position on the board or potentially making some other move that violates the rules of the game.
  Depending on the kind of rule you are enforcing, you might be able to use a unique constraint, but otherwise you’re vulnerable to write skew.
- Claiming a username
  On a website where each user has a unique username, two users may try to create accounts with the same username at the same time.
  You may use a transaction to check whether a name is taken and, if not, create an account with that name.
  However, like in the previous examples, that is not safe under snapshot isolation.
  Fortunately, a unique constraint is a simple solution here (the second transaction that tries to register the username will be aborted due to violating the constraint).
- Preventing double-spending
  A service that allows users to spend money or points needs to check that a user doesn’t spend more than they have.
  You might implement this by inserting a tentative spending item into a user’s account, listing all the items in the account, and checking that the sum is positive.
  With write skew, it could happen that two spending items are inserted concurrently that together cause the balance to go negative, but that neither transaction notices the other.

#### Phantoms causing write skew

All of these examples follow a similar pattern:

1. A SELECT query checks whether some requirement is satisfied by searching for rows that match some search condition (there are at least two doctors on call).
2. Depending on the result of the first query, the application code decides how to continue (perhaps to go ahead with the operation, or perhaps to report an error to the user and abort).
3. If the application decides to go ahead, it makes a write (INSERT, UPDATE, or DELETE) to the database and commits the transaction.
   The effect of this write changes the precondition of the decision of step 2.
   In other words, if you were to repeat the SELECT query from step 1 after commiting the write, you would get a different result, because the write changed the set of rows matching the search condition (there is now one fewer doctor on call).

The steps may occur in a different order. For example, you could first make the write,
then the SELECT query, and finally decide whether to abort or commit based on the
result of the query.

In the case of the doctor on call example, the row being modified in step 3 was one of
the rows returned in step 1, so we could make the transaction safe and avoid write
skew by locking the rows in step 1 (SELECT FOR UPDATE).
However, the other four examples are different: they check for the absence of rows matching some search condition, and the write adds a row matching the same condition.
If the query in step 1 doesn’t return any rows, SELECT FOR UPDATE can’t attach locks to anything.

This effect, where a write in one transaction changes the result of a search query in
another transaction, is called a *phantom*.
Snapshot isolation avoids phantoms in read-only queries, but in read-write transactions like the examples we discussed, phantoms can lead to particularly tricky cases of write skew.

##### Materializing conflicts

If the problem of phantoms is that there is no object to which we can attach the locks,
perhaps we can artificially introduce a lock object into the database?
For example, in the meeting room booking case you could imagine creating a table of
time slots and rooms. Each row in this table corresponds to a particular room for a
particular time period (say, 15 minutes). You create rows for all possible combina‐
tions of rooms and time periods ahead of time, e.g. for the next six months.
Now a transaction that wants to create a booking can lock (SELECT FOR UPDATE) the
rows in the table that correspond to the desired room and time period. After it has
acquired the locks, it can check for overlapping bookings and insert a new booking as
before. Note that the additional table isn’t used to store information about the book‐
ing—it’s purely a collection of locks which is used to prevent bookings on the same
room and time range from being modified concurrently.
This approach is called materializing conflicts, because it takes a phantom and turns it
into a lock conflict on a concrete set of rows that exist in the database.

Unfortunately, it can be hard and error-prone to figure out how to materialize conflicts, and it’s ugly to let a concurrency control mechanism leak into the application data model.
For those reasons, materializing conflicts should be considered a last resort if no alternative is possible.
A serializable isolation level is much preferable in most cases.

### Serializability

Serializable isolation is usually regarded as the strongest isolation level. It guarantees
that even though transactions may execute in parallel, the end result is the same as if
they had executed one at a time, serially, without any concurrency. Thus, the database
guarantees that if the transactions behave correctly when run individually, they con‐
tinue to be correct when run concurrently—in other words, the database prevents all
possible race conditions.

Most databases that
provide serializability today use one of three techniques, which we will explore in the
rest of this chapter:

- Literally executing transactions in a serial order
- Two-phase locking, which for several decades was the only viable option
- Optimistic concurrency control techniques such as serializable snapshot isolation

#### Actual Serial Execution

The simplest way of avoiding concurrency problems is to remove the concurrency
entirely: to execute only one transaction at a time, in serial order, on a single thread.
By doing so, we completely sidestep the problem of detecting and preventing con‐
flicts between transactions: the resulting isolation is by definition serializable.

The approach of executing transactions serially is implemented in VoltDB/H-Store, Redis, and Datomic.
A system designed for single-threaded execution can sometimes perform better than a system that supports concurrency, because it can avoid the coordination overhead of locking.
However, its throughput is limited to that of a single CPU core. In order to make the most of that single thread, transactions need to be structured differently from their traditional form.

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

## BASE

(Basically Available, Soft-State, Eventually Consistent)

- Basic Availability: fulfill request, even in partial consistency.
- Soft State: abandon the consistency requirements of the ACID model pretty much completely
- Eventual Consistency: at some point in the future, data will converge to a consistent state; delayed consistency, as opposed to immediate consistency of the ACID properties.
- purely a liveness guarantee (reads eventually return the requested value); but
- does not make safety guarantees, i.e.,
- an eventually consistent system can return any value before it converges

### ACID vs. BASE trade-off

- No general answer to whether your application needs an ACID versus BASE consistency model.
- Given BASE’s loose consistency, developers need to be more knowledgeable and rigorous about consistent data if they choose a BASE store for their application.
- Planning around BASE limitations can sometimes be a major disadvantage when compared to the simplicity of ACID transactions.
- A fully ACID database is the perfect fit for use cases where data reliability and consistency are essential.

## Atomic Commit

### Two-Phase Commit

A two-phase commit protocol is an algorithm that lets all clients in a distributed system agree either to commit a transaction or abort.

TiDB

### Three-Phase Commit

### TCC

not used normally

### Paxos

### Quorum

### Saga

proxy

MySQL

## Concurrency Control

[Serializable Snapshot Isolation in PostgreSQL](https://www.drkp.net/papers/ssi-vldb12.pdf)

[Serializable, Lockless, Distributed: Isolation in CockroachDB](https://www.cockroachlabs.com/blog/serializable-lockless-distributed-isolation-cockroachdb/)

[Large-scale Incremental Processing Using Distributed Transactions and Notifications](https://www.usenix.org/legacy/event/osdi10/tech/full_papers/Peng.pdf)

### Two-Phase Locking

### Validation-Based Concurrency

### MVCC

- Multi-Version Two-Phase Locking
- Multi-Version Optimistic Concurrency Control
- Multi-Version Timestamp Ordering

## Links

- [MySQL Transaction](/docs/CS/DB/MySQL/Transaction.md)

## References

1. [ACID vs. BASE and SQL vs. NoSQL](https://marcobrambillapolimi.files.wordpress.com/2019/01/01-nosql-overview.pdf)
2. [A Critique of ANSI SQL Isolation Levels](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-95-51.pdf)
3. [Serializable Isolation for Snapshot Databases](https://courses.cs.washington.edu/courses/cse444/08au/544M/READING-LIST/fekete-sigmod2008.pdf)
4. [A Critique of ANSI SQL Isolation Levels](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-95-51.pdf)
5. [An Empirical Evaluation of In-Memory Multi-Version Concurrency Control](https://db.cs.cmu.edu/papers/2017/p781-wu.pdf)
