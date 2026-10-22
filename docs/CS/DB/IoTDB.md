## Introduction

Apache IoTDB 是 Apache 顶级项目，面向 IoT 场景的时序数据库。它的核心设计是**围绕工业物联网的数据特点**——设备层级树、海量设备（百万级）、高频采样（毫秒级）、乱序到达、数据量大但价值密度低——打造一套轻量、高压缩、分布式的存储和查询栈。

当前版本 **2.x**（2.0.6 为最新稳定版），最大变化是正式支持**双模式**：老的 tree model（层级路径存储）和新的 table model（关系表语法）。2026 年下半年发布了 **AI Node**——把时序特征分析和 ML 模型训练推理整合进 IoTDB 生态。

IoTDB 与 TDengine 有明显同构——两者都面向 IoT、都自研列式格式、都做超高压缩。但 IoTDB 走 Apache 基金会路线、有 Hadoop/Spark/TensorFlow 生态对接、TsFile 格式被独立纳入 Apache 项目；TDengine 是商业公司开源路线、一设备一表的物理边界更激进、在国内电力/工业场景有巨大安装量。

## Architecture

IoTDB 单机就是一个 JVM 进程；集群是 **3 ConfigNode + ≥3 DataNode**（典型 3C3D）的 MPP 架构：

| 组件 | 职责 |
| :-- | :-- |
| **ConfigNode**（3 个，Raft HA） | 元数据管理、表/设备 schema、权限、分片策略、负载均衡、调度。2.x 把元数据从 DataNode 彻底抽离 |
| **DataNode**（≥ 3 个） | 数据存储与查询执行的核心单元。每个 DataNode 内部有独立的列式 LSM 引擎、写 WAL、内存 memtable、后台 compaction |
| **AINode**（可选） | 2.x 新增，时序特征工程 + ML 模型训练/推理的统一引擎，可从 IoTDB / TsFile 直接取数据 |
| **TsFile Connector** | 让 Hadoop、Spark、Flink 直接读 TsFile 做分析，跳过 IoTDB 引擎 |

### 数据分片

IoTDB 的数据分片是**两个维度**的：

1. **设备维度（Meta Partition）**：ConfigNode 按设备 ID（root.sg1.d1、root.sg2.d1……）做哈希分片，不同设备的时序分到不同 DataNode。
2. **时间维度（Time Partition）**：每个设备内的数据按时间窗口（默认 7 天）切成 TimePartition，每个 TimePartition 对应一组 TsFile。

这种设计让 IoTDB 能**在设备层面独立伸缩**——某个 DataNode 热了只需要把它上面的设备迁移到冷节点，不影响其他设备；同时时间维度的切分让 TTL 删除和 compaction 都非常高效。

## Data Model

IoTDB 2.x 正式支持**两种数据模型并存**：

### Tree Model（老模式，兼容）

路径式层级存储——最符合工业 IoT 的设备层级习惯：

```sql
-- 层级定义：root(根) → sg(storage group) → d(device) → m(measurement)
CREATE STORAGE GROUP TO root.sg1;
CREATE TIMESERIES root.sg1.d1.m1 WITH DATATYPE=INT32, ENCODING=RLE;
CREATE TIMESERIES root.sg1.d1.m2 WITH DATATYPE=FLOAT, ENCODING=GORILLA;

INSERT INTO root.sg1.d1(timestamp, m1, m2) VALUES (1713715200000, 1234, 45.6);
```

tree model 的优势：
- 零 schema 管理压力——直接写路径即可，不需要 CREATE TABLE。
- 工业设备层级天然对齐——`root.factory1.assembly_line3.robot7.sensor1`。
- 写入侧极轻量——不需要维护标签字典。

### Table Model（新模式，SQL-first）

2.0 引入，把时序数据放进关系表里——如果知道设备类型、需要结构化标签和 SQL JOIN，table model 更合适：

```sql
CREATE TABLE device_readings (
    time          TIMESTAMP,
    device_id     STRING TAG,    -- TAG 列，类似 InfluxDB 的 tag
    region        STRING TAG,
    temperature   FLOAT FIELD,
    humidity      FLOAT FIELD,
    PRIMARY KEY(time, device_id)
);

INSERT INTO device_readings VALUES (now(), 'dev-001', 'us-east', 23.4, 45.2);
```

