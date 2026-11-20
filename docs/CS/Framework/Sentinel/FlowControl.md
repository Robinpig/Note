## Introduction

流量控制是 Sentinel 最核心的能力，由链上的 `FlowSlot`（`@Spi(order = -2000)`）执行。它基于前面 Slot 收集到的实时统计（[Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)、[统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)），用预设的 `FlowRule` 决定请求是否放行；`SphU.entry()` 触发规则时抛出 `FlowException`（`BlockException` 子类），可 catch 后自定义降级逻辑。一条 `FlowRule` 由 `grade`（阈值类型）、`strategy`（调用关系维度）、`controlBehavior`（流控效果）三要素组合，外加 `count`（阈值）与 `limitApp`（调用来源）。

> 版本基线：Sentinel 1.8.10

## Rule Construction: RATE_LIMITER Now Maps to ThrottlingController

规则加载时，`FlowRuleUtil.buildFlowRuleMap()` 逐条调用 `generateRater(rule)` 生成流量整形控制器并 `rule.setRater(rater)`。**这是最容易与旧资料冲突的地方**：1.8.10 里 `CONTROL_BEHAVIOR_RATE_LIMITER` 映射的是 `ThrottlingController`，而不是旧版（1.x）的 `RateLimiterController`。源码 `sentinel-core/.../slots/block/flow/FlowRuleUtil.java`：

```java
private static TrafficShapingController generateRater(/*@Valid*/ FlowRule rule) {
    if (rule.getGrade() == RuleConstant.FLOW_GRADE_QPS) {
        switch (rule.getControlBehavior()) {
            case RuleConstant.CONTROL_BEHAVIOR_WARM_UP:
                return new WarmUpController(rule.getCount(), rule.getWarmUpPeriodSec(),
                        ColdFactorProperty.coldFactor);
            case RuleConstant.CONTROL_BEHAVIOR_RATE_LIMITER:
                return new ThrottlingController(rule.getMaxQueueingTimeMs(), rule.getCount());
            case RuleConstant.CONTROL_BEHAVIOR_WARM_UP_RATE_LIMITER:
                return new WarmUpRateLimiterController(rule.getCount(), rule.getWarmUpPeriodSec(),
                        rule.getMaxQueueingTimeMs(), ColdFactorProperty.coldFactor);
            case RuleConstant.CONTROL_BEHAVIOR_DEFAULT:
            default:
                // Default mode or unknown mode: default traffic shaping controller (fast-reject).
        }
    }
    return new DefaultController(rule.getCount(), rule.getGrade());
}
```

四种 `controlBehavior` 与控制器对应关系：

| controlBehavior | 控制器 | 思路 |
| :--- | :--- | :--- |
| `CONTROL_BEHAVIOR_DEFAULT` | `DefaultController` | 直接拒绝 / 并发数控制 |
| `CONTROL_BEHAVIOR_WARM_UP` | `WarmUpController` | 冷启动预热（令牌桶） |
| `CONTROL_BEHAVIOR_RATE_LIMITER` | `ThrottlingController` | 匀速排队（漏桶） |
| `CONTROL_BEHAVIOR_WARM_UP_RATE_LIMITER` | `WarmUpRateLimiterController` | 预热 + 匀速排队 |

注意 `DEFAULT` 与「线程数 grade」共用 `DefaultController`：只有 `grade == QPS` 时才按 `controlBehavior` 分支，线程数维度一律 fast-reject。`coldFactor` 取 `ColdFactorProperty.coldFactor`，其默认值来自 `SentinelConfig.DEFAULT_COLD_FACTOR = 3`。

## DefaultController (Fast Reject / Priority Occupying)

`DefaultController` 用 `avgUsedTokens` 按 `grade` 取当前用量：线程数维度取 `node.curThreadNum()`，QPS 维度取 `node.passQps()`。超阈值时默认直接拒绝；仅当请求 `prioritized == true` 且为 QPS 维度时，尝试 `node.tryOccupyNext` 预占未来时间片，成功则 `sleep(waitInMs)` 后抛 `PriorityWaitException` 表示「等一会儿会通过」。`sentinel-core/.../slots/block/flow/controller/DefaultController.java`：

