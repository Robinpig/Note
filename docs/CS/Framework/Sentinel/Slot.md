## Introduction

Sentinel 采用**责任链模式（Chain of Responsibility）**把校验逻辑解耦：每个 Slot 实现 `ProcessorSlot` 接口，按固定顺序处理 Entry，像一个完成特定任务的「Filter」。决策类 Slot（FlowSlot/DegradeSlot…）依赖前面 Slot 建好的调用树与实时统计，因此顺序很关键。本页讲 Slot 的通用机制、core 默认链，以及四个「基础设施 Slot」（建树 + 日志 + 统计）；授权、系统自适应、流控、熔断五个「决策 Slot」分别见 [Authority](/docs/CS/Framework/Sentinel/Authority.md)、[SystemAdaptive](/docs/CS/Framework/Sentinel/SystemAdaptive.md)、[FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md)、[CircuitBreaker](/docs/CS/Framework/Sentinel/CircuitBreaker.md)。

> 版本基线：Sentinel 1.8.10

## The Slot Chain Mechanism

`ProcessorSlot<T>` 定义四个方法：入口 `entry()`、出口 `exit()`，以及链上传递用的 `fireEntry()` / `fireExit()`（`sentinel-core/src/main/java/com/alibaba/csp/sentinel/slotchain/ProcessorSlot.java`）。

```java
public interface ProcessorSlot<T> {

    /**
     * Entrance of this slot.
     *
     * @param context         current {@link Context}
     * @param resourceWrapper current resource
     * @param param           generics parameter, usually is a {@link com.alibaba.csp.sentinel.node.Node}
     * @param count           tokens needed
     * @param prioritized     whether the entry is prioritized
     * @param args            parameters of the original call
     * @throws Throwable blocked exception or unexpected error
     */
    void entry(Context context, ResourceWrapper resourceWrapper, T param, int count, boolean prioritized,
               Object... args) throws Throwable;

    /**
     * Means finish of {@link #entry(Context, ResourceWrapper, Object, int, boolean, Object...)}.
     *
     * @param context         current {@link Context}
     * @param resourceWrapper current resource
     * @param obj             relevant object (e.g. Node)
     * @param count           tokens needed
     * @param prioritized     whether the entry is prioritized
     * @param args            parameters of the original call
     * @throws Throwable blocked exception or unexpected error
     */
    void fireEntry(Context context, ResourceWrapper resourceWrapper, Object obj, int count, boolean prioritized,
                   Object... args) throws Throwable;

    /**
     * Exit of this slot.
     *
     * @param context         current {@link Context}
     * @param resourceWrapper current resource
     * @param count           tokens needed
     * @param args            parameters of the original call
     */
    void exit(Context context, ResourceWrapper resourceWrapper, int count, Object... args);

    /**
     * Means finish of {@link #exit(Context, ResourceWrapper, int, Object...)}.
     *
     * @param context         current {@link Context}
     * @param resourceWrapper current resource
     * @param count           tokens needed
     * @param args            parameters of the original call
     */
    void fireExit(Context context, ResourceWrapper resourceWrapper, int count, Object... args);
}
```

抽象基类 `AbstractLinkedProcessorSlot` 用 `next` 指针把 Slot 串成单向链：`fireEntry()` 经 `transformEntry()`（做一次泛型强转）调用下一个 Slot 的 `entry()`，`fireExit()` 则调用下一个 Slot 的 `exit()`。注意**每个 Slot 自己决定何时调用 `fireEntry()`**——这正是「先校验后统计」等顺序语义的实现点。

