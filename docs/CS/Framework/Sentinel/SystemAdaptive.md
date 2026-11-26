## Introduction

系统自适应保护（System Adaptive Protection）不从单个资源出发，而是把**整机**当成一个管道：在入口处统计全局 QPS / RT / 并发 / 线程数，并周期性采集系统 load 与 CPU，在系统濒临过载前拒绝新请求，追求「高吞吐下仍不雪崩」。它由链上的 `SystemSlot` 执行，只对入流量（`EntryType.IN`）生效；思想借鉴 TCP BBR，不单看 load，而是用历史「最大成功 QPS × 最小 RT」估算系统容量，避免一高负载就无脑限流。

> 版本基线：Sentinel 1.8.10

> [!NOTE]
> 系统规则是**全局**的：所有维度都读 `Constants.ENTRY_NODE` 这个全局入口统计节点，而非某个资源的 `StatisticNode`。这与针对「单个资源」的 [流量控制](/docs/CS/Framework/Sentinel/FlowControl.md)、[熔断降级](/docs/CS/Framework/Sentinel/CircuitBreaker.md) 根本不同。`ENTRY_NODE` 的统计口径见 [统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)。

## The Slot Is Only a Forwarder

`SystemSlot` 本身极简，没有任何判断逻辑。`entry()` 只做两件事：调用 `SystemRuleManager.checkSystem(resourceWrapper, count)`，然后 `fireEntry` 把请求交给链上的下一个 Slot；`exit()` 则纯转发。

```java
@Spi(order = Constants.ORDER_SYSTEM_SLOT)
public class SystemSlot extends AbstractLinkedProcessorSlot<DefaultNode> {

    @Override
    public void entry(Context context, ResourceWrapper resourceWrapper, DefaultNode node, int count,
                      boolean prioritized, Object... args) throws Throwable {
        SystemRuleManager.checkSystem(resourceWrapper, count);
        fireEntry(context, resourceWrapper, node, count, prioritized, args);
    }

    @Override
    public void exit(Context context, ResourceWrapper resourceWrapper, int count, Object... args) {
        fireExit(context, resourceWrapper, count, args);
    }
}
```

也就是说，全部防护语义都在 `SystemRuleManager` 的静态方法中——Slot 只是一个可插拔的钩子（见 [Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)）。

源文件：`sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/system/SystemSlot.java`

## checkSystem: The Five Gates

`checkSystem` 是真正的判定入口，顺序是「开关 → 仅 IN → QPS → 线程 → RT → 负载 → CPU」，任一维度越界就抛 `SystemBlockException(resourceName, "维度")`。

```java
public static void checkSystem(ResourceWrapper resourceWrapper, int count) throws BlockException {
    if (resourceWrapper == null) {
        return;
    }
    // Ensure the checking switch is on.
    if (!checkSystemStatus.get()) {
        return;
    }

    // for inbound traffic only
    if (resourceWrapper.getEntryType() != EntryType.IN) {
        return;
    }

    // total qps
    double currentQps = Constants.ENTRY_NODE.passQps();
    if (currentQps + count > qps) {
        throw new SystemBlockException(resourceWrapper.getName(), "qps");
    }

    // total thread
    int currentThread = Constants.ENTRY_NODE.curThreadNum();
    if (currentThread > maxThread) {
        throw new SystemBlockException(resourceWrapper.getName(), "thread");
    }

    double rt = Constants.ENTRY_NODE.avgRt();
    if (rt > maxRt) {
        throw new SystemBlockException(resourceWrapper.getName(), "rt");
    }

    // load. BBR algorithm.
    if (highestSystemLoadIsSet && getCurrentSystemAvgLoad() > highestSystemLoad) {
        if (!checkBbr(currentThread)) {
            throw new SystemBlockException(resourceWrapper.getName(), "load");
        }
    }

    // cpu usage
    if (highestCpuUsageIsSet && getCurrentCpuUsage() > highestCpuUsage) {
        throw new SystemBlockException(resourceWrapper.getName(), "cpu");
    }
}
```

