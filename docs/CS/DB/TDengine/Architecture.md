## Introduction

TDengine 的服务器侧代码**全部在单个进程 `taosd` 里**：集群中没有独立的存储进程、计算进程或共识进程，mnode、vnode、qnode、snode、bnode 都是这个进程内的逻辑角色。理解这本分册最重要的是先把"逻辑单元"和"物理进程"两层分开——官方架构图画的 M1/M2/M3、V2/V3/V4 都是逻辑实例，不是要分别部署的东西。

本页讲这些逻辑单元的职责边界、它们之间的 Raft 复制关系、客户端 `taosc` 的双重角色、FQDN 与 endpoint 的解析规则，以及三个发行形态的功能矩阵。版本锚点 **3.4.x**。

## Logical Units

### pnode 与 dnode

| 单元 | 定义 | 标识 |
| :-- | :-- | :-- |
| **pnode** | 一台拥有独立计算、存储、网络的计算机：物理机、虚拟机或 Docker 容器 | **FQDN**（集群通信完全依赖 FQDN） |
| **dnode** | `taosd` 在 pnode 上的一个运行实例 | **endpoint** = FQDN + 端口 |

一个 pnode 上配不同 `serverPort`（默认 **6030**）就能起多个 dnode。FQDN 可以配多个；官方不推荐把 `fqdn` 直接写成 IP（网络变化会导致集群失联），且 `fqdn` 参数值应控制在 96 字符以内。

### mnode：管理节点

- 元数据存储与管理中心：用户、权限、数据库、超级表、拓扑、vgroup 分配。
- **多 mnode 组成虚拟 mnode 组，Raft 一致性协议**，最多 3 个；任何数据更新只能在 leader 执行。
- 第 1 个 dnode 部署时自动成为 mnode，后续 mnode 由用户 SQL 增删：`CREATE MNODE ON DNODE <id>` / `DROP MNODE ON DNODE <id>`。
- 每个 dnode 上最多 1 个 mnode。

### vnode 与 vgroup：数据侧

- **vnode 是数据存储、查询和备份的基本单元**，官方原话是"每个 vnode 可视为一个独立的数据库"：一个 vnode 存一部分表的元数据 + 这些表的全部时序数据，有独立的运行线程、内存空间和持久化路径。
- 一个 vnode 只属于一个数据库，一个数据库可以有多个 vnode；库内 vnode 数量由建库时的 `VGROUPS` 决定。
- **vgroup 是跨 dnode 的 vnode 组**：组内 vnode 间走 **Raft**，写操作只在 leader，数据**异步复制**到 follower。vgroup 里的 vnode 数量 = 该数据库的副本数，建库时 `REPLICA` 指定（默认 1）。
- 副本数 N 要求集群至少 N 个 dnode；vgroup ID 由 mnode 分配，删除后不回收复用。

这里有个容易混淆的点：**mnode 组和 vgroup 都用 Raft，但复制的对象不同**——前者复制集群元数据，后者复制时序数据；而 mnode 组本身又是靠 dnode 心跳维护的，dnode 与 mnode 的 endpoint 发现顺序是：先看自己的 `dnode.json`，再看 `taos.cfg` 的 `firstEp`/`secondEp`，最后把自己当 mnode 单机运行。

### qnode / snode / bnode：3.x 新增的共享计算角色

这三个是 3.x 架构演化的重点，全部**集群级共享、不绑定数据库**，每个 dnode 上各最多 1 个，默认都不创建：

| 逻辑节点 | 创建 SQL | 作用 | 缺省行为 |
| :-- | :-- | :-- | :--- |
| **qnode** | `CREATE QNODE ON DNODE <id>` | 查询计算节点，超级表聚合场景承担全局聚合 | 没有 qnode，计算退回 vnode 执行 |
| **snode** | 流计算节点创建时由 mnode 调度 | 流计算任务执行 | 没有 snode，流计算退回 vnode 执行 |
| **bnode** | `CREATE BNODE ON DNODE <id> [PROTOCOL mqtt]` | 数据订阅节点，拉起子进程 `taosmqtt` 对外提供 MQTT 订阅 | 默认不创建；协议暂只支持 MQTT |

qnode 的引入被官方称为"**存储与计算的分离**"：查算可以集中在少数 qnode 上，vnode 专心存储。但注意这只是**计算侧分离**，与对象存储上卸载的"存算分离"（企业版 `SS_*` 共享存储参数）不是一回事。

同一 dnode 上三种角色可以共存：`supportVnodes` 不为 0 时该 dnode 既有 vnode 又可挂 qnode/mnode；要物理分离就把 `supportVnodes` 设 0，只留 mnode 或 qnode。

### vnode 里的逻辑节点关系