```java
@Override
public boolean canPass(Node node, int acquireCount, boolean prioritized) {
    int curCount = avgUsedTokens(node);
    if (curCount + acquireCount > count) {
        if (prioritized && grade == RuleConstant.FLOW_GRADE_QPS) {
            long currentTime;
            long waitInMs;
            currentTime = TimeUtil.currentTimeMillis();
            waitInMs = node.tryOccupyNext(currentTime, acquireCount, count);
            if (waitInMs < OccupyTimeoutProperty.getOccupyTimeout()) {
                node.addWaitingRequest(currentTime + waitInMs, acquireCount);
                node.addOccupiedPass(acquireCount);
                sleep(waitInMs);

                // PriorityWaitException indicates that the request will pass after waiting for {@link @waitInMs}.
                throw new PriorityWaitException(waitInMs);
            }
        }
        return false;
    }
    return true;
}

private int avgUsedTokens(Node node) {
    if (node == null) {
        return DEFAULT_AVG_USED_TOKENS;
    }
    return grade == RuleConstant.FLOW_GRADE_THREAD ? node.curThreadNum() : (int)(node.passQps());
}
```

## ThrottlingController (Uniform Rate / Leaky Bucket)

旧笔记的 `RateLimiterController` 整段伪代码在 1.8.10 已失效。真实实现 `ThrottlingController`（`@since 2.0`，类注释明确写 `Refactored from legacy RateLimitController of Sentinel 1.x`）用 `latestPassedTime`（`AtomicLong`）记录上一次放行时刻，`costTime` 为两次请求的理论间隔。路径 `sentinel-core/.../slots/block/flow/controller/ThrottlingController.java`。

构造器判据决定走纳秒还是毫秒路径：`useNanoSeconds = statDurationMs % Math.round(maxCountPerStat) != 0 || maxCountPerStat / statDurationMs > 1`，即当统计周期不能被 QPS 整除、或 QPS 大于每秒 1 个时，用 `System.nanoTime()` 提高精度：

```java
public ThrottlingController(int queueingTimeoutMs, double maxCountPerStat) {
    this(queueingTimeoutMs, maxCountPerStat, 1000);
}

public ThrottlingController(int queueingTimeoutMs, double maxCountPerStat, int statDurationMs) {
    AssertUtil.assertTrue(statDurationMs > 0, "statDurationMs should be positive");
    AssertUtil.assertTrue(maxCountPerStat >= 0, "maxCountPerStat should be >= 0");
    AssertUtil.assertTrue(queueingTimeoutMs >= 0, "queueingTimeoutMs should be >= 0");
    this.maxQueueingTimeMs = queueingTimeoutMs;
    this.count = maxCountPerStat;
    this.statDurationMs = statDurationMs;
    // Use nanoSeconds when durationMs%count != 0 or count/durationMs> 1 (to be accurate)
    if (maxCountPerStat > 0) {
        this.useNanoSeconds = statDurationMs % Math.round(maxCountPerStat) != 0 || maxCountPerStat / statDurationMs > 1;
    } else {
        this.useNanoSeconds = false;
    }
}
```

`canPass` 只做前置校验（抢占数 ≤ 0 直接通过、阈值 ≤ 0 直接拒绝以防溢出），再按 `useNanoSeconds` 分派到两条路径：

```java
@Override
public boolean canPass(Node node, int acquireCount, boolean prioritized) {
    // Pass when acquire count is less or equal than 0.
    if (acquireCount <= 0) {
        return true;
    }
    // Reject when count is less or equal than 0.
    // Otherwise, the costTime will be max of long and waitTime will overflow in some cases.
    if (count <= 0) {
        return false;
    }
    if (useNanoSeconds) {
        return checkPassUsingNanoSeconds(acquireCount, this.count);
    } else {
        return checkPassUsingCachedMs(acquireCount, this.count);
    }
}
```

