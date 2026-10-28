## Introduction

3.x 的部署极简：Core / Enterprise 都是**单二进制 `influxdb3`**，Clustered 是一组 K8s 容器。本页覆盖最小可运行部署、配置入口、从 1.x/2.x 迁移的路径，以及产品选型。

## Docker Quick Start

3.x 的 Docker 镜像：`influxdb:3-core`、`influxdb:3-enterprise`、`influxdb:3-clustered`。**2026-09-15 起 `latest` 标签指向 3 Core**——生产环境务必锁版本 tag，否则一次 `docker pull` 就把 2.x 悄悄换成 3.x。

```shell
# Core：本地文件系统当对象存储，数据落 data-dir
docker run -d --name influxdb3 \
  -p 8181:8181 \
  -v $PWD/data:/var/lib/influxdb3 \
  influxdb:3-core serve --node-id node0 --object-store file --data-dir /var/lib/influxdb3

# 写入与查询
influxdb3 query --host http://localhost:8181 "SELECT * FROM cpu LIMIT 5"
```

## Configuration Surface

配置入口有三层，优先级从高到低：

1. **CLI 参数**：`influxdb3 serve --node-id ... --object-store ... --data-dir ...`，`influxdb3 query/write/create trigger` 等子命令。
2. **环境变量**：`INFLUXDB3_*` 系列，与 CLI 参数一一对应（3.10 起有一批改名，如 `INFLUXDB3_DB_DIR` → `INFLUXDB3_DATA_DIR`、`INFLUXDB3_START_WITHOUT_AUTH` → `INFLUXDB3_WITHOUT_AUTH`，老名字会告警）。
3. **Catalog**：database / table / cache 定义等 schema 级状态，存对象存储里，跨重启恢复。

常用 serve 参数：

| 参数 | 作用 |
| :-- | :-- |
| `--node-id` | 节点标识，对象存储路径的前缀，重启后用同一 ID 才能恢复现场 |
| `--object-store` | `file` / `s3` / `gcs` / `azure`，对象存储类型 |
| `--cluster-id` | Enterprise 多节点必填，同 ID 的节点组成逻辑集群 |
| `--mode` | 子进程组合 `all,ingest,query,process,compact` |
| `--plugin-dir` | 启用 Processing Engine 及插件目录 |
| `--shutdown-timeout` | 优雅停机超时（3.11 新增） |

Enterprise 新引擎上线线程默认随 license 核心数伸缩；超限线程数会被截断并告警而非拒绝启动。

## Migration Paths

| 源版本 | 目标 | 路径 |
| :-- | :-- | :--- |
| 2.x OSS / Cloud TSM | 3 Enterprise | `influxdb3-upgrade` 工具，双写镜像后切换 |
| 1.x OSS | 3 Core | 双写 72 小时后切换（数据模型与 ILP 兼容，InfluxQL 保留） |
| 1.x / 2.x 存量 Flux | 任意 3.x | **必须重写**：无 Flux 兼容层，改写为 SQL / InfluxQL / Processing Engine |

迁移成本的大头从来不是数据而是查询语言：官方对 Flux 用户的指引是把 Flux 查询全部改写为 SQL 或 InfluxQL，把 Task 改写为 Processing Engine 的 schedule trigger。schema 上注意 3.x 不允许表创建后新增 tag 列（见 [Data_Model](/docs/CS/DB/InfluxDB/Data_Model.md)），迁移前先评审 tag 设计。

## Choosing a Product Line

| 场景 | 选择 |
| :-- | :-- |
| 边缘设备、开发测试、免费单节点 | Core |
| 生产、需要 HA / 读副本 / 长期历史查询 | Enterprise（Trial 或 Home license 先评估） |
| 大规模自托管、摄入查询独立伸缩、冷热分层 | Clustered |
| 多租户自助云、按量付费 | Cloud Serverless |
| 托管单租户云 | Cloud Dedicated |

Enterprise Trial / Home license 不需要销售沟通即可下载评估；Core 升 Enterprise 是同一二进制加 license，无数据迁移。1.x/2.x 存量部署的官方口径：需要 v3 特性（SQL、对象存储、无限基数、Processing Engine）时就规划迁移，否则继续维护期使用。

## Links

- [InfluxDB 枢纽](/docs/CS/DB/InfluxDB/InfluxDB.md)
- [Architecture](/docs/CS/DB/InfluxDB/Architecture.md)
- [Data_Model](/docs/CS/DB/InfluxDB/Data_Model.md)
- [Processing_Engine](/docs/CS/DB/InfluxDB/Processing_Engine.md)
- [Query](/docs/CS/DB/InfluxDB/Query.md)

## References

1. [InfluxDB 3 Install Documentation](https://docs.influxdata.com/influxdb3/core/install/)
2. [Which InfluxDB 3 should I use](https://docs.influxdata.com/influxdb3/which-influxdb-3/)
3. [InfluxDB 3 Enterprise Release Notes](https://docs.influxdata.com/influxdb3/enterprise/release-notes/)
4. [Upgrade to InfluxDB 3 Enterprise](https://docs.influxdata.com/influxdb3/core/admin/upgrade-to-enterprise/)
