# Nacos Storage and Persistence

## Introduction

Nacos 的存储最容易踩的坑是：**它不是一个「全量落盘」的中间件**。哪些数据进数据库、哪些只在内存，取决于一致性模型：

- **命名（服务发现）的临时实例走 AP（Distro）**：实例注册 / 心跳全在内存，节点间异步同步。**不写数据库**——节点重启后内存里的临时实例会丢，靠客户端重连 / 心跳重新注册补回。这也是为什么 Nacos 集群里「重启一台，实例会被短暂摘除」是预期行为。
- **配置（config）走 CP（JRaft）**：配置内容、灰度、标签、历史、租户、权限**全部落外部数据库**，并借 Raft 保证多节点一致。

所以「Nacos 用什么存储」要分两层答：共识元数据靠 **JRaft 日志 + 快照**（见 [JRaft](/docs/CS/Framework/nacos/jraft.md)），业务持久化靠 **Derby（单机）/ MySQL（集群）**。

## Derby: Single-Node Embedded, Not Clustered

- Nacos 默认内置 **Apache Derby**，standalone 模式开箱即用，无需外部依赖。
- **3.x 起 schema 文件不再放在 `conf/` 目录**：`distribution/conf/` 只剩 `application.properties`、`cluster.conf.example`、`nacos-logback.xml` 等，建表脚本随**数据源插件**分发，路径为 `nacos-datasource-plugin-derby/src/main/resources/META-INF/derby-schema.sql`（实测 3.2.4）。
- Derby 是**单文件嵌入式数据库**，**不支持多节点并发写入**：集群模式下若多个 Nacos 共用同一份 Derby 数据会直接报错 / 锁冲突。
- 官方明确：Derby 仅供本地开发、demo、单节点，**生产集群必须用 MySQL**。
- 踩坑：Docker 环境偶尔出现 `load derby-schema.sql error`——根因多是 Derby 初始化失败或挂载冲突，标准解法就是切 MySQL。

```properties
# standalone 默认即可，无需配置；集群务必切换：
spring.sql.init.platform=mysql
```

## MySQL: Cluster Production Storage

集群部署在 `application.properties` 里切到 MySQL，并导入官方建表脚本：

```properties
spring.sql.init.platform=mysql
db.num=1
db.url.0=jdbc:mysql://127.0.0.1:3306/nacos?characterEncoding=utf8&connectTimeout=1000&socketTimeout=3000&autoReconnect=true&useUnicode=true&useSSL=false&serverTimezone=UTC
db.user.0=nacos
db.password.0=nacos
# 多库可继续 db.url.1 / db.user.1 ...
```

> [!WARNING]
> **平台属性在 3.x 已改名**：`spring.datasource.platform` 被降级为「旧属性」——`PersistenceConstant` 里常量名就是
> `DATASOURCE_PLATFORM_PROPERTY_OLD`，新属性是 **`spring.sql.init.platform`**（`DATASOURCE_PLATFORM_PROPERTY`）。
> 老写法目前仍被兼容读取，但新部署应改用 `spring.sql.init.platform`。
> 另外 **建表脚本不在 `conf/` 下**：3.2.4 的 `distribution/conf/` 已无 `mysql-schema.sql`，
> 脚本随数据源插件分发（`nacos-datasource-plugin-mysql/.../META-INF/mysql-schema.sql`）。

要点：

- 库名没有硬性要求；3.2.4 自带的 `application.properties` 示例用的是 `nacos`（旧文档常见 `nacos_config`）。
- **所有节点必须连同一个 MySQL 实例 / 高可用 MySQL 集群**——Nacos 自身不复制 DB 数据，DB 的可用性是 CP 侧的单点，需要 DB 侧做主从 / 集群。
- 3.x 把数据源**插件化**：官方默认实现提供 `nacos-datasource-plugin-mysql` / `-derby` / `-postgresql` / `-oracle` 四个插件（3.2.4 实测），每个插件各自带 `META-INF/*-schema.sql`。接入 PostgreSQL 等只需换插件 + 放 JDBC 驱动，配置方式随插件而定。

## Table Structure (MySQL schema)

以 3.2.4 的 `mysql-schema.sql` 为准，库里一共 **13 张表**，按职能分四组：

**配置管理表**

| 表 | 用途 |
| :-- | :-- |
| `config_info` | 配置主表，`content` 为全文；`data_id` + `group_id` + `tenant_id` 唯一键 |
| `his_config_info` | 配置变更历史，每次增删改留痕（`op_type`：I/U/D） |
| `config_info_gray` | **灰度配置**（3.x 取代旧的 `config_info_beta`） |
| `config_tags_relation` | 配置与 tag 的关联关系 |

