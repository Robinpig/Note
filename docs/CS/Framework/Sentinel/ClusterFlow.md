# ClusterFlow

## Introduction

> 版本基线：Sentinel 1.8.10

集群流控（Cluster Flow Control）把限流判定从每个客户端上移到中心化的 **Token Server**：客户端不再用本地 `StatisticNode` 自行判定，而是通过 `TokenService` 向 Server 申请令牌，Server 用滑动窗口统计全局通过量并集中裁决。它解决的是「单机均值限流在实例数波动时无法换算成集群总量」的问题，但代价是引入一次网络往返与一套独立的 client/server 状态机。

本篇的增量在于把这套契约拆到源码级：从状态码的正负陷阱、`count` 默认是单机均值、per-namespace 配置不生效、20ms 请求超时，到 `writeAndFlush` 早于 `putPromise` 的竞态窗口。所有片段取自 tag `1.8.10`（commit `cf97bba`）。

## Client-Server Token Contract

客户端与 Server 之间的全部交互收敛在一个接口里。`cluster/TokenService.java` 定义了四类请求：普通令牌、热点参数令牌、并发令牌的获取与释放。

```java
public interface TokenService {

    /**
     * Request tokens from remote token server.
     *
     * @param ruleId the unique rule ID
     * @param acquireCount token count to acquire
     * @param prioritized whether the request is prioritized
     * @return result of the token request
     */
    TokenResult requestToken(Long ruleId, int acquireCount, boolean prioritized);

    /**
     * Request tokens for a specific parameter from remote token server.
     *
     * @param ruleId the unique rule ID
     * @param acquireCount token count to acquire
     * @param params parameter list
     * @return result of the token request
     */
    TokenResult requestParamToken(Long ruleId, int acquireCount, Collection<Object> params);

    /**
     * Request acquire concurrent tokens from remote token server.
     *
     * @param clientAddress the address of the request belong.
     * @param ruleId ruleId the unique rule ID
     * @param acquireCount token count to acquire
     * @return result of the token request
     */
    TokenResult requestConcurrentToken(String clientAddress,Long ruleId,int acquireCount);
    /**
     * Request release concurrent tokens from remote token server asynchronously.
     *
     * @param tokenId the unique token ID
     */
    void releaseConcurrentToken(Long tokenId);
}
```

返回值 `cluster/TokenResult.java` 用五个字段描述一次申请的结果：`status` 是判定码，`remaining` 是剩余额度，`waitInMs` 是优先级请求的预占等待时长，`tokenId` 用于并发令牌释放，`attachments` 是扩展信息。

```java
public class TokenResult {

    private Integer status;

    private int remaining;
    private int waitInMs;

    private long tokenId;

    private Map<String, String> attachments;
```

## Status Codes: Positive Is Not Success

这是最容易踩的反直觉点：`TokenResultStatus` 里**只有 `OK = 0` 表示成功**，正整数不是「成功的某种程度」而是各类失败/等待，负整数则是请求级错误。

```java
public final class TokenResultStatus {

    /**
     * Bad client request.
     */
    public static final int BAD_REQUEST = -4;
    /**
     * Too many request in server.
     */
    public static final int TOO_MANY_REQUEST = -2;
    /**
     * Server or client unexpected failure (due to transport or serialization failure).
     */
    public static final int FAIL = -1;

    /**
     * Token acquired.
     */
    public static final int OK = 0;

    /**
     * Token acquire failed (blocked).
     */
    public static final int BLOCKED = 1;
    /**
     * Should wait for next buckets.
     */
    public static final int SHOULD_WAIT = 2;
    /**
     * Token acquire failed (no rule exists).
     */
    public static final int NO_RULE_EXISTS = 3;
    /**
     * Token acquire failed (reference resource is not available).
     */
    public static final int NO_REF_RULE_EXISTS = 4;
    /**
     * Token acquire failed (strategy not available).
     */
    public static final int NOT_AVAILABLE = 5;
    /**
     * Token is successfully released.
     */
    public static final int RELEASE_OK = 6;
    /**
     * Token already is released before the request arrives.
     */
    public static final int ALREADY_RELEASE=7;
```

注意负数序列是 `-4 / -2 / -1`，**没有 `-3`**：`BAD_REQUEST` 直接跳到 `-4`。消费方判断成功只能判 `status == OK`，用 `status > 0` 当成功是错的——`BLOCKED(1)` 恰恰是限流拒绝。

## Server-Side Admission Logic

