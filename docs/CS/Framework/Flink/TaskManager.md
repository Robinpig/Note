## Introduction

TaskManager 是 Flink 集群的**工作节点（worker）**，是真正干活的 JVM 进程。它向集群提供计算资源（内存、CPU），接收 [JobManager](/docs/CS/Framework/Flink/JobManager.md) 部署下来的 Task 并执行，持有算子的实际状态，并负责数据在算子之间的交换（shuffle）。

每个 TaskManager 把自己的资源切成若干 **Slot（任务槽）**，注册给 ResourceManager 统一调度；一个作业并行子任务就运行在一个 Slot 中。根据资源管理器不同，TaskManager 可以是 Standalone 下固定数量启动，也可以在 Yarn/Kubernetes 上按需动态拉起。

## Slot

- Slot 是 TaskManager 资源调度的最小单位。`taskmanager.numberOfTaskSlots` 决定一个 TM 切多少个 Slot，通常建议与机器 CPU 核数相当。
- Slot 主要**切分内存**，CPU 目前是按需共享的。
- 通过 **Slot Sharing（槽位共享）**，同一个作业的不同算子子任务（source/map/sink 的一条 pipeline）可以共享同一个 Slot，从而：
  - 让不同资源开销的算子（轻量 source、重量 window）均衡到各 Slot，提高利用率；
  - 一个 Slot 里串起一条完整算子链，减少跨网络/线程的数据传递。
- 需要隔离时可用 `slotSharingGroup()` 把算子划到不同共享组，强制分配到不同 Slot。

## Task Execution

- JobMaster 把 ExecutionGraph 中的 ExecutionVertex 部署到 TaskManager，对应一个 **Task**；一个 Task 内部运行一条 **operator chain**（多个算子由同一线程以函数调用方式串联执行）。
- Task 的生命周期大致：`DEPLOYING → INITIALIZING → RUNNING → FINISHED`，异常时进入 `FAILED/CANCELING/CANCELED`。
- Task 通过 `StreamTask` / `OneInputStreamTask` / `SourceStreamTask` 等运行时载体驱动内部 `StreamOperator`，而 Operator 再调用用户写的 `Function`（这是 Flink 最小数据处理单元）。
- 输入由 InputGate 拉取/接收、经算子链处理后由 RecordWriter 输出，形成事件驱动的主循环 `processInput()`。

## Data Exchange and Shuffle

TaskManager 提供运行时的网络数据交换环境（主笔记里的 Shuffle Environment / Network Manager）：

- 上游 Task 的 `RecordWriter` → ResultPartition / ResultSubpartition → 经 **Netty** 网络通道 → 下游 Task 的 **InputGate / InputChannel**。
- 采用**信用制（credit-based）流控**：下游按 channel 给 credit，上游有 credit 才发数据，天然实现背压（背压一路传导回 Source）。
- 同一个 TaskManager 内的 Task 之间可走**本地通道（local channel）**，直接在内存传递，避免网络与序列化。
- 网络依赖 Netty + 自建 buffer pool（以 `NetworkBufferPool` 管理一批 `MemorySegment` 作为网络内存段），相关参数集中在 `taskmanager.network.memory.*`。
- 批模式还支持阻塞式 / sort 风格 shuffle（先落盘或存内存再给下游拉取），以支持大批量、可中断的批处理。

## State and Checkpoint

TaskManager **持有真正的状态**（算子状态/键控状态），状态后端（HashMapStateBackend 存堆内 + EmbeddedRocksDBStateBackend 落本地 RocksDB）运行在 Task 侧。

Checkpoint 由 JobMaster 的 CheckpointCoordinator 中央触发，但**快照动作在 TaskManager 上完成**：

1. Coordinator 注入 checkpoint barrier 随数据流向下游；
2. Task 对齐/非对齐各输入流的 barrier（alignment / unaligned checkpoint）；
3. 异步把当前状态快照到分布式存储（HDFS/S3 等），再向 JobMaster 回报 ack；
4. 所有 Task 都 ack 后该 checkpoint 才算完成。失败恢复时 Task 从最近 checkpoint 的状态位点重置。

## Memory Management

Flink 在 TaskManager 内做了精细的**自主内存管理**，这是它稳定与高性能的关键之一：

- 把内存明确划分为：Framework Heap/Off-Heap、Task Heap/Off-Heap、**Network**、**Managed Memory**、JVM Metaspace/Overhead 等区域（`process.size = total.flink.size + jvm.*`）。
- 大量内部数据（排序、哈希、RocksDB 批量写、缓存）使用基于 `MemorySegment` 的**堆外/托管内存**，减少 JVM GC 压力并避免大对象带来的停顿。
- Managed Memory 用于 RocksDB state backend、批模式的 sort/hash/shuffle 缓存等，可按比例配置。

## Actor / RPC

较新 Flink 已用 **Akka/Pekko（Actor 模型）+ RPC** 承载 TaskManager 与 JobManager 之间的控制消息（TaskManagerRunner 注册、心跳、Task 部署/取消），数据通路则单独走 Netty，控制面与数据面分离。TaskManager 启动后向 ResourceManager 注册，并通过心跳维持存活与 Slot 状态同步。

## Links

- [Flink](/docs/CS/Framework/Flink/Flink.md)
- [JobManager](/docs/CS/Framework/Flink/JobManager.md)
- [Dataflow](/docs/CS/Framework/Flink/Dataflow.md)
- [Client](/docs/CS/Framework/Flink/Client.md)

## References

1. [Flink Architecture - Task Slots and Resources](https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/flink-architecture/#task-slots-and-resources)
2. [Flink Docs - Task Lifecycle](https://nightlies.apache.org/flink/flink-docs-stable/docs/internals/task_lifecycle/)
3. [Flink Docs - Network / Shuffle Service](https://nightlies.apache.org/flink/flink-docs-stable/docs/ops/networking/overview/)
4. [Flink Docs - Memory Configuration](https://nightlies.apache.org/flink/flink-docs-stable/docs/deployment/memory/mem_setup/)
