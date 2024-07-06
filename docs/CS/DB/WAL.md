## Introduction

In computer science, write-ahead logging (WAL) is a family of techniques for providing atomicity and durability (two of the ACID properties) in database systems.
It can be seen as an implementation of the "Event Sourcing" architecture, in which the state of a system is the result of the evolution of incoming events from an initial state.
A write ahead log is an append-only auxiliary disk-resident structure used for crash and transaction recovery.
The changes are first recorded in the log, which must be written to stable storage, before the changes are written to the database.

The following features are responsible for the popularity of Write Ahead Logging:

- **Reduced Disk Writes:**<br>
  WAL reduces the amount of disk writes significantly as you only need to flush the log file to the disk when committing a transaction. This is an optimal method rather than writing every transaction directly on the disk.
- **Decreased Syncing Cost:**<br>
  Since log files accept data sequentially, the syncing cost of log data is much less as compared to that of flushing data pages. This is beneficial, especially for servers managing numerous small transactions using different parts of your data store.
- **Fast Redo Operation:**<br>
  WAL supports high-speed roll-forward recovery (REDO). This implies any modifications that were aborted in between can be recovered from the log records.
- **Accessible Data Backup:**<br>
  WAL caters to your data backup needs and also provides you with backup and point-in-time recovery. You can simply archive the WAL data and revert to any time instant that occurred prior to the latest data write.

In a system using WAL, all modifications are written to a log before they are applied. 
Usually both redo and undo information is stored in the log.

The purpose of this can be illustrated by an example. Imagine a program that is in the middle of performing some operation when the machine it is running on loses power.
Upon restart, that program might need to know whether the operation it was performing succeeded, succeeded partially, or failed.
If a write-ahead log is used, the program can check this log and compare what it was supposed to be doing when it unexpectedly lost power to what was actually done.
On the basis of this comparison, the program could decide to undo what it had started, complete what it had started, or keep things as they are.

After a certain amount of operations, the program should perform a checkpoint, writing all the changes specified in the WAL to the database and clearing the log.

WAL allows updates of a database to be done in-place. Another way to implement atomic updates is with shadow paging, which is not in-place.
The main advantage of doing updates in-place is that it reduces the need to modify indexes and block lists.

ARIES is a popular algorithm in the WAL family.

### Examples

- The log implementation in all Consensus algorithms like Zookeeper and RAFT is similar to write ahead log
- The storage implementation in [Kafka](/docs/CS/MQ/Kafka/Kafka.md) follows similar structure as that of commit logs in databases
- All the databases, including the nosql databases like Cassandra use write ahead log technique to guarantee durability

## Checkpoint

A “Checkpoint” operation transfers the Write Ahead Logging file transactions into your database.
The normal rollback contains only 2 operations namely, Reading & Writing.
However, WAL takes it a step further and adds a third operation called Checkpointing.
You can even perform a Checkpoint and Read operation concurrently which will in turn boost your database’s performance.

A Checkpoint operation must stop only when it reaches a WAL page that succeeds the end mark of any of the current read operations.
This is to prevent overwriting in the database file. Furthermore, a Checkpoint stores the WAL index to memorize how far it got.
This allows it to resume the transfer of WAL data to your database from the point where it left off in the last transfer.
A long-running Read operation can prevent a new Checkpoint from moving forward, but since every Read operation eventually ends, the Checkpoint can continue.

## Links

- [DataBases](/docs/CS/DB/DB.md)

## References

1. [WAL - Wiki](https://www.wikiwand.com/en/Write_ahead_logging)
2. [Write-Ahead Logging - SQLite](https://sqlite.org/wal.html)
