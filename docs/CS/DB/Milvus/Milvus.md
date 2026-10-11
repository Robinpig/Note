## Introduction

Milvus 是一个开源云原生向量数据库，专为在海量向量数据集上进行高性能相似性搜索而设计。它把 ANN 检索与数据库该有的东西——schema、事务边界、一致性级别、多租户、备份恢复、权限——装进同一套存算分离架构里，因此理解它的成本几乎全部落在「组件之间如何传递事实」这一件事上。

> 向量数据库的整体图景（ANN 原理、选型坐标）见 [vector](/docs/CS/DB/vector.md)。本目录下的笔记锚定 **v3.0.1** 源码：3.0 相对 2.x 做了一次架构级迁移，凭 2.x 印象写的组件职责大多是错的，下面「Two Architectural Ruptures」一节先说清哪里变了。

## Two Architectural Ruptures

2.x 的资料里，写入是「Proxy 投 DML channel → DataNode 消费 → DataNode flush」，索引构建由独立的 IndexNode 承担。v3.0.1 两条都不成立：

| 主题 | 2.x 的讲法 | v3.0.1 的事实 |
| --- | --- | --- |
| 落盘 | DataNode 订阅 DML channel 消费 WAL 后 flush | **StreamingNode 的 flusher 是唯一落盘路径**；DataNode 的 `WatchDmChannels` 是 no-op |
| 日志角色 | 一条旁路消息总线（msgstream） | **WAL 是唯一事实来源**，读、恢复、复制都以它为准 |
| 索引构建 | IndexNode 独立进程 | 由 **DataNode 本地执行**（`types.DataNode` 同时实现 `workerpb.IndexNodeServer`） |
| 协调者 | RootCoord / DataCoord / QueryCoord 三进程 | 合并成单进程 **MixCoord**（外加 StreamingCoord），只开一个 gRPC 端口 |
| 段分配 | Proxy 向 DataCoord 调 `AssignSegmentID` | 生产路径不再调用，segment 创建下沉到 WAL 的 shard interceptor 并广播 `CreateSegment` |

`MILVUS_STREAMING_SERVICE_ENABLED` 由 `cmd/main.go` 恒置为 1，它已不是可关的灰度开关，而是等清理完 2.x 分支后的过渡残留——这解释了为什么代码里仍能看到两套落盘模型。

## Component Model

组件按「协调者管元数据与调度，节点执行实际工作」划分，接口集中在 `internal/types/types.go`，全部实现统一的 `Component` 生命周期（`Init` / `Start` / `Stop` / `Register`）。

| 角色 | 进程 | 职责 |
| --- | --- | --- |
| MixCoord | 协调者 | 单进程承载 RootCoord（DDL/DCL、TSO、RBAC）+ DataCoord（段生命周期、compaction、索引调度、GC）+ QueryCoord（目标视图、replica、balance）+ StreamingCoord（通道分配、原子广播） |
| Proxy | 接入层 | 校验、限流、任务调度、按 shard 扇出与结果汇聚 |
| StreamingNode | 执行者 | 持有 WAL 分区，提供 append / consume / broadcast，内含 flusher |
| QueryNode | 执行者 | 加载段与索引，经 segcore 执行 search / query |
| DataNode | 执行者 | 执行 compaction、索引构建、stats、import 等任务 |
| CDC | 执行者 | 跨集群 WAL 复制 |

同一个二进制按 `milvus run <serverType>` 装配不同角色组合，就变成 Lite / Embedded / Standalone / Cluster 四种形态，装配细节与关停顺序见 [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md)。

## Data Model

Milvus 的数据存储分为逻辑层与物理层：

```
[逻辑层] Database (数据库)
   │
   ├── [逻辑层] Collection (集合/表)
   │      │
   │      ├── [逻辑层] Partition (分区) -> *可选，用于逻辑过滤*
   │      │      │
   │      │      ├── [物理层] Segment (数据段) -> *物理存储和计算的基本单元*
   │      │      │      ├── Field Data (字段数据/列存)
   │      │      │      └── Index Data (索引数据)
   │      │      │
   │      │      └── [物理层] Segment ...
   │      │
   │      └── [逻辑层] Partition ...
   │
   └── [逻辑层] Collection ...
```

