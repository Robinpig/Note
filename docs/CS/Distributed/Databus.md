# Databus

Databus 是 LinkedIn 在 2012 年公开的**变更数据捕获（Change Data Capture, CDC）**平台，负责从源数据库（Oracle / MySQL 等）捕获数据变更，以**低延迟、有序、可重放**的方式发布给下游消费者。它是 LinkedIn 在通用日志系统 Kafka 成熟之前，内部解决"数据库变更如何可靠流向搜索、社交图、缓存等下游"的关键基础设施。

Databus 与 [Wormhole](/docs/CS/Distributed/Wormhole.md)（跨 region 的 pub-sub）定位互补：Databus 侧重"单集群内、从数据库到下游的变更流"，Wormhole 侧重"跨 region 的事件复制"；两者都属于 [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md) 语境下"数据如何被复制与流动"的工程答案。

## Two Capabilities: Bootstrap and Stream

Databus 的核心设计是**把"全量"和"增量"统一成一条有序流**：

- **Bootstrap（引导）**：一个新消费者接入时，先拉取源表的**全量快照**，拿到一个一致的起始位点；随后无缝切换到**增量流**，从快照位点之后继续消费。这样新消费者无需从"时间起点"重放，也不会漏掉快照与增量之间的变更。
- **增量变更流**：解析源数据库的 redo log / binlog，把每行变更（insert/update/delete）序列化成事件，按源**有序**发布。消费语义通常也是 at-least-once，依赖消费者幂等。

## Design Points

- **低延迟**：捕获到发布之间的延迟控制在秒级甚至更低，远快于"批量 ETL 定时抽数"，让下游（搜索索引、缓存、数仓）近乎实时地反映源库变化。
- **多消费者、扇出**：一份源库变更可被多个独立下游同时消费，互不阻塞——典型的发布订阅扇出，与 [Dynamo](/docs/CS/Distributed/Dynamo.md) 的"一个写被多个副本看到"在"一对多扩散"上思路相通。
- **与 Kafka 的关系**：Kafka 后来在 LinkedIn 承担了大部分通用日志/事件流职责；Databus 专注"数据库变更的语义化捕获 + bootstrap"，是 CDC 这一细分领域的专用方案。许多现代 CDC（Debezium 等）沿用了 Databus 的 bootstrap + stream 分层思想。

## Why CDC Instead of Dual Writes

如果没有 CDC，业务代码需要在"写数据库"的同时"写下游"（双写），但双写在故障时极易出现"库成了、下游没成"或反之的不一致。CDC 把变更捕获从**应用代码**下沉到**数据库日志**，保证"下游看到的就是数据库真实提交的变更"，从根本上消除双写不一致。这与 [Consensus/Consensus.md](/docs/CS/Distributed/Consensus/Consensus.md) 里"把一致性交给可靠的复制/提交协议"的工程哲学一致。

## Links

- [Wormhole](/docs/CS/Distributed/Wormhole.md)
- [PNUTS](/docs/CS/Distributed/PNUTS.md)
- [Dynamo](/docs/CS/Distributed/Dynamo.md)
- [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md)

## References

- All Aboard the Databus! LinkedIn's Scalable Consistent Change Data Capture Platform (LinkedIn, 2012)
- Article: https://engineering.linkedin.com/research/2012/all-aboard-the-databus-linkedlns-scalable-consistent-change-data-capture-platform