```java
public abstract class AbstractLinkedProcessorSlot<T> implements ProcessorSlot<T> {

    private AbstractLinkedProcessorSlot<?> next = null;

    @Override
    public void fireEntry(Context context, ResourceWrapper resourceWrapper, Object obj, int count, boolean prioritized, Object... args)
        throws Throwable {
        if (next != null) {
            next.transformEntry(context, resourceWrapper, obj, count, prioritized, args);
        }
    }

    @SuppressWarnings("unchecked")
    void transformEntry(Context context, ResourceWrapper resourceWrapper, Object o, int count, boolean prioritized, Object... args)
        throws Throwable {
        T t = (T)o;
        entry(context, resourceWrapper, t, count, prioritized, args);
    }

    @Override
    public void fireExit(Context context, ResourceWrapper resourceWrapper, int count, Object... args) {
        if (next != null) {
            next.exit(context, resourceWrapper, count, args);
        }
    }

    public AbstractLinkedProcessorSlot<?> getNext() {
        return next;
    }

    public void setNext(AbstractLinkedProcessorSlot<?> next) {
        this.next = next;
    }

}
```

执行要点：

- 每个 Slot 实现 `ProcessorSlot`，`fireEntry()` 向下传递；`exit()` 阶段用 `fireExit()` 反向传递。
- 若某 Slot 校验失败（如触发流控/熔断），抛出 `BlockException` 中断链路并返回调用方；此时 `CtSph.entryWithPriority()` 会捕获 `BlockException`、调用 `e.exit(count, args)` 回收 Entry 后再上抛（见 [架构与工作原理](/docs/CS/Framework/Sentinel/Sentinel.md?id=architecture)）。
- `entry()` 完成后**必须调用 `entry.exit()`** 触发 `fireExit()`，完成统计回滚与 Context 清理。

## The Default Slot Chain

core 默认链在 `sentinel-core/src/main/resources/META-INF/services/com.alibaba.csp.sentinel.slotchain.ProcessorSlot` 注册，由 `DefaultSlotChainBuilder` 通过 SPI **按 `@Spi(order)` 升序**加载并 `addLast()` 串链——顺序来自 order 常量，不是 service 文件里的书写顺序：

```java
    @Override
    public ProcessorSlotChain build() {
        ProcessorSlotChain chain = new DefaultProcessorSlotChain();

        List<ProcessorSlot> sortedSlotList = SpiLoader.of(ProcessorSlot.class).loadInstanceListSorted();
        for (ProcessorSlot slot : sortedSlotList) {
            if (!(slot instanceof AbstractLinkedProcessorSlot)) {
                RecordLog.warn("The ProcessorSlot(" + slot.getClass().getCanonicalName() + ") is not an instance of AbstractLinkedProcessorSlot, can't be added into ProcessorSlotChain");
                continue;
            }

            chain.addLast((AbstractLinkedProcessorSlot<?>) slot);
        }

        return chain;
    }
```

`SpiLoader.loadInstanceListSorted()` 内部用 `Collections.sort` + `Integer.compare(order1, order2)` 升序比较 `@Spi.order()`（无注解取 0）。order 常量集中在 `sentinel-core/src/main/java/com/alibaba/csp/sentinel/Constants.java`：

```java
    public static final int ORDER_NODE_SELECTOR_SLOT = -10000;
    public static final int ORDER_CLUSTER_BUILDER_SLOT = -9000;
    public static final int ORDER_LOG_SLOT = -8000;
    public static final int ORDER_STATISTIC_SLOT = -7000;
    public static final int ORDER_AUTHORITY_SLOT = -6000;
    public static final int ORDER_SYSTEM_SLOT = -5000;
    public static final int ORDER_FLOW_SLOT = -2000;
    public static final int ORDER_DEFAULT_CIRCUIT_BREAKER_SLOT = -1500;
    public static final int ORDER_DEGRADE_SLOT = -1000;
```

于是 core 默认链（1.8.10）为：

