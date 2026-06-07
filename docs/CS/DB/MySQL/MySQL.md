## 简介

MySQL 是一个数据库管理系统（DBMS）。

### 体系结构

MySQL 采用了客户端-服务器架构。

#### 连接层

- 连接池组件
- 认证组件

#### 服务层

- 管理服务和工具组件：备份、恢复、安全管理等
- SQL 接口组件：DML、DDL、存储过程、视图、触发器
- 解析器组件：语法解析
- 优化器组件：查询优化，选择索引和执行计划
- 缓存和缓冲区组件：查询缓存（MySQL 8.0 中已移除）

#### 存储引擎层

可插拔式存储引擎架构，支持多种存储引擎同时使用。
常用的存储引擎包括 InnoDB、MyISAM、Memory 等。

#### 文件系统层

数据存储在文件系统中，与操作系统交互。

### 存储引擎

MySQL 支持多种存储引擎，最常用的包括：

#### InnoDB

InnoDB 是 MySQL 的默认存储引擎，支持：

- 事务（ACID 兼容）
- 行级锁
- 外键约束
- 崩溃恢复
- MVCC（多版本并发控制）

#### MyISAM

MyISAM 是 MySQL 的旧存储引擎（在 MySQL 5.5.5 之前为默认引擎），不支持事务。

#### Memory

Memory 存储引擎将数据存储在内存中，重启后数据会丢失。

#### NDB（NDB Cluster）

NDB 是 MySQL Cluster 使用的存储引擎。

### 锁类型

MySQL 中的锁类型包括：

- **全局锁**：锁定整个数据库实例，通常用于全库备份。
- **表级锁**：包括表锁和元数据锁（MDL）。
- **行级锁**：InnoDB 支持行级锁，包括记录锁、间隙锁和 Next-Key 锁。
- **意向锁**：用于表示事务打算在行上获取的锁类型。

### SQL 执行流程

1. **解析**：解析器进行词法和语法分析，生成解析树。
2. **预处理**：验证表和列是否存在，解析权限。
3. **优化**：优化器选择最佳执行计划。
4. **执行**：执行器根据执行计划调用存储引擎 API。

### 日志

MySQL Server 层：

- binlog：二进制日志，用于复制和恢复。
- error log：错误日志。
- general query log：通用查询日志。
- slow query log：慢查询日志。

InnoDB 存储引擎层：

- redo log：重做日志，用于崩溃恢复。
- undo log：回滚日志，用于事务回滚和 MVCC。

### 复制

MySQL 复制通过 binlog 实现：

- **异步复制**：主库写入 binlog 后立即返回，不等待从库确认。
- **半同步复制**：主库等待至少一个从库确认收到 binlog 后再提交。
- **组复制**：基于 Paxos 协议的组复制。

### XA 事务

外部 XA 事务允许在多个资源管理器之间协调事务。

## 架构

```sql

SELECT * FROM users WHERE id = 1;
```

1. 查询缓存（MySQL 5.7 及更早版本）
2. 解析器 -> 解析树
3. 预处理器 -> 验证语义
4. 优化器 -> 执行计划
5. 执行器 -> 调用存储引擎 API

### 客户端连接

- 使用 TCP 连接
- 认证

### 缓存

MySQL 8.0 已移除查询缓存。

```sql
SHOW STATUS LIKE 'Qcache%';
```

## 数据类型

### 整型

TINYINT、SMALLINT、MEDIUMINT、INT、BIGINT

### 浮点型

FLOAT、DOUBLE

### 定点型

DECIMAL

### 字符串

CHAR、VARCHAR、BINARY、VARBINARY、BLOB、TEXT、ENUM、SET

### 日期和时间

DATE、TIME、YEAR、DATETIME、TIMESTAMP

### JSON

MySQL 5.7.8 引入了 JSON 类型。

## MySQL 的索引类型

- B+ 树索引
- 哈希索引
- 全文索引
- 空间索引（R 树）

## 查询执行顺序

```sql
SELECT ...
FROM ...
JOIN ...
ON ...
WHERE ...
GROUP BY ...
HAVING ...
ORDER BY ...
LIMIT ...
```

## 参考

```shell
SELECT VERSION();
SELECT @@version;
```

MySQL 中的 ROW 操作

```sql
INSERT INTO users (name, age) VALUES ('John', 25);
SELECT * FROM users;
UPDATE users SET age = 26 WHERE id = 1;
DELETE FROM users WHERE id = 1;
```

- DDL
- DML
- DCL

### 数据库创建

```sql
CREATE DATABASE IF NOT EXISTS mydb DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci;
```

## 链接

- [MySQL 官方文档](https://dev.mysql.com/doc/)
- [InnoDB 存储引擎](/docs/CS/DB/MySQL/InnoDB.md)
- [MySQL 复制](/docs/CS/DB/MySQL/replica.md)