纳秒路径：`costTimeNs = round(1e6 * statDurationMs * acquireCount / maxCountPerStat)`，用 `latestPassedTime.addAndGet(costTimeNs)` 原子推进排队时刻，超出 `maxQueueingTimeNs` 则回滚并拒绝，等待用 `LockSupport.parkNanos`：

```java
private boolean checkPassUsingNanoSeconds(int acquireCount, double maxCountPerStat) {
    final long maxQueueingTimeNs = maxQueueingTimeMs * MS_TO_NS_OFFSET;
    long currentTime = System.nanoTime();
    // Calculate the interval between every two requests.
    final long costTimeNs = Math.round(1.0d * MS_TO_NS_OFFSET * statDurationMs * acquireCount / maxCountPerStat);

    // Expected pass time of this request.
    long expectedTime = costTimeNs + latestPassedTime.get();

    if (expectedTime <= currentTime) {
        // Contention may exist here, but it's okay.
        latestPassedTime.set(currentTime);
        return true;
    } else {
        final long curNanos = System.nanoTime();
        // Calculate the time to wait.
        long waitTime = costTimeNs + latestPassedTime.get() - curNanos;
        if (waitTime > maxQueueingTimeNs) {
            return false;
        }

        long oldTime = latestPassedTime.addAndGet(costTimeNs);
        waitTime = oldTime - curNanos;
        if (waitTime > maxQueueingTimeNs) {
            latestPassedTime.addAndGet(-costTimeNs);
            return false;
        }
        // in race condition waitTime may <= 0
        if (waitTime > 0) {
            sleepNanos(waitTime);
        }
        return true;
    }
}
```

毫秒路径用 `TimeUtil.currentTimeMillis()` 与 `costTime = round(statDurationMs * acquireCount / maxCountPerStat)`，等待用 `Thread.sleep`；逻辑与纳秒路径对称，同样带 `addAndGet` 回滚：

```java
private boolean checkPassUsingCachedMs(int acquireCount, double maxCountPerStat) {
    long currentTime = TimeUtil.currentTimeMillis();
    // Calculate the interval between every two requests.
    long costTime = Math.round(1.0d * statDurationMs * acquireCount / maxCountPerStat);

    // Expected pass time of this request.
    long expectedTime = costTime + latestPassedTime.get();

    if (expectedTime <= currentTime) {
        // Contention may exist here, but it's okay.
        latestPassedTime.set(currentTime);
        return true;
    } else {
        // Calculate the time to wait.
        long waitTime = costTime + latestPassedTime.get() - TimeUtil.currentTimeMillis();
        if (waitTime > maxQueueingTimeMs) {
            return false;
        }

        long oldTime = latestPassedTime.addAndGet(costTime);
        waitTime = oldTime - TimeUtil.currentTimeMillis();
        if (waitTime > maxQueueingTimeMs) {
            latestPassedTime.addAndGet(-costTime);
            return false;
        }
        // in race condition waitTime may <= 0
        if (waitTime > 0) {
            sleepMs(waitTime);
        }
        return true;
    }
}
```

排队等待会让**业务线程休眠**（纳秒路径 `LockSupport.parkNanos`、毫秒路径 `Thread.sleep`），适合瞬时突发的削峰填谷（如秒杀下单），不适合延迟敏感的同步调用。`maxQueueingTimeMs` 默认 500（见 `FlowRule.java`）。

## WarmUpController (Token Bucket Warm-up)

预热思路来自 Guava，但 Sentinel 关注「每秒进入请求数」而非请求间隔（更像令牌桶）。长时间低负载后突增流量可能瞬间打垮系统，预热让 QPS 从冷态逐步爬升到稳态 `count`。核心是 `warningToken` / `maxToken` / `slope` 三个量：`coldFactor` 默认 3（须 > 1），`warningToken = warmUpPeriodInSec*count/(coldFactor-1)`，`maxToken = warningToken + 2*warmUpPeriodInSec*count/(1+coldFactor)`，`slope = (coldFactor-1)/count/(maxToken-warningToken)`。路径 `sentinel-core/.../slots/block/flow/controller/WarmUpController.java`：

