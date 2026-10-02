## Introduction

本文主要是介绍一种在生产环境可用的基于Docker Compose 的 三节点 Milvus集群部署方案。

### 部署方案总览

各部署方案共享 §1（etcd）、§2（Kafka）的中间件部署，差异集中在 Milvus 自身的 compose 配置：

| 章节 | 方案 | 消息队列 | 状态 |
|------|------|---------|------|
| §0–§5 | **Milvus 2.4 + Kafka** | 外部 Kafka 3.4.1 KRaft（二进制部署） | 已实现 |
| §6 | **Milvus 3.0 + Kafka** | 外部 Kafka 3.4.1 KRaft（二进制部署） | 待补充 |
| §7 | **Milvus 3.x + Woodpecker** | 内置 Woodpecker（3.x 默认） | 方案说明 |
| §8 | Prometheus 监控 | — | 通用 |

> **版本说明**：§0–§5 基于 **Milvus 2.4.11**，使用外部 Kafka 3.4.1 KRaft（二进制部署）作为消息队列；§6、§7 介绍 **Milvus 3.x** 的两种消息队列方案——§6 沿用外部 Kafka，§7 使用内置 Woodpecker 替代外部 MQ 后的部署差异。

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
| 消息队列 | NATS / RocksMQ（单机内置） | **Apache Kafka 3.4.1 KRaft（二进制部署）** |
| 集群模式 | 无（单机）或单独部署 | 3 节点 KRaft 集群（combined `broker,controller`），宿主机进程直跑，不经过 Docker |
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
保留余量             8G     (系统突发、日志、监控采集)
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
├── kafka-cluster/                     # Kafka KRaft 二进制部署（§2）
│   ├── deploy-kafka.sh                # 安装脚本（Node1 版本，需按节点修改 NODE_ID 与 IP）
│   ├── kafka_2.13-3.4.1.tgz           # 官方二进制包（wget 下载，见 §2.3）
│   ├── kafka_2.13-3.4.1/              # 解压后的 Kafka 安装目录
│   ├── data/                          # Kafka 日志数据目录 log.dirs（首次部署自动创建）
│   └── logs/                          # Kafka 运行日志（LOG_DIR）
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

| 组件 | 固定版本 | 分发方式 |
|------|----------|------|
| etcd | 3.5.5 | 镜像 `quay.io/coreos/etcd:v3.5.5` |
| Kafka | **3.4.1**（KRaft 模式，Scala 2.13 构建） | 二进制包 `kafka_2.13-3.4.1.tgz`，宿主机进程直跑 |
| Milvus | v2.4.11 | 镜像 `milvusdb/milvus:v2.4.11` |
| Attu | v2.4 | 镜像 `zilliz/attu:latest` |

> Kafka 3.4.1 KRaft 模式运行无需 ZooKeeper，也不经过 Docker。二进制包从 Apache 官方归档下载：
>
> ```bash
> wget https://archive.apache.org/dist/kafka/3.4.1/kafka_2.13-3.4.1.tgz
> ```
>
> Kafka 3.4.x 运行依赖 **JDK 11+**，部署前需在三台节点预先安装 JDK（如 `yum install -y java-11-openjdk` 或 `apt install -y openjdk-11-jdk`）。

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
chmod -R 755 "${path}"

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
            --user $(id -u):$(id -g) \
            --log-driver json-file \
            --log-opt max-size=100m \
            --log-opt max-file=7 \
            -v "/aiapp/mid/etcd/data:/etcd-data" \
            -v "/aiapp/mid/etcd/logs:/etcd/logs" \
            quay.io/coreos/etcd:v3.5.5 \
            etcd \
            --name etcd-node1 \
            --listen-peer-urls http://0.0.0.0:2380 \
            --initial-advertise-peer-urls http://${localhost}:2380 \
            --initial-cluster etcd-node1=http://193.195.129.57:2380,etcd-node2=http://193.195.129.58:2380,etcd-node3=http://193.195.129.59:2380 \
            --advertise-client-urls=http://${localhost}:2379 \
            --listen-client-urls http://0.0.0.0:2379 \
            --log-outputs=/etcd/logs/etcd.log \
            --log-level=info \
            --data-dir /etcd-data
    else
        echo "跳过Etcd安装！"
    fi
}

