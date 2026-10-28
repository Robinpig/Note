## Introduction

Sentinel 采用**责任链模式**把校验逻辑解耦：每个 Slot 实现 `ProcessorSlot` 接口，按固定顺序处理 Entry，像一个完成特定任务的「Filter」。决策类 Slot（FlowSlot/DegradeSlot…）依赖前面 Slot 建好的调用树与实时统计，因此顺序很关键。本页讲 Slot 的通用机制与前四个「基础设施 Slot」（建树 + 统计）；授权、系统自适应、热点、流控、熔断五个「决策 Slot」分别见 [Authority](/docs/CS/Framework/Sentinel/Authority.md)、[SystemAdaptive](/docs/CS/Framework/Sentinel/SystemAdaptive.md)、[FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md)、[CircuitBreaker](/docs/CS/Framework/Sentinel/CircuitBreaker.md)。

## Slot 机制

`ProcessorSlot<T>` 定义入口 `entry()` 与出口 `exit()`。抽象基类 `AbstractLinkedProcessorSlot` 用 `next` 指针串成链，`fireEntry()` 负责把请求传递给下一个 Slot。

```java
public interface ProcessorSlot<T> {
    void entry(Context context, ResourceWrapper resourceWrapper, T param, int count,
               boolean prioritized, Object... args) throws Throwable;
    void exit(Context context, ResourceWrapper resourceWrapper, T param, int count, Object... args)
        throws Throwable;
}
```

```java
public abstract class AbstractLinkedProcessorSlot<T> implements ProcessorSlot<T> {
    private AbstractLinkedProcessorSlot<?> next = null;

    @Override
    public void fireEntry(Context context, ResourceWrapper resourceWrapper, Object obj, int count,
                          boolean prioritized, Object... args) throws Throwable {
        if (next != null) {
            next.transformEntry(context, resourceWrapper, obj, count, prioritized, args);
        }
    }

    @SuppressWarnings("unchecked")
    void transformEntry(Context context, ResourceWrapper resourceWrapper, Object o, int count,
                       boolean prioritized, Object... args) throws Throwable {
        entry(context, resourceWrapper, (T) o, count, prioritized, args);
    }
}
```

执行要点：

- 每个 Slot 实现 `ProcessorSlot`，`fireEntry()` 向下传递；`exit()` 阶段同样用 `fireExit()` 反向回滚。
- 若某 Slot 校验失败（如触发流控/熔断），抛出 `BlockException`，**中断链路**并返回调用方；`entry()` 抛异常后，`CtSph` 会回收 Entry 再向上抛出（见 [架构](/docs/CS/Framework/Sentinel/Architecture.md)）。
- `entry()` 完成后**必须调用 `entry.exit()`**，触发 `fireExit()` 完成统计回滚与 Context 清理。

## NodeSelectorSlot

`@Spi(order = -10000)`。职责：在当前 Context 下为资源创建/复用 `DefaultNode`，并把它挂到调用树上（`context.getLastNode().addChild(node)`），同时把自己设为 `context.curNode`。

值得注意的是它以 **context name 为 key**（而非 resource name）构建 `DefaultNode` 映射。因为同一资源全局共享同一条 Slot 链，进入该 Slot 时资源名一定相同、但 context name 可能不同；用 context name 作 key 才能把「同一资源在不同入口」区分开，从而构建出调用树。不同 Context 下访问同一资源会创建多个 `DefaultNode`。

```java
@Spi(isSingleton = false, order = Constants.ORDER_NODE_SELECTOR_SLOT) // -10000
public class NodeSelectorSlot extends AbstractLinkedProcessorSlot<Object> {
    private volatile Map<String, DefaultNode> map = new HashMap<String, DefaultNode>(10);

    @Override
    public void entry(Context context, ResourceWrapper resourceWrapper, Object obj, int count,
                      boolean prioritized, Object... args) throws Throwable {
        DefaultNode node = map.get(context.getName());
        if (node == null) {
            synchronized (this) {
                node = map.get(context.getName());
                if (node == null) {
                    node = new DefaultNode(resourceWrapper, null);
                    HashMap<String, DefaultNode> cacheMap = new HashMap<>(map.size());
                    cacheMap.putAll(map);
                    cacheMap.put(context.getName(), node);
                    map = cacheMap;
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
> 调用树可用 `curl http://localhost:8719/tree?type=root` 查看；`@Spi(isSingleton = false)` 表示每个资源有独立的 Slot 实例（因为 map 是按资源持有的）。

## ClusterBuilderSlot

`@Spi(order = -9000)`。职责：维护资源的运行统计（`ClusterNode`），并为每个来源 origin 创建独立的 origin 统计节点。一个资源**只有一个** `ClusterNode`，但可以有多个 `DefaultNode`。

