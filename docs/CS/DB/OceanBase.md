## Introduction





## Installation



```shell
docker run -d \
  --name oceanbase \
  -p 2881:2881 \
  -p 2883:2883 \
  -e MODE=slim \
  -e OB_ROOT_PASSWORD=OceanBase_123 \
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
-- 将 root 用户的密码修改为你想要的密码（例如 OceanBase_123）
ALTER USER root IDENTIFIED BY 'OceanBase_123';

-- 刷新权限使其生效
FLUSH PRIVILEGES;
```





## Architecture





## Migration





## MySQL

从MySQL迁移到OceanBase





