# Nacos 存储与持久化

## Introduction

Nacos 的存储最容易踩的坑是：**它不是一个「全量落盘」的中间件**。哪些数据进数据库、哪些只在内存，取决于一致性模型：

- **命名（服务发现）的临时实例走 AP（Distro）**：实例注册 / 心跳全在内存，节点间异步同步。**不写数据库**——节点重启后内存里的临时实例会丢，靠客户端重连 / 心跳重新注册补回。这也是为什么 Nacos 集群里「重启一台，实例会被短暂摘除」是预期行为。
- **配置（config）走 CP（JRaft）**：配置内容、灰度、标签、历史、租户、权限**全部落外部数据库**，并借 Raft 保证多节点一致。

所以「Nacos 用什么存储」要分两层答：共识元数据靠 **JRaft 日志 + 快照**（见 [JRaft](/docs/CS/Framework/nacos/jraft.md)），业务持久化靠 **Derby（单机）/ MySQL（集群）**。

## Derby：单机内嵌，不可集群

- Nacos 默认内置 **Apache Derby**，standalone 模式开箱即用，无需外部依赖，`conf/derby-schema.sql` 初始化。
- Derby 是**单文件嵌入式数据库**，**不支持多节点并发写入**：集群模式下若多个 Nacos 共用同一份 Derby 数据会直接报错 / 锁冲突。
- 官方明确：Derby 仅供本地开发、demo、单节点，**生产集群必须用 MySQL**。
- 踩坑：Docker 环境偶尔出现 `load derby-schema.sql error`——根因多是 Derby 初始化失败或挂载冲突，标准解法就是切 MySQL。

```properties
# standalone 默认即可，无需配置；集群务必切换：
spring.datasource.platform=mysql
```

## MySQL：集群生产存储

集群部署在 `application.properties` 里切到 MySQL，并导入 `conf/mysql-schema.sql`：

```properties
spring.datasource.platform=mysql
db.url.0=jdbc:mysql://127.0.0.1:3306/nacos_config?characterEncoding=utf8&connectTimeout=1000&socketTimeout=3000&autoReconnect=true&useUnicode=true&useSSL=false&serverTimezone=UTC
db.user.0=nacos
db.password.0=nacos
# 多库可继续 db.url.1 / db.user.1 ...
```

要点：

- 数据库名通常叫 `nacos_config`，表结构由官方 `mysql-schema.sql` 创建。
- **所有节点必须连同一个 MySQL 实例 / 高可用 MySQL 集群**——Nacos 自身不复制 DB 数据，DB 的可用性是 CP 侧的单点，需要 DB 侧做主从 / 集群。
- 3.x 起通过**多数据源插件**支持 PostgreSQL 等（官方文档「多数据源插件」），配置方式随插件而定，JDBC 驱动需自行放置；Oracle 11g 及以下官方插件已不再向下兼容。

## 表结构（MySQL schema）

Nacos 的库按职能分三组，约 11~15 张表（3.x 多出 AI 资源相关表）：

**配置管理表**

| 表 | 用途 |
| :-- | :-- |
| `config_info` | 配置主表，`content` 为全文；`data_id` + `group_id` + `tenant_id` 唯一键 |
| `his_config_info` | 配置变更历史，每次增删改留痕（`op_type`：I/U/D） |
| `config_info_beta` | Beta 灰度配置 |
| `config_info_tag` | 按 tag 维度隔离的配置 |
| `config_info_aggr` | 聚合配置（按 datum_id 分批，大型配置拆分） |

**多租户 / 容量表**

| 表 | 用途 |
| :-- | :-- |
| `tenant_info` | 租户（namespace）元数据 |
| `tenant_capacity` | 租户级配额（quota / usage / max_size） |
| `group_capacity` | 分组级配额 |

**鉴权表**（与 [Security](/docs/CS/Framework/nacos/security.md) 对应）

| 表 | 用途 |
| :-- | :-- |
| `users` | 用户凭证（`password` 为 BCrypt，2.4.0+ 默认无 `nacos/nacos`） |
| `roles` | 用户 → 角色（`ROLE_ADMIN` 等） |
| `permissions` | 角色 → 资源 / 操作（RBAC） |

3.x 额外引入 `ai_resource` 等 AI 资源管理表，纳入同一 namespace 体系。

### 配置主表关键列

`config_info` 的几列决定了 Nacos 的运转方式：

- **`data_id` + `group_id` + `tenant_id`**：三元组唯一确定一条配置，对应客户端的 `dataId` / `group` / `namespace`。唯一索引 `uk_configinfo_datagrouptenant` 保证单租户内不重复。
- **`content`**：配置全文（yaml / json / properties / text），`longtext`。
- **`md5`**：内容 MD5，客户端 / 服务端用它做「是否变更」的快速比对，避免每次拉全量。
- **`type`**：内容类型（yaml / json / properties / text / xml …），影响控制台渲染与解析。
- **`encrypted_data_key`**：配置加密场景下保存的数据密钥（配合配置加密插件，原文以密文存储）。
- **`gmt_create` / `gmt_modified`**：时间戳，驱动 dump / 监听的增量判断。

## 容量与配额

`tenant_capacity` / `group_capacity` 控制单租户、单分组的配额（最大配置数、最大容量、使用量）。超限会拒绝发布——容量相关异常在监控里表现为配置发布失败，排查时先看这两个表与对应配额配置。

## 持久化边界小结

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
- <https://github.com/alibaba/nacos/blob/master/distribution/conf/mysql-schema.sql>
