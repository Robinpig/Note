## Introduction

Milvus 是一个开源云原生向量数据库，专为在海量向量数据集上进行高性能相似性搜索而设计。

> 关于向量数据库的整体介绍（选型、ANN 搜索原理等），参见[向量数据库](/docs/CS/DB/vector.md)。

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

##### **Milvus Distributed**

Milvus Distributed 可以部署在 Kubernetes 集群上。这种部署采用云原生架构，摄取负载和搜索查询分别由独立节点处理，允许关键组件冗余。

<!-- tabs:end -->


## Architecture

Milvus 的云原生和高度解耦的系统架构确保了系统可以随着数据的增长而不断扩展。

<div style="text-align: center;">

![Highly decoupled system architecture of Milvus](https://milvus-docs.s3.us-west-2.amazonaws.com/assets/milvus_architecture_2_6.png)

</div>

<p style="text-align: center;">
Milvus 高度解耦的系统架构
</p>

Milvus 采用存算分离架构，本身是完全无状态的，因此可以借助 Kubernetes 或公共云轻松扩展。此外，Milvus 的各个组件都有很好的解耦，其中最关键的三项任务——搜索、数据插入和索引/压实——被设计为易于并行化的流程，复杂的逻辑被分离出来。这确保了相应的查询节点、数据节点和索引节点可以独立地向上和向下扩展，从而优化了性能和成本效率。

### Data Model

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

- **Database**：顶层逻辑单元，支持多租户隔离；
- **Collection**：类似关系型数据库中的表；
- **Partition**：Collection 的可选逻辑划分，可按分区键过滤以缩小搜索范围；
- **Segment**：物理存储与计算的基本单元，分为 Growing Segment（增量写入）和 Sealed Segment（固化后构建索引）。

## Links

- [Deploy](/docs/CS/DB/Milvus/Deploy.md)
- [向量数据库](/docs/CS/DB/vector.md)
- [DataBases](/docs/CS/DB/DB.md)
