## Introduction

本文主要是介绍一种在生产环境可用的基于Docker Compose 的 三节点 Milvus集群部署方案

## 0. 交付件概述

### 0.1 设计变更说明

本部署方案相较于 Milvus 官方默认部署方式，基于生产环境三节点分布式集群做了以下关键变更：

#### 网络模式变更

| 变更项 | 官方默认 | 本方案 |
|--------|---------|--------|
| 网络模式 | `bridge`（端口映射） | `host`（直接暴露宿主机端口） |
| 跨节点通信 | Docker DNS + 容器名 | 宿主机物理 IP（`193.195.129.57/58/59`） |
| Attu | 同属一个 compose 或独立 bridge | 单独 bridge 模式，`-p 28000:3000` 映射 |

Host 模式下消除了 Docker NAT 转发开销，但也要求端口规划不得冲突、防火墙策略精确到位。

#### 消息队列变更

| 变更项 | 官方默认 | 本方案 |
|--------|---------|--------|
| 消息队列 | NATS / RocksMQ（单机内置） | **Apache Kafka 3.4.0 KRaft** |
| 集群模式 | 无（单机）或单独部署 | 3 节点 KRaft 集群（combined `broker,controller`） |
| ZooKeeper | 需额外部署（Kafka 传统模式） | **无需 ZooKeeper**（KRaft 内置 Raft 选主） |

Kafka KRaft 替代 NATS 是 Milvus 生产环境中大吞吐场景的推荐方案，支持消息持久化、多消费者和水平扩展。

#### Metrics 端口分配

| 变更项 | 官方默认 | 本方案 |
|--------|---------|--------|
| Metrics 端口 | 所有组件共用 `9091`（端口冲突） | 每个组件独立分配 `9991-9998` |
| 分配策略 | 单端口复用 | 8 个组件各占一个 Metrics 端口 |

Host 模式下所有容器共享宿主机网络栈，组件共用 `9091` 必然冲突。本方案将 8 个 Milvus 组件 Metrics 端口拆分为 `9991-9998`，按组件角色逐一分配。

#### Coordinator 高可用

| 变更项 | 官方默认 | 本方案 |
|--------|---------|--------|
| Coordinator 部署 | 单实例（单点故障） | 3 节点 **Active-Standby** |
| 策略 | 无 | `xxx_COORD_ENABLE_ACTIVE_STANDBY: true` |

四个 Coordinator（RootCoord、DataCoord、QueryCoord、IndexCoord）均启用 Active-Standby 模式，每个节点上的 Coordinator 实例可互相热备，容忍单节点故障。

#### 资源隔离

| 变更项 | 官方默认 | 本方案 |
|--------|---------|--------|
| 资源限制 | 无（共享主机资源） | 按角色设定 CPU/内存限额 |
| 分配策略 | 无 | 物理机 32G 规划：os+docker 2G + etcd 4G + Milvus 业务 18G + 余量 8G |

**Milvus 各组件资源分配**：

| 组件 | 内存 | CPU | 说明 |
|------|------|-----|------|
| rootcoord / datacoord / querycoord / indexcoord | 各 1G | 各 1c | 协调节点，Active-Standby 热备 |
| proxy | 2G | 2c | 业务入口，F5 后端 |
| datanode | 2G | 2c | 数据持久化写盘 |
| querynode | **6G** | **4c** | 向量索引缓存 + 查询计算，内存大头 |
| indexnode | **4G** | **3c** | 索引构建，CPU 密集型 |
| **Milvus 合计** | **18G** | **16c** | — |

**宿主机资源规划（单节点 32G）**：

```
 OS + Docker 开销    2G
 etcd                4G     (docker run 独立进程)
 Milvus 8 组件      18G     (docker-compose 统一管理)
─────────────────────────────────
已分配小计          24G
保留余量             8G     (Kafka 无限制 + 系统突发、日志、监控采集)
─────────────────────────────────
总计                32G
```

### 0.2 项目结构

