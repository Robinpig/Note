## 简介

[SUBSCRIBE](https://redis.io/commands/subscribe)、[UNSUBSCRIBE](https://redis.io/commands/unsubscribe) 和 [PUBLISH](https://redis.io/commands/publish) 实现了 [发布/订阅消息范式](http://en.wikipedia.org/wiki/Publish/subscribe)，其中（引用维基百科）发送者（发布者）不需要将消息编程发送给特定的接收者（订阅者）。
相反，发布的消息被分类到频道中，发布者不知道有哪些（如果有的话）订阅者。
订阅者对一或多个频道表达兴趣，只接收感兴趣的消息，不知道有哪些（如果有的话）发布者。
这种发布者和订阅者的解耦可以允许更大的可扩展性和更动态的网络拓扑。

请注意，`redis-cli` 一旦进入订阅模式将不接受任何命令，只能通过 `Ctrl-C` 退出该模式。

### 数据库和作用域
Pub/Sub 与键空间无关。它的设计目的是在任何层面都不与键空间相互干扰，包括数据库编号。

在 db 10 上发布的消息，db 1 上的订阅者也能收到。

如果你需要某种作用域，可以为频道加上环境名称前缀（test、staging、production...）。

Redis 定时任务

通过开启 Keyspace Notifications 和 Pub/Sub 消息订阅的方式，可以拿到每个键值过期的事件，我们利用这个机制实现了给每个人开启一个定时任务的功能，过期事件中我们可以获取到过期键的 key 值，在 key 值中我们可以存储每个用户的 id，例如"user_1001"的方式，其中数字部分表示用户的编号，通过此编号就可以完成给对应人发送消息通知的功能

## 链接

- [Redis](/docs/CS/DB/Redis/Redis.md?id=struct)

## 参考
1. []()
