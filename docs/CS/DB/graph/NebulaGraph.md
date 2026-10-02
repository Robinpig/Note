## Introduction

[NebulaGraph](https://www.nebula-graph.io/) 是一款开源的**分布式图数据库**，擅长超大规模图谱的毫秒级多跳查询。原生分布式、存储与计算分离，使用 **Raft** 保证一致性，查询语言兼容 **openCypher**（nGQL 为其扩展）。

## 架构（存储/计算分离）

- **Meta Service**：元数据（schema、分片、图空间信息），自身用 Raft 多副本。
- **Storage Service**：真正存数据，按分片（partition）分布，底层基于 **RocksDB**；每个分片是一个 Raft group。
- **Graph Service（Query）**：无状态计算节点，接收 nGQL、生成执行计划、向 Storage 拉数据并做多跳遍历；可水平扩展。

## 数据模型

- **点（Vertex）** = 标签（Tag）+ 一组属性 + 全局唯一 `VID`。
- **边（Edge）** = 类型（EdgeType）+ 起点/终点 VID + 排名（rank）+ 属性；边可单向/双向。
- 同 VID 的 Tag 与出/入边在 Storage 中同分片，使一跳遍历尽量本地完成。

## 查询与对比

- **nGQL** 兼容 openCypher：`MATCH (v:player)-[e:like]->(n) RETURN n`。
- 多跳（K-hop）深链查询是强项；对比 [Neo4j](/docs/CS/DB/graph/Neo4j.md)（单机为主、Cypher）、[JanusGraph](/docs/CS/DB/graph/JanusGraph.md)（基于外部 KV、无原生存储）。

## Links

- [Graph DB](/docs/CS/DB/graph/graph.md)
- [RocksDB](/docs/CS/DB/RocksDB/RocksDB.md)
- [Neo4j](/docs/CS/DB/graph/Neo4j.md)

## References

- [NebulaGraph Documentation](https://docs.nebula-graph.io/)