```
<部署节点 IP：193.195.129.57/58/59>
├── etcd/                              # etcd 部署（§1）
│   ├── deploy-etcd.sh                 # 安装脚本（Node1 版本，需按节点修改 IP 与 --name）
│   └── images/
│       └── milvus_etcd.tar            # etcd 3.5.5 离线镜像
│
├── kafka-cluster/                     # Kafka KRaft 部署（§2）
│   ├── deploy-kafka.sh                # 安装脚本（Node1 版本，需按节点修改 NODE_ID 与 IP）
│   ├── data/                          # Kafka 数据目录（首次部署自动创建）
│   └── kafka-3.4.0.tar               # Bitnami Kafka 3.4.0 离线镜像
│
├── milvus/                            # Milvus 分布式部署（§3）
│   ├── docker-compose.yaml            # 三节点统一 compose 文件（按节点修改环境变量）
│   ├── volumes/                       # Milvus 持久化数据卷
│   └── images/
│       └── milvusdb_milvus_v2.4.11.tar
│
├── attu/                              # Attu 运维控制台部署（§4）
│   ├── deploy-attu.sh                 # 安装脚本（仅 Node1 部署）
│   └── images/
│       └── milvus_attu.tar            # Attu 离线镜像
│
└── docs/
    └── AgentFlow — Milvus 生产环境部署 Host 模式 Kafka.md   # 本文档
```

**部署节点分布**：

| 节点 IP | 部署组件 |
|---------|---------|
| 193.195.129.57 | etcd-node1 + kafka-node1 + Milvus 全部 8 组件 + Attu |
| 193.195.129.58 | etcd-node2 + kafka-node2 + Milvus 全部 8 组件 |
| 193.195.129.59 | etcd-node3 + kafka-node3 + Milvus 全部 8 组件 |

> 每台节点上 Milvus 的 8 个组件（rootcoord、datacoord、querycoord、indexcoord、proxy、datanode、querynode、indexnode）全部启动，四个 Coordinator 通过 `ENABLE_ACTIVE_STANDBY` 实现跨节点热备。

### 0.3 硬性约束

- 跨主机连接必须使用节点 IP（`193.195.129.57/58/59`），不得使用 Docker 容器名或 localhost；
- 每个项目独立启停、独立验证、独立维护；
- **Host 网络模式下，端口冲突由运维保证** —— etcd `2379/2380`、Kafka `9092/9093`、Milvus Proxy `19530`、Milvus Metrics `9991-9998`；
- **同一宿主机上的每个 Milvus 组件必须配置不同的 `METRICS_PORT`**，禁止继续共用默认端口 `9091`。

### 0.4 版本基线

| 组件 | 固定版本 | 镜像 |
|------|----------|------|
| etcd | 3.5.5 | `quay.io/coreos/etcd:v3.5.5` |
| Kafka | **3.4.0**（KRaft 模式） | `kafka:3.4.0`  |
| Milvus | v2.4.11 | `milvusdb/milvus:v2.4.11` |
| Attu | v2.4 | `zilliz/attu:latest` |

> Kafka 3.4.0 KRaft 模式运行无需 ZooKeeper。生产环境推荐使用 `confluentinc/cp-kafka:3.4.0`（Confluent 打包，内置 KRaft 支持），也可使用 `apache/kafka:3.4.0` 官方镜像。
> 本次使用的镜像来源是 
`docker pull swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/bitnami/kafka:3.4.0`

### 0.5 端口规划（Host 模式独占）

Host 网络模式下，所有容器直接监听宿主机 IP 上的端口。三台节点端口规划完全对称。Kafka 已占用 `9092/9093`，Milvus Metrics 不得复用这两个端口，也不得继续使用默认 `9091`：

