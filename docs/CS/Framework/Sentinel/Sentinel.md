## Introduction

Sentinel 是面向分布式、多语言异构化服务架构的流量治理组件，主要以流量为切入点，从流量路由、流量控制、流量整形、熔断降级、系统自适应过载保护、热点流量防护等多个维度来帮助开发者保障微服务的稳定性。

- core
- dashboard
- adapter
- cluster
- transport
- extension



### Quick Start

1. Run [Sentinel Dashboard](https://sentinelguard.io/en-us/docs/dashboard.html)

2. [Quick Start](https://sentinelguard.io/en-us/docs/quick-start.html)

```xml
<dependency>
    <groupId>com.alibaba.cloud</groupId>
    <artifactId>spring-cloud-starter-alibaba-sentinel</artifactId>
    <version>x.y.z.RELEASE</version>
</dependency>
```

```properties


spring.cloud.sentinel.transport.dashboard = localhost:8080
```

3. Test using JMeter

- [How Sentinel works](/docs/CS/Framework/Spring_Cloud/Sentinel)
- [CircuitBreaker](/docs/CS/Framework/Spring_Cloud/Sentinel/CircuitBreaker.md)



## 原理

Sentinel 的核心原理可以高度概括为：**基于上下文的调用链路追踪 + 责任链（Slot Chain）拦截架构 + 滑动窗口度量统计 + 策略化流控/熔断算法 + 热更新规则管理**



Sentinel通过AspectJ切入接口 为其添加@Around通知 并使用try-catch包裹



在 Sentinel 的世界中，万物都是可以被保护的“资源”，当一个外部请求想要访问 Sentinel 的资源时，便会创建一个 Entry 对象。
每一个 Entry 对象都要过五关斩六将，经过 Slot 链路的层层考验最终完成自己的业务，你可以把 Slot 当成是一类完成特定任务的“Filter”，这是一种典型的职责链设计模式



Sentinel 采用 **责任链模式** 将校验逻辑解耦。默认 Slot 执行顺序如下（ `com.alibaba.csp.sentinel.slotchain.DefaultProcessorSlotChain` 初始化）

```
NodeSelectorSlot → ClusterBuilderSlot → LogSlot → StatisticSlot → AuthoritySlot → SystemSlot → FlowSlot → DegradeSlot
```

责任链

```java
public abstract class AbstractLinkedProcessorSlot<T> implements ProcessorSlot<T> {
    private AbstractLinkedProcessorSlot<T> next;
    
    public void fireEntry(Context context, ResourceWrapper resourceWrapper, Object obj, int count, boolean prioritized, Object... args) {
        if (next != null) {
            next.transformEntry(context, resourceWrapper, obj, count, prioritized, args);
        }
    }
}
```

- 每个 Slot 实现 `ProcessorSlot` 接口，`fireEntry()` 负责向下一个节点传递。
- 若某个 Slot 校验失败（如触发流控），会抛出 `BlockException`，中断链路并返回给调用方。
- `entry()` 执行完毕后必须调用 `entry.exit()`，触发 `fireExit()` 完成统计回滚与上下文清理。

分布在 SlotChain 里面的各个 Slot 各司其职，为了保护 Sentinel 背后的“资源”，这些
Slot 通过互相配合的方式执行了各项检查任务。比如有的 Slot 用来统计数据，而有的 Slot
负责做限流降级检查

在这些 Slot 中，有几个是被专门用来收集数据的。比如，NodeSelectorSlot 被用来构建
当前请求的访问路径，它将上下游调用链串联起来，形成了一个服务调用关系的树状结
构。而 ClusterBuilderSlot 和 StatisticSlot 这两个 Slot 会从多个维度统计一些运行期信
息，比如接口响应时间、服务 QPS、当前线程数等等

- 



## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)


## References

1. [Sentinel Dashboard](https://sentinelguard.io/en-us/docs/dashboard.html)
2. [Quick Start](https://sentinelguard.io/en-us/docs/quick-start.html)
