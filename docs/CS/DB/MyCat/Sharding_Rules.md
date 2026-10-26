## Introduction

分片算法是 MyCAT 的路由核心：同一个分片列的值，经过算法计算后落到底层哪个 dataNode。源码 `io/mycat/route/function/` 下一共 **18 个分片算法类**，出厂 rule.xml 自带其中 10 个的可用配置，其余需要按需手写。本页把家族按「哈希、范围、日期、模式」四类讲清语义与选型，并给出两条最容易踩的暗礁：**1.675 之后 `PartitionByLong` 的分布不兼容**，以及 **ER 分片与全局表这两种「让 join 不跨库」的手段**。配置语法见 [Configuration](/docs/CS/DB/MyCat/Configuration.md)。

## The Algorithm Family

### 哈希类：取模与一致性哈希

| 算法类 | 名称 | 出厂自带 | 语义 | 关键属性 |
| :--- | :--- | :--- | :--- |
| `PartitionByMod` | mod-long | 是 | 对分片列取模，`count` 个节点轮流 | `count`（出厂示例 3） |
| `PartitionByLong` | func1 | 是 | 按 `partitionLength` 切段，段内连续、段间哈希到 `partitionCount` 个分片 | `partitionCount=8`、`partitionLength=128` |
| `PartitionByMurmurHash` | murmur | 是 | murmur 哈希 + 虚拟节点的一致性哈希 | `seed=0`、`count`、`virtualBucketTimes=160`、可选 `weightMapFile` / `bucketMapPath` |
| `PartitionByJumpConsistentHash` | jump-consistent-hash | 是 | 跳一致性哈希，免虚拟节点，节点数变化时只重映射少量 key | `totalBuckets` |
| `PartitionByCRC32PreSlot` | crc32slot | 是 | CRC32 预分片（先算 CRC32 再切 slot） | `count` |
| `PartitionByString` | sharding-by-string | 否 | 字符串列哈希 | `count` 等 |

取模（`PartitionByMod`）是最直觉的选择，也是扩容最痛的选择：**节点数一变，几乎全部 key 重新落位**。一致性哈希解决的就是这个问题，MyCAT 提供了两条实现路径：

- **`PartitionByMurmurHash`**：每个物理节点映射成 `virtualBucketTimes` 个虚拟节点（出厂 160 倍），key 先经 murmur 哈希落到虚拟节点环上。配合 `weightMapFile` 可以给不同机器配不同权重（权重必须是正整数，否则按 1 处理）。`bucketMapPath` 可把「虚拟节点 ↔ 物理节点」的映射 dump 到文件，**仅用于调试观察分布**，生产不要开。
- **`PartitionByJumpConsistentHash`**：跳一致性哈希不需要虚拟节点环，`totalBuckets` 直接给桶数；节点增减时平均只动 1/(n+1) 的 key。数据更均匀、内存更小，代价是没有权重机制。

选型上：节点规模固定且要权重 → murmur；频繁扩缩容、要最小化迁移 → jump consistent hash。

### 范围类：按值域切片

| 算法类 | 名称（均出厂自带） | 语义 |
| :--- | :--- | :--- |
| `AutoPartitionByLong` | rang-long | 自动范围分片，区间映射写在 `mapFile`（`autopartition-long.txt`）里，按容量规划每段多大 |
| `PartitionByRangeMod` | rang-mod | 范围 + 取模混合：大段内再取模，区间映射在 `partition-range-mod.txt` |
| `PartitionByFileMap` | hash-int | 纯文件映射：`mapFile`（`partition-hash-int.txt`）里逐条写「值 → 节点索引」 |

范围类的共同点是**可人工规划数据分布**——哪些号段在哪台机器的哪个库，写进 mapFile 就固定下来。适合历史数据归档、按租户/按地域切片这类「分布要可解释」的场景；代价是号段用完要改文件、新数据落在哪完全靠预先规划。

### 日期类：时序数据切片

| 算法类 | 名称 | 出厂自带 | 语义 | 关键属性 |
| :--- | :--- | :--- | :--- | :--- |
| `PartitionByMonth` | partbymonth | 是 | 按月分片，`sBeginDate` 起算 | `dateFormat=yyyy-MM-dd`、`sBeginDate=2015-01-01` |
| `LatestMonthPartion` | latestMonth | 是 | 最近一段时间按小时/时段细分，应对「最新数据最热」 | `splitOneDay=24` |
| `PartitionByDate` | sharding-by-date | 否 | 按日期切片，每片覆盖若干天 | `dateFormat`、起止日期、每片天数 |
| `PartitionByHotDate` | sharding-by-hotdate | 否 | 历史按天、最近若干天按小时的冷热分层 | 日期格式 + 起止 + 热数据窗口 |
| `PartitionByRangeDateHash` | sharding-by-rangedatehash | 否 | 先按日期范围分组、组内再哈希 | 日期格式 + 范围 + 分组参数 |

