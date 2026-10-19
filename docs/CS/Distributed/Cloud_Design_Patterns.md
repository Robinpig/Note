# Cloud Design Patterns

Cloud Design Patterns 是微软维护的**云/分布式系统架构模式目录**（在线持续更新，非单一系统），总结在生产系统中反复出现的设计套路。本库已在多处分散覆盖了其中的多数模式——本文只做**索引式串联**，把外部目录与本库已有专页对接，避免与 [Distributed.md](/docs/CS/Distributed/Distributed.md) 的 Engineering Implementation 章节重复深写。

Cloud Design Patterns 原文（外部参考，建议作为横向索引而非深写）：https://docs.microsoft.com/en-us/azure/architecture/patterns/

## Patterns Mapped to This Knowledge Base

- **重试 / 幂等 / 断路器（Retry / Idempotency / Circuit Breaker）**：与 [Seata](/docs/CS/Framework/Seata/Seata.md) 的事务保障、以及 Engineering Implementation 的"故障处理 限流 降级 熔断"呼应。分布式调用必须假设失败，重试要幂等、过载要熔断。
- **领导选举（Leader Election）**：本库 [Consensus](/docs/CS/Distributed/Consensus/Consensus.md)（Raft/Paxos）、[etcd](/docs/CS/Framework/etcd/README.md) 已覆盖；选主是分布式协调的经典问题。
- **CQRS / 事件溯源（Event Sourcing）**：与 [Databus](/docs/CS/Distributed/Databus.md)（CDC / 变更流）、[Wormhole](/docs/CS/Distributed/Wormhole.md)（pub-sub）、[Distributed Transaction Patterns](/docs/CS/Distributed/Distributed_Transaction_Patterns.md)（Saga 用事件编排）直接呼应——"以事件为中心"是云系统的主流解耦方式。
- **边车 / 大使 / 绞杀者（Sidecar / Ambassador / Strangler Fig）**：与 [Container](/docs/CS/Container/Container.md)（K8s sidecar）、Service Mesh（Istio / Higress）呼应；把横切能力（网络、观测、迁移）下沉到代理。
- **缓存旁路（Cache-Aside）**：与 Redis 等内存缓存对照，是缓解存储压力的经典模式。

## Why an Index, Not a Deep Dive

模式目录本身持续演进、体量庞大，且本库对每个实质模式已有专页。把"模式"逐条重写既重复又易过时；更好的做法是把它当作**外部参考入口**，本文只负责把读者引回本库对应的深度笔记。这与 KB"枢纽叙述性串联、不堆砌目录"的惯例一致。

## Links

- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Consensus](/docs/CS/Distributed/Consensus/Consensus.md)
- [Databus](/docs/CS/Distributed/Databus.md)
- [Container](/docs/CS/Container/Container.md)

## References

- Azure Cloud Design Patterns catalog: https://docs.microsoft.com/en-us/azure/architecture/patterns/
