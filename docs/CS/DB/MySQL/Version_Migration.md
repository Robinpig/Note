## Introduction

本篇是 `docs/CS/DB/MySQL/` 子树的**版本坐标与勘误表**。子树里的多数笔记写于 MySQL 5.7 / 8.0 时代，
机制叙述大多仍然成立，但**类名、sysvar 默认值、SQL 语法和认证插件已经变了**。
凭印象照抄旧结论会写错，所以这里统一记录：当前该以哪个版本为准、哪些符号已消失、哪些结论已过期、
过期在**哪一篇的哪一节**。

读子树任意一篇之前，先在这里对齐坐标。

## Version Baseline

| 项 | 值 |
| :--- | :--- |
| 正文默认版本 | MySQL 9.7.x LTS（最新 9.7.3，2026-08-18） |
| 源码核实基线 | tag `mysql-9.7.2`（Gitee 镜像；9.7.3 相对 9.7.2 为 bug fix，不影响结构性结论） |
| 次要兼容目标 | MySQL 8.4.x LTS（最新 8.4.12，2026-08-18） |
| 已停止支持 | MySQL 8.0（EOL **2026-04-30**）、MySQL 5.7（EOL 2023-10） |
| 引擎版本口径 | InnoDB 引擎版本与 Server 版本**同号**，`INNODB_VERSION_MAJOR/MINOR/BUGFIX` 直接取 `MYSQL_VERSION_*` |
| 核实日期 | 2026-10-07 |

源码中 `MYSQL_VERSION` 文件里 `MYSQL_VERSION_MATURITY="LTS"`，可直接判定版本线成熟度，
不必依赖二手资料。

## Release Model: LTS and Innovation

MySQL 分两条生产级轨道，**都含 bug 与安全修复**：

| 轨道 | 定位 | 行为变化 | 支持期 |
| :--- | :--- | :--- | :--- |
| **LTS** | 稳定、长支持 | LTS 系列内**不移除特性**（移除只发生在该系列第一个版本，如 8.4.0） | 5 年 premier + 3 年 extended |
| **Innovation** | 追新、快迭代 | 会有行为变化、弃用清理、向 SQL 标准靠拢 | 支持到**下一个 Innovation** |

选轨的实质差别在于能否接受行为变化：LTS 保证同系列内数据格式不变、可直接原地升降级；
Innovation 降级需要逻辑导出导入（mysqldump 一类），不能只换二进制。

## Calendar Versioning After 9.7

**`MySQL 9.7` 是最后一条顺序版本号（`major.minor.patch`）版本线。** 此后改用日历版本号 `YY.M.P`：

- `YY` = 两位年份，`M` = 发布月份，`P` = 该发布线内的维护版本号，从 0 起。
- `26.7.0`（2026-07-28）是**第一个**合法的日历版本号发布，`26.7.1`（2026-08-18）是其补丁版。
- 被指定为 LTS 的日历版本，其 `YY.M` 基础号在整个支持周期内固定，只递增 `P`。
- ⚠️ **日历版本号本身不表明它是 LTS 还是 Innovation**，成熟度是每个发布的显式属性，
  要查发布说明或仓库轨道（如 `mysql-innovation-community` 与 `mysql-9.7-lts-community`）。

### Upgrade Paths

升级被「兼容族（compatibility lineage）」约束，不能只看版本号大小：

```text
8.4.x LTS  -> 9.7.x LTS                         允许（相邻 LTS）
8.4.x LTS  -> 28.4.x LTS                        不允许（跳过 LTS 系列）
9.7.x LTS  -> 首个日历版本化兼容族               允许（9.7 是唯一能直接接入的旧 LTS）
Innovation -> 同族内更晚的发布（含收尾的 LTS）      允许
Innovation -> 跨兼容族边界                       不允许
LTS 系列内原地升降级                             允许
Innovation 降级                                 需逻辑导出导入
```

顺序版本化时代「8.3.0 → 9.0.0 不行，必须先过 8.4.0 LTS」的规则同样适用于日历版本化：
**两个 Innovation 系列之间要用 LTS 做桥**。官方仓库为过渡做了便利：第一个 LTS 发布
（8.4.0）在仓库里同时算 LTS 与 Innovation。

