# Schema and DDL

## Introduction

向量库的 schema 不是一锤定音的。生产系统上线后总要加字段、改字段属性、换 analyzer、给新老集合切别名，而 Milvus 的分布式形态把每一次 DDL 都放大成一组组合动作：RootCoord 校验并构造变更，StreamingCoord 把它广播出去，各消费端与元数据侧再跟上。本篇锚定 v3.0.1 源码讲两件事：DDL 的**能力边界**（哪些改动能原地完成、哪些只能新建集合加迁移），以及它的**落地机制**（ack callback 框架加 catalog 顺序写）。

v3.0.1 是 WAL-first 架构：DDL 不再直接改元数据，而是被编码成广播消息，经 StreamingCoord 的 Broadcaster 写到 ControlChannel 与相关 VChannel，WAL append 被 ACK 之后，ack callback 才把结果应用到 MetaTable 并落 catalog。广播本身的原子性、Term 与 fencing 归 [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md) 与 [Write Path](/docs/CS/DB/Milvus/Write_Path.md)，本篇只写到广播 ACK 之后的元数据落地这条接缝。

边界：缓存失效的广播链路在 [Metadata Cache](/docs/CS/DB/Milvus/Metadata_Cache.md)；analyzer 的倒排与资源细节在 [Full Text Search](/docs/CS/DB/Milvus/Full_Text_Search.md)；库级配额与 RBAC 的运营面归 Deployment 篇。本篇覆盖 schema 语义、演进校验与 DDL 回调机制。

## DDL Inventory

RootCoord 的 ack 回调注册表（`RegisterDDLCallbacks`）直接反映了 v3.0.1 支持的 DDL 全集；索引与 Load 不在其中，由 DataCoord 与 QueryCoord 各自负责。

| 对象 | 操作 | 资源锁 | 广播与落地 |
| --- | --- | --- | --- |
| Database | create / alter / drop | `ExclusiveDBName` | ControlChannel 广播；ack 回调写 catalog |
| Collection | create / drop / truncate | `SharedDBName` + `ExclusiveCollectionName` | V1 消息 + ack 回调 |
| Collection 演进 | add field / add struct field / alter field / alter collection schema | 同上 | ControlChannel + 该集合全部 VChannel |
| Partition | create / drop | 集合级锁 | ack 回调 |
| Alias | create / alter / drop | `ExclusiveDBName` | 仅 ControlChannel；Create 与 Alter 复用同一条 AlterAlias 消息 |
| RBAC | user / role / privilege 系列 | `ExclusivePrivilege` | ControlChannel 广播，V2 回调 |
| Index / Load | create index / load / release | 不在 RootCoord 注册表内 | 分别归 DataCoord / QueryCoord，见 Index 篇与 Query 篇 |

两个细节：组件内部有 `startBroadcastWithAliasOrCollectionLock`，当请求用的是别名时先解析出真实集合名再加集合锁，保证同一集合上的 AddField 与 AlterCollection 串行；集合级消息带 `UpdateMask`，实际广播范围是 `ControlChannel + coll.VirtualChannelNames`。

## Schema Validation on Create

建集合时校验分两层：Proxy 侧做集合级上限与形态校验，RootCoord 侧用 `checkFieldSchema` 做字段语义校验。关键规则：

| 规则 | 约束 | 配置键与默认值 |
| --- | --- | --- |
| 字段总数 | 含 struct 子字段，按 `GetTotalFieldsNum` 计 | `proxy.maxFieldNum` = 256 |
| 向量字段数 | 至少 1 个，至多 | `proxy.maxVectorFieldNum` = 10 |
| 向量维度 | 浮点 2 ~ 上限；二进制上限乘 8 | `proxy.maxDimension` = 32768 |
| VarChar 长度 | max_length 上限 | `proxy.maxVarCharLength` = 65535 |
| 分片数 | shardNum 上限 | `proxy.maxShardNum` |
| 主键 | 单主键；不支持 nullable；不支持 default_value | 写入校验另有 more than 1 primary keys 检查 |
| default_value | 类型必须与字段类型匹配且不得越界；PK、Array、Vector 不支持；非 dynamic 的 JSON 不支持；加 TEXT 字段时不允许 | `checkFieldSchema` |
| dynamic field | 至多一个，必须是 JSON 且名为 `$meta`；enable 开关与字段存在性必须一致 | `validateEvolutionDynamicGraph` |
| struct array | 普通字段不能是 ArrayOfStruct；ArrayOfVector 只能出现在 struct array 内 | `checkFieldSchema` |
| 保留名 | RowID、Timestamp、`$meta`、Namespace、VirtualPK 不可被用户字段占用 | Proxy 与回调双侧检查 |