| order | Slot | 职责 |
| :-- | :-- | :-- |
| -10000 | `NodeSelectorSlot` | 建 `DefaultNode`、挂调用树 |
| -9000 | `ClusterBuilderSlot` | 建 `ClusterNode`、origin 统计 |
| -8000 | `LogSlot` | 被拦截时记录 `BlockException` 日志 |
| -7000 | `StatisticSlot` | 实时统计（QPS/RT/线程数/异常） |
| -6000 | `AuthoritySlot` | 授权（黑名单/白名单） |
| -5000 | `SystemSlot` | 系统自适应保护（仅 `EntryType.IN`） |
| -2000 | `FlowSlot` | 流量控制 |
| -1500 | `DefaultCircuitBreakerSlot` | 1.8 新熔断（慢调用比例/异常比例/异常数） |
| -1000 | `DegradeSlot` | 降级统计与熔断检查 |

> [!WARNING]
> service 文件里 `DegradeSlot` 写在 `DefaultCircuitBreakerSlot` 之前，但运行时按 order 升序，实际是 `DefaultCircuitBreakerSlot`(-1500) **先于** `DegradeSlot`(-1000)。另外，**`ParamFlowSlot` 不在 core 默认链**：它带 `@Spi(order = -3000)`，单独注册在 extension 模块 `sentinel-parameter-flow-control` 的 `META-INF/services/com.alibaba.csp.sentinel.slotchain.ProcessorSlot` 里；只有引入该依赖才会插入链中（落在 SystemSlot 与 FlowSlot 之间）。旧笔记把 ParamFlowSlot 列进 core 链是错的。

## Entry Point: CtSph

资源被访问时，`CtSph.entryWithPriority()` 解析出 Context 与 SlotChain，然后创建 Entry。`sentinel-core/.../CtSph.java`（1.8.10）中入口对象是**五个参数**的：

```java
        ProcessorSlot<Object> chain = lookProcessChain(resourceWrapper);

        /*
         * Means amount of resources (slot chain) exceeds {@link Constants.MAX_SLOT_CHAIN_SIZE},
         * so no rule checking will be done.
         */
        if (chain == null) {
            return new CtEntry(resourceWrapper, null, context);
        }

        Entry e = new CtEntry(resourceWrapper, chain, context, count, args);
        try {
            chain.entry(context, resourceWrapper, null, count, prioritized, args);
        } catch (BlockException e1) {
            e.exit(count, args);
            throw e1;
        } catch (Throwable e1) {
            // This should not happen, unless there are errors existing in Sentinel internal.
            RecordLog.info("Sentinel unexpected exception", e1);
        }
        return e;
```

> [!NOTE]
> 正确写法是 `new CtEntry(resourceWrapper, chain, context, count, args)`（`count` 为请求的令牌数，`args` 为原调用参数）；旧笔记里 3 参数的 `new CtEntry(resourceWrapper, chain, context)` 已过时。无链场景（NullContext / 全局开关关闭 / 链缓存超限）才走 3 参数的 `new CtEntry(resourceWrapper, null, context)`，不做规则校验。

## NodeSelectorSlot

`@Spi(isSingleton = false, order = -10000)`。职责：在当前 Context 下为资源创建/复用 `DefaultNode`，挂到调用树上（`((DefaultNode) context.getLastNode()).addChild(node)`），并把它设为 `context.curNode`。源码注释明确：**以 context name 为 map key，而不是 resource name**——同一资源全局共享同一条 Slot 链，进到本 Slot 时资源名必然相同、但 context name 可能不同；用 context name 作 key 才能区分「同一资源在不同入口」，从而建出调用树（不同 Context 下访问同一资源会创建多个 `DefaultNode`）。`sentinel-core/.../slots/nodeselector/NodeSelectorSlot.java`。

