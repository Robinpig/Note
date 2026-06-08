## Introduction

在 Redis 中，分布式锁是一种用于协调分布式系统中多个进程或线程访问共享资源的机制。
Redis 分布式锁的核心原理是使用 SETNX（SET if Not eXists）命令在 Redis 中创建一个键来表示锁，其他进程或线程在尝试获取锁时，也会使用 SETNX 命令，如果返回值是 1，则表示获取锁成功；如果返回值是 0，则表示锁已经被其他进程或线程持有。

### 使用

```shell
redis 127.0.0.1:6379> SETNX lock "locked"
(integer) 1  # 获取锁成功

redis 127.0.0.1:6379> SETNX lock "locked"
(integer) 0  # 获取锁失败
```

### Redlock

Redlock 是 Redis 官方提供的一种分布式锁算法，它使用多个 Redis 实例来实现锁的高可用。

Redlock 算法的核心思想是：在多个 Redis 实例上同时获取锁，只有当超过半数的实例返回成功时，才认为锁获取成功。
这样可以避免单点故障导致的锁失效问题。

### Lua 脚本

使用 Lua 脚本实现分布式锁，可以减少网络通信次数，提高性能和原子性。

```lua
-- 获取锁的 Lua 脚本
local key = KEYS[1]
local value = ARGV[1]
local ttl = ARGV[2]
local result = redis.call('SET', key, value, 'NX', 'PX', ttl)
return result
```

## 配置

```ini
# 锁超时时间
lock_timeout=10000
# 锁重试次数
lock_retry_count=3
```

## 链接

- [Redis](/docs/CS/DB/Redis/Redis.md)
