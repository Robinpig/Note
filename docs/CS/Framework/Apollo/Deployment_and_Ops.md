# Apollo Deployment and Ops

## Introduction

Apollo 的部署模型可以一句话概括：**一个 Portal 管多套 Config/Admin，一套 MySQL 装全部状态**。官方对简易性的原话：「目前唯一的外部依赖是 MySQL，所以部署非常简单，只要装了 Java 和 MySQL，Apollo 就能跑起来」。本文覆盖快速开始与分布式部署两条路、端口与网络边界、环境变量清单与升级要点，基线为 v3.0.0（2026-10-03）。

## Two Deployment Paths

| | 快速开始 | 分布式部署 |
| :-- | :-- | :-- |
| 数据库 | 内嵌 H2（`h2-default` profile，自动建表） | MySQL **5.6.5+**（表结构 timestamp 用了多个默认值声明，低版本不支持） |
| 启动 | 解压后 `scripts/startup.sh`，停 `scripts/shutdown.sh` | 同样脚本，但先导入 `apolloportaldb.sql` 与每环境一份 `apolloconfigdb.sql`，配 `application-github.properties` |
| 适用 | 本地试用 / 演示 | 生产 |

生产拓扑固定形状：**ApolloPortalDB 只一套，每个环境（dev / fat / uat / pro）独立一套 config-service + admin-service + ApolloConfigDB**。环境清单在 Portal 的 `apollo.portal.envs` 登记（默认 `dev`，多环境逗号分隔，**修改后需重启 Portal**）。

JDK 要求：**服务端 17+**（3.0.0 从 Java 8 提到 17；2.x 用 8）；**客户端 1.8+**（Java 1.7 运行时用 1.x 客户端，如 1.9.1）。

## Ports and Network Boundaries

| 服务 | 默认端口 | 暴露面 |
| :-- | :-- | :-- |
| apollo-configservice | 8080 | 客户端可达；**兼任 Meta Server** |
| apollo-adminservice | 8090 | 仅 Portal 可达 |
| apollo-portal | 8070 | 人 / Open API 调用方 |

三条网络边界（官方明确要求）：

1. **不要把 configservice 与 adminservice 暴露到公网**——两者按内网可信网络设计；
2. **不要开通 Client → Admin Service 的网络**——客户端只需要 Meta Server 与 Config Service；
3. Portal 域名经 SLB 绑多台机器，Portal 无单点。

## Environment Variables

分布式部署的核心配置（数据库连接，`application-github.properties` 或 Docker `-e`）：

```properties
spring.datasource.url = jdbc:mysql://localhost:3306/ApolloConfigDB?useSSL=false&characterEncoding=utf8
spring.datasource.username = someuser
spring.datasource.password = somepwd
```

Docker 形式：`SPRING_DATASOURCE_URL` / `SPRING_DATASOURCE_USERNAME` / `SPRING_DATASOURCE_PASSWORD`。

Eureka 实例注册（多网卡 / Docker 环境常需指定，否则注册到容器内部 IP 客户端不可达）：

```properties
-Dspring.cloud.inetutils.ignoredInterfaces[0]=docker0
-Dspring.cloud.inetutils.ignoredInterfaces[1]=veth.*
-Deureka.instance.ip-address=1.2.3.4
-Deureka.instance.homePageUrl=http://1.2.3.4:8080     # configservice；adminservice 用 8090
-Deureka.instance.preferIpAddress=false
```

Meta Server 地址（`apollo-env.properties`，或运行时覆盖）：

```properties
dev.meta=http://1.1.1.1:8080
fat.meta=http://apollo.fat.xxx.com
uat.meta=http://apollo.uat.xxx.com
pro.meta=http://apollo.xxx.com
```

运行时优先级更高的两种覆盖：Java System Property `${env}_meta`（如 `-Ddev_meta=...`）与 OS 环境变量 `${ENV}_META`（如 `DEV_META=...`，全大写、`_` 分隔）。打包期在 `scripts/build.sh` 里配 `dev_meta` / `fat_meta` / `uat_meta` / `pro_meta` 及 `META_SERVERS_OPTS`。

