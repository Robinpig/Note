## Introduction

流量控制是 Sentinel 最核心的能力，由链上的 `FlowSlot` 执行。它基于前面 Slot 收集到的实时统计（[Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)、[统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)），用预设的 `FlowRule` 决定请求是否放行。`SphU.entry()` 触发规则时会抛出 `FlowException`（继承自 `BlockException`），可 catch 后自定义降级逻辑。

`FlowSlot` 会遍历该资源的所有流控规则，直到某条命中或全部通过。一条规则由以下要素组合：

- `resource`：资源名。
- `count`：阈值。
- `grade`：阈值类型——`QPS` 或 `并发线程数`（THREAD）。
- `strategy`：基于调用链关系的流控策略（见下文）。
- `controlBehavior`：流控效果（直接拒绝 / 预热 / 排队等待 / 预热+排队）。
- `limitApp`：针对的调用来源（配合 `strategy` 按调用方限流）。

## 流控维度：QPS vs 并发线程数

`grade` 决定按 **QPS** 还是 **并发线程数** 限流：

- **并发线程数**：保护线程不被长时间占用。某资源 RT 越长，占用线程越多；超出阈值直接拒绝。它是轻量级的「信号量隔离」，比线程池隔离省去上下文切换开销。
- **QPS**：每秒请求数超阈值时，按 `controlBehavior` 处理。

查看实时统计：`curl http://localhost:8719/tree?type=root`，字段含 `thread / pass / blocked / success / rt / total / 1m-pass / 1m-block / exception`。

## 流控模式（strategy）

基于调用链路（`NodeSelectorSlot` 建树、`ClusterBuilderSlot` 收集来源）有三种关系维度：

| strategy | 含义 | 关键字段 |
| :--- | :--- | :--- |
| 直接（直接关联资源自身） | 资源自身统计超阈值即限流 | `limitApp=default` |
| 关联（RELATE） | 当**关联资源** B 的流量超标时，限制资源 A。适合「读写互斥」场景，如 A 读库、B 写库，B 繁忙时限制 A | `refResource = B` |
| 链路（CHAIN / 入口） | 仅当从指定入口资源调用时才限流，实现「不同入口区别对待同一资源」 | `refResource = 入口名` |

`limitApp` 进一步按调用来源细分：

- `default`：不区分调用方，资源总流量超阈值即拦截。
- `<origin>`：仅指定调用方超阈值时拦截（来源由 `ContextUtil.enter(name, origin)` 指定）。
- `other`：除已显式配置的调用方之外的其它来源。

## 流控效果（controlBehavior）与流量整形控制器

`controlBehavior` 决定了「超阈值后怎么办」，对应四种 `TrafficShapingController` 实现：

| controlBehavior | 控制器 | 算法 | 行为 |
| :--- | :--- | :--- | :--- |
| `CONTROL_BEHAVIOR_DEFAULT` | `DefaultController` | 计数器 | 立即拒绝，抛 `FlowException`（默认） |
| `CONTROL_BEHAVIOR_WARM_UP` | `WarmUpController` | 令牌桶（Guava 思路） | 冷启动预热，逐步提升到阈值 |
| `CONTROL_BEHAVIOR_RATE_LIMITER` | `RateLimiterController` | 漏桶 | 匀速排队，严格间隔放行 |
| `CONTROL_BEHAVIOR_WARM_UP_RATE_LIMITER` | `WarmUpRateLimiterController` | 令牌桶 + 漏桶 | 预热 + 匀速排队 |

### RateLimiterController（排队等待 / 漏桶）

严格控制系统处理请求的间隔，让请求以**均匀速率**通过；突发流量不被直接拒绝，而是排队等待，超时（`maxQueueingTimeMs`）则拒绝。本质是漏桶算法。

```java
public class RateLimiterController implements TrafficShapingController {
    private final int maxQueueingTimeMs;
    private final double count;                 // 阈值 QPS
    private final AtomicLong latestPassedTime = new AtomicLong(-1);

    @Override
    public boolean canPass(Node node, int acquireCount, boolean prioritized) {
        if (acquireCount <= 0) return true;
        if (count <= 0) return false;           // 否则 costTime 会溢出
        long currentTime = TimeUtil.currentTimeMillis();
        long costTime = Math.round(1.0 * acquireCount / count * 1000); // 两次请求间理论间隔
        long expectedTime = costTime + latestPassedTime.get();
        if (expectedTime <= currentTime) {
            latestPassedTime.set(currentTime);
            return true;
        }
        long waitTime = costTime + latestPassedTime.get() - TimeUtil.currentTimeMillis();
        if (waitTime > maxQueueingTimeMs) {
            return false;                        // 排队超过上限，拒绝
        }
        long oldTime = latestPassedTime.addAndGet(costTime);
        try {
            waitTime = oldTime - TimeUtil.currentTimeMillis();
            if (waitTime > maxQueueingTimeMs) {
                latestPassedTime.addAndGet(-costTime);
                return false;
            }
            if (waitTime > 0) {
                Thread.sleep(waitTime);          // 当前线程休眠排队
            }
            return true;
        } catch (InterruptedException e) { /* 被打断，视为不通过 */ }
        return false;
    }
}
```

> [!NOTE]
> 排队等待会让**业务线程休眠**，适合处理瞬时突发的消息削峰填谷（如秒杀下单），但不适合对延迟敏感的同步调用。1.8.7 起 `RateLimiterController` 被重构以提高准确性并支持 `maxQps > 1000`。