```java
@Spi(isSingleton = false, order = Constants.ORDER_CLUSTER_BUILDER_SLOT) // -9000
public class ClusterBuilderSlot extends AbstractLinkedProcessorSlot<DefaultNode> {
    @Override
    public void entry(Context context, ResourceWrapper resourceWrapper, DefaultNode node, int count,
                      boolean prioritized, Object... args) throws Throwable {
        if (clusterNode == null) {
            synchronized (lock) {
                if (clusterNode == null) {
                    clusterNode = new ClusterNode(resourceWrapper.getName(), resourceWrapper.getResourceType());
                    HashMap<ResourceWrapper, ClusterNode> newMap = new HashMap<>(Math.max(clusterNodeMap.size(), 16));
                    newMap.putAll(clusterNodeMap);
                    newMap.put(node.getId(), clusterNode);
                    clusterNodeMap = newMap;
                }
            }
        }
        node.setClusterNode(clusterNode);
        // 若设置了 origin，为来源创建/获取对应统计 Node
        if (!"".equals(context.getOrigin())) {
            Node originNode = node.getClusterNode().getOrCreateOriginNode(context.getOrigin());
            context.getCurEntry().setOriginNode(originNode);
        }
        fireEntry(context, resourceWrapper, node, count, prioritized, args);
    }
}
```

## LogSlot

`@Spi(order = -8000)`。职责：在 Slot 链较靠前位置记录日志——当后续 Slot 抛出 `BlockException` 时，`LogSlot` 负责把「被限流/被熔断」的事件落到本地日志（默认 `sentinel-block.log`），便于排查。它不参与统计与决策，只做日志记录，因此是「基础设施 Slot」里最轻量的一个。

## StatisticSlot

`@Spi(order = -7000)`。职责：**实时统计**，是后续所有决策 Slot 的数据来源。进入时必须先 `fireEntry()` 让后续 Slot 完成校验，再根据结果分别累加：

- 请求通过：线程数 +1、pass 计数 +count（含 origin 节点与全局入口 `Constants.ENTRY_NODE`）。
- 抛出 `PriorityWaitException`（排队等待场景）：线程数 +1，但不计 pass。
- 抛出 `BlockException`：记录 block 计数，并把异常挂到当前 Entry。
- 其它内部异常：记录 error，不计入业务异常（业务异常应走 `Tracer.trace()`）。

```java
@Spi(order = Constants.ORDER_STATISTIC_SLOT) // -7000
public class StatisticSlot extends AbstractLinkedProcessorSlot<DefaultNode> {
    @Override
    public void entry(Context context, ResourceWrapper resourceWrapper, DefaultNode node, int count,
                      boolean prioritized, Object... args) throws Throwable {
        try {
            fireEntry(context, resourceWrapper, node, count, prioritized, args); // 先放行后续 Slot 校验
            node.increaseThreadNum();
            node.addPassRequest(count);
            if (context.getCurEntry().getOriginNode() != null) {
                context.getCurEntry().getOriginNode().increaseThreadNum();
                context.getCurEntry().getOriginNode().addPassRequest(count);
            }
            if (resourceWrapper.getEntryType() == EntryType.IN) {
                Constants.ENTRY_NODE.increaseThreadNum();
                Constants.ENTRY_NODE.addPassRequest(count);
            }
            // 触发 onPass 回调
        } catch (PriorityWaitException ex) {
            node.increaseThreadNum();
            // ... origin / ENTRY_NODE 线程数 +1，触发 onPass
        } catch (BlockException e) {
            context.getCurEntry().setBlockError(e);
            node.increaseBlockQps(count);          // 记录被拦截
            if (context.getCurEntry().getOriginNode() != null) {
                context.getCurEntry().getOriginNode().increaseBlockQps(count);
            }
            if (resourceWrapper.getEntryType() == EntryType.IN) {
                Constants.ENTRY_NODE.increaseBlockQps(count);
            }
            // 触发 onBlocked 回调
            throw e;
        } catch (Throwable e) {
            context.getCurEntry().setError(e);
            throw e;
        }
    }
}
```

统计底层是滑动窗口（[统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)），`addPassRequest` 最终落到 `LeapArray` 的当前 bucket 上做原子累加。

## Links

- [Sentinel 枢纽](/docs/CS/Framework/Sentinel/Sentinel.md)
- [架构与工作原理](/docs/CS/Framework/Sentinel/Architecture.md)
- [统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)
- [流量控制 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md)
- [熔断降级 CircuitBreaker](/docs/CS/Framework/Sentinel/CircuitBreaker.md)

## References

1. [How it works (官方 Wiki)](https://github.com/alibaba/Sentinel/wiki/How-it-works)
