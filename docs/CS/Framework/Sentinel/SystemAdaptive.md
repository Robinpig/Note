## Introduction

系统自适应保护（System Adaptive Protection）从**整体机器维度**出发，在系统濒临过载前自动拒绝流量，维持高吞吐的同时保证可靠性。它由链上的 `SystemSlot` 执行，仅对**入流量**（`EntryType.IN`）生效。其思想借鉴 **TCP BBR**：不单看某个指标（如系统 load），而是平衡「系统能处理的请求量」与「被允许放行的请求量」。

> [!NOTE]
> 与 [流量控制 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md)、[熔断降级 CircuitBreaker](/docs/CS/Framework/Sentinel/CircuitBreaker.md) 针对「单个资源」不同，系统规则是**全局**的，作用在 `Constants.ENTRY_NODE` 这一全局入口统计节点上。

## SystemRule 维度

`SystemRule` 提供五类全局保护项：

| 维度 | 字段 | 含义 |
| :--- | :--- | :--- |
| 系统负载 | `highestSystemLoad` | 系统 `load1` 阈值（Linux 下取 `/proc/loadavg` 的 1 分钟负载） |
| CPU 使用率 | `highestCpuUsage` | CPU 使用率阈值（0~1） |
| 全局入口 QPS | `qps` | 全局入流量 QPS 上限 |
| 全局平均 RT | `avgRt` | 全局平均响应时间上限 |
| 全局最大并发 | `maxThread` | 全局入流量最大并发线程数上限 |

> [!WARNING]
> 系统规则**只对 `EntryType.IN` 的入口流量生效**；出口调用（`EntryType.OUT`，如服务作为客户端去调别人）不受系统规则限制，否则会造成「自己被别人拖垮还反向影响自身出口」的错乱。

## 负载保护原理（BBR 思路）

负载保护条件（两者**同时满足**才拦截）：

1. 当前系统 `load1` **超过** `highestSystemLoad`；
2. 当前并发线程数 **超过** 系统处理能力估算值：`thread count > minRt * maxQps`。

其中 `minRt * maxQps` 是「在稳态 RT 下，系统能安全承载的最大并发」的近似。仅当负载已高且并发确实逼近容量上限时才拒绝，避免「负载高但还能扛」时白白限流，也避免「负载低但并发失控」时放任。

对于非负载类的其余维度（CPU、QPS、RT、线程数），`SystemSlot` 直接按对应阈值判断是否拦截，逻辑更直接。

## 配置示例

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

## Links

- [Sentinel 枢纽](/docs/CS/Framework/Sentinel/Sentinel.md)
- [架构与工作原理](/docs/CS/Framework/Sentinel/Architecture.md)
- [Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)
- [流量控制 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md)
- [统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)

## References

1. [System Adaptive Protection (官方文档)](https://sentinelguard.io/en-us/docs/system-adaptive-protection.html)