## Evolution Boundaries

演进校验的统一入口是 `schemautil.ValidateSchemaEvolution`：它把新旧 schema 展开成字段图（含 struct 主字段与子字段的 parent 关系），分别校验 kept、added、dropped 三类字段，再检查 clustering key、dynamic 图与 `max_field_id` 属性。核心不变量是**已写入的数据不能被重新解释**。

可以原地完成的改动：

| 改动 | 允许范围 | 机制 |
| --- | --- | --- |
| 加字段 AddCollectionField | 新字段必须 nullable 或带 default；不能是 PK、autoID、分区键、系统字段 | 分配 FieldID = 当前最大 + 1；SchemaVersion 加 1；同步更新 max_field_id property；timestamptz 默认值按集合 timezone 重写 |
| 加 struct 字段 AddCollectionStructField | 新 struct 必须 nullable 且至少一个子字段；子字段必须 nullable、无 protected role | 子字段以 stored root 名称参与命名冲突检查 |
| 改字段 AlterCollectionField | 只能改 `TypeParams` 属性与 description | 内容无变化直接返回 errIgnoredAlterCollection 保幂等；analyzer 参数仅限 string 字段，且未启用 text match、不被 BM25 或 MinHash function 依赖 |
| 数值边界 | max_length、max_capacity 可增可减，但不可删除或置为非法值 | dimension 是例外，见下表 |
| clustering key | 可在线添加，但集合最多一个 | `validateEvolutionClusteringKey` |
| function 字段 | AlterCollectionSchema 的 AddRequest 加 function 及其输出字段；DropRequest 删除 | DropRequest 广播前先 waitUntilSchemaDropReady |

不能原地完成、只能新建集合加数据迁移的改动（统一返回 `merr.ErrParameterInvalid`，错误码 1100，InputError 族）：

| 改动 | 校验点 |
| --- | --- |
| 重命名字段、改 data type、改 element type | cannot rename field / cannot change the data type in place |
| 改 nullability | cannot change the nullability in place |
| 改字段结构角色 IsPrimaryKey、IsPartitionKey、IsClusteringKey、AutoID、IsDynamic | cannot change the structural role |
| 改或删 dimension | cannot change or remove the dimension |
| 删除 PK、分区键、clustering key、系统字段、最后一个向量字段、仍被 function 引用的字段 | cannot drop |
| 在 kept struct 上加或删子字段 | cannot add sub-field to kept struct field |
| 复用已分配的 field id，或 max_field_id property 与期望值不符 | new field id reuses an already allocated field id |
| 把既有字段改造成 function output | cannot repurpose existing field as a function output |

字段重命名没有任何在线路径；同理改类型、改维度都意味着旧数据重新解释会产生垃圾读，实践上只能新建集合后重导。`AlterCollectionSchema` 的 DropRequest 是目前唯一的在线删除路径，且删除对象被上述规则严格限缩。

## Dynamic Field vs JSON

dynamic field 不是隐式魔法列，而是 schema 里一个真实字段：名称为 `$meta`（`common.MetaFieldName`）、`DataType_JSON` 且 `IsDynamic = true`，由 `enable_dynamic_field` 开关控制其存在性，两者不一致会在演进校验里被拒绝。

- 写入侧：Proxy 的 `checkDynamicFieldData` 把关。客户端未显式携带时，`autoGenDynamicFieldData` 补一列全 `{}` 的 JSON；携带的内容必须是 JSON object，键名不能与静态字段重名（partial update 场景跳过该冲突检查，保证 schema 演进添加静态列后旧 `$meta` 键仍合法），也不允许出现 `$meta` 键。
- 查询侧：字段解析把未命中 schema 的字段名映射成 `$meta` 加 JSON Pointer 后下推（如 `parseOrderByFieldSpec` 处理 `unknown["key"]` 与裸 `unknown` 两种写法）；显式 JSON 字段则请求整列，不做动态投影。
- 取舍：

| 维度 | dynamic field | 显式 JSON 字段 | 显式标量列 |
| --- | --- | --- | --- |
| 演进 | 新增键零 DDL | 结构由业务约定 | 需要 AddCollectionField |
| 写入 | 未识别列打包进 `$meta` | 按 JSON 列传入 | 每列显式传 |
| 约束 | 键名不得与静态字段冲突 | 无 | 无 |

## Nullable and Default Values

