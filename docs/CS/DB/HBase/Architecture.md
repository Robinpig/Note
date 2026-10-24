## Introduction

HBase 的集群由 HMaster（管调度、不碰数据）、HRegionServer（干活的节点）、Region（按 RowKey 范围切分、均衡单位）、hbase:meta（路由权威）组成。本页讲清角色分工、Region 数量治理，以及 3.0 把客户端引导从 ZooKeeper 改成 RPC registry 这一关键断点——这是写设计文档时最容易踩的版本陷阱。深入 RowKey 与写路径见 [HBase](/docs/CS/DB/HBase.md) 的其它分册。

## Architecture

- **HMaster**：管元数据与调度（建表/删表、列族变更、Region 分配与迁移、负载均衡），**不参与实际数据读写**，所以 Master 宕机不影响在线读写，只短时影响管理操作。
- **HRegionServer**：工作节点，服务多个 Region，承接客户端读写、flush、compaction、WAL。
- **Region**：一张表按 RowKey 范围水平切分成多个 Region，是分布式与负载均衡的单位；一个 Region 内按列族拆成多个 **Store**，每个 Store = MemStore + 若干 HFile。
- **hbase:meta**：系统表，记录「哪个 RowKey 落在哪个 RegionServer 的哪个 Region」，客户端查一次后在本地缓存路由。
- **分裂由 RegionServer 自己完成**，Master 不参与：RS 把父 Region 下线、一分为二、在**父 Region 所在节点**打开两个子 Region 并写回 `hbase:meta`，最后才向 Master 上报。也就是说分裂是本地事件，代价是一次短暂的 region offline。
- **Region 数量要克制**：官方建议单表/单集群维持「少量大 Region」——20~200 个、每个 5~20 GB，实践中**约 100 个 Region / RegionServer** 效果最好。原因很硬：MSLAB 每个 MemStore 预留 2 MB 堆内缓冲，1000 个 Region × 2 个列族 ≈ 3.9 GB 堆还没装数据。
- **自动治理**：`hbase.normalizer.period`（默认 300000 ms）由 `hbase.normalizer.split.enabled` / `hbase.normalizer.merge.enabled`（均默认 `true`）控制，Master 周期性拆分过小 / 合并过大的相邻 Region。

```
Client --(2.x: 读 ZK 定位 meta / 3.0+: RPC 问 Master)--> hbase:meta --> HRegionServer
HRegionServer -> Region -> Store(per CF) -> MemStore + HFile
持久化 -> HDFS(HFile, WAL)；协调与选举 -> ZooKeeper；元数据与调度 -> HMaster
```

> [!WARNING]
> **客户端与 ZooKeeper 的关系在 3.0.0 变了**。2.x 默认以 ZooKeeper 为事实来源，客户端启动前必须知道 `hbase.zookeeper.quorum`，靠读 znode 拿 Master 地址与 meta 位置。**3.0.0 起默认连接注册方式（connection registry，2.5.0 引入）改为 RPC 实现**：客户端改为联系 Master 的 RPC 端点，配置项换成 `hbase.masters`，ZooKeeper 退化为集群内部依赖。把「HBase 客户端必须能访问 ZK」当恒真命题写进设计文档，在 3.x 上是错的。

## Connection Registry (Client Bootstrap)

客户端启动前必须拿到三类元数据才能开始读写：**active master 地址**、**当前 `hbase:meta` region 的位置**、**cluster ID**。历史上这三类信息来自 ZooKeeper 的 znode；3.0 把默认来源换成了 RPC 服务，但 ZK 并未退出集群（见下）。

### Evolution: ZK to RPC

- **ZK-based（`ZKConnectionRegistry`）**：2.x 及更早的默认实现。客户端读 `/hbase/meta-region-server`、`/hbase/master`、`/hbase/rs` 等 znode 引导，依赖 `hbase.zookeeper.quorum`。
- **MasterRegistry（`MasterRegistry`，HBASE-18095，2.3.0 引入）**：同样的元数据改从 Master 的 RPC 端点拉取，而不是 ZK。**所有** master（active + stand-by）都暴露该服务，客户端可以连任意一台，避免单点热点。HBASE-23647 把它设为 3.0 默认。
- **RpcConnectionRegistry（`RpcConnectionRegistry`，2.5.0 引入）**：同样基于 RPC，但 **RegionServer 也实现该服务**，因此**任意节点都能当引导节点**（不止 master）；并新增引导节点的**定期刷新**（分摊负载、剔除死节点）。这是 **3.0.0 的默认客户端 registry 实现**。

