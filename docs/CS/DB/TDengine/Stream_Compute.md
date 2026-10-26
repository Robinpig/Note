## Introduction

TDengine 把实时链路里原本属于 Kafka + Flink 的两块能力收进了库内：**流计算**（数据写入即触发持续计算，跑在 snode）和**数据订阅 TMQ**（把 WAL 当消息队列消费，vnode 即 partition）。再加上 bnode 的 MQTT 订阅，一进两出三条通道覆盖了"原始数据进来 → 实时加工 → 推给下游"的完整闭环。这是官方"极简时序数据平台"定位最实的一部分——应用侧确实可以不再集成 Kafka。

本页讲流计算的任务形态、TMQ 的 topic/消费者组/offset 语义、MQTT 订阅，以及它们各自与 vnode/snode 的关系。

## Stream Compute

### 任务形态

流计算在 TDengine 里是**用 SQL 创建、随数据写入持续执行的计算任务**，官方称每个实时分析对应一个 TDengine 流计算（Stream），计算逻辑直接运行在数据库内核，不占应用服务器资源——应用层重启或网络中断，流计算依然在数据库层面持续运行。计算结果作为时序数据写回 TDengine，与原始读数统一存储，可直接 SQL 查询或做下游输入。

执行载体是 **snode**（流计算节点）：集群级共享、每 dnode 最多 1 个、默认不创建；mnode 调度可用 snode 完成任务，没有 snode 时计算退回 vnode。

### 触发方式

流计算不假设数据按固定频率到达。官方文档归纳了覆盖工业数据不同节拍的触发方式，典型的几类：

- **时间驱动**：按时间滑动窗口持续计算（每分钟刷一次滚动 KPI）。
- **状态驱动**：跟随状态列变化自动分段统计（运行/空闲/故障切换）。
- **静默/批次驱动**：检测到数据流静默间隔自动触发批次汇总。
- **事件驱动**：异常在某一时刻瞬间触发即算。

### 乱序与回填

- **乱序/迟到数据**：受影响的时间窗口会**重新计算**，保证输出准确。
- **回填（backfill）**：流计算可以对存量历史数据执行回填——分析上线后历史趋势图即刻完整，不用等新数据攒够。

### 与 TDgpt 的配合

需要"已知规则 + 未知偏离"双覆盖时，规则用流计算的窗口聚合精确定义，难以预先描述的复杂偏离交给 TDgpt 的异常检测（见 [TDgpt](/docs/CS/DB/TDengine/TDgpt.md)），两者在同一平台并行运行。

## Data Subscription（TMQ）

### 定位：WAL 即消息队列

官方对 TMQ 的对标很明确：**类似 Kafka，使用数据订阅需要先定义 topic**。本质是"时序数据存在 vnode 上，消费就是从 vnode 的 WAL 文件读数据"——WAL 顺序写入、自动建索引支持快速随机访问，切换/保留时间/大小可配。注意 WAL 里除数据外还存元数据和写消息，所以**WAL 版本号不连续**。

### Topic 三型

| 类型 | 用途 | 粒度 |
| :-- | :--- | :--- |
| **数据库订阅** | 数据迁移，可在另一集群恢复整个数据库 | 整库 |
| **超级表订阅** | 数据迁移，恢复整个超级表 | 整表 |
| **查询语句订阅** | 灵活获取数据——官方称这是 TDengine 数据订阅的亮点 | 任意查询 |

查询语句订阅由 TDengine 直接从 WAL 读数据、经统一查询引擎过滤转换后再推送，减少传输量与应用复杂度。

### 消费者组语义

- **vnode 对标 Kafka partition**：一个 topic 的数据表分布在多个 vnode 上，消费者**先均分 vnode、再消费分到的 vnode**；消费进度按 vnode 记录。
- **消费者组必须指定**；同组消费者**共享消费进度**，实现均匀分配。4 个 vnode 的分配示例：2 个消费者各 2 个；3 个消费者两人各 1 个、第三人 2 个；5 个消费者时第 5 个不参与消费（vnode 分完为止）。
- **Rebalance**：新消费者加入或订阅变化时触发，**每 2 秒检查一次**；服务端实现、对用户透明；rebalance 期间非 ready 状态的消费者不能消费。
- **心跳**：消费者信息经心跳上报 mnode，心跳丢失超过 `session.timeout.ms` 判离线——默认 **45 s（v3.4.3.6 起，此前 12 s）**，超时后经 rebalance 流程清理。
- **消费语义**：**at-least-once**，即使崩溃重启也保证不丢。

### Offset

**offset 就是 vnode 上的 WAL 版本号**，对应 Kafka 的 offset。提交方式支持手动提交或配置后自动周期提交；首次消费起点由订阅参数 `earliest`/`latest` 决定（仅首次或未提交进度时生效）。同一 topic + 同一消费者组下**每个 vnode 的进度唯一**；不同消费者组**不共享**进度，即使订阅同一 topic。消费者收到数据同时收到版本号（先存内存），退出前必须 commit 到服务端持久化。

### Pull + Push 混合

拉取侧：vnode 有大量未消费数据时消费者一次性大批量拉取；周期性向 mnode 请求 rebalance 后的 vnode 分配列表；持续向各 vnode 尝试取新数据。推送侧：某 vnode 无数据可消费时消费者注册**消费句柄**，新数据一写入即被推送，保时效。这条组合是 TMQ 延迟低于普通轮询的关键。

### Producer 侧

向 topic 数据表写数据的应用即 producer，写入方式包括 SQL、Stmt（预编译）、Schemaless（Line Protocol/JSON/Telnet 等）、CSV、流计算输出，最终都落入 vnode 的 WAL。

## MQTT Subscription（bnode）

`CREATE BNODE ON DNODE <id> [PROTOCOL protocol]` 创建订阅节点，dnode 随即启动子进程 `taosmqtt` 对外提供订阅服务。协议参数未指定时默认 `mqtt`，官方称后续会扩展其它协议。与 TMQ 的分工：TMQ 是库内/近库的消费者组模型（JDBC/Go/Python/C 等连接器消费），bnode 面向**外部 MQTT 生态**把数据变更推出去。

## Links

- [TDengine](/docs/CS/DB/TDengine/TDengine.md)
- [SQL](/docs/CS/DB/TDengine/SQL.md)
- [TDgpt](/docs/CS/DB/TDengine/TDgpt.md)
- [Architecture](/docs/CS/DB/TDengine/Architecture.md)
- [Storage_Engine](/docs/CS/DB/TDengine/Storage_Engine.md)
- [WAL](/docs/CS/DB/Concept/WAL.md)

## References

1. [技术内幕：数据订阅引擎](https://docs.tdengine.com/internals/topic/)
2. [技术内幕：流式计算引擎](https://docs.tdengine.com/internals/stream/)
3. [节点管理 SQL（CREATE BNODE）](https://docs.taosdata.com/reference/taos-sql/node/)
