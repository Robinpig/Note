## Introduction

## script

## Redis Lua 脚本调试器
从 3.2 版本开始，Redis 包含了一个完整的 Lua 调试器，可用于简化编写复杂 Redis 脚本的任务。

默认情况下，每个新的调试会话都是**分支会话**。
这也意味着脚本调试会话结束后，更改会被**回滚**。

按需提供另一种同步（非分支）调试模式，以便保留对数据集的更改。
在此模式下，服务器在调试会话活动期间阻塞。

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md?id=struct)

## References
1. [Redis Lua scripts debugger](https://redis.io/topics/ldb)