`latestMonth` 的 `splitOneDay=24` 含义是**把一天切成 24 份（每小时一份）**——最近一个月的流量全部压在「当天」这个分片上，按时钟拆开后单表量级可控。这是日志、流水类表的常用解。

`PartitionByRangeDateHash` 有个值得记住的工程细节：**2025-10 的提交专门给它修了时区问题（显式使用 UTC）**——分片列是时间戳、跨时区部署时，解析器的时区假设直接决定数据落哪片。

### 模式类：从值里「抠」出分片号

| 算法类 | 名称 | 出厂自带 | 语义 |
| :--- | :--- | :--- | :--- |
| `PartitionByPattern` | sharding-by-pattern | 否 | 按预定义模式串把列值切成若干段，逐段映射节点 |
| `PartitionByPrefixPattern` | sharding-by-prefixpattern | 否 | 取列值**前缀**做映射（如租户 ID 打头的编码） |
| `PartitionDirectBySubString` | sharding-by-substring | 否 | 直接截取子串当节点索引（如订单号内嵌分片号） |
| `SlotFunction` | （crc32slot 底层） | 否 | slot 计算函数，被 CRC32 预分片复用 |

模式类的适用场景很窄但很致命地好用：**业务编码里本身就带了分片信息**（如 `SHARD02-000123` 的订单号），直接截出来用，省掉一次哈希，也让「这条数据在哪」对人可读。

## Two Ways to Keep Joins Local

分库分表最难缠的不是单表路由，是 join。MyCAT 给了两个配置层的手段，把跨库 join 退化掉：

### ER 分片（childTable）

子表不配自己的算法，而是声明 `joinKey`（子表关联列）与 `parentKey`（父表主键）。路由父表时，用父表的分片结果反推子表所在分片——**父子表永远同库**。订单表按 `user_id` 分片、订单项表按 `order_id` 挂在订单表下，就是最典型的形态：查「某用户的订单及明细」全程不跨库。

代价是**写入时的约束**：子表行必须跟着父表走，父表的分片列改了，子表要跟着迁。er 分片把 join 问题转化成了数据模型问题。

### 全局表（type="global"）

字典表、配置表这类「每个分片都要 join 的小表」，设为 `type="global"` 后**每个节点都存全量**。join 时任选一个节点本地完成；写入时 MyCAT 负责把变更下发到所有节点。全局表把「跨库 join 小表」变成「单库 join」，代价是**写放大与一致性窗口**——所有节点的数据是最终一致的，不是强一致的。

## Version Quirks Worth Knowing

1. **`PartitionByLong` 在 1.675 之后数据分布与之前不兼容**。2020-01-01 合入的 PR 优化了该算法的均衡性，同一个分片列在跨越这个版本的部署上会落到不同分片——升级即数据重分布，必须先做双跑或迁移。
2. **一致性哈希三兄弟的迁移成本不同**：murmur（有虚拟节点、有权重）、jump consistent hash（无虚拟节点、无权重）、crc32slot（预分片）。切换算法等于换一套哈希空间，没有平滑过渡。
3. **mapFile 类算法改文件即改路由**：`autopartition-long.txt`、`partition-hash-int.txt`、`partition-range-mod.txt` 的内容直接决定号段去向，生产变更必须走版本管理，改错一行就是一批数据路由错位。
4. **自定义算法**继承 `AbstractPartitionAlgorithm` 即可被 rule.xml 引用，官方「插件化开发」指的就是这条路；MyCAT2 进一步把算法做成可插拔组件，甚至提供基于 HTTP 调用的分片算法。

## Links

- [MyCat](/docs/CS/DB/MyCat/MyCat.md)
- [Configuration](/docs/CS/DB/MyCat/Configuration.md)
- [SQL_Routing](/docs/CS/DB/MyCat/SQL_Routing.md)
- [Shard](/docs/CS/DB/Shard.md)

## References

1. [Mycat-Server: src/main/resources/rule.xml（出厂算法与属性）](https://github.com/MyCATApache/Mycat-Server/blob/master/src/main/resources/rule.xml)
2. [MyCATApache/Mycat-Server（route/function 算法类清单）](https://github.com/MyCATApache/Mycat-Server)
3. [MyCAT 官方网站 · 关键特性](https://www.mycat.org.cn)