```java
private void construct(double count, int warmUpPeriodInSec, int coldFactor) {

    if (coldFactor <= 1) {
        throw new IllegalArgumentException("Cold factor should be larger than 1");
    }

    this.count = count;

    this.coldFactor = coldFactor;

    // thresholdPermits = 0.5 * warmupPeriod / stableInterval.
    // warningToken = 100;
    warningToken = (int)(warmUpPeriodInSec * count) / (coldFactor - 1);
    // / maxPermits = thresholdPermits + 2 * warmupPeriod /
    // (stableInterval + coldInterval)
    // maxToken = 200
    maxToken = warningToken + (int)(2 * warmUpPeriodInSec * count / (1.0 + coldFactor));

    // slope
    // slope = (coldIntervalMicros - stableIntervalMicros) / (maxPermits
    // - thresholdPermits);
    slope = (coldFactor - 1.0) / count / (maxToken - warningToken);

}
```

`canPass` 先用 `previousPassQps` 同步令牌（`syncToken`），余量 ≥ `warningToken` 时进入「警戒区」，按线性公式压低允许的 `warningQps`；否则按稳态 `count` 放行：

```java
@Override
public boolean canPass(Node node, int acquireCount, boolean prioritized) {
    long passQps = (long) node.passQps();

    long previousQps = (long) node.previousPassQps();
    syncToken(previousQps);

    // 开始计算它的斜率
    // 如果进入了警戒线，开始调整他的qps
    long restToken = storedTokens.get();
    if (restToken >= warningToken) {
        long aboveToken = restToken - warningToken;
        // 消耗的速度要比warning快，但是要比慢
        // current interval = restToken*slope+1/count
        double warningQps = Math.nextUp(1.0 / (aboveToken * slope + 1.0 / count));
        if (passQps + acquireCount <= warningQps) {
            return true;
        }
    } else {
        if (passQps + acquireCount <= count) {
            return true;
        }
    }

    return false;
}
```

令牌每秒补充（`syncToken` 按整秒对齐），余量低于警戒线、或余量高于警戒线但 `passQps < count/coldFactor` 时补充，上限 `maxToken`。

## WarmUpRateLimiterController (Warm-up + Queueing)

它继承 `WarmUpController`，把预热期的限流值 `warmingQps` 换算成 `costTime`，再复用漏桶式的 `latestPassedTime` 排队（`timeoutInMs` 即 `maxQueueingTimeMs`）。路径 `sentinel-core/.../slots/block/flow/controller/WarmUpRateLimiterController.java`：

```java
@Override
public boolean canPass(Node node, int acquireCount, boolean prioritized) {
    long previousQps = (long) node.previousPassQps();
    syncToken(previousQps);

    long currentTime = TimeUtil.currentTimeMillis();

    long restToken = storedTokens.get();
    long costTime = 0;
    long expectedTime = 0;
    if (restToken >= warningToken) {
        long aboveToken = restToken - warningToken;

        // current interval = restToken*slope+1/count
        double warmingQps = Math.nextUp(1.0 / (aboveToken * slope + 1.0 / count));
        costTime = Math.round(1.0 * (acquireCount) / warmingQps * 1000);
    } else {
        costTime = Math.round(1.0 * (acquireCount) / count * 1000);
    }
    expectedTime = costTime + latestPassedTime.get();

    if (expectedTime <= currentTime) {
        latestPassedTime.set(currentTime);
        return true;
    } else {
        long waitTime = costTime + latestPassedTime.get() - currentTime;
        if (waitTime > timeoutInMs) {
            return false;
        } else {
            long oldTime = latestPassedTime.addAndGet(costTime);
            try {
                waitTime = oldTime - TimeUtil.currentTimeMillis();
                if (waitTime > timeoutInMs) {
                    latestPassedTime.addAndGet(-costTime);
                    return false;
                }
                if (waitTime > 0) {
                    Thread.sleep(waitTime);
                }
                return true;
            } catch (InterruptedException e) {
            }
        }
    }
    return false;
}
```

