# Apollo Storage

## Introduction

Apollo 服务端只有一个外部依赖——MySQL，分两个库：**ApolloPortalDB**（Portal 的权限、应用元数据、token，生产只一套）与 **ApolloConfigDB**（配置本体，每环境一套）。两个库的表都遵循同一套列范式：`IsDeleted`(bit) + `DeletedAt`(毫秒时间戳) 做软删除，`DataChange_CreatedBy` / `DataChange_CreatedTime` / `DataChange_LastModifiedBy` / `DataChange_LastTime` 做变更审计。本文基线为 v3.0.0 schema（`scripts/sql/src/`，注意 **3.0.0 的列名是驼峰式**，与 2.x 的 snake_case 不同）。

## ApolloConfigDB: Read Path

客户端一次完整读取经过的表：

1. `Namespace` / `Cluster`：按 `AppId + ClusterName + NamespaceName` 定位配置坐标；
2. `Release`：该坐标下最新发布行——**全量配置快照**，`Configurations` 为 longtext，`ReleaseKey` 为本次发布的唯一标识（客户端用它判断配置是否变化）；
3. `ReleaseMessage`：发布时写入的通知行，`Message` varchar(1024) 形如包含 appId / cluster / namespace 的 JSON，客户端长轮询靠它感知变更（机制见 [Config Push](/docs/CS/Framework/Apollo/Config_Push.md)）；
4. `Instance` / `InstanceConfig`：记录哪个实例（`Ip`、`DataCenter`）在什么时间（`ReleaseDeliveryTime`）拿到了哪个 `ReleaseKey`——这就是 Portal「灰度实例列表 / 实例列表」的数据来源。

## ApolloConfigDB: Write Path

一次「编辑 → 提交 → 发布」经过的表：

1. `Item`：配置项本体（`Key` / `Type` / `Value` longtext / `LineNum`），用户编辑的落点；
2. `Commit`：一次提交的变更集（`ChangeSets` longtext），回答「这次改了什么」；
3. `Release`：发布时把当前所有配置打包成快照（`Configurations` + `ReleaseKey`，`IsAbandoned` 标记废弃）；
4. `ReleaseHistory`：发布动作台账，`Operation` 枚举 0 普通 / 1 回滚 / 2 灰度发布 / 3 灰度规则更新 / 4 灰度合并回主分支 / 5 主分支发布灰度自动发布 / 6 主分支回滚灰度自动发布 / 7 放弃灰度；
5. `ReleaseMessage`：通知行，唤醒长轮询。

配套表：`NamespaceLock`（编辑锁，防并发修改）、`GrayReleaseRule`（`Rules` varchar(16000) 灰度规则 + `BranchName` + `BranchStatus` 0 删除 / 1 使用中 / 2 已全量，绑定一个 `ReleaseId`）、`AccessKey`（按 AppId 的 `Secret`，`Mode` 区分 filter / observer，`IsEnabled` 控制）、`ServerConfig`（ConfigDB 自身配置，如 `eureka.service.url` 默认 `http://127.0.0.1:8080/eureka/`、`namespace.value.length.limit.override`）。

## ApolloConfigDB: Registry and Audit

- `ServiceRegistry`（`ServiceName` / `Uri` / `Cluster` / `Metadata`）：**database-discovery 的注册表**——3.0.0 起 Config / Admin Service 默认用它替代内嵌 Eureka（见 [Architecture](/docs/CS/Framework/Apollo/Architecture.md)）。
- `AuditLog`（`TraceId` / `SpanId` / `Operator` / `OpType`）与 `AuditLogDataInfluence`（字段级旧值 / 新值）：3.0.0 的链路化审计；旧 `Audit` 表保留作历史兼容。

## ApolloPortalDB

Portal 库约 20 张表，按功能分四组：

| 组 | 表 | 说明 |
| :-- | :-- | :-- |
| 身份 | `App`、`AppNamespace`（`Format`、`IsPublic`） | 应用与 namespace 定义 |
| 权限 | `Users`、`Authorities`、`Role`、`Permission`（`PermissionType` + `TargetId`）、`UserRole`、`RolePermission`、`ConsumerRole` | RBAC 全链，见 [Portal](/docs/CS/Framework/Apollo/Portal.md) |
| Open API / Token | `Consumer`、`ConsumerToken`（`Token` / `RateLimit` / `Expires`）、`ConsumerAudit`、`UserToken`（`TokenPrefix` / `TokenHash` / `Scopes` / `RevokedAt`）、`UserTokenAudit` | 3.0.0 的 UserToken 面向 AI agent 与自动化 |
| 功能与审计 | `ServerConfig`（预置 `apollo.portal.envs`、`organizations`、`superAdmin`、`consumer.token.salt` 等）、`Favorite`、`SPRING_SESSION` / `SPRING_SESSION_ATTRIBUTES`、`AuditLog` / `AuditLogDataInfluence` | 会话表说明 Portal 的登录态在库里 |

## Schema Evolution

- schema 源文件在 `scripts/sql/src/`（`apolloconfigdb.sql` / `apolloportaldb.sql`），构建时由 `apollo-build-sql-converter` 生成各数据库 profile 的 SQL（`h2-default` / `mysql-default` / `mysql-database-not-specified`）；
- 版本间 delta 脚本按 `v220-v230` / `v230-v240` / `v250-v300` 分目录存放——**升级 3.0.0 需要应用 v250→v300 的 delta**；
- 2.4.0 → 2.5.0 **无 schema 变更**，直接部署即可。

> [!WARNING]
>
> 快速开始（单机 H2）与生产（MySQL）用的是同一套 schema 的不同 profile。H2 模式建的表在升级到 MySQL 时**不能直接搬数据**——官方分布式部署指南给出了数据迁移需处理的表范围（`App`、`AppNamespace`、`Cluster` 仅 `Name='default'`、`Namespace` 仅 `ClusterName='default'`），照章执行，不要手工拼 INSERT。

## Links

- [Apollo](/docs/CS/Framework/Apollo/Apollo.md)
- [Architecture](/docs/CS/Framework/Apollo/Architecture.md)
- [Config Push](/docs/CS/Framework/Apollo/Config_Push.md)
- [Portal](/docs/CS/Framework/Apollo/Portal.md)
- [Deployment and Ops](/docs/CS/Framework/Apollo/Deployment_and_Ops.md)

## References

- <https://github.com/apolloconfig/apollo/tree/master/scripts/sql/src>
- <https://www.apolloconfig.com/#/en/deployment/distributed-deployment-guide>
