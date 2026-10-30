## Introduction

在 Dubbo 的集群调用流程中，LoadBalance 的执行时机是在 Directory 获取全部 Invoker 和 Router 路由过滤之后，作为最后一环完成服务实例的最终选择。

关于它有三个流传很广但都不准确的说法：

1. **「Dubbo 有 6 个负载均衡策略」**——3.3.6 有 **7 个**。第7 个是 `AdaptiveLoadBalance`（扩展名 `adaptive`），它在 `ApplicationModel` 里取 `AdaptiveMetrics` bean，按 **P2C（Power of Two Choices）** 算法挑节点，并把负载信息写回 attachment 供服务端上报使用。
2. **「`ShortestResponseLoadBalance` 是个空壳 / 用的是全量累计平均耗时」**——都不对。3.3.6 里它 `implements ScopeModelAware`，用**滑动窗口**（`SlideWindowData`）统计最近一个周期内的成功调用平均耗时，默认窗口 30s，且估算公式里的活跃数是 **`active + 1`** 而不是 `active`。算法改动的动机就是解决 2.x「老样本长期不变、节点劣化后无法被淘汰」的问题。
3. **「SPI 文件在 `...cluster.loadbalance.LoadBalance`」**——**该路径不存在**。SPI 文件名按**接口 FQN** 命名，而接口在 `org.apache.dubbo.rpc.cluster` 包，实现类在 `cluster.loadbalance` **子包**，所以真实路径是 `META-INF/dubbo/internal/org.apache.dubbo.rpc.cluster.LoadBalance`。

还有一处贯穿全篇的细节：3.3.6 里取方法名**统一走 `RpcUtils.getMethodName(invocation)`**，不再直接 `invocation.getMethodName()`——前者会处理 `$invoke` 之类的泛化调用后缀。

本文版本基线：Apache Dubbo **3.3.6**，所有代码块与扩展名清单均逐文件核对自源码 tag `dubbo-3.3.6`。其中 `LoadBalance` 接口定义、预热公式（`AbstractLoadBalance.java:46-49`）、以及预热机制说明三处已按 3.3.6 **逐字核对，与源码完全一致**，未作改动。`Cluster` 如何调用 `LoadBalance` 见 [cluster](/docs/CS/Framework/Dubbo/cluster.md)，消费端调用链见 [Consumer](/docs/CS/Framework/Dubbo/Consumer.md)。

```java
@SPI(RandomLoadBalance.NAME)
public interface LoadBalance {

    @Adaptive("loadbalance")
    <T> Invoker<T> select(List<Invoker<T>> invokers, URL url, Invocation invocation) throws RpcException;

}
```

## Extension Point List

3.3.6 的 `dubbo-cluster` 注册了 **6 个** LoadBalance 扩展名，对应 7 个类（`AbstractLoadBalance` 是抽象基类，不注册）：

```properties
# dubbo-cluster/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.cluster.LoadBalance
random=org.apache.dubbo.rpc.cluster.loadbalance.RandomLoadBalance
roundrobin=org.apache.dubbo.rpc.cluster.loadbalance.RoundRobinLoadBalance
leastactive=org.apache.dubbo.rpc.cluster.loadbalance.LeastActiveLoadBalance
consistenthash=org.apache.dubbo.rpc.cluster.loadbalance.ConsistentHashLoadBalance
shortestresponse=org.apache.dubbo.rpc.cluster.loadbalance.ShortestResponseLoadBalance
adaptive=org.apache.dubbo.rpc.cluster.loadbalance.AdaptiveLoadBalance
```

注意文件路径里是 `cluster.LoadBalance`（接口所在包），不是 `cluster.loadbalance.LoadBalance`。



## Balance Type




所有负载均衡策略都继承自 AbstractLoadBalance，它实现了模板方法 select，并提供了通用的权重计算逻辑

### AbstractLoadBalance


getWeight 方法则实现了 Dubbo 的预热机制：新启动的服务提供者权重会随时间线性增长，直到达到配置的权重值，这样可以防止服务刚启动时被分配过多流量

```java
public abstract class AbstractLoadBalance implements LoadBalance {
    static int calculateWarmupWeight(int uptime, int warmup, int weight) {
        int ww = (int) ( uptime / ((float) warmup / weight));
        return ww < 1 ? 1 : (Math.min(ww, weight));
    }

    @Override
    public <T> Invoker<T> select(List<Invoker<T>> invokers, URL url, Invocation invocation) {
        if (CollectionUtils.isEmpty(invokers)) {
            return null;
        }
        if (invokers.size() == 1) {
            return invokers.get(0);
        }
        return doSelect(invokers, url, invocation);
    }

    protected abstract <T> Invoker<T> doSelect(List<Invoker<T>> invokers, URL url, Invocation invocation);

    protected int getWeight(Invoker<?> invoker, Invocation invocation) {
        int weight;
        URL url = invoker.getUrl();
        if (invoker instanceof ClusterInvoker) {
            url = ((ClusterInvoker<?>) invoker).getRegistryUrl();
        }

        // Multiple registry scenario, load balance among multiple registries.
        if (REGISTRY_SERVICE_REFERENCE_PATH.equals(url.getServiceInterface())) {
            weight = url.getParameter(WEIGHT_KEY, DEFAULT_WEIGHT);
        } else {
            weight = url.getMethodParameter(RpcUtils.getMethodName(invocation), WEIGHT_KEY, DEFAULT_WEIGHT);
            if (weight > 0) {
                long timestamp = invoker.getUrl().getParameter(TIMESTAMP_KEY, 0L);
                if (timestamp > 0L) {
                    long uptime = System.currentTimeMillis() - timestamp;
                    if (uptime < 0) {
                        return 1;
                    }
                    int warmup = invoker.getUrl().getParameter(WARMUP_KEY, DEFAULT_WARMUP);
                    if (uptime > 0 && uptime < warmup) {
                        weight = calculateWarmupWeight((int)uptime, warmup, weight);
                    }
                }
            }
        }
        return Math.max(weight, 0);
    }
}
```

`getWeight` 在 3.3.6 里有四处与旧版不同，都不是可选的细节：

