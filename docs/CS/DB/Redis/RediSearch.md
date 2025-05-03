## Introduction



RediSearch 是一个高性能的全文搜索引擎，它可以作为一个 Redis Module（扩展模块）运行在 Redis 服务器上





```shell
git clone https://github.com/RedisLabsModules/RediSearch.git
cd RediSearch # 进入模块目录
make all
```



安装完成之后，可以使用如下命令启动 Redis 并加载 RediSearch 模块，命令如下：

```shell
src/redis-server redis.conf --loadmodule ../RediSearch/src/redisearch.so
```







## Links

- [Redis](/docs/CS/DB/Redis/Redis.md?id=struct)


## References

1. []()