真正的判定在 `sentinel-cluster-server-default` 的 `cluster/flow/ClusterFlowChecker.java`。入口 `acquireClusterToken` 的顺序是：先过全局请求限流 `GlobalRequestLimiter`，再取滑动窗口的当前 QPS（`metric.getAvg(PASS)`），算出全局阈值后与 `latestQps + acquireCount` 比较，`nextRemaining >= 0` 放行并计数，否则按 `prioritized` 尝试预占下一窗口，预占失败记 BLOCK 拒绝。

```java
    static TokenResult acquireClusterToken(/*@Valid*/ FlowRule rule, int acquireCount, boolean prioritized) {
        Long id = rule.getClusterConfig().getFlowId();

        if (!allowProceed(id)) {
            return new TokenResult(TokenResultStatus.TOO_MANY_REQUEST);
        }

        ClusterMetric metric = ClusterMetricStatistics.getMetric(id);
        if (metric == null) {
            return new TokenResult(TokenResultStatus.FAIL);
        }

        double latestQps = metric.getAvg(ClusterFlowEvent.PASS);
        double globalThreshold = calcGlobalThreshold(rule) * ClusterServerConfigManager.getExceedCount();
        double nextRemaining = globalThreshold - latestQps - acquireCount;

        if (nextRemaining >= 0) {
            // TODO: checking logic and metric operation should be separated.
            metric.add(ClusterFlowEvent.PASS, acquireCount);
            metric.add(ClusterFlowEvent.PASS_REQUEST, 1);
            if (prioritized) {
                // Add prioritized pass.
                metric.add(ClusterFlowEvent.OCCUPIED_PASS, acquireCount);
            }
            // Remaining count is cut down to a smaller integer.
            return new TokenResult(TokenResultStatus.OK)
                .setRemaining((int) nextRemaining)
                .setWaitInMs(0);
        } else {
            if (prioritized) {
                // Try to occupy incoming buckets.
                double occupyAvg = metric.getAvg(ClusterFlowEvent.WAITING);
                if (occupyAvg <= ClusterServerConfigManager.getMaxOccupyRatio() * globalThreshold) {
                    int waitInMs = metric.tryOccupyNext(ClusterFlowEvent.PASS, acquireCount, globalThreshold);
                    // waitInMs > 0 indicates pre-occupy incoming buckets successfully.
                    if (waitInMs > 0) {
                        ClusterServerStatLogUtil.log("flow|waiting|" + id);
                        return new TokenResult(TokenResultStatus.SHOULD_WAIT)
                            .setRemaining(0)
                            .setWaitInMs(waitInMs);
                    }
                    // Or else occupy failed, should be blocked.
                }
            }
            // Blocked.
            metric.add(ClusterFlowEvent.BLOCK, acquireCount);
            metric.add(ClusterFlowEvent.BLOCK_REQUEST, 1);
            ClusterServerStatLogUtil.log("flow|block|" + id, acquireCount);
            ClusterServerStatLogUtil.log("flow|block_request|" + id, 1);
            if (prioritized) {
                // Add prioritized block.
                metric.add(ClusterFlowEvent.OCCUPIED_BLOCK, acquireCount);
                ClusterServerStatLogUtil.log("flow|occupied_block|" + id, 1);
            }

            return blockedResult();
        }
    }
```

三个出口对应三个状态码：放行是 `OK(0)`，优先级请求预占成功是 `SHOULD_WAIT(2)`（带 `waitInMs`），兜底拒绝是 `BLOCKED(1)`（由 `blockedResult()` 构造）。`allowProceed` 失败时直接返回 `TOO_MANY_REQUEST(-2)`。

## Global Threshold and the count Trap

`globalThreshold` 由 `calcGlobalThreshold(rule)` 再乘 `getExceedCount()`（默认 1.0）得到。关键在 `calcGlobalThreshold`：`FLOW_THRESHOLD_AVG_LOCAL` 模式下阈值不是规则里的 `count`，而是 **`count × 当前连接的客户端数`**。

```java
    private static double calcGlobalThreshold(FlowRule rule) {
        double count = rule.getCount();
        switch (rule.getClusterConfig().getThresholdType()) {
            case ClusterRuleConstant.FLOW_THRESHOLD_GLOBAL:
                return count;
            case ClusterRuleConstant.FLOW_THRESHOLD_AVG_LOCAL:
            default:
                int connectedCount = ClusterFlowRuleManager.getConnectedCount(rule.getClusterConfig().getFlowId());
                return count * connectedCount;
        }
    }
```

