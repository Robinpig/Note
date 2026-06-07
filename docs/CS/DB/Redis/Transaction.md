## 简介

[MULTI](https://redis.io/commands/multi)、[EXEC](https://redis.io/commands/exec)、[DISCARD](https://redis.io/commands/discard) 和 [WATCH](https://redis.io/commands/watch) 是 Redis 事务的基础。
它们允许在一个步骤中执行一组命令，并提供两个重要保证：

- 事务中的所有命令都被序列化并按顺序执行。在 Redis 事务执行过程中，不会出现另一个客户端发出的请求被中断服务的情况。这保证了命令作为单个隔离操作被执行。
- 所有命令要么全部被处理，要么全部不被处理，因此 Redis 事务也是原子的。EXEC 命令触发事务中所有命令的执行，因此如果客户端在调用 EXEC 命令之前失去与服务器的连接，则不会执行任何操作；如果调用 EXEC 命令，则执行所有操作。使用 append-only file 时，Redis 确保使用单个 write(2) 系统调用将事务写入磁盘。这样，在服务器崩溃的情况下，要么事务的全部内容都已记录，要么没有记录任何内容。

从 2.2 版本开始，Redis 还提供了乐观锁，以 check-and-set (CAS) 方式实现。

## 用法

使用 `MULTI` 命令进入 Redis 事务。该命令始终回复 `OK`。
此时用户可以发出多个命令。Redis 不会立即执行这些命令，而是将它们排队。
调用 `EXEC` 后，将执行所有命令。

作为替代方案，可以调用 `DISCARD` 刷新事务队列并退出事务。

```shell
> MULTI
OK
> INCR foo
QUEUED
> INCR bar
QUEUED
> EXEC
1) (integer) 1
2) (integer) 1
```

## 事务中的错误

在事务期间，可能会遇到两种命令错误：

- 命令可能入队失败，因此在调用 `EXEC` 之前就会出错。
  例如，命令可能在语法上错误（参数数量错误、命令名错误等），或者存在一些关键条件，如内存不足（如果服务器配置了 `maxmemory` 限制）。
- 在调用 `EXEC` 之后，命令可能失败。例如，对具有错误值的键执行操作（如对字符串值调用列表操作）。

在 `EXEC` 调用之前，客户端可以通过检查命令入队时的回复来发现错误：如果某个命令入队时返回 QUEUED，则正确入队；否则 Redis 返回错误。
如果在命令入队时发生错误，大多数客户端将中止事务并丢弃它。

但从 Redis 2.6.5 开始，服务器会记住在命令累积期间发生的错误，在 `EXEC` 时拒绝该事务，并自动丢弃事务（与 `DISCARD` 的效果相同）。

相反，在 `EXEC` 之后发生的错误不会以特殊方式处理：即使事务中的某些命令失败，所有其他命令也会继续执行。

## 为什么 Redis 不支持回滚

Redis 内部简化且速度更快，因为它不需要回滚能力。

## 使用 WATCH 实现 CAS

`WATCH` 用于为 Redis 事务提供 check-and-set (CAS) 行为。

监视的键会被检查是否有更改，以决定是否中止事务（如果至少有一个被监视的键在 `EXEC` 之前被修改，整个事务将中止并返回 `nil`）。

```shell
WATCH mykey
val = GET mykey
val = val + 1
MULTI
SET mykey $val
EXEC
```

使用上述代码，如果在执行 `WATCH` 之后且 `EXEC` 调用之前有另一个客户端修改了 `mykey` 的值，事务将失败。

### WATCH 说明

`WATCH` 可以多次调用。简单来说，`WATCH` 调用会标记要在之后检查更改的键（在 `EXEC` 时被检查）。从调用 `WATCH` 的那一刻起，Redis 会跟踪键是否被修改。如果在调用 `WATCH` 和 `EXEC` 之间，键被修改或删除，`EXEC` 将失败。

在 `EXEC` 被调用（无论成功与否）并且连接关闭后，所有 `WATCH` 都会被清除。此外，还可以使用 `UNWATCH` 命令（不带参数）刷新所有监视的键。

### 不使用 WATCH 的 CAS

`WATCH` 如上所述。但也可以不使用 `WATCH` 而仅使用 `INCR`（Redis 已经在旧值上增加了，其他人无法[覆盖/覆盖]它）来创建原子递增。

实际上，`GET` 和 `SET` 也可用于以非原子方式递增，因为每个客户端 `GET` 该值，递增，`SET` 回新值。
该递增在并发访问时不太安全，因为其他客户端可能同时执行相同操作，最终覆盖一方。

### Redis 脚本和事务

Redis 脚本是事务性的，因此你可以通过使用脚本实现 CAS 和其他效果。

## 链接

- [Redis](/docs/CS/DB/Redis/Redis.md)
