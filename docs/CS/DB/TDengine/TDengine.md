## Introduction

TDengine 是涛思数据（TAOS Data）用 C 写的**国产开源时序数据库**，现在官方产品名是 TDengine TSDB。它的底色有两条：**一设备一表**（One table per device）——每个采集点（传感器、电表、汽车、机器人）对应一张子表，同类采集点用超级表共享 schema、各带静态标签；**极简时序数据平台**——时序数据库之外，缓存、数据订阅、流计算、AI 智能体全部内置，官方明确说应用因此不必再集成 Kafka / Redis / HBase / Spark。许可证是 **AGPL-3.0**（仓库根 `LICENSE` 即 GNU AGPL v3），集群功能全部开源。

版本锚点 **3.4.x**：GitHub 最新稳定版 **3.4.3.3（2026-10-19）**，本库所有结论以官方文档（docs.taosdata.com）与源码为准。3.4 这条线有三个发行形态，差异比一般开源/商业二分更细：

| 形态 | 服务端平台 | 客户端平台 | 说明 |
| :-- | :-- | :-- | :-- |
| **TDengine TSDB-OSS** | Linux、macOS | Linux、macOS、Windows | 社区版，集群、多副本（replica 3）、TMQ、流计算、TDgpt 全都有 |
| **TDengine TSDB-Enterprise** | Linux、Windows | Linux、macOS、Windows | 企业版：安全（RBAC/MFA/加密）、多级存储、taosX HA、Explorer SSO、模型评估工具等 |
| **TDengine Cloud** | 云服务 | — | 免部署的托管形态 |

3.4 还有两条硬断点：**OSS 客户端从此连不上 Enterprise 服务端**（反向可以），且**不支持滚动升级**——集群必须整集群停机后逐节点升级。

本页是 TDengine 的**枢纽页**：只放定位、架构总览、选型与最要紧的反直觉事实；架构逻辑单元、数据模型、存储引擎、压缩、SQL、流计算与订阅、TDgpt、生态工具、部署运维九个方向各有分册展开。

## Architecture

TDengine 的集群是"**mnode 管元数据 + vgroup 存数据 + taosc 驱动**"的形状，全部服务器侧代码跑在**一个进程 `taosd`** 里，逻辑节点是进程内的角色而非独立二进制：

| 逻辑单元 | 载体 | 职责 |
| :-- | :-- | :-- |
| **pnode** | 物理机/虚拟机/容器 | 由 FQDN 标识，集群网络通信完全依赖 FQDN |
| **dnode** | `taosd` 实例 | 由 endpoint（FQDN + 端口，默认 `serverPort` 6030）唯一标识；一台 pnode 可起多个 dnode |
| **mnode** | dnode 内角色（每 dnode 最多 1 个） | 元数据（用户、库、超级表、拓扑）、调度；**多 mnode 组 Raft**，最多 3 个 |
| **vnode** | dnode 内角色 | 存储与查询的基本单元，一个 vnode "就是一个独立数据库"；一个 vnode 只属于一个数据库 |
| **vgroup** | 跨 dnode 的 vnode 组 | vnode 间 **Raft 复制**，写只在 leader，异步同步 follower；vgroup 数量即副本数 |
| **qnode** | dnode 内角色 | 查询计算节点，集群级共享，**存算分离**的执行侧；没有 qnode 时计算退回 vnode |
| **snode** | dnode 内角色 | 流计算节点，同样集群级共享 |
| **bnode** | dnode 内角色 | 订阅节点，拉起子进程 `taosmqtt` 对外提供 MQTT 订阅 |
| **taosc** | 客户端库 | C 驱动，被 JDBC/Go/Python/Node/C#/Rust 连接器内嵌；负责 SQL 解析、计划、调度与最后一级聚合 |

写入侧还有 `taosAdapter`（HTTP/REST/WebSocket/InfluxDB Line Protocol/Prometheus 的协议适配层）与 `taosKeeper`（监控导出）两个独立进程。数据从客户端到落盘的完整路径、各逻辑单元的创建 SQL（`CREATE MNODE/QNODE/SNODE/BNODE`）与 FQDN/端口解析顺序，见 [Architecture](/docs/CS/DB/TDengine/Architecture.md)。

## Map of This Section

九个分册对应九类问题，也对应使用 TDengine 时九种不同的翻车方式：

