# Nacos Storage and Persistence

## Introduction

Nacos 的存储最容易踩的坑是：**它不是一个「全量落盘」的中间件**。哪些数据进数据库、哪些只在内存，完全取决于一致性模型：临时实例走 AP（Distro），全在内存、不落库；配置走 CP（JRaft），全部落外部数据库并借 Raft 保证多节点一致（见 [一致性抽象层](/docs/CS/Framework/nacos/consistency.md)）。

> 版本基线：Nacos 3.2.4（commit 2c587c0）。以下片段均取自该 tag，路径为模块相对路径。

三个需要先摆正的直觉：

- **3.x 有独立的 `persistence` 模块**，数据源实现以插件形式放在 `plugin-default-impl/nacos-default-datasource-plugin/`（mysql / derby / oracle / postgresql）；config 模块不再直接持有一堆 Mapper。
- **旧 `KvStorage` 接口与 `KvType{File,Memory,RocksDB}` 枚举在 3.2.4 已不存在**，全树只剩 `KvStorageException` 这个异常类。
- **`config_info_beta` / `config_info_tag` / `config_info_aggr` 三张表已移除**，灰度统一为 `config_info_gray` + `DumpAllGrayProcessor`。

## Persistence Boundary

```dot
digraph StorageBoundary {
  rankdir=LR;
  node [shape=box, style=rounded];

  subgraph cluster_ap {
    label="AP 侧 / 临时实例 (Distro)";
    mem [label="内存 DataStore\n(每个节点全量)"];
    snap [label="Distro 快照/校验\n仅内存数据交换"];
  }

  subgraph cluster_cp {
    label="CP 侧 / 配置 + 持久实例 (JRaft)";
    raft [label="Raft 日志 + NacosStateMachine"];
    db [label="外部 DB / 内嵌 Derby\nconfig_info 等 13 表"];
    disk [label="本地磁盘 dump\nconfig-data / worker_{port}"];
  }

  mem -> snap [label="异步同步"];
  raft -> db [label="onApply 落库"];
  db -> disk [label="DumpService 全量/增量"];
  disk -> mem [label="客户端直读降 DB 压力"];
}
```

## The persistence Module

3.x 把持久化从 config 模块里抽出来，独立成 `persistence` 模块：它持有数据源抽象（`DataSourceService`）、动态路由（`DynamicDataSource`）、内嵌库操作（`repository/embedded`）与配置条件（`configuration/condition`）。具体方言实现则在 `plugin-default-impl/nacos-default-datasource-plugin/` 下，每个插件自带建表脚本：

| 插件 | schema 资源 |
| :-- | :-- |
| `nacos-datasource-plugin-derby` | `META-INF/derby-schema.sql` |
| `nacos-datasource-plugin-mysql` | `META-INF/mysql-schema.sql` |
| `nacos-datasource-plugin-postgresql` | `META-INF/pg-schema.sql` |
| `nacos-datasource-plugin-oracle` | `META-INF/oracle-schema.sql` |

数据源实现由 `DynamicDataSource` 按「是否内嵌存储」二选一路由，且各自懒加载：

```java
public synchronized DataSourceService getDataSource() {
    try {
        // Embedded storage is used by default in stand-alone mode
        // In cluster mode, external databases are used by default
        if (DatasourceConfiguration.isEmbeddedStorage()) {
            if (localDataSourceService == null) {
                localDataSourceService = new LocalDataSourceServiceImpl();
                localDataSourceService.init();
            }
            return localDataSourceService;
        } else {
            if (basicDataSourceService == null) {
                basicDataSourceService = new ExternalDataSourceServiceImpl();
                basicDataSourceService.init();
            }
            return basicDataSourceService;
        }
    } catch (Exception e) {
        throw new RuntimeException(e);
    }
}
```

> [!NOTE]
> `distribution/conf/` 下已无 `mysql-schema.sql` 等建表脚本（3.2.4 实测）；脚本随数据源插件分发。Derby 是单文件嵌入式库，不支持多节点并发写，仅用于单机 / demo；生产集群必须切外部数据源（MySQL / PostgreSQL / Oracle）。

## Config Property Rename

平台属性在 3.x 已改名。`PersistenceConstant` 把新属性定义为 `DATASOURCE_PLATFORM_PROPERTY`，旧属性标成 `..._OLD` 并注释「may be removed with the upgrade of springboot version」：