etcdInstall
```

> **注意**：不建议将系统日志目录挂载进容器。以上脚本基于 etcd v3.5.5。

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


## 2. Kafka 3.4.1 KRaft（二进制部署）

### 2.1 项目说明

- **部署方式**：官方二进制包 `kafka_2.13-3.4.1.tgz`，解压后以宿主机进程直接运行（不使用 Docker）
- **运行依赖**：JDK 11+（KRaft 模式无需 ZooKeeper）
- **安装目录**：`/aiapp/mid/kafka-cluster/kafka_2.13-3.4.1/`
- **数据目录**：`/aiapp/mid/kafka-cluster/data`（`log.dirs`）
- **日志目录**：`/aiapp/mid/kafka-cluster/logs`（`LOG_DIR`）
- **监听端口**：进程直接绑定宿主机网卡，`9092`（PLAINTEXT 客户端）/ `9093`（CONTROLLER 集群通信）
- **集群规模**：3 节点 KRaft 集群（combined `broker,controller` 角色，容忍 1 节点故障）

### 2.2 Kafka KRaft 集群设计

Kafka 3.4.1 KRaft 模式下，每个节点同时承担 Broker（数据存储与读写）和 Controller（元数据管理 + 选主）两个角色：

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

以下是 Kafka 安装脚本 Node1 版本（`193.195.129.57`）。脚本完成：下载二进制包 → 解压 → 生成 `server.properties` → `kafka-storage.sh format` 格式化元数据 → 后台启动。

```bash
#!/bin/bash

# 环境变量
# 服务器地址
localhost="193.195.129.57"
# 本节点 node.id（Node1=1, Node2=2, Node3=3）
node_id="1"
# 安装包目录
path="/aiapp/mid/kafka-cluster"
kafka_version="3.4.1"
scala_version="2.13"
kafka_pkg="kafka_${scala_version}-${kafka_version}"
kafka_home="${path}/${kafka_pkg}"
# KRaft 集群 ID，三个节点必须完全一致（22 位 base64，可用 kafka-storage.sh random-uuid 生成）
cluster_id="MkU3OEVBNTcwNTJENDM5Qk"
quorum_voters="1@193.195.129.57:9093,2@193.195.129.58:9093,3@193.195.129.59:9093"

# Kafka安装
kafkainstall() {
    read -p "即将安装Kafka，是否安装 (y/n) : " isY
    if [ "$isY" = "y" ]
    then
        # 前置检查：JDK 11+
        if ! java -version 2>&1 | grep -Eq '"(11|1[2-9]|[2-9][0-9])\.'; then
            echo "未检测到 JDK 11+，请先安装 JDK（yum install -y java-11-openjdk 或 apt install -y openjdk-11-jdk）"
            exit 1
        fi

        echo "下载 Kafka 二进制包..."
        cd "${path}"
        if [ ! -f "${kafka_pkg}.tgz" ]; then
            wget https://archive.apache.org/dist/kafka/${kafka_version}/${kafka_pkg}.tgz
        fi

        echo "解压..."
        tar -xzf "${kafka_pkg}.tgz"

        echo "准备数据与日志目录..."
        mkdir -p "${path}/data" "${path}/logs"

        echo "生成 KRaft server.properties..."
        cat > "${kafka_home}/config/kraft/server.properties" <<EOF
process.roles=broker,controller
node.id=${node_id}
controller.quorum.voters=${quorum_voters}

listeners=PLAINTEXT://:9092,CONTROLLER://:9093
advertised.listeners=PLAINTEXT://${localhost}:9092
controller.listener.names=CONTROLLER
listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
inter.broker.listener.name=PLAINTEXT

num.partitions=1
offsets.topic.replication.factor=3
transaction.state.log.replication.factor=3
transaction.state.log.min.isr=2

log.dirs=${path}/data
log.retention.hours=168
log.segment.bytes=1073741824
EOF

        echo "格式化 KRaft 元数据存储（cluster.id=${cluster_id}）..."
        # 注意：format 只能在首次部署执行一次，重复执行会清空已格式化的元数据
        if [ ! -f "${path}/data/meta.properties" ]; then
            "${kafka_home}/bin/kafka-storage.sh" format -t "${cluster_id}" \
                -c "${kafka_home}/config/kraft/server.properties"
        else
            echo "meta.properties 已存在，跳过 format"
        fi

        echo "启动 Kafka..."
        export LOG_DIR="${path}/logs"
        export KAFKA_HEAP_OPTS="-Xms2G -Xmx2G"
        "${kafka_home}/bin/kafka-server-start.sh" -daemon \
            "${kafka_home}/config/kraft/server.properties"

        echo "Kafka 启动完成，日志见 ${path}/logs/server.log"
    else
        echo "跳过Kafka安装！"
    fi
}

