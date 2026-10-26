# HyperDex

HyperDex 是 2012 年（SIGCOMM）提出的**可搜索分布式 KV 存储**，目标是解决普通分布式 KV（[Dynamo](/docs/CS/Distributed/Dynamo.md) / [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)）只能按主键查询、无法按对象属性检索的短板。它用 **hyperspace hashing（超空间哈希）** 把每个对象的多维属性映射到高维坐标空间，从而支持**等值查询、范围查询、多维联合检索**，同时保持分布式 KV 的可扩展与容错。

## Hyperspace Hashing

- 传统 KV 只对主键做哈希，次级属性查询只能全表扫或建二级索引（索引本身要维护和查询放大）。
- HyperDex 为对象的**每个属性维度**分配一个坐标；一个对象因此被定位到高维空间中的一个点。查询时指定若干维度的取值或范围，就映射成一个**子空间（subspace）**，只需联系负责该子空间的一小部分节点即可，而不是全集群广播。
- 相比"逐属性二级索引"方案，hyperspace hashing 让典型查询触达的节点数更少（理想情况下接近相关分片而非全量），在"既能按主键、又能按属性检索"之间取得平衡。

## Consistency and Cost

- HyperDex 提供**强一致**的 searchable 存储（与 Dynamo 的最终一致相对）；但多维映射意味着一次写入要更新多个维度的坐标，写入放大高于纯主键 KV。
- 节点增减时，高维空间的 rebalancing 与数据再分布比单维哈希复杂，工程代价显著。

## Position

HyperDex 是"在分布式 KV 上叠加查询能力"这一方向上的学术代表；工业界更常见的落地是用 [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md) 的二级索引 / SASI、或把 KV 与搜索引擎（Elasticsearch）组合。它与 [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md) 枢纽里的"分布式 KV"一类直接对照：KV 不止能按 key 取，还能被"搜"。

## Links

- [Dynamo](/docs/CS/Distributed/Dynamo.md)
- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md)
- [Replica](/docs/CS/Distributed/Replica.md)

## References

- HyperDex: A Distributed, Searchable Key-Value Store (Escriva, Wong, Sirer, SIGCOMM 2012)
- Paper: https://www.cs.cornell.edu/people/egs/papers/hyperdex-sigcomm.pdf
