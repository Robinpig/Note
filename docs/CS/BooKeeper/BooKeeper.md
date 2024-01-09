## Introduction

[Apache BookKeeper](https://bookkeeper.apache.org/) is a scalable, fault-tolerant, and low-latency storage service optimized for real-time workloads. It offers durability, replication, and strong consistency as essentials for building reliable real-time applications.

BookKeeper is suitable for a wide variety of use cases, including:


|Use case|Example|
|:--|:--|
|[WAL](https://en.wikipedia.org/wiki/Write-ahead_logging) (write-ahead logging)|The HDFS [namenode](https://hadoop.apache.org/docs/r2.5.2/hadoop-project-dist/hadoop-hdfs/HDFSHighAvailabilityWithNFS.html#BookKeeper_as_a_Shared_storage_EXPERIMENTAL)|
|[WAL](https://en.wikipedia.org/wiki/Write-ahead_logging) (write-ahead logging)|Twitter [Manhattan](https://blog.twitter.com/engineering/en_us/a/2016/strong-consistency-in-manhattan.html)|
|[WAL](https://en.wikipedia.org/wiki/Write-ahead_logging) (write-ahead logging)|[HerdDB](https://github.com/diennea/herddb)|
|[WAL](https://en.wikipedia.org/wiki/Write-ahead_logging) (write-ahead logging)|[Pravega](https://github.com/pravega/pravega)|
|Message storage|[Apache Pulsar](https://pulsar.apache.org/docs/concepts-architecture-overview#persistent-storage)|
|Offset/cursor storage|[Apache Pulsar](https://pulsar.apache.org/docs/concepts-architecture-overview#persistent-storage)|
|Object/[BLOB](https://en.wikipedia.org/wiki/Binary_large_object) storage|Storing snapshots to replicated state machines|

BookKeeper is a service that provides persistent storage of streams of log entries—aka records—in sequences called ledgers. BookKeeper replicates stored entries across multiple servers.

In BookKeeper:

- each unit of a log is an entry (aka record)
- streams of log entries are called ledgers
- individual servers storing ledgers of entries are called bookie

BookKeeper is designed to be reliable and resilient to a wide variety of failures. Bookies can crash, corrupt data, or discard data, but as long as there are enough bookies behaving correctly in the ensemble the service as a whole will behave correctly.

> **Entries** contain the actual data written to ledgers, along with some important metadata.

BookKeeper entries are sequences of bytes that are written to [ledgers](https://bookkeeper.apache.org/docs/getting-started/concepts#ledgers). Each entry has the following fields:

|Field|Java type|Description|
|:--|:--|:--|
|Ledger number|`long`|The ID of the ledger to which the entry has been written|
|Entry number|`long`|The unique ID of the entry|
|Last confirmed (LC)|`long`|The ID of the last recorded entry|
|Data|`byte[]`|The entry's data (written by the client application)|
|Authentication code|`byte[]`|The message auth code, which includes _all_ other fields in the entry|


> **Ledgers** are the basic unit of storage in BookKeeper.

Ledgers are sequences of entries, while each entry is a sequence of bytes. Entries are written to a ledger:

- sequentially, and
- at most once.

This means that ledgers have _append-only_ semantics. Entries cannot be modified once they've been written to a ledger. Determining the proper write order is the responsibility of [client applications](https://bookkeeper.apache.org/docs/getting-started/concepts#clients).


> **Bookies** are individual BookKeeper servers that handle ledgers (more specifically, fragments of ledgers). Bookies function as part of an ensemble.

A bookie is an individual BookKeeper storage server. Individual bookies store fragments of ledgers, not entire ledgers (for the sake of performance). For any given ledger **L**, an _ensemble_ is the group of bookies storing the entries in **L**.

Whenever entries are written to a ledger, those entries are striped across the ensemble (written to a sub-group of bookies rather than to all bookies).


## Links
