# MySQL



## Transaction

**Implement on engine layer, and only innodb support transaction.**

- Atomicity
- Consistency
- Isolation
- Durability



Isolation Problem

- Dirty read
- Non-repeatable read
- Phantom read



Isolation level

- Read uncommitted
- Read committed default in Oracle SQL server
- Repetable read **default level in MySQL**
- Serializable



![image-20210430214713744](/Users/robin/Library/Application Support/typora-user-images/image-20210430214713744.png)

Table

笛卡尔积

Forever table

temp table

- union union all
- Temptable algorithm
- distinct and order by



virtual table

2

### Server




- 连接器 身份认证 权限管理 连接不断 即使修改了权限 此连接不受影响
- 查询缓存 8.0后移除 缓存select语句及结果集 因在频繁更新情况下经常失效
- 分析器 无命中缓存进入 词法分析 提出关键字段 语法分析 检验语句是否正确
- 优化器 内部实现 执行计划 选择索引 
- 执行器 检验有权限后调用引擎接口 返回执行结果
- 日志模块 binlog公有 redolog只InnoDB有
### Engine

```shell
mysql> select version();
10.3.27-MariaDB
```

| Engine | Support | Comment | Transactions | XA   | Savepoints |
| ------ | ------- | ------- | ------------ | ---- | ---------- |
| MEMORY	| YES	| Hash based, stored in memory, useful for temporary tables	| NO	| NO | NO |
| MRG_MyISAM	| YES	| Collection of identical MyISAM tables	| NO	| NO	| NO |
| CSV	| YES	| Stores tables as CSV files	| NO	| NO	| NO |
| BLACKHOLE	| YES	| /dev/null storage engine (anything you write to it disappears)	| NO	| NO	| NO |
| MyISAM	| YES	| Non-transactional engine with good performance and small data footprint	| NO	| NO	| NO |
| ARCHIVE	| YES	| gzip-compresses tables for a low storage footprint	| NO	| NO	| NO |
| FEDERATED	| YES	| Allows to access tables on other MariaDB servers, supports transactions and more	| YES	| NO	| YES |
| PERFORMANCE_SCHEMA	| YES	| Performance Schema	| NO	| NO	NO |
| SEQUENCE	| YES	| Generated tables filled with sequential values	| YES	NO	| YES |
| InnoDB	| DEFAULT	| Supports transactions, row-level locking, foreign keys and encryption for tables	| YES	| YES	| YES |
| Aria	| YES	| Crash-safe tables with MyISAM heritage	| NO	| NO	| NO |



```shell
mysql> select version();
5.7.34
```

| Engine | Support | Comment | Transactions | XA   | Savepoints |
| ------ | ------- | ------- | ------------ | ---- | ---------- |
| InnoDB | DEFAULT | Supports transactions, row-level locking, and foreign keys | YES  | YES  | YES  |
| MRG_MYISAM | YES | Collection of identical MyISAM tables | NO | NO | NO |
| MEMORY | YES | Hash based, stored in memory, useful for temporary tables | NO | NO | NO |
| BLACKHOLE | YES | /dev/null storage engine (anything you write to it disappears) | NO | NO | NO |
| MyISAM | YES | MyISAM storage engine | NO | NO | NO |
| CSV | YES | CSV storage engine | NO | NO | NO |
| ARCHIVE | YES | Archive storage engine | NO | NO | NO |
| PERFORMANCE_SCHEMA | YES | Performance Schema | NO | NO   | NO |
| FEDERATED | NO | Federated MySQL storage engine | NULL | NULL | NULL |



#### MyISAM和InnoDB区别 

  MyISAM:

Select immediately 

数据文件毁坏后不易恢复

Not support:

- transactions, row-level locking, foreign keys and encryption for tables
- 

Support:
- Full-Text, B-Tree, R-Tree index

    

Storage file

- .frm defintion of tables
- .MYD data
- .MYI index



  InnoDB:



storage file

- .frm
- .ibd 索引和data一起

查询先定位到数据块 再到行 较MyISAM直接定位慢

支持事务 外键 行级锁 MVCC 支持真正的在线热备份

### Index  

    Hash索引：
        InnoDB当索引使用频繁时在B+Tree上再建哈希索引
    B+Tree索引：
    Fractal Tree索引：
    全文索引：
        MyISAM支持全文索引 用以查找文本关键字 而不是直接比较是否相等
        MATCH AGAINST 不是WHERE InnoDB 5.6.4后支持全文索引
    空间数据索引：
        MyISAM支持空间数据索引（R-Tree） 地理数据存储



### MVCC

多版本并发控制
    只使用于读提交和可重复读
    InnoDB 存储引擎实现隔离级别的一种具体方式，用于实现提交读和可重复读这两种隔离级别
    版本号
        系统版本号 开启一个事务 就会递增
        事务版本号 事务开始时系统版本号
    隐藏列：    每行记录后有两个隐藏列版本号
        创建版本号 创建时系统版本号
        删除版本号 删除版本未定义或大于当前事务版本号则该快照有效
    Undo日志
        使用的快照存储在Undo日志 通过回滚指针把一个行所有快照连接



### 锁机制：
  三级封锁协议
     

 - 写与写互斥 防止数据覆盖
 - 读不允许写 防止脏读
 - 读不允许写 防止不可重复读
   

  两段锁协议

 - 加锁与解锁分成两个阶段

 意向锁都是表级锁 相互兼容
### 数据库优化
限制查询 少用*
读写分离 主库写 从库查
垂直分区 数据表列拆分 拆成多表 对事务要求更复杂
    MySQL分区表 物理上为多文件 逻辑上为一个表 跨分区查询效率低 建议采用物理分表
水平分区 分库 事务逻辑复杂

#### 数据库字段设计规范

- 字符串转换成数字类型存储 IP地址 inet_aton inet_ntoa 
- 非负数数据（如自增ID）优先无符号整型
- 避免使用TEXT BLOB 大数据 内存临时表不支持 只能磁盘临时表 只能前缀索引 
- 避免使用ENUM 操作复杂
- 尽可能所有列都为非空 索引NULL列需要额外空间 比较计算也要特殊处理
- 存储时间不用字符串 占用更大空间 无法直接比较
- 财务金额使用decimal

  #### 索引设计规范
- 限制每张表上的索引数量,建议单张表索引不超过 5 个
- 禁止给表中的每一列都建立单独的索引
- 每个 Innodb 表必须有个主键
- 频繁的查询优先考虑使用覆盖索引 避免 Innodb 表进行索引的二次查询  随机 IO 变成顺序 IO 
- 尽量避免使用外键约束
- 避免使用子查询，可以把子查询优化为 join 操作
- 避免使用 JOIN 关联太多的表
- 减少同数据库的交互次数
- 对应同一列进行 or 判断时，使用 in 代替 or
- WHERE 从句中禁止对列进行函数转换和计算

**MySQL字符集**
采用类似继承方式 表的默认字符集是数据库的字符集 未指定使用时采用默认

