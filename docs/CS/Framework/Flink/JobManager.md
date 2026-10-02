## Introduction

JobManager 是 Flink 集群的**管理节点（master）**，负责接收并执行来自 [Client](/docs/CS/Framework/Flink/Client.md) 提交的 JobGraph，协调、调度整个作业，并管理集群资源。集群启动后至少有一个 JobManager 和多个 [TaskManager](/docs/CS/Framework/Flink/TaskManager.md)，三者都是独立 JVM 进程。

从 Flink 1.x 起，"JobManager" 是一个逻辑概念，内部由三个主要组件构成：**Dispatcher、ResourceManager、JobMaster**。在 Session 模式下一个 JobManager 进程可同时服务多个作业（每个作业一个 JobMaster）；在 Per-Job/Application 模式下通常一个作业独享一个 JobManager。

## Components

### Dispatcher

- 提供一个 **REST 接口**用来接收 Client 提交的应用（也因此跨版本、便于穿透防火墙）。
- 为每一个新提交的作业**启动一个新的 JobMaster**。
- 启动并托管 **Web UI**，方便展示和监控作业执行信息；同时负责作业的持久化（job graph store）与历史归档。

### ResourceManager

- 负责集群**资源的分配与管理**，在一个 Flink 集群中只有一个。
- 管理注册上来的 TaskManager 及其空闲 Slot（TaskExecutor 注册 slot 到 RM）。
- 当 JobMaster 申请资源、现有 Slot 不足时，向底层资源平台**动态申请新的 TaskManager**：

  - Standalone：资源是固定预启动的，RM 只能分配已注册的 Slot，无法弹性扩容；
  - [Yarn](/docs/CS/Framework/Hadoop/Yarn.md)：申请新的 TaskManager container；
  - Kubernetes：启动新的 TaskManager Pod。
- 回收长时间空闲的 TaskExecutor 以释放资源。

### JobMaster

- 作业级别的核心协调者，一个作业对应一个 JobMaster。
- 把接收到的 **JobGraph 转换成 ExecutionGraph**（按并行度把 JobVertex 展开为多个 ExecutionVertex）。
- 向 **ResourceManager 申请执行任务所需的 Slot**；拿到足够资源后，把 ExecutionGraph 的各个 ExecutionVertex 以 Task 的形式**部署（deploy）到 TaskManager** 上。
- 运行期间负责所有需要**中央协调**的工作，最典型的是 **Checkpoint 协调（CheckpointCoordinator）**：周期性触发检查点、收集各 Task 的 ack、在所有任务成功后把检查点标记为 complete，从而实现 exactly-once 状态一致性。
- 还负责任务失败后的重启策略、故障恢复（从最近 checkpoint 恢复）、作业状态机（CREATED→RUNNING→FAILING/RESTARTING→…→FINISHED/CANCELED）。

## Job Lifecycle

```
Client 提交 JobGraph
      -> Dispatcher 接收并启动 JobMaster
      -> JobMaster: JobGraph -> ExecutionGraph
      -> JobMaster 向 ResourceManager 申请 Slot
      -> ResourceManager 分配/启动 TaskManager，TaskManager 提供 Slot
      -> JobMaster 将 ExecutionVertex 部署为 Task
      -> Task 在 TaskManager 上执行，定期向 JobMaster 汇报状态/Checkpoint ack
      -> 作业结束（FINISHED）或失败（触发重启/恢复）
```

图从 StreamGraph 到 ExecutionGraph 的演进细节见 [Dataflow](/docs/CS/Framework/Flink/Dataflow.md)。

## High Availability

生产环境 JobManager 必须做高可用，避免单点：

- 多个 JobManager 候选，基于 **ZooKeeper**（或 Kubernetes leader election）选主，Dispatcher/ResourceManager/JobMaster 各自有 leader latch。
- 关键元数据（已完成的 checkpoint 位置、作业状态、JobGraph）写入高可用存储（如 HDFS/S3 + ZK），主节点故障后 standby 节点接管并从最近 checkpoint 恢复。

## JobManager vs TaskManager

| 维度 | JobManager（master） | TaskManager（worker） |
| ---- | ---- | ---- |
| 数量 | 至少 1 个（HA 下多候选选主） | 多个 |
| 职责 | 接收作业、调度、Checkpoint 协调、资源管理 | 真正执行 Task、缓存/交换数据、管理状态 |
| 资源抽象 | 管理 Slot 分配 | 把内存/CPU 切成 Slot 提供给集群 |
| 状态 | 协调态（checkpoint 元数据） | 持有每个算子的实际 keyed/operator state |

## Links

- [Flink](/docs/CS/Framework/Flink/Flink.md)
- [Client](/docs/CS/Framework/Flink/Client.md)
- [TaskManager](/docs/CS/Framework/Flink/TaskManager.md)
- [Dataflow](/docs/CS/Framework/Flink/Dataflow.md)
- [Yarn](/docs/CS/Framework/Hadoop/Yarn.md)

## References

1. [Flink Architecture](https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/flink-architecture/)
2. [Flink Docs - JobManager High Availability](https://nightlies.apache.org/flink/flink-docs-stable/docs/deployment/ha/overview/)
3. [Flink Docs - Task Failure Recovery](https://nightlies.apache.org/flink/flink-docs-stable/docs/ops/state/task_failure_recovery/)
