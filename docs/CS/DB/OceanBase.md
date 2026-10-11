## Introduction





## Installation



```shell
docker run -d \
  --name oceanbase \
  -p 2881:2881 \
  -p 2883:2883 \
  -e MODE=slim \
  -e OB_ROOT_PASSWORD=yourpassword \
  -v ob_data:/root/ob \
  oceanbase/oceanbase-ce:latest
```

进入容器 连接数据库无需密码

```shell
docker exec -it oceanbase bash
obclient -h127.0.0.1 -P2881 -uroo
```

修改密码

```sql
-- 将 root 用户的密码修改为你想要的密码（例如 yourpassword）
ALTER USER root IDENTIFIED BY 'yourpassword';

-- 刷新权限使其生效
FLUSH PRIVILEGES;
```





## Architecture





## Migration





## MySQL

从 MySQL 迁移到 OceanBase

## Links

- [BLink-Tree](/docs/CS/DB/BLink-Tree.md)
- [Cassandra](/docs/CS/DB/Cassandra.md)
- [ClickHouse](/docs/CS/DB/ClickHouse.md)
- [DB](/docs/CS/DB/DB.md)
- [Doris](/docs/CS/DB/Doris.md)
- [Dragonfly](/docs/CS/DB/Dragonfly.md)


## References

1. [OceanBase 文档](https://www.oceanbase.com/docs)
2. [oceanbase/oceanbase](https://github.com/oceanbase/oceanbase)