table model 的优势：
- 直接 SQL（带 JOIN、聚合、窗口函数），不用学 IoTDB 特定路径语法。
- TAG / FIELD 分离——存储层物理独立 TAG 列、大幅减少扫描量。
- 与 GreptimeDB、InfluxDB 3.x 的数据模型非常相似，迁移路径清晰。

### 两种模型共存

一个 IoTDB 实例可以同时跑 tree model 和 table model——两者物理存储都落到 Apache TsFile 格式上，只是上层抽象不同。选择哪种模型取决于你的 schema 管理需求和查询习惯。

## TsFile

**Apache TsFile** 是 IoTDB 自研的列式存储格式，已独立为 Apache 顶级项目。它是 IoTDB 的一切——内存 memtable flush、持久化落盘、HDFS 上的冷存储、Spark/Hadoop 的离线分析，都围绕 TsFile 展开。

### TsFile 内部结构

一个 TsFile 文件内部是一系列 Chunk + Index：

```
┌──────────────────────────────────────────────────────────┐
│  Chunk 1: measurement = temperature                      │  ← 一列的数据块
│    ├── Page 1: [ts1, v1, ts2, v2, ...]                    │
│    ├── Page 2: [ts101, v101, ...]                          │
│    └── ...                                                 │
├──────────────────────────────────────────────────────────┤
│  Chunk 2: measurement = humidity                          │
│    └── ...                                                 │
├──────────────────────────────────────────────────────────┤
│  Chunk 3: measurement = voltage                            │
│    └── ...                                                 │
├──────────────────────────────────────────────────────────┤
│  Time Index Tree                                           │  ← 所有 chunk 的时间范围索引
├──────────────────────────────────────────────────────────┤
│  Metadata（各 chunk 的统计信息 + Schema）                   │
└──────────────────────────────────────────────────────────┘
```

### 压缩算法（每列独立选择）

| 列类型 | IoTDB 压缩 | 说明 |
| :-- | :-- | :-- |
| **timestamp** | **Delta-of-Delta + PLAIN** | 二阶差分 + 简单编码 |
| **INT32/INT64** | **RLE + Snappy** | 工业数据相邻值经常相等，RLE 完美 |
| **FLOAT/DOUBLE** | **Gorilla** | 相邻浮点值 XOR 压缩 |
| **STRING** | **DTLZ（字典 + 截尾）+ Snappy** | 工业场景值种类有限 |
| **BOOLEAN** | **RLE** | 同上 |

典型压缩率 **10~20x**。IoTDB 让用户在建表时就指定编码算法（`ENCODING=GORILLA`），之后无法更改——设计意图是：工业物联网场景每个 measurement 的数据类型特征是固定的，提前选好编码让压缩率最大化。

### LSM 引擎

IoTDB 的存储引擎是列式 LSM：

```
  WAL（本地磁盘）  ←── 接受写入、durability
       │
       ▼
  Memtable（内存，列式）
       │ size / time 触发 flush
       ▼
  TsFile（Level 0, 不可变）
       │
       ▼ compaction（后台合并小文件）
       │
       ▼
  TsFile（Level 1+, 合并后、更大）
```

每个 DataNode 内部管理自己的一组 LSM——不同 DataNode 的 TsFile 之间不做复制（企业版支持副本）。

## Query

IoTDB 使用 **SQL-like 方言**，tree model 和 table model 语法不同：

### Tree Model 查询

```sql
-- 按路径查
SELECT * FROM root.sg1.d1;
SELECT m1, m2 FROM root.sg1.d1 WHERE time > now() - 1d;

-- 跨设备聚合（GROUP BY DEVICE）
SELECT AVG(m1), MAX(m2)
FROM root.sg1.* 
WHERE time > now() - 1d
GROUP BY DEVICE;

-- 带时间桶
SELECT AVG(m1)
FROM root.sg1.d1
GROUP BY time(1h);
```

### Table Model 查询

就是标准 SQL：

```sql
SELECT device_id, region, AVG(temperature)
FROM device_readings
WHERE time > now() - INTERVAL '7 days'
GROUP BY device_id, region;
```

### 序列对齐（Timestamp Alignment）

IoTDB 的特色功能——不同 measurement 采样频率不同（有的 1s、有的 10s），JOIN 时自动按时间对齐：

```sql
-- m1（1s 间隔）和 m2（10s 间隔）的时间自动对齐
SELECT m1, m2 FROM root.sg1.d1;
```

## Ingestion

