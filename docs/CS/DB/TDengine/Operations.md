## Introduction

TDengine 的运维面有一个其他数据库少见的特征：**服务器侧只有一个进程 `taosd`**，没有 ZooKeeper 那样的外部依赖，"安装、集群几秒搞定"是官方原话。运维复杂度不在进程编排，而在**配置项的作用域**（建库参数 / dnode 级 / 客户端级）、**副本与 vgroup 的变更约束**，以及 3.4 的两条升级硬限制。

本页覆盖安装部署、配置作用域、集群扩缩、备份恢复、监控日志、压测与升级路径。版本锚点 **3.4.x**。

## Deployment

三条路，按官方 get-started：

| 方式 | 说明 |
| :-- | :--- |
| **安装包** | 最常用。RPM/DEB 包自动配置系统服务；源码 `make install` 同样注册服务 |
| **Docker** | 容器快速启动，适合试用与 CI |
| **Kubernetes** | 生产集群部署，官方提供部署文档 |

平台矩阵（3.4 Release Notes）：**OSS 服务端只支持 Linux 和 macOS**；**企业版服务端支持 Windows**；OSS 客户端支持 Linux/macOS/Windows。CPU 架构 x64、ARM64，不支持交叉编译。

安装后服务管理：

```bash
sudo systemctl start taosd          # Linux
sudo launchctl start com.tdengine.taosd   # macOS
taos                                # 命令行连接
```

不想以服务运行可以前台起：`./build/bin/taosd -c test/cfg`，另一个终端 `./build/bin/taos -c test/cfg`（`-c` 指定配置目录，客户端 CLI 程序名是 `taos`，服务端是 `taosd`）。

## Configuration Scopes

配置分三层，改错地方不生效是最常见的运维事故：

| 层 | 文件 | 典型参数 |
| :-- | :--- | :--- |
| **建库参数** | SQL `CREATE DATABASE` | `VGROUPS`、`REPLICA`、`BUFFER`、`PAGES`、`PAGESIZE`、`KEEP`、`DURATION`、`COMP`、`WAL_LEVEL`、`CACHEMODEL`、`CACHESIZE` |
| **dnode 级** | `taos.cfg` | `fqdn`、`serverPort`（默认 6030）、`firstEp`/`secondEp`、`supportVnodes`、`sLastCache*`、`compressMsgSize` |
| **客户端级** | taosc 的 `taos.cfg` | `queryPolicy`（只对单个 taosc 生效，集群内可混用） |

dnode 加入集群的 endpoint 发现顺序：先读自己的 `dnode.json`；没有再读 `taos.cfg` 的 `firstEp`/`secondEp`（可指向不带 mnode 的普通节点，连接时重定向）；都没有就把自己当 mnode 单机跑。`sLastCache*` 系列是**惰性生效**（`_LAZY`），改完必须重启 dnode 或重开 vnode；`CACHESIZE` 例外，`ALTER DATABASE ... CACHESIZE` 可在线调整。

## Cluster Operations

节点与角色的管理全部走 SQL：

```sql
SHOW DNODES;                                   -- 数据节点
CREATE MNODE ON DNODE 2;                       -- 扩 mnode（最多 3）
CREATE QNODE ON DNODE 3;                       -- 建查询节点（存算分离）
SHOW QNODES;
CREATE BNODE ON DNODE 4;                       -- 订阅节点（拉起 taosmqtt）
SHOW VGROUPS;                                  -- vgroup 分布
CLOSE VNODE <vgroup_id> ON DNODE <id>;         -- 优雅关闭某 vnode（刷写后停，不删数据）
SELECT SERVER_VERSION();                       -- 版本自检
```

扩容的本质是 vnode/vgroup 迁移：mnode 负责创建、分配和再平衡，vgroup ID 分配后不回收。**副本变更有硬约束**：单副本可变双副本；双副本不能转其他副本数；三副本不能转双副本——规划副本数要在建库时一次定对。

数据生命周期由 `KEEP`（默认 3650 天）与 `DURATION`（默认 10d）共同决定：`DURATION` 是数据文件存储的时间跨度，`KEEP` 必须 ≥ 3 × `DURATION`。社区版配多个 `KEEP` 不生效，只取最大值（多级存储是企业版）。

## Backup and Recovery

- **目录级备份**：3.4 升级前的标准动作就是拷贝整个 TDengine 目录（官方升级文档原文：back up your deployment by making a copy of the TDengine directory）。
- **taosdump**：逻辑导出/备份工具（随 `BUILD_TOOLS` 编译），适合跨版本、跨集群搬迁。
- **TMQ 数据库订阅**：订阅整库 → 在另一集群重放恢复，是官方给的数据迁移路径（见 [Stream_Compute](/docs/CS/DB/TDengine/Stream_Compute.md)）。

## Monitoring

三层观察手段：

1. **taosKeeper** 导出 taosd 运行指标，接 Prometheus。
2. **系统表**：`INFORMATION_SCHEMA.INS_*` 直接 SQL 查运行态——如 `INS_LAST_CACHE_STATS` 看每 vgroup 的 last cache block cache 用量、memtable、flush/compaction 积压、写限流速率。
3. **日志**：普通日志 + 慢查询日志（官方技术内幕有专页），慢日志是定位查询两阶段瓶颈的第一现场。

## Benchmarking

`taosBenchmark`（曾名 taosdemo，随 `BUILD_TOOLS` 编译）模拟多设备写入与查询压测。调优入口优先级：先 `BUFFER`/`VGROUPS`（写缓存与并行度），再 `CACHEMODEL`（最新值查询场景），`WAL_LEVEL` 只在可靠性优先时动。写入侧可以换 jemalloc（`-DBUILD_JEMALLOC=ON`）。

## Upgrade to 3.4

官方升级约束，逐条都是坑：

1. **只能从 3.0.1.5 或更高版本升级**。
2. **不支持滚动升级**：集群必须**关闭所有节点、全部升级完再启动**。
3. 升级前先做目录级备份。
4. **3.4 起 OSS 客户端不能连 Enterprise 服务端**——混合环境先规划客户端形态。
5. 在用 taosX 非数据源功能或 taosX-Agent 的**不要升 3.4**；只用数据源功能的，升级后要删除并重建所有数据摄入任务。
6. 企业版/Cloud 升级联系厂商。

## Links

- [TDengine](/docs/CS/DB/TDengine.md)
- [Architecture](/docs/CS/DB/TDengine/Architecture.md)
- [Storage_Engine](/docs/CS/DB/TDengine/Storage_Engine.md)
- [Ecosystem](/docs/CS/DB/TDengine/Ecosystem.md)
- [Stream_Compute](/docs/CS/DB/TDengine/Stream_Compute.md)

## References

1. [TDengine TSDB 3.4 Release Notes](https://tdengine.com/?p=30263/)
2. [节点管理 SQL](https://docs.taosdata.com/reference/taos-sql/node/)
3. [TDengine SQL：CREATE DATABASE](https://docs.taosdata.com/reference/taos-sql/database/)
4. [taosdata/TDengine README-CN](https://github.com/taosdata/TDengine/blob/main/README-CN.md)
