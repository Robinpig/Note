## Introduction

TDengine 是 C 写的国产时序数据库，由涛思数据（TAOS Data）开发，核心设计思路是"**一设备一表**"（One table per device）——每个数据采集点（传感器、电表、汽车、机器人……）对应一张独立表，同类采集点共享 schema 但拥有自己的静态标签。这套设计让 TDengine 在 IoT、电力、工业物联网、车联网场景尤其受欢迎，目前在国内这几个领域是安装量最大的时序数据库之一。

TDengine 当前稳定版本 **3.x / 4.x**。它的开源版（TDengine Community）和商业版功能差距比其他时序库小得多——社区版已经包含分布式集群、C 驱动、HTTP API、Prometheus 协议支持、生态对接等能力。

## Architecture

TDengine 的集群架构是典型的 "mnode 管理 + vnode 数据" 模式：

| 组件 | 运行在哪 | 职责 |
| :-- | :-- | :-- |
| **mnode（Management Node）** | dnode 内（可与 vnode 共置） | 集群元数据管理、用户权限、schema、拓扑、调度。**Raft 共识**实现 HA，最多 3 个 mnode 组成 HA 组 |
| **vnode（Virtual Node）** | dnode 内 | 数据存储与查询执行的核心单元。一个 vnode 管理 supertable/subtable 的一个子集，内部有独立的列式 LSM |
| **dnode（Data Node）** | 独立进程 `taosd` | 一个物理节点，承载 1+ mnode + 0+ vnode。多 dnode 组成集群 |
| **taosc** | 客户端 | C 语言驱动库，被各语言绑定（Python/Go/Java/Node/Rust）调用。**无状态、直连** |
| **taosAdapter** | 独立进程 | HTTP/gRPC/Prometheus/InfluxDB Line Protocol/OpenTSDB 的协议适配层——让 TDengine 不用改内核就能对接主流生态 |
| **taosCLI** | 独立进程 | 命令行管理工具 |

与其他时序库的关键差异：mnode 用 Raft 共识做元数据 HA，vnode 之间的数据分片和负载均衡由 mnode 调度——不需要自己做分片管理和 vnode 间的共识复制（TDengine 默认不做数据副本，副本是企业版特性）。

```
          mnode (Raft)
         /     \
     dnode-1  dnode-2        客户端 → taosAdapter / taosc
    ┌──────┐  ┌──────┐
    │vnode │  │vnode │       vnode 内部：
    │  SST │  │  SST │         ┌───────────────┐
    └──────┘  └──────┘         │  WAL + Memtable │
                               ├───────────────┤
                               │  SST (列式)    │
                               └───────────────┘
```

## Data Model

TDengine 对时序数据的核心建模只有三个概念：

| 概念 | 含义 | 类比关系库 |
| :-- | :-- | :-- |
| **supertable（STable）** | 同类采集点的集合，定义共享 schema | 类似 CREATE TABLE 声明 + 标签模板 |
| **table（subtable）** | 单个采集点，有独立的表名和静态 tag 值 | 类似每个设备一张独立表 |
| **column** | 三种角色：timestamp（时间戳）、metric（动态测量值）、tag（静态标签） | 关系列，但 tag/metric 物理分开存储 |

建表示例（监控 1000 个电表的耗电量和电压）：

```sql
-- 1. 先建超级表：所有电表的 schema + tag 定义
CREATE STABLE meters (
    ts        TIMESTAMP,
    current   FLOAT,      -- metric：动态采集值
    voltage   FLOAT       -- metric
) TAGS (
    groupid   INT,        -- tag：静态，安装时确定，采集时不变
    location  BINARY(64)  -- tag
);

-- 2. 每个电表一张子表，自动从 supertable 继承 schema
CREATE TABLE meters_001 USING meters TAGS (groupid=1, location='北京');
CREATE TABLE meters_002 USING meters TAGS (groupid=1, location='上海');
-- ... 可以有几百万张子表
```

### 为什么"一设备一表"是关键设计

- **零写入开销**：每个子表独立追加写，不需要全局协调器，写入路径极短。
- **天然负载隔离**：热设备的写压不会影响冷设备。
- **高效聚合查询**：查询 supertable 时 TDengine 自动并发向所有子表拉数据、做聚合——不需要在应用层做 UNION ALL。
- **标签分离存储**：tag 列（静态）和 metric 列（动态）物理分开存放，聚合查询只扫 metric 列 + 少量 tag 索引，扫描体积远小于传统宽列模型。

### 与其他时序库的数据模型对比

| 产品 | 等价概念 | 差异 |
| :-- | :-- | :-- |
| InfluxDB | measurement → supertable, tag values → subtable id | InfluxDB 用一个 measurement 存全部数据、用 tag 区分序列；TDengine 是真的多张表 |
| VictoriaMetrics / Prometheus | metric name + labels → 单一序列 | 标签不同就是不同序列，但仍然存在同一个 metric name 下；不存在"每个 tag 组合独立表"的物理边界 |
| GreptimeDB | PRIMARY KEY(tag, ...) 把标签放一个表 | GreptimeDB 一张表包含所有 tag 组合，靠 PRIMARY KEY 排序保证局部性 |

## Storage Engine

TDengine 的存储引擎是一个**列式 LSM Tree**——每条 SSTable 内部按列独立存储和压缩。