- **[Architecture](/docs/CS/DB/TDengine/Architecture.md)**——「集群到底是什么形状」。pnode/dnode/vnode/vgroup/qnode/snode/bnode 的职责边界、Raft 用在哪些层、taosc 的双重角色、FQDN 与 endpoint 解析、三个发行形态的功能矩阵。理解所有其他分册的地图。
- **[Data_Model](/docs/CS/DB/TDengine/Data_Model.md)**——「该怎么建模」。超级表/子表/标签/度量列的角色分工、一设备一表的代价与收益、自动建表、标签基数、schema 演进限制、3.4 的虚拟表（vtable）。建表前必读。
- **[Storage_Engine](/docs/CS/DB/TDengine/Storage_Engine.md)**——「数据落在哪」。WAL、memtable（红黑树 + 跳表）、TDB 元数据 B+Tree、TSDB 的五类文件（head/data/sma/tomb/stt）、时间分区、一致性哈希分表、四层缓存与默认值。调 `BUFFER`/`PAGES`/`CACHEMODEL` 之前从这页读起。
- **[Compression](/docs/CS/DB/TDengine/Compression.md)**——「压缩率从哪来」。一阶段按列编码（timestamp 差分、整数 zigzag、浮点 delta-delta、字符串字典）、二阶段通用压缩（LZ4/ZLIB/ZSTD/XZ）、有损压缩 TSZ、硬件加速库替换、传输压缩。这是 TDengine "存储不及通用库 1/10" 的来源。
- **[SQL](/docs/CS/DB/TDengine/SQL.md)**——「SQL 到底能写到哪一步」。类 MySQL 方言的时序扩展、窗口算子全家桶、JOIN 的三个版本断点（3.3.0.0 / 3.4.3.0）、查询策略 `queryPolicy`、UDF、TSMA 预计算、虚拟表查询优化。
- **[Stream_Compute](/docs/CS/DB/TDengine/Stream_Compute.md)**——「实时计算和消息队列在哪」。流计算（snode + `CREATE STREAM`，含回填与多种触发方式）与数据订阅 TMQ（topic 三型、消费者组、WAL offset、rebalance）、bnode MQTT 订阅。替代 Kafka + Flink 的那部分。
- **[TDgpt](/docs/CS/DB/TDengine/TDgpt.md)**——「AI 到底跑在哪」。TDgpt 是跑在独立 Anode（Python 动态加载）上的时序分析智能体，通过 `FORECAST()`/`ANOMALY_WINDOW()`/`FILL_HOLE()` 等 SQL 函数提供服务；内置算法库、自研时序基础模型 TDtsfm、自定义算法接入方式。注意它**不在 taosd 进程里**。
- **[Ecosystem](/docs/CS/DB/TDengine/Ecosystem.md)**——「怎么接现有系统」。七门语言连接器、taosAdapter 的协议矩阵（InfluxDB/Prometheus/OpenTSDB 兼容）、taosTools（taosBenchmark/taosdump）、taosX 数据迁移、taosKeeper、Grafana 等第三方集成。
- **[Operations](/docs/CS/DB/TDengine/Operations.md)**——「怎么装、怎么扩、怎么救」。安装包/Docker/K8s 部署、配置项作用域、扩缩容与 rebalance、备份恢复、监控日志、taosBenchmark 压测、3.4 升级的停机约束。

## Applicable Scenarios

TDengine 的甜点区一句话：**采集点数量巨大、schema 同质、按设备维度查询为主、且希望整个实时链路（写入→缓存→订阅→流计算→AI 分析）收在一个系统里**。

适合：

- **工业互联网 / 电力 / 车联网 / IT 运维**：百万级采集点、同类设备同 schema，正是超级表 + 一设备一表的目标负载；国内这几个场景它的安装量最大。
- **不想养 Kafka + Redis + Spark 的系统**：内置消息队列（TMQ）、缓存（last/last_row）、流计算（stream）和 AI 分析，架构上直接砍掉三个外部依赖。
- **需要库内 AI 的场景**：异常检测、预测、补全一条 SQL 搞定，数据不出库；私有化部署同样完整可用（TDgpt 不依赖外部大模型服务）。
- **Prometheus / InfluxDB 生态迁移**：taosAdapter 吃 Line Protocol 与 Prometheus remote 读写，存量采集端可以不改。

不适合：

- **强关系型负载**：虽然 3.3.0.0 起 JOIN 已经相当完整（含 ASOF/WINDOW JOIN），但它终究是为时序优化的引擎，复杂关系建模和 OLTP 事务不是设计目标。
- **多信号可观测统一（metrics + logs + traces）**：纯时序定位，不像 InfluxDB 3.x / GreptimeDB 那样把 logs/traces 当一等公民。
- **对象存储原生的存算分离**：3.4 的存算分离靠 qnode 计算节点 + 企业版共享存储（`SS_*` 参数）实现，社区版没有对象存储卸载这条路。
- **Windows 服务端**：只有企业版支持 Windows server。

