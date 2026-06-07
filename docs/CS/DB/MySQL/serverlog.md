## 简介

MySQL Server 日志包含：

- **错误日志**（Error Log）
- **通用查询日志**（General Query Log）
- **慢查询日志**（Slow Query Log）
- **二进制日志**（Binary Log）
- **中继日志**（Relay Log）

### 二进制日志

二进制日志（Binary Log / Binlog）包含描述数据库变更（如表创建或表数据修改）的"事件"。
它还包含可能进行修改的语句的事件（除非使用基于行的日志记录）。
二进制日志也用于 `SELECT` 语句，这些语句不会修改数据。

> 二进制日志有两个重要用途：
> 1. **复制**：主库将二进制日志发送给从库，从库执行这些事件以保持数据一致。
> 2. **数据恢复**：通过 `mysqlbinlog` 工具处理二进制日志来恢复数据。

> 二进制日志在事务提交时写入，包含已提交的事务。

### 中继日志

中继日志（Relay Log）是由从库 I/O 线程从主库二进制日志读取的事件组成的日志。
然后，从库 SQL 线程执行中继日志中的事件。

### 慢查询日志

慢查询日志（Slow Query Log）包含执行时间超过 `long_query_time` 秒且至少检查 `min_examined_row_limit` 行的 SQL 语句。

## 链接

- [MySQL Server](/docs/CS/DB/MySQL/MySQL.md)
- [MySQL 复制](/docs/CS/DB/MySQL/replica.md)

## 参考

1. [MySQL 官方文档 - 二进制日志](https://dev.mysql.com/doc/refman/8.0/en/binary-log.html)
