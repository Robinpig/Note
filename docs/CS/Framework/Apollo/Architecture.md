# Apollo Architecture

## Introduction

Apollo 服务端的架构叙事是「**三个逻辑角色、两个数据库、一个注册发现**」。三个角色职责单向：Config Service 只服务客户端的读与推送，Admin Service 只服务 Portal 的写，Portal 是唯一的管理面入口。这套切分决定了网络边界——客户端永远不需要知道 Admin Service 的存在。本文按「角色 → 模块 → 发现机制 → 可用性」的顺序展开，模块源码地图以服务端仓库 `apolloconfig/apollo`（基线 v3.0.0）为准。

## Logical Roles

| 逻辑角色 | 制品 | 默认端口 | 服务对象 | 职责 |
| :-- | :-- | :-- | :-- | :-- |
| Config Service | `apollo-configservice` | 8080 | Apollo 客户端 | 配置读取、变更推送，**兼任 Meta Server** |
| Admin Service | `apollo-adminservice` | 8090 | Apollo Portal | 配置修改、发布、灰度等写操作 |
| Portal | `apollo-portal` | 8070 | 人 / Open API 调用方 | 管理界面、权限、审计、Open API |
| 注册发现 | 内嵌 Eureka / 库表 / 第三方 | — | Config + Admin Service | 实例注册与心跳 |
| 存储 | ApolloPortalDB + ApolloConfigDB | 3306 | 三个服务 | 唯一外部依赖是 MySQL |

官方整体设计文档的原文表述：Config Service 与 Admin Service 都是**多实例、无状态**部署，因此需要向注册中心注册并保持心跳；为简化部署，**Config Service、Eureka、Meta Server 三个逻辑角色实际跑在同一个 JVM 进程里**。

「无状态」是这套架构成立的前提：三个服务都不在本地磁盘存业务状态，全部状态在 MySQL，所以扩容 = 加进程 + 改注册信息，不需要数据搬迁。

## Module Map

服务端仓库（v3.0.0）的 Maven 模块，按依赖方向分三层：

- **接入层**：`apollo-configservice`（读路径 + 长轮询）、`apollo-adminservice`（写路径）、`apollo-portal`（管理面 + Open API）、`apollo-assembly`（打包分发）。
- **领域层**：`apollo-biz`——Config Service 与 Admin Service **共享的核心领域逻辑**（配置项、发布、灰度规则、命名空间等实体与服务）；`apollo-common`（跨服务复用的基础组件）；`apollo-audit`（审计日志链路）。
- **构建层**：`apollo-buildtools`、`apollo-build-sql-converter`（把 schema 源文件转换成各数据库 profile 的 SQL）。

