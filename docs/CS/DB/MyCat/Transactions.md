## Introduction

分库分表之后，事务与主键是两座绕不开的山：单库的 ACID 到了多分片就退化成「尽力而为」，自增主键到了多分片就不再唯一。MyCAT 的答案分两层——事务上提供**弱 XA**与**真 XA**（1.6.5 起）两档，主键上提供**全局序列号**。本页讲清两档事务的语义边界、序列号的用法，以及与外部事务协调者（Seata）的分工。

## Weak XA: The Default Compromise

MyCAT 默认的事务形态是**弱 XA**，官网特性清单的原文措辞就是「支持分布式事务(弱xa)」。它的执行形态是一阶段提交：

1. MyCAT 在参与的每个分片上开启本地事务
2. 各分片本地执行、本地提交（或回滚）
3. **没有两阶段Prepare、没有全局协调者**

后果要说透：正常情况下它和普通事务没区别；异常情况下（某分片提交成功、某分片失败、或 MyCAT 在中间崩溃），**部分分片已提交、部分未提交，数据处于不一致状态**，且没有自动补偿机制——要么业务层对账冲正，要么人工介入。所谓「弱」，弱在**没有原子性保证**。

1.6 还有一条与事务相邻的坑（README 点名）：**回滚事务时可能发生连接泄露**，尤其强制放弃连接之后。监控后端连接数是 MyCAT 事务健康的常规手段。

## XA: Two-Phase Since 1.6.5

真 XA（两阶段提交）从 **1.6.5** 起支持，这也是「MyCAT 支持分布式事务」这类说法的版本分界线——更早的版本只有弱 XA。两阶段提交提供的是原子性：要么全部分片提交，要么全部回滚。

但 XA 的代价必须一起算：

- **性能**：两次 RTT + 事务日志 + 锁定窗口拉长，吞吐显著低于单分片事务。
- **可用性**：协调者（MyCAT 自身）在第二阶段前崩溃，分片进入「prepared 挂起」状态，恢复依赖 XA 恢复日志；后端 MySQL 的 `innodb_support_xa` 与 binlog 的配合要确认。
- **语义上限**：XA 保证原子性，不保证隔离性——跨分片仍没有全局快照，写冲突检测是各分片本地的。

MyCAT2 对 XA 做了两处值得知道的修正：**不涉及跨库时不再升级成 XA 事务**（单分片事务走本地路径），以及**修复了 XA 在不跨库时保留后端连接、导致读写分离失效**的问题——都是「XA 路径误伤普通事务」的教训。

选型上：**单分片事务（精确路由）是绝大多数请求应该走的路径**；跨分片写入先想 ER 分片能不能合并；真跨分片且要原子性，才上 XA，并接受吞吐损失。

## Global Sequence: Primary Keys Across Shards

分库分表后，各分片独立自增的主键必然重复。MyCAT 的方案是全局序列号，用法是 SQL 内嵌的 next value 语法：

```sql
INSERT INTO `travelrecord` (`id`, user_id) VALUES ('next value for MYCATSEQ_GLOBAL', "xxx");
```

几个关键事实：

- **这不是 MySQL 8 的 `AUTO_INCREMENT`**，是一个字符串字面量占位符，MyCAT 在路由前把它替换成序列值。ORM 的默认主键策略（依赖 `getGeneratedKeys` 或数据库默认值）直接失效，**接入必须改造主键生成方式**：要么 SQL 里手写 next value，要么应用层用自己的 ID 方案（雪花等）。
- **序列的供给方式在 1.6 起可配置**：文件、数据库表、ZooKeeper（zk 序列，1.6 新增）、本地时间戳等。多 MyCAT 实例共享号段必须走 ZK 或数据库，本地文件/时间戳只在单实例下可靠。
- **MyCAT2 支持全局表自增序列号插入的三种方式**（release notes），并对 null/0 值的列自动替换为自增值——1.x 时代「忘了写 next value 导致主键为 0」的坑在 2.x 有兜底。

## Seata and External Coordinators

MyCAT2 的仓库里有一个 `seata` 模块——外部事务协调者的集成被做成一等公民。分工上：

| 层 | 提供什么 | 不提供什么 |
| :--- | :--- | :--- |
| MyCAT 弱 XA | 低开销的「常态一致」 | 异常时的一致性（需对账补偿） |
| MyCAT XA | 跨分片原子性 | 高吞吐、全局隔离性 |
| Seata（AT/TCC/SAGA） | 业务级分布式事务模式、与业务逻辑配合的补偿 | 需要应用显式声明分支事务、引入额外部署 |

实务中的常见组合：**MyCAT 负责路由与读写分离，事务边界尽量设计成单分片；真正跨分片的写，要么 XA、要么把一致性推给业务层的对账与冲正**。指望中间件把分布式事务做得跟单库一样，是分库分表项目最常见的预期错位。

## Links

- [MyCat](/docs/CS/DB/MyCat/MyCat.md)
- [Read_Write_Split](/docs/CS/DB/MyCat/Read_Write_Split.md)
- [SQL_Routing](/docs/CS/DB/MyCat/SQL_Routing.md)
- [Shard](/docs/CS/DB/Shard.md)

## References

1. [MyCAT 官方网站 · 关键特性（弱 XA、XA 1.6.5、全局序列号）](https://www.mycat.org.cn)
2. [MyCATApache/Mycat-Server README（next value for MYCATSEQ_GLOBAL 语法）](https://github.com/MyCATApache/Mycat-Server)
3. [MyCATApache/Mycat2 Releases（XA 行为修正与全局表自增序列）](https://github.com/MyCATApache/Mycat2/releases)
