## Introduction

Milvus 是一个开源云原生向量数据库，专为在海量向量数据集上进行高性能相似性搜索而设计。


## Installation

Milvus 有三种部署选项：Milvus Lite、Milvus Standalone 和 Milvus Distributed

Milvus Lite是一个 Python 库，可导入到您的应用程序中。作为 Milvus 的轻量级版本，它非常适合在 Jupyter Notebooks 中进行快速原型开发，或在资源有限的智能设备上运行
运行 `pip install pymilvus milvus-lite` 进行安装，并使用`MilvusClient("./demo.db")` 语句实例化一个带有本地文件的向量数据库，以持久化所有数据

示例代码

```python
from pymilvus import MilvusClient
import random

# 1. 启动/连接 Milvus Lite
# 指定一个本地文件路径（如 ./milvus_demo.db），Milvus Lite 会自动创建并启动
# 如果文件已存在，则会直接加载之前的数据
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

# 3. 插入数据
# 准备一些模拟数据
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


Milvus Standalone 是单机服务器部署。Milvus Standalone 的所有组件都打包到一个Docker 镜像中，部署起来非常方便

Milvus Distributed 可以部署在Kubernetes集群上。这种部署采用云原生架构，摄取负载和搜索查询分别由独立节点处理，允许关键组件冗余







## Architecture

Milvus 的云原生和高度解耦的系统架构确保了系统可以随着数据的增长而不断扩展

![Highly decoupled system architecture of Milvus](https://milvus-docs.s3.us-west-2.amazonaws.com/assets/milvus_architecture_2_6.png)

Milvus 采用存算分离架构，本身是完全无状态的，因此可以借助 Kubernetes 或公共云轻松扩展。此外，Milvus 的各个组件都有很好的解耦，其中最关键的三项任务--搜索、数据插入和索引/压实--被设计为易于并行化的流程，复杂的逻辑被分离出来。这确保了相应的查询节点、数据节点和索引节点可以独立地向上和向下扩展，从而优化了性能和成本效率









## Links

