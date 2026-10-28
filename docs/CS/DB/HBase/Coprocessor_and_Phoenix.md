## Introduction

本页覆盖 HBase 注入式扩展的两块：Coprocessor（把用户代码注入 RegionServer / Master 的 Observer 钩子与 Endpoint RPC）与 Phoenix（构建在 HBase 之上的 SQL 层与 JDBC 驱动、二级索引的工业级实现）。Phoenix 正是 Coprocessor 最大的生产消费者——它的查询下推与索引维护全部靠注入 RegionServer 的 Observer / Endpoint。跨行事务的边界见 [Replication](/docs/CS/DB/HBase/Replication.md) 分册。

## Coprocessors

Coprocessor 把用户代码注入 RegionServer / Master 进程，分两类：

- **Observer**：钩子。拦截读写、flush、compaction、WAL、Master 管理操作等事件点（`RegionObserver` / `RegionServerObserver` / `MasterObserver` / `WALObserver`），用于权限校验、二级索引维护、行级安全这类「随写随做」的逻辑。
- **Endpoint**：自定义 RPC 服务。客户端把聚合计算下推到数据所在节点执行，避免把全表拉回客户端。

装载点在 `hbase.coprocessor.region.classes`（「region observer 或 endpoint，默认加载到所有表，按声明顺序调用」）与 `hbase.coprocessor.master.classes` 等，另有表级/列族级属性。

> [!WARNING]
> 两个版本断点：**2.0 起**只实现 `RegionObserver` 不再足够——必须同时实现 `RegionCoprocessor` 并提供 `getRegionObserver()` 返回自身；**3.0 移除了 `hbase-protocol` 模块**，旧 Coprocessor Endpoint 的 protobuf 依赖随之断掉，升级前要重编译。Phoenix 的二级索引维护与查询下推正是构建在这套机制之上。

## Phoenix: SQL and Secondary Index

HBase 自身没有 SQL、也没有原生二级索引（见 [RowKey Design](/docs/CS/DB/HBase/RowKey_Design.md)）。[Apache Phoenix](https://phoenix.apache.org/) 是构建在 HBase 之上的 **SQL 层与 JDBC 驱动**，把「要 SQL / 要二级索引」的需求接回 HBase——它正是 Coprocessor（前文）最大的生产消费者：查询下推、索引维护都靠注入 RegionServer 的 Observer / Endpoint 实现。

- **SQL 编译为 HBase 原语**：Phoenix 把 SQL 编译成对 HBase 的 scan / get / 聚合，能下推到 RegionServer 执行，避免把全表拉回客户端；支持 JOIN、二级索引、视图、UPSERT。
- **二级索引**：这是 Phoenix 在 HBase 生态里最常被用到的能力。分为 **Global Index**（索引数据写进另一张独立的 HBase 表，读时走索引表拿主表 RowKey；写入要跨表更新，但读不再扇出）与 **Local Index**（索引与数据同表、同 Region，写入代价小、读要走 region 内索引）。全局索引的维护由 Coprocessor 在写主表时同步 / 异步维护，因此**索引与主数据的一致性靠 Phoenix 的写路径保证**，不是 HBase 内核。
- **版本对应**：Phoenix 4.x 对应 HBase 1.x（4.16.1 → 1.3~1.6）；**Phoenix 5.x 对应 HBase 2.x**——5.1.3 → 2.1~2.5，5.2.x → 2.4~2.6，5.3.x → 2.5~2.6。升级 HBase 2.x 大版本时 Phoenix 也要同步换 5.x 线，否则连不上。
- **连接注册**：Phoenix 5.2 起支持 HBase 的 registry 变体，JDBC URL 可用 `jdbc:phoenix+zk:`（默认）、`jdbc:phoenix+rpc:`、`jdbc:phoenix+master:`，与 HBase 3.0 默认 RPC registry（[Architecture](/docs/CS/DB/HBase/Architecture.md) 的 WARNING）对齐。

> [!NOTE]
> Phoenix 不是「给 HBase 加事务」的银弹：它提供有限的跨行原子与索引维护，但 HBase 内核没有原生跨行事务这一事实不变（见 [Replication](/docs/CS/DB/HBase/Replication.md) 分册）。需要真正跨行 ACID 仍应迁 TiDB / OceanBase，或引入 Tephra 一类事务框架。选 Phoenix 的出发点应是「保留 HBase 按 RowKey 取宽行的高吞吐，同时拿到 SQL 与二级索引」，而不是把 HBase 当成关系库用。

## Links

- [HBase](/docs/CS/DB/HBase/HBase.md)
- [RowKey Design](/docs/CS/DB/HBase/RowKey_Design.md)
- [Replication](/docs/CS/DB/HBase/Replication.md)
- [TiDB](/docs/CS/DB/TiDB/TiDB.md)
- [OceanBase](/docs/CS/DB/OceanBase.md)

## References

1. [Apache HBase Reference Guide](https://hbase.apache.org/book.html)
2. [Apache Phoenix](https://phoenix.apache.org/)
3. [Apache Phoenix Downloads](https://phoenix.apache.org/downloads/)
