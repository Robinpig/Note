## Introduction

Elasticsearch 集群是一个经典的分布式系统设计案例：通过分片（Sharding）、副本（Replication）、投票式主节点选举与近实时（NRT）存储，实现海量数据的水平扩展、高可用与高性能搜索。

**版本基线：Elasticsearch 9.5.5**。本篇结论可回源码反查（`elastic/elasticsearch` tag `v9.5.5`），关键路径：选举在 `org.elasticsearch.cluster.coordination`，路由在 `org.elasticsearch.cluster.routing`，写路径在 `org.elasticsearch.index.engine.InternalEngine`。

## 基本单元

| 概念 | 说明 |
| ---- | ---- |
| 索引（Index） | 逻辑数据集合，类似 Database；主分片数创建后不可变 |
| 分片（Shard） | 索引切分出的工作单元，每个主分片物理上是一个独立的 Lucene 索引（见 [Lucene](/docs/CS/Framework/ES/Lucene.md)） |
| 副本（Replica） | 主分片的拷贝，提供读负载均衡与容灾 |
| 节点（Node） | ES 实例；每节点一个 UUID 存于 data 目录，`node.name` 缺省取 `HOSTNAME` |

角色划分详见 [Install：安装与节点角色](/docs/CS/Framework/ES/Install.md)——9.x 用 `node.roles` 列表配置，`node.master`/`node.data` 布尔配置已移除。

## 发现与主节点选举

1. **节点发现**：启动时按 `discovery.seed_hosts` 发送 ping 发现其他节点并交换集群状态（cluster state：有哪些节点、哪些索引、分片如何分布）；
2. **主节点选举**：由 `cluster.coordination` 包的 Coordinator 完成——先预投票（pre-vote）避免扰动，再按 Raft 式法定人数选出主节点；
3. **防脑裂**：写操作必须得到法定人数（quorum）确认，网络分区下少数派分区无法完成写，从而天然防脑裂。配套机制：
   - `cluster.initial_master_nodes` 引导初始投票配置（`ClusterBootstrapService.java:49-52,242-255`），仅在「发现节点数 × 2 > 需求数」时真正触发（`:198-200`）；
   - `cluster.auto_shrink_voting_configuration` 默认 **true**，自动收缩投票配置保持至少 3 个可投票节点（`Reconfigurator.java:49-54`）；
   - `discovery.unconfigured_bootstrap_timeout` 默认 **3s**，未配 seed 时尽力 bootstrap 的等待上限。

> [!WARNING]
> **`discovery.zen.minimum_master_nodes` 已从源码移除**（全仓无 Setting 定义、无消费方）。法定人数由投票配置自动计算，所有还在教你手动配最小主节点数的资料都是 7.x 以前的。`discovery.type` 在 9.x 只有 `multi-node` / `single-node` 两个合法值（`DiscoveryModule.java:68-75`）。

## 写路径

```
协调节点 -> 路由计算 -> 主分片节点
  1. 路由：shard = Math.floorMod(Murmur3(routing), number_of_primary_shards)
     routing 为空时用 _id（IndexRouting.java:186-190,341-343）
  2. 写 Lucene：文档进 IndexWriter 内存缓冲（indexWriter.addDocument）
  3. 写 translog：Lucene 成功后才 translog.add()（InternalEngine.java:1310-1325）
  4. 并发转发副本，达到 wait_for_active_shards 阈值后响应客户端
```

两个容易写反的事实：

- **顺序是 Lucene 先、translog 后**，不是「先写 translog 保不丢」。恢复时只需重放「translog 有、Lucene 没有」的操作；
- **`index.write.wait_for_active_shards` 默认 1**（`IndexMetadata.java:484-490`）——默认不等副本同步，要强一致须显式 `?wait_for_active_shards=all`。

串行化不靠 IndexShard 互斥锁：engine 层 per-UID 锁（`versionMap.acquireLock`，`InternalEngine.java:1243-1246`）+ 主分片 seq-no + 同 shard bulk 单线程执行，三层叠加保证顺序。

## 搜索路径：Query Then Fetch

默认 `search_type` 为 `QUERY_THEN_FETCH`（`SearchType.java:36`），9.x 实际有三个环节：

1. **can_match 预过滤**（`CanMatchPreFilterSearchPhase.java:50-63`）：扇出前按查询改写结果把不可能命中的分片整个跳过，预过滤分片数 `action.search.pre_filter_shard_size.default` 默认 128；
2. **Query 阶段**（`QueryPhase.java:53-75`）：请求广播到相关分片（主或副本），各分片本地查询后返回 doc id + score 的轻量结果，协调节点全局归并排序取 Top N；
3. **Fetch 阶段**（`FetchPhase.java:70-75`）：按 doc id 去对应分片取 `_source`，组装完整结果返回。

DFS 变体仍存在（先取词频统计再打分，更准更慢），且 kNN 向量搜索会强制切到 DFS（`TransportSearchAction.java:836-841`）。分页与深度翻页见 [Query DSL](/docs/CS/Framework/ES/Query_DSL.md)。

## Links

- [Elasticsearch（枢纽页）](/docs/CS/Framework/ES/ES.md)
- [Install：安装与节点角色](/docs/CS/Framework/ES/Install.md)
- [Query DSL：查询与分页](/docs/CS/Framework/ES/Query_DSL.md)
- [Lucene：倒排、段与分片](/docs/CS/Framework/ES/Lucene.md)
- [Troubleshooting：排障](/docs/CS/Framework/ES/Troubleshooting.md)

## References

1. [Elasticsearch Reference - Discovery and cluster formation](https://www.elastic.co/guide/en/elasticsearch/reference/current/modules-discovery.html)
2. [Elasticsearch Reference - Distributed search execution](https://www.elastic.co/guide/en/elasticsearch/reference/current/distributed-search.html)
3. [elastic/elasticsearch v9.5.5 源码](https://github.com/elastic/elasticsearch/tree/v9.5.5)
