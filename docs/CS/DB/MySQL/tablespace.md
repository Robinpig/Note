## 简介

表空间（Tablespace）是 `InnoDB` 存储引擎的存储结构，包含一个或多个数据文件。

### 段

段（Segment）包括数据段、索引段、回滚段等。

### 区

区（Extent）由 64 个连续的页组成，大小为 1MB。

### 页

页（Page）是 InnoDB 磁盘管理的最小单位，默认大小为 16KB。
可通过 `innodb_page_size` 设置为 4K、8K、16K、32K 或 64K。

页的类型：

- 数据页（B-tree Node）
- undo 页
- 系统页
- 事务数据页
- 插入缓冲位图页
- 插入缓冲空闲列表页
- 未压缩的二进制大对象页
- 压缩的二进制大对象页

### 行

行（Row）是数据存储的最小逻辑单元。
InnoDB 支持 Antelope 和 Barracuda 两种行格式。

#### Compact 行格式

Compact 行格式在 MySQL 5.0 中引入。

#### Redundant 行格式

Redundant 行格式是 MySQL/InnoDB 的旧行格式。

#### Dynamic 行格式

Dynamic 行格式在 MySQL 5.6 中引入，使用 Barracuda 文件格式。

#### Compressed 行格式

Compressed 行格式使用 zlib 压缩表和索引数据。

### 数据文件

- `.ibd` 文件：每个独立表空间的数据文件。
- `.ibdata` 文件：系统表空间的数据文件。

## 链接

- [InnoDB 存储引擎](/docs/CS/DB/MySQL/InnoDB.md?id=innodb-on-disk-structures)