## Authentication: mysql_native_password Removed

子树里若还在写 `mysql_native_password`，必须分版本线表述——**MySQL 9.0 起该插件已从服务端代码移除**，
源码 `sql/auth/sql_authentication.cc` 的注释原文是
`In MySQL 9.0 the mysql_native_password was removed from server code.`

| 版本线 | 状况 |
| :--- | :--- |
| 5.7 | `mysql_native_password` 是默认认证插件 |
| 8.0 | 默认改 `caching_sha2_password`；`mysql_native_password` 弃用但可用 |
| 8.4 | 需显式加载插件才可用，未加载会报 `mysql_native_password is not loaded` |
| **9.0+** | **插件已从服务端移除，该报错与变通方案均不适用**；只能走 `caching_sha2_password` 或 `authentication_ldap_sasl` / `authentication_openid_connect` 等 |

[MySQL Server](/docs/CS/DB/MySQL/MySQL.md) 的 Installation 小节记录的是 8.4 及更早的变通路径，
在 9.x 上会误导，已按版本线拆开。

## Lock System: CATS Replaced the Old Story

这是子树**漂移最严重**的一块。[lock](/docs/CS/DB/MySQL/lock.md) 原文写的是
「8.0.18 以前用 DFS 遍历等待图」「参考 MySQL 8.0 `DeadlockChecker` 类」，而 9.7 的实际实现是：

- **`DeadlockChecker` 类在 9.7 全树 grep 无命中，已不存在**。
- 锁**调度**改用 **CATS**（Contention-Aware Lock Scheduling）的变体，设计文档直接内嵌在
  `storage/innobase/include/lock0lock.h` 的 `@section sect_lock_sys_scheduling`。
  每个 WAITING 事务的 weight = 它传递性地阻塞的事务数，放行 weight 高者。
- 锁队列逻辑上分两组：Granted 从 **HEAD** 进、Waiting 从 **TAIL** 进。Grant Group 是逆时间序
  且有断言（CATS 不需要它，但死锁检测需要）；Wait Group 顺序无意义，因为 CATS weight 持续变化。
- 每个事务至多一个 WAITING 锁，因而至多一个 Blocking Transaction，所以这个信息直接存在事务对象上。
- **死锁检测与牺牲者选择已迁到 `lock/lock0wait.cc`**：先对等待 slot 做快照，
  用 `reservation_no`（slot 预约序号）判断快照后事务是否仍留在原 slot（防 ABA），
  再在成环集合里选牺牲者。
- 牺牲者权重 `TRX_WEIGHT(t) = t->undo_no + UT_LIST_GET_LEN(t->lock.trx_locks)`，
  即**改动行数 + 持有锁数**；比较函数 `trx_weight_ge()` 会**先看谁编辑过非事务表**，
  编辑过的一方更重。这与旧叙述里的「事务优先级/undo 大小/锁数量」大致同源但不等价。
- `innodb_deadlock_detect` 仍存在、默认 ON；关掉则完全依赖 `innodb_lock_wait_timeout`。

B-tree 侧 `index->lock` **没有被删**：`dict_index_t::lock` 仍在
（`include/dict0mem.h`，注释 "read-write lock protecting the upper levels of the index tree"），
`RW_SX_LATCH` 与 `btr_cur_latch_leaves()` 也还在用，并新增了
`BTR_LATCH_FOR_INSERT` / `BTR_LATCH_FOR_DELETE` 意图标志来收窄 `block->lock` 范围。
所以 [B-Tree](/docs/CS/DB/MySQL/B-Tree.md) 的 latch coupling / SMO 叙述方向正确，
需要补的是 9.7 现状而非推翻。

## Replication Vocabulary: slave to replica

| 旧（≤ 8.0.22 语境） | 新（9.7 实际） |
| :--- | :--- |
| `rpl_slave.cc` | `sql/rpl_replica.cc` |
| `SHOW SLAVE STATUS` | `SHOW REPLICA STATUS` |
| `Seconds_Behind_Master` | `Seconds_Behind_Source` |
| `CHANGE MASTER TO` | `CHANGE REPLICATION SOURCE TO` |
| `master_*` / `slave_*` sysvar | `source_*` / `replica_*`，旧名以 `Sys_var_deprecated_alias` 保留 |

