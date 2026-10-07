## Introduction

[SUBSCRIBE](https://redis.io/commands/subscribe)、[UNSUBSCRIBE](https://redis.io/commands/unsubscribe) 与 [PUBLISH](https://redis.io/commands/publish) 实现了 [发布/订阅（Publish/Subscribe）](http://en.wikipedia.org/wiki/Publish/subscribe) 消息范式：发送者（publisher）并不针对特定接收者（subscriber）发送消息，而是按频道（channel）分类发布；订阅者只接收自己感兴趣的频道消息，双方彼此解耦，从而得到更好的可扩展性与更动态的网络拓扑。

> [!NOTE]
> `redis-cli` 一旦进入订阅态就不再接受其它命令，只能按 `Ctrl-C` 退出订阅模式。

Pub/Sub 即发即弃、不持久化，离线订阅者会永久丢失消息，更适合"在线推送、丢一两条无妨"的场景（实时通知、行情广播、配置热更新等）。若需要持久化、ACK 与重投，应改用 [Streams（Redis 作为 MQ）](/docs/CS/DB/Redis/MQ.md)。

## Database & Scoping

Pub/Sub 与 key space 完全无关，它在任何层面都不与 key 空间互相干扰，包括逻辑数据库编号（db number）。

在 db 10 上发布的消息，db 1 上的订阅者同样能收到。

如果确实需要隔离（如区分 test / staging / production 环境），只能在频道名上加前缀。

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)
- [Redis 作为 MQ（Streams 消费者组、ACK 等）](/docs/CS/DB/Redis/MQ.md)
- [Scheduled Task](/docs/CS/SE/Scheduled_Task.md)

## References

1. Redis Pub/Sub 官方文档：https://redis.io/docs/latest/develop/interact/pubsub/
2. SUBSCRIBE 命令参考：https://redis.io/commands/subscribe/
3. PUBLISH 命令参考：https://redis.io/commands/publish/