```java
public class PersistenceConstant {

    /**
     * May be removed with the upgrade of springboot version.
     */
    public static final String DATASOURCE_PLATFORM_PROPERTY_OLD = "spring.datasource.platform";

    public static final String DATASOURCE_PLATFORM_PROPERTY = "spring.sql.init.platform";

    public static final String MYSQL = "mysql";

    public static final String DERBY = "derby";

    public static final String EMBEDDED_STORAGE = "embeddedStorage";
}
```

读取时**先读新属性、为空再回退旧属性**——这就是老配置目前仍可用的原因：

```java
public static String getDatasourcePlatform(String defaultPlatform) {
    String platform =
        EnvUtil.getProperty(PersistenceConstant.DATASOURCE_PLATFORM_PROPERTY, defaultPlatform);
    if (StringUtils.isBlank(platform)) {
        platform = EnvUtil.getProperty(PersistenceConstant.DATASOURCE_PLATFORM_PROPERTY_OLD,
            defaultPlatform);
    }
    return platform;
}
```

集群切 MySQL 的配置示例（注意端口、时区、重连参数）：

```properties
spring.sql.init.platform=mysql
db.num=1
db.url.0=jdbc:mysql://127.0.0.1:3306/nacos?characterEncoding=utf8&connectTimeout=1000&socketTimeout=3000&autoReconnect=true&useUnicode=true&useSSL=false&serverTimezone=UTC
db.user.0=nacos
db.password.0=nacos
```

> [!WARNING]
> **所有节点必须连同一个 MySQL 实例 / 高可用 MySQL 集群**——Nacos 自身不复制 DB 数据，DB 的可用性是 CP 侧的单点，需要 DB 侧做主从 / 集群。库名没有硬性要求，3.2.4 的 `application.properties` 示例用的是 `nacos`（旧文档常见 `nacos_config`）。

## Table Structure

以 3.2.4 的 `mysql-schema.sql` 为准，库里共 **13 张表**，按职能分组：

**配置管理表**

| 表 | 用途 |
| :-- | :-- |
| `config_info` | 配置主表，`content` 为全文；`data_id` + `group_id` + `tenant_id` 唯一键 |
| `his_config_info` | 配置变更历史（`op_type`：I/U/D；另有 `publish_type` / `gray_name` / `ext_info`） |
| `config_info_gray` | **灰度配置**（3.x 取代旧的 beta / tag 表） |
| `config_tags_relation` | 配置与 tag 的关联关系 |

**多租户 / 容量表**

| 表 | 用途 |
| :-- | :-- |
| `tenant_info` | 租户（namespace）元数据 |
| `tenant_capacity` | 租户级配额（quota / usage / max_size / max_aggr_count / max_aggr_size / max_history_count） |
| `group_capacity` | 分组级配额 |

**鉴权表**（见 [Security](/docs/CS/Framework/nacos/security.md)）

| 表 | 用途 |
| :-- | :-- |
| `users` | 用户凭证（BCrypt；schema 里**无内置 INSERT**，即没有默认 `nacos/nacos`，需初始化时自行设置） |
| `roles` | 用户 → 角色 |
| `permissions` | 角色 → 资源 / 操作（RBAC） |

**3.x 新增表**

| 表 | 用途 |
| :-- | :-- |
| `ai_resource` / `ai_resource_version` | AI 资源（MCP / Prompt 等）及版本，纳入同一 namespace 体系 |
| `pipeline_execution` | AI 资源发布审核 Pipeline 的执行记录 |

主表与灰度表都用四元组做唯一键——灰度表多一个 `gray_name` 维度，这正是 3.x 用一张表统一灰度的结构基础：

`config_info` 的唯一键：

```sql
UNIQUE KEY `uk_configinfo_datagrouptenant` (`data_id`,`group_id`,`tenant_id`)
```

`config_info_gray` 在四元组上做唯一键，多出的 `gray_name` 维度正是 3.x 用一张表统一灰度的结构基础：

```sql
`gray_name` varchar(128) NOT NULL COMMENT 'gray_name',
`gray_rule` text NOT NULL COMMENT 'gray_rule',
UNIQUE KEY `uk_configinfogray_datagrouptenantgray` (`data_id`,`group_id`,`tenant_id`,`gray_name`),
```

> [!WARNING]
> 2.x 常见的 `config_info_beta`（Beta 灰度）、`config_info_tag`（按 tag 隔离配置）、`config_info_aggr`（聚合配置）在 3.2.4 的 `mysql-schema.sql` 中 **0 命中**。它们只残留在历史升级脚本与测试用 schema 里，**不要按它们去查 3.x 的库**。相应地，dump 侧的 `DumpAllBetaProcessor` / `DumpAllTagProcessor` 也已删除（0 命中），只剩 `DumpAllProcessor` 与 `DumpAllGrayProcessor`。

