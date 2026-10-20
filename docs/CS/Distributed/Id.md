## Introduction

在单机时代，数据库自增主键（AUTO_INCREMENT）足以充当业务唯一标识。一旦系统演进为分布式——数据分库分表、服务多实例部署、跨数据中心写入——"在同一时刻、由不同节点生成、且全局不重复"的 ID 就成了基础需求。

所谓**分布式 ID（distributed unique ID）**，是指由发号逻辑在多个独立节点上生成、保证全局唯一、且通常还追求高性能与高可用的标识符。它的本质难点不在"生成"，而在于：在**无全局时钟、节点独立失效、网络不可靠**的前提下（见 [Distributed Systems](/docs/CS/Distributed/Distributed.md)），如何用局部信息推导出全局不冲突的结果。

本页按"有状态 / 无状态"两个大类梳理方案，并对照工业级开源实现，最后给出选型对比与踩坑清单。

## Requirements

一个合格的分布式 ID 方案通常要满足：

- **全局唯一（Uniqueness）**：最基本、不可妥协的硬约束。
- **高性能（High Performance）**：生成延迟低、吞吐高，不能成为业务关键路径的瓶颈。
- **高可用（High Availability）**：发号服务自身不能成为单点；理想情况下单节点故障不影响整体。
- **方便易用（Usability）**：接入成本低，最好对业务透明。

进阶诉求（按场景取舍）：

- **安全**：ID 不应泄露业务规模（如从递增 ID 推算订单量）、不应嵌入 MAC 等敏感信息。
- **趋势递增（Monotonic Trending）**：有利于 B+ 树索引的写入局部性，降低 MySQL/InnoDB 页分裂。
- **业务含义可控**：可在位结构中预留 bizType、shardId 等字段。
- **独立部署**：发号器作为独立服务，与业务解耦。

> [!NOTE]
>
> 唯一性的来源各不相同：**数据库自增 / 号段**依赖中心存储的串行推进；**Redis** 依赖原子递增；**Snowflake** 依赖"时间戳 + Worker ID + 序列号"三者组合；**UUID** 依赖随机数质量。选型时先想清"冲突域"在哪。

## Database-based Approaches

这类方案把"下一个可用 ID"这一状态集中存放在数据库（或类数据库存储）中，因此是有状态的。

### Auto-increment

直接用 MySQL 等关系型数据库的自增主键，或建一张序列表，通过 `REPLACE INTO` / `INSERT ... ON DUPLICATE KEY UPDATE` 推进计数器，再 `SELECT LAST_INSERT_ID()` 取回。

- 优点：实现简单、ID 严格递增、存储紧凑。
- 缺点：并发上限受数据库单点制约；每次获取都访问 DB 压力大；ID 无业务含义，且易暴露商业机密（递增即可推测量级）。

适用：业务量小、单机架构、后台管理系统。

### Segment (号段模式)

批量向数据库申请一段 ID 区间缓存在内存，用一段、再异步申请下一段，从而把对数据库的访问从"每条一次"降为"每区间一次"。

典型表结构含 `current_max_id`（当前已分配到的最大值）、`step`（步长）、`version`（乐观锁）、`biz_type`（业务类型）。推进时用 `UPDATE ... WHERE version = ?` 的 CAS 方式，并检查 `affected_rows` 防止并发冲突。

- 优点：ID 趋势递增、存储小、对 DB 访问次数少、压力小。
- 缺点：仍有数据库单点（可用主从 / 多库缓解）；ID 无业务含义且存在**跳号**（实例宕机则未用完的号段作废）。

适用：高并发、追求极致吞吐的互联网业务（滴滴 Tinyid 即基于此演化）。

### NoSQL

#### Redis INCR

利用 `INCR` 命令的原子顺序递增生成 ID，依靠 RDB / AOF 持久化降低丢失风险。

- 优点：性能高（内存操作）、单 key 正常时递增。
- 缺点：持久化延迟或主从切换可能导致 ID 回退；单分片易成热点。
- 适用：流水号、短周期计数、可业务兜底去重的场景。

#### MongoDB ObjectId

12 字节结构：`0~3` Unix 秒级时间戳、`4~8` 随机值（初为机器+进程特征）、`9~11` 自增计数器。性能不错、近似有序，但非严格单调，且含时间信息有一定规律性。

## Algorithm-based Approaches

这类方案不依赖中心存储，节点凭本地信息即可生成，因此是无状态的，可水平扩展。

### UUID

128 bit 标识符，标准字符串形式 36 字符。RFC 9562 定义了 v1~v8：

- **v4**：基于随机数（JDK `UUID.randomUUID()` 默认），122 bit 随机位。
- **v7**：48 位 Unix 毫秒时间戳 + 剩余随机 / 计数器字段，趋势有序，无需 Worker ID。
- **v8**：实验性，122 位自定义。

- 优点：生成快、开箱即用、无需协调。
- 缺点：存储空间大（16 字节或 32+ 字符）、不安全（v1 泄露 MAC）、多数版本不严格递增、无业务含义。
- 适用：中小规模分布式系统；**UUID v7** 适合云原生、无中心化集群、追求开箱即用（主键仍建议唯一索引兜底）。

### Snowflake (雪花算法)

Twitter 开源的 64 bit 无状态方案，是当前最主流的分布式 ID 算法。

#### Bit Layout

标准结构（高位在前）：

| 字段 | 位数 | 说明 |
| :--- | :--- | :--- |
| sign | 1 bit | 符号位，恒为 0 |
| timestamp | 41 bits | 相对自定义 epoch 的毫秒数，约可用 69 年 |
| datacenter id | 5 bits | 机房 / 数据中心编号，最多 32 |
| worker id | 5 bits | 机器 / 实例编号，最多 32 |
| sequence | 12 bits | 同一毫秒内的序列号，最多 4096 |

