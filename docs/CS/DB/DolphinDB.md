## Introduction

DolphinDB 是浙江智臾科技有限公司（2016 年成立于杭州）自研的 C++ 实时计算平台，定位是「以高性能时序数据库为核心，向上覆盖复杂分析、流计算与机器学习的一体化数据底座」。它在本库其它时序产品里的位置比较特殊：TDengine 是纯存储引擎，InfluxDB 3.x 是可观测三信号，而 DolphinDB 把**多模存储引擎 + 内置编程语言 + 流批一体的计算框架**打包进同一个集群——用户面对的不只是一个库，而是一个「库内编程」的分析平台。

版本基线：当前主线 **3.00.x**（2026-10 已发布 3.00.6），2.00 维护线同步发布 2.00.19；TSDB 存储引擎自 **2.0** 版本引入。分社区版与企业版，社区版已覆盖集群、多模引擎与主要 SDK，企业版增量在安全、运维与 AI 平台化能力上。

## Architecture

集群模式由四类进程组成，单节点模式则把 DataNode 与 Controller 合进一个进程，供本地验证与小规模试用：

| 组件 | 职责 |
| :-- | :-- |
| **Controller** | 集群元数据管家：分区与副本分布、分区版本号、事务日志。多个 Controller 组成一个 **Raft 组**，只有 Leader 与数据节点交互，日志同步到多数派后才告知提交；Leader 宕机立即重选。要元数据高可用，Controller 至少 3 个（容忍少于半数故障），且副本数必须大于 1 |
| **Agent** | 接收 Controller 指令，管理本机节点的启停 |
| **DataNode** | 数据存储 + 主要查询与计算任务的承担者 |
| **ComputeNode** | 只算不存，用于存算分离场景 |

高可用分四层，覆盖的故障类型不同：

- **数据高可用**：同一分区的数据写入多个节点成为副本，副本间用轻量的**两阶段提交（2PC）**保证一致，节点损坏可读其它副本并经 recovery 修复；生产环境副本数一般大于 2。注意 DolphinDB 的数据副本走 2PC 而不是 Raft——共识只用在 Controller 元数据上。
- **集群高可用**：即 Controller 的 Raft 组，见上表。
- **流表高可用**：基于 **Raft Learner** 的跨集群复制——Learner 从主集群同步日志但不参与投票，且只允许跨集群部署（Voter 必须同集群内），用于跨集群容灾与读写隔离。
- **客户端高可用**：API 自动重连，失败时透明切换到其它可用节点。

分布式底座是 shared-nothing：自研分布式文件系统 + 分区元数据由 Controller 统一管理，支持在线/离线两种方式的水平与垂直扩展、无缝数据迁移与再平衡，另有备份恢复与跨地域异步复制（低延迟、高吞吐，不阻塞主集群写入）。

## Storage Engines

DolphinDB 的招牌能力是**多模存储引擎**：五套引擎在同一集群内并存，按表选择，共享同一套 SQL 与分布式调度：

| 引擎 | 布局 | 解决的问题 |
| :-- | :-- | :-- |
| **TSDB** | PAX 行列混存，基于 LSM-Tree | 高频时序数据的写入、点查与聚合的平衡；2.0 引入 |
| **OLAP** | 列式 | 长时间跨度某些列的聚合计算，比 TSDB 更适合离线分析 |
| **PKEY** | 主键唯一约束 + 实时更新 | 从 OLTP 主键表 CDC 进 DolphinDB 做分析，替代「先删再插」 |
| **IMOLTP** | 内存行存 + 事务 + B+ 树索引 | 高频度高并发的更新与查询，数据全在内存 |
| **VECTORDB** | 向量索引 + 近似最近邻搜索 | 大规模向量检索，支撑库内 RAG |

全引擎保证事务 ACID 与快照级隔离；无损压缩支持 LZ4（默认）、zstd、delta（delta-of-delta）、chimp（小数部分不超过三位的 DOUBLE）与 SYMBOL 字典编码，整体压缩率 4:1~10:1，金融数据落盘常见 20%~30%；另支持热冷分级存储降低成本。

### TSDB Engine

TSDB 引擎的设计可以浓缩成一句话：**用 sortKey 换索引，用 block 换压缩**。

建表时通过必选参数 `sortColumns` 声明排序列，规则很硬：

- 最后一列必须是时间类型或整型，其余列的组合即 **sortKey**（索引键 sortKeyEntry）；只有一列时该列就是 sortKey。
- `sortColumns` 决定索引键值、数据排序与数据去重三件事；`keepDuplicates` 取 `ALL`（默认）/ `LAST`（只留最新）/ `FIRST`（只留第一条）。
- 仅支持 INTEGER / TEMPORAL / STRING / SYMBOL 类型，sortKey 不能是 TIME、TIMESTAMP、NANOTIME、NANOTIMESTAMP。
- 官方调优口径：`sortColumns` 列数不超过 4，单分区 sortKey 组合数宜小于 2000。

每个 sortKey 的数据按列存储，列内按固定行数切成 block，block 内部按最后一列排序、block 间保持对齐。刷盘时生成 **Level File**，其尾部挂两类元数据：

| 元数据 | 内容 | 用途 |
| :-- | :-- | :-- |
| **zonemap** | 每列、每 sortKey 的 min、max、sum、notnullcount | 查询时按 block 过滤，跳过不相关块 |
| **indexes** | sortKey 个数、每 sortKey 记录数、每列 block 的文件偏移、checksum | 先定位 sortKey，再定位 block |