| # | 旧写法 | 3.3.6 真实形态 | 证据 |
|---|---|---|---|
| 1 | `int getWeight(...)`（包级私有） | **`protected`**，子类可覆写 | `AbstractLoadBalance.java:72` |
| 2 | 直接 `invoker.getUrl()` | `invoker instanceof ClusterInvoker` 时**改用 `getRegistryUrl()`** | `:74-77` |
| 3 | `url.getParameter(REGISTRY_KEY + "." + WEIGHT_KEY, DEFAULT_WEIGHT)` | `url.getParameter(WEIGHT_KEY, DEFAULT_WEIGHT)`，**不再拼 `registry.` 前缀** | `:81` |
| 4 | `invocation.getMethodName()` | `RpcUtils.getMethodName(invocation)` | `:83` |

第2 条尤其关键：多注册中心场景下 `ClusterInvoker` 的 `getUrl()` 返回的是**面向消费者的 URL**（带路由/负载均衡等本地决策参数），而权重必须按**注册中心维度的 URL** 读，否则拿不到真实配置。这也是为什么 `RandomLoadBalance.needWeightLoadBalance` 里也做了同样的 `ClusterInvoker` 判断（`RandomLoadBalance.java:110-113`）。



### RandomLoadBalance


计算总权重，生成一个 [0, totalWeight) 的随机数，然后依次减去每个 Invoker 的权重，当结果小于 0 时，该 Invoker 即被选中
权重越大，被选中的概率越高

调用量越大分布越均匀，且动态调整权重很方便，这也是它成为默认策略的原因
```java
public class RandomLoadBalance extends AbstractLoadBalance {

    public static final String NAME = "random";

    @Override
    protected <T> Invoker<T> doSelect(List<Invoker<T>> invokers, URL url, Invocation invocation) {
        // Number of invokers
        int length = invokers.size();

        if (!needWeightLoadBalance(invokers, invocation)) {
            return invokers.get(ThreadLocalRandom.current().nextInt(length));
        }

        // Every invoker has the same weight?
        boolean sameWeight = true;
        // the maxWeight of every invoker, the minWeight = 0 or the maxWeight of the last invoker
        int[] weights = new int[length];
        // The sum of weights
        int totalWeight = 0;
        for (int i = 0; i < length; i++) {
            int weight = getWeight(invokers.get(i), invocation);
            // Sum
            totalWeight += weight;
            // save for later use
            weights[i] = totalWeight;
            if (sameWeight && totalWeight != weight * (i + 1)) {
                sameWeight = false;
            }
        }
        if (totalWeight > 0 && !sameWeight) {
            int offset = ThreadLocalRandom.current().nextInt(totalWeight);
            if (length <= 4) {
                for (int i = 0; i < length; i++) {
                    if (offset < weights[i]) {
                        return invokers.get(i);
                    }
                }
            } else {
                int i = Arrays.binarySearch(weights, offset);
                if (i < 0) {
                    i = -i - 1;
                } else {
                    while (weights[i + 1] == offset) {
                        i++;
                    }
                    i++;
                }
                return invokers.get(i);
            }
        }
        // If all invokers have the same weight value or totalWeight=0, return evenly.
        return invokers.get(ThreadLocalRandom.current().nextInt(length));
    }

}
```

3.3.6 加了两处性能优化，旧版代码里都看不到：

**（1）`needWeightLoadBalance()` 快速路径**（`RandomLoadBalance.java:60-62`、`:108-128`）。URL 上压根没配 `weight` 也没有 `timestamp` 时，说明所有节点权重相同，直接均匀随机返回，**跳过整套权重累加与比较**。这是默认配置下最常见的分支——旧版即使什么都没配也要走完整个数组。

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/loadbalance/RandomLoadBalance.java:108-128
    private <T> boolean needWeightLoadBalance(List<Invoker<T>> invokers, Invocation invocation) {
        Invoker<T> invoker = invokers.get(0);
        URL invokerUrl = invoker.getUrl();
        if (invoker instanceof ClusterInvoker) {
            invokerUrl = ((ClusterInvoker<?>) invoker).getRegistryUrl();
        }

        // Multiple registry scenario, load balance among multiple registries.
        if (REGISTRY_SERVICE_REFERENCE_PATH.equals(invokerUrl.getServiceInterface())) {
            String weight = invokerUrl.getParameter(WEIGHT_KEY);
            return StringUtils.isNotEmpty(weight);
        } else {
            String weight = invokerUrl.getMethodParameter(RpcUtils.getMethodName(invocation), WEIGHT_KEY);
            if (StringUtils.isNotEmpty(weight)) {
                return true;
            } else {
                String timeStamp = invoker.getUrl().getParameter(TIMESTAMP_KEY);
                return StringUtils.isNotEmpty(timeStamp);
            }
        }
    }
```

只看第一个Invoker 的 URL 即可判定——它要么全配了要么全没配。

**（2）`length > 4` 时改用 `Arrays.binarySearch`**（`:85-102`）。`weights[i]` 是累积权重数组，本身严格递增，所以可以二分查找落点，把 O(n) 的线性扫描降到 O(log n)。节点数少（≤4）时二分反而不如直接扫，源码里保留了两条分支。



### RoundRobinLoadBalance

为每个方法调用维护一个计数器，每次请求将计数器加1，然后根据权重调整选择逻辑

适合集群中各个节点性能相近的情况，能保证请求平滑均匀地分发

> [!NOTE]
>
> Dubbo 2.6.5 版本后优化了实现，解决了原版本中“慢的提供者累积请求”的问题

```java
public class RoundRobinLoadBalance extends AbstractLoadBalance {
    public static final String NAME = "roundrobin";

    private static final int RECYCLE_PERIOD = 60000;

    protected static class WeightedRoundRobin {
        private int weight;
        private AtomicLong current = new AtomicLong(0);
        private long lastUpdate;

        public int getWeight() {
            return weight;
        }

        public void setWeight(int weight) {
            this.weight = weight;
            current.set(0);
        }

        public long increaseCurrent() {
            return current.addAndGet(weight);
        }

        public void sel(int total) {
            current.addAndGet(-1 * total);
        }

        public long getLastUpdate() {
            return lastUpdate;
        }

        public void setLastUpdate(long lastUpdate) {
            this.lastUpdate = lastUpdate;
        }
    }

    private ConcurrentMap<String, ConcurrentMap<String, WeightedRoundRobin>> methodWeightMap = new ConcurrentHashMap<String, ConcurrentMap<String, WeightedRoundRobin>>();

