## Introduction

TiDB 是 PingCAP 开源的分布式关系型数据库，对外暴露 MySQL 协议，同时提供行存（TiKV）与列存（TiFlash）两套引擎，构成 HTAP 形态。理解 TiDB 的关键是接受一个前提：**它不是在单机数据库外面套一层分片代理，而是把单机数据库的各个子系统拆成独立进程重新实现一遍**——SQL 解析与优化在 TiDB Server，事务与一致性在 TiKV/TiDB Server 协作的 Percolator 模型里，元信息与调度在 PD，列存与 MPP 计算在 TiFlash。本页把这四个组件的拓扑、数据流与部署形态讲清楚；每个组件的内部机制另立分册。

与「中间件分片」路线（本库 [ShardingSphere](/docs/CS/DB/ShardingSphere.md)、[TDDL](/docs/CS/DB/TDDL.md)）相比，TiDB 的分片与再均衡做进内核：应用看到的是单一 endpoint 与标准 SQL，不需要自己选分片键、处理跨分片事务与二次扩容时的数据迁移。代价是写路径必须走分布式共识与两阶段提交，单行点写的延迟与吞吐上限都受这条链路约束——选型时这是最需要掂量的取舍。

## Component Topology

一个 TiDB 集群由四类组件构成，加上可选的接入代理 TiProxy：

| 组件 | 角色 | 有状态 | 默认实例数 |
| :--- | :--- | :--- | :--- |
| TiDB Server | SQL 层：协议接入、解析、优化、分布式执行计划 | 无状态，节点完全对等 | ≥2 |
| PD | 元信息存储、TSO 授时、调度「大脑」 | 有状态（内嵌 etcd） | 3（奇数） |
| TiKV | 行存：Region + Raft + RocksDB + MVCC | 有状态 | 3 |
| TiFlash | 列存：Raft Learner 同步 + DeltaTree + MPP | 有状态 | ≥2（可选） |
| TiProxy | 官方代理：连接保持、服务发现、故障转移 | 无状态 | ≥2（可选） |

**计算存储分离**的含义：TiDB Server 本身不存任何数据，只把 SQL 翻译成对 TiKV/TiFlash 的 KV 调用并组装结果。因此这一层可以任意水平扩缩，单节点故障不丢数据也不丢可用性（会话级状态如本地临时表除外）。这也决定了它的接入方式：多个 TiDB 实例通过负载均衡组件对外提供统一地址，客户端连接均匀分摊。

## Request Path

一条查询的完整链路：

1. 客户端连接经负载均衡层（TiProxy / LVS / HAProxy / F5）落到某个 TiDB Server；
2. TiDB Server 解析 MySQL Protocol Packet，做语法解析与语义分析，生成逻辑执行计划；
3. 优化器基于统计信息与数据分布做代价估算，产出分布式物理计划：能下推的谓词与聚合变成 cop task 下发到 TiKV/TiFlash，跨 Region 的 join/聚合由 TiDB 层协调，TiFlash 上还可以走 MPP 模式做跨节点 shuffle；
4. 执行阶段向 PD 查询 Key 到 Region 的路由，直接与对应 TiKV/TiFlash 交互；
5. 写路径先取 PD 的 TSO 时间戳，事务提交走 Percolator 两阶段提交（详见 [Transaction](/docs/CS/DB/TiDB/Transaction.md)）。

PD 在这条链路里出场三次：授时（TSO）、路由（Region 位置）、以及后台持续调度（副本均衡、 Leader 打散、热点治理）。表结构的全局版本号也存在 PD（`/tidb/ddl/global_schema_version`），而表数据本身在 TiKV。

## Placement Driver at a Glance

PD 至少 3 个节点，内嵌 etcd 保证自身高可用。它常被误解为「只是元数据存储」——官方表述是「不仅存储元信息，同时还会根据 TiKV 节点实时上报的数据分布状态，下发数据调度命令」，并「为分布式事务分配事务 ID」。PD 的完整机制见 [PD](/docs/CS/DB/TiDB/PD.md)。

## HTAP Shape

TiKV 是行存引擎，承接 OLTP 读写；TiFlash 是「TiKV 的列存扩展」，通过 Raft Learner 异步复制 TiKV 的数据，读时通过进度校对保证不落后于请求时间戳，因此分析查询读到的是强一致的快照而不是陈旧数据。TiDB 优化器按代价估算自动选择行存或列存，甚至同一查询内混合使用；也可以用 Hint 或 engine 隔离强制。细节见 [TiFlash](/docs/CS/DB/TiDB/TiFlash.md)。

## Deployment Shapes

三种主流形态：