### Config Main Table Key Columns

`config_info` 的几列决定 Nacos 的运转方式：

- **`data_id` + `group_id` + `tenant_id`**：三元组唯一确定一条配置，对应客户端的 `dataId` / `group` / `namespace`。
- **`content` / `md5`**：全文与内容摘要；md5 用于「是否变更」的快速比对，避免每次拉全量。
- **`encrypted_data_key`**：配置加密场景下保存的数据密钥（原文以密文存储）。
- **`gmt_create` / `gmt_modified`**：时间戳，驱动 dump / 监听的增量判断。
- 历史表 `his_config_info` 在 3.x 多出 `publish_type`（`formal` / `gray`）、`gray_name`、`ext_info` 三列——灰度发布也进历史。

## Dump: DB → Local Disk

`DumpService` 启动时同时触发全量配置与全量灰度的 dump，并在集群模式下按 `DUMP_ALL_INTERVAL_IN_MINUTE`（= 6 × 60 分钟）定时全量重 dump：

```java
try {
    dumpAllConfigInfoOnStartup(dumpAllProcessor);
    dumpAllGrayConfigInfoOnStartup(dumpAllGrayProcessor);
} catch (Exception e) {
    LogUtil.FATAL_LOG.error(
        "Nacos Server did not start because dumpservice bean construction failure :\n" + e);
    throw new NacosException(NacosException.SERVER_ERROR,
        "Nacos Server did not start because dumpservice bean construction failure :\n"
            + e.getMessage(), e);
}
if (!EnvUtil.getStandaloneMode()) {
    long initialDelay = ThreadLocalRandom.current().nextInt(INITIAL_DELAY_IN_MINUTE) + 10;
    ConfigExecutor.scheduleConfigTask(new DumpAllProcessorRunner(), initialDelay,
        DUMP_ALL_INTERVAL_IN_MINUTE, TimeUnit.MINUTES);
    ConfigExecutor.scheduleConfigTask(new DumpAllGrayProcessorRunner(), initialDelay,
        DUMP_ALL_INTERVAL_IN_MINUTE, TimeUnit.MINUTES);
}
```

灰度 dump 由 `DumpAllGrayProcessor` 分页读 `config_info_gray`，逐条写本地磁盘：

```java
for (ConfigInfoGrayWrapper cf : page.getPageItems()) {
    if (StringUtils.isBlank(cf.getTenant())) {
        continue;
    }
    boolean result = ConfigCacheService
        .dumpGray(cf.getDataId(), cf.getGroup(), cf.getTenant(), cf.getGrayName(),
            cf.getGrayRule(), cf.getContent(),
            cf.getLastModified(), cf.getEncryptedDataKey());
}
```

这条「服务端 → 磁盘」的链路与「服务端 → 客户端」的推送是两条独立链路，后者见 [Config Push](/docs/CS/Framework/nacos/config-push.md)。

## Persistence Boundary Summary

| 数据 | 是否落 DB | 一致性 | 重启后 |
| :-- | :-- | :-- | :-- |
| 配置（config） | 是（config_info 等） | CP / JRaft | 从 DB + Raft 恢复 |
| 权限 / 租户 | 是（users/roles/permissions/tenant_info） | CP | 恢复 |
| 临时实例（ephemeral） | 否 | AP / Distro（内存） | 丢失，靠重注册补回 |
| 持久实例（persistent） | 是（经 JRaft 落 DB） | CP | 恢复 |

记住这条边界，就能解释 Nacos 运维里大量「现象」：配置永不丢、临时实例重启会抖、扩缩容要让 `cluster.conf` 与 Raft 成员一致。

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [一致性抽象层](/docs/CS/Framework/nacos/consistency.md)
- [JRaft](/docs/CS/Framework/nacos/jraft.md)
- [Config Push](/docs/CS/Framework/nacos/config-push.md)
- [Security](/docs/CS/Framework/nacos/security.md)

## References

- <https://github.com/alibaba/nacos/tree/3.2.4/persistence>
- <https://github.com/alibaba/nacos/blob/3.2.4/plugin-default-impl/nacos-default-datasource-plugin/nacos-datasource-plugin-mysql/src/main/resources/META-INF/mysql-schema.sql>
- <https://nacos.io/docs/latest/manual/admin/deployment/deployment-best-practices>
