> [!NOTE]
> 源码事实基于 Netflix/eureka **v1.10.19**，分布在 `PeerAwareInstanceRegistryImpl`、`AbstractInstanceRegistry` 与 `com.netflix.eureka.util.MeasuredRate`。

## Introduction

自我保护（self preservation）是 Eureka 最能体现其 AP 取舍的机制：**当 Server 在短时间内收不到足够多的心跳时，它假定是自己的网络出了问题（而不是实例都挂了），于是停止剔除任何实例**，把注册表冻结在最后一刻的样子。Netflix 最初的触发场景是 AWS 上客户端与 Server 之间发生网络分区——此时实例其实都活着，如果不加保护，Server 会把整张注册表清空，恢复后所有服务都找不到对方。

代价写在源码注释里：进入自我保护后 Server 可能返回已经不存在的实例，因此 **Eureka 契约要求客户端必须能容忍这点**——快速超时并换下一台，而不是把一次失败当成服务问题。

## Threshold

保护的判定输入只有一个：最近一分钟收到的续约次数。

```java
// PeerAwareInstanceRegistryImpl
protected void updateRenewsPerMinThreshold() {
    this.numberOfRenewsPerMinThreshold = (int) (this.expectedNumberOfClientsSendingRenews
            * (60.0 / serverConfig.getExpectedClientRenewalIntervalSeconds())   // 60/30 = 2
            * serverConfig.getRenewalPercentThreshold());                        // 0.85
}
```

按默认值展开即 `threshold = 实例数 × 2 × 0.85 = 1.7 × 实例数`——每个实例每分钟期望续约 2 次，打 85 折作为下限。`expectedNumberOfClientsSendingRenews` 在以下时点变动：

- **启动** `openForTraffic()`：设成从邻居 `syncUp()` 搬来的实例数（若为 0 表示集群首次启动，为空集群）；
- **新注册**：`expectedNumberOfClientsSendingRenews + 1`（仅当当前 > 0 时，避免与 `syncUp` 重复计数）；
- **下线 / 剔除**：`internalCancel()` 里 `- 1`。

另外有一个 15 分钟的定时任务 `scheduleRenewalThresholdUpdateTask()`，它只在**当前实例数大于按阈值折算的期望值**、或自我保护被关闭时才更新阈值——防止在已经处于自我保护状态时把阈值越调越低、导致永久锁死。

## Decision

```java
// PeerAwareInstanceRegistryImpl
@Override
public boolean isLeaseExpirationEnabled() {
    if (!isSelfPreservationModeEnabled()) {
        // The self preservation mode is disabled, hence allowing the instances to expire.
        return true;
    }
    return numberOfRenewsPerMinThreshold > 0 && getNumOfRenewsInLastMin() > numberOfRenewsPerMinThreshold;
}
```

`AbstractInstanceRegistry#evict()` 一开始就调用它，返回 false 就整轮什么都不做。注意两个细节：

- `numberOfRenewsPerMinThreshold > 0` 意味着**空集群（expected 为 0）永远允许剔除**；
- 用于比较的 `getNumOfRenewsInLastMin()` 来自 `MeasuredRate`：它维护 `currentBucket` / `lastBucket` 两个 `AtomicLong`，每 60 秒执行一次 `lastBucket.set(currentBucket.getAndSet(0))`，即「上一分钟的完整计数」。因此自我保护从被触发到解除，**最快需要一分钟量级的观察窗口**。

```java
// com.netflix.eureka.util.MeasuredRate
public synchronized void start() {
    if (!isActive) {
        timer.schedule(new TimerTask() {
            @Override
            public void run() {
                try {
                    // Zero out the current bucket.
                    lastBucket.set(currentBucket.getAndSet(0));
                } catch (Throwable e) {
                    logger.error("Cannot reset the Measured Rate", e);
                }
            }
        }, sampleInterval, sampleInterval);
        isActive = true;
    }
}
```

## Symptoms

进入自我保护后 Dashboard 顶部会出现红字告警（源码注释里的原文）：

> EMERGENCY! EUREKA MAY BE INCORRECTLY CLAIMING INSTANCES ARE UP WHEN THEY'RE NOT. RENEWALS ARE LESSER THAN THRESHOLD AND HENCE THE INSTANCES ARE NOT BEING EXPIRED JUST TO BE SAFE.

同时能观察到：

- 实例列表里保留着已经停掉的实例，`Renews threshold` 与 `Renews (last min)` 两个数值前者明显更大；
- Server 日志周期性出现 `DS: lease expiration is currently disabled.`；
- 由于这些实例仍在返回给客户端，调用方会频繁遇到 connection refused / 超时——判断依据应该是「应用侧报错增加」而不是「Dashboard 是否干净」。

## When It Misfires

自我保护误伤最常见的三种场景，排障顺序参见 [troubleshooting](/docs/CS/Framework/eureka/troubleshooting.md)：

1. **实例总数太少**。例如只有 2 个实例，阈值 = `2 × 1.7 = 3.4` → 取整 3；任意实例重启一小会儿就可能跌破。这是开发/测试环境常见现象，也是很多人直接关掉它的原因。
2. **Server 重启/网络分区后注册表不完整**。`syncUp()` 没拿到数据 → `expected` 偏低，随后大量注册又把 `expected` 抬上去，但平移期间 `lastMin` 跟不上。
3. **续约间隔被改过**。把 `leaseRenewalIntervalInSeconds` 从 30s 调大（例如降到每 60s 一次）却没同步 `expectedClientRenewalIntervalSeconds`，公式仍按 30s 折算，阈值天然偏高。

## Operating Advice

- **开发/测试环境可以直接关**：`eureka.server.enable-self-preservation=false`，顺手把 `eviction-interval-timer-in-ms` 调到 5~10s 以加快清理。
- **生产环境保留开启**，但要配合两件事：关闭只读响应缓存（`use-read-only-response-cache=false`）以减少过期实例在视图中的停留时间；下游必须有超时重试与熔断（[Hystrix](/docs/CS/Framework/Spring_Cloud/Hystrix.md) 或 [Resilience4j](/docs/CS/Framework/Spring_Cloud/Resilience4j.md)），把它当作「调用可能失败」的普通情况处理。
- 集群扩容/缩容后若长时间停在保护态，检查 `Renews threshold` 是否回到合理值；必要时**重启 Server 让其重新 `syncUp()`**，不要靠调低 `renewalPercentThreshold` 掩盖问题。

## Links

- [Eureka](/docs/CS/Framework/eureka/Eureka.md)
- [Registry](/docs/CS/Framework/eureka/registry.md)
- [Cache](/docs/CS/Framework/eureka/cache.md)
- [Server](/docs/CS/Framework/eureka/Server.md)
- [Config](/docs/CS/Framework/eureka/config.md)
- [Troubleshooting](/docs/CS/Framework/eureka/troubleshooting.md)

## References

1. [Netflix/eureka · PeerAwareInstanceRegistryImpl](https://github.com/Netflix/eureka/blob/v1.10.19/eureka-core/src/main/java/com/netflix/eureka/registry/PeerAwareInstanceRegistryImpl.java)
2. [Netflix/eureka Wiki · Self Preservation](https://github.com/Netflix/eureka/wiki/Understanding-Eureka-Peer-to-Peer-Communication)
