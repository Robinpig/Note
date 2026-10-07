## Introduction

## 集群

很少有 Web 服务像搜索引擎这样，对每个请求需要如此多的计算量。平均而言，Google 上的单次查询要读取数百 MB 数据，消耗数百亿次 CPU 周期。要支撑每秒数千次查询的峰值请求流，所需基础设施的规模与最大的超级计算机装机相当。把超过 15000 台商品化（commodity-class）PC 与容错软件结合起来，构建出的方案比用少量高端服务器拼出的同等系统更具成本效益。

这里我们介绍 Google 集群的架构，并讨论影响其设计最重要的几个因素：能效（energy efficiency）与性价比（price-performance ratio）。在我们这样的运营规模下，能耗与散热问题会成为显著的运行因素，逼近可用数据中心功率密度的极限，因此能效是关键。

我们的应用很容易并行化：不同查询可在不同处理器上运行，而整体索引被分区，使得单个查询可以利用多个处理器。因此，峰值处理器性能不如其性价比重要。在这种意义下，Google 是一个面向吞吐量的工作负载示例，应当能从提供更多片上并行性的处理器架构（如同步多线程或片上多处理器）中受益。

Google 的软件架构源于两个基本洞见。

- 第一，我们在软件而非服务器级硬件中提供可靠性，因此可以用商品化 PC 以低端价格构建高端计算集群。
- 第二，我们为最佳的总体请求吞吐而非峰值服务器响应时间做设计，因为我们可以通过把单个请求并行化来控制响应时间。

我们相信，对我们的应用而言，最佳性价比来自用不可靠的商品化 PC 集群打造可靠的 computing 基础设施。我们在软件层面提供可靠性——通过把服务复制到多台不同机器上，并自动检测与处理故障。这种基于软件的可靠性涵盖许多不同领域，涉及系统设计的各个部分。

Google 集群遵循三条关键设计原则：

- **软件可靠性（Software reliability）。**
  我们摒弃容错硬件特性，例如冗余电源、廉价磁盘冗余阵列（RAID，redundant array of inexpensive disks）与高质量组件，转而专注于在软件中容忍故障。
- **用复制提升请求吞吐与可用性（Use replication for better request throughput and availability）。**
  由于机器本质上不可靠，我们把每个内部服务复制到多台机器上。由于我们本就为了获得足够容量而把服务跨多机复制，这种容错几乎是“免费”得来的。
- **性价比胜过峰值性能（Price/performance beats peak performance）。**
  我们采购当前单位价格性能最好的 CPU 代际，而非绝对性能最好的 CPU。
- **使用商品化 PC 降低计算成本（Using commodity PCs reduces the cost of computation）。**
  因此，我们能在每次查询上负担更多计算资源，在排序算法中采用更昂贵的技術，或检索更大的文档索引。

[GFS](/docs/CS/Distributed/GFS.md)

[MapReduce](/docs/CS/Distributed/MapReduce.md)
[Chubby](/docs/CS/Distributed/Chubby.md)

[Bigtable](/docs/CS/Distributed/Bigtable.md)

[Spanner](/docs/CS/Distributed/Spanner.md)

[Dapper](/docs/CS/Distributed/Dapper.md)


## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed.md)
- [GFS](/docs/CS/Distributed/GFS.md)
- [MapReduce](/docs/CS/Distributed/MapReduce.md)
- [Bigtable](/docs/CS/Distributed/Bigtable.md)
- [Spanner](/docs/CS/Distributed/Spanner.md)
- [Borg](/docs/CS/Distributed/Borg.md)

## References

1. [Web Search for a Planet: The Google Cluster Architecture](http://www.carfield.com.hk/document/networking/google_cluster.pdf?)
2. [Google Cluster Architecture overview](https://web.njit.edu/~alexg/courses/cs345/OLD/F15/solutions/f5345f15.pdf)