kafkainstall
```

> **停止 / 重启**：
>
> ```bash
> # 停止
> export LOG_DIR=/aiapp/mid/kafka-cluster/logs
> /aiapp/mid/kafka-cluster/kafka_2.13-3.4.1/bin/kafka-server-stop.sh
> # 重启（先停后启）
> /aiapp/mid/kafka-cluster/kafka_2.13-3.4.1/bin/kafka-server-start.sh -daemon \
>     /aiapp/mid/kafka-cluster/kafka_2.13-3.4.1/config/kraft/server.properties
> ```

> **生产环境建议使用 systemd 托管进程**（开机自启、崩溃重启）。`kafka.service` 示例（注意 systemd 下不要加 `-daemon`）：
>
> ```ini
> [Unit]
> Description=Apache Kafka KRaft
> After=network.target
>
> [Service]
> Type=simple
> Environment="LOG_DIR=/aiapp/mid/kafka-cluster/logs"
> Environment="KAFKA_HEAP_OPTS=-Xms2G -Xmx2G"
> ExecStart=/aiapp/mid/kafka-cluster/kafka_2.13-3.4.1/bin/kafka-server-start.sh /aiapp/mid/kafka-cluster/kafka_2.13-3.4.1/config/kraft/server.properties
> ExecStop=/aiapp/mid/kafka-cluster/kafka_2.13-3.4.1/bin/kafka-server-stop.sh
> Restart=always
> LimitNOFILE=65536
>
> [Install]
> WantedBy=multi-user.target
> ```

### 2.4 Node2 / Node3 变体

脚本中仅需修改两处变量：

| 变量 | Node1（57） | Node2（58） | Node3（59） |
|------|------------|------------|------------|
| `node_id` | `1` | `2` | `3` |
| `localhost` | `193.195.129.57` | `193.195.129.58` | `193.195.129.59` |

生成的 `server.properties` 中对应差异项：

| 配置项 | Node1（57） | Node2（58） | Node3（59） |
|------|------------|------------|------------|
| `node.id` | `1` | `2` | `3` |
| `advertised.listeners` | `PLAINTEXT://193.195.129.57:9092` | `PLAINTEXT://193.195.129.58:9092` | `PLAINTEXT://193.195.129.59:9092` |

**以下配置三个节点完全一致**：

```properties
cluster.id（format 时使用）= MkU3OEVBNTcwNTJENDM5Qk
controller.quorum.voters=1@193.195.129.57:9093,2@193.195.129.58:9093,3@193.195.129.59:9093
```

> **CLUSTER_ID 生成**：在任意一台节点解压后的安装目录下执行，输出值填入三个节点脚本的 `cluster_id` 变量：
>
> ```bash
> /aiapp/mid/kafka-cluster/kafka_2.13-3.4.1/bin/kafka-storage.sh random-uuid
> ```
>
> 三个节点必须使用**同一个** cluster.id 分别 format，且 format 只能在首次启动前执行一次。

### 2.5 验证命令

