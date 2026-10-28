# RAMCloud

RAMCloud 是 Stanford 在 2010 年（FAST）提出的**分布式内存存储系统**，核心主张激进：**所有数据常驻 DRAM，DRAM 即真相源（source of truth）**，副本在内存中同步复制，持久化只靠把日志/备份异步写到磁盘、SSD 或其他节点的内存。目标是把客户端访问延迟压到**读约 5µs、写约 10µs** 量级——比基于磁盘/SSD 的存储快约 100 倍。

RAMCloud 与 [Aurora](/docs/CS/Distributed/Aurora.md)（计算存储分离、仍以磁盘为主）、[TiDB](/docs/CS/DB/TiDB/TiDB.md)（磁盘/SSD 真相源）走的是相反路线：传统系统以持久介质为真相源、内存只是缓存；RAMCloud 以 DRAM 为真相源、磁盘仅做备份。

## Architecture

- **中心化 Coordinator**：管理集群配置、表到 server 的映射、故障检测与恢复调度；本身不介入数据路径。
- **数千个 Server**：每个 server 管理一段内存表（hash/range 分片），客户端**直接访问** server，无中间代理层——这是低延迟的关键。
- **内存复制 + 异步持久化**：每个对象的写入先同步复制到若干个其他 server 的内存（跨机架/机房），再异步把 checkpoint/日志刷到外存（磁盘/SSD）。崩溃的 server 由 Coordinator 触发，从内存副本**重建**其丢失的内存状态，恢复时间以秒计而非分钟。

## Trade-offs

- **优势**：微秒级延迟、高吞吐、故障恢复快；适合需要极快随机访问的在线系统（会话、索引、元数据）。
- **代价**：DRAM 昂贵且容量受限，单位存储成本远高于磁盘/SSD；单节点故障虽不影响可用性（多副本），但整机内存失效要快速从副本补回。
- **与 Redis 对照**：Redis 是单机内存 KV（集群模式也以内存为主、持久化可选），但 RAMCloud 从一开始就是"全内存、强一致、自动分片与故障恢复"的分布式存储系统，而非一个内存数据结构服务；两者在"内存速度"上同源，在工程定位上不同。

## Relevance

RAMCloud 证明了一条与"磁盘/SSD 中心"相反的存储路线：当容量预算允许，**把持久化降级为后台备份、把内存升级为系统状态本身**，可彻底改写延迟上限。这与 [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md) 枢纽里"热数据用副本、冷数据用纠删码"的层次化思路形成对照——RAMCloud 把"热"推到了极致。

## Links

- [Aurora](/docs/CS/Distributed/Aurora.md)
- [TiDB](/docs/CS/DB/TiDB/TiDB.md)
- [Dynamo](/docs/CS/Distributed/Dynamo.md)
- [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md)

## References

- RAMCloud: Scalable High-Performance Storage Entirely in DRAM (Ousterhout et al., FAST 2010)
- Project: https://ramcloud.atlassian.net/
