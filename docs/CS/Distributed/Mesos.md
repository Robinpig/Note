## Introduction

[Mesos](https://mesos.apache.org) 是一个**数据中心级资源调度内核**，设计哲学与 Linux 内核相似，只是抽象层级更高：Mesos kernel 跑在每台机器上，向上层应用（Hadoop、Spark、Kafka、Elasticsearch 等）提供跨整个数据中心 / 云的资源管理与调度 API。它用「两级调度（two-level scheduling）」在「全局资源视图」与「框架自主决策」之间取得平衡。

## 两级调度模型

Mesos 自身**不做任务级调度**，而是把资源以 **resource offer** 的形式主动「邀请」给上层框架（Framework），由框架决定是否接受并在拿到的资源上跑任务：

1. **Agent（slave）** 向 **Master** 汇报可用资源（CPU/内存/端口）。
2. **Master** 按策略（DRF，Dominant Resource Fairness 主导资源公平）把资源切片成 offer 发给注册框架。
3. **Framework 的 Scheduler** 收到 offer 后，自行决定启动（launch）哪些 Task（或拒绝 offer）。
4. **Executor** 在 Agent 上执行 Task，并向 Framework/Master 汇报状态。

这种「offer → 拒绝/接受」的悲观调度避免了中心调度器的全局锁，框架保有领域知识（如任务本地性），但代价是可能出现资源碎片与拒绝-重发开销。

## 组件与高可用

- **Master**：单点逻辑决策者，生产用 **ZooKeeper** 做领导者选举与状态共享实现 HA（类比 Raft/ZAB 的共识需求）。
- **Agent**：每台物理/虚拟机的守护进程，管理本地 Executor 与资源隔离（cgroups / 容器）。
- **Framework**：由 Scheduler + Executor 组成，每个分布式应用注册一个（如 Marathon 跑长服务、Chronos 跑批）。

## 与 Kubernetes / Borg 的对比

| 维度 | Mesos | Kubernetes |
|---|---|---|
| 调度哲学 | 两级（offer 给框架） | 一级集中调度（kube-scheduler） |
| 抽象 | 通用资源内核 + 框架生态 | 以 Pod/Deployment 为原生编排单位 |
| 生态 | 需 Marathon 等框架补长服务 | 自带完整编排（Service/Ingress/HPA） |
| 现状 | 社区降温，多迁 K8s | 事实标准 |

Mesos 的「资源内核」思想影响了后续调度器设计；如今多数场景被 Kubernetes 取代，但其在混合负载公平调度上的 DRF 思路仍有价值。

## Links

- [Distributed](/docs/CS/Distributed/Distributed.md)
- [Consensus](/docs/CS/Distributed/Consensus/Consensus.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Kubernetes](/docs/CS/Container/k8s/K8s.md)

## References

- [Mesos: A Platform for Fine-Grained Resource Sharing in the Data Center](https://www.usenix.org/conference/nsdi11/mesos-platform-fine-grained-resource-sharing-data-center)
- [Apache Mesos Official Site](https://mesos.apache.org)
