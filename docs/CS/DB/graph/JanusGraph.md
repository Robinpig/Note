## Introduction

[JanusGraph](https://janusgraph.org/) 源于Titan，最新版本0.3.1于2018年10月发布，基于Apache 2开源协议，
是最有前景的开源图数据库，可支持数十亿级别的顶点和边规模，与Neo4J一样也使用Java开发，由IBM主导并提供云服务

JanusGraph可以为不断增大的数据和用户量提供了弹性和线性的扩展能力，通过数据多点分布和复制来提高性能和容错能力；支持ACID特性和最终一致性。
与Neo4J不同，JanusGraph不是原生的图数据库，相反的，其将数据存储到通用的存储系统上，
支持的后端存储包括：Apache Cassandra、Apache HBase、Google Cloud Bigtable和Oracle BerkeleyDB。
其中BerkeleyDB一般只做例子演示用


Janus Graph 采用邻接列表的方式来存储数据 一个顶点的邻接列表包含该顶点的属性及其关联的边
Janus Graph 将图的邻接列表存储在任何支持 HBase 数据模型的存储中






## Links

- [Graph DB](/docs/CS/DB/graph/graph.md)