> [!NOTE]
>
> **Java 客户端已不在本仓库**。`com.ctrip.framework.apollo:apollo-client` 等制品的源码在独立仓库 [`apolloconfig/apollo-java`](https://github.com/apolloconfig/apollo-java)，模块含 `apollo-client`、`apollo-client-config-data`（Spring Boot Config Data 集成）、`apollo-core`、`apollo-openapi`、`apollo-mockserver`、`apollo-plugin`。客户端 tag 至 v2.5.0，与主仓版本线解耦——**看到主仓库里找不到 `apollo-client` 目录不要惊讶，这是 3.0.0 前后的仓库拆分，不是文档写错**。

## Discovery: Meta Server and Registry

Apollo 的服务发现刻意做了两层封装：底层是注册中心（早期只有内嵌 Eureka），上层是 **Meta Server**，对外只暴露「给我某个服务的实例列表」这一种语义。

访问模式因此是**两跳**：

1. 客户端 / Portal 通过域名访问 Meta Server，拿到 Config Service（或 Admin Service）的实例列表（IP + Port）；
2. **直接**经 IP + Port 访问目标实例，负载均衡与错误重试放在**客户端侧 / Portal 侧**自己做。

这也解释了为什么 Meta Server 可以与 Config Service 同 JVM——它只是把 Eureka 的发现接口翻译了一层。

注册中心的实现路线（按版本）：

| 路线 | 引入版本 | 状态 |
| :-- | :-- | :-- |
| 内嵌 Eureka | 1.x 起 | 2.x 的默认；3.0.0 起仍可用，回退方式见下 |
| `database-discovery`（库表注册） | 2.1.0 支持 | **3.0.0 起默认启用**，官方发布包与 Docker 镜像已默认打开 |
| `nacos-discovery` | 1.8.0+ | 可选替代 |
| `consul-discovery` | 1.9.0+ | 可选替代 |
| `zookeeper-discovery` | 2.0.0+ | 可选替代（ZooKeeper 3.5.x+） |
| `custom-defined-discovery` | 2.0.0+ | 自定义（`apollo.config-service.url` / `apollo.admin-service.url`） |

`database-discovery` 用 ApolloConfigDB 的 `ServiceRegistry` 表（`ServiceName` / `Uri` / `Cluster` / `Metadata`）做注册，不依赖第三方注册中心。升级自 2.x Eureka 部署想保留旧行为：运行时设 `SPRING_PROFILES_ACTIVE=github`，或源码构建时改回 `-Dapollo_profile=github`。

多集群场景下可用 `apollo.service.registry.cluster` 限制客户端只读同集群的 Config Service；`apollo.service.registry.uri` 自定义对外暴露的 URI。

> [!WARNING]
>
> 官方明确要求：**不要把 `apollo-configservice` 和 `apollo-adminservice` 直接暴露到公网**——两者按内网可信网络设计；同时**不要开通从 Client 到 Admin Service 的网络**，客户端只需要 Meta Server 与 Config Service（默认 8080）。

## Availability Matrix

由于三个角色无状态 + 客户端有本地缓存，故障面比看起来小得多（官方矩阵）：

| 故障 | 对客户端的影响 | 说明 |
| :-- | :-- | :-- |
| 一台 Config Service 宕 | 无影响 | 客户端重连其它 Config Service |
| 全部 Config Service 宕 | 读不到最新配置，Portal 失效 | 客户端重启时读本地缓存文件 |
| 一台 Admin Service 宕 | 无影响 | Portal 重连其它 Admin Service |
| 全部 Admin Service 宕 | 客户端不受影响 | Portal 无法改配置 |
| 一台 Portal 宕 | 无影响 | Portal 域名经 SLB 绑多机 |
| 一个数据中心宕 | 无影响 | 多 DC 部署数据全量同步，Meta Server / Portal 域名经 SLB 自动切到存活 DC |

真正的单点不在进程层，而在 **MySQL**：配置的强正确性（发布原子性、回滚）最终由数据库保证，DB 的 HA 方案（主从 / MGR / 云 RDS）是整个体系的底座。

## Multi-Data Center Topology

生产拓扑的固定形状：

- **ApolloPortalDB 只部署一套**——Portal 是全局唯一的，通过 `apollo.portal.envs` 登记多个环境。
- **每个环境（dev / fat / uat / pro）独立部署一套** config-service + admin-service + ApolloConfigDB——环境之间数据物理隔离，Portal 切换环境即切换后端。
- 各环境的 Meta Server 地址通过 `apollo.portal.meta.servers`（1.6.0+，JSON，优先级高于其它配置方式）或 `apollo-env.properties` 的 `${env}.meta` 下发。

这套「一个 Portal 管多套 Config/Admin」的形状，是 Apollo 与「每环境一套完整系统」方案（如自建多套 Nacos）在运维模型上的根本差异。

## Startup

解压分发包后 `scripts/startup.sh` 启动、`scripts/shutdown.sh` 停止；JVM 参数在各自 `scripts/startup.sh` 的 `JAVA_OPTS` 中调整，官方默认值（仅作起点，勿照抄）：

- configservice：`-Xms6144m -Xmx6144m`
- adminservice：`-Xms2560m -Xmx2560m`
- portal：`-Xms4096m -Xmx4096m`

自 2.5.0 起 configservice 与 adminservice 支持**优雅停机**（`server.shutdown=graceful`，默认等待在途请求 10 秒，可用环境变量 `GRACEFUL_SHUTDOWN_TIMEOUT` 调大）。

## Links

- [Apollo](/docs/CS/Framework/Apollo/Apollo.md)
- [Namespace](/docs/CS/Framework/Apollo/Namespace.md)
- [Storage](/docs/CS/Framework/Apollo/Storage.md)
- [Deployment and Ops](/docs/CS/Framework/Apollo/Deployment_and_Ops.md)
- [etcd 横向对照](/docs/CS/Framework/etcd/compare.md)

## References

- <https://www.apolloconfig.com/#/en/design/apollo-introduction>
- <https://www.apolloconfig.com/#/en/deployment/distributed-deployment-guide>
- <https://github.com/apolloconfig/apollo>
