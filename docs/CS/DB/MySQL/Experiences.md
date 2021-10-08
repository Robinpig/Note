## Configurations

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

1. use cover index + child serach primary key
2. remember last index (for a continuous query)
3. lower rank for a overflow limit offset value(fail-fast return 4XX)