    /**
     * get invoker addr list cached for specified invocation
     * <p>
     * <b>for unit test only</b>
     *
     * @param invokers
     * @param invocation
     * @return
     */
    protected <T> Collection<String> getInvokerAddrList(List<Invoker<T>> invokers, Invocation invocation) {
        String key = invokers.get(0).getUrl().getServiceKey() + "." + RpcUtils.getMethodName(invocation);
        Map<String, WeightedRoundRobin> map = methodWeightMap.get(key);
        if (map != null) {
            return map.keySet();
        }
        return null;
    }

    @Override
    protected <T> Invoker<T> doSelect(List<Invoker<T>> invokers, URL url, Invocation invocation) {
        String key = invokers.get(0).getUrl().getServiceKey() + "." + RpcUtils.getMethodName(invocation);
        ConcurrentMap<String, WeightedRoundRobin> map = methodWeightMap.computeIfAbsent(key, k -> new ConcurrentHashMap<>());
        int totalWeight = 0;
        long maxCurrent = Long.MIN_VALUE;
        long now = System.currentTimeMillis();
        Invoker<T> selectedInvoker = null;
        WeightedRoundRobin selectedWRR = null;
        for (Invoker<T> invoker : invokers) {
            String identifyString = invoker.getUrl().toIdentityString();
            int weight = getWeight(invoker, invocation);
            WeightedRoundRobin weightedRoundRobin = map.computeIfAbsent(identifyString, k -> {
                WeightedRoundRobin wrr = new WeightedRoundRobin();
                wrr.setWeight(weight);
                return wrr;
            });

            if (weight != weightedRoundRobin.getWeight()) {
                //weight changed
                weightedRoundRobin.setWeight(weight);
            }
            long cur = weightedRoundRobin.increaseCurrent();
            weightedRoundRobin.setLastUpdate(now);
            if (cur > maxCurrent) {
                maxCurrent = cur;
                selectedInvoker = invoker;
                selectedWRR = weightedRoundRobin;
            }
            totalWeight += weight;
        }
        if (invokers.size() != map.size()) {
            map.entrySet().removeIf(item -> now - item.getValue().getLastUpdate() > RECYCLE_PERIOD);
        }
        if (selectedInvoker != null) {
            selectedWRR.sel(totalWeight);
            return selectedInvoker;
        }
        // should not happen here
        return invokers.get(0);
    }

}
```





### LeastActiveLoadBalance

选择活跃数最少的 Invoker。活跃数指正在处理的请求数量，活跃数越小，说明该服务处理能力越强或当前负载越低

能自动“避让”处理慢或负载高的节点，使慢的提供者收到更少请求，非常适合处理请求耗时差异较大的场景


Filter the number of invokers with the least number of active calls and count the weights and quantities of these invokers.
 * If there is only one invoker, use the invoker directly;
 * if there are multiple invokers and the weights are not the same, then random according to the total weight;
 * if there are multiple invokers and the same weight, then randomly called.

```java
public class LeastActiveLoadBalance extends AbstractLoadBalance {

    public static final String NAME = "leastactive";

    @Override
    protected <T> Invoker<T> doSelect(List<Invoker<T>> invokers, URL url, Invocation invocation) {
        // Number of invokers
        int length = invokers.size();
        // The least active value of all invokers
        int leastActive = -1;
        // The number of invokers having the same least active value (leastActive)
        int leastCount = 0;
        // The index of invokers having the same least active value (leastActive)
        int[] leastIndexes = new int[length];
        // the weight of every invokers
        int[] weights = new int[length];
        // The sum of the warmup weights of all the least active invokers
        int totalWeight = 0;
        // The weight of the first least active invoker
        int firstWeight = 0;
        // Every least active invoker has the same weight value?
        boolean sameWeight = true;


        // Filter out all the least active invokers
        for (int i = 0; i < length; i++) {
            Invoker<T> invoker = invokers.get(i);
            // Get the active number of the invoker
            int active = RpcStatus.getStatus(invoker.getUrl(), RpcUtils.getMethodName(invocation)).getActive();
            // Get the weight of the invoker's configuration. The default value is 100.
            int afterWarmup = getWeight(invoker, invocation);
            // save for later use
            weights[i] = afterWarmup;
            // If it is the first invoker or the active number of the invoker is less than the current least active number
            if (leastActive == -1 || active < leastActive) {
                // Reset the active number of the current invoker to the least active number
                leastActive = active;
                // Reset the number of least active invokers
                leastCount = 1;
                // Put the first least active invoker first in leastIndexes
                leastIndexes[0] = i;
                // Reset totalWeight
                totalWeight = afterWarmup;
                // Record the weight the first least active invoker
                firstWeight = afterWarmup;
                // Each invoke has the same weight (only one invoker here)
                sameWeight = true;
                // If current invoker's active value equals with leaseActive, then accumulating.
            } else if (active == leastActive) {
                // Record the index of the least active invoker in leastIndexes order
                leastIndexes[leastCount++] = i;
                // Accumulate the total weight of the least active invoker
                totalWeight += afterWarmup;
                // If every invoker has the same weight?
                if (sameWeight && afterWarmup != firstWeight) {
                    sameWeight = false;
                }
            }
        }
        // Choose an invoker from all the least active invokers
        if (leastCount == 1) {
            // If we got exactly one invoker having the least active value, return this invoker directly.
            return invokers.get(leastIndexes[0]);
        }
        if (!sameWeight && totalWeight > 0) {
            // If (not every invoker has the same weight & at least one invoker's weight>0), select randomly based on 
            // totalWeight.
            int offsetWeight = ThreadLocalRandom.current().nextInt(totalWeight);
            // Return a invoker based on the random value.
            for (int i = 0; i < leastCount; i++) {
                int leastIndex = leastIndexes[i];
                offsetWeight -= weights[leastIndex];
                if (offsetWeight < 0) {
                    return invokers.get(leastIndex);
                }
            }
        }
        // If all invokers have the same weight value or totalWeight=0, return evenly.
        return invokers.get(leastIndexes[ThreadLocalRandom.current().nextInt(leastCount)]);
    }
}
```



### ShortestResponseLoadBalance

选「成功调用平均耗时 × 并发数」估算值最小的节点。**3.3.6 里这个类的算法已经重写为滑动窗口模型**，不再是 2.x 的全量累计平均——旧的 `succeededAverageElapsed * active` 公式会随着服务运行时间增长而越来越迟钝（一个节点哪怕已经劣化，历史样本也会把它一直留在候选里）。

选择流程与 `LeastActiveLoadBalance` 完全同构，唯一区别在估算值怎么算：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/loadbalance/ShortestResponseLoadBalance.java:46-71
public class ShortestResponseLoadBalance extends AbstractLoadBalance implements ScopeModelAware {

    public static final String NAME = "shortestresponse";

    private int slidePeriod = 30_000;

    private final ConcurrentMap<RpcStatus, SlideWindowData> methodMap = new ConcurrentHashMap<>();

    private final AtomicBoolean onResetSlideWindow = new AtomicBoolean(false);

    private volatile long lastUpdateTime = System.currentTimeMillis();

    private ExecutorService executorService;

    @Override
    public void setApplicationModel(ApplicationModel applicationModel) {
        slidePeriod = applicationModel
                .modelEnvironment()
                .getConfiguration()
                .getInt(Constants.SHORTEST_RESPONSE_SLIDE_PERIOD, 30_000);
        executorService = applicationModel
                .getFrameworkModel()
                .getBeanFactory()
                .getBean(FrameworkExecutorRepository.class)
                .getSharedExecutor();
    }
```