> datacenter + worker 共 10 bits（最多 1024 个节点）；41 bit 时间戳 × 1024 节点 × 4096/ms 决定了理论容量。具体位宽可按业务重排（见下方工业级框架）。

- 优点：生成快、趋势递增、结构灵活（可嵌入业务位）。
- 缺点：存在**时钟回拨**风险；依赖机器 ID 分配，对动态调度环境不友好。

#### Clock Skew (时钟回拨)

根因：NTP 同步、人工调时间、硬件时钟漂移都可能让系统时间"倒退"。由于 ID 高位是时间戳，若回拨后继续用旧时间生成，就可能与回拨前已发出的 ID 重复。

| 解决策略 | 优点 | 缺点 | 适用场景 |
| :--- | :--- | :--- | :--- |
| 拒绝服务 | 实现简单 | 回拨期间完全不可用 | 可用性要求不高 |
| 等待追回 | 保证 ID 唯一性 | 幅度大时长时间阻塞 | 回拨极小 |
| 备用 Worker ID | 高可用 | 实现复杂（租约 / 脑裂处理） | 有可靠注册中心的系统 |

#### Worker ID Allocation

10 bit 的 worker id 需要在集群内不冲突地分配。常见做法：

- **ZooKeeper 注册**：用临时顺序节点（ephemeral sequential）取序号作为 worker id，会话结束自动释放（见 [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)）。
- **Redis 注册**：`SETNX` 抢占位。
- **数据库分配**：落库记录占用。
- **动态 IP / UID 哈希**：按节点特征哈希，简单但有冲突风险（K8s 下 Pod 动态变化尤其明显）。

> [!WARNING]
>
> Snowflake 的全部正确性都建立在"本地时钟单调前进"之上。这与 [Time](/docs/CS/Distributed/Time.md) 中讨论的"日历时钟不可靠"直接相关——单调时钟适合测间隔，但 Snowflake 用的是墙上时钟，因此时钟回拨是其核心故障模式，必须在实现层显式处理，不能假设 NTP 永远精准。

## Industrial Frameworks

工业实现通常把上述某条路线产品化，并处理 worker id 分配、号段预取、时钟回拨等工程细节。

### UidGenerator (百度)

基于 Snowflake 改进，位分配为 `sign(1) + delta seconds(28, 相对 2016-05-20 秒级) + worker id(22, 由 DB 分配、用后即弃) + sequence(13, 每秒 8192)`。worker id 不持久占用，缓解冲突。注意官方仓库长期不活跃，新项目需评估维护状态。

### Leaf (美团)

同时提供两种模式：

- **号段模式**：核心优化是**双 Buffer（Double Buffer）**——当前号段消耗到阈值后，异步线程提前申请下一号段预加载，显著降低 TP999 抖动。
- **Snowflake 模式**：弱依赖 ZooKeeper 管理 workId，并配套处理时钟回拨。官方压测可达近 5w/s QPS。

### Tinyid (滴滴)

基于数据库号段模式，亮点：

- 双号段缓存（异步加载下一号段）；
- 多数据库支持（号段范围互不重叠）；
- 提供 `tinyid-client`，纯本地操作、无 HTTP 消耗。

### IdGenerator (个人)

基于 Snowflake、解决时间回拨且不依赖外部存储。位分配为 `timestamp(位数不固定, 默认基点 2020 年) + worker id(默认 6 bits) + sequence(默认 6 bits)`，ID 更短、支持多语言。

## Comparison

| 方案 | 性能 | 有序性 | 运维成本 | 适用场景 |
| :--- | :--- | :--- | :--- | :--- |
| 数据库自增 | 低 | 严格递增 | 低 | 业务量小、单机架构、后台系统 |
| 号段模式 | 高 | 趋势递增 | 中 | 高并发、追求极致吞吐的互联网业务 |
| Redis | 很高 | 单 key 正常时递增 | 中 | 已有 Redis 集群、能容忍极小概率 ID 回退 |
| Snowflake | 高 | 趋势递增 | 中 | 大中型分布式系统，需处理 Worker ID、时钟回拨 |
| UUID v7 | 高 | 趋势递增 | 极低 | 云原生、无中心化集群、追求开箱即用 |

## Pitfalls

- **跳号不是 Bug**：号段模式、Snowflake、UUID 都可能出现跳号；绝大多数业务只要求唯一、不要求连续。
- **不要完全依赖 ID 排序**：需要按时间排序时，优先使用独立的创建时间字段，而非用 ID 近似时间。
- **没有银弹**：金融核心主键等场景，需结合落库唯一约束兜底，不能只信发号器。

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed.md) — 本页所处的分布式主题枢纽
- [Time](/docs/CS/Distributed/Time.md) — 时钟回拨（Clock Skew）是 Snowflake 的核心约束
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md) — 常用作 Snowflake 的 Worker ID 注册中心
- [Redis](/docs/CS/DB/Redis/) — 既可作为号段存储，也可直接以 INCR 发号

## References

1. [分布式 ID 生成方案详解：UUID、Snowflake、号段模式、Leaf 与 Tinyid 对比 | JavaGuide](https://javaguide.cn/distributed-system/distributed-id.html)
2. [Leaf：美团分布式 ID 生成服务](https://tech.meituan.com/2017/04/21/mt-leaf.html)
3. [baidu/uid-generator](https://github.com/baidu/uid-generator)
4. [twitter-archive/snowflake](https://github.com/twitter-archive/snowflake)
5. [RFC 9562: Universally Unique IDentifiers (UUID)](https://www.rfc-editor.org/rfc/rfc9562)
6. [didi/tinyid](https://github.com/didi/tinyid)