```bash
# 检查 Kafka 进程（Kafka 进程主类为 kafka.Kafka）
jps | grep Kafka
ps -ef | grep 'kafka.Kafka' | grep -v grep

# 验证 Kafka 监听端口（进程直接绑定宿主机网卡）
ss -tlnp | grep -E '9092|9093'

# 验证 KRaft 集群状态（在任意节点安装目录下执行）
/aiapp/mid/kafka-cluster/kafka_2.13-3.4.1/bin/kafka-metadata-quorum.sh \
  --bootstrap-server 193.195.129.57:9092,193.195.129.58:9092,193.195.129.59:9092 \
  describe --status

# 期望输出：LeaderId 存在，QuorumState 为 QuorumLeader 或 Follower

# 查看 broker 注册情况（应列出 3 个节点 id: 1,2,3）
/aiapp/mid/kafka-cluster/kafka_2.13-3.4.1/bin/kafka-broker-api-versions.sh \
  --bootstrap-server 193.195.129.57:9092,193.195.129.58:9092,193.195.129.59:9092 | awk -F: '{print $1}'
```

## 3. Milvus 2.4 + Kafka

### 3.1 项目说明

- **网络模式**：`network_mode: host`（所有 Milvus 组件）
- **数据卷**：`/data/milvus/volumes` 挂载到容器 `/var/lib/milvus`
- **消息队列**：Kafka 3.4.1 KRaft 二进制部署（`MQ_TYPE=kafka`）
- **MinIO 统一入口**：F5 VIP `172.1.0.88:9000`，bucket `milvus-sunklm`
- **etcd 端点**：通过宿主机 IP:2379 访问
- **Kafka 端点**：通过宿主机 IP:9092 访问

> [!WARNING]
>
> 部署 Milvus 需确认 Etcd、Kafka 和对象存储（兼容 MinIO）可用


### 3.2 安装配置（docker-compose）

部署前需重点确认以下配置项：

- **ETCD_ENDPOINTS**：三节点 etcd 地址；
- **MinIO 配置**：对象存储入口、AccessKey/SecretKey、bucket；
- **MQ 配置**：`MQ_TYPE=kafka` 及 `KAFKA_BROKER_LIST`。