## Rule Checking: FlowRuleChecker

`FlowSlot.entry()` 调 `checker.checkFlow(...)`，遍历资源的所有规则，任一不通过即抛 `FlowException`。`canPassCheck()` 是分流枢纽：`limitApp == null` 直接放行；集群模式走 `passClusterCheck`；否则 `passLocalCheck`。路径 `sentinel-core/.../slots/block/flow/FlowRuleChecker.java`：

```java
public void checkFlow(Function<String, Collection<FlowRule>> ruleProvider, ResourceWrapper resource,
                      Context context, DefaultNode node, int count, boolean prioritized) throws BlockException {
    if (ruleProvider == null || resource == null) {
        return;
    }
    Collection<FlowRule> rules = ruleProvider.apply(resource.getName());
    if (rules != null) {
        for (FlowRule rule : rules) {
            if (!canPassCheck(rule, context, node, count, prioritized)) {
                throw new FlowException(rule.getLimitApp(), rule);
            }
        }
    }
}

public boolean canPassCheck(/*@NonNull*/ FlowRule rule, Context context, DefaultNode node, int acquireCount,
                                                    boolean prioritized) {
    String limitApp = rule.getLimitApp();
    if (limitApp == null) {
        return true;
    }

    if (rule.isClusterMode()) {
        return passClusterCheck(rule, context, node, acquireCount, prioritized);
    }

    return passLocalCheck(rule, context, node, acquireCount, prioritized);
}
```

本地检查先由 `selectNodeByRequesterAndStrategy` 选出「统计哪个 Node」，选不到就放行；选到则交给 `rule.getRater().canPass()` 做最终的控制器判定：

```java
private static boolean passLocalCheck(FlowRule rule, Context context, DefaultNode node, int acquireCount,
                                      boolean prioritized) {
    Node selectedNode = selectNodeByRequesterAndStrategy(rule, context, node);
    if (selectedNode == null) {
        return true;
    }

    return rule.getRater().canPass(selectedNode, acquireCount, prioritized);
}
```

`limitApp` 三种匹配 + `strategy` 三种策略在 `selectNodeByRequesterAndStrategy` 里组合：

- **精确 origin**（`limitApp.equals(origin)` 且 origin 非 `default`/`other`）：DIRECT 取 `context.getOriginNode()`，否则走关联节点。
- **default**：不区分调用方，DIRECT 取 `node.getClusterNode()`（资源总流量），否则走关联节点。
- **other**：仅当 `FlowRuleManager.isOtherOrigin(...)` 为真（该 origin 未在其它规则显式配置）时，DIRECT 取 originNode，否则走关联节点。

`strategy` 的关联/链路由 `selectReferenceNode` 决定：RELATE 取 `ClusterBuilderSlot.getClusterNode(refResource)`（关联资源 B 的 clusterNode）；CHAIN 要求 `refResource.equals(context.getName())`（入口匹配）才返回当前 node；DIRECT 不在此处理。

```java
static Node selectNodeByRequesterAndStrategy(/*@NonNull*/ FlowRule rule, Context context, DefaultNode node) {
    // The limit app should not be empty.
    String limitApp = rule.getLimitApp();
    int strategy = rule.getStrategy();
    String origin = context.getOrigin();

    if (limitApp.equals(origin) && filterOrigin(origin)) {
        if (strategy == RuleConstant.STRATEGY_DIRECT) {
            // Matches limit origin, return origin statistic node.
            return context.getOriginNode();
        }

        return selectReferenceNode(rule, context, node);
    } else if (RuleConstant.LIMIT_APP_DEFAULT.equals(limitApp)) {
        if (strategy == RuleConstant.STRATEGY_DIRECT) {
            // Return the cluster node.
            return node.getClusterNode();
        }

        return selectReferenceNode(rule, context, node);
    } else if (RuleConstant.LIMIT_APP_OTHER.equals(limitApp)
        && FlowRuleManager.isOtherOrigin(origin, rule.getResource())) {
        if (strategy == RuleConstant.STRATEGY_DIRECT) {
            return context.getOriginNode();
        }

        return selectReferenceNode(rule, context, node);
    }

    return null;
}
```

