## Introduction

MySQL 与其它「一个数据库只有一种存储实现」的 DBMS 不同，采用**插件式存储引擎架构**：Server 层负责连接管理、SQL 解析/优化、缓存、内置函数等通用逻辑，
而数据真正如何存储、如何建索引、如何加锁与实现事务，则交给可插拔的**存储引擎（Storage Engine，也叫表类型）**。引擎是**按表**而非按库指定的——同一个库的不同表可以用不同引擎。

```sql
CREATE TABLE t (...) ENGINE=InnoDB;          -- 建表指定引擎
SHOW ENGINES;                                -- 查看当前实例支持的引擎
SHOW CREATE TABLE t;                         -- 查看某表所用引擎
```

## Architecture

- **连接层**：连接处理、授权认证、线程池复用、SSL。
- **服务层（Server）**：SQL 接口、解析器、查询[优化器](/docs/CS/DB/MySQL/Optimizer.md)、查询缓存（8.0 移除）、内置函数、存储过程/触发器/视图，以及跨引擎的通用能力。
- **引擎层**：真正负责数据的存储与提取，索引在这一层实现（不同引擎索引结构不同），通过 Handler API 向 Server 层提供统一的行读写接口。
- **存储层**：落在文件系统上的数据、索引、redo/undo/binlog 等。

下面源码片段展示了 InnoDB 作为一个 `MYSQL_STORAGE_ENGINE_PLUGIN` 向 Server 注册的方式，正是「插件式」的体现：

```cpp
mysql_declare_plugin(innobase){
    MYSQL_STORAGE_ENGINE_PLUGIN,
    &innobase_storage_engine,
    innobase_hton_name,
    PLUGIN_AUTHOR_ORACLE,
    "Supports transactions, row-level locking, and foreign keys",
    PLUGIN_LICENSE_GPL,
    innodb_init,   /* Plugin Init */
    nullptr,       /* Plugin Check uninstall */
    innodb_deinit, /* Plugin Deinit */
    INNODB_VERSION_SHORT,
    innodb_status_variables_export, /* status variables */
    innobase_system_variables,      /* system variables */
    nullptr,                        /* reserved */
    0,                              /* flags */
},
    i_s_innodb_trx, i_s_innodb_cmp, i_s_innodb_cmp_reset, i_s_innodb_cmpmem,
    i_s_innodb_cmpmem_reset, i_s_innodb_cmp_per_index,
    i_s_innodb_cmp_per_index_reset, i_s_innodb_buffer_page,
    i_s_innodb_buffer_page_lru, i_s_innodb_buffer_stats,
    i_s_innodb_temp_table_info, i_s_innodb_metrics,
    i_s_innodb_ft_default_stopword, i_s_innodb_ft_deleted,
    i_s_innodb_ft_being_deleted, i_s_innodb_ft_config,
    i_s_innodb_ft_index_cache, i_s_innodb_ft_index_table, i_s_innodb_tables,
    i_s_innodb_tablestats, i_s_innodb_indexes, i_s_innodb_tablespaces,
    i_s_innodb_columns, i_s_innodb_virtual, i_s_innodb_cached_indexes,
    i_s_innodb_session_temp_tablespaces

    mysql_declare_plugin_end;
```

## Common Engines

### InnoDB

MySQL **5.5 之后的默认引擎**，面向高并发、事务型业务，细节见 [InnoDB](/docs/CS/DB/MySQL/InnoDB.md)。

- 支持 **ACID 事务**（[redo](/docs/CS/DB/MySQL/redolog.md)/[undo](/docs/CS/DB/MySQL/undolog.md)、MVCC）、**行级锁**、**外键**；
- 聚簇索引组织表（[Index](/docs/CS/DB/MySQL/Index.md)），二级索引叶子存主键值；
- 磁盘文件：表结构 + 独立表空间 `xxx.ibd`（数据与索引在一起，受 `innodb_file_per_table` 控制）；
- 逻辑存储结构：表空间 → 段（segment）→ 区（extent，1MB = 64 个 16KB 页）→ 页（page，默认 16KB，磁盘 I/O 最小单元）→ 行（含隐藏字段 DB_TRX_ID/DB_ROLL_PTR/DB_ROW_ID），见 [tablespace](/docs/CS/DB/MySQL/tablespace.md)。

### MyISAM

MySQL 早期默认引擎：

- **不支持事务、不支持外键，只有表锁**，并发写能力弱；但只读/追加场景访问快、批量插入快、占用空间小；
- 文件三件套：`xxx.sdi`（8.0 前是 `.frm`，表结构）、`xxx.MYD`（数据）、`xxx.MYI`（索引，索引与数据分离，非聚簇）；
- 适合读多写少、不需要事务的非核心场景（日志、历史表、报表），如今这类需求不少已转向 MongoDB/分析型存储。

### MEMORY（Heap）

- 数据全部放在内存，默认使用 **Hash 索引**（也支持 B-Tree），重启即丢、容量受限于内存；
- 磁盘上只有表结构文件 `xxx.sdi`；适合临时表、缓存、Lookup 表，如今大量场景被 [Redis](/docs/CS/DB/Redis/Redis.md) 取代。
- 注意它与 InnoDB 用内存做的 [Buffer Pool](/docs/CS/DB/MySQL/memory.md) 不是一回事。

### Comparison

| 特点 | InnoDB | MyISAM | MEMORY |
| --- | --- | --- | --- |
| 事务 | **支持（ACID）** | 不支持 | 不支持 |
| 锁粒度 | **行锁**（也可表锁） | 表锁 | 表锁 |
| 外键 | **支持** | 不支持 | 不支持 |
| B+Tree 索引 | 支持 | 支持 | 支持 |
| Hash 索引 | 不直接建（有自适应 Hash） | 不支持 | **默认支持** |
| 全文索引 | 5.6+ 支持 | 支持 | 不支持 |
| 索引组织方式 | 聚簇（数据即主键索引叶子） | 非聚簇（.MYI/.MYD 分离） | 内存 |
| 空间/内存占用 | 较高 | 低 | N/A |
| 批量插入速度 | 相对低 | 高 | 高 |
| 持久性 | 崩溃可恢复 | 较弱 | 无（重启丢数据） |

**面试高频——InnoDB vs MyISAM**：核心就三点——① 是否支持事务；② 行锁还是表锁；③ 是否支持外键。再补充聚簇索引/崩溃恢复（redo log）的差异即可。

## Choosing an Engine

- **默认就选 InnoDB**：需要事务、外键、高并发读写、要求崩溃恢复的核心业务。现代 MySQL 几乎没有主动选 MyISAM 的理由。
- **MyISAM**：只读或以追加插入为主、几乎不更新删除、且不要求事务的边缘场景。
- **MEMORY**：会话内临时数据、维表缓存，但要接受易失与容量限制；持久化缓存优先考虑 Redis。
- 其它引擎各有专门用途（如 CSV、Archive、Federated、Blackhole），生产 OLTP 基本围绕 InnoDB。

## Links

- [InnoDB](/docs/CS/DB/MySQL/InnoDB.md)
- [Index](/docs/CS/DB/MySQL/Index.md) — 各引擎索引结构差异
- [tablespace](/docs/CS/DB/MySQL/tablespace.md)
- [MySQL](/docs/CS/DB/MySQL/MySQL.md)

## References

1. [Alternative Storage Engines (MySQL Reference Manual)](https://dev.mysql.com/doc/refman/8.0/en/storage-engines.html)
2. [InnoDB Introduction](https://dev.mysql.com/doc/refman/8.0/en/innodb-introduction.html)