四个关键点：

1. **`implements ScopeModelAware`**（`:46`）。窗口周期从配置读（key `shortestresponse.slide.period`，默认 `30_000` 毫秒），线程池从 `FrameworkExecutorRepository` 借共享的——不自己建池。
2. **窗口按 `RpcStatus` 分桶**（`methodMap` 的 key 是 `RpcStatus` 本身，不是字符串）。滑动窗口的状态就是两个 offset。
3. **权重项用 `active + 1`**（`:98-101`）。加1 是为了让「当前无并发」的节点估算值不为 0，从而仍能参与最小值比较。
4. **窗口 reset 是异步的**（`:152-160`），且用 `AtomicBoolean` CAS 保证同一时刻只有一个 reset 任务在跑，不阻塞 `doSelect`。

窗口内部的两个 offset 与平均值算法：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/loadbalance/ShortestResponseLoadBalance.java:73-102
    protected static class SlideWindowData {

        private long succeededOffset;
        private long succeededElapsedOffset;
        private final RpcStatus rpcStatus;

        public SlideWindowData(RpcStatus rpcStatus) {
            this.rpcStatus = rpcStatus;
            this.succeededOffset = 0;
            this.succeededElapsedOffset = 0;
        }

        public void reset() {
            this.succeededOffset = rpcStatus.getSucceeded();
            this.succeededElapsedOffset = rpcStatus.getSucceededElapsed();
        }

        private long getSucceededAverageElapsed() {
            long succeed = this.rpcStatus.getSucceeded() - this.succeededOffset;
            if (succeed == 0) {
                return 0;
            }
            return (this.rpcStatus.getSucceededElapsed() - this.succeededElapsedOffset) / succeed;
        }

        public long getEstimateResponse() {
            int active = this.rpcStatus.getActive() + 1;
            return getSucceededAverageElapsed() * active;
        }
    }
```

所以「滑动窗口」的实现方式不是定时清零计数器，而是**记住上次 reset 时刻的累计值，用当前累计值相减得到窗口内的增量**。`reset()` 只是把 offset 推到当前位置。这是一个零额外内存开销的滑动窗口。

取估算值与触发异步 reset 的那段：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/loadbalance/ShortestResponseLoadBalance.java:126-132, 152-160
            RpcStatus rpcStatus = RpcStatus.getStatus(invoker.getUrl(), RpcUtils.getMethodName(invocation));
            SlideWindowData slideWindowData =
                    ConcurrentHashMapUtils.computeIfAbsent(methodMap, rpcStatus, SlideWindowData::new);

            // Calculate the estimated response time from the product of active connections and succeeded average
            // elapsed time.
            long estimateResponse = slideWindowData.getEstimateResponse();
        // ...

        if (System.currentTimeMillis() - lastUpdateTime > slidePeriod
                && onResetSlideWindow.compareAndSet(false, true)) {
            // reset slideWindowData in async way
            executorService.execute(() -> {
                methodMap.values().forEach(SlideWindowData::reset);
                lastUpdateTime = System.currentTimeMillis();
                onResetSlideWindow.set(false);
            });
        }
```

reset 是在**筛选完成之后**触发的，且提交任务后立刻继续走返回逻辑，不等它执行完。

> [!WARNING]
>
> 3.3.6 的 `methodMap` **只增不减**——里面按 `RpcStatus` 缓存的 `SlideWindowData` 不会被移除。方法下线后对应的桶会一直留在 map 里。


### ConsistentHashLoadBalance

将服务提供者节点（及其虚拟节点）映射到一个圆环上（哈希环），根据请求参数的哈希值在圆环上顺时针寻找最近的节点。Dubbo 默认使用 160 份虚拟节点来解决哈希偏斜问题

特别适合有状态的服务，如缓存。当某台提供者宕机时，其上的请求会平摊到其他节点，避免了剧烈变动

