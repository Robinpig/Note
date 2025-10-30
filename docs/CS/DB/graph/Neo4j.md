## Introduction

Neo4j 是一款基于 Java 实现的图数据库 兼容 ACID 特性, 并提供了开源的单机版





Neo4j 使用的存储结构是链表结构 其物理存储单元可以是连续的或者非连续的 链表由一系列元素组成 元素通过链表的指针链接次序来实现逻辑顺序

在 Neo4j 中 图按照不同的图名称存储在不同的路径下 每条图路径根据数据的分类存储在不同的文件中 顶点、边、标签和属性都是独立的存储文件 这种图结构和属性分离的方式 可以显著提高图遍历的性能 例如在不需要基于属性值进行过滤的图遍历查询中 只需要使用图结构文件

1. 顶点 图存储路径下 `neostore.nodestore.db` 每个顶点记录被表示成一个 NodeRecord
2. 边 图存储路径下 `neostore.relationshipstore.db`
3. 属性 图存储路径下 `neostore.propertystore.db` 每个属性包含四个 Property Block 以及属性链表下一个属性指针




## Links

- [Graph DB](/docs/CS/DB/graph/graph.md)
