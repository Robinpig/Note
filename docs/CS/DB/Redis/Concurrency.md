## Introduction

Redis是 多进程 + 多线程 混合并发模型

- 多进程: 子进程处理[持久化]() RDB/AOF
- 多线程: 主线程 + 后台线程 + IO线程





## 多进程

子进程触发条件

```
rdbSaveBackground
```



```
rdbSaveToSlavesSockets
```



```
rewriteAppendOnlyFileBackground
```



## 多线程



Redis 使用单线程模型进行设计 保证了每个操作的原子性，减少了线程创建的开销 也减少了线程的上下文切换和竞争 不需要考虑各种锁问题 同时能带来更好的可维护性，方便开发和调试

> It’s not very frequent that CPU becomes your bottleneck with Redis, as usually Redis is either memory or network bound.
> For instance, using pipelining Redis running on an average Linux system can deliver even 1 million requests per second, so if your application mainly uses O(N) or O(log(N)) commands, it is hardly going to use too much CPU.

如果这种吞吐量不能满足我们的需求，更推荐的做法是使用分片的方式将不同的请求交给不同的 Redis 服务器来处理，而不是在同一个 Redis 服务中引入大量的多线程操作

Redis 4.0后开始使用多线程 新版的 Redis 服务在执行一些命令时就会使用主处理线程之外的其他线程，例如 UNLINK、FLUSHALL ASYNC、FLUSHDB ASYNC 等非阻塞的删除操作

> However with Redis 4.0 we started to make Redis more threaded.
> For now this is limited to deleting objects in the background, and to blocking commands implemented via Redis modules.
> For the next releases, the plan is to make Redis more and more threaded.







## Links

- [Redis](/docs/CS/DB/Redis/Redis.md?id=struct)

## References

1. [[Redis] 浅析 Redis 并发模型](https://wenfh2020.com/2023/12/25/redis-multi-thread/)