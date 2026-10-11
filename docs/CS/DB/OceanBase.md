## Introduction

OceanBase 是蚂蚁集团自研的分布式关系型数据库：Shared-Nothing 集群 + [Paxos](https://lamport.azurewebsites.net/pubs/lamport-paxos.pdf) 复制，跑在通用服务器上而不依赖特殊硬件，同时兼容 MySQL 协议与生态，因此「单机 MySQL 顶不住」是最常见的入口场景。

官方给出的能力边界（README 口径）：单集群 1500+ 节点、PB 级数据、单表超万亿行；RPO = 0、RTO < 8 秒；存储成本相比传统方案省 70%–90%（来自编码压缩 + 增量/基线分层的存储结构）；同一集群内支持 HTAP；TPC-C 7.07 亿 tmpC、TPC-H 1526 万 QphH@30000GB。License 为 Apache 2.0。

> [!IMPORTANT]
>
> 基线 **OceanBase 社区版 4.4.2（v4.4.2_CE_BP3，2026-09）**。4.x 相比 3.x 是架构级重写（引入日志流、租户内 GTS、存算分层重做），网上大量「OB 3.x 合并/转储」「RootServer 集群」的旧文章不能直接套用。社区版**仅提供 MySQL 模式**，Oracle 兼容模式在企业版。

## Architecture

### Cluster and Nodes

集群由多个**对等**节点（OBServer）组成，每个节点都是一个 `observer` 单进程，内部同时跑 SQL 引擎、事务引擎与存储引擎，节点之间通过 TCP/IP 通信。一组「具有相似硬件可用性」的节点构成可用区（Zone），Zone 带 IDC 与 Region 属性——容灾布局（同城三 Zone、两地三中心）就是围绕 Zone 表达的。

表可以水平拆分为分区，每个物理分区对应一个 **Tablet**（有序存储数据记录的载体）。DML 与强一致读都落到 Tablet 上，因此分区键的选择直接决定了一次查询要不要跨节点。

### Log Stream and Replication

4.x 用**日志流（Log Stream, LS）**统一日志与复制：每个 Tablet 归属一个确定的日志流，一个租户的日志流总数由 `primary_zone` 与 locality 配置决定。

- 日志流有多副本，分布在不同可用区，副本间用自研 Paxos 维持共识，其中一个副本为主副本（Leader），只有主副本接受写入；
- 主副本要等**多数派副本持久化成功**，才确认这条 Redo 日志写入成功——RPO = 0 就是这条规则；
- 主副本故障后重新选举新主继续服务（RTO < 8 秒）；
- 均衡层通过日志流的分裂与合并完成负载均衡。

对比：MySQL 的复制是「一个实例一条 binlog 流」，OceanBase 的复制单位是日志流，粒度介于实例与分区之间，这是它能把「多副本一致性」和「分区水平扩展」缝在一起的直接原因。

### Multi-Tenancy

租户是集群内相互隔离的逻辑实例，CPU、内存、IO 全部隔离——对使用者而言，一个租户就是一个独立的「数据库」。集群自带系统租户 `sys`，业务应另建租户，不要直接跑在 sys 上。

资源按 **Unit（资源单元）→ 资源池（Resource Pool）→ 租户** 三层分配：Unit 是 observer 进程内按租户切出的虚拟容器（含 CPU、内存、日志盘配额），同一租户分布在各节点上的 Unit 组成资源池，租户绑定资源池。也正因为这层隔离，OceanBase 可以把大量小库塞进同一套物理集群，而不必像 MySQL 那样一库一套实例。

### Access Layer

OBProxy（又称 ODP）是无状态的接入层代理：把客户端 SQL 路由到正确的 OBServer，主副本切换、扩缩容对应用透明。生产环境应连 OBProxy 而不是直连节点。

| 端口 | 归属 | 用途 |
| :-- | :-- | :-- |
| 2881 | OBServer | MySQL 协议 SQL 端口（直连节点） |
| 2882 | OBServer | 节点间 RPC 通信 |
| 2883 | OBProxy | 应用统一入口 |
| 2884 | OBProxy | Prometheus 监控指标 |

用户名格式也是差异点，直连与经代理两种写法不能混用：

```shell
# 直连 OBServer：用户名@租户
mysql -h10.0.0.1 -P2881 -uroot@my_tenant -p
# 经 OBProxy：用户名@租户#集群名
mysql -h10.0.0.1 -P2883 -uroot@my_tenant#obcluster -p
```

## Storage Engine

写路径与 MySQL 的 InnoDB（原地更新 B+Tree + redo）根本不同，是 LSM 式的增量/基线分层：

1. DML 先写内存 **MemTable**；
2. MemTable 攒到一定大小就冻结并**转储**落盘，成为 L0 SSTable；
3. L0 SSTable 数量达到阈值，多个 L0 合并成 L1 SSTable；
4. 每天在配置的业务低峰期，把 MemTable、L0、L1 归并成一个 **Major SSTable**（基线，只读）——这就是「合并」，也是多副本基线保持一致的时间点，日常转储不会动基线。

分层换来两件事：基线只读 + 高压缩比，于是拿到 70%–90% 的存储成本优势；但和所有 LSM 一样，省了写放大就欠了读放大（一次读要叠多个 SSTable），所以监控要同时盯「转储/合并是否积压」与「内存水位」。

### Transaction and Consistency

事务层保证单分区与跨分区 DML 提交的原子性，跨分区走**优化过的两阶段提交**。时间戳统一由 **GTS**（Global Timestamp Service）提供：它是租户内产生连续递增时间戳的服务，自身用多副本保证可用。事务提交时向 GTS 取一个时间戳作为提交版本号，读数据时跳过版本号大于本次读取版本的数据——快照读与读写不阻塞由这一条支撑。

## Installation

### Docker

官方镜像 `oceanbase/oceanbase-ce` 定位是**快速起测试环境**：仅单实例集群、仅测试用途、不适用于 Kubernetes（K8s 上用 [ob-operator](https://github.com/oceanbase/ob-operator)）。主机建议至少 2 物理核 + 8 GB 内存。镜像同时发布在 dockerhub、quay.io 与 ghcr.io。

```shell
# mini 最省资源；normal 尽量吃满容器资源；slim 只启动 observer 并走快速启动（租户名 test，集群/租户资源变量不生效）
docker run -p 2881:2881 --name oceanbase-ce -e MODE=mini -d oceanbase/oceanbase-ce

# 起实例并同时建好密码与初始化 SQL（改 root 密码请用环境变量，不要在 init SQL 里改）
docker run -p 2881:2881 --name oceanbase-ce \
  -e OB_SYS_PASSWORD=yourpassword -e OB_TENANT_PASSWORD=yourpassword \
  -v "$PWD/init.d":/root/boot/init.d -d oceanbase/oceanbase-ce
```

启动最长约 5 分钟，看到 `boot success!` 才算就绪：

```shell
docker logs oceanbase-ce | tail -1
```

连接（用户名是 `用户@租户`，默认租户为 `test`，默认空密码）：

```shell
docker exec -it oceanbase-ce obclient -h127.0.0.1 -P2881 -uroot        # sys 租户
docker exec -it oceanbase-ce obclient -h127.0.0.1 -P2881 -uroot@test   # 默认 MySQL 租户
```

镜像内可用 `obd test sysbench obcluster` 直接跑基准测试。需要持久化时挂载 `/root/ob`（程序与数据）与 `/root/.obd/cluster`（配置）；排错时保留 `enable_rich_error_msg`（默认开启）并用 `trace` 拿详细信息。

### OBD 与集群部署

生产形态用 OBD（OceanBase Deployer，all-in-one 工具集，仅 Linux）：

```shell
bash -c "$(curl -s https://obbusiness-private.oss-cn-shanghai.aliyuncs.com/download-center/opensource/oceanbase-all-in-one/installer.sh)"
source ~/.oceanbase-all-in-one/bin/env.sh
obd demo            # 单机最小集群，快速体验
```

正经部署写 YAML 拓扑（`servers` + `global`：`devname`、`mysql_port: 2881`、`rpc_port: 2882`、`zone`、`cluster_id`、`memory_limit`、`system_memory` 等），再 `obd cluster autodeploy mycluster -c distributed.yaml`；集群状态用 `obd cluster list` / `obd cluster status mycluster` 查看。observer 必须以非 root 用户（惯例 `admin`）运行。

### Tenants and Users

建业务租户要显式走完 Unit → Pool → Tenant 三步：

```sql
CREATE RESOURCE UNIT unit_web MAX_CPU 4, MIN_CPU 2, MEMORY_SIZE '16G', LOG_DISK_SIZE '50G';
CREATE RESOURCE POOL pool_web UNIT = 'unit_web', UNIT_NUM = 2, ZONE_LIST = ('zone1','zone2');
CREATE TENANT web_tenant RESOURCE_POOL_LIST = ('pool_web') SET ob_tcp_invited_nodes='%';
```

`ob_tcp_invited_nodes` 是租户级 IP 白名单，漏配会表现为「能连上 sys，连不上业务租户」。

## Migration from MySQL

迁移走官方 OMS 社区版（OceanBase Migration Service）：结构迁移 → 全量迁移 → 增量同步（订阅源库 binlog）→ 数据校验，四段各自可观测，支持反向增量以便回退。小库也可用 mysqldump/`LOAD DATA` 一把梭。

兼容性是「协议 + 语法」层面的兼容，不等于逐条等价，落地前重点核对：

- **必须显式建主键**：无主键表在分布式下既难均衡又难增量同步；分区表还要保证主键包含分区键。
- **用户名带租户**：连接串从 `user@host` 变成 `user@tenant`（经 ODP 再加 `#cluster`），连接池与 ORM 的数据源配置要改。
- **分区设计前置**：MySQL 里没有的概念，搬过来时按查询维度重排分区键，否则热点与跨机 JOIN 全留给运行期。
- **事务隔离级别**：MySQL 默认 REPEATABLE-READ，OceanBase 租户默认 READ-COMMITTED，依赖 RR 语义（间隙锁式不可重复读规避）的业务要显式设置并回归测试。
- 自增列/序列、大小写敏感（`lower_case_table_names` 语义）、字符集与 `VARCHAR` 长度、DDL 与业务窗口（合并期）叠加的影响。

割接思路与所有分库分表中间件一致：全量 + 增量追平 → 双向校验通过 → 灰度切读 → 切写并保留反向同步 → 观察期后源库降级为只读。

## Links

- [DB](/docs/CS/DB/DB.md)
- [MySQL](/docs/CS/DB/MySQL/MySQL.md)
- [TiDB](/docs/CS/DB/TiDB.md)
- [PolarDB](/docs/CS/DB/PolarDB/PolarDB.md)
- [canal](/docs/CS/DB/canal.md)

## References

1. [OceanBase 系统架构（社区版文档）](https://www.oceanbase.com/docs/community-observer-cn-10000000000901181)
2. [OceanBase 整体架构（V4.0 社区版文档）](https://www.oceanbase.com/docs/community-observer-cn-10000000000900890)
3. [OceanBase 产品架构（通用文档）](https://www.oceanbase.com/docs/common-oceanbase-database-cn-10000000001687855)
4. [使用 Docker 部署 OceanBase（oceanbase/docker-images）](https://github.com/oceanbase/docker-images/blob/main/oceanbase-ce/README_CN.md)
5. [OMS 社区版概述](https://www.oceanbase.com/docs/community-oms-cn-1000000006682591)
6. [迁移 MySQL 数据库的数据至 OceanBase 社区版](https://www.oceanbase.com/docs/community-oms-cn-1000000006682553)
