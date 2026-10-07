## Introduction

Oracle Database 是 Oracle 公司的商业关系数据库，长期占据高端企业市场（金融、电信、政务），强项是 MPP/RAC 集群、成熟的事务一致性、复杂查询优化器（CBO）和一整套企业级组件（分区、ASM、Data Guard、RMAN、AWR）。它是典型的**重许可、重 DBA 运维**体系，互联网公司更多使用 [MySQL](/docs/CS/DB/MySQL/MySQL.md)/[PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)，但存量核心系统迁移时仍绕不开它。

## Architecture (Essential Differences from MySQL)

- **实例（Instance）= SGA（共享内存）+ 后台进程**，一个数据库可以被 RAC 的多个实例同时挂载，这是 Oracle 共享存储集群的基础；MySQL 是单实例对应数据目录。
- **数据库物理文件**：datafile（数据）、control file（控制文件，多路复用）、redo log（在线重做日志，至少两组循环写）、archive log（归档）、spfile/pfile（参数）。
- **逻辑结构**：表空间（tablespace）→ 段（segment）→ 区（extent，连续块）→ 块（block，默认 8K）。schema 在 Oracle 里基本等同于一个用户（user），这与 MySQL 的 database 概念错位，是迁移最常见的混淆点。
- **进程模型**：专用服务器（每连接一个影子进程，类似 PG）或共享服务器（MTS，连接复用）；没有 MySQL 那种线程模型。

## Multi-Version and Consistency

- Oracle 原生就是 **MVCC**：回滚段（undo segment，9i 后自动管理 UNDO 表空间）保存旧版本，读不阻塞写、写不阻塞读，查询以 SCN（System Change Number，单调递增的逻辑时钟）做一致性视图，实现一致性读与闪回查询（`AS OF SCN/TIMESTAMP`）。对照 MySQL 的实现见 [undolog](/docs/CS/DB/MySQL/undolog.md)。
- 事务控制走 **redo（物理重做，前滚）+ undo（逻辑回滚）**：提交时只要 redo 落盘即可返回（commit 快速提交），脏块由 DBWn 后台懒写——和 [InnoDB redo log](/docs/CS/DB/MySQL/redolog.md) 的 WAL 思想同源但进程分工不同（LGWR/DBWn/ARCH/SMON/PMON）。
- 隔离级别默认 **READ COMMITTED**，可串行化需要显式设置；没有 MySQL REPEATABLE READ + gap lock 的组合，锁模型以行锁 + ITL（事务槽）为主。

## Common SQL and Dialect Differences

Oracle 的 SQL 方言与 MySQL 差别不小：`DUAL` 虚表、字符串用单引号、分页历史上靠 `ROWNUM`（12c 后支持 `OFFSET/FETCH FIRST n ROWS ONLY`）、自增列靠序列（SEQUENCE，12c 起有 identity column）、空字符串等同于 NULL。

charset：

```sql
select userenv('language'), lengthb('_') as byte_num, length('_') as char_num from dual;
```

字符集排查要点：`USERENV('LANGUAGE')` 返回语言_地域.数据库字符集；`LENGTHB` 按字节、`LENGTH` 按字符，二者差异可判断 AL32UTF8 下一个汉字占 3 字节是否导致 `VARCHAR2(n BYTE)` 截断（建表可声明 `VARCHAR2(n CHAR)` 按字符计量）。

其他高频写法：

```sql
-- 分页（12c+）
SELECT * FROM t ORDER BY id OFFSET 10 ROWS FETCH FIRST 20 ROWS ONLY;
-- 序列
CREATE SEQUENCE seq_t START WITH 1 INCREMENT BY 1 NOCACHE;
INSERT INTO t(id, name) VALUES (seq_t.NEXTVAL, 'x');
-- 执行计划
EXPLAIN PLAN FOR SELECT * FROM t WHERE id = 1;
SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY);
```

## Operations and Performance

- **AWR / Statspack**：定期快照性能数据，`awrrpt.sql` 出对比报告，是定位性能问题的第一入口；ASH 提供会话级实时采样。
- **执行计划与统计信息**：CBO 依赖直方图与统计信息（`DBMS_STATS.GATHER_TABLE_STATS`），统计信息陈旧是执行计划突变的首因；可用 SQL Plan Baseline 固定计划。
- **等待事件模型**：`V$SESSION_WAIT`/`V$SYSTEM_EVENT` 把瓶颈归因为 db file sequential read、log file sync、buffer busy waits 等，调优按 Top 等待事件推进。
- 高可用：**Data Guard**（物理/逻辑备库，redo 同步，对应 MySQL 主从但有最大保护/可用/性能三档保护模式）、**RAC**（多实例共享存储，解决可用性与水平读，不解决水平写）、**RMAN** 备份恢复。

## Comparison with Open-Source Databases

| 维度 | Oracle | MySQL/InnoDB | PostgreSQL |
|------|--------|--------------|------------|
| 集群 | RAC 共享存储 + DG | 主从/Group Replication | 流复制/Patroni |
| MVCC 旧版本 | UNDO 段（独立） | 回滚段在 undo 表空间 | 元组多版本 + VACUUM |
| 序列 | SEQUENCE 原生 | AUTO_INCREMENT | SEQUENCE/SERIAL |
| 分页 | ROWNUM / 12c OFFSET | LIMIT | LIMIT/OFFSET |
| 成本 | 商业 License 高昂 | 开源 | 开源 |

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [MySQL](/docs/CS/DB/MySQL/MySQL.md)
- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [InnoDB](/docs/CS/DB/MySQL/InnoDB.md)

## References

1. [Oracle Database 官方文档](https://docs.oracle.com/en/database/oracle/oracle-database/)
2. [Concepts for Database Administrators](https://docs.oracle.com/en/database/oracle/oracle-database/19/admin/get-started-with-database-administration.html)
