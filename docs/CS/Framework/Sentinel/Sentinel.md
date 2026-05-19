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


Sentinel通过AspectJ切入接口 为其添加@Around通知 并使用try-catch包裹



在 Sentinel 的世界中，万物都是可以被保护的“资源”，当一个外部请求想要访问 Sentinel 的资源时，便会创建一个 Entry 对象。
每一个 Entry 对象都要过五关斩六将，经过 Slot 链路的层层考验最终完成自己的业务，你可以把 Slot 当成是一类完成特定任务的“Filter”，这是一种典型的职责链设计模式

分布在 SlotChain 里面的各个 Slot 各司其职，为了保护 Sentinel 背后的“资源”，这些
Slot 通过互相配合的方式执行了各项检查任务。比如有的 Slot 用来统计数据，而有的 Slot
负责做限流降级检查


在这些 Slot 中，有几个是被专门用来收集数据的。比如，NodeSelectorSlot 被用来构建
当前请求的访问路径，它将上下游调用链串联起来，形成了一个服务调用关系的树状结
构。而 ClusterBuilderSlot 和 StatisticSlot 这两个 Slot 会从多个维度统计一些运行期信
息，比如接口响应时间、服务 QPS、当前线程数等等





## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)


## References

1. [Sentinel Dashboard](https://sentinelguard.io/en-us/docs/dashboard.html)
2. [Quick Start](https://sentinelguard.io/en-us/docs/quick-start.html)
