## Introduction

> 版本基线：Redis 8.10.2（commit 498ecd0d）。

RediSearch 是 Redis 的**查询与索引引擎**（query and indexing engine），提供二级索引、全文搜索、向量相似度检索与聚合。**8.0.0 起这套能力以 Query Engine 形态内建进 Redis Open Source**，不再只是外挂 Module——`FT.CREATE` / `FT.SEARCH` 等命令开箱可用，见枢纽 [Version Baseline](/docs/CS/DB/Redis/Redis.md) 的 8.0 条目。8.x 默认应直接使用内建 Query Engine，无需 `--loadmodule`。

> [!NOTE]
> 仓库地址已迁移：`RedisLabsModules/RediSearch` 现为 301 重定向到 **`RediSearch/RediSearch`**（未归档，描述为「A query and indexing engine for Redis, providing secondary indexing, full-text search, vector similarity search and aggregations」）。
>
> 该仓库对应的是**独立 module 发行版**；内建 Query Engine 的源码随 Redis 主仓库一起发布。若确需独立 module（例如部署 7.x，或想独立于内建版本跟踪上游新特性），可按下方步骤自行编译加载。





```shell
git clone https://github.com/RediSearch/RediSearch.git
cd RediSearch # 进入模块目录
make all
```



（独立 module 场景）编译完成后，用 `--loadmodule` 启动 Redis 加载该模块：

```shell
src/redis-server redis.conf --loadmodule ../RediSearch/src/redisearch.so
```







## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)
- [module.md](/docs/CS/DB/Redis/module.md)


## References

1. [RediSearch](https://github.com/RediSearch/RediSearch)