| 组件 | 端口 | 用途 | 防火墙策略 |
|------|------|------|-----------|
| etcd | 2379 | 客户端连接 | 仅 `193.195.129.57/58/59` |
| etcd | 2380 | Peer 集群通信 | 仅 `193.195.129.57/58/59` |
| Kafka | 9092 | 客户端连接（PLAINTEXT） | 仅 `193.195.129.57/58/59` |
| Kafka | 9093 | Controller 集群通信 | 仅 `193.195.129.57/58/59` |
| Milvus Proxy | 19530 | 业务入口 | 仅 `193.195.129.57/58/59`（F5 后端） |
| Milvus RootCoord | 53100 | 内部 gRPC | 仅 `193.195.129.57/58/59` |
| Milvus DataCoord | 13333 | 内部 gRPC | 仅 `193.195.129.57/58/59` |
| Milvus QueryCoord | 19531 | 内部 gRPC | 仅 `193.195.129.57/58/59` |
| Milvus IndexCoord | 22930 | 内部 gRPC | 仅 `193.195.129.57/58/59` |
| Milvus RootCoord Metrics | 9991 | Prometheus 指标 | 仅 `193.195.129.57/58/59` |
| Milvus DataCoord Metrics | 9992 | Prometheus 指标 | 仅 `193.195.129.57/58/59` |
| Milvus QueryCoord Metrics | 9993 | Prometheus 指标 | 仅 `193.195.129.57/58/59` |
| Milvus IndexCoord Metrics | 9994 | Prometheus 指标 | 仅 `193.195.129.57/58/59` |
| Milvus Proxy Metrics | 9995 | Prometheus 指标、F5 健康检查 | 仅 `193.195.129.57/58/59` |
| Milvus DataNode Metrics | 9996 | Prometheus 指标 | 仅 `193.195.129.57/58/59` |
| Milvus QueryNode Metrics | 9997 | Prometheus 指标 | 仅 `193.195.129.57/58/59` |
| Milvus IndexNode Metrics | 9998 | Prometheus 指标 | 仅 `193.195.129.57/58/59` |
| Milvus 内部（各 Worker 节点默认端口） | 21147、21149、21151 | DataNode/QueryNode/IndexNode 组件间 gRPC | 仅 `193.195.129.57/58/59` |
| Attu | 28000 | Web 运维控制台 | 仅 `193.195.129.57` |



## 1. etcd 部署

### 1.1 项目说明

- **项目目录**：`/aiapp/mid/etcd/`
- **网络模式**：`network_mode: host`
- **数据卷**：`/data/milvus/etcd` 挂载到容器 `/etcd`
- **资源限制**：CPU 2 核 / 内存 4 GB
- **集群规模**：3 节点 Raft（quorum=2，容忍 1 节点故障）


### 1.2 安装脚本

```bash
#!/bin/bash

# 环境变量
# 服务器地址
localhost="193.195.129.57"
# 安装包目录
path="/aiapp/mid/etcd"

# 设置安装包目录执行权限
chmod -R 777 "${path}"

# etcd安装
etcdInstall() {
    read -p "即将安装Etcd，是否安装 (y/n) : " lsY
    if [ "$lsY" = "y" ]
    then
        echo "加载镜像..."
        docker load -i images/milvus_etcd.tar
        echo "运行Etcd镜像..."
        docker run -d --restart=always --name etcd \
            --network host \
            -e ETCD_AUTO_COMPACTION_MODE=revision \
            -e ETCD_AUTO_COMPACTION_RETENTION=1000 \
            -e ETCD_QUOTA_BACKEND_BYTES=4294967296 \
            -e ETCD_SNAPSHOT_COUNT=50000 \
            -v "/aiapp/mid/etcd:/etcd" \
            quay.io/coreos/etcd:v3.5.5 \
            etcd \
            --name etcd-node1 \
            --listen-peer-urls http://0.0.0.0:2380 \
            --initial-advertise-peer-urls http://${localhost}:2380 \
            --initial-cluster etcd-node1=http://193.195.129.57:2380,etcd-node2=http://193.195.129.58:2380,etcd-node3=http://193.195.129.59:2380 \
            --advertise-client-urls=http://${localhost}:2379 \
            --listen-client-urls http://0.0.0.0:2379 \
            --data-dir /etcd
    else
        echo "跳过Etcd安装！"
    fi
}

etcdInstall
```

### 1.3 调优参数

另外的调优环境变量参数, 可以考虑添加

