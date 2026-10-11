## Introduction

从存储层的实现来看，图数据库可以分成原生图存储和非原生存储。
非原生存储是指依赖第三方存储系统实现的图数据库，如基于 HBase 或者 RocksDB 等底层存储系统，在数据处理层实现了免索引邻接。

## Data Models

### Property Graph

属性图模型由顶点、边及其属性构成。顶点和边都可以带有属性，节点可以通过“标签（Label）”进行分组。表示关系的边总是从一个开始点指向一个结束点，而且边是一定是有方向的，这使得图成为了有向图。关系上的属性可以为节点的关系提供额外的元数据和语义。

### RDF

RDF 图（Resource Description Framework）的顶点和边上没有属性，只有一个资源描述符，这是 RDF 与属性图模型间最根本的区别。在 RDF 中每增加一条信息都要用一个单独的节点表示。比如，在图中给表示人的节点添加姓名。在属性图中只需要在节点添加属性即可，而在 RDF 中必须添加一个名字的单独节点，并用 hasName 与原始节点相连。

RDF 可以水平扩展但不能快速横向扩展关系，因为它们将三元组存储为单独的元素，所以必须从独立事实创建连接并增加延迟以执行图查询。由于其在延迟和规模方面的缺点，主要应用于离线分析。

## Data Import

图数据库的数据导入可分为存量导入、实时导入、流式导入和增量批量导入等模式。

## Storage Structures

存储结构上两条路线分明：原生图存储多以链表组织记录与邻接关系，代表是 [Neo4j](/docs/CS/DB/graph/Neo4j.md)；非原生实现把邻接列表落在 LSM 树上，如可接 Cassandra/HBase 后端的 [JanusGraph](/docs/CS/DB/graph/JanusGraph.md)，以及存储层直接构建在 RocksDB 上的 [NebulaGraph](/docs/CS/DB/graph/NebulaGraph.md)。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Neo4j](/docs/CS/DB/graph/Neo4j.md)
- [JanusGraph](/docs/CS/DB/graph/JanusGraph.md)
- [NebulaGraph](/docs/CS/DB/graph/NebulaGraph.md)

## References

- [Graph database - Wikipedia](https://en.wikipedia.org/wiki/Graph_database)
- [JanusGraph](https://janusgraph.org/)
- [NebulaGraph](https://www.nebula-graph.io/)