```java
/**
 * ConsistentHashLoadBalance
 */
public class ConsistentHashLoadBalance extends AbstractLoadBalance {
    public static final String NAME = "consistenthash";

    /**
     * Hash nodes name
     */
    public static final String HASH_NODES = "hash.nodes";

    /**
     * Hash arguments name
     */
    public static final String HASH_ARGUMENTS = "hash.arguments";

    private final ConcurrentMap<String, ConsistentHashSelector<?>> selectors = new ConcurrentHashMap<String, ConsistentHashSelector<?>>();

    @SuppressWarnings("unchecked")
    @Override
    protected <T> Invoker<T> doSelect(List<Invoker<T>> invokers, URL url, Invocation invocation) {
        String methodName = RpcUtils.getMethodName(invocation);
        String key = invokers.get(0).getUrl().getServiceKey() + "." + methodName;
        int invokersHashCode = invokers.hashCode();
        // If the detection is successful, return in advance. it may be different from selector, but it doesn't matter
        ConsistentHashSelector<T> oldSelector0;
        if ((oldSelector0 = (ConsistentHashSelector<T>) selectors.get(key)) != null
                && oldSelector0.identityHashCode == invokersHashCode) {
            return oldSelector0.select(invocation);
        }

        // using the hashcode of invoker list to create consistent selector by atomic computation.
        ConsistentHashSelector<T> selector = (ConsistentHashSelector<T>) selectors.compute(
                key,
                (k, oldSelector) -> (oldSelector == null || oldSelector.identityHashCode != invokersHashCode)
                        ? new ConsistentHashSelector<>(invokers, methodName, invokersHashCode)
                        : oldSelector);
        return selector.select(invocation);
    }

    private static final class ConsistentHashSelector<T> {

        private final TreeMap<Long, Invoker<T>> virtualInvokers;

        private final int replicaNumber;

        private final int identityHashCode;

        private final int[] argumentIndex;

        ConsistentHashSelector(List<Invoker<T>> invokers, String methodName, int identityHashCode) {
            this.virtualInvokers = new TreeMap<Long, Invoker<T>>();
            this.identityHashCode = identityHashCode;
            URL url = invokers.get(0).getUrl();
            this.replicaNumber = url.getMethodParameter(methodName, HASH_NODES, 160);
            String[] index = COMMA_SPLIT_PATTERN.split(url.getMethodParameter(methodName, HASH_ARGUMENTS, "0"));
            argumentIndex = new int[index.length];
            for (int i = 0; i < index.length; i++) {
                argumentIndex[i] = Integer.parseInt(index[i]);
            }
            for (Invoker<T> invoker : invokers) {
                String address = invoker.getUrl().getAddress();
                for (int i = 0; i < replicaNumber / 4; i++) {
                    byte[] digest = Bytes.getMD5(address + i);
                    for (int h = 0; h < 4; h++) {
                        long m = hash(digest, h);
                        virtualInvokers.put(m, invoker);
                    }
                }
            }
        }

        public Invoker<T> select(Invocation invocation) {
            String key = toKey(invocation.getArguments());
            byte[] digest = Bytes.getMD5(key);
            return selectForKey(hash(digest, 0));
        }

        private String toKey(Object[] args) {
            StringBuilder buf = new StringBuilder();
            for (int i : argumentIndex) {
                if (i >= 0 && i < args.length) {
                    buf.append(args[i]);
                }
            }
            return buf.toString();
        }

        private Invoker<T> selectForKey(long hash) {
            Map.Entry<Long, Invoker<T>> entry = virtualInvokers.ceilingEntry(hash);
            if (entry == null) {
                entry = virtualInvokers.firstEntry();
            }
            return entry.getValue();
        }

        private long hash(byte[] digest, int number) {
            return (((long) (digest[3 + number * 4] & 0xFF) << 24)
                    | ((long) (digest[2 + number * 4] & 0xFF) << 16)
                    | ((long) (digest[1 + number * 4] & 0xFF) << 8)
                    | (digest[number * 4] & 0xFF))
                    & 0xFFFFFFFFL;
        }
    }

}
```


哈希环构建逻辑（160 虚拟节点、`replicaNumber / 4 * 4`、`hash.arguments` 默认 `"0"`）在 3.3.6 未变，仍与旧版一致。

`selectors` 缓存的写入在 3.3.6 改成了 **`ConcurrentHashMap.compute`**（`ConsistentHashLoadBalance.java:54-67`）。旧写法是「`get` → null 判断 → `put` → 再 `get`」，两次 `get` 之间存在竞态：两个线程可能同时判定为 null，各自`new` 一个 selector，后写的覆盖先写的，中间白算一遍 `MD5` 建环（160 个虚拟节点的成本不低）。`compute` 把这段变成原子的。

### AdaptiveLoadBalance

第7 个实现，也是唯一**不做权重随机**的一个：它用 **P2C（Power of Two Choices）** —— 随机取两个节点，挑其中负载较低的那个。P2C 的好处是比纯随机分布更均匀，又比轮询更廉价。

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/loadbalance/AdaptiveLoadBalance.java:36-60
public class AdaptiveLoadBalance extends AbstractLoadBalance {

    public static final String NAME = "adaptive";

    // default key
    private String attachmentKey = "mem,load";

    private final AdaptiveMetrics adaptiveMetrics;

    public AdaptiveLoadBalance(ApplicationModel scopeModel) {
        adaptiveMetrics = scopeModel.getBeanFactory().getBean(AdaptiveMetrics.class);
    }

