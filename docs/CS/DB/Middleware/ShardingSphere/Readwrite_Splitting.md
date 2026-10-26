## Introduction

读写分离应对的是「读多写少」：主库扛事务型写，从库分摊查询，按 SQL 语义感知底层拓扑，让应用像用「一个库」一样用「一个主从组」。它与分片的区别是**节点间数据一致、而非互不感知**，两者可组合。本页讲路由机制、负载均衡、事务内读策略与高可用的边界。

## Positioning

- 一主多从：查询均摊到多个副本，避开行锁、提升整体查询吞吐。
- 多主多从：在吞吐之外增强可用性——任一库宕机甚至磁盘损坏，系统仍可运行。
- **与分片的分野**：分片把数据分散到互不重叠的节点；读写分离的节点持有同一份数据的不同副本。混用时，先分片再在每个分片组内做读写分离，是常见叠加形态。

## Routing

读写分离按 SQL 分析结果路由：事务型语句（INSERT/DELETE/UPDATE 等）进写库，查询进读库。拓扑由配置显式声明，ShardingSphere **不负责主从之间的数据复制**——复制是数据库自己的事，中间件只消费拓扑。

## Configuration

```yaml
rules:
- !READWRITE_SPLITTING
  dataSourceGroups:
    readwrite_ds:
      writeDataSourceName: write_ds
      readDataSourceNames:
        - read_ds_0
        - read_ds_1
      transactionalReadQueryStrategy: PRIMARY
      loadBalancerName: random
  loadBalancers:
    random:
      type: RANDOM
```

- `writeDataSourceName` 与 `readDataSourceNames` 均支持**行表达式解析**（默认 Groovy 的 Row Value Expressions SPI），多库多从可以表达式展开，不必逐个枚举。
- 逻辑数据源组名即应用看到的名字；规则可多组并存。

## Load Balancers

内置三种负载均衡算法：

| type | 语义 | 关键属性 |
| :--- | :--- | :--- |
| `ROUND_ROBIN` | 轮询 | — |
| `RANDOM` | 随机 | — |
| `WEIGHT` | 权重 | 属性名用副本名（`${replica-name}`），填该副本权重；单副本权重 > 0，总和 ≤ `Double.MAX_VALUE` |

权重的典型用法是按机器规格分配读流量；随机与轮询在副本同构时差异不大。

## Transactional Read Query Strategy

事务内的读请求路由策略 `transactionalReadQueryStrategy`：

| 值 | 语义 |
| :--- | :--- |
| `PRIMARY`（默认） | 事务内读一律走主库 |
| `FIXED` | 同一事务内固定路由到某个数据源 |
| `DYNAMIC` | 同一事务内路由到非固定数据源 |

**`FIXED` 与 `DYNAMIC` 要求数据库支持主从强一致同步才能使用**（官方点名的例子是 openGauss）；普通异步复制下，事务内读到从库的旧快照会破坏读写一致性。默认 `PRIMARY` 正是「事务内读写都在主库」的保守正确解。

## High Availability

读写分离的高可用由治理层协同完成，边界要说清：

- 主从拓扑在规则里声明，**副本间的数据复制与复制延迟不由 ShardingSphere 负责**；主从延迟导致读到旧数据是数据库复制的问题，中间件只能让你把读导向主库（`PRIMARY`）。
- 集群模式下，实例状态与数据源上下线由注册中心协调（实例在线状态、数据源禁用/恢复状态以节点形式 persisted），配合心跳探测感知拓扑变化——这是 [Governance](/docs/CS/DB/Middleware/ShardingSphere/Governance.md) 的范畴，读写分离规则只声明「静态拓扑长什么样」。
- 多主多从是可用性主力：单点故障时读流量可整体切换，写入口需业务或 DBA 侧配合（ShardingSphere 不做故障转移决策的自动化承诺，按拓扑声明 + 状态禁用使用）。

## Facts Worth Pinning Down

1. **`FIXED`/`DYNAMIC` 不是纯性能选项**：没有强一致主从同步（如 openGauss）就不要开，默认 `PRIMARY` 是最稳的。
2. **读写分离不复制数据**：主从延迟、数据不一致是数据库侧责任；把它当「中间件保证一致」会出生产事故。
3. **读写分离与分片可叠加但语义不同**：分片节点数据互不重叠，读写分离节点数据相同——混用时的排查思路完全不同（分片查路由，分离查复制延迟）。
4. **多写不被支持**：官方明确不支持「双主/多主同时提供写操作」的配置语义，写入口是单点。

## Links

- [Sharding](/docs/CS/DB/Middleware/ShardingSphere/Sharding.md)
- [MySQL Replication](/docs/CS/DB/MySQL/replica.md)
- [Architecture](/docs/CS/DB/Middleware/ShardingSphere/Architecture.md)

## References

1. [Read/write Splitting :: ShardingSphere](https://shardingsphere.apache.org/document/current/en/features/readwrite-splitting/)
2. [Readwrite-splitting YAML Configuration](https://shardingsphere.apache.org/document/current/en/user-manual/shardingsphere-jdbc/yaml-config/rules/readwrite-splitting/)
3. [Load Balance Algorithm (built-in list)](https://shardingsphere.apache.org/document/current/en/user-manual/common-config/builtin-algorithm/load-balance)
4. [Apache ShardingSphere document v5.0.0](https://shardingsphere.apache.org/document/5.0.0/en/shardingsphere_docs_en.pdf)
