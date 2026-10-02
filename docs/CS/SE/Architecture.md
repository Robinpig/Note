## Introduction

软件架构是在系统早期最难变更的决策集合：组件如何切分、它们之间以什么协议与数据形态交互、哪些能力中心化、哪些下沉。架构的目标不是追求"先进"，而是在给定约束（团队规模、流量、变更频率、预算）下管理复杂度与权衡——正如《Fundamentals of Software Architecture》所强调的：**架构 = 系统结构 + 架构特征（"-ilities"）**，即不仅是组件图，还包括对可用性、可扩展性、可维护性、延迟等非功能属性的持续保障。

## 架构风格谱系

| 风格 | 核心组织方式 | 适用/代价 |
|------|-------------|-----------|
| 单体分层（Layered） | 表现层→业务层→DAO→DB | 简单直接；层间易退化为贫血大泥球 |
| 六边形/端口适配器 | 核心领域不依赖外围，通过 port/interface 与 DB、MQ、HTTP 适配 | 领域可单测、技术设施可替换；与 [DDD](/docs/CS/SE/DDD.md) 天然搭配 |
| 管道-过滤器 | 数据经一系列处理阶段 | 编译链路、ETL、Netty pipeline |
| SOA | 粗粒度服务 + ESB 编排 | 重治理，适合传统企业集成 |
| 微服务 | 按业务能力切分、独立部署、去中心化数据 | 扩展性与自治；换来分布式复杂度（见下） |
| 事件驱动 | 组件经消息总线异步解耦 | 削峰填谷、最终一致；调试与一致性变难 |
| 插件化 | 内核 + 可装载扩展 | IDE、规则平台；内核稳定性要求高 |
| Serverless | 函数粒度按需运行，无服务器管理 | 突发型任务；冷启动与厂商绑定，见 [Serverless](/docs/CS/SE/Serverless.md) |

## 微服务的本质权衡

微服务解决的是**组织与变更速度**问题（康威定律：系统结构镜像组织沟通结构），而不是性能银弹。它把进程内调用变成网络调用，必须直面：服务发现（[registry](/docs/CS/SE/registry.md)）、API 网关、配置中心、分布式事务（[Saga/Seata](/docs/CS/SE/Transaction.md)）、容错（[熔断](/docs/CS/SE/CircuitBreaker.md)/限流）、链路追踪、灰度发布、可观测性。判断标准：团队是否大到单体发布互相阻塞、各模块扩展节奏是否真的不同——小团队用模块化单体（modular monolith）往往更优。

## 架构视图

一个"架构"需要多个视图描述，单一类图说不清系统：

- **逻辑视图**：模块/领域划分与依赖（六边形、DDD 限界上下文）；
- **运行时视图**：进程、调用链、同步异步（时序图）；
- **物理/部署视图**：节点、机房、网络边界、容器编排（[K8s](/docs/CS/Container/k8s/K8s.md)）；
- **数据视图**：库表归属、数据流向、缓存与一致性策略；
- C4 模型把沟通分四层：Context（系统在世界中的位置）→ Container（进程/服务）→ Component（模块）→ Code。

## 关键架构决策原则

- **关注点分离 / 高内聚低耦合**：沿变化频率与业务能力切分，而非技术分层切（只有 Controller/Service/DAO 包是技术切分）。
- **依赖方向指向稳定与抽象**：依赖倒置，核心不依赖外围框架。
- **CAP 与一致性取舍**：分区容忍不可放弃，CP（一致性优先，如 etcd/ZooKeeper）还是 AP（可用性优先）按业务选择，见分布式共识相关笔记。
- **演进式架构**：用适配层（anti-corruption layer）、特性开关、演进式数据库设计（expand-migrate-contract）让大变更可分阶段安全完成。
- **量化而非感觉**：架构决策要用架构特征指标支撑（可用性 SLA、P99 延迟、部署频率/变更前置时间/MTTR 等 DORA 指标）。

## 与设计模式的关系

设计模式（[代理](/docs/CS/DesignPatterns/ProxyPattern.md)、策略等）解决组件内部的局部设计问题；架构模式决定组件边界与协作方式。两者同属"可复用决策"，但粒度与变更成本完全不同：一个模式用错可以局部重构，架构选错可能要多年偿还。

## Links

- [DDD](/docs/CS/SE/DDD.md)
- [SystemDesign](/docs/CS/SE/SystemDesign.md)
- [Engineering](/docs/CS/SE/Engineering.md)
- [Transaction](/docs/CS/SE/Transaction.md)
- [CircuitBreaker](/docs/CS/SE/CircuitBreaker.md)
- [Clean Code](/docs/CS/SE/Clean_Code.md)

## References

1. [Software Architecture Guide - Martin Fowler](https://martinfowler.com/architecture/)
2. [The Twelve-Factor App](https://12factor.net/)
