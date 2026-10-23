> [!NOTE]
> 源码事实基于 Netflix/eureka **v1.10.19**，路径为 `eureka-core/src/main/java/com/netflix/eureka/registry/`。这是整个 Eureka Server 的写路径与过期逻辑所在处。

## Introduction

Server 的注册表由两个类协同：`AbstractInstanceRegistry` 持有真实数据并负责 register / renew / cancel / statusUpdate / evict 的全部本地逻辑；`PeerAwareInstanceRegistryImpl` 加一层 peer 转发、启动同步（`syncUp`）与自我保护阈值，并把事件[复制到其它节点](/docs/CS/Framework/eureka/replication.md)。所有对注册表的写都会同时做三件事：写 `registry`、进 `recentlyChangedQueue`（供客户端拉增量）、`invalidateCache`（失效[响应缓存](/docs/CS/Framework/eureka/cache.md)）。

## Data Structure

核心字段（`registry/AbstractInstanceRegistry.java`）：

| 字段                                | 类型 / 默认                                                        | 作用                                                          |
| :-------------------------------- | :------------------------------------------------------------- | :---------------------------------------------------------- |
| `registry`                        | `ConcurrentHashMap<String, Map<String, Lease<InstanceInfo>>>`     | 外层 `appName`、内层 `instanceId`；内层 map 用 `putIfAbsent` 惰性创建 |
| `overriddenInstanceStatusMap`      | Guava cache，`initialCapacity(500)` + `expireAfterAccess(1h)`     | 保存人工覆盖的状态（如 `OUT_OF_SERVICE`）                                  |
| `recentlyChangedQueue`            | `ConcurrentLinkedQueue<RecentlyChangedItem>`（无界，靠定时任务清理）         | 增量拉取的数据源，条目保留 `retentionTimeInMSInDeltaQueue`（3 分钟）      |
| `recentRegisteredQueue` / `recentCanceledQueue` | `CircularQueue<Pair<Long,String>>`，**字面量容量 1000**（无常量名）   | 仅用于 Dashboard 展示最近注册/下线，委托 `ArrayBlockingQueue` 并重写 `offer`（满则 poll 后再入队） |
| `readWriteLock` / `read` / `write` | `ReentrantReadWriteLock`                                        | 保护整张 registry 的写；另有独立的 `lock` Object 只保护 `expectedNumberOfClientsSendingRenews` |
| `renewsLastMin`                   | `MeasuredRate(1000 * 60 * 1)`                                    | 一分钟滑动窗口的实际续约计数，自我保护的唯一输入                                    |
| `deltaRetentionTimer` / `evictionTimer` | daemon `Timer`，后台线程名 `Eureka-DeltaRetentionTimer` / `Eureka-EvictionTimer` | delta 清理周期 30s；剔除任务周期 `evictionIntervalTimerInMs`（60s），在 `postInit()` 里 schedule |

注意 `recentRegisteredQueue` / `recentCanceledQueue` **不是** `[ArrayBlockingQueue](/docs/CS/Java/JDK/Collection/Queue.md?id=arrayblockingqueue)` 本体，而是一个装饰类：`offer` 失败时先 `poll()` 再重试，从而在满 1000 后覆盖最旧记录。

## Lease

租约是 Eureka 的健康模型：客户端每 30s 续约一次，Server 只在租约过期后才剔除。

```java
// registry/lease/Lease.java
public class Lease<T> {
    private static final int DEFAULT_DURATION_IN_SECS = 90 * 1;

    public void renew() {
        lastUpdateTimestamp = System.currentTimeMillis() + duration;
    }

    /**
     * Note that due to renew() doing the 'wrong" thing and setting lastUpdateTimestamp to +duration more than
     * what it should be, the expiry will actually be 2 * duration. This is a minor bug and should only affect
     * instances that ungracefully shutdown. Due to possible wide ranging impact to existing usage, this will
     * not be fixed.
     */
    public boolean isExpired(long additionalLeaseMs) {
        return (evictionTimestamp > 0 || System.currentTimeMillis() > (lastUpdateTimestamp + duration + additionalLeaseMs));
    }
}
```