### Configuration

最小客户端配置：

- ≤ 2.x（ZK 默认）：`hbase.zookeeper.quorum = host1,host2,host3`
- ≥ 3.0（RPC 默认）：`hbase.masters = host1,host2,host3`（逗号分隔的 `host:port`，缺省端口为 **16000**）

用 `hbase.client.registry.impl` 显式选择实现：

- `org.apache.hadoop.hbase.client.ZKConnectionRegistry`（ZK）
- `org.apache.hadoop.hbase.client.MasterRegistry`（master RPC，2.3+）
- `org.apache.hadoop.hbase.client.RpcConnectionRegistry`（RPC，2.5+，3.0 默认）

`RpcConnectionRegistry` 还可指定引导节点：`hbase.client.bootstrap.servers = rs1:16020,rs2:16020,rs3:16020`（**必须带端口**，默认 RS 端口 16020）；不配则回退到 master 地址。RPC hedging 扇出为 `hbase.client.bootstrap.hedged.fanout`（默认 **2**）；刷新旋钮有 `hbase.client.bootstrap.refresh_interval_secs`（默认 **300** 秒）、`hbase.client.bootstrap.initial_refresh_delay_secs`（默认是刷新间隔的 1/10）、`hbase.client.bootstrap.min_secs_between_refreshes`。（MasterRegistry 的 hedging 用的是另一个 key `hbase.rpc.hedged.fanout`，默认也是 2。）

### Why the change

- **给 ZooKeeper 减负**：ZK 对集群运行至关重要，把它移出客户端引导路径可保护它。
- **统一的客户端超时/重试**：新 registry 把引导过程纳入 HBase RPC 框架，超时与重试与其余 RPC 一致配置。
- **从客户端库去除 ZK 依赖**：客户端不再需要 ZK 客户端 jar 与 ZK ACL。

### What does not change

- **ZooKeeper 并未从集群移除**。Master↔RegionServer 的存活检测、内部状态（ephemeral znode、选主）、以及**跨集群 replication** 仍走 ZK-based registry；集群对 ZK 的可用性要求与以前一致。
- **Master 进入客户端引导的关键路径**：当客户端元数据缓存为空或失效时，master 成为瓶颈，连接负载上升。**所有 master 都服务 registry RPC** 以分摊；客户端以随机顺序 hedging 请求，避免打到单台 master。

### Upgrade note (2.x to 3.0)

客户端配置必须把 `hbase.zookeeper.quorum` 改成 `hbase.masters`。若要保留旧 ZK 引导（如滚动升级期间），设 `hbase.client.registry.impl=org.apache.hadoop.hbase.client.ZKConnectionRegistry`。

### Correlated 3.0 break: hbase-protocol removed

HBASE-23797 在 3.0.0 **移除了 `hbase-protocol` 模块**，所有 protobuf 迁入 `hbase-protocol-shaded`（protobuf 2.5 → 3.x，且 shaded）。客户端与 coprocessor 代码必须针对 shaded proto 重新编译；**线格式兼容保留**（旧客户端仍能连新 coprocessor 服务），但不再能依赖旧的 `hbase-protocol` artifact。

## Links

- [HBase](/docs/CS/DB/HBase.md)
- [HDFS](/docs/CS/Framework/Hadoop/HDFS.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Region Management](/docs/CS/DB/HBase/Region_Management.md)

## References

1. [Apache HBase Reference Guide](https://hbase.apache.org/book.html)
2. [Bigtable: A Distributed Storage System for Structured Data](https://research.google/pubs/bigtable-a-distributed-storage-system-for-structured-data/)
3. [Salesforce Engineering - Evolution of Region Assignment Part 3 (SCP / WAL split)](https://engineering.salesforce.com/evolution-of-region-assignment-in-the-apache-hbase-architecture-part-3-e03b814ae92/)
4. [Apache HBase Docs - Client / Connection Registry](https://hbase.apache.org/docs/architecture/client)
5. [HBASE-23647 Make MasterRegistry the default registry impl](https://issues.apache.org/jira/browse/HBASE-23647)
6. [HBASE-23797 Remove hbase-protocol module (protobuf → hbase-protocol-shaded)](https://issues.apache.org/jira/browse/HBASE-23797)
