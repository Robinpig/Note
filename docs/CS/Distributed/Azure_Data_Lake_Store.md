# Azure Data Lake Store

Azure Data Lake Store（ADLS，2015 GA，后演进为 **ADLS Gen2** 融入 Azure Blob Storage）是微软的**云规模分布式文件系统**，专为大数据分析负载设计。它提供 **HDFS 兼容 API**，支持无限层级的目录命名空间（hierarchical namespace）、单文件 TB 级、面向聚合吞吐（而非低延迟 OLTP）优化，是 Azure 上 Hadoop / Spark 生态的存储底座。

ADLS 与 [GFS](/docs/CS/Distributed/GFS.md) / [Hadoop](/docs/CS/Framework/Hadoop/Hadoop.md) 的 HDFS 同源（"大规模顺序读写的分布式文件系统"），区别在交付形态：HDFS 是自建集群的存储层，ADLS 是托管的云服务。

## Design

- **Hierarchical namespace**：与对象存储（S3 / MinIO）的扁平 key 不同，ADLS 维护真正的目录树。这让 Hadoop/Spark 常见的"重命名目录"成为 O(1) 的元数据操作，而非逐对象 copy——对分析负载至关重要。
- **分块与冗余**：数据按 256MB 块切分，跨多节点分布；结合多副本与纠删码保证持久与可用，类似 HDFS 的块复制，但由云基础设施托管。
- **Gen2 融合**：Gen2 在 Azure Blob Storage 之上加 hierarchical namespace，统一了"对象存储的无限扩展/低成本"与"文件系统目录语义"，成为 Azure 数据分析的事实标准入口。

## Comparison

- **vs HDFS / GFS**：同样是"一次写、多次顺序读"的分布式文件系统范式，ADLS 把运维（容量、可靠性、纠删码）下沉给云厂商，用户只付存储与吞吐。
- **vs 对象存储（S3 / MinIO）**：对象存储只有扁平 key、无目录语义，rename 昂贵；ADLS 的目录树更适合 Hadoop 生态。这也呼应 [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md) 里"文件系统"与"对象存储"两类接口的区分——ADLS 属于文件系统类，但长在云上。
- **与容器生态**：云上分析负载常跑在 [Container](/docs/CS/Container/Container.md)（K8s）里，ADLS 作为挂载的分布式文件系统提供持久、共享、高吞吐的数据层。

## Links

- [Hadoop](/docs/CS/Framework/Hadoop/Hadoop.md)
- [GFS](/docs/CS/Distributed/GFS.md)
- [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md)
- [Container](/docs/CS/Container/Container.md)

## References

- Azure Data Lake Storage documentation: https://learn.microsoft.com/en-us/azure/storage/blobs/data-lake-storage-introduction
