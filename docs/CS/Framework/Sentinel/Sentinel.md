## Introduction

Sentinel 是面向分布式、多语言异构化服务架构的**流量治理**组件，以「流量」为切入点，从流量路由、流量控制、流量整形、熔断降级、系统自适应过载保护、热点流量防护等多个维度保障微服务稳定性。它承接了阿里巴巴近 15 年双十一大促的核心场景（秒杀、冷启动、消息削峰填谷、集群流控、实时熔断下游不可用服务）。

> [!NOTE] 版本基线
> 本库以 **Sentinel 1.8.x** 源码与官方文档为基线；最新稳定版 **1.8.8（2024-06）**，**2.0 仍处于 alpha**。1.8.0 是一次重要版本：重构了熔断降级（慢调用比例策略、半开探测恢复、熔断事件监听）。下文的 Slot 链、熔断状态机、系统规则均以 1.8.x 为准；2.0 在架构上做了较大演进，具体以官方 Release Notes 为准。

Sentinel 代码分为多个模块：

- **core**：核心库，包含 Slot 链、资源管理、规则匹配、统计与所有内置 Slot。
- **dashboard**：可视化的流量治理控制台，负责规则下发、实时监控、机器发现。
- **adapter**：适配层，把 Web、Dubbo、gRPC、Spring Cloud 等框架的资源自动埋点接入 Sentinel。
- **cluster**：集群流控模块，支持集群维度的统一限流（Token Server / Token Client）。
- **transport**：应用与 dashboard 之间的心跳与规则推送通道（默认本地起 8719 端口的 HTTP Server）。
- **extension**：扩展点，如数据源（Nacos、ZooKeeper、Apollo）持久化、自定义 Slot 等。

## 核心抽象

Sentinel 把「一切需要保护的」都抽象成 **资源（Resource）**：一次接口调用、一个方法、一段业务逻辑都可以是一个资源，用唯一名称标识。围绕资源，运行时有三个核心对象：

- **Entry**：每次访问资源都会创建一个 Entry，它要依次穿过 Slot 链；若某个 Slot 校验失败会抛出 `BlockException`，中断链路。
- **Context**：一次调用链路的上下文（入口节点、当前 Entry、来源 origin），通过 `ContextUtil.enter()` 创建并绑定到 `ThreadLocal`。
- **Node**：资源的实时统计节点，负责记录 QPS、RT、线程数、异常数等；Sentinel 用滑动窗口（LeapArray）做实时统计。

四种 Node 的区别、滑动窗口的实现见 [统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)。

## 工作原理总览

Sentinel 的核心原理可概括为：**基于上下文的调用链路追踪 + 责任链（Slot Chain）拦截 + 滑动窗口度量统计 + 策略化流控/熔断算法 + 热更新规则管理**。

资源被访问时，`SphU.entry()` 先解析出 Context 与 ProcessorSlotChain，再让 Entry 依次穿过链上的每个 Slot；每个 Slot 各司其职（建树、统计、鉴权、流控、熔断……），最后 `entry.exit()` 完成统计回滚。完整的入口流程、Context 构建、SlotChain 加载机制见 [架构与工作原理](/docs/CS/Framework/Sentinel/Architecture.md)；Slot 自身的机制与四个「基础设施 Slot」见 [Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)。

默认 Slot 执行顺序（`DefaultSlotChainBuilder` 按 `@Spi(order)` 排序加载）：

```
NodeSelectorSlot → ClusterBuilderSlot → LogSlot → StatisticSlot
→ AuthoritySlot → SystemSlot → ParamFlowSlot → FlowSlot → DegradeSlot
```

## 五大防护能力

Sentinel 的防护能力按 Slot 落在链上不同位置，可分为：

- **流量控制（Flow Control）**：基于 QPS 或并发线程数，支持直接/关联/链路三种流控模式与快速失败/预热/排队/预热+排队四种流控效果，由 `FlowSlot` 执行。四种流量整形控制器（含 WarmUp、RateLimiter）的实现细节见 [流量控制 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md)。
- **熔断降级（Circuit Breaking）**：基于慢调用比例、异常比例、异常数三种策略，用状态机（CLOSED/OPEN/HALF_OPEN）实现自动熔断与探测恢复，由 `DegradeSlot` 执行。详见 [熔断降级 CircuitBreaker](/docs/CS/Framework/Sentinel/CircuitBreaker.md)。
- **系统自适应保护（System Adaptive）**：从整体维度（load1、CPU、入口 QPS、平均 RT、最大并发）保护系统，借鉴 TCP BBR 思想，仅对入流量（`EntryType.IN`）生效，由 `SystemSlot` 执行。详见 [系统自适应保护 SystemAdaptive](/docs/CS/Framework/Sentinel/SystemAdaptive.md)。
- **授权控制（Authority）**：按调用来源（origin）配置黑名单/白名单，由 `AuthoritySlot` 执行。详见 [授权控制 Authority](/docs/CS/Framework/Sentinel/Authority.md)。
- **热点参数限流（Hotspot）**：对资源的热点参数（如商品 ID）做精细化限流，由 `ParamFlowSlot` 执行，是流控能力的参数级扩展，见 [流量控制 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md?id=热点参数限流) 中的说明。

## Quick Start

引入 Spring Cloud Alibaba Sentinel starter（版本随 Spring Cloud Alibaba 父子依赖对齐，不要写死 x.y.z）：

```xml
<dependency>
    <groupId>com.alibaba.cloud</groupId>
    <artifactId>spring-cloud-starter-alibaba-sentinel</artifactId>
</dependency>
```

配置 dashboard 地址（transport 端口 8719 是应用侧 HTTP Server，用于接收控制台下发的规则）：

```properties
spring.cloud.sentinel.transport.dashboard = localhost:8080
```

启动 [Sentinel Dashboard](https://sentinelguard.io/en-us/docs/dashboard.html)，对接口加 `@SentinelResource` 或直接依赖 starter 的自动埋点，再用 [Quick Start](https://sentinelguard.io/en-us/docs/quick-start.html) 中的方式做压测验证。规则既可以从控制台推送到本地内存，也可以托管到 Nacos 等外部数据源做持久化。

## Links

- [架构与工作原理](/docs/CS/Framework/Sentinel/Architecture.md)
- [统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)
- [Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)
- [流量控制 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md)
- [熔断降级 CircuitBreaker](/docs/CS/Framework/Sentinel/CircuitBreaker.md)
- [Spring Cloud Alibaba](/docs/CS/Framework/Spring_Cloud/Alibaba.md)

## References

1. [Sentinel 官网](https://sentinelguard.io/)
2. [Sentinel Dashboard](https://sentinelguard.io/en-us/docs/dashboard.html)
3. [Quick Start](https://sentinelguard.io/en-us/docs/quick-start.html)
4. [Sentinel Core 1.8.8 (Maven Central)](https://mvnrepository.com/artifact/com.alibaba.csp/sentinel-core/1.8.8)