## Cluster Flow Check

集群模式先 `pickClusterService()` 取 `TokenService`（客户端取 `TokenClientProvider`、服务端取内嵌 `EmbeddedClusterTokenServerProvider`），拿不到或请求异常就 `fallbackToLocalOrPass`；TokenResult 按状态处理：OK 放行、SHOULD_WAIT 则 `Thread.sleep(waitInMs)`、FAIL 类走本地回退、BLOCKED 直接拒绝。详见 [集群流控](/docs/CS/Framework/Sentinel/ClusterFlow.md)。

```java
private static boolean passClusterCheck(FlowRule rule, Context context, DefaultNode node, int acquireCount,
                                        boolean prioritized) {
    try {
        TokenService clusterService = pickClusterService();
        if (clusterService == null) {
            return fallbackToLocalOrPass(rule, context, node, acquireCount, prioritized);
        }
        long flowId = rule.getClusterConfig().getFlowId();
        TokenResult result = clusterService.requestToken(flowId, acquireCount, prioritized);
        return applyTokenResult(result, rule, context, node, acquireCount, prioritized);
        // If client is absent, then fallback to local mode.
    } catch (Throwable ex) {
        RecordLog.warn("[FlowRuleChecker] Request cluster token unexpected failed", ex);
    }
    // Fallback to local flow control when token client or server for this rule is not available.
    // If fallback is not enabled, then directly pass.
    return fallbackToLocalOrPass(rule, context, node, acquireCount, prioritized);
}

private static boolean fallbackToLocalOrPass(FlowRule rule, Context context, DefaultNode node, int acquireCount,
                                             boolean prioritized) {
    if (rule.getClusterConfig().isFallbackToLocalWhenFail()) {
        return passLocalCheck(rule, context, node, acquireCount, prioritized);
    } else {
        // The rule won't be activated, just pass.
        return true;
    }
}
```

## Parameter Flow Control (Hotspot)

热点参数限流由 `ParamFlowSlot`（`@Spi(order = -3000)`）实现，位于 `SystemSlot` 与 `FlowSlot` 之间。它**不在 core 默认链里**，而在 `sentinel-extension/sentinel-parameter-flow-control` 模块，靠 SPI 被发现、需引入依赖才生效。它复用 `ParamFlowRule` 而非 `FlowRule`，`entry()` 里 `checkFlow` 按参数索引（`paramIdx`，支持负数倒数）统计热点参数维度，未通过则抛 `ParamFlowException`。配置与原理见官方[热点参数限流](https://sentinelguard.io/en-us/docs/parameter-flow-control.html)。

## Links

- [Sentinel 枢纽](/docs/CS/Framework/Sentinel/Sentinel.md)
- [架构与工作原理](/docs/CS/Framework/Sentinel/Sentinel.md?id=architecture)
- [Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)
- [统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)
- [熔断降级 CircuitBreaker](/docs/CS/Framework/Sentinel/CircuitBreaker.md)
- [集群流控 ClusterFlow](/docs/CS/Framework/Sentinel/ClusterFlow.md)

## References

- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/block/flow/FlowRuleUtil.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/block/flow/controller/ThrottlingController.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/block/flow/FlowRuleChecker.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-extension/sentinel-parameter-flow-control/src/main/java/com/alibaba/csp/sentinel/slots/block/flow/param/ParamFlowSlot.java>
- <https://sentinelguard.io/en-us/docs/flow-control.html>