Docker Portal 专用：`APOLLO_PORTAL_ENVS=dev,pro` + `DEV_META` / `PRO_META`。

> [!NOTE]
>
> 用内嵌 Eureka 时，若 `eureka.service.url` 只配了当前启动机器，启动日志可能出现 `Connection refused`——**这是预期行为**，Eureka 客户端会自动重试，不影响最终注册。

## Key ServerConfig Items

ApolloPortalDB.ServerConfig（Portal 侧，均支持 `-D` / `application.properties` 覆盖，**且覆盖优先级高于库内配置**）：

| 配置项 | 语义 |
| :-- | :-- |
| `apollo.portal.envs` | 支持的环境列表，默认 `dev`，改后重启 |
| `apollo.portal.meta.servers` | 1.6.0+，各环境 Meta Service 地址（JSON），优先级高于其它方式 |
| `superAdmin` | Portal 超级管理员，多账号英文逗号分隔 |
| `organizations` | 部门列表（创建 App 时选择） |
| `consumer.token.salt` | Open API token 盐值，建议 `openssl rand -hex 32`，约一分钟生效 |
| `wiki.address` | 门户「帮助」链接地址 |

ApolloConfigDB.ServerConfig（Config 侧）：`eureka.service.url`（默认 `http://127.0.0.1:8080/eureka/`，改端口需同步）、`namespace.value.length.limit.override`。

database-discovery 可选：`apollo.service.registry.cluster`（多集群限制客户端读同集群 Config Service）、`apollo.service.registry.uri`（自定义对外暴露 URI）。

## Graceful Shutdown

自 2.5.0 起，configservice 与 adminservice 支持优雅停机：`server.shutdown=graceful`，等待在途请求完成，**默认超时 10 秒**，可用环境变量 `GRACEFUL_SHUTDOWN_TIMEOUT` 调大（`30s` / `60s` / `2m`）。对滚动发布的意义：发布中的长轮询请求不会被一刀切断。

## Upgrading to 3.0.0

从 2.5.x 升级的三个必须动作：

1. **运行时先升级 JDK 17**——服务端基线从 Java 8 移到 Java 17，configservice / adminservice / portal 三个服务都要先换运行时再部署 3.0.0；
2. **确认注册发现行为**——3.0.0 起 `database-discovery` 默认启用，官方包与镜像已默认打开；想保留旧 Eureka 行为需显式回退（`SPRING_PROFILES_ACTIVE=github`）；
3. **应用 schema delta**——`v250-v300` 的增量脚本（见 [Storage](/docs/CS/Framework/Apollo/Storage.md)）。

相对地，2.4.0 → 2.5.0 **无 schema 变更**，直接部署即可。

## HA Recap

体系里没有单点进程，但有一个单点依赖——MySQL。Config / Admin / Portal 全部无状态，扩容只是加进程；DB 的 HA（主从 / MGR / 云 RDS）决定发布的原子性与回滚的正确性。最后一层保险是客户端本地缓存：Config Service 全挂时，**已启动的应用不受影响，重启的应用从本地缓存文件恢复配置**（灾急扩容甚至可以把缓存文件先拷到新机）。

## Links

- [Apollo](/docs/CS/Framework/Apollo/Apollo.md)
- [Architecture](/docs/CS/Framework/Apollo/Architecture.md)
- [Storage](/docs/CS/Framework/Apollo/Storage.md)
- [Client](/docs/CS/Framework/Apollo/Client.md)
- [Kubernetes 调度](/docs/CS/Container/k8s/K8s.md)

## References

- <https://www.apolloconfig.com/#/en/deployment/distributed-deployment-guide>
- <https://www.apolloconfig.com/#/zh/deployment/quick-start>
- <https://github.com/apolloconfig/apollo/releases>
