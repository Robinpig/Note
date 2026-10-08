## Introduction

这页记录账号维护、密码重置、深分页这类「零散但反复要用」的操作经验。它不解释机制——
索引结构与回表成本的成因见 Index 与 B-Tree，语句执行阶段见 SQL，这里只留「怎么做、这条命令在哪条版本线上还成立」。

| 项 | 值 |
| :--- | :--- |
| 正文默认版本 | MySQL 9.7.x LTS（最新 9.7.3，2026-08-18） |
| 源码核实基线 | tag `mysql-9.7.2` |
| 次要兼容目标 | 8.4.x LTS |
| 已停止支持 | 8.0（EOL 2026-04-30）、5.7（EOL 2023-10） |
| 核实日期 | 2026-10-07 |

> [!WARNING]
>
> 下列命令按 8.0+/9.7 口径写。标注了 5.x 或 MariaDB 的片段是**历史现场记录**，
> 用于解释旧脚本为什么长这样，不要照抄到现网。版本坐标与逐页勘误见
> [Version_Migration](/docs/CS/DB/MySQL/Version_Migration.md)。

## Configurations

### Create new User

```mysql
create user 'robin'@'%' identified by '123456';

grant all privileges on *.* to 'robin'@'%';

flush privileges;
```

`flush privileges` 只在**手工改过权限表**（`UPDATE mysql.user ...` 一类）之后才需要；
走 `CREATE USER` / `GRANT` 时账户信息本来就在内存里，这句是多余的，留着只是因为老脚本里都有。

- 9.0 起 `mysql_native_password` 已从服务端代码移除，新建账户默认走 `caching_sha2_password`。
  升级后「老客户端连不上」多半是驱动不支持 SHA2 认证或未启用 RSA 密钥交换，
  正确处置是升级驱动，而不是把认证插件改回去。
- 弱口令是否被拒取决于 `validate_password` 组件是否安装，与某个版本的默认参数无关，别指望换版本绕过。

### Forgot password

原始记录来自 MariaDB 与 5.7 之前的环境，那条路径在新版本上已经**不成立**：

```mysql
# 5.7 之前的 mysql.user：Password 列 + PASSWORD() 函数（现网勿用）
MariaDB [(none)]> use mysql;
MariaDB [mysql]> UPDATE user SET password=password('newpassword') WHERE user='user';
MariaDB [mysql]> flush privileges;
MariaDB [mysql]> exit;
```

变化的确切坐标是：**MySQL 8.0 移除了账号管理相关的这批废弃特性**——包括 `PASSWORD()` 函数、
`old_passwords` 系统变量，以及用 `GRANT` 顺带改账号属性的写法（官方升级说明里逐条列了）。
5.7 起 `mysql.user` 存放凭据的列也已由 `Password` 改为 `authentication_string`。
所以「UPDATE 权限表 + PASSWORD()」这条路在新版本上根本不成立，只剩账户语句这一条路径。

新版本（8.0+/9.7）的重置流程：

1. 以跳过权限表的方式启动

```shell
mysqld --skip-grant-tables --user=mysql &
```

这一步有两个副作用要知道：任何人无需密码即可连上并拥有全部权限（用完立刻正常重启），
并且服务端会同时启用 `skip_networking`，只能走本地连接；Windows 上还要额外开
`shared_memory` 或 `named_pipe`，否则服务起不来。

2. 连上之后**先执行 `FLUSH PRIVILEGES`，再改密码**

```mysql
FLUSH PRIVILEGES;
ALTER USER 'root'@'localhost' IDENTIFIED BY 'newpassword';
```

`--skip-grant-tables` 会禁用 `ALTER USER` / `SET PASSWORD` 这类账户管理语句，
必须先执行 `FLUSH PRIVILEGES` 让服务端重新加载权限表，账户语句才可用——这一步是新旧流程的实质差别，
漏掉报的是「account management statements are disabled」而不是权限不足。

3. 正常重启数据库

## Using


### Search Limit

深分页的三条经验，按性价比从高到低：

1. 用覆盖索引拿到主键，再按主键二次定位完整行。
2. 记住上一页的边界值做连续翻页（keyset 分页），彻底不出现大 offset。
3. offset 超过阈值就降级或直接 fail-fast 返回 4XX，不让它打到数据库。

```mysql
-- 反例：offset 越大，扫描后被丢弃的行越多
select id, name from tb_user order by id limit 1000000, 20;

-- 经验 1：先用覆盖索引选出主键，再回表，被丢弃的行不再携带整行宽度
select u.id, u.name
from tb_user u
join (select id from tb_user order by id limit 1000000, 20) as t on u.id = t.id;

-- 经验 2：keyset 分页，成本与页码无关
select id, name from tb_user where id > 1000000 order by id limit 20;
```

## Links

- [B-Tree](/docs/CS/DB/MySQL/B-Tree.md)
- [Double-Buffer](/docs/CS/DB/MySQL/Double-Buffer.md)
- [Index](/docs/CS/DB/MySQL/Index.md)
- [InnoDB](/docs/CS/DB/MySQL/InnoDB.md)
- [MySQL](/docs/CS/DB/MySQL/MySQL.md)
- [Optimization](/docs/CS/DB/MySQL/Optimization.md)
- [SQL](/docs/CS/DB/MySQL/SQL.md)

## References

- [How to Reset the Root Password](https://dev.mysql.com/doc/refman/9.7/en/resetting-permissions.html)
- [Changes in MySQL 8.0 (Account Management)](https://dev.mysql.com/doc/refman/8.0/en/upgrading-from-previous-series.html)
- [Assigning Passwords to Accounts](https://dev.mysql.com/doc/refman/9.7/en/assigning-passwords.html)
- [CREATE USER Statement](https://dev.mysql.com/doc/refman/9.7/en/create-user.html)
- [Pluggable Authentication](https://dev.mysql.com/doc/refman/9.7/en/pluggable-authentication.html)
- [LIMIT Query Optimization](https://dev.mysql.com/doc/refman/9.7/en/limit-optimization.html)