旧写法在 9.7 **仍可执行**（弃用别名），但新笔记应以新式为主、旧式注明。
[replica](/docs/CS/DB/MySQL/replica.md) 原文通篇 `show slave status` / `seconds_behind_master`，属此类。

## Storage Engines in 9.7

`git ls-tree HEAD storage/` 得到 13 个引擎目录：
`archive, blackhole, csv, example, federated, heap, innobase, myisam, myisammrg, ndb, perfschema, secondary_engine_mock, temptable`。

两处子树需要留意的漂移：

- **MEMORY 引擎目录还在**，但内部临时表早已不靠它——
  `internal_tmp_mem_storage_engine ∈ {MEMORY, TempTable}`，默认 **TempTable**（8.0.16 起取代 MEMORY）。
  [plugin](/docs/CS/DB/MySQL/plugin.md) 讲 MEMORY 时要区分「表引擎」与「内部临时表载体」两件事。
- [MySQL Server](/docs/CS/DB/MySQL/MySQL.md) 里那张 `SHOW ENGINES` 输出与
  `SELECT VERSION(); -- 5.7.42` 是 5.7 时代快照，Docker 示例还停在 `mysql:5.7`（已 EOL）。

## Character Set Defaults

8.0 起服务端默认已是 **utf8mb4**（源码走 `my_charset_utf8mb4_0900_ai_ci`；
`default_character_set_name` 由 CMake 的 `MYSQL_DEFAULT_CHARSET_NAME` 注入）。
「默认 latin1 / latin1_swedish_ci」是 5.5/5.6 的事实。

⚠️ 另：[MySQL Server](/docs/CS/DB/MySQL/MySQL.md) 字符集小节的示例输出里
`character_sets_dir = /usr/share/mariadb/charsets` 是 **MariaDB** 的结果，被误当作 MySQL 记录。

## Errata By Page

改写各页时按此表逐条对照，避免旧结论残留：

| 页面 | 过期点 | 处置 |
| :--- | :--- | :--- |
| MySQL.md | `latin1` 默认字符集、5.7.42 快照、`mysql:5.7` Docker、8.4 认证变通、MariaDB 输出串台 | 按版本线拆分并更新 |
| lock.md | `DeadlockChecker` 类已不存在、DFS 叙述被 CATS 取代 | 改 9.7 实现并保留历史脉络 |
| replica.md | 通篇 slave/master 旧术语 | 换 replica/source，注明别名 |
| Double-Buffer.md | 空的 `// buf0dblwr.cc` 代码块残留 | 填真实摘录或删除 |
| memory.md | 图示外链指向已停更的 `refman/8.0` 文档站 | 改 9.7 或本地化配图 |
| B-Tree.md | 结论止于「5.7 之后」 | 补 8.4 / 9.7 的 SX latch 与意图标志 |
| Transaction.md | 体量大、混入源码摘录与旧版本断言 | 拆分并逐节校准 |

## Links

- [MySQL Server](/docs/CS/DB/MySQL/MySQL.md)
- [InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md)
- [Locks](/docs/CS/DB/MySQL/lock.md)
- [Replication](/docs/CS/DB/MySQL/replica.md)
- [Storage Engines](/docs/CS/DB/MySQL/plugin.md)
- [B-Tree](/docs/CS/DB/MySQL/B-Tree.md)

## References

1. [MySQL Releases: Innovation and LTS](https://dev.mysql.com/doc/refman/26.7/en/mysql-releases.html)
2. [MySQL End of Life Versions Notice](https://www.mysql.com/support/eol-notice.html)
3. [MySQL 9.7 Release Notes](https://dev.mysql.com/doc/relnotes/mysql/9.7/en/)
4. [MySQL 26.7 Release Notes](https://dev.mysql.com/doc/relnotes/mysql/26.7/en/)
5. [MySQL Reference Manual 9.7](https://dev.mysql.com/doc/refman/9.7/en/)
6. [Contention-Aware Lock Scheduling for Transactional Databases](https://dl.acm.org/doi/10.1145/3341301.3359648)
