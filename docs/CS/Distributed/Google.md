## Introduction

## Cluster

Few Web services require as much computation per request as search engines.
On average, a single query on Google reads hundreds of megabytes of data and consumes tens of billions of CPU cycles.
Supporting a peak request stream of thousands of queries per second requires an infrastructure comparable in size to that of the largest supercomputer installations.
Combining more than 15,000 commodity-class PCs with fault-tolerant software creates a solution that is more cost-effective than a comparable system built out of a smaller number of high-end servers.

Here we present the architecture of the Google cluster, and discuss the most important factors that influence its design: energy efficiency and price-performance ratio.
Energy efficiency is key at our scale of operation, as power consumption and cooling issues become significant operational factors, taxing the limits of available data center power densities.

Our application affords easy parallelization:
Different queries can run on different processors, and the overall index is partitioned so that a single query can use multiple processors.
Consequently, peak processor performance is less important than its price/performance.
As such, Google is an example of a throughput-oriented workload, and should benefit from processor architectures that offer more on-chip parallelism, such as simultaneous multithreading or on-chip multiprocessors.

Google’s software architecture arises from two basic insights.

- First, we provide reliability in software rather than in server-class hardware, so we can use commodity PCs to build a high-end computing cluster at a low-end price.
- Second, we tailor the design for best aggregate request throughput, not peak server response time, since we can manage response times by parallelizing individual requests.

We believe that the best price/performance tradeoff for our applications comes from fashioning a reliable computing infrastructure from clusters of unreliable commodity PCs.
We provide reliability in our environment at the software level, by replicating services across many different machines and automatically detecting and handling failures.
This software-based reliability encompasses many different areas and involves all parts of our system design.

Google clusters follow three key design principles:

- **Software reliability.**
  We eschew fault-tolerant hardware features such as redundant power supplies, a redundant array of inexpensive disks (RAID), and highquality components, instead focusing on tolerating failures in software.
- **Use replication for better request throughput and availability.**
  Because machines are inherently unreliable, we replicate each of our internal services across many machines.
  Because we already replicate services across multiple machines to obtain sufficient capacity, this type of fault tolerance almost comes for free.
- **Price/performance beats peak performance.**
  We purchase the CPU generation that currently gives the best performance per unit price, not the CPUs that give the best absolute performance.
- **Using commodity PCs reduces the cost of computation.**
  As a result, we can afford to use more computational resources per query, employ more expensive techniques in our ranking algorithm, or search a larger index of documents.

[GFS](/docs/CS/Distributed/GFS.md)

[MapReduce](/docs/CS/Distributed/MapReduce.md)
[Chubby](/docs/CS/Distributed/Chubby.md)

[Bigtable](/docs/CS/Distributed/Bigtable.md)

[Spanner](/docs/CS/Distributed/Spanner.md)

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed_Systems.md)

## References

1. [Web Search for a Planet: The Google Cluster Architecture](http://www.carfield.com.hk/document/networking/google_cluster.pdf?)
2. [Google Cluster Architecture overview](https://web.njit.edu/~alexg/courses/cs345/OLD/F15/solutions/f5345f15.pdf)