| 条件 | 选择 |
| :--- | :--- |
| 百万设备、同 schema、国内 IoT/工业生态 | TDengine |
| 关系 + 时序混合查询 | TimescaleDB |
| 多信号可观测一体化、对象存储 | GreptimeDB / InfluxDB 3.x |
| Prometheus 生态长保留、最轻量 | VictoriaMetrics |
| Apache 生态、树形设备路径 | IoTDB |

## Facts Worth Pinning Down

最容易被默认值、版本和文档惯性坑到的几条，完整清单散布在各分册：

1. **社区版支持 replica 3，不支持 replica 2**。`CREATE DATABASE` 的 `replica` 取值 `1/2/3`、默认 `1`，官方文档原话是"`2` 仅在企业版支持"——即多副本高可用（3 副本）是开源能力，双副本反而是企业版限定。副本数必须 ≤ dnode 数；单副本可变双副本，但双副本不能转其他副本数、三副本不能转双副本。
2. **`WAL_LEVEL` 默认 1，不 fsync**。写 WAL 但数据只到文件系统缓存，掉电丢最近写入；要可靠性得显式 `WAL_LEVEL 2`（配 `WAL_FSYNC_PERIOD`，默认 3000 ms）。性能/可靠权衡是建库时的显式决策。
3. **JOIN 不是"不支持"，而是分三步开放的**：3.3.0.0 之前只有 INNER；3.3.0.0 起有 LEFT/RIGHT/FULL/SEMI/ANTI-SEMI 和时序特色的 ASOF/WINDOW JOIN；3.4.3.0 起才有显式 CROSS JOIN、无条件逗号 join 与混合嵌套 JOIN。按"TDengine 无 JOIN"做选型结论会直接错。
4. **浮点列压缩是 delta-delta，不是 XOR**。官方压缩文档：timestamp 用相邻差分、数值统一 zigzag、float/double 用 delta-delta、布尔按位紧致、字符串字典编码；之后再过一层通用压缩。网上（含早期二手资料）流传的"浮点 XOR"是错的。
5. **`CACHEMODEL` 默认 `none`**——读缓存默认关闭。一旦设为 `last_row`/`last_value`/`both`，每个 vnode 会额外拉起一个**持久化 RocksDB 实例**做 last cache，`sLastCache*` 参数（`taos.cfg`）都是惰性生效，改完要重启 dnode。
6. **`KEEP` 默认 3650 天且必须 ≥ 3 × `DURATION`**（`DURATION` 默认 10d）。设 `KEEP 30` 而 `DURATION` 默认 10d 是合法边界；社区版配多个 `KEEP` 不生效，只取最大值（多级存储是企业版）。
7. **TDgpt 不在 taosd 里**。查询涉及时序 AI 时 vnode 把请求转发到独立组件 Anode（Python 算法动态加载），部署 TDgpt 要单独装它，不是 taosd 的自带功能。
8. **TMQ 的 offset 是 WAL 版本号**，消费单位是 vnode（对标 Kafka partition），语义 at-least-once；消费者组 rebalance 每 2 秒检查一次，心跳超时 `session.timeout.ms` 默认 45 s（v3.4.3.6 起，此前 12 s）。
9. **3.4 起 OSS 客户端连不上 Enterprise 服务端，且不支持滚动升级**。混合部署和滚动发布计划都要按这条重新排。
10. **表在 vnode 间的分布是一致性哈希**，不由表名算法细节外露；查询超级表时 taosc 先向 mnode 要元数据、再扇出到各 vnode 本地计算，最后由 qnode（或缺省 vnode）做全局聚合——这条两阶段路径是超级表查询延迟的主要构成。

## Links

- [Timeseries](/docs/CS/DB/Concept/Timeseries.md)
- [InfluxDB](/docs/CS/DB/InfluxDB/InfluxDB.md)
- [IoTDB](/docs/CS/DB/Timeseries/IoTDB.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)
- [WAL](/docs/CS/DB/Concept/WAL.md)
- [DataBases](/docs/CS/DB/DB.md)

## References

1. [TDengine TSDB 官方文档](https://docs.taosdata.com/)
2. [taosdata/TDengine README-CN](https://github.com/taosdata/TDengine/blob/main/README-CN.md)
3. [TDengine TSDB 3.4 Release Notes](https://tdengine.com/?p=30263/)
4. [技术内幕：整体架构](https://docs.taosdata.com/internals/arch/)
5. [TDengine SQL：CREATE DATABASE](https://docs.taosdata.com/reference/taos-sql/database/)
6. [TDgpt：背景介绍](https://docs.taosdata.com/ai-and-advanced-analytics/tdgpt/introduction)