```bash
      # 高可用调优
      -e ETCD_HEARTBEAT_INTERVAL=250
      -e ETCD_ELECTION_TIMEOUT=1500
      -e ETCD_SNAPSHOT_COUNT=50000

      # 存储配额与自动压缩
      -e ETCD_QUOTA_BACKEND_BYTES=4294967296
      -e ETCD_AUTO_COMPACTION_MODE=revision
      -e ETCD_AUTO_COMPACTION_RETENTION=1000
```



### 1.4 Node2 / Node3 变体

仅需要替换脚本中两处 
- localhost 的IP为宿主机IP
- `--name` 对应的值需和 `--initial-cluster` 中配置的对应关系进行呼应

| 参数 | Node1 | Node2 | Node3 |
|------|-------|-------|-------|
| `--name` | `etcd-node1` | `etcd-node2` | `etcd-node3` |
| `localhost` | `193.195.129.57` | `193.195.129.58` | `193.195.129.59` |


`ETCD_INITIAL_CLUSTER` 三个节点完全一致，无需修改。

### 1.5 验证命令

```bash
# 检查容器状态
docker ps | grep etcd

# 验证 etcd 监听端口（host 模式下直接用 ss 检查宿主机端口）
ss -tlnp | grep -E '2379|2380'

# 检查集群健康
docker exec -T etcd etcdctl \
  --endpoints=http://193.195.129.57:2379,http://193.195.129.58:2379,http://193.195.129.59:2379 \
  endpoint health

# 查看成员状态
docker exec -T etcd etcdctl \
  --endpoints=http://193.195.129.57:2379,http://193.195.129.58:2379,http://193.195.129.59:2379 \
  endpoint status --write-out=table
```

> Host 模式下，etcd 的 2379/2380 端口直接暴露在宿主机网络接口上。防火墙规则必须严格限制 2380 仅允许三台 Milvus 节点互访（参见部署流程文档 §5.4）。


## 2. Kafka 3.4.0 KRaft

### 2.1 项目说明

- **网络模式**：`network_mode: host`
- **数据卷**：`/aiapp/mid/kafka-cluster/data` 挂载到容器 `/bitnami/kafka`
- **集群规模**：3 节点 KRaft 集群（combined `broker,controller` 角色，容忍 1 节点故障）
- **依赖**：无（KRaft 模式无需 ZooKeeper）

### 2.2 Kafka KRaft 集群设计

Kafka 3.4.0 KRaft 模式下，每个节点同时承担 Broker（数据存储与读写）和 Controller（元数据管理 + 选主）两个角色：

```text
                       ┌──────────────────────┐
                       │   Client (Milvus)     │
                       │   :9092 (PLAINTEXT)   │
                       └──────┬───────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
   │ Kafka Node 1 │   │ Kafka Node 2 │   │ Kafka Node 3 │
   │ 57:9092/9093 │   │ 58:9092/9093 │   │ 59:9092/9093 │
   │              │   │              │   │              │
   │ broker       │   │ broker       │   │ broker       │
   │ controller   │   │ controller   │   │ controller   │
   └──────────────┘   └──────────────┘   └──────────────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            │
                    KRaft Raft quorum
                    controller.quorum.voters
                    1@57:9093,2@58:9093,3@59:9093
```

### 2.3 安装脚本

以下是Kafka安装脚本 Node1 版本（`193.195.129.57`）