```java
@Spi(isSingleton = false, order = Constants.ORDER_NODE_SELECTOR_SLOT)
public class NodeSelectorSlot extends AbstractLinkedProcessorSlot<Object> {

    /**
     * {@link DefaultNode}s of the same resource in different context.
     */
    private volatile Map<String, DefaultNode> map = new HashMap<String, DefaultNode>(10);

    @Override
    public void entry(Context context, ResourceWrapper resourceWrapper, Object obj, int count, boolean prioritized, Object... args)
        throws Throwable {
        /*
         * It's interesting that we use context name rather resource name as the map key.
         *
         * Remember that same resource({@link ResourceWrapper#equals(Object)}) will share
         * the same {@link ProcessorSlotChain} globally, no matter in which context. So if
         * code goes into {@link #entry(Context, ResourceWrapper, DefaultNode, int, Object...)},
         * the resource name must be same but context name may not.
         *
         * If we use {@link com.alibaba.csp.sentinel.SphU#entry(String resource)} to
         * enter same resource in different context, using context name as map key can
         * distinguish the same resource. In this case, multiple {@link DefaultNode}s will be created
         * of the same resource name, for every distinct context (different context name) each.
         *
         * Consider another question. One resource may have multiple {@link DefaultNode},
         * so what is the fastest way to get total statistics of the same resource?
         * The answer is all {@link DefaultNode}s with same resource name share one
         * {@link ClusterNode}. See {@link ClusterBuilderSlot} for detail.
         */
        DefaultNode node = map.get(context.getName());
        if (node == null) {
            synchronized (this) {
                node = map.get(context.getName());
                if (node == null) {
                    node = new DefaultNode(resourceWrapper, null);
                    HashMap<String, DefaultNode> cacheMap = new HashMap<String, DefaultNode>(map.size());
                    cacheMap.putAll(map);
                    cacheMap.put(context.getName(), node);
                    map = cacheMap;
                    // Build invocation tree
                    ((DefaultNode) context.getLastNode()).addChild(node);
                }

            }
        }

        context.setCurNode(node);
        fireEntry(context, resourceWrapper, node, count, prioritized, args);
    }
}
```

> [!NOTE]
> `map` 用「copy-on-write + volatile 替换」而非并发容器：`synchronized` 内复制出 `cacheMap` 改完再整体替换 `map`，读路径无锁。调用树可用 `curl http://localhost:8719/tree?type=root` 查看；`@Spi(isSingleton = false)` 表示每个资源持有独立的 Slot 实例（因为 map 是按资源持有的）。

## ClusterBuilderSlot

`@Spi(isSingleton = false, order = -9000)`。职责：为资源创建全局唯一的 `ClusterNode`（汇总所有 Context 下的 `DefaultNode`），并设置到 `node.setClusterNode(clusterNode)`；若 Context 带 origin，再为该来源创建/获取独立统计节点挂到当前 Entry。一个资源**只有一个** `ClusterNode`，但可以有多个 `DefaultNode`。`sentinel-core/.../slots/clusterbuilder/ClusterBuilderSlot.java`。

```java
    @Override
    public void entry(Context context, ResourceWrapper resourceWrapper, DefaultNode node, int count,
                      boolean prioritized, Object... args)
        throws Throwable {
        if (clusterNode == null) {
            synchronized (lock) {
                if (clusterNode == null) {
                    // Create the cluster node.
                    clusterNode = new ClusterNode(resourceWrapper.getName(), resourceWrapper.getResourceType());
                    HashMap<ResourceWrapper, ClusterNode> newMap = new HashMap<>(Math.max(clusterNodeMap.size(), 16));
                    newMap.putAll(clusterNodeMap);
                    newMap.put(node.getId(), clusterNode);

                    clusterNodeMap = newMap;
                }
            }
        }
        node.setClusterNode(clusterNode);

        /*
         * if context origin is set, we should get or create a new {@link Node} of
         * the specific origin.
         */
        if (!"".equals(context.getOrigin())) {
            Node originNode = node.getClusterNode().getOrCreateOriginNode(context.getOrigin());
            context.getCurEntry().setOriginNode(originNode);
        }

        fireEntry(context, resourceWrapper, node, count, prioritized, args);
    }
```

## LogSlot

`@Spi(order = -8000)`。职责：在 Slot 链较靠前位置记录日志——`fireEntry()` 抛出 `BlockException` 时，用 `EagleEyeLogUtil.log(...)` 把「被哪个规则拦截、limitApp、origin、ruleId、count」落到日志（默认 `sentinel-block.log`），便于排查；它不参与统计与决策，只做记录。`sentinel-core/.../slots/logger/LogSlot.java`。