- **Database**：顶层逻辑单元，承载元数据命名空间与库级配额；
- **Collection**：类似关系型数据库中的表；
- **Partition / Partition Key**：分区用于物理隔离与裁剪，partition key 按键哈希落分区；
- **Shard / VChannel**：一个 collection 划成若干 shard，每个 shard 对应一个逻辑通道 VChannel，决定写入并行度与查询路由粒度；
- **Segment**：物理存储与计算的基本单元，同时是索引单位、加载单位与查询扇出单位。按状态分 Growing（增量写入）与 Sealed（固化后建索引），按 Level 分 **L0**（只承载删除的段，`RowNum` 恒为 0）、**L1**（普通段）、**L2**（带 clustering 分布信息的段）。

字段类型上，v3.0.1 除 dense 向量外还支持 sparse 向量、binary / float16 / bfloat16 / int8 向量、JSON 与 array、动态字段（dynamic field）以及函数字段（function field，如 text 生成 embedding 或 BM25 稀疏向量）——它们各自能建什么索引，见 [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)。

## Metadata and Schema

Schema 不是一次定终身：加字段、改字段、加别名、调 analyzer 都要经过 DDL，而每次 DDL 在分布式架构里都是「元数据变更 + 广播 + 缓存失效」的组合动作。[Schema and DDL](/docs/CS/DB/Milvus/Schema_and_DDL.md) 讲清演进的能力边界（哪些改动允许、哪些必须重建集合、dynamic field 与 nullable 的语义），以及 DDL callback 框架与 catalog 的顺序落地。

DDL 之后「为什么所有节点立刻看到新事实」是另一个问题：Proxy 不可能每次请求都回源 etcd，于是有了缓存；缓存的一致性靠**广播失效**来兜——一次 AlterCollection 的完整链路（元数据落地 → 广播 → 各 Proxy 失效 → 下一次请求重建）见 [Metadata Cache](/docs/CS/DB/Milvus/Metadata_Cache.md)。

## Installation

Milvus 有三种部署选项：Milvus Lite、Milvus Standalone 和 Milvus Distributed。

| 部署选项 | 形态 | 适用场景 |
|---------|------|---------|
| Milvus Lite | Python 库（`pip install pymilvus milvus-lite`） | 快速原型开发（Jupyter Notebook）、资源受限的智能设备 |
| Milvus Standalone | 单机服务器部署，所有组件打包进一个 Docker 镜像 | 功能验证、小规模生产 |
| Milvus Distributed | Kubernetes 集群 / 云原生分布式部署 | 生产环境，支持组件独立扩缩容与冗余 |

> 已实现基于 Docker Compose 的三节点 Milvus 集群部署方案，详见 [Deploy](/docs/CS/DB/Milvus/Deploy.md)。

<!-- tabs:start -->

##### **Milvus Lite**

Milvus Lite 是一个 Python 库，可导入到应用程序中。作为 Milvus 的轻量级版本，它非常适合在 Jupyter Notebooks 中进行快速原型开发，或在资源有限的智能设备上运行。

运行 `pip install pymilvus milvus-lite` 进行安装，并使用 `MilvusClient("./demo.db")` 语句实例化一个带有本地文件的向量数据库，以持久化所有数据。

示例代码：