null 的通用载体是 `FieldData.ValidData` 逐行 bool 数组：某行 valid 为 false 即该行为 null，只有 nullable 字段在填充完成后保留 valid_data。写入路径的角色分工是 Proxy 负责补齐、RootCoord 负责校验 schema 语义。

- 写入填值：`fieldvalidator` 的 `fillWithValue` 在列长度不足期望行数时，对无 default 的 nullable 字段填 null，对有 default 的字段用 `FillWithDefaultValue` 填默认值；完全缺列且既非 nullable 又无 default 的字段，在写入校验阶段直接报 fieldSchema has no corresponding fieldData pass in。默认值由 Proxy 侧物化，schema 里的 default 只是写入兜底值。
- schema 层约束：PK 不能 nullable 也不能带 default；default 的类型与范围在 `checkFieldSchema` 校验（含 Int8、Int16 越界检查）；timestamptz 的 default 按集合 timezone 属性重写后才入库；加 TEXT 字段不允许携带 default。
- 演进联动的意义：新加字段必须 nullable 或带 default，正是为了历史行不需要回填——旧数据读出来要么是 null 要么是默认值，否则加字段当场就会产生不可读行。

## DDL Callbacks and Catalog

callback 框架解决的问题是：广播消息可能被重试、重放，而元数据落地必须与广播结果严格对齐且可重复执行。RootCoord 初始化时 `RegisterDDLCallbacks` 按 message type 与 version 注册回调（collection、partition、database、alias、RBAC 五个 register 入口）；Broadcaster 在广播 ACK 后经注册表调用回调，未注册消息类型直接跳过。扩展一种新 DDL 只需新增一种广播消息加一个回调。

回调契约与幂等：回调只依赖广播结果（消息头体与各 channel 的 timetick），不依赖发起现场的内存，所以可重复执行；源码在可幂等的位置显式处理——改字段无实际变化返回 errIgnoredAlterCollection，别名指向相同目标返回 errIgnoredAlterAlias，集合已不存在时 AlterCollection 直接返回 errAlterCollectionNotFound 而不是报错。

catalog 顺序写：MetaTable 用一把 ddLock 串行化所有落地。AlterAlias 先 `catalog.AlterAlias` 写 etcd、再更新内存 aliases 表；AlterCollection 先 clone old/new、按 `UpdateMask` 区分 schema 变更与跨库变更，写 `catalog.AlterCollection`（含 MigrateGrantCollectionName 迁移授权）后再更新 names 与 collID2Meta 索引。先持久化、后内存，元数据以 catalog 为准。

回调收尾统一走 `ExpireCaches`：消息携带 cache expirations，回调用新生成的 TSO 调 `ExpireMetaCache` 触发缓存失效，链路细节见 [Metadata Cache](/docs/CS/DB/Milvus/Metadata_Cache.md)。

### Alias Semantics

- 别名严格库内唯一，且目标必须是真实集合。集合名解析本身是「先查别名表、再查 names 表」；**链式别名不可表达**的真正原因是 Create / Alter 的前置检查（`CheckIfAliasCreatable` / `CheckIfAliasAlterable`）只经 names 表解析目标，要求目标必须是真实集合。
- 别名不得与既有集合名冲突（dropping 或 dropped 状态除外）；仍带别名的集合禁止跨库 rename。
- Create 与 Alter 复用同一条 AlterAlias 消息；完全相同指向是幂等的（errIgnoredAlterAlias），**改指向别的集合是 AlterAlias 的正常路径且会成功**——`AliasAlreadyExist` 一类错误只属于 CreateAlias 的前置检查（别名已指向别的集合时拒绝创建）。
- AlterAlias 消息头携带 `OldCollectionId`，三态决定缓存驱逐策略：大于 0 时按 id 精确驱逐，0 视为旧目标未知走 holder scan，-1 哨兵值（aliasNoOldTarget）表示 CreateAlias 无需扫描。

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [Write Path](/docs/CS/DB/Milvus/Write_Path.md)
- [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)
- [Metadata Cache](/docs/CS/DB/Milvus/Metadata_Cache.md)
- [Full Text Search](/docs/CS/DB/Milvus/Full_Text_Search.md)

## References

- [Milvus v3.0.1 schema_evolution.go](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/util/schemautil/schema_evolution.go)
- [Milvus v3.0.1 ddl_callbacks.go](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/rootcoord/ddl_callbacks.go)
- [Milvus v3.0.1 validate_util.go](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/proxy/fieldvalidator/validate_util.go)
- [Milvus v3.0.1 proxy schema utilities](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/proxy/util.go)