```
cluster
├── mnode group (≤3, Raft)              元数据共识
├── vgroup-1 (Raft, replica=N)          库 A 的分片
│   ├── vnode @ dnode-1 (leader)
│   └── vnode @ dnode-2 (follower)
├── vgroup-2 ...                        更多分片
├── qnode pool (共享)                   查询计算
├── snode pool (共享)                   流计算
└── bnode pool (共享)                   MQTT 订阅
```

## taosc：客户端驱动的双重角色

`taosc` 不只是"转发请求的驱动"：

1. **解析与计划**：SQL 进来先解析成 AST，Catalog 向 mnode/vnode 请求元数据做权限与合法性校验，生成逻辑计划再转物理计划——**查询调度发生在客户端**。
2. **元数据缓存**：taosc 缓存库、表、vgroup 元数据，缓存固定大小、先到先得，空间耗尽部分淘汰。所以建表后客户端可能有秒级延迟才可见。
3. **最后一级计算**：结果返回前，跨 vnode 的聚合、排序、过滤的最后一级在 taosc 完成。
4. **分发到正确 dnode**：客户端连集群中**任意一个** dnode 即可，由 taosc 负责把子任务按数据亲和性或负载调度到目标 vnode/qnode 所在 dnode。

taosc 以 C/C++ 原生接口提供，被 JDBC、Go、Python、Node.js、C#、Rust 连接器内嵌——对 JDBC 等接口，taosc 跑在**应用进程内**。此外 taosc 还可与 taosAdapter 交互走 RESTful，构成全分布式的 HTTP 通道。

## Server-Side Processes

| 进程 | 归属 | 职责 |
| :-- | :-- | :--- |
| `taosd` | 核心 | 上述全部逻辑角色的宿主，系统服务名 `taosd`（`systemctl start taosd`） |
| `taosAdapter` | 独立进程 | HTTP/REST、WebSocket、InfluxDB Line Protocol、Prometheus、OpenTSDB 协议适配；详见 [Ecosystem](/docs/CS/DB/TDengine/Ecosystem.md) |
| `taosKeeper` | 独立进程（Go） | taosd 监控数据导出，配 `-DBUILD_KEEPER=true` 编译 |
| `taosmqtt` | bnode 拉起的子进程 | MQTT 订阅服务 |
| Anode | 独立组件 | TDgpt 的时序分析算法宿主，详见 [TDgpt](/docs/CS/DB/TDengine/TDgpt.md) |

编译侧的事实（README-CN）：CMake ≥ 3.13.0；`BUILD_TOOLS=true` 编 taosTools（taosBenchmark/taosdump），`BUILD_KEEPER=true` 编 taosKeeper，`BUILD_JEMALLOC=ON` 换 jemalloc 分配器；taosAdapter/taosKeeper 需要 Go ≥ 1.23。CPU 支持 x64、ARM64，**不支持交叉编译**。

## Edition Matrix

按 3.4 Release Notes 与数据库 SQL 文档整理，社区版/企业版差异：

| 能力 | OSS | Enterprise |
| :-- | :-- | :-- |
| 集群（mnode/vgroup/qnode/snode/bnode） | ✅ | ✅ |
| 数据副本 replica 3 | ✅ | ✅ |
| replica 2 | ❌ | ✅ |
| Windows server | ❌ | ✅ |
| 安全（SASL、存储透明加密、MFA、RBAC、AES/SHA 函数、审计） | ❌ | ✅ |
| 多级存储（多个 KEEP） | ❌ | ✅ |
| 共享存储卸载（`SS_KEEPLOCAL`/`SS_CHUNKPAGES`/`SS_COMPACT`） | ❌ | ✅ |
| `DNODES` 指定 vnode 分布、`COMPACT_*` 高级 compaction 控制、vgroup leader 再平衡 | ❌ | ✅ |
| taosX HA（多 xnode） | ❌ | ✅ |
| Explorer SSO（OAuth 2.0 / OIDC 1.0）、TDgpt 模型评估工具 | ❌ | ✅ |

另有一条部署侧断点：**3.4 起 OSS 客户端不能连 Enterprise 服务端**（Enterprise 客户端可以连 Enterprise 服务端），混用集群时客户端版本必须和服务端形态对齐。

## Links

- [TDengine](/docs/CS/DB/TDengine/TDengine.md)
- [Storage_Engine](/docs/CS/DB/TDengine/Storage_Engine.md)
- [SQL](/docs/CS/DB/TDengine/SQL.md)
- [WAL](/docs/CS/DB/Concept/WAL.md)

## References

1. [技术内幕：整体架构](https://docs.taosdata.com/internals/arch/)
2. [节点管理 SQL](https://docs.taosdata.com/reference/taos-sql/node/)
3. [TDengine TSDB 3.4 Release Notes](https://tdengine.com/?p=30263/)
4. [taosdata/TDengine README-CN](https://github.com/taosdata/TDengine/blob/main/README-CN.md)
