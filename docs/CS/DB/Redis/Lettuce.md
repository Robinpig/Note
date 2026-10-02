## Introduction

Lettuce 是基于 **Netty 的可伸缩 Redis 客户端**（Spring Data Redis / Spring Boot 2.x 起的默认客户端），与老牌 [Jedis](/docs/CS/DB/Redis/Jedis.md) 的关键差异是：它**线程安全且天生异步**——单个连接通过 Netty 的事件循环多路复用并发处理多个命令，不需要为每个线程借还连接；而 Jedis 的连接对象非线程安全，必须依赖 commons-pool2 连接池。

## 三种调用方式

```java
RedisClient client = RedisClient.create("redis://localhost:6379");
StatefulRedisConnection<String, String> conn = client.connect();
RedisStringCommands<String, String> sync = conn.sync();

String v = sync.get("k");                       // 同步
RedisFuture<String> f = conn.async().get("k"); // 异步（基于 Netty Future/Promise）
conn.reactive().get("k").subscribe(v -> {});   // 响应式（Reactor Flux/Mono）

conn.close(); client.shutdown();
```

同步、异步、Reactive 三套 API 共享同一连接——同步调用只是把异步命令阻塞等待。这种模型天然契合虚拟线程与 WebFlux：少量连接就能支撑高并发。

## 与 Jedis/Redisson 对比

| 维度 | Jedis | Lettuce | Redisson |
|------|-------|---------|----------|
| IO 模型 | BIO，同步阻塞 | Netty NIO，多路复用 | Netty NIO |
| 线程模型 | 连接非线程安全，靠连接池 | 连接线程安全，可单连接共享 | 线程安全 |
| API | 贴近原生命令 | sync/async/reactive | 高层对象（分布式锁、集合、布隆过滤器） |
| 特色 | 简单直接、开销小 | Spring 默认、拓扑刷新 | 分布式协调能力最全，见 [Redisson](/docs/CS/DB/Redis/Redisson.md) |
| 连接开销 | 池内连接数多 | 极少连接 | 少 |

## 集群与拓扑刷新

- 支持 Sentinel、Cluster、Pipeline、事务、Pub/Sub（订阅独占一个新连接）；
- 集群模式下槽位迁移（resharding）时，MOVED/ASK 重定向可能让旧拓扑失效。需要显式开启周期性与自适应拓扑刷新：

```java
ClusterTopologyRefreshOptions opt = ClusterTopologyRefreshOptions.builder()
        .enablePeriodicRefresh(Duration.ofSeconds(30))      // 周期刷新
        .enableAllAdaptiveRefreshTriggers()                 // MOVED/ASK/重连等事件触发
        .build();
```

这是从 Jedis 迁移到 Lettuce 后最常见的线上坑：不开刷新时槽位迁移会持续报 MOVED 错误。

## 超时与连接管理

- 命令级超时 `RedisURI.timeout`、`setTimeout`；底层是命令排队 + Netty channel 事件驱动，注意超时命令的响应回来时要被丢弃（Lettuce 内部处理）；
- 自动重连默认开启，连接断开期间命令默认排队等待（也可配置拒绝）；
- 阻塞型命令（BLPOP）会占用连接通道，和普通命令混用要注意调度。
- 底层命令与数据结构参见 [Redis](/docs/CS/DB/Redis/Redis.md)，分布式锁不要自己用 SETNX 拼装，直接用 Redisson（见 [Lock](/docs/CS/DB/Redis/Lock.md)）。

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)
- [Jedis](/docs/CS/DB/Redis/Jedis.md)
- [Redisson](/docs/CS/DB/Redis/Redisson.md)
- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [Redis 分布式锁](/docs/CS/DB/Redis/Lock.md)

## References

1. [Lettuce 官方文档](https://lettuce.io/core/release/reference/)