索引信息惰性加载进内存索引区（首次命中分区时加载、之后常驻，`TSDBLevelFileIndexCacheSize` 默认取 `maxMemSize` 的 5%，内存不足时置换），查询路径因此是「indexes 定位 sortKey → zonemap 过滤 block → 读取并解压目标 block」三步，不碰无关数据。

两个容易踩的坑，文档有明确提醒：其一，DolphinDB 不支持约束语义，**不要把主键/唯一约束设为 sortColumns**——sortKey 组合过少会让单个 sortKey 下的数据量膨胀，极端情况可达 50 倍；其二，更新与删除产生的旧版本分区文件默认 30 分钟定时回收，删大分区后的空间释放有滞后。

## Query Language

DolphinDB 内置一门图灵完备的脚本语言，支持命令式、函数式、向量化与 SQL 四种范式混编（hybrid programming），配套 2000+ 内置函数（数学、统计、金融分析为主），分布式侧提供 pipeline、Map-Reduce 与迭代计算三种模型。SQL 侧兼容 **SQL-92**，并扩展组内计算（context by）、透视表等语法，同时兼容 Oracle 与 MySQL 主流方言——迁移成本主要不在 SQL 本身，而在把存储过程逻辑改写成库内脚本。

## Stream Processing

流计算是 DolphinDB 与其它时序库拉开差距的一层，能力覆盖「接入 → 计算 → 回放 → 容灾」全链路：

- 流数据表（stream table）负责订阅发布，可对接多种数据源实时写入。
- 内置计算引擎：时间序列聚合、横截面处理、响应式状态、异常检测、会话窗口、多表关联；引擎可串联成流水线，或用 streamEngineParser 自动构建。
- 历史回放支持 1 对 1、N 对 N、N 对 1 三种形式。
- **流批一体**：历史数据上建模得到的因子/表达式直接用于实时流，保证流计算结果与批量计算完全一致——量化研究的核心诉求。
- 内置 CEP（复杂事件处理）引擎，支持事件检测与规则回调；官方口径延迟亚毫秒级。

## Ecosystem and AI

- SDK：Python、C++、C#、Go、R、JavaScript。
- 客户端：Web 集群管理器、VS Code 插件、Java GUI、Jupyter Notebook、终端。
- 插件与模块：行情接入、DataX 数据导入、Grafana 可视化，以及技术指标库、因子库（WorldQuant 101 Alpha、国泰君安 191 Alpha）、多因子风险模型、交易日历等开箱模块。
- AI：VECTORDB 引擎支持十亿级向量存储与毫秒级 ANN；LibTorch 插件可在库内加载 PyTorch 模型做预测，另兼容 TensorFlow、XGBoost、LightGBM；GPU 异构计算平台 Shark 承接计算密集型任务；3.00 起原生支持 MCP 协议，LLM 可直接把库内函数当工具调用。

## Comparison

| 维度 | DolphinDB | TDengine | InfluxDB 3.x | ClickHouse | TimescaleDB |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 语言 | C++ | C | Rust | C++ | C（PG 扩展） |
| 定位 | 时序 + 分析 + 流计算平台 | 纯时序数据库 | 可观测三信号 | 列式 OLAP | 关系 + 时序混合 |
| 存储引擎 | 五引擎多模（TSDB/OLAP/PKEY/IMOLTP/VECTORDB） | 列式 LSM | Arrow + Parquet + DataFusion | MergeTree | PG 行存 + 列式压缩 |
| 集群共识 | Controller Raft；数据副本 2PC | mnode Raft | 无共识（对象存储） | 复制表 / ZooKeeper | 靠 PG 复制 |
| 存算分离 | ✅（ComputeNode） | ❌ | ✅ 对象存储原生 | ❌ | ❌ |
| 流计算 | ✅ 流批一体 + CEP | CREATE CONTINUOUS QUERY | ❌ | 物化视图 | 连续聚合 |
| SQL | SQL-92 + Oracle/MySQL 方言 | 类 MySQL（无 JOIN） | SQL + InfluxQL | 自有 SQL 方言 | 完整 PostgreSQL SQL |
| 典型场景 | 金融量化、电力、工业高频数据 | 国内 IoT、电力 | 可观测一体化 | 通用 OLAP、日志 | 关系 + 时序混合 |

与同门的 TDengine 对比最能看出路线差异：TDengine 用「一设备一表」把 schema 决策前移，DolphinDB 则用 sortKey + 分区把索引决策交给库内脚本，换取分析表达能力的上限；与 ClickHouse 对比，DolphinDB 多了流批一体与多模引擎，ClickHouse 的生态与纯 OLAP 性能仍是更稳的选择。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Timeseries](/docs/CS/DB/Timeseries.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)
- [WAL](/docs/CS/DB/WAL.md)
- [ClickHouse](/docs/CS/DB/ClickHouse.md)
- [TDengine](/docs/CS/DB/TDengine.md)
- [InfluxDB](/docs/CS/DB/InfluxDB.md)
- [vector](/docs/CS/DB/vector.md)

## References

1. [DolphinDB 官方文档中心](https://docs.dolphindb.cn/)
2. [TSDB 存储引擎](https://docs.dolphindb.cn/zh/db_distr_comp/db/tsdb.html)
3. [高可用](https://docs.dolphindb.cn/zh/db_distr_comp/db/ha.html)
4. [流数据](https://docs.dolphindb.cn/zh/stream/str_intro.html)
5. [VECTORDB 引擎](https://docs.dolphindb.cn/zh/db_distr_comp/db/vectordb.html)
6. [DolphinDB V3.00.6 & V2.00.19 发布说明](https://www.dolphindb.com/news/detail/242)
7. [关于智臾科技](https://dolphindb.cn/about-us/company-profile)