### WAL + Memtable

- WAL 本地磁盘，保护尚未 flush 的内存数据。
- Memtable 按列组织：一个 vnode 里所有子表的 metric 列和 timestamp 列分别存在各自的内存 buffer 里。
- Flush 时把 memtable 转成不可变 SST 文件，按 vnode 目录组织。

### SSTable 列式存储

每个 SST 文件内部是列式布局——一个子表的时间戳列全堆在一起，current 列全堆在一起，voltage 列全堆在一起。每列独立压缩：

| 列类型 | 算法 | 适用场景 |
| :-- | :-- | :-- |
| **timestamp** | **delta-of-delta**（二阶差分） | 相邻时间戳差值通常稳定（如 5 秒、1 分钟） |
| **integer** | **ZigZag + delta** | 有符号整数先 ZigZag 转无符号再做差值编码 |
| **float/double** | **XOR** | 相邻浮点值 XOR 后零值极多 |
| **string（低基数 tag）** | 字典编码 | tag 值种类有限，字典表存一次 |

典型压缩率 **10-20x**。压缩后列文件直接写入 vnode 目录，底层用 `mmap` 访问。

### Compaction

TDengine 的 compaction 是**按子表内部做**，不跨子表合并——一设备一表的边界直接变成了 compaction 边界，避免了 LSM Tree 常见的"合并时扫描全数据集"的问题。

### 查询路径

查询 supertable 时：
1. mnode 把 query 下发到所有相关 vnode。
2. 每个 vnode 并发向其持有的子表集合发查询——只扫 metric 列 + tag 索引。
3. 所有 vnode 并行返回局部结果，mnode 汇总后返回给客户端。
4. 时间范围查询自动跳过不相关 SST 文件。

## Query Language

TDengine 使用**类 MySQL SQL**——大部分语法能直接用，但有以下扩展：

| 扩展 | 示例 |
| :-- | :-- |
| Supertable 关键字 | `CREATE STABLE meters (...) TAGS (...);` |
| TAGS 子句 | `WHERE groupid = 1 AND location = '北京'`（直接在 supertable 上过滤 tag） |
| Show supertable | `SHOW STABLES;` |
| 采样函数 | `_wstart`（窗口起始时间）、`_wend`（窗口结束） |
| 时间间隔语法 | `INTERVAL(5m)`、`INTERVAL(1d, start_time)` |
| 流式计算 | `CREATE CONTINUOUS QUERY`（类似 InfluxDB CQ） |

TDengine SQL **不支持 JOIN**——设计哲学是 tag 列和 metric 列已经在 supertable 聚合查询中自然分离，不需要跨表 JOIN。

## Comparison

| 维度 | TDengine | TimescaleDB | InfluxDB 3.x | GreptimeDB | VictoriaMetrics |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 语言 | C | C（PostgreSQL 扩展） | Rust | Rust | Go |
| 数据模型 | supertable + 一设备一表 | hypertable + 时间分区 | measurement + tag + fields | Tag + Timestamp + Field | metric + labels |
| 存储引擎 | 列式 LSM（自研） | PostgreSQL 行存 + 列式压缩 | Arrow + Parquet + DataFusion | Mito LSM + Parquet SST | 自研 LSM part |
| WAL | ✅ | ✅（PG 自带） | ✅（可关） | ✅ 多模式 | ❌ |
| SQL | 类 MySQL SQL（无 JOIN） | 完整 PostgreSQL SQL | SQL + InfluxQL | SQL + PromQL | ❌ |
| 集群组件 | mnode（Raft）+ vnode | 靠 PG 复制 | Router + Ingester + Querier | Metasrv + Frontend + Datanode | vminsert + vmstorage + vmselect |
| 存算分离 | ❌ | ❌ | ✅ 对象存储原生 | ✅ 对象存储原生 | ❌ |
| 多信号 | ❌（纯时序） | ❌（纯时序） | metrics + logs + traces | metrics + logs + traces | metrics only |
| 一设备一表 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 典型场景 | 国内 IoT、电力、工业 | 关系 + 时序混合 | 可观测一体化 | 可观测统一 + 对象存储 | Prom 生态长保留 |

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Timeseries](/docs/CS/DB/Timeseries.md)
- [InfluxDB](/docs/CS/DB/InfluxDB.md)
- [GreptimeDB](/docs/CS/DB/GreptimeDB.md)
- [TimescaleDB](/docs/CS/DB/TimescaleDB.md)
- [VictoriaMetrics](/docs/CS/DB/VictoriaMetrics.md)
- [QuestDB](/docs/CS/DB/QuestDB.md)
- [IoTDB](/docs/CS/DB/IoTDB.md)
- [OpenTSDB](/docs/CS/DB/OpenTSDB.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)
- [WAL](/docs/CS/DB/WAL.md)

## References

1. [TDengine 官方文档](https://docs.taosdata.com/)
2. [TDengine TSDB Architecture](https://tdengine.com/tsdb-architecture-core-technology-explained/)
3. [TDengine 2026 Product White Paper](https://content.tdengine.com/hubfs/Downloads/TDengine%202026%20Product%20White%20Paper-v5-compressed.pdf)
4. [Supertable Design](https://tdengine.com/data-modeling-practice-guide-super-table-creation/)
5. [TDengine 开源版 vs 企业版](https://www.taosdata.com/enterprise)
