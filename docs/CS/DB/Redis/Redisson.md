## Introduction




## Locks and synchronizers

Redisson 提供多种分布式锁类型。它们共享相同的 API 范式和看门狗行为，主要区别在于保证顺序、是否分发围栏令牌以及等待线程的通知方式。

| Lock type               | Reentrant | Fair / FIFO | Fencing token | Waiting mechanism | Typical use case                                             |
|:------------------------| :-------- | :---------- | :------------ | :---------------- | :----------------------------------------------------------- |
| Lock                    | ✔️         | ❌           | ❌             | Pub/sub           | General mutual exclusion                                     |
| Non-Reentrant Lock      | ❌         | ❌           | ❌             | Pub/sub           | Mutual exclusion where the same thread must not re-enter     |
| Fair Lock               | ✔️         | ✔️           | ❌             | Pub/sub           | Acquisition must follow request order (FIFO)                 |
| Non-Reentrant Fair Lock | ❌         | ✔️           | ❌             | Pub/sub           | FIFO ordering without reentrancy                             |
| MultiLock               | ✔️         | ❌           | ❌             | Pub/sub           | Lock several keys together as a single unit                  |
| ReadWriteLock)          | ✔️         | ❌           | ❌             | Pub/sub           | Many concurrent readers, one exclusive writer                |
| Spin Lock               | ✔️         | ❌           | ❌             | Backoff polling   | Very large numbers of locks, where one pub/sub subscription per lock is too costly |
| Fenced Lock             | ✔️         | ❌           | ✔️             | Pub/sub           | Guarding an external resource against a stale lock holder    |


分布式重入Lock对象，适用于Java，并实现了Lock接口。使用pub/sub通道通知所有Redisson实例中等待获取锁的其他线程。

如果Redisson实例获得锁崩溃，该锁定可能会永远挂在获得状态。
为避免这种情况，Redisson 维护锁的看门狗，延长锁的到期时间，而锁持有者 Redisson 实例仍在。
默认情况下，锁的看门狗超时是30秒，可以通过Config.lockWatchdog超时设置更改。

leaseTime锁定获取过程中可以定义参数。在指定时间区间后，锁定锁会自动解除。

```java
RLock lock = redisson.getLock("myLock");

// traditional lock method
lock.lock();

// or acquire lock and automatically unlock it after 10 seconds
lock.lock(10, TimeUnit.SECONDS);

// or wait for lock acquisition up to 100 seconds and auto-unlock after 10 seconds
boolean res = lock.tryLock(100, 10, TimeUnit.SECONDS);
if (res) {
    try {
        // ...
    } finally {
        lock.unlock();
    }
}
```



## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)