```python
from pymilvus import MilvusClient
import random

# 如果文件已存在，则会直接加载之前的数据
# Specify a Local File Path (e.g., ./milvus_demo.db), Milvus Lite Will Automatically Create and Start
# If the File Already Exists, the Previous Data Is Loaded Directly
client = MilvusClient(uri="./milvus_demo.db")

print("Milvus Lite 已成功启动并连接！")

# 2. 创建集合 (Collection)
collection_name = "my_collection"

# 如果集合已存在，先删除（演示用）
if client.has_collection(collection_name):
    client.drop_collection(collection_name)

# 创建集合，包含一个主键字段和一个向量字段
client.create_collection(
    collection_name=collection_name,
    dimension=8  # 假设向量维度为 8
)
print(f"集合 '{collection_name}' 创建成功。")

# 准备一些模拟数据
# Prepare Some Simulated Data
num_entities = 10
ids = [i for i in range(num_entities)]
embeddings = [[random.uniform(-1, 1) for _ in range(8)] for _ in range(num_entities)]

data = [
    {"id": i, "vector": embeddings[i]} for i in range(num_entities)
]

res = client.insert(collection_name=collection_name, data=data)
print(f"成功插入 {res['insert_count']} 条数据。")

# 4. 执行向量搜索
query_vector = [random.uniform(-1, 1) for _ in range(8)]

search_res = client.search(
    collection_name=collection_name,
    data=[query_vector],
    limit=3,  # 返回最相似的 3 条数据
    output_fields=["id"]
)

print("\n搜索结果:")
for hits in search_res:
    for hit in hits:
        print(f"ID: {hit['id']}, 距离: {hit['distance']}")

# 5. 关闭连接 (可选，程序结束时会自动释放)
client.close()
print("\nMilvus Lite 连接已关闭，数据已持久化到 ./milvus_demo.db 文件中。")
```

##### **Milvus Standalone**

Milvus Standalone 是单机服务器部署。Milvus Standalone 的所有组件都打包到一个 Docker 镜像中，部署起来非常方便。

```yml
services:
  etcd:
    container_name: milvus-etcd
    image: quay.io/coreos/etcd:v3.5.25
    environment:
      - ETCD_AUTO_COMPACTION_MODE=revision
      - ETCD_AUTO_COMPACTION_RETENTION=1000
      - ETCD_QUOTA_BACKEND_BYTES=4294967296
      - ETCD_SNAPSHOT_COUNT=50000
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/etcd:/etcd
    command: etcd -advertise-client-urls=http://etcd:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd
    healthcheck:
      test: ["CMD", "etcdctl", "endpoint", "health"]
      interval: 30s
      timeout: 20s
      retries: 3

  minio:
    container_name: milvus-minio
    image: minio/minio:RELEASE.2024-05-28T17-19-04Z
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    ports:
      - "9001:9001"
      - "9000:9000"
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/minio:/minio_data
    command: minio server /minio_data --console-address ":9001"
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 30s
      timeout: 20s
      retries: 3

  standalone:
    container_name: milvus-standalone
    image: milvusdb/milvus:v3.0.0
    command: ["milvus", "run", "standalone"]
    security_opt:
    - seccomp:unconfined
    environment:
      MINIO_REGION: us-east-1
      ETCD_ENDPOINTS: etcd:2379
      MINIO_ADDRESS: minio:9000
      COMMON_SECURITY_AUTHORIZATIONENABLED: true
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/milvus:/var/lib/milvus
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9091/healthz"]
      interval: 30s
      start_period: 90s
      timeout: 20s
      retries: 3
    ports:
      - "19530:19530"
      - "9091:9091"
    depends_on:
      - "etcd"
      - "minio"

  attu:
    container_name: attu
    image: zilliz/attu:v3.0.0
    ports:
      - "3001:3000"
    environment:
      - MILVUS_ADDRESS=standalone:19530
    volumes:
      - ./attu-data:/data
    depends_on:
      - "standalone"
networks:
  default:
    name: milvus
```

> 提示：上面的 compose 把镜像钉在 `milvusdb/milvus:v3.0.0` 与 `zilliz/attu:v3.0.0`，比本页锚定的 v3.0.1 落后一个补丁版；且该 standalone compose 未显式配 `mq.type`，按 v3.0.1 的 default 解析规则（standalone 优先 rocksmq，判据是 `rocksmq.path` 非空、默认为 `/var/lib/milvus/rdb_data`）会落到 RocksMQ，与 [Deploy](/docs/CS/DB/Milvus/Deploy.md) 三节点集群的 Kafka 路径不同。

##### **Milvus Distributed**

Milvus Distributed 可以部署在 Kubernetes 集群上。这种部署采用云原生架构，摄取负载和搜索查询分别由独立节点处理，允许关键组件冗余。

