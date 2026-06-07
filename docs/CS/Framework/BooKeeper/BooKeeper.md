## Introduction

[Apache BookKeeper](https://bookkeeper.apache.org/) 是一个可扩展、容错且低延迟的存储服务，专为实时工作负载优化。它为构建可靠的实时应用提供了持久性、复制和强一致性等关键特性。

BookKeeper 适用于多种使用场景，包括：

|使用场景|示例|
|:--|:--|
|[WAL](https://en.wikipedia.org/wiki/Write-ahead_logging)（预写日志）|HDFS [namenode](https://hadoop.apache.org/docs/r2.5.2/hadoop-project-dist/hadoop-hdfs/HDFSHighAvailabilityWithNFS.html#BookKeeper_as_a_Shared_storage_EXPERIMENTAL)|
|[WAL](https://en.wikipedia.org/wiki/Write-ahead_logging)（预写日志）|Twitter [Manhattan](https://blog.twitter.com/engineering/en_us/a/2016/strong-consistency-in-manhattan.html)|
|[WAL](https://en.wikipedia.org/wiki/Write-ahead_logging)（预写日志）|[HerdDB](https://github.com/diennea/herddb)|
|[WAL](https://en.wikipedia.org/wiki/Write-ahead_logging)（预写日志）|[Pravega](https://github.com/pravega/pravega)|
|消息存储|[Apache Pulsar](https://pulsar.apache.org/docs/concepts-architecture-overview#persistent-storage)|
|偏移量/游标存储|[Apache Pulsar](https://pulsar.apache.org/docs/concepts-architecture-overview#persistent-storage)|
|对象/[BLOB](https://en.wikipedia.org/wiki/Binary_large_object) 存储|存储复制状态机的快照|

BookKeeper 是一种提供日志条目流（也称为记录）持久化存储的服务，这些条目按顺序组织成 ledger。BookKeeper 将存储的条目在多个服务器间进行复制。

在 BookKeeper 中：

- 日志的每个单元称为 entry（亦称 record）
- 日志条目的流称为 ledger
- 存储 ledger 条目的单个服务器称为 bookie

BookKeeper 被设计为可靠且能抵御各种故障。Bookie 可能崩溃、数据损坏或丢弃数据，但只要 ensemble 中有足够多的 bookie 正常运行，整个服务就能正确运行。

> **Entries** 包含实际写入 ledger 的数据，以及一些重要的元数据。

BookKeeper 条目是写入 [ledger](https://bookkeeper.apache.org/docs/getting-started/concepts#ledgers) 的字节序列。每个条目包含以下字段：

|字段|Java 类型|描述|
|:--|:--|:--|
|Ledger number|`long`|条目写入的 ledger ID|
|Entry number|`long`|条目的唯一 ID|
|Last confirmed (LC)|`long`|最后记录的条目 ID|
|Data|`byte[]`|条目的数据（由客户端应用写入）|
|Authentication code|`byte[]`|消息认证码，包含条目中所有其他字段|

> **Ledgers** 是 BookKeeper 中的基本存储单元。

Ledger 是条目的序列，而每个条目是一个字节序列。条目写入 ledger 的方式是：

- 顺序写入，且
- 最多一次。

这意味着 ledger 具有**只追加**语义，一旦写入 ledger 就不能修改。确定正确的写入顺序是[客户端应用](https://bookkeeper.apache.org/docs/getting-started/concepts#clients)的职责。

> **Bookies** 是处理 ledger（更具体地说是 ledger 片段）的单个 BookKeeper 服务器。Bookie 作为 ensemble 的一部分运行。

Bookie 是单个 BookKeeper 存储服务器。为了性能考虑，单个 bookie 存储 ledger 的片段，而非整个 ledger。对于任何给定的 ledger **L**，一个 ensemble 是存储 **L** 中条目的 bookie 组。

每当条目写入 ledger 时，这些条目会被条带化写入 ensemble（写入 bookie 的子集，而非所有 bookie）。

## Links

- [Apache Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md)
