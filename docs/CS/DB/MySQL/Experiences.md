## 配置

### 创建新用户

```mysql
create user 'robin'@'%' identified by '123456';

grant all privileges on *.* to 'robin'@'%';

flush privileges;
```

### 忘记密码

1. 以 skip-grant-tables 模式启动数据库

```shell
#Mariadb 
>/bin/mysqld_safe --skip-grant-tables&
```

2. 重置密码

```mysql
# mysql
MariaDB [(none)]> use mysql;  
MariaDB [mysql]> UPDATE user SET password=password('newpassword') WHERE user='user';  
MariaDB [mysql]> flush privileges;   
MariaDB [mysql]> exit; 
```

3. 正常重启数据库

## 使用

### 搜索分页

1. 使用覆盖索引 + 子查询主键
2. 记住上一页最后一条记录的索引（用于连续查询）
3. 对于过大的 limit offset 值降低优先级（快速失败返回 4XX）
