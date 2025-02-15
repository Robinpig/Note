## Introduction


子事务


存储引擎只有redolog 没有undo log 子事务实现是通过分配一个新的事务id
子事务还可以继续创建子事务 构成一个树状结构

jDBC驱动配置了autosave需要同时配置cleanup savepoints 否则会引起性能问题


## Engine


OrioleDB





## Links


## References

1. [PGlite - Postgres in WASM](https://github.com/electric-sql/pglite)