    @Override
    protected <T> Invoker<T> doSelect(List<Invoker<T>> invokers, URL url, Invocation invocation) {
        Invoker<T> invoker = selectByP2C(invokers, invocation);
        invocation.setAttachment(Constants.ADAPTIVE_LOADBALANCE_ATTACHMENT_KEY, attachmentKey);
        long startTime = System.currentTimeMillis();
        invocation.getAttributes().put(Constants.ADAPTIVE_LOADBALANCE_START_TIME, startTime);
        invocation.getAttributes().put(LOADBALANCE_KEY, LoadbalanceRules.ADAPTIVE);
        adaptiveMetrics.addConsumerReq(getServiceKey(invoker, invocation));
        adaptiveMetrics.setPickTime(getServiceKey(invoker, invocation), startTime);

        return invoker;
    }
```

三个要点：

1. **构造器接 `ApplicationModel`**（`:45-47`），直接取 `AdaptiveMetrics` bean。这是 3.x ScopeModel 化的典型形态——`AbstractLoadBalance` 的无参构造在这里被打破。
2. **`attachmentKey = "mem,load"`**（`:41`）是默认采集的负载指标，即内存与 CPU 负载。
3. **选中后立刻把指标写进 `Invocation`**（`:52-57`）：采集维度、选择时刻、`LoadbalanceRules.ADAPTIVE` 标记。服务端据此在响应里回传真实负载，客户端侧的 `AdaptiveMetrics` 才能算出下一次选择所需的负载值——这是一个**闭环反馈**，与前6 个「客户端单方面决策」的策略本质不同。

节点数只有 2 时直接二选一比较（`selectByP2C`，`:68-70`），不浪费随机采样。

## AdaptiveMetrics & Feedback Loop

`AdaptiveMetrics` 在 3.3.6 里**不是接口而是具体类** `org.apache.dubbo.rpc.AdaptiveMetrics`（它无 `@SPI` / `@Activate` 注解，见 `AdaptiveMetrics.java:17-31`）。客户端 `AdaptiveLoadBalance` 构造器通过 `scopeModel.getBeanFactory().getBean(AdaptiveMetrics.class)` 取到的就是它的单例。

真实方法签名（注意：**没有** `setLoad` / `removeConsumerReq`，仓库内不存在这两个方法名）：

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/AdaptiveMetrics.java:49-126
public double getLoad(String idKey, int weight, int timeout);                 // :49
public AdaptiveMetrics getStatus(String idKey);                               // :78
public void addConsumerReq(String idKey);                                     // :82
public void addConsumerSuccess(String idKey);                                 // :87
public void addErrorReq(String idKey);                                        // :92
public void setPickTime(String idKey, long time);                             // :97
public void setProviderMetrics(String idKey, Map<String, String> metricsMap); // :102
```

**默认实现是否开箱即用？是。** 该 bean 由 `AdaptiveScopeModelInitializer` 在 `initializeApplicationModel` 时注册：

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/AdaptiveScopeModelInitializer.java:26-29
public void initializeApplicationModel(ApplicationModel applicationModel) {
    ScopeBeanFactory beanFactory = applicationModel.getBeanFactory();
    beanFactory.registerBean(AdaptiveMetrics.class);
}
```

其注册靠 SPI 文件 `dubbo-rpc/dubbo-rpc-api/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.model.ScopeModelInitializer`，内容为 `adaptive=org.apache.dubbo.rpc.AdaptiveScopeModelInitializer`。因此 `getBean(AdaptiveMetrics.class)` **不会 NPE**，也无需用户注册 bean——`AdaptiveLoadBalance` 开箱即用。它不走 `ExtensionLoader` / `@SPI`，就是普通 Scope Bean。

**服务端回传闭环在主仓库内是内置的（不依赖三方扩展）：**

| 环节 | 类 | 激活条件 | 行为 |
|---|---|---|---|
| 客户端读取回传 | `AdaptiveLoadBalanceFilter` | `@Activate(group=CONSUMER, order=-200000, value="loadbalance:adaptive")` | `onResponse` 读响应里的 `lb_adaptive`，按逗号+冒号拆成 `key:value` 进 `metricsMap`，补 `rt`，提交线程池执行 `adaptiveMetrics.setProviderMetrics`；`onError` 调 `addErrorReq` |
| 服务端写回 | `ProfilerServerFilter` | `@Activate(group=PROVIDER, order=Integer.MIN_VALUE)` | `onResponse`→`addAdaptiveResponse` 读入站 `lb_adaptive`，非空则把 `curTime:<now>,load:<系统负载>` 写进响应 attachment |

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/filter/ProfilerServerFilter.java:92-106
private void addAdaptiveResponse(Result appResponse, Invocation invocation) {
    String adaptiveLoadAttachment = invocation.getAttachment(Constants.ADAPTIVE_LOADBALANCE_ATTACHMENT_KEY);
    if (StringUtils.isNotEmpty(adaptiveLoadAttachment)) {
        OperatingSystemMXBean mx = ManagementFactory.getOperatingSystemMXBean();
        StringBuilder sb = new StringBuilder(64);
        sb.append("curTime:").append(System.currentTimeMillis());
        sb.append(COMMA_SEPARATOR).append("load:")
          .append(mx.getSystemLoadAverage() * 100 / mx.getAvailableProcessors());
        appResponse.setAttachment(Constants.ADAPTIVE_LOADBALANCE_ATTACHMENT_KEY, sb.toString());
    }
}
```

闭环常量（与 `AdaptiveLoadBalance.doSelect` 写入一致）：

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/Constants.java:122-123
String ADAPTIVE_LOADBALANCE_ATTACHMENT_KEY = "lb_adaptive";
String ADAPTIVE_LOADBALANCE_START_TIME      = "adaptive_startTime";
// dubbo-common/.../constants/CommonConstants.java:409
String LOADBALANCE_KEY = "loadbalance";
// dubbo-common/.../constants/LoadbalanceRules.java:52
String ADAPTIVE = "adaptive";
```

> [!NOTE]
> 默认 `attachmentKey = "mem,load"`（`AdaptiveLoadBalance.java:41`）**仅是一个触发标记**：服务端 `ProfilerServerFilter` 只判断它非空，真正回传的是 `curTime` 与 `load`，**并不产出 `mem`**。所以 `"mem,load"` 里的前半段 `mem` 实际是无效占位——`setProviderMetrics` 也只读 `curTime` / `load` / `rt` 三个 key（见 `AdaptiveMetrics.java:102-126`）。

## RpcStatus Statistics Source

`LeastActiveLoadBalance` 读的 `getActive()` 与 `ShortestResponseLoadBalance` 读的 `getSucceeded()` / `getSucceededElapsed()`，数据都来自 `org.apache.dubbo.rpc.RpcStatus`，按 `url.toIdentityString()` + `methodName` 分桶（`RpcStatus.java:36-81`）。

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/RpcStatus.java:101-156（维护逻辑）
public static boolean beginCount(URL url, String methodName, int max) {
    ... methodStatus.active.compareAndSet(i, i + 1); appStatus.active.incrementAndGet(); ...
}
private static void endCount(RpcStatus status, long elapsed, boolean succeeded) {
    status.active.decrementAndGet();            // 结束调用，active -1
    status.total.incrementAndGet();
    status.totalElapsed.addAndGet(elapsed);
    if (succeeded) { ... succeededMaxElapsed ... } else { failed++; failedElapsed += elapsed; }
}
```

关键点：**`succeeded` / `succeededElapsed` 是派生值，不是独立字段**——`getSucceeded() = getTotal() - getFailed()`，`getSucceededElapsed() = getTotalElapsed() - getFailedElapsed()`（`RpcStatus.java:272-283`）。`ShortestResponse` 的滑动窗口正是读这两个派生量做差值。

**谁在维护（consumer 侧）？只有 `ActiveLimitFilter`。** 全仓库 grep `beginCount` / `endCount` 的调用方只有两处：

- `ActiveLimitFilter`：`@Activate(group=CONSUMER, value=ACTIVES_KEY)`（`ActiveLimitFilter.java:45`），`invoke` 前后调 `beginCount`/`endCount`（`ActiveLimitFilter.java:56,61,94,110`）。
- `ExecuteLimitFilter`：`@Activate(group=PROVIDER, value=EXECUTES_KEY)`（`ExecuteLimitFilter.java:40`），维护的是**服务端自己**的 `RpcStatus` 视图，与 consumer 侧的 LeastActive 无关。

> [!WARNING]
> **`ActiveLimitFilter` 仅在 consumer 配了 `actives` 时才激活。** 若没配 `actives`，consumer 侧**没有任何代码调用 `beginCount`/`endCount`**，于是 `RpcStatus` 的 `active` / `succeeded` 恒为 0。`LeastActiveLoadBalance` 会看到所有节点 `active==0`（全相等→退化为按权重随机），`ShortestResponseLoadBalance` 则 `getSucceededAverageElapsed()` 在 `succeed==0` 时直接返回 0（`ShortestResponseLoadBalance.java:90-93`）→ 所有节点估算值 0 → 同样退化为随机。换言之，**LeastActive / ShortestResponse 的"智能"是挂在 `actives` 限流开关上的**，默认并不生效。

`active` 的语义要厘清：它是「**本 consumer 对该 provider+method 正在进行的调用数**」，由 consumer 用 `invoker.getUrl()`（provider 的 URL）维护，**不是 provider 的真实并发**。多个 consumer 各自独立计数，彼此不可见。

## selectByP2C Full Code

`AdaptiveLoadBalance.doSelect` 只暴露了前段，完整 P2C 逻辑在 `selectByP2C` / `chooseLowLoadInvoker` 里：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/loadbalance/AdaptiveLoadBalance.java:62-130
private <T> Invoker<T> selectByP2C(List<Invoker<T>> invokers, Invocation invocation) {
    int length = invokers.size();
    if (length == 1) return invokers.get(0);
    if (length == 2) return chooseLowLoadInvoker(invokers.get(0), invokers.get(1), invocation);
    int pos1 = ThreadLocalRandom.current().nextInt(length);
    int pos2 = ThreadLocalRandom.current().nextInt(length - 1);
    if (pos2 >= pos1) pos2 = pos2 + 1;                 // 保证 pos1 != pos2
    return chooseLowLoadInvoker(invokers.get(pos1), invokers.get(pos2), invocation);
}

private String buildServiceKey(Invoker<?> invoker, Invocation invocation) {
    URL url = invoker.getUrl();
    return url.getAddress() + ":" + invocation.getProtocolServiceKey();
}

private <T> Invoker<T> chooseLowLoadInvoker(Invoker<T> invoker1, Invoker<T> invoker2, Invocation invocation) {
    int weight1 = getWeight(invoker1, invocation);
    int weight2 = getWeight(invoker2, invocation);
    int timeout1 = getTimeout(invoker1, invocation);
    int timeout2 = getTimeout(invoker2, invocation);
    long load1 = Double.doubleToLongBits(
        adaptiveMetrics.getLoad(getServiceKey(invoker1, invocation), weight1, timeout1));
    long load2 = Double.doubleToLongBits(
        adaptiveMetrics.getLoad(getServiceKey(invoker2, invocation), weight2, timeout2));
    if (load1 == load2) {                               // 负载相等→按权重随机
        int totalWeight = weight1 + weight2;
        if (totalWeight > 0) {
            int offset = ThreadLocalRandom.current().nextInt(totalWeight);
            return offset < weight1 ? invoker1 : invoker2;
        }
        return ThreadLocalRandom.current().nextInt(2) == 0 ? invoker1 : invoker2;
    }
    return load1 > load2 ? invoker2 : invoker1;         // 挑负载低者
}
```

两点补充（现有文档未展开）：

1. **负载 key 是 `address:protocolServiceKey`，按 provider 维度而非 method 维度**。`buildServiceKey` 拼的是 `url.getAddress()` + `protocolServiceKey`，所以同一 provider 上不同方法的自适应负载是共享一个 `AdaptiveMetrics` 桶的——这与 `LeastActive` / `ShortestResponse` 按 `methodName` 分桶（`RpcStatus.getStatus(url, methodName)`）不同。
2. **冷启动不崩**：第一次 `doSelect` 里 `selectByP2C` 先于 `addConsumerReq` 执行（`AdaptiveLoadBalance.java:51` 调用 `selectByP2C`，`:56` 才 `addConsumerReq`）。此刻 `consumerReq=0` → `inflight=0`、`providerCPULoad=0` → `getLoad` 返回 0，两端相等走权重随机。等 `ProfilerServerFilter` 回传 `load` 后，`getLoad` 才出现区分度。`getLoad` 里还强制：若 `now - pickTime > timeout*2` 直接返回 `0`（`AdaptiveMetrics.java:53`），避免某节点长期不被选中而"饿死"。

## Warmup Formula

预热默认参数（与 `AbstractLoadBalance.getWeight` 引用一致）：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/Constants.java:29, 99
int DEFAULT_WEIGHT = 100;
int DEFAULT_WARMUP = 10 * 60 * 1000;   // 600000 ms = 10 分钟
```

公式本身：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/loadbalance/AbstractLoadBalance.java:46-49
static int calculateWarmupWeight(int uptime, int warmup, int weight) {
    int ww = (int) (uptime / ((float) warmup / weight));
    return ww < 1 ? 1 : (Math.min(ww, weight));
}
```

代数化简：`ww = uptime / (warmup/weight) = uptime * weight / warmup`。

- **为什么线性**：分子 `uptime` 线性增长，`weight/warmup` 是常数，所以 `ww` 随运行时长线性上升。
- **为什么下限 1、上限 weight**：`ww < 1 ? 1` 保证刚启动的节点仍拿最小流量（不会是 0 导致永远不被选中）；`Math.min(ww, weight)` 在 `uptime ≥ warmup` 时封顶到配置权重。
- **数值例子**（`weight=100`，`warmup=600000ms`）：

| uptime | 计算 | ww |
|---|---|---|
| 0 | 0 → 触发 `ww<1` | **1** |
| 60s (60000) | 60000 / (600000/100)=60000/6000 | 10 |
| 300s (300000) | 300000/6000 | 50 |
| 600s (600000) | 600000/6000 | **100 (=weight)** |

即权重在 10 分钟内从 1 线性爬升到 100，避免新节点一上线就被打满。

## RoundRobin Smooth Weighted Algorithm

现有 `RoundRobinLoadBalance` 用的是 **Nginx smooth weighted round-robin**（平滑加权轮询），不是朴素轮询。原理与代码对应如下：

```text
每轮：对每个节点 current += weight
选择：current 最大的节点
选中后：该节点 current -= totalWeight
```

伪码：

```java
// 对应 WeightedRoundRobin.increaseCurrent / sel 与 doSelect 的 maxCurrent 选择
for each invoker:
    wrr.current += wrr.weight;           // increaseCurrent()  :249-251
    if (wrr.current > maxCurrent) { selected = invoker; maxCurrent = wrr.current; }
selectedWRR.current -= totalWeight;     // sel(totalWeight)   :253-255, 调用于 :321
```

`doSelect` 里 `maxCurrent` 取最大、选中后 `selectedWRR.sel(totalWeight)` 扣掉总权重（`:308-321`），与上面的算法一一对应。

**为什么能避免"慢节点累积"**：朴素轮询给每个节点按权重均分序号，若某节点变慢，它的请求会在同一窗口集中堆积；平滑加权每轮只把 `weight` 累加进 `current`，选中时扣 `totalWeight`，于是高权重节点虽然被选中更频繁，但每次选中都会大幅回退 `current`，请求在时间轴上被**打散**到多轮、不会连续扎堆。

**`RECYCLE_PERIOD=60000` 的意义**（`RoundRobinLoadBalance.java:233, 317-319`）：当 `invokers.size() != map.size()`（有节点下线或新上线）时，移除 `now - lastUpdate > 60000` 的 `WeightedRoundRobin`。否则一个已下线的节点其 `current` 累积值会一直留在 `methodWeightMap` 里，既浪费内存，也可能让慢节点残留的高 `current` 干扰选择。这就是 Dubbo 2.6.5 那次修复的核心——旧实现的"慢的提供者累积请求"问题正是靠这套平滑 + 回收机制解决的（对应 [Pitfall List](/docs/CS/Framework/Dubbo/LoadBalance.md?id=pitfall-list) 第 8 条）。

## Sticky Selection

「粘性」指在一次调用的重试过程中**尽量复用同一个 Provider**，但它**不属于 LoadBalance 的职责**——代码里没有任何 LoadBalance 实现感知 sticky。粘性的实现位于 `AbstractClusterInvoker.select`（`support/AbstractClusterInvoker.java:155-185`）：当方法参数 `CLUSTER_STICKY_KEY`（默认 `DEFAULT_CLUSTER_STICKY` = `false`）开启时，若 `stickyInvoker` 字段仍处在候选里且可用，直接返回它，不再问 LoadBalance。

这与 LoadBalance 的关系是**解耦**的：LoadBalance 永远只回答「给定候选里挑谁」，而「是否要避开已选过的、是否要粘住上一次的」由外层 `select` 的 `selected` 去重与 sticky 逻辑兜住。需要深入理解见 [cluster](/docs/CS/Framework/Dubbo/cluster.md?id=abstractclusterinvoker-template-method)。

## Why Random Is the Default

`LoadBalance` 接口用 `@SPI(RandomLoadBalance.NAME)` 声明缺省实现，即 `random`。选它作为默认不是因为「最公平」，而是工程权衡：

- **大样本趋匀**：随着调用量增大，带权随机的统计分布会自然逼近理论权重比例，无需维护任何跨请求的状态（对比 `RoundRobin` 要维护 `WeightedRoundRobin` 计数器、`LeastActive` 要读 `RpcStatus` 活跃数）。
- **动态权重零成本**：权重（含预热）变化时随机算法天然适配，不需要像轮询那样重新平衡累计值。
- **快速路径省开销**：3.3.6 的 `RandomLoadBalance.needWeightLoadBalance`（`RandomLoadBalance.java:108-128`）在「未配 `weight` 也未配 `timestamp`」时直接均匀随机，**跳过整套权重累加与二分查找**——这是默认配置下最常见的分支，开销最低。

代价是「单次瞬时分布不如轮询平滑」，但对无状态服务来说这点抖动通常可接受，因此 Dubbo 把最低认知负担、最低开销的 Random 设为默认，把更精细的策略留给显式配置。

## Pitfall List

> [!WARNING]
>
> 每一条都对应一个「照旧文档写就会出错」的具体后果。

1. **SPI 文件路径是 `...rpc.cluster.LoadBalance`，不是 `...rpc.cluster.loadbalance.LoadBalance`**。按实现类所在包去找会找不到文件——SPI 文件名永远按**接口 FQN** 命名。
2. **实现有 7 个，不是 6 个**。漏掉的是 `adaptive`（`AdaptiveLoadBalance`）。
3. **`ShortestResponseLoadBalance` 不是空壳，也不是全量累计平均**。3.3.6 是滑动窗口（默认 30s、`active + 1`、异步 reset），旧公式 `succeededAverageElapsed * active` 里的 `active` **没有 +1**。照旧公式推导节点排序会算错。
4. **`getWeight` 是 `protected` 且会走 `ClusterInvoker.getRegistryUrl()`**。多注册中心场景下用 `getUrl()` 读权重读的是消费者侧 URL，拿不到真实配置。同时 key 也不再拼 `registry.` 前缀。
5. **取方法名统一用 `RpcUtils.getMethodName(invocation)`**。直接 `invocation.getMethodName()` 在泛化调用（`$invoke`）场景下会拿到错误的名字，进而导致 `methodWeightMap` / `RpcStatus` 分桶错位。
6. **`RandomLoadBalance` 有 `needWeightLoadBalance()` 快速路径**。不配 `weight` 也不配 `timestamp` 时直接均匀随机，跳过整套权重计算——只看旧版代码会以为权重计算总是会执行。
7. **`ConsistentHashLoadBalance.selectors` 用 `compute` 原子写入**。旧版「get → put → get」写法有竞态，在节点列表频繁变动时可能重复建环。
8. **`RoundRobinLoadBalance` 的 2.6.5 优化仍然有效**：超过 `RECYCLE_PERIOD`（60s）未被更新的 `WeightedRoundRobin` 会被剔除，解决慢节点累积请求的问题。
9. **`AdaptiveLoadBalance` 是闭环的**：它依赖服务端回传负载数据才能工作。链路里没有服务端负载上报（如部分 mesh 场景）时，它的 P2C 决策会退化。

## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [cluster](/docs/CS/Framework/Dubbo/cluster.md)
- [Router](/docs/CS/Framework/Dubbo/Router.md)
- [Consumer](/docs/CS/Framework/Dubbo/Consumer.md)
- [Governance](/docs/CS/Framework/Dubbo/Governance.md)

## References

1. [Apache Dubbo 3.3.6 源码（tag dubbo-3.3.6）](https://github.com/apache/dubbo/tree/dubbo-3.3.6)
2. [dubbo-cluster loadbalance 包源码](https://github.com/apache/dubbo/tree/dubbo-3.3.6/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/loadbalance)
3. [Dubbo 负载均衡官方文档](https://cn.dubbo.apache.org/zh-cn/overview/core-features/loadbalance/)
4. [Dubbo SPI 扩展点开发指南](https://cn.dubbo.apache.org/zh-cn/overview/mannual/java-sdk/reference-manual/architecture/dubbo-spi/)