### WarmUpController（预热 / 令牌桶）

灵感来自 Guava，但 Guava 基于速率调整请求间隔（类似漏桶），Sentinel 更关注「每秒进入请求数」而不算间隔（类似令牌桶）。系统长时间低负载后突增流量可能被瞬间打垮，预热让系统逐步「热起来」再达到稳态阈值。

核心参数：`count`（稳态阈值）、`warmUpPeriodInSec`（预热时长）、`coldFactor`（冷因子，默认 3）。由 `warningToken` 与 `maxToken` 划分「警戒区」，令牌余量越少代表系统越冷，允许的 QPS 越低。

```java
public class WarmUpController implements TrafficShapingController {
    protected double count;
    private int coldFactor;
    protected int warningToken = 0;
    private int maxToken;
    protected double slope;
    protected AtomicLong storedTokens = new AtomicLong(0);
    protected AtomicLong lastFilledTime = new AtomicLong(0);

    private void construct(double count, int warmUpPeriodInSec, int coldFactor) {
        if (coldFactor <= 1) throw new IllegalArgumentException("Cold factor should be larger than 1");
        this.count = count;
        this.coldFactor = coldFactor;
        warningToken = (int)(warmUpPeriodInSec * count) / (coldFactor - 1);
        maxToken = warningToken + (int)(2 * warmUpPeriodInSec * count / (1.0 + coldFactor));
        slope = (coldFactor - 1.0) / count / (maxToken - warningToken);
    }

    @Override
    public boolean canPass(Node node, int acquireCount, boolean prioritized) {
        long passQps = (long) node.passQps();
        long previousQps = (long) node.previousPassQps();
        syncToken(previousQps);
        long restToken = storedTokens.get();
        if (restToken >= warningToken) {
            long aboveToken = restToken - warningToken;
            double warningQps = Math.nextUp(1.0 / (aboveToken * slope + 1.0 / count));
            return passQps + acquireCount <= warningQps;
        } else {
            return passQps + acquireCount <= count;
        }
    }

    // 每秒补充令牌；冷态慢补、热态按 count 补
    private long coolDownTokens(long currentTime, long passQps) {
        long oldValue = storedTokens.get();
        long newValue = oldValue;
        if (oldValue < warningToken) {
            newValue = (long)(oldValue + (currentTime - lastFilledTime.get()) * count / 1000);
        } else if (oldValue > warningToken) {
            if (passQps < (int)count / coldFactor) {
                newValue = (long)(oldValue + (currentTime - lastFilledTime.get()) * count / 1000);
            }
        }
        return Math.min(newValue, maxToken);
    }
}
```

### WarmUpRateLimiterController（预热 + 排队）

`WarmUpController` 与 `RateLimiterController` 的组合：冷启动阶段用令牌桶逐步抬升阈值，超过警戒线后切换为漏桶的匀速排队（`timeoutInMs` 控制最大排队时间）。

```java
public class WarmUpRateLimiterController extends WarmUpController {
    private final int timeoutInMs;
    private final AtomicLong latestPassedTime = new AtomicLong(-1);

    @Override
    public boolean canPass(Node node, int acquireCount, boolean prioritized) {
        long previousQps = (long) node.previousPassQps();
        syncToken(previousQps);
        long currentTime = TimeUtil.currentTimeMillis();
        long restToken = storedTokens.get();
        long costTime;
        if (restToken >= warningToken) {
            double warmingQps = Math.nextUp(1.0 / (restToken * slope + 1.0 / count));
            costTime = Math.round(1.0 * acquireCount / warmingQps * 1000);
        } else {
            costTime = Math.round(1.0 * acquireCount / count * 1000);
        }
        long expectedTime = costTime + latestPassedTime.get();
        if (expectedTime <= currentTime) {
            latestPassedTime.set(currentTime);
            return true;
        }
        long waitTime = costTime + latestPassedTime.get() - currentTime;
        if (waitTime > timeoutInMs) return false;
        long oldTime = latestPassedTime.addAndGet(costTime);
        try {
            waitTime = oldTime - TimeUtil.currentTimeMillis();
            if (waitTime > timeoutInMs) { latestPassedTime.addAndGet(-costTime); return false; }
            if (waitTime > 0) Thread.sleep(waitTime);
            return true;
        } catch (InterruptedException e) { }
        return false;
    }
}
```

## 热点参数限流

`ParamFlowSlot`（`@Spi(order = -4000)`）位于 `SystemSlot` 与 `FlowSlot` 之间，提供**参数级**的热点限流：对资源的某个热点参数（如商品 ID、用户 ID）单独设阈值，对热点参数限流、对普通参数放行。它复用 `FlowRule` 之外的 `ParamFlowRule`，由 `ParamFlowSlot` 在统计到热点参数维度后执行，是普通流控的精细化扩展。配置与原理见官方 [热点参数限流](https://sentinelguard.io/en-us/docs/parameter-flow-control.html)。

## Links

- [Sentinel 枢纽](/docs/CS/Framework/Sentinel/Sentinel.md)
- [架构与工作原理](/docs/CS/Framework/Sentinel/Architecture.md)
- [Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)
- [统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)
- [熔断降级 CircuitBreaker](/docs/CS/Framework/Sentinel/CircuitBreaker.md)

## References

1. [Flow Control (官方文档)](https://sentinelguard.io/en-us/docs/flow-control.html)
2. [Parameter Flow Control (热点参数限流)](https://sentinelguard.io/en-us/docs/parameter-flow-control.html)