> [!WARNING]
> `renew()` 把过期时间写成 `now + duration` 而 `isExpired()` 又追加了一个 `duration`，**实际过期窗口是 `2 * duration`（默认 180 秒）**。源码注释明确承认这是 bug 且为兼容性不修。它只影响「非优雅退出 + 未发送 cancel」的实例——优雅下发的 DELETE 会立刻生效。推导感知时延时必须用 180s 而不是 90s，见 [cache](/docs/CS/Framework/eureka/cache.md?id=感知时延的完整推导)。

## Register

`AbstractInstanceRegistry#register(InstanceInfo, int leaseDuration, boolean isReplication)` 全流程在 `read` 锁内：

1. **惰性创建内层 map**：`registry.putIfAbsent(appName, new ConcurrentHashMap<>())`。
2. **已存在 lease 的取舍**：比较 `lastDirtyTimestamp`，只有 `existing > incoming` 时才沿用旧的 holder；时间戳相等时**取新传入的**（源码注释：宁可信任远端传来的 InstanceInfo）。
3. **新注册提升计数**：`synchronized (lock)` 内若 `expectedNumberOfClientsSendingRenews > 0` 则 +1 并 `updateRenewsPerMinThreshold()`——注意**首次启动阶段该值为 0 时不计数**，避免把 `syncUp()` 搬来的实例重复计入。
4. **overridden status 转移**：若注册报文带了 `overriddenStatus != UNKNOWN` 且 map 中没有该 id，则写入；随后用 map 中的值回写 registrant。
5. **最终状态计算**：`getOverriddenInstanceStatus(registrant, existingLease, isReplication)` → `setStatusWithoutDirty(...)`；状态为 `UP` 时 `lease.serviceUp()`。
6. **进增量 + 失效缓存**：`ActionType.ADDED`，`recentlyChangedQueue.add(...)`，最后 `invalidateCache(appName, vip, svip)`。

第 5 步的规则链（`PeerAwareInstanceRegistryImpl` 构造器中装配）是「谁说了算」的关键：

```java
this.instanceStatusOverrideRule = new FirstMatchWinsCompositeRule(new InstanceStatusOverrideRule[]{
        new DownOrStartingRule(),
        new OverrideExistsRule(this.overriddenInstanceStatusMap),
        new LeaseExistsRule()
});
```

优先级：**DOWN / STARTING 永不覆盖 > 人工 override > 实例自己上报的状态**，兜底 `AlwaysMatchInstanceStatusRule`。

## Renew

`renew(appName, id, isReplication)` 只有两处返回 `false`，都是「需要客户端重新注册」的信号：

- `leaseToRenew == null`：Server 上根本没有这个实例（常见于 Server 重启后注册表被清空、或剔除任务已把该实例清掉）；
- `getOverriddenInstanceStatus(...) == UNKNOWN`：实例存在但状态被判为未知（如 override 被删除）。

命中后 `InstanceResource` 返回 404，客户端据此就地重新注册，见 [Client](/docs/CS/Framework/eureka/Client.md?id=续约与重注册)。成功路径先 `renewsLastMin.increment()`（喂给[自我保护](/docs/CS/Framework/eureka/self_preservation.md)）再 `leaseToRenew.renew()`；若现行状态与规则算出的 override 状态不一致，会就地把状态改写回去。

## Cancel

`cancel()` 直接转发 `internalCancel(appName, id, isReplication)`，后者是 register 的逆操作：

- `gMap.remove(instanceId)` 拿不到 lease → `CANCEL_NOT_FOUND.increment()` 并返回 false；
- 取到则 `lease.cancel()`、`recentCanceledQueue.add(...)`、`overriddenInstanceStatusMap.remove(id)`、`ActionType.DELETED` 进增量、`invalidateCache(...)`；
- 最后在 `synchronized (lock)` 中**递减** `expectedNumberOfClientsSendingRenews` 并重算阈值。

因为下线是主动 DELETE，它不受租约到期影响——这是「优雅下线比 kill -9 快得多」的根本原因（差 3 分钟级别），详见 [troubleshooting](/docs/CS/Framework/eureka/troubleshooting.md)。

## Status Update