| 协议 | 说明 |
| :-- | :-- |
| **Thrift** | 原生协议，Java/C++/Python/Go/Rust SDK 都基于它 |
| **MQTT** | IoT 设备直接对接（工业标准协议） |
| **HTTP REST** | 简单场景 |
| **Influx Line Protocol** | 兼容 InfluxDB 生态 |
| **OpenTSDB / Prometheus** | 2.x 提供部分兼容层 |
| **JDBC（table model）** | table model 下走标准 JDBC |

## Cluster

3C3D 是官方推荐的最小集群：

- **ConfigNode × 3**：Raft HA，一个 leader 两个 follower。leader 负责元数据变更、分片调度、负载均衡。
- **DataNode × 3+**：每个 DataNode 持有若干设备分片（Meta Partition）+ 若干时间窗口（Time Partition）。新节点加入后 ConfigNode 自动 rebalance。
- **AINode**：可选，分布式场景下可以挂在集群旁边做训练推理。

IoTDB 集群**默认不做副本**——工业场景对 RPO/RTO 要求通常没有金融那么严，副本靠本地 RAID 或快照/归档解决。

## Comparison

| 维度 | IoTDB | TDengine | InfluxDB 3.x | GreptimeDB | TimescaleDB | QuestDB |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 语言 | Java | C | Rust | Rust | C（PG 扩展） | Java+C+++Rust |
| 组织 | Apache 顶级 | 商业公司开源 | 商业公司开源 | 商业公司开源 | 商业公司开源 | 商业公司开源 |
| 存储格式 | **TsFile（Apache 独立项目）** | 自研列式 LSM | Arrow + Parquet | Mito LSM + Parquet SST | PG 行存 + 列式压缩 | WAL + 本地列式 + Parquet 冷 |
| LSM | ✅ 列式 | ✅ 列式 | Ingester buffer + Parquet | ✅ | ❌（PG 自带 + 列式压缩） | ❌（WAL + 分区） |
| 集群 | ConfigNode(3) + DataNode(3+) | mnode(Raft) + vnode | Router + Ingester + Querier | Metasrv + Frontend + Datanode | 靠 PG 复制 | 单机为主 |
| 设备分片 | Meta Partition（设备维度） | 一设备一表 | 无特殊设备分片 | Region | 无 | 无 |
| 数据模型 | 双模式：tree（路径）+ table（TAG/FIELD） | supertable + 一设备一表 | measurement + tag + fields | Tag + Timestamp + Field | 关系表 | symbol + timestamp + 多列 |
| SQL | 类 SQL（双模型语法不同） | 类 MySQL（无 JOIN） | ✅ DataFusion | ✅ | ✅ 完整 PG | ✅ 普通 + SAMPLE BY + ASOF |
| PromQL | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| 对象存储 | ❌（本地 + HDFS） | ❌ | ✅ | ✅ | ❌ | Tier 3 冷层 |
| 乱序处理 | 写入侧接受 | 写入侧接受 | Ingester buffer | merge mode | PG 自动合并 | WAL buffer 5s |
| AINode | ✅ 2.x 新增 | ❌ | ❌ | ❌ | ❌ | ❌ |
| 生态对接 | Hadoop + Spark + Flink TsFile Connector | 有限 | DataFusion（Arrow/Paraquet 天然对接） | Arrow/Paraquet | PostgreSQL 生态 | Parquet 冷层 |

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Timeseries](/docs/CS/DB/Timeseries.md)
- [TDengine](/docs/CS/DB/TDengine.md)
- [InfluxDB](/docs/CS/DB/InfluxDB.md)
- [GreptimeDB](/docs/CS/DB/GreptimeDB.md)
- [TimescaleDB](/docs/CS/DB/TimescaleDB.md)
- [QuestDB](/docs/CS/DB/QuestDB.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)
- [WAL](/docs/CS/DB/WAL.md)

## References

1. [Apache IoTDB 官方文档](https://iotdb.apache.org/UserGuide/latest/)
2. [IoTDB Architecture](https://iotdb.apache.org/UserGuide/latest/IoTDB-Introduction/IoTDB-Introduction_apache.html)
3. [Apache TsFile](https://tsfile.apache.org/) — 独立 Apache 项目
4. [IoTDB 2.0 Release History](https://iotdb.apache.org/UserGuide/latest/IoTDB-Introduction/Release-history_apache.html)
5. [ACM: Apache IoTDB Paper](https://dl.acm.org/doi/10.1145/3589775)