几点必须按源码读准：

- **前置两道闸**：`checkSystemStatus` 未开、`entryType != IN`，都直接 `return`，零判断。
- **QPS 带本次增量**：判定是 `passQps() + count > qps`，把当前这次请求的 `count` 也算进去，而不是只比历史值。
- **RT 字段映射**：规则里配置的是 `avgRt`（见 `SystemRule`），在 Manager 内部被存进 `maxRt`，所以判定写作 `avgRt() > maxRt`——名字不同但语义一致（全局平均响应时间上限）。
- **load 是「双条件」**：只有 `highestSystemLoadIsSet && 当前 load > 阈值` **且** `!checkBbr(currentThread)`（并发已逼近容量）才拦截，避免「负载高但还能扛」时误杀。
- **CPU 单条件**：只要 `highestCpuUsageIsSet && 当前 CPU > 阈值` 就拦截，不像 load 那样叠加 BBR。

源文件：`sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/system/SystemRuleManager.java`

## checkBbr: Little's Law in One Line

负载保护的第二道条件 `checkBbr` 是整套设计的核心，源码只有一行判断：

```java
private static boolean checkBbr(int currentThread) {
    if (currentThread > 1 &&
        currentThread > Constants.ENTRY_NODE.maxSuccessQps() * Constants.ENTRY_NODE.minRt() / 1000) {
        return false;
    }
    return true;
}
```

这就是 **Little's Law（利特尔法则）** 的等价形式：

> 系统中的并发数（in-flight） ≈ 吞吐率（QPS） × 平均时延（RT）

源码用两个历史极值来估算系统容量：`maxSuccessQps()` 是成功请求的历史最大 QPS（吞吐能力），`minRt()` 是历史最小 RT（无排队时的基准时延）。二者相乘得到「系统能安全承载的最大并发」。其中的 **`/ 1000` 是单位换算**：`minRt()` 以毫秒计，而 QPS 以秒计，除以 1000 把毫秒换成秒，结果才是无量纲的并发数。此外 `currentThread > 1` 是保护性门槛——并发低于 2 时不做 BBR 判断。

旧资料常把这里写成 `thread count > minRt * maxQps`：**既漏了 `/ 1000` 的单位换算，又把「最大成功 QPS」笼统写成 QPS**，不精确。按 1.8.10 源码，务必以 `maxSuccessQps() * minRt() / 1000` 为准。

> [!WARNING]
> 负载与 CPU 的采样来自 `SystemStatusListener`：后台线程每 1 秒用 `OperatingSystemMXBean` 取一次 `getSystemLoadAverage()`，CPU 取 `max(进程 CPU, 系统 CPU)`。因此这两个维度是**秒级滞后**的近似值，且 load 仅在类 Unix 系统有意义。源文件：`slots/system/SystemStatusListener.java`。

## Counterintuitive Defaults

`SystemRuleManager` 的字段默认值刻意设成「极值 + 未设置标记」，这正是「没有规则时几乎零开销」的原因：

```java
private static volatile double highestSystemLoad = Double.MAX_VALUE;
/**
 * cpu usage, between [0, 1]
 */
private static volatile double highestCpuUsage = Double.MAX_VALUE;
private static volatile double qps = Double.MAX_VALUE;
private static volatile long maxRt = Long.MAX_VALUE;
private static volatile long maxThread = Long.MAX_VALUE;
/**
 * mark whether the threshold are set by user.
 */
private static volatile boolean highestSystemLoadIsSet = false;
private static volatile boolean highestCpuUsageIsSet = false;
private static volatile boolean qpsIsSet = false;
private static volatile boolean maxRtIsSet = false;
private static volatile boolean maxThreadIsSet = false;

private static AtomicBoolean checkSystemStatus = new AtomicBoolean(false);
```

反直觉之处在于：