- **TiUP cluster**：自建物理机/虚拟机集群的命令行运维，v4.0 引入，覆盖部署、扩缩容、升级、参数管理，也能部署 TiFlash/TiCDC 与监控系统；
- **TiDB Operator**：Kubernetes 上的全生命周期自动化运维（部署、升级、扩缩容、备份恢复、配置变更），TiDB Cloud 自身也构建在它之上；
- **TiDB Cloud**：PingCAP 全托管 DBaaS，分 Starter / Essential / Premium / Dedicated / BYOC / Lake 多条产品线（Starter 内核仍为经典 TiDB 版本号，Essential/Premium 跑 TiDB X 内核）。

生产环境最小规模通常是 2 TiDB + 3 PD + 3 TiKV，TiFlash 与 TiProxy 按需添加。硬件基线（v8.5 官方建议）：

| 组件 | CPU | 内存 | 磁盘 | 实例数 |
| :--- | :--- | :--- | :--- | :--- |
| TiDB | 16 核+ | 48 GB+ | SSD | 2 |
| PD | 8 核+ | 16 GB+ | SSD | 3 |
| TiKV | 16 核+ | 64 GB+ | SSD | 3 |
| TiFlash | 48 核+ | 128 GB+ | 一块以上 SSD | 2 |
| TiProxy | 8 核+ | 16 GB+ | SAS | 2 |

网络要求万兆网卡。常用端口：TiDB 4000（应用访问），TiKV 20160，PD 2379，TiFlash 9000/3930，TiCDC 8300。

操作系统方面，除 RHEL / Rocky / openEuler 外，v8.5 明确支持银河麒麟 V10 SP1~SP3、统信 UOS V20——信创环境选型时这是硬门槛，需要回到官方硬件与软件要求页逐版本核对。

## Version Lineage

TiDB 采用 `X.Y.Z` 版本号：LTS 约每六个月一发，生命周期内只出补丁（不含新功能）；DMR（开发里程碑版本，自 v6.0.0 引入）约每两个月一发，**不提供补丁，不建议用于生产**。发布历史上：

- 当前基线为 **v8.5.8 LTS（2026-08-27）**，8.5.0 发布于 2024-12-19；
- **8.4.0-DMR（2024-11-11）是最后一个 DMR**，8.5 线至今没有任何 DMR 后缀版本——创新功能的发布节奏实质上收敛到了 LTS；
- LTS 序列为 6.5 / 7.1 / 7.5 / 8.1 / 8.5（BR 兼容性矩阵页的列举可作旁证）；
- v9.0 只有 beta 标签（v9.0.0-beta.1，2025-03-24），**从未 GA**：官方发布历史、pingcap/tidb 仓库标签、文档版本路径三处互相印证，写「TiDB 9」的二手文章都不可信。

新架构方面，TiDB Cloud 的 Starter/Essential/Premium 跑在 **TiDB X** 内核上，版本号为 CalVer 形态 `TiDB-X-CLOUD.YYYYMM.x`（202603 表示基线分支创建于 2026 年 3 月，与发布日期不同）；pingcap/tidb 仓库 master 分支标签已同步切到 `v26.3.x` 形式。PingCAP 官方计划 **2026 年底开源 TiDB X 核心代码**——这意味着本页的版本基线在不久的将来会再次变化，届时以官方发布历史页为准。

## Links

- [TiDB Server](/docs/CS/DB/TiDB/TiDB_Server.md)
- [TiKV](/docs/CS/DB/TiDB/TiKV.md)
- [PD](/docs/CS/DB/TiDB/PD.md)
- [TiFlash](/docs/CS/DB/TiDB/TiFlash.md)
- [TiDB Tools](/docs/CS/DB/TiDB/Tools.md)

## References

- [TiDB 整体架构](https://docs.pingcap.com/zh/tidb/v8.5/tidb-architecture/)
- [TiDB 数据库的计算](https://docs.pingcap.com/zh/tidb/stable/tidb-computing/)
- [TiProxy 简介](https://docs.pingcap.com/zh/tidb/v8.5/tiproxy-overview/)
- [使用 TiUP 部署 TiDB 集群](https://docs.pingcap.com/zh/tidb/v8.5/production-deployment-using-tiup/)
- [TiDB Operator 简介](https://docs.pingcap.com/zh/tidb/v8.5/tidb-operator-overview/)
- [软硬件环境要求](https://docs.pingcap.com/zh/tidb/v8.5/hardware-and-software-requirements/)
- [TiDB 版本规则](https://docs.pingcap.com/zh/tidb/v8.5/versioning/)
- [TiDB 版本发布历史](https://docs.pingcap.com/zh/tidb/v8.5/release-notes/)