`ClusterRuleConstant.java` 中 `FLOW_THRESHOLD_AVG_LOCAL` 的值是 `0`，且它是 `ClusterFlowConfig` 的默认值——所以**什么都不配就走「单机均值 × 连接数」**：

```java
    public static final int FLOW_THRESHOLD_AVG_LOCAL = 0;
    public static final int FLOW_THRESHOLD_GLOBAL = 1;

    public static final int DEFAULT_CLUSTER_SAMPLE_COUNT = 10;
```

连接数的来源在 `ClusterFlowRuleManager.java`：先由 `flowId` 反查 namespace，再取该 namespace 的连接数；`flowId <= 0` 或查不到映射时返回 0——此时 `count * 0 = 0`，阈值归零，请求会被全部拒绝，这是配置 `flowId` 时必须全局唯一的直接原因。

```java
    public static int getConnectedCount(long flowId) {
        if (flowId <= 0) {
            return 0;
        }
        String namespace = FLOW_NAMESPACE_MAP.get(flowId);
        if (namespace == null) {
            return 0;
        }
        return ConnectionManager.getConnectedCount(namespace);
    }
```

反直觉结论：规则里写的 `count` 在默认模式下是**单机均值**，想表达「集群总 QPS 上限」必须显式设 `thresholdType = FLOW_THRESHOLD_GLOBAL`，否则客户端数量一变，实际阈值跟着变。

## Per-Namespace Config That Never Applies

`acquireClusterToken` 里用的是**无参** `getExceedCount()` / `getMaxOccupyRatio()`，而不是带 namespace 的版本。虽然 `ClusterServerConfigManager.java` 里两套都提供了：

```java
    public static double getExceedCount(String namespace) {
        AssertUtil.notEmpty(namespace, "namespace cannot be empty");
        ServerFlowConfig config = NAMESPACE_CONF.get(namespace);
        if (config != null) {
            return config.getExceedCount();
        }
        return exceedCount;
    }

    public static double getMaxOccupyRatio(String namespace) {
        AssertUtil.notEmpty(namespace, "namespace cannot be empty");
        ServerFlowConfig config = NAMESPACE_CONF.get(namespace);
        if (config != null) {
            return config.getMaxOccupyRatio();
        }
        return maxOccupyRatio;
    }
```

判定路径调用的却是只读全局字段的无参版本：

```java
    public static double getExceedCount() {
        return exceedCount;
    }

    public static double getMaxOccupyRatio() {
        return maxOccupyRatio;
    }
```

更彻底的是，所谓「按 namespace 加载配置」的入口本身就没实现——`loadFlowConfig` 带 TODO 直接写进全局 property，`NAMESPACE_CONF` 在整个类里只有读、没有任何写入点：

```java
    public static void loadFlowConfig(String namespace, ServerFlowConfig config) {
        AssertUtil.notEmpty(namespace, "namespace cannot be empty");
        // TODO: Support namespace-scope server flow config.
        globalFlowProperty.updateValue(config);
    }
```

所以多 namespace 场景下，per-namespace 的 exceedCount / maxOccupyRatio 配置**不会生效**，所有 namespace 共用一份全局值。

## Request Timeout: 20ms

`ClusterConstants.java` 里请求超时与连接超时差距悬殊：

```java
    public static final int DEFAULT_CLUSTER_SERVER_PORT = 18730;
    public static final int DEFAULT_REQUEST_TIMEOUT = 20;
    public static final int DEFAULT_CONNECT_TIMEOUT_MILLIS = 10 * 1000;
```

`DEFAULT_REQUEST_TIMEOUT = 20`（毫秒）意味着一次 `requestToken` 往返只给 20ms，而连接超时是 10000ms。默认值来自 `ClusterClientConfigManager` 的同名常量字段；除非通过 `ClusterClientConfig` 显式调大，否则 Server 端 GC 抖动或网络轻微延迟都会让 `promise.await` 超时、客户端拿到 `FAIL(-1)` 或回退本地。

## Client Transport and the Promise Race

客户端 `DefaultClusterTokenClient` 只持有**单一** `NettyTransportClient`。构造器向 `ClusterClientConfigManager` 注册 `ServerChangeObserver`，地址也取自该管理器；Server 变更回调 `changeServer` 会停掉旧连接、无条件重建新客户端（注释明说「even if the new client is not ready」）。