- 阈值默认是 `Double.MAX_VALUE` / `Long.MAX_VALUE`（不是 0），所以即使忘了 `xxxIsSet`，比较也永远不会因默认值触发。
- 每个维度都有独立的 `xxxIsSet` 标记，默认 `false`；`checkSystemStatus` 是 `AtomicBoolean(false)`。没有加载任何 `SystemRule`（或规则全为空）时，`checkSystem` 第一行开关判断就返回，Slot 形同虚设。
- 真正把开关打开的是 `loadSystemConf`：某个字段 `>= 0` 才算被设置、并把 `checkStatus` 置真；`configUpdate` 会先 `restoreSetting()` 复位全部阈值与标记，再逐条 `loadSystemConf`。多条规则的同名字段取 `Math.min`（最严格者生效）。
- 唯一的常驻成本是 `static` 块里那个每 1 秒采样一次的 `SystemStatusListener` 线程池——与请求链路上的判断无关。

`SystemRule` 自身五个字段（负值表示不检查）默认均为 `-1`：

```java
private double highestSystemLoad = -1;
/**
 * cpu usage, between [0, 1]
 */
private double highestCpuUsage = -1;
private double qps = -1;
private long avgRt = -1;
private long maxThread = -1;
```

## SystemRule Dimensions

`SystemRule` 提供五类全局保护项，字段与 Manager 内部变量的对应关系如下（源码字段以 `SystemRule` 为准）：

| 维度 | `SystemRule` 字段 | Manager 内部变量 | 含义 |
| :--- | :--- | :--- | :--- |
| 系统负载 | `highestSystemLoad` | `highestSystemLoad` | `load1` 阈值（类 Unix 取系统平均负载）；**需叠加 BBR 才拦截** |
| CPU 使用率 | `highestCpuUsage` | `highestCpuUsage` | CPU 使用率阈值，范围 `[0, 1]` |
| 全局入口 QPS | `qps` | `qps` | 全局入流量 QPS 上限（double） |
| 全局平均 RT | `avgRt` | `maxRt` | 全局平均响应时间上限（ms，long） |
| 全局最大并发 | `maxThread` | `maxThread` | 全局入流量最大并发线程数上限（long） |

> [!WARNING]
> 系统规则**只对 `EntryType.IN` 的入口流量生效**；出口调用（`EntryType.OUT`，如本服务作为客户端去调别人）不受系统规则限制——否则「自己被别人拖垮」还会反向影响自己的出口调用。`isValidRule` 还会拦截 `highestCpuUsage > 1` 的非法值并只打印警告、忽略该规则。

## Configuration Example

```java
List<SystemRule> rules = new ArrayList<>();
SystemRule rule = new SystemRule();
rule.setHighestSystemLoad(3.0);     // load1 超过 3.0 且并发逼近容量时保护
rule.setHighestCpuUsage(0.6);       // CPU 超过 60% 保护
rule.setQps(20);                    // 全局入口 QPS 上限 20
rule.setAvgRt(10);                  // 全局平均 RT 上限 10ms
rule.setMaxThread(10);              // 全局最大并发线程 10
rules.add(rule);
SystemRuleManager.loadRules(rules);
```

配置项含义：五个 setter 分别对应上表五个字段；`loadRules` 最终经 `currentProperty.updateValue(rules)` 触发 `configUpdate`，重置并重建全部阈值。字段传负值即表示清除该维度的检查。

## Links

- [Sentinel 枢纽](/docs/CS/Framework/Sentinel/Sentinel.md)
- [架构与工作原理](/docs/CS/Framework/Sentinel/Sentinel.md?id=architecture)
- [Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)
- [流量控制 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md)
- [统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)
- [授权控制 Authority](/docs/CS/Framework/Sentinel/Authority.md)

## References

- <https://sentinelguard.io/en-us/docs/system-adaptive-protection.html>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/system/SystemSlot.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/system/SystemRuleManager.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/system/SystemRule.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/system/SystemStatusListener.java>
