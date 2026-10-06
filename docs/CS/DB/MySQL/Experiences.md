## Configurations

### Create new User

```mysql
create user 'robin'@'%' identified by '123456';

grant all privileges on *.* to 'robin'@'%';

flush privileges;
```

### Forgot password

1. Start db with skip-grant-tables


```shell
#Mariadb 
>/bin/mysqld_safe --skip-grant-tables&
```

2. Rest password

```mysql
# mysql
MariaDB [(none)]> use mysql;  
MariaDB [mysql]> UPDATE user SET password=password('newpassword') WHERE user='user';  
MariaDB [mysql]> flush privileges;   
MariaDB [mysql]> exit; 
```



3. Restart db as normal



## Using


### Search Limit

1. use cover index + child search primary key
2. remember last index (for a continuous query)
3. lower rank for a overflow limit offset value(fail-fast return 4XX)

## Links

- [B-Tree](/docs/CS/DB/MySQL/B-Tree.md)
- [Double-Buffer](/docs/CS/DB/MySQL/Double-Buffer.md)
- [Index](/docs/CS/DB/MySQL/Index.md)
- [InnoDB](/docs/CS/DB/MySQL/InnoDB.md)
- [cd source code root](/docs/CS/DB/MySQL/MySQL.md)
- [Optimization](/docs/CS/DB/MySQL/Optimization.md)