```java
@Spi(order = Constants.ORDER_LOG_SLOT)
public class LogSlot extends AbstractLinkedProcessorSlot<DefaultNode> {

    @Override
    public void entry(Context context, ResourceWrapper resourceWrapper, DefaultNode obj, int count, boolean prioritized, Object... args)
        throws Throwable {
        try {
            fireEntry(context, resourceWrapper, obj, count, prioritized, args);
        } catch (BlockException e) {
            EagleEyeLogUtil.log(resourceWrapper.getName(), e.getClass().getSimpleName(), e.getRuleLimitApp(),
                context.getOrigin(), e.getRule() != null ? e.getRule().getId() : null, count);
            throw e;
        } catch (Throwable e) {
            RecordLog.warn("Unexpected entry exception", e);
        }
    }
```

## StatisticSlot

`@Spi(order = -7000)`。职责：**实时统计**，是后续所有决策 Slot 的数据来源。进入时**先 `fireEntry()` 让后续 Slot 完成校验**，再根据结果分别累加；这正是「通过/排队/被拦截/内部错误」四条分支的来源。`sentinel-core/.../slots/statistic/StatisticSlot.java`。

```java
    @Override
    public void entry(Context context, ResourceWrapper resourceWrapper, DefaultNode node, int count,
                      boolean prioritized, Object... args) throws Throwable {
        try {
            // Do some checking.
            fireEntry(context, resourceWrapper, node, count, prioritized, args);

            // Request passed, add thread count and pass count.
            node.increaseThreadNum();
            node.addPassRequest(count);

            if (context.getCurEntry().getOriginNode() != null) {
                // Add count for origin node.
                context.getCurEntry().getOriginNode().increaseThreadNum();
                context.getCurEntry().getOriginNode().addPassRequest(count);
            }

            if (resourceWrapper.getEntryType() == EntryType.IN) {
                // Add count for global inbound entry node for global statistics.
                Constants.ENTRY_NODE.increaseThreadNum();
                Constants.ENTRY_NODE.addPassRequest(count);
            }

            // Handle pass event with registered entry callback handlers.
            for (ProcessorSlotEntryCallback<DefaultNode> handler : StatisticSlotCallbackRegistry.getEntryCallbacks()) {
                handler.onPass(context, resourceWrapper, node, count, args);
            }
        } catch (PriorityWaitException ex) {
            node.increaseThreadNum();
            if (context.getCurEntry().getOriginNode() != null) {
                // Add count for origin node.
                context.getCurEntry().getOriginNode().increaseThreadNum();
            }

            if (resourceWrapper.getEntryType() == EntryType.IN) {
                // Add count for global inbound entry node for global statistics.
                Constants.ENTRY_NODE.increaseThreadNum();
            }
            // Handle pass event with registered entry callback handlers.
            for (ProcessorSlotEntryCallback<DefaultNode> handler : StatisticSlotCallbackRegistry.getEntryCallbacks()) {
                handler.onPass(context, resourceWrapper, node, count, args);
            }
        } catch (BlockException e) {
            // Blocked, set block exception to current entry.
            context.getCurEntry().setBlockError(e);

            // Add block count.
            node.increaseBlockQps(count);
            if (context.getCurEntry().getOriginNode() != null) {
                context.getCurEntry().getOriginNode().increaseBlockQps(count);
            }

            if (resourceWrapper.getEntryType() == EntryType.IN) {
                // Add count for global inbound entry node for global statistics.
                Constants.ENTRY_NODE.increaseBlockQps(count);
            }

            // Handle block event with registered entry callback handlers.
            for (ProcessorSlotEntryCallback<DefaultNode> handler : StatisticSlotCallbackRegistry.getEntryCallbacks()) {
                handler.onBlocked(e, context, resourceWrapper, node, count, args);
            }

            throw e;
        } catch (Throwable e) {
            // Unexpected internal error, set error to current entry.
            context.getCurEntry().setError(e);

            throw e;
        }
    }
```

