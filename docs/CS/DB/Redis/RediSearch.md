## Introduction

RediSearch 是一个高性能的全文搜索引擎，它可以作为一个 [Redis Module](/docs/CS/DB/Redis/module.md)（扩展模块）运行在 Redis 服务器上

> [!NOTE]
> 仓库地址已迁移：`RedisLabsModules/RediSearch` 现为 301 重定向到 **`RediSearch/RediSearch`**（未归档，描述为「A query and indexing engine for Redis, providing secondary indexing, full-text search, vector similarity search and aggregations」）。





```shell
git clone https://github.com/RediSearch/RediSearch.git
cd RediSearch # 进入模块目录
make all
```



安装完成之后，可以使用如下命令启动 Redis 并加载 RediSearch 模块，命令如下：

```shell
src/redis-server redis.conf --loadmodule ../RediSearch/src/redisearch.so
```







## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)
- [module.md](/docs/CS/DB/Redis/module.md)


## References

1. [RediSearch](https://github.com/RediSearch/RediSearch)