```java
    public DefaultClusterTokenClient() {
        ClusterClientConfigManager.addServerChangeObserver(new ServerChangeObserver() {
            @Override
            public void onRemoteServerChange(ClusterClientAssignConfig assignConfig) {
                changeServer(assignConfig);
            }
        });
        initNewConnection();
    }
```

```java
    private void changeServer(/*@Valid*/ ClusterClientAssignConfig config) {
        if (serverEqual(serverDescriptor, config)) {
            return;
        }
        try {
            if (transportClient != null) {
                transportClient.stop();
            }
            // Replace with new, even if the new client is not ready.
            this.transportClient = new NettyTransportClient(config.getServerHost(), config.getServerPort());
            this.serverDescriptor = new TokenServerDescriptor(config.getServerHost(), config.getServerPort());
            startClientIfScheduled();
            RecordLog.info("[DefaultClusterTokenClient] New client created: {}", serverDescriptor);
        } catch (Exception ex) {
            RecordLog.warn("[DefaultClusterTokenClient] Failed to change remote token server", ex);
        }
    }
```

请求与响应的配对在 `NettyTransportClient.sendRequest`：用递增 `xid` 标识请求，`ChannelPromise.await(requestTimeout)` 等待应答，配对表是 `TokenClientPromiseHolder`。**注意 `writeAndFlush` 发生在 `putPromise` 之前**：

```java
    @Override
    public ClusterResponse sendRequest(ClusterRequest request) throws Exception {
        if (!isReady()) {
            throw new SentinelClusterException(ClusterErrorMessages.CLIENT_NOT_READY);
        }
        if (!validRequest(request)) {
            throw new SentinelClusterException(ClusterErrorMessages.BAD_REQUEST);
        }
        int xid = getCurrentId();
        try {
            request.setId(xid);

            channel.writeAndFlush(request);

            ChannelPromise promise = channel.newPromise();
            TokenClientPromiseHolder.putPromise(xid, promise);

            if (!promise.await(ClusterClientConfigManager.getRequestTimeout())) {
                throw new SentinelClusterException(ClusterErrorMessages.REQUEST_TIME_OUT);
            }

            SimpleEntry<ChannelPromise, ClusterResponse> entry = TokenClientPromiseHolder.getEntry(xid);
            if (entry == null || entry.getValue() == null) {
                // Should not go through here.
                throw new SentinelClusterException(ClusterErrorMessages.UNEXPECTED_STATUS);
            }
            return entry.getValue();
        } finally {
            TokenClientPromiseHolder.remove(xid);
        }
    }
```

这是一个真实的竞态窗口：如果 Server 应答极快，在 `writeAndFlush` 之后、`putPromise` 之前就回到客户端，`TokenClientHandler.channelRead` 调用 `completePromise` 时 `PROMISE_MAP` 还没有该 xid，会直接返回 false 把应答丢弃；随后 `await(20ms)` 只能等到超时。窗口很小，但叠加 20ms 的短超时就值得关注。

```java
    public static <T> boolean completePromise(int xid, ClusterResponse<T> response) {
        if (!PROMISE_MAP.containsKey(xid)) {
            return false;
        }
```

## Role Switching

同一个进程可以在 client / server 之间切换，状态在 `cluster/ClusterStateManager.java` 里用 `volatile int mode` 加一个 `SentinelProperty<Integer>` 承载，切换经 `applyState` → `configUpdate` 落到 `setToClient` / `setToServer`。

```java
    private static volatile int mode = CLUSTER_NOT_STARTED;
    private static volatile long lastModified = -1;

    private static volatile SentinelProperty<Integer> stateProperty = new DynamicSentinelProperty<Integer>();
    private static final PropertyListener<Integer> PROPERTY_LISTENER = new ClusterStatePropertyListener();
```

切换的顺序是先停对端再起自己：`setToClient` 走 `startClient()` 停掉 embedded server，`setToServer` 走 `startServer()` 停掉 client。

```java
    public static boolean setToClient() {
        if (mode == CLUSTER_CLIENT) {
            return true;
        }
        mode = CLUSTER_CLIENT;
        sleepIfNeeded();
        lastModified = TimeUtil.currentTimeMillis();
        return startClient();
    }
```

```java
    private static boolean startClient() {
        try {
            EmbeddedClusterTokenServer server = EmbeddedClusterTokenServerProvider.getServer();
            if (server != null) {
                server.stop();
            }
            ClusterTokenClient tokenClient = TokenClientProvider.getClient();
```