四个分支小结：

- **通过**：线程数 +1、pass +count，并同步到 origin 节点与全局入口 `Constants.ENTRY_NODE`（`EntryType.IN`），最后触发 `onPass` 回调。
- **`PriorityWaitException`**（排队等待场景）：线程数 +1，但**不计 pass**，仍触发 `onPass`。
- **`BlockException`**：`setBlockError(e)` + block 计数 +1，触发 `onBlocked` 后**重新抛出**。
- **其它 `Throwable`**：视为内部错误 `setError(e)` 后上抛，不计业务异常（业务异常应走 `Tracer.trace()`）。

`exit()` 里用 `recordCompleteFor()` 记录 RT / 成功数 / 异常（业务异常才 `increaseExceptionQps`），并在末尾 `fireExit()`——这是针对 issue #2374 的修复：

```java
    @Override
    public void exit(Context context, ResourceWrapper resourceWrapper, int count, Object... args) {
        Node node = context.getCurNode();

        if (context.getCurEntry().getBlockError() == null) {
            // Calculate response time (use completeStatTime as the time of completion).
            long completeStatTime = TimeUtil.currentTimeMillis();
            context.getCurEntry().setCompleteTimestamp(completeStatTime);
            long rt = completeStatTime - context.getCurEntry().getCreateTimestamp();

            Throwable error = context.getCurEntry().getError();

            // Record response time and success count.
            recordCompleteFor(node, count, rt, error);
            recordCompleteFor(context.getCurEntry().getOriginNode(), count, rt, error);
            if (resourceWrapper.getEntryType() == EntryType.IN) {
                recordCompleteFor(Constants.ENTRY_NODE, count, rt, error);
            }
        }

        // Handle exit event with registered exit callback handlers.
        Collection<ProcessorSlotExitCallback> exitCallbacks = StatisticSlotCallbackRegistry.getExitCallbacks();
        for (ProcessorSlotExitCallback handler : exitCallbacks) {
            handler.onExit(context, resourceWrapper, count, args);
        }

        // fix bug https://github.com/alibaba/Sentinel/issues/2374
        fireExit(context, resourceWrapper, count, args);
    }

    private void recordCompleteFor(Node node, int batchCount, long rt, Throwable error) {
        if (node == null) {
            return;
        }
        node.addRtAndSuccess(rt, batchCount);
        node.decreaseThreadNum();

        if (error != null && !(error instanceof BlockException)) {
            node.increaseExceptionQps(batchCount);
        }
    }
```

统计底层是滑动窗口（见 [统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)）：`addPassRequest()` → `ArrayMetric.addPass()` → `data.currentWindow()` 拿到当前 bucket 后 `wrap.value().addPass(count)` 做原子累加。

## Links

- [Sentinel 枢纽](/docs/CS/Framework/Sentinel/Sentinel.md)
- [架构与工作原理](/docs/CS/Framework/Sentinel/Sentinel.md?id=architecture)
- [统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)
- [流量控制 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md)
- [熔断降级 CircuitBreaker](/docs/CS/Framework/Sentinel/CircuitBreaker.md)
- [规则与动态数据源 RuleDataSource](/docs/CS/Framework/Sentinel/RuleDataSource.md)

## References

1. [ProcessorSlot.java](https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slotchain/ProcessorSlot.java)
2. [AbstractLinkedProcessorSlot.java](https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slotchain/AbstractLinkedProcessorSlot.java)
3. [DefaultSlotChainBuilder.java](https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/DefaultSlotChainBuilder.java)
4. [CtSph.java](https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/CtSph.java)
5. [NodeSelectorSlot.java](https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/nodeselector/NodeSelectorSlot.java)
6. [StatisticSlot.java](https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/statistic/StatisticSlot.java)
