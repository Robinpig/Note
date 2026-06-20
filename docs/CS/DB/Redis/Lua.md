
## Introduction


## script

## Redis Lua scripts debugger
Starting with version 3.2 Redis includes a complete Lua debugger, that can be used in order to make the task of writing complex Redis scripts much simpler.

By default every new debugging session is a **forked session**. This also means that changes are **rolled back** after the script debugging session finished.

An alternative synchronous (non forked) debugging model is available on demand, so that changes to the dataset can be retained. In this mode the server blocks for the time the debugging session is active





## Links

- [Redis](/docs/CS/DB/Redis/Redis.md?id=struct)

## References
1. [Redis Lua scripts debugger](https://redis.io/topics/ldb)