> [!NOTE]
> 
> security_opt 中 milvus-seccomp.json 是从 [docker-archive-public/docker.labs](https://github.com/docker-archive-public/docker.labs/blob/master/security/seccomp/seccomp-profiles/default.json) 获取的
>
> 开发测试环境可以使用 `privileged: true`，生产环境禁用



```yaml
version: '3.8'

# ==================== 环境变量定义 ====================
x-milvus-env: &milvus-env
  # HOST_IP 在每节点的 .env 中设置为本机 IP（57/58/59），供 coordinator 注册地址使用
  HOST_IP: "${HOST_IP}"
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
  LOG_FORMAT: "json"
  # Milvus 文件日志轮转配置
  # maxSize 单位通常是 MB
  # maxAge 单位通常是天
  # maxBackups 是保留的历史文件数量
  LOG_FILE_MAXSIZE: "100"
  LOG_FILE_MAXAGE: "7"
  LOG_FILE_MAXBACKUPS: "5"
  COMMON_SECURITY_AUTHORIZATIONENABLED: "true"

x-logging: &default-logging
  driver: json-file
  options:
    max-size: "100m"
    max-file: "7"

# ==================== 公共模板定义 ====================
x-milvus-common: &milvus-common
  image: milvusdb/milvus:v2.4.11
  user: "xxxx:xxxx"
  restart: always
  network_mode: host
  logging: *default-logging
  security_opt:
    - seccomp:/aiapp/mid/milvus/milvus-seccomp.json
  ulimits:
    nofile:
      soft: 65536
      hard: 65536
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
    volumes:
    # 数据与日志在宿主机上为同级目录，避免嵌套挂载导致遮蔽
      - /data/milvus/rootcoord/data:/var/lib/milvus
      - /data/milvus/rootcoord/logs:/var/lib/milvus/logs
    command: ["milvus", "run", "rootcoord"]

  datacoord:
    <<: *milvus-common
    environment:
      <<: *milvus-env
      METRICS_PORT: 9992
      DATA_COORD_PORT: 13333
      DATA_COORD_ADDRESS: datacoord
      DATA_COORD_ENABLE_ACTIVE_STANDBY: true
      LOG_FILE_ROOTPATH: /var/lib/milvus/logs/datacoord
    container_name: milvus-datacoord
    command: ["milvus", "run", "datacoord"]

  querycoord:
    <<: *milvus-common
    environment:
      <<: *milvus-env
      METRICS_PORT: 9993
      QUERY_COORD_PORT: 19531
      QUERY_COORD_ADDRESS: "${HOST_IP}"
      QUERY_COORD_ENABLE_ACTIVE_STANDBY: true
      LOG_FILE_ROOTPATH: /var/lib/milvus/logs/querycoord
    container_name: milvus-querycoord
    command: ["milvus", "run", "querycoord"]

  indexcoord:
    <<: *milvus-common
    environment:
      <<: *milvus-env
      METRICS_PORT: 9994
      INDEX_COORD_PORT: 22930
      INDEX_COORD_ADDRESS: "${HOST_IP}"
      INDEX_COORD_ENABLE_ACTIVE_STANDBY: true
      LOG_FILE_ROOTPATH: /var/lib/milvus/logs/indexcoord
    container_name: milvus-indexcoord
    command: ["milvus", "run", "indexcoord"]
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 1g

  # ============== 工作节点  ==============
  proxy:
    <<: *milvus-common
    environment:
      <<: *milvus-env
      METRICS_PORT: 9995
      LOG_FILE_ROOTPATH: /var/lib/milvus/logs/proxy
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
      LOG_FILE_ROOTPATH: /var/lib/milvus/logs/datanode
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
      LOG_FILE_ROOTPATH: /var/lib/milvus/logs/querynode
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
      LOG_FILE_ROOTPATH: /var/lib/milvus/logs/indexnode
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

---

## 6. Milvus 3.0 + Kafka 部署（待补充）

> [!TODO]
> 本章节后续补充 **Milvus 3.0 + 外部 Kafka** 的完整部署方案。与 §0–§5（Milvus 2.4.11 + Kafka）相比，etcd、Kafka、端口规划、Attu 等中间件部分完全复用，差异集中在 Milvus 自身的 compose 配置。

### 6.1 方案说明

- **镜像版本**：`milvusdb/milvus:v3.0.x`（以实际选型为准）
- **消息队列**：继续使用外部 Kafka 3.4.1 KRaft（`MQ_TYPE=kafka`），复用 §2 的三节点集群
- **启动依赖链**：etcd quorum → Kafka KRaft quorum → Milvus（与 2.4 相同）
- **端口规划**：与 §0.5 保持一致，无新增端口

### 6.2 与 2.4 部署的差异（初稿）

| 变更项 | 2.4.11（§3） | 3.0 + Kafka |
|--------|-------------|-------------|
| 镜像 | `milvusdb/milvus:v2.4.11` | `milvusdb/milvus:v3.0.x` |
| MQ 配置 | `MQ_TYPE=kafka` + `KAFKA_BROKER_LIST` | 沿用，具体环境变量名以 3.x 官方配置参考为准 |
| Coordinator Active-Standby | `*_ENABLE_ACTIVE_STANDBY: true` | 待确认（3.x 部署形态可能有变化） |
| 废弃配置项 | — | 清理 `milvus.yaml` 中已废弃的 `kafka.*` 参数 |

### 6.3 待补充内容

- [ ] 3.0 + Kafka 完整 docker-compose.yaml（三节点，Host 模式）
- [ ] 环境变量与 2.4 的逐项对照（以 3.x 官方 `milvus.yaml` 为准）
- [ ] 验证命令与 §3.3 的差异
- [ ] 从 2.4 + Kafka 升级到 3.0 + Kafka 的升级路径与回滚说明

## 7. Milvus 3.x + Woodpecker

### 7.1 Woodpecker 概述

Milvus 3.x 引入了 **Woodpecker** 作为内置的 WAL（Write-Ahead Log）/ 流存储引擎，**完全取代了 Kafka、Pulsar、NATS、RocksMQ 等外部消息队列**。

在 Milvus 2.x 架构中，外部 MQ 承担三项核心职责：

1. **WAL**：Proxy 将写入操作追加到 MQ，DataNode 消费并持久化；
2. **事件总线**：组件间通过 MQ Topic 传递增量数据；
3. **流回放**：QueryNode 通过消费 MQ 重建内存视图。

Woodpecker 将上述能力内建到 Milvus 自身：

| 维度 | 2.x（外部 MQ） | 3.x（Woodpecker） |
|------|---------------|-------------------|
| 部署形态 | 独立 Kafka/Pulsar 集群 | Milvus 内置，无需独立部署 |
| 数据持久化 | MQ 自身存储（Kafka segment / Pulsar BookKeeper） | Woodpecker 日志段直接写入对象存储 / 本地盘 |
| 副本一致性 | 依赖 MQ 副本机制（KRaft / BookKeeper） | 内置 Raft 协议复制日志 |
| 运维复杂度 | 需维护 MQ 集群的版本、扩缩容、磁盘 | 与 Milvus 生命周期统一管理 |
| 资源开销 | 额外 JVM 堆内存、page cache | 无额外进程，与 Milvus 共享资源 |

> Woodpecker 的核心设计目标是消除外部 MQ 的运维负担和资源冗余，同时针对 Milvus 的写入模式（顺序追加、按 segment 消费）做日志存储优化。

### 7.2 部署拓扑变更

移除 Kafka 集群后，三节点部署从 **etcd + Kafka + Milvus** 三层简化为 **etcd + Milvus** 两层：

| 节点 IP | 2.x 部署组件 | 3.x 部署组件 |
|---------|-------------|-------------|
| 193.195.129.57 | etcd-node1 + kafka-node1 + Milvus 8 组件 + Attu | etcd-node1 + Milvus 8 组件 + Attu |
| 193.195.129.58 | etcd-node2 + kafka-node2 + Milvus 8 组件 | etcd-node2 + Milvus 8 组件 |
| 193.195.129.59 | etcd-node3 + kafka-node3 + Milvus 8 组件 | etcd-node3 + Milvus 8 组件 |

**启动依赖链简化**：

```
2.x:  etcd quorum → Kafka KRaft quorum → Milvus
3.x:  etcd quorum → Milvus（Woodpecker 随 Milvus 自启）
```

不再需要 Kafka 数据目录（`/aiapp/mid/kafka-cluster/data`）、Kafka 二进制安装目录（`kafka_2.13-3.4.1/`）以及 `deploy-kafka.sh` 脚本。

### 7.3 端口规划变更

移除 Kafka 后释放以下端口：

| 端口 | 2.x 用途 | 3.x |
|------|---------|-----|
| 9092 | Kafka 客户端连接（PLAINTEXT） | **释放** |
| 9093 | Kafka Controller 通信 | **释放** |

Woodpecker 作为 Milvus 内置组件，复用 Milvus 已有的内部通信端口，**不引入额外的宿主机端口监听**。其余端口规划（etcd 2379/2380、Milvus Proxy 19530、Metrics 9991–9998 等）保持不变。

### 7.4 docker-compose 配置变更

#### 7.4.1 移除的配置

`x-milvus-env` 中删除所有 Kafka 相关环境变量：

```yaml
# 以下配置在 3.x 中移除
KAFKA_BROKER_LIST: "193.195.129.57:9092,193.195.129.58:9092,193.195.129.59:9092"
MQ_TYPE: "kafka"
```

#### 7.4.2 Woodpecker 配置

Milvus 3.x 中 Woodpecker 作为默认 WAL 引擎，`MQ_TYPE` 默认为 `woodpecker`（或已移除该配置项）。Woodpecker 的数据目录、副本数等通过 `woodpecker.*` 配置项控制，在 docker-compose 中映射为大写环境变量。典型配置如下：

```yaml
x-milvus-env: &milvus-env
  HOST_IP: "${HOST_IP}"
  ETCD_ENDPOINTS: "193.195.129.57:2379,193.195.129.58:2379,193.195.129.59:2379"
  # ... MinIO / 日志 / 鉴权等配置与 2.x 相同 ...

  # 3.x：Woodpecker WAL 配置
  # 具体环境变量名以对应 3.x 版本官方配置参考为准
  WOODPECKER_PATH: "/var/lib/milvus/woodpecker"    # WAL 日志存储路径
  WOODPECKER_REPLICATION_FACTOR: "3"                 # 日志副本数（建议等于节点数，容忍 1 节点故障）
```

> **注意**：Woodpecker 的具体环境变量名称、默认值和可用配置项随 Milvus 3.x 小版本迭代可能调整。部署前应以目标版本的官方配置参考（`milvus.yaml` 中 `woodpecker` 段）为准。

#### 7.4.3 数据卷

Woodpecker 的日志数据需要持久化。在各服务的 `volumes` 中确保 Woodpecker 路径被挂载到宿主机：

```yaml
volumes:
  - /data/milvus/rootcoord/data:/var/lib/milvus
  # Woodpecker 日志随 /var/lib/milvus 统一持久化，
  # 无需单独挂载（WOODPECKER_PATH 在该目录下）
```

#### 7.4.4 镜像版本

```yaml
x-milvus-common: &milvus-common
  image: milvusdb/milvus:v3.0.0   # 替换为实际部署的 3.x 版本
```

### 7.5 资源规划调整

移除 Kafka 后，单节点可回收 Kafka 占用的资源（典型为 2–4 GB 内存 + 1–2 CPU 核）。这部分余量可分配给 QueryNode / IndexNode 以提升查询和索引性能：

| 组件 | 2.x 内存 | 3.x 内存（建议） | 说明 |
|------|---------|-----------------|------|
| Kafka（每节点） | ~2–4 GB | **0**（移除） | — |
| QueryNode | 6 GB | **7–8 GB** | 可吸收 Kafka 释放的内存 |
| Woodpecker（内置） | 0（共享） | ~1–2 GB（共享） | 内置日志缓存，包含在 Milvus 进程内 |

实际分配应根据数据规模和查询负载压测调整。

### 7.6 迁移注意事项

从 2.x + Kafka 升级到 3.x + Woodpecker 需要注意：

1. **数据迁移**：2.x 中残留在 Kafka 中的未消费 WAL 数据必须在升级前由 DataNode 完全消费并生成 segment。升级前确认所有 MsgStream 消费位点已追平（lag = 0）。
2. **版本路径**：Milvus 3.x 可能要求先升级到特定的 2.x 小版本作为跳板，再升级到 3.x。具体升级路径参考官方升级指南。
3. **配置清理**：升级前备份并清理 `milvus.yaml` 中所有 `kafka.*` / `pulsar.*` 配置段，避免 3.x 启动时因无法识别配置而报错。
4. **WAL 回放**：3.x 首次启动时，Woodpecker 从对象存储中加载已有 segment 重建日志视图，首次启动时间可能长于常规重启。
5. **回滚限制**：Woodpecker 的日志格式与 Kafka 不兼容，升级到 3.x 后无法直接回滚到 2.x + Kafka。升级前务必做好 etcd 快照和对象存储备份。

### 7.7 验证要点

3.x 部署的验证与 §3.3 基本一致，额外确认：

```bash
# 确认 Woodpecker 日志目录已创建并写入
ls -la /data/milvus/rootcoord/data/woodpecker/

# 确认无 Kafka 连接报错（日志中不应出现 kafka client 相关错误）
docker logs milvus-proxy --tail 50 | grep -i -E 'woodpecker|kafka|mq'

# 写入验证：通过 Python SDK 插入数据后确认 Woodpecker 日志段增长
python3 -c "
from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType
connections.connect(host='193.195.129.57', port='19530')
print('Milvus 版本:', connections.get_connection_addr('default'))
# 后续插入/搜索验证逻辑同 2.x
"
```

### 7.8 版本基线（3.x）

| 组件 | 版本 | 镜像 |
|------|------|------|
| etcd | 3.5.5 | `quay.io/coreos/etcd:v3.5.5` |
| ~~Kafka~~ | ~~3.4.1~~ | **已移除，由 Woodpecker 替代** |
| Milvus | 3.x | `milvusdb/milvus:v3.x`（以实际版本为准） |
| Attu | 3.x 对应版本 | `zilliz/attu:latest` |



## 8. Prometheus 监控

Milvus 官方指标可视化仪表盘：
```shell
wget https://raw.githubusercontent.com/milvus-io/milvus/refs/heads/master/deployments/monitor/grafana/milvus-dashboard.json
```

因为Milvus目前主要是kubernetes部署的，所以需要适配一下

修改prometheus.yml

2.4.x版本

```yml
# Milvus rootcoord
- job_name: 'milvus-rootcoord'
  static_configs:
  - targets: ['193.195.129.57:9991','193.195.129.58:9991','193.195.129.59:9991']
    labels:
      namespace: "milvus-docker"
      app_kubernetes_io_name: "milvus"
      app_kubernetes_io_instance: "milvus-cluster"
      app_kubernetes_io_component: "rootcoord"

#Milvus datacoord
- job_name: 'milvus-datacoord'
  static_configs:
  - targets: ['193.195.129.57:9992','193.195.129.58:9992','193.195.129.59:9992']
    labels:
      namespace: "milvus-docker"
      app_kubernetes_io_name: "milvus"
      app_kubernetes_io_instance: "milvus-cluster"
      app_kubernetes_io_component: "datacoord"

# Milvus querycoord
- job_name: 'milvus-querycoord'
  static_configs:
  - targets: ['193.195.129.57:9993','193.195.129.58:9993','193.195.129.59:9993']
    labels:
      namespace: "milvus-docker"
      app_kubernetes_io_name: "milvus"
      app_kubernetes_io_instance: "milvus-cluster"
      app_kubernetes_io_component: "querycoord"

# Milvus indexcoord
- job_name: 'milvus-indexcoord'
  static_configs:
  - targets: ['193.195.129.57:9994','193.195.129.58:9994','193.195.129.59:9994']
    labels:
      namespace: "milvus-docker"
      app_kubernetes_io_name: "milvus"
      app_kubernetes_io_instance: "milvus-cluster"
      app_kubernetes_io_component: "indexcoord"

# Milvus proxy
- job_name: 'milvus-proxy'
  static_configs:
  - targets: ['193.195.129.57:9995','193.195.129.58:9995','193.195.129.59:9995']
    labels:
      namespace: "milvus-docker"
      app_kubernetes_io_name: "milvus"
      app_kubernetes_io_instance: "milvus-cluster"
      app_kubernetes_io_component: "proxy"

# Milvus datanode
- job_name: 'milvus-datanode'
  static_configs:
  - targets: ['193.195.129.57:9996','193.195.129.58:9996','193.195.129.59:9996']
    labels:
      namespace: "milvus-docker"
      app_kubernetes_io_name: "milvus"
      app_kubernetes_io_instance: "milvus-cluster"
      app_kubernetes_io_component: "datanode"


# Milvus querynode
- job_name: 'milvus-querynode'
  static_configs:
  - targets: ['193.195.129.57:9997','193.195.129.58:9997','193.195.129.59:9997']
    labels:
      namespace: "milvus-docker"
      app_kubernetes_io_name: "milvus"
      app_kubernetes_io_instance: "milvus-cluster"
      app_kubernetes_io_component: "querynode"


# Milvus indexnode
- job_name: 'milvus-indexnode'
  static_configs:
  - targets: ['193.195.129.57:9998','193.195.129.58:9998','193.195.129.59:9998']
    labels:
      namespace: "milvus-docker"
      app_kubernetes_io_name: "milvus"
      app_kubernetes_io_instance: "milvus-cluster"
      app_kubernetes_io_component: "indexnode"
```

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)