<!-- tabs:end -->

## The WAL Convergence

要理解 3.0 的一切，先接受一个前提：**数据不再「写进存储」，而是「追加进日志」**。[WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md) 从后端抽象讲起——`pkg/streaming/walimpls` 把 RocksMQ、Kafka、Pulsar、Woodpecker 注册成可替换实现，之上是 PChannel / VChannel / CChannel 三层通道模型，用一个结构同时满足「多 collection 共享一条物理日志」「单 collection 内严格保序」「集群级变更需要唯一排序点」。日志的持有者是 StreamingNode，它靠单调递增的 Term 隔离失效归属，靠 TimeTick 划出 MVCC 的可见性边界；这也是 WAL 敢当真相源的底气。后端之间并非等价替换：Kafka 与 Pulsar 把持久化外包给成熟消息系统，RocksMQ 是单机嵌入，而 Woodpecker 是官方自研的云原生日志，用「quorum + 对象存储」同时买到低运维与无限容量——它的两种运行模式与取舍单独成篇：[Woodpecker](/docs/CS/DB/Milvus/Woodpecker.md)。

有了这层地基，[Write Path](/docs/CS/DB/Milvus/Write_Path.md) 讲的端到端链路就变得顺理成章：Proxy 完成校验与取号后把 DML 打成 WAL 消息，TSO、RowID、TimeTick 三个号码都源自 MixCoord——正因取号频率如此之高，3.0 把四个协调者合进单进程才有意义。落盘只是 WAL 的第一路消费者，QueryNode 的实时可见是第二路，两条路互不等待，所以「写完立刻能读」不需要等 flush。更细的机制各自成篇：写事务不是锁加隔离级别的套餐，而是 WAL 上的消息分组——一组 append 由 `Begin` / `CommitTxn` 圈起、提交前对读者不可见，防并发竞争的锁则是 append 路径上的 key 级闸门，见 [Transactions and Locking](/docs/CS/DB/Milvus/Transactions_and_Locking.md)。

## Serving a Search

查询侧的难点不是算得快，而是**一次请求要横跨十几个 shard，还得让它们给出同一个时间点的答案**。[Query Path](/docs/CS/DB/Milvus/Query_Path.md) 沿这条线展开：一致性级别如何落成一个具体要等待的时间戳、QueryCoord 为什么用「目标视图」而不是直接分配段、shard leader 的 delegator 如何把内存里的 growing 段与对象存储上的 sealed 段合成一份答案、以及删除墓碑（L0 段）在读取时才被应用成位图。真正做向量检索的是 C++ 的 segcore，Go 与它之间只过 plan、placeholder 与 bitset。

检索质量的天花板则由索引决定。[Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md) 给出 v3.0.1 的完整能力面：Knowhere 承担的算法层、稠密与稀疏索引的类型矩阵、每种索引支持哪些向量数据类型、mmap 与磁盘型索引如何换取内存、标量与 JSON 与全文倒排索引各自适合什么谓词，最后用功能矩阵说清它与 pgvector / Qdrant / Weaviate 的分工边界——ANN 算法本身的原理不在此重复，见 [vector](/docs/CS/DB/vector.md)。语义相似之外还有一类需求是**精确词项匹配**——订单号、错误码、专有名词；Milvus 用 analyzer 链加 tantivy 倒排补齐这块能力，并让文本字段经 function 直接产出 BM25 稀疏向量，与向量检索共存于同一次混合查询，见 [Full Text Search](/docs/CS/DB/Milvus/Full_Text_Search.md)。

## Durability and Cost

数据封口之后才是账单的大头。[Storage Layer](/docs/CS/DB/Milvus/Storage_Layer.md) 讲清三层存储模型与段在对象存储上的产物，并处理一个容易踩的坑：binlog 的 storage v1 与基于 manifest 的新引擎并非「旧的已过时」，v3.0.1 里三个版本常量共存、按字段类型与开关决定走哪条路。元数据则走 etcd 或 TiKV，这层容量与事务批大小直接决定协调者的调度节奏。

[Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md) 处理封口之后的所有事：段状态机、各类 compaction 的触发阈值与优先级、L0 删除段的消化、GC 为什么让「删了数据对象存储却没变小」、以及 TTL 这类**配置项存在但没有守护任务**的伪功能。这几节里对 LSM-tree 的对比，可以连着 [RocksDB](/docs/CS/DB/RocksDB/RocksDB.md) 与 [LevelDB](/docs/CS/DB/LevelDB/LevelDB.md) 一起看。

## Running It

形态与选型是部署的真正分水岭：同一套代码在 Lite / Standalone / Cluster 之间切换，查询与写入机制完全相同，生产可用性由三个外部依赖决定——WAL 后端、元数据 KV、对象存储。[Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md) 给出四后端对比与选择算法、配置三层叠加与「哪些改动必须重启」、可观测性入口、配额与限流为什么是写请求被拒的第一嫌疑、以及 Database / RBAC / Resource Group / Partition Key 四层多租户各自的事实落在哪个组件。

两件横切的事也在这条线上：跨集群容灾不在同一套 WAL 之内——CDC 角色从源集群日志读消息、经目标集群 Proxy 落入目标 WAL，复制的是变更流而非存储快照，见 [CDC and Replication](/docs/CS/DB/Milvus/CDC_and_Replication.md)；而跨进程、跨语言（Go↔C++）、跨协议（gRPC/REST）的失败语义由统一错误契约 merr 承担，排障时看到的每一个错误码都出自那里，见 [Error Model](/docs/CS/DB/Milvus/Error_Model.md)。动手环节看 [Deploy](/docs/CS/DB/Milvus/Deploy.md)：etcd + Kafka KRaft 三节点集群的完整实操。

## Default Values Worth Memorizing

| 事实 | 值 | 归属 |
| --- | --- | --- |
| 初始 PChannel 数，同时封顶单集合 shard 数 | `rootCoord.dmlChannelNum` 16 | WAL and StreamingNode |
| 段封口：目标大小与最小比例 | `dataCoord.segment.maxSize` 1024 MB、`sealProportion` 0.12 | Write Path |
| L0 删除段落盘阈值 | 50 万行 / 32 MB / 10 分钟 | Compaction and Lifecycle |
| 对象存储回收节奏 | `dataCoord.gc.interval` 3600s、`dropTolerance` 10800s | Compaction and Lifecycle |
| 新存储引擎开关 | `useLoonFFI` 默认 false，未全量切换 | Storage Layer |
| WAL 后端 | `mq.type` 默认 `default` 按形态推断，且**首次启动即钉进 etcd 不可热换** | Deployment and Ops |
| Bounded 一致性的回退量 | `common.gracefulTime` 5000 ms | Query Path |
| 元数据缓存 | 无 TTL、无容量上限，一致性全靠广播失效 | Metadata Cache |
| PChannel 再平衡保护 | `allowRebalance` true；迁移间隔 5m、恢复滞后 >1s 禁迁移 | WAL and StreamingNode |
| 内存保护水位 | 0.85 开始线性降速、0.95 直接拒写 | Deployment and Ops |
| RBAC | `common.security.authorizationEnabled` 默认 false | Deployment and Ops |

## Links

- [Deploy](/docs/CS/DB/Milvus/Deploy.md)
- [Write Path](/docs/CS/DB/Milvus/Write_Path.md)
- [Query Path](/docs/CS/DB/Milvus/Query_Path.md)
- [vector](/docs/CS/DB/vector.md)
- [DataBases](/docs/CS/DB/DB.md)
- [WAL](/docs/CS/DB/WAL.md)

## References

- [Milvus Repository](https://github.com/milvus-io/milvus)
- [Milvus v3.0.1 Release](https://github.com/milvus-io/milvus/releases/tag/v3.0.1)
- [Milvus Architecture Analysis](https://github.com/milvus-io/milvus/blob/master/docs/agent_guides/README.md)
- [Knowhere](https://github.com/zilliztech/knowhere)
- [Woodpecker Log Store](https://github.com/zilliztech/woodpecker)
- [Milvus Lite](https://github.com/milvus-io/milvus-lite)
