## Introduction

本页梳理 Sentinel 的**运行时工作原理**：一次 `SphU.entry()` 从解析 Context、加载 Slot 链，到穿过 Slot 链完成统计与规则校验的完整链路。Slot 自身的机制与「基础设施 Slot」的实现见 [Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)，四种统计节点见 [统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)。

![How Sentinel works](https://user-images.githubusercontent.com/9434884/69955207-1e5d3c00-1538-11ea-9ab2-297efff32809.png)

## Entry / Exit 配对与 BlockException

概念上，任何需要保护（物理或逻辑）的资源都应被一个 Entry 包围。当任意规则阈值被触发时，该资源的请求会被拦截并抛出 `BlockException`；业务异常则用 `Tracer.trace()` 标记，不影响流控统计。

> [!WARNING]
> `SphU.entry()` 与 `entry.exit()` **必须在同一线程配对**，否则会抛出 `ErrorEntryFreeException`。这也是为什么异步场景下需要手动调用 `Entry.asyncExit()` 或借助 `AsyncEntry`。

```java
public void foo() {
    Entry entry = null;
    try {
        entry = SphU.entry("abc");     // 受保护资源，名称唯一
        // resource that need protection
    } catch (BlockException blockException) {
        // 触发限流/熔断等规则，在这里写降级逻辑
    } catch (Throwable bizException) {
        Tracer.trace(bizException);    // 业务异常标记，用于异常比例/异常数熔断
    } finally {
        if (entry != null) {
            entry.exit();
        }
    }
}
```

规则通过 `XxxRuleManager.loadRules()` 热加载，无需重启。Sentinel 内部对 `entry()` 的处理集中在 `CtSph`。

## CtSph.entry 流程

`CtSph` 是 `Sph` 接口的默认实现，核心方法 `entryWithPriority()` 做了五件事：

1. 从 `ThreadLocal` 取 `Context`，没有则使用默认 Context（`Constants.CONTEXT_DEFAULT_NAME`）。
2. 全局开关 `Constants.ON` 关闭、或 Context 超过上限进入 `NullContext`、或 Slot 链数量超过 `MAX_SLOT_CHAIN_SIZE` 时，**只创建 Entry 不做任何规则校验**（退化放行）。
3. 通过 `lookProcessChain()` 取该资源的 ProcessorSlotChain。
4. 创建 `CtEntry` 并调用 `chain.entry()` 穿过 Slot 链。
5. 任一 Slot 抛出 `BlockException` 时回收 Entry 并向上抛出。

```java
public class CtSph implements Sph {

    public static Entry entry(String name) throws BlockException {
        return Env.sph.entry(name, EntryType.OUT, 1, OBJECTS0);
    }

    @Override
    public Entry entry(String name, EntryType type, int count, Object... args) throws BlockException {
        return entry(new StringResourceWrapper(name, type), count, args);
    }

    private Entry entryWithPriority(ResourceWrapper resourceWrapper, int count, boolean prioritized, Object... args)
            throws BlockException {
        Context context = ContextUtil.getContext();
        if (context instanceof NullContext) {
            // NullContext 表示 Context 数量已超阈值，仅初始化 entry，不做规则校验
            return new CtEntry(resourceWrapper, null, context);
        }
        if (context == null) {
            context = InternalContextUtil.internalEnter(Constants.CONTEXT_DEFAULT_NAME);
        }
        // 全局开关关闭，不做规则校验
        if (!Constants.ON) {
            return new CtEntry(resourceWrapper, null, context);
        }
        ProcessorSlot<Object> chain = lookProcessChain(resourceWrapper);
        // 资源（Slot 链）数量超 MAX_SLOT_CHAIN_SIZE，不做规则校验
        if (chain == null) {
            return new CtEntry(resourceWrapper, null, context);
        }
        Entry e = new CtEntry(resourceWrapper, chain, context);
        try {
            chain.entry(context, resourceWrapper, null, count, prioritized, args);
        } catch (BlockException e1) {
            e.exit(count, args);
            throw e1;
        } catch (Throwable e1) {
            RecordLog.info("Sentinel unexpected exception", e1);
        }
        return e;
    }
}
```

## Context 与 ContextUtil

`Context` 保存当前调用链路的元数据：根入口节点 `EntranceNode`、当前 Entry、当前统计 Node、来源 `origin`（用于按调用方分别限流，通常是服务消费方应用名或来源 IP）。每次 `SphU.entry()` 都发生在某个 Context 中，不显式调用 `ContextUtil.enter()` 时使用默认 Context。

`ContextUtil.enter(name, origin)` 把 Context 包进 `ThreadLocal`（每个线程一份），并与之绑定一个 `EntranceNode`。同一个 context name 全局共享同一个 `EntranceNode`。当 origin 过多时，会为「不同资源 × 不同 origin」创建大量 origin 统计节点，需要关注内存占用。

> [!WARNING]
> 每个不同的 origin 都会为资源创建独立的统计 Node，节点总数是 **distinct 资源名 × distinct origin**。origin 来源过多（如按 IP 维度）时内存放大明显，应谨慎选择 origin 粒度。

```java
public class ContextUtil {
    // 存放在 ThreadLocal，便于访问
    private static ThreadLocal<Context> contextHolder = new ThreadLocal<>();

    // 保存所有 EntranceNode，每个 context name 对应一个
    private static volatile Map<String, DefaultNode> contextNameNodeMap = new HashMap<>();
    private static final ReentrantLock LOCK = new ReentrantLock();
    private static final Context NULL_CONTEXT = new NullContext();

    public static Context enter(String name, String origin) {
        if (Constants.CONTEXT_DEFAULT_NAME.equals(name)) {
            throw new ContextNameDefineException("The default context can't be permit to defined!");
        }
        return trueEnter(name, origin);
    }

    protected static Context trueEnter(String name, String origin) {
        Context context = contextHolder.get();
        if (context == null) {
            Map<String, DefaultNode> localCacheNameMap = contextNameNodeMap;
            DefaultNode node = localCacheNameMap.get(name); // 取 EntranceNode
            if (node == null) {
                if (localCacheNameMap.size() > Constants.MAX_CONTEXT_NAME_SIZE) {
                    setNullContext();
                    return NULL_CONTEXT;
                }
                LOCK.lock(); // 为新建 EntranceNode 加锁
                try {
                    node = contextNameNodeMap.get(name);
                    if (node == null) {
                        if (contextNameNodeMap.size() > Constants.MAX_CONTEXT_NAME_SIZE) {
                            setNullContext();
                            return NULL_CONTEXT;
                        }
                        node = new EntranceNode(new StringResourceWrapper(name, EntryType.IN), null);
                        Constants.ROOT.addChild(node);
                        // 用 volatile 写替换整个 Map，保证读线程无锁
                        Map<String, DefaultNode> newMap = new HashMap<>(contextNameNodeMap.size() + 1);
                        newMap.putAll(contextNameNodeMap);
                        newMap.put(name, node);
                        contextNameNodeMap = newMap;
                    }
                } finally {
                    LOCK.unlock();
                }
            }
            context = new Context(node, name);
            context.setOrigin(origin);
            contextHolder.set(context);
        }
        return context;
    }
}
```

```java
public class Context {
    private final String name;
    private DefaultNode entranceNode;  // 当前调用树的根（EntranceNode）
    private Entry curEntry;            // 当前处理点
    private String origin = "";        // 调用来源（服务消费方名或来源 IP）
    private final boolean async;
    // ...
}
```

## lookProcessChain 与 SlotChain 加载

同一个资源（`ResourceWrapper.equals()` 相等）**全局共享同一条 ProcessorSlotChain**，与处于哪个 Context 无关。Slot 链数量超过 `Constants.MAX_SLOT_CHAIN_SIZE` 时返回 `null`（退化放行）。

```java
public class CtSph implements Sph {
    // 同一资源共享同一条 ProcessorSlotChain
    private static volatile Map<ResourceWrapper, ProcessorSlotChain> chainMap
            = new HashMap<ResourceWrapper, ProcessorSlotChain>();

    ProcessorSlot<Object> lookProcessChain(ResourceWrapper resourceWrapper) {
        ProcessorSlotChain chain = chainMap.get(resourceWrapper);
        if (chain == null) {
            synchronized (LOCK) {
                chain = chainMap.get(resourceWrapper);
                if (chain == null) {
                    if (chainMap.size() >= Constants.MAX_SLOT_CHAIN_SIZE) {
                        return null;
                    }
                    chain = SlotChainProvider.newSlotChain();
                    Map<ResourceWrapper, ProcessorSlotChain> newMap = new HashMap<>(chainMap.size() + 1);
                    newMap.putAll(chainMap);
                    newMap.put(resourceWrapper, chain);
                    chainMap = newMap;
                }
            }
        }
        return chain;
    }
}
```

`SlotChainProvider` 通过 SPI 解析 `SlotChainBuilder`，默认实现 `DefaultSlotChainBuilder` 会把所有 `@Spi` 标注的 `ProcessorSlot` 按 `order` 排序后 `addLast` 进链。这意味着**自定义 Slot 只需实现 `ProcessorSlot` 并加 `@Spi(order=...)` 即可插入链中**。

```java
public final class SlotChainProvider {
    public static ProcessorSlotChain newSlotChain() {
        if (slotChainBuilder != null) {
            return slotChainBuilder.build();
        }
        slotChainBuilder = SpiLoader.of(SlotChainBuilder.class).loadFirstInstanceOrDefault();
        if (slotChainBuilder == null) {
            slotChainBuilder = new DefaultSlotChainBuilder();
        }
        return slotChainBuilder.build();
    }
}

@Spi(isDefault = true)
public class DefaultSlotChainBuilder implements SlotChainBuilder {
    @Override
    public ProcessorSlotChain build() {
        ProcessorSlotChain chain = new DefaultProcessorSlotChain();
        // 加载所有 ProcessorSlot，按 order 排序
        List<ProcessorSlot> sortedSlotList = SpiLoader.of(ProcessorSlot.class).loadInstanceListSorted();
        for (ProcessorSlot slot : sortedSlotList) {
            if (!(slot instanceof AbstractLinkedProcessorSlot)) {
                continue;
            }
            chain.addLast((AbstractLinkedProcessorSlot<?>) slot);
        }
        return chain;
    }
}
```

## 默认 Slot 链顺序

`DefaultSlotChainBuilder` 加载的全部内置 Slot 按 `order` 升序执行：

```
NodeSelectorSlot(-10000) → ClusterBuilderSlot(-9000) → LogSlot(-8000)
→ StatisticSlot(-7000) → AuthoritySlot(-6000) → SystemSlot(-5000)
→ ParamFlowSlot(-4000) → FlowSlot(-2000) → DegradeSlot(-1000)
```

前四个（`NodeSelectorSlot`/`ClusterBuilderSlot`/`LogSlot`/`StatisticSlot`）负责建树与统计，是后四个「决策 Slot」的数据基础；`AuthoritySlot`/`SystemSlot`/`ParamFlowSlot`/`FlowSlot`/`DegradeSlot` 负责各自的规则校验。每个 Slot 的职责与源码见 [Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)。

## Links

- [Sentinel 枢纽](/docs/CS/Framework/Sentinel/Sentinel.md)
- [统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)
- [Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)
- [流量控制 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md)
- [ThreadLocal](/docs/CS/Java/JDK/Concurrency/ThreadLocal.md)

## References

1. [How it works (官方 Wiki)](https://github.com/alibaba/Sentinel/wiki/How-it-works)