```bash
#!/bin/bash

# 环境变量
# 服务器地址
localhost="193.195.129.57"
# 安装包目录
path="/aiapp/mid/kafka-cluster"

# 设置安装目录执行权限
chmod -R 777 "${path}"

# Kafka安装
kafkainstall() {
        read -p "即将安装Kafka，是否安装 (y/n) : " isY
        if [ "$isY" = "y" ]
        then
                echo "加载镜像..."
                docker load -i kafka-3.4.0.tar
                echo "准备目录..."
                if [ ! -d "${path}/data" ]; then
                    mkdir -p ${path}/data
                fi
                chown 1001:1001 -R ${path}/data
                chmod 755 -R ${path}/data/
                echo "运行Kafka镜像..."
                # 修改node 和 node id
                docker run -d --name kafka-node1 \
                        --network host \
                        -e KAFKA_ENABLE_KRAFT=yes \
                        -e KAFKA_CFG_PROCESS_ROLES=controller,broker \
                        -e KAFKA_CFG_NODE_ID=1 \
                        -e KAFKA_CFG_CONTROLLER_LISTENER_NAMES=CONTROLLER \
                        -e KAFKA_CFG_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093 \
                        -e KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT \
                        -e KAFKA_CFG_ADVERTISED_LISTENERS=PLAINTEXT://${localhost}:9092 \
                        -e KAFKA_CFG_CONTROLLER_QUORUM_VOTERS=1@193.195.129.57:9093,2@193.195.129.58:9093,3@193.195.129.59:9093 \
                        -e KAFKA_KRAFT_CLUSTER_ID=MkU3OEVBNTcwNTJENDM5Qk \
                        -e ALLOW_PLAINTEXT_LISTENER=yes \
                        -v ${path}/data:/bitnami/kafka \
                        bitnami/kafka:3.4.0
        else
                echo "跳过Kafka安装！"
        fi
}

# Kafka运行
kafkainstall
```

### 2.4 Node2 / Node3 变体

| 参数 | Node1（57） | Node2（58） | Node3（59） |
|------|------------|------------|------------|
| `KAFKA_NODE_ID` | `1` | `2` | `3` |
| `KAFKA_ADVERTISED_LISTENERS` | `PLAINTEXT://193.195.129.57:9092` | `PLAINTEXT://193.195.129.58:9092` | `PLAINTEXT://193.195.129.59:9092` |

**以下参数三个节点完全一致**：

```yaml
CLUSTER_ID: "MkU3OEVBNTcwNTJENDM5Qk"                   # 同一集群使用相同 ID
KAFKA_CONTROLLER_QUORUM_VOTERS: "1@193.195.129.57:9093,2@193.195.129.58:9093,3@193.195.129.59:9093"
```

>
>  **CLUSTER_ID 生成**：在任意一台节点执行 `echo "MkU3OEVBNTcwNTJENDM5Qk" | base64 -d > /dev/null 2>&1 || echo "使用以下命令生成：kafka-storage random-uuid"`，或者直接使用 docker 执行：
>
> ```bash
> docker run --rm confluentinc/cp-kafka:3.4.0 kafka-storage random-uuid
> ```
> 将输出值填入三个节点的 `CLUSTER_ID` 环境变量。

### 2.5 验证命令

```bash
# 检查容器状态
docker ps

# 验证 Kafka 进程监听端口（Host 模式下直接检查宿主机）
ss -tlnp | grep -E '9092|9093'

# 验证 KRaft 集群状态（在任意节点执行）
docker exec -T kafka-node1 \
  kafka-metadata-quorum --bootstrap-server 193.195.129.57:9092,193.195.129.58:9092,193.195.129.59:9092 \
  describe --status

# 期望输出：LeaderId 存在，QuorumState 为 QuorumLeader 或 Follower
```

## 3. Milvus

### 3.1 项目说明

- **网络模式**：`network_mode: host`（所有 Milvus 组件）
- **数据卷**：`/data/milvus/volumes` 挂载到容器 `/var/lib/milvus`
- **消息队列**：Kafka 3.4.0（`MQ_TYPE=kafka`）
- **MinIO 统一入口**：F5 VIP `172.1.0.88:9000`，bucket `milvus-sunklm`
- **etcd 端点**：通过宿主机 IP:2379 访问
- **Kafka 端点**：通过宿主机 IP:9092 访问

> [!WARNNING]
>
> 部署 Milvus 需确认 Etcd,Kafka 和 对象存储（兼容MinIO）可用


### 3.2 安装配置（docker-compose）

需要确认的地方
- ETCD_ENDPOINTS

- MINIO的配置

- MQ配置

  