`statusUpdate(appName, id, newStatus, lastDirtyTimestamp, isReplication)`：唯一返回 false 的场景是 lease 不存在；其余情况都会 `lease.renew()`（状态变更视作一次续约）、写入 override map、`UP` 时 `serviceUp()`、状态确实变化才产生 `MODIFIED` 增量。`deleteStatusOverride(...)` 会移除 override 并把状态回落到实例自报值；若 map 中本来就没有记录则**不改状态**。这也是上面 `renew()` 返回 `UNKNOWN` 的来源链路：[replication](/docs/CS/Framework/eureka/replication.md) 复制这两个动作时，`statusUpdate` 传 `newStatus`，而 `deleteStatusOverride` 传 `null`。

## Delta 队列

```java
private TimerTask getDeltaRetentionTask() {
    return new TimerTask() {
        @Override
        public void run() {
            Iterator<RecentlyChangedItem> it = recentlyChangedQueue.iterator();
            while (it.hasNext()) {
                if (it.next().getLastUpdateTime() <
                        System.currentTimeMillis() - serverConfig.getRetentionTimeInMSInDeltaQueue()) {
                    it.remove();
                } else {
                    break;   // 队列按时间有序，遇到未过期即停止
                }
            }
        }
    };
}
```

该任务在**构造器**里就完成 schedule（周期 `deltaRetentionTimerIntervalMs` = 30s），条目保留 3 分钟。这意味着：**客户端断线休息超过 3 分钟后再拉增量，会丢中间变更**——补偿机制是客户端用 `appsHashCode` 校验增量结果，不一致就退化为全量拉取，见 [Client](/docs/CS/Framework/eureka/Client.md?id=增量拉取与-reconcile)。

## Eviction

剔除任务由 `AbstractInstanceRegistry#postInit()` 启动，周期 `evictionIntervalTimerInMs` = 60s。它先算 compensation time 以抵消 GC 停顿或时钟漂移造成的延迟：

```java
long getCompensationTimeMs() {
    long currNanos = getCurrentTimeNano();
    long lastNanos = lastExecutionNanosRef.getAndSet(currNanos);
    if (lastNanos == 0l) {
        return 0l;
    }
    long elapsedMs = TimeUnit.NANOSECONDS.toMillis(currNanos - lastNanos);
    long compensationTime = elapsedMs - serverConfig.getEvictionIntervalTimerInMs();
    return compensationTime <= 0l ? 0l : compensationTime;
}
```

随后 `evict(additionalLeaseMs)` 的行为：

1. `isLeaseExpirationEnabled()` 为 false（即处于[自我保护](/docs/CS/Framework/eureka/self_preservation.md)）**直接 return，一个实例都不剔除**；
2. 遍历整张 registry 收集所有 `lease.isExpired(additionalLeaseMs)` 的租约；
3. 用当前注册表规模算出「最多能剔多少」：`registrySizeThreshold = registrySize * renewalPercentThreshold(0.85)`，`evictionLimit = registrySize - registrySizeThreshold`；`toEvict = min(过期数, evictionLimit)`；
4. 用 Knuth shuffle 随机挑 `toEvict` 个执行 `internalCancel(appName, id, false)`。

第 3 步常被误读为「一次最多剔 15%」——准确说法是**注册表里至少保住 85% 的实例**，即单轮最多剔除当前规模的 15%；第 4 步的随机化是为了避免按 map 顺序剔除时把某个应用的实例「整锅端掉」（源码注释原文：`we might wipe out whole apps before self preservation kicks in`）。

## Links

- [Eureka](/docs/CS/Framework/eureka/Eureka.md)
- [Cache](/docs/CS/Framework/eureka/cache.md)
- [Self Preservation](/docs/CS/Framework/eureka/self_preservation.md)
- [Replication](/docs/CS/Framework/eureka/replication.md)
- [Server](/docs/CS/Framework/eureka/Server.md)
- [Troubleshooting](/docs/CS/Framework/eureka/troubleshooting.md)

## References

1. [Netflix/eureka · AbstractInstanceRegistry](https://github.com/Netflix/eureka/blob/v1.10.19/eureka-core/src/main/java/com/netflix/eureka/registry/AbstractInstanceRegistry.java)
2. [Netflix/eureka · Lease](https://github.com/Netflix/eureka/blob/v1.10.19/eureka-core/src/main/java/com/netflix/eureka/lease/Lease.java)