> [!WARNING]
> **2.x 常见的三张表在 3.x 已不存在**（3.2.4 的 `mysql-schema.sql` 中 0 命中）：
> `config_info_beta`（Beta 灰度，改为 `config_info_gray`）、`config_info_tag`（按 tag 隔离配置）、
> `config_info_aggr`（聚合配置，按 datum_id 分批）。
> 这三个表名如今只出现在 `distribution/conf/1.4.0-ipv6_support-update.sql` 这份 **1.4.0 历史升级脚本**
> 和两份测试用 `derby-schema.sql` 里，**不要按它们去查 3.x 的库**。

**多租户 / 容量表**

| 表 | 用途 |
| :-- | :-- |
| `tenant_info` | 租户（namespace）元数据 |
| `tenant_capacity` | 租户级配额（quota / usage / max_size / max_aggr_count / max_aggr_size / max_history_count） |
| `group_capacity` | 分组级配额 |

**鉴权表**（与 [Security](/docs/CS/Framework/nacos/security.md) 对应）

| 表 | 用途 |
| :-- | :-- |
| `users` | 用户凭证（`password` 为 BCrypt；schema 里**不再内置任何 INSERT**，即没有默认 `nacos/nacos`，需初始化时自行设置） |
| `roles` | 用户 → 角色（`ROLE_ADMIN` 等） |
| `permissions` | 角色 → 资源 / 操作（RBAC） |

**3.x 新增表**

| 表 | 用途 |
| :-- | :-- |
| `ai_resource` / `ai_resource_version` | AI 资源（MCP / Prompt 等）及其版本，纳入同一 namespace 体系 |
| `pipeline_execution` | AI 资源发布审核 Pipeline 的执行记录（`execution_id` 主键，`pipeline` 存节点结果 JSON） |

### Config Main Table Key Columns

`config_info` 的几列决定了 Nacos 的运转方式：

- **`data_id` + `group_id` + `tenant_id`**：三元组唯一确定一条配置，对应客户端的 `dataId` / `group` / `namespace`。唯一索引 `uk_configinfo_datagrouptenant` 保证单租户内不重复。
- **`content`**：配置全文（yaml / json / properties / text），`longtext`。
- **`md5`**：内容 MD5，客户端 / 服务端用它做「是否变更」的快速比对，避免每次拉全量。
- **`type`**：内容类型（yaml / json / properties / text / xml …），影响控制台渲染与解析。
- **`encrypted_data_key`**：配置加密场景下保存的数据密钥（配合配置加密插件，原文以密文存储）。
- **`gmt_create` / `gmt_modified`**：时间戳，驱动 dump / 监听的增量判断。
- 历史表 `his_config_info` 在 3.x 多出 `publish_type`（`formal` / `gray`）、`gray_name`、`ext_info` 三列——灰度发布也会进历史，与上面的 `config_info_gray` 是同一套灰度模型。

## Capacity and Quota

`tenant_capacity` / `group_capacity` 控制单租户、单分组的配额（最大配置数、最大容量、使用量）。超限会拒绝发布——容量相关异常在监控里表现为配置发布失败，排查时先看这两个表与对应配额配置。

## Persistence Boundary Summary

| 数据 | 是否落 DB | 一致性 | 重启后 |
| :-- | :-- | :-- | :-- |
| 配置（config） | 是（config_info 等） | CP / JRaft | 从 DB + Raft 恢复 |
| 权限 / 租户 | 是（users/roles/permissions/tenant_info） | CP | 恢复 |
| 临时实例（ephemeral） | 否 | AP / Distro（内存） | 丢失，靠重注册补回 |
| 持久实例（persistent） | 是（经 JRaft 落 DB） | CP | 恢复 |

记住这条边界，就能解释 Nacos 运维里大量「现象」：配置永不丢、临时实例重启会抖、扩缩容要让 `cluster.conf` 与 Raft 成员一致等。

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Config](/docs/CS/Framework/nacos/config.md)
- [JRaft](/docs/CS/Framework/nacos/jraft.md)
- [Security](/docs/CS/Framework/nacos/security.md)
- [etcd 存储对照](/docs/CS/Framework/etcd/boltdb.md)

## References

- <https://nacos.io/docs/latest/manual/admin/deployment/deployment-best-practices>
- <https://nacos.io/docs/v3.0/manual/admin/auth/>
- <https://github.com/alibaba/nacos/blob/3.2.4/plugin-default-impl/nacos-default-datasource-plugin/nacos-datasource-plugin-mysql/src/main/resources/META-INF/mysql-schema.sql>
- <https://github.com/alibaba/nacos/blob/3.2.4/specs/zh-cn/plugin/datasource-dialect-plugin-spec.md>