```java
    public static boolean setToServer() {
        if (mode == CLUSTER_SERVER) {
            return true;
        }
        mode = CLUSTER_SERVER;
        sleepIfNeeded();
        lastModified = TimeUtil.currentTimeMillis();
        return startServer();
    }
```

```java
    private static boolean startServer() {
        try {
            ClusterTokenClient tokenClient = TokenClientProvider.getClient();
            if (tokenClient != null) {
                tokenClient.stop();
            }
            EmbeddedClusterTokenServer server = EmbeddedClusterTokenServerProvider.getServer();
```

最后一个反直觉点：`sleepIfNeeded` 的 javadoc 写「by default 10s」，但常量实际是 `5 * 1000`，即两次切换的最小间隔是 **5 秒**，注释与常量不符。

```java
    /**
     * The interval between two change operations should be greater than {@code MIN_INTERVAL} (by default 10s).
     * Or we need to wait for a while.
     */
```

```java
    private static final int MIN_INTERVAL = 5 * 1000;
```

## ClusterFlowConfig Fields

`slots/block/flow/ClusterFlowConfig.java` 是挂在 `FlowRule` 上的集群配置。`flowId` 是全局唯一键（决定令牌申请打到哪条 Server 规则，`getConnectedCount` 也靠它反查 namespace）；`thresholdType` 默认 `FLOW_THRESHOLD_AVG_LOCAL`；`sampleCount` 默认 10，`windowIntervalMs` 用 `RuleConstant.DEFAULT_WINDOW_INTERVAL_MS`（1s）；`resourceTimeout` 默认 2000ms，用于并发令牌超时策略。

```java
    /**
     * Global unique ID.
     */
    private Long flowId;

    /**
     * Threshold type (average by local value or global value).
     */
    private int thresholdType = ClusterRuleConstant.FLOW_THRESHOLD_AVG_LOCAL;
    private boolean fallbackToLocalWhenFail = true;

    /**
     * 0: normal.
     */
    private int strategy = ClusterRuleConstant.FLOW_CLUSTER_STRATEGY_NORMAL;

    private int sampleCount = ClusterRuleConstant.DEFAULT_CLUSTER_SAMPLE_COUNT;
    /**
     * The time interval length of the statistic sliding window (in milliseconds)
     */
    private int windowIntervalMs = RuleConstant.DEFAULT_WINDOW_INTERVAL_MS;

    /**
     * if the client keep the token for more than resourceTimeout,resourceTimeoutStrategy will work.
     */
    private long resourceTimeout = 2000;
```

需要特别区分：`fallbackToLocalWhenFail`（默认 `true`）只是「Token Server 不可用时客户端退回本地流控」的开关，它是客户端侧行为，**不进入 `ClusterFlowChecker` 的放行计算**——判定公式只认 `thresholdType` / `count` / `getExceedCount()` / 连接数。别把它和阈值上限混为一谈。

## Links

- [Sentinel 枢纽](/docs/CS/Framework/Sentinel/Sentinel.md)
- [流量控制 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md)
- [Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)
- [规则与动态数据源 RuleDataSource](/docs/CS/Framework/Sentinel/RuleDataSource.md)

## References

- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/cluster/TokenService.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/cluster/TokenResult.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/cluster/TokenResultStatus.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/cluster/ClusterStateManager.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/block/ClusterRuleConstant.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/block/flow/ClusterFlowConfig.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-cluster/sentinel-cluster-server-default/src/main/java/com/alibaba/csp/sentinel/cluster/flow/ClusterFlowChecker.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-cluster/sentinel-cluster-server-default/src/main/java/com/alibaba/csp/sentinel/cluster/flow/rule/ClusterFlowRuleManager.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-cluster/sentinel-cluster-server-default/src/main/java/com/alibaba/csp/sentinel/cluster/server/config/ClusterServerConfigManager.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-cluster/sentinel-cluster-common-default/src/main/java/com/alibaba/csp/sentinel/cluster/ClusterConstants.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-cluster/sentinel-cluster-client-default/src/main/java/com/alibaba/csp/sentinel/cluster/client/DefaultClusterTokenClient.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-cluster/sentinel-cluster-client-default/src/main/java/com/alibaba/csp/sentinel/cluster/client/NettyTransportClient.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-cluster/sentinel-cluster-client-default/src/main/java/com/alibaba/csp/sentinel/cluster/client/handler/TokenClientPromiseHolder.java>