> [!NOTE]
> 
> security_opt 中 milvus-seccomp.json 是从 [docker-archive-public/docker.labs](https://github.com/docker-archive-public/docker.labs/blob/master/security/seccomp/seccomp-profiles/default.json) 获取的
>
> 开发测试环境可以使用 `privileged: true`，生产环境禁用



```yaml
version: '3.8'

# ==================== 环境变量定义 ====================
x-milvus-env: &milvus-env
  ETCD_ENDPOINTS: "193.195.129.57:2379,193.195.129.58:2379,193.195.129.59:2379"
  MINIO_ADDRESS: "${MINIO_ADDRESS}"
  MINIO_ACCESS_KEY_ID: "${MINIO_ACCESS_KEY_ID}"
  MINIO_SECRET_ACCESS_KEY: "${MINIO_SECRET_ACCESS_KEY}"
  MINIO_USE_SSL: "${MINIO_USE_SSL}"
  MINIO_BUCKET_NAME: "${MINIO_BUCKET_NAME}"
  KAFKA_BROKER_LIST: "193.195.129.57:9092,193.195.129.58:9092,193.195.129.59:9092"
  MQ_TYPE: "kafka"
  COMMON_STORAGETYPE: "minio"
  KNOWHERE_GPU_MEM_POOL_SIZE: "0"
  QUERYNODE_LOAD_MEMORY_LIMIT_FACTOR: "0.8"
  DATASEGMENT_MAX_SIZE: "1024"
  LOG_LEVEL: "info"
  COMMON_SECURITY_AUTHORIZATIONENABLED: "true"
  OPENBLAS_NUM_THREADS: 1
  OMP_NUM_THREADS: 1
  GOTO_NUM_THREADS: 1

# ==================== 公共模板定义 ====================
x-milvus-common: &milvus-common
  image: milvusdb/milvus:v2.4.11
  restart: always
  network_mode: host
  security_opt:
    - seccomp:/aiapp/mid/milvus/milvus-seccomp.json
  ulimits:
    nofile:
      soft: 65536
      hard: 65536
  volumes:
    - /data/milvus/volumes:/var/lib/milvus
  deploy: &base-deploy
    resources:
      limits:
        cpus: '1'
        memory: 1g

services:
  # ============== 协调节点 (active 主) ==============
  rootcoord:
    <<: *milvus-common
    environment:
      <<: *milvus-env
      METRICS_PORT: 9991
      ROOT_COORD_PORT: 53100
      ROOT_COORD_ADDRESS: rootcoord
      ROOT_COORD_ENABLE_ACTIVE_STANDBY: true
    container_name: milvus-rootcoord
    command: ["milvus", "run", "rootcoord"]

  datacoord:
    <<: *milvus-common
    environment:
      <<: *milvus-env
      METRICS_PORT: 9992
      DATA_COORD_PORT: 13333
      DATA_COORD_ADDRESS: datacoord
      DATA_COORD_ENABLE_ACTIVE_STANDBY: true
    container_name: milvus-datacoord
    command: ["milvus", "run", "datacoord"]

  querycoord:
    <<: *milvus-common
    environment:
      <<: *milvus-env
      METRICS_PORT: 9993
      QUERY_COORD_PORT: 19531
      QUERY_COORD_ADDRESS: querycoord
      QUERY_COORD_ENABLE_ACTIVE_STANDBY: true
    container_name: milvus-querycoord
    command: ["milvus", "run", "querycoord"]

  indexcoord:
    <<: *milvus-common
    environment:
      <<: *milvus-env
      GOTO_NUM_THREADS: 1
      METRICS_PORT: 9994
      INDEX_COORD_PORT: 22930
      INDEX_COORD_ADDRESS: indexcoord
      INDEX_COORD_ENABLE_ACTIVE_STANDBY: true
    container_name: milvus-indexcoord
    command: ["milvus", "run", "indexcoord"]

  # ============== 工作节点  ==============
  proxy:
    <<: *milvus-common
    environment:
      <<: *milvus-env
      METRICS_PORT: 9995
    container_name: milvus-proxy
    command: ["milvus", "run", "proxy"]
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2g

  datanode:
    <<: *milvus-common
    environment:
      <<: *milvus-env
      METRICS_PORT: 9996
    container_name: milvus-datanode
    command: ["milvus", "run", "datanode"]
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2g

  querynode:
    <<: *milvus-common
    environment:
      <<: *milvus-env
      METRICS_PORT: 9997
    container_name: milvus-querynode
    command: ["milvus", "run", "querynode"]
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 6g

  indexnode:
    <<: *milvus-common
    environment:
      <<: *milvus-env
      METRICS_PORT: 9998
    container_name: milvus-indexnode
    command: ["milvus", "run", "indexnode"]
    deploy:
      resources:
        limits:
          cpus: '3'
          memory: 4g
```

### 3.3 验证命令

```bash
# 检查 8 个 Milvus 容器全部运行
docker ps | grep milvus

# 验证关键端口监听（Host 模式下直接检查宿主机）
ss -tlnp | grep -E '19530|999[1-8]|53100|13333|19531|22930'

# 检查 Proxy 健康状态（通过 metrics 端点）
curl -s http://193.195.129.57:9995/metrics | head -20

# 验证 Milvus 组件列表（通过 Proxy 的 gRPC 接口）
# 方式一：使用 milvus-cli（需额外安装）
# milvus-cli --host 193.195.129.57 --port 19530

# 方式二：使用 Python SDK 验证连接（可选）
python3 -c "
from pymilvus import connections, utility
connections.connect(host='193.195.129.57', port='19530')
print('Milvus 连接成功')
print('服务版本:', utility.get_server_version())
print('集合列表:', utility.list_collections())
"

# 查看各个组件的日志确认无报错
docker logs milvus-rootcoord --tail 20
docker logs milvus-datacoord --tail 20
docker logs milvus-querycoord --tail 20
docker logs milvus-indexcoord --tail 20
docker logs milvus-proxy --tail 20
docker logs milvus-datanode --tail 20
docker logs milvus-querynode --tail 20
docker logs milvus-indexnode --tail 20
```

> **验证要点**：
> - `docker ps` 应输出 8 个 Milvus 容器（rootcoord、datacoord、querycoord、indexcoord、proxy、datanode、querynode、indexnode），状态均为 `Up`
> - `ss` 应监听 `19530`（Proxy 业务入口）及 `9991-9998`（各组件 Metrics）
> - Python SDK 连接测试需在装有 `pymilvus` 的客户端执行，首次连接成功即表示集群可正常服务


## 4. Attu

### 4.1 项目说明

Attu 是 Milvus 的 Web 运维控制台，用于验证Milvus集群部署状态和基本操作。

- **网络模式**：`bridge`（单独部署，非 Host 模式）
- **宿主机端口**：`28000`（映射到容器内 `3000`）
- **部署节点**：仅 `193.195.129.57`（Node1）
- **依赖**：Milvus Proxy（`19530`）正常运行

### 4.2 安装脚本

```bash
#!/bin/bash

# 环境变量
# 服务器地址
localhost="193.195.129.57"
# 安装包目录
path="/aiapp/mid/attu"

# 设置安装目录执行权限
chmod -R 777 "${path}"

attuInstall() {
    read -p '即将安装Milvus Attu，是否安装（y/n）：' isY
    if [ "$isY" = "y" ]
    then
         echo "加载 Milvus Attu 镜像..."
         docker load -i images/milvus_attu.tar
        echo "运行 Milvus_attu 镜像..."
        docker run -d --restart=always --name milvus-attu \
            -e HOST_URL=http://${localhost}:28000 \
            -e MILVUS_URL=${localhost}:19530 \
            -p 28000:3000 \
            zilliz/attu:latest
    else
        echo "跳过Milvus Attu安装！"
    fi
}

attuInstall
```

### 4.3 访问说明

- **Web 控制台**：`http://193.195.129.57:28000`
- **Milvus 连接地址**：`http://193.195.129.57:19530`
- Attu 与 Milvus 部署在同一台机器上，所以 `HOST_URL` 和 `MILVUS_URL` 均为 `localhost`

## 5. 总结

> **首次启动要点**：
> - etcd 三节点全部启动后，**必须确认 quorum** 再启动 Kafka；
> - Kafka 三节点全部启动后，**必须确认 KRaft 元数据 quorum** 再启动 Milvus；
> - Host 模式下端口直接暴露，启动前务必确认端口未被占用。



## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)