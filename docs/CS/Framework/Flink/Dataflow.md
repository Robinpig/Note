## Introduction

Dataflow（数据流 / 数据传递模型）描述 Flink 作业中算子之间数据是如何流动的。Flink 的基本数据模型是**数据流与事件序列**，这与把数据看作一个个小批 RDD 的 Spark Streaming、以及把中间结果落盘的 MapReduce 有本质区别。

两条最直观的特征（沿用原笔记的观察）：

- **算子之间是 push（推）模型**：数据从上一个 operator 处理完后直接 push 给下一个 operator，事件驱动、流水式地在算子链里流动，而不是等上一阶段全部算完。
- **Shuffle 仍是推**：即便存在 shuffle（如 `keyBy`），Flink 也是由上游通过网络**主动推**给下游；这不同于 [MapReduce](/docs/CS/Framework/Hadoop/MapReduce.md) 模型里 Reduce 端主动从 Map 端**拉取（pull）**数据的方式。

正是这种原生的流式 push 执行，让同一个运行时既能处理无界流（streaming），也能处理有界流（batch，批被视为“有界的流”），实现批流一体。

> [!NOTE]
> 版本基线（2026-11-23 核实）：Flink **2.3.0**（tag `release-2.3.0`，commit `c0f8d1a1e09f209885a88f9c19ceb9d9e9870283`）。下文源码片段均取自该 tag，路径相对仓库根目录，不带行号。

## Graph Evolution

一个 Flink 作业从代码到物理执行要经过四层图的转换，前三步发生在 [Client](/docs/CS/Framework/Flink/Client.md) 与 [JobManager](/docs/CS/Framework/Flink/JobManager.md)。SQL / Table API 作业经过优化器后同样落到这四层图上（见 [Table_SQL](/docs/CS/Framework/Flink/Table_SQL.md)）：

1. **StreamGraph**：在 Client 端由用户 API 生成，是 DAG 的最初形态，节点对应每个算子 Transformation（`map`、`keyBy`、`window` 等），一一对应、不做合并。
2. **JobGraph**：Client 对 StreamGraph 做优化，把可以 chain 在一起的算子合并成一个 **JobVertex**，并加上中间数据集（IntermediateDataSet），是提交给集群的统一抽象（流/批都转成 JobGraph）。
3. **ExecutionGraph**：JobMaster 收到 JobGraph 后按**并行度**把每个 JobVertex 展开成多个 `ExecutionVertex`（每个就是一个可调度的子任务），是并行化后的“执行视图”。
4. **物理执行**：ExecutionVertex 以 Task 形式部署到 [TaskManager](/docs/CS/Framework/Flink/TaskManager.md) 的 Slot 中，Task 内部通过算子链真正处理数据。

```
API 调用 -> StreamGraph -> JobGraph(chain 优化) -> ExecutionGraph(按并行度展开) -> Task/Slot 物理执行
 Client                Client          JobManager                    TaskManager
```

## Source-Level Graph Mechanics

概念层面的四层边界之上，2.3 源码里有三个容易理解错的点：

- **JobGraph 不携带"当前并行度"的最终决定**：AdaptiveScheduler 在 REACTIVE 模式下会按可用资源重算并行度，`JobGraph` 里的值只是基准；
- **`ExecutionGraph` 是接口不是类**：2.3 源码里它是含 `attachJobGraph()` / `initializeJobVertex()` 的接口，具体实现由 scheduler 注入；
- **2.3 的 `JobGraph` 已经带 `ApplicationID`**：FLIP-549 的"应用一等公民"不是纯 UI 变化，它渗进了图模型的构造参数。

```dot
digraph GraphEvolution {
  rankdir=LR;
  node [shape=box, style=rounded];

  sg [label="StreamGraph\nClient: 算子 DAG\nTransformation 一一对应"];
  jg [label="JobGraph\nClient: chain 合并\nJobVertex + IntermediateDataSet\n(2.3 带 ApplicationID)"];
  ps [label="VertexParallelismStore\nScheduler: 并行度决策\n(REACTIVE 可重算)"];
  eg [label="ExecutionGraph\n接口: attachJobGraph\nExecutionJobVertex / ExecutionVertex"];
  task [label="物理 Task\nTaskManager Slot\noperator chain 线程"];

  sg -> jg [label=" StreamingJobGraphGenerator"];
  jg -> ps;
  ps -> eg [label=" ExecutionGraphFactory"];
  eg -> task [label=" deploy / TaskDeploymentDescriptor"];
}
```

### JobGraph: The Submission Contract

`JobGraph` 是 Client 与集群之间约定的统一数据结构，内部用 `LinkedHashMap<JobVertexID, JobVertex>` 存顶点，保持插入顺序：

```java
private final Map<JobVertexID, JobVertex> taskVertices =
        new LinkedHashMap<JobVertexID, JobVertex>();
```

2.3 的构造器签名已经把 ApplicationID 作为一等参数（旧的 `(jobId, jobName)` 重载还在，但底层都委托给三参版本，applicationId 传 null）：

```java
public JobGraph(String jobName) { this(null, null, jobName); }

/**
 * Constructs a new job graph with the given job ID (or a random ID, if {@code null} is passed),
 * the given application ID, the given name and the given execution configuration ...
 */
public JobGraph(@Nullable JobID jobId, @Nullable ApplicationID applicationId, String jobName) {
    this.jobID = jobId == null ? new JobID() : jobId;
    this.jobName = jobName == null ? "(unnamed job)" : jobName;
    this.applicationId = applicationId;
    // ... setExecutionConfig(new ExecutionConfig())
}
```

`addVertex()` 用 `put` 并返回被替换的旧顶点——重复 ID 会被静默替换（调用方负责保证唯一）：

```java
public void addVertex(JobVertex vertex) {
    final JobVertexID id = vertex.getID();
    JobVertex previous = taskVertices.put(id, vertex);
    // ...
}
```

拓扑序通过 `getVerticesSortedTopologicallyFromSources()` 从 source 递归 `addNodesThatHaveNoNewPredecessors()` 得出，说明 JobGraph 的拓扑关系由 JobVertex 之间的边表达，而不是靠数组下标。

### ExecutionGraph: Attached, Not Constructed

2.3 源码里 `ExecutionGraph` 是接口，其 javadoc 直接给出三层对象的定义：

> *The ExecutionJobVertex represents one vertex from the JobGraph (usually one operator) with all its parallel subtasks.* … *The ExecutionVertex represents one parallel subtask. For each ExecutionJobVertex, there is one ExecutionVertex per parallel subtask, identified by the ExecutionJobVertex and the index of the parallel subtask.*

图不是 new 出来的，而是把 JobGraph **挂上去**：

```java
void attachJobGraph(
        List<JobVertex> topologiallySorted,
        JobID jobID,
        long createTimestamp,
        int numJobsStoredInHistory,
        JobMetricGroup jobMetricGroup,
        VertexParallelismStore parallelismStore) throws JobException;
```

随后 `initializeJobVertex()` 带 createTimestamp 初始化每个顶点的时间统计，`notifyNewlyInitializedJobVertices()` 让图知道哪些顶点是新初始化的（用于增量建图 / 动态扩缩容）。

> [!NOTE]
> `attachJobGraph()` 的签名里已经带 `VertexParallelismStore`——并行度不再是 JobVertex 自带的固定属性，而是建图时从外部注入的决策结果。这是理解 AdaptiveScheduler 的前提。

### Parallelism: Two Stores

`AdaptiveScheduler` 明确区分两个并行度存储（源码注释写得非常清楚）：

- `computeVertexParallelismStore()`：**用于决定调度需求**，在 REACTIVE 模式下可以选与 JobGraph 不同的并行度；
- `computeVertexParallelismStoreForExecution()`：**用于真正建 ExecutionGraph**，在所有执行模式下都尊重 JobGraph 里设置的并行度。

```java
/**
 * Creates the parallelism store that should be used for determining scheduling requirements,
 * which may choose different parallelisms than set in the {@link JobGraph} depending on the
 * execution mode.
 */
private static VertexParallelismStore computeVertexParallelismStore(
        JobGraph jobGraph, SchedulerExecutionMode executionMode) {
    if (executionMode == SchedulerExecutionMode.REACTIVE) {
        return computeReactiveModeVertexParallelismStore(
                jobGraph.getVertices(), SchedulerBase::getDefaultMaxParallelism, true);
    }
    return SchedulerBase.computeVertexParallelismStore(jobGraph);
}
```

REACTIVE 模式会把并行度缩放到"刚好能跑起来"的规模；其他模式走 `SchedulerBase` 的常规计算。这也是为什么 reactive 模式下 Web UI 看到的并行度可能与提交时写的不一样。

### AdaptiveScheduler: A State Machine Over Resources

`AdaptiveScheduler` 的构造阶段就读出三个与 rescale 相关的设置：`rescaleOnFailedCheckpointsCount`、`rescaleHistoryMax`，以及基于后者创建的 `RescaleTimeline`：

```java
final int rescaleHistoryMax = settings.getRescaleHistoryMax();
this.rescaleTimeline =
        rescaleHistoryMax <= 0
                ? ... // disabled
                : new DefaultRescaleTimeline(() -> jobInformation, rescaleHistoryMax);
```

资源变化时走状态机：`newResourcesAvailable()` 把事件投递给当前 state 的 `ResourceListener.onNewResourcesAvailable()`：

```java
private void newResourcesAvailable(Collection<? extends PhysicalSlot> physicalSlots) {
    state.tryRun(
            ResourceListener.class,
            ResourceListener::onNewResourcesAvailable,
            "newResourcesAvailable");
}
```

`state.tryRun(Class, Consumer, reason)` 的语义是"只在当前状态实现了该 listener 接口时才执行"——不同状态（WaitingForResources / CreatingExecutionGraph / Executing / Failing）对同一事件有不同反应，这正是状态机调度器的实现方式。

> [!NOTE]
> 2.3 的 FLIP-487 / FLIP-495 给 AdaptiveScheduler 加了**可查询的 rescale 历史**（`RescaleTimeline` + Web UI 页签），上面源码里的 `rescaleHistoryMax` 就是它的容量配置。排障"为什么并行度突然变了"时先看这条时间线。

### Version Anchors: 2.x Module and Model Changes

- **模块归属变化**：`StreamTask`、`SubtaskCheckpointCoordinatorImpl` 等 `org.apache.flink.streaming.runtime.tasks` 包下的类，2.x 已位于 **`flink-runtime`** 模块，不再在 `flink-streaming-java`。按类找源码，别按旧模块路径找。
- **新增模块**：2.3 根 `pom.xml` 的 `<modules>` 中出现 `flink-datastream`、`flink-datastream-api`、`flink-models`（与 DataStream API 重构、AI 方向对齐）。
- **应用级模型**：`JobGraph` 带 `ApplicationID`；Web UI 新增 Applications 页签，作业回链应用（FLIP-549 / FLIP-560，见 [Deployment](/docs/CS/Framework/Flink/Deployment.md)）。
- **Rescale 历史**：`RescaleTimeline` / `DefaultRescaleTimeline`（FLIP-495）。

## Operator Chaining

Flink 会把满足条件的多个算子**链（chain）**在一起，放进同一个 Task、由同一个线程执行，称为 operator chain。条件包括：上下游并行度相同、forward 分区（一对一）、同一 SlotSharingGroup 等。

链化的好处：

- 算子之间变成方法调用 / 线程内传递，**避免线程切换、序列化与网络开销**；
- 减少线程数与缓冲，降低延迟。

可以用 `disableChaining()`、`startNewChain()` 调整。链内数据直接对象引用传递；链之间（跨 Task、跨 TaskManager）才走网络栈与序列化。链化策略对应 Transformation 上的 `ChainingStrategy`：`ALWAYS / NEVER / HEAD / HEAD_WITH_SOURCES`。

## Data Exchange

跨算子链 / 跨 Task 的数据交换由网络层承担，核心组件：

- 上游 `RecordWriter` 把记录写进 **ResultPartition**（按下游子任务切成多个 ResultSubpartition）；
- 下游 Task 的 **InputGate**（含多个 InputChannel）消费对应分区；
- 传输基于 Netty，使用**基于信用（credit-based）的流控**：下游为每个 channel 声明可用 credit，上游只有拿到 credit 才发送，避免把下游压垮，这是 Flink 背压机制的基础。

### Partitioning / Shuffle

上下游之间的数据分区方式决定记录如何路由到并行子任务：

| 分区策略 | 语义 | 典型算子 |
| ---- | ---- | ---- |
| Forward | 一对一，记录原样到同编号子任务（可 chain） | map/filter 之后 |
| Rebalance | 轮询（round-robin）均匀打散 | `rebalance()`，解决数据倾斜 |
| Hash / KeyGroupStream | 按 key 的 hash 路由，保证同 key 进同一子任务 | `keyBy()` |
| Broadcast | 每条记录广播给所有下游子任务 | `broadcast()`、广播状态 |
| Rescale | 本地局部轮询（不跨全集群） | `rescale()` |
| Global | 全部发往下游第一个子任务 | 慎用，易成瓶颈 |

### Backpressure

当下游处理不过来时，credit 耗尽 → 上游停止网络发送 → 输入端缓冲被占满 → 反压一路传导回 Source，从而让整条链路按最慢算子的速度运行。Flink Web UI 可直接查看各任务的背压比例，定位慢算子。

## Stream vs Batch on Same Runtime

尽管 DataSet API（批）已逐步被 DataStream API 的批执行模式取代，但底层是**同一个流式运行时**：处理有界数据时，调度与 shuffle 可以采用更批式的优化（如阻塞式 shuffle、sort-merge shuffle、算子间流水线断开），处理无界数据时则全流水线常驻。这与 Spark “微批 RDD”、[Storm](/docs/CS/Framework/Flink/Storm.md) “至少一次为主”的执行模型形成对比。

## Why This Shape

- **为什么图要分四层**：StreamGraph 忠于用户代码，JobGraph 做静态优化（chain 合并），ExecutionGraph 处理并行与调度，物理 Task 落到资源上。每层只解决一类问题，才能让 Client / JobManager / TaskManager 各自只依赖需要的抽象。
- **为什么并行度要抽成独立 store**：Adaptive Scheduler 的核心能力是"按当前可用资源决定并行度"，这要求并行度是可变决策而非图的固有属性；抽成 store 后，同一份 JobGraph 可生成不同并行度的执行图。
- **为什么 ExecutionGraph 是接口**：不同调度器（Default / Adaptive / Reactive）对图的操作方式不同，接口 + `attachJobGraph()` 让 scheduler 自己决定怎么建图与初始化。
- **为什么调度器用状态机**：资源、checkpoint 失败、作业状态变化是异步并发事件；把"当前状态能响应哪些事件"编码进 state 接口，比一堆 if-else 更不容易出竞态。

## Links

- [Flink](/docs/CS/Framework/Flink/Flink.md)
- [Storm](/docs/CS/Framework/Flink/Storm.md)
- [Client](/docs/CS/Framework/Flink/Client.md)
- [JobManager](/docs/CS/Framework/Flink/JobManager.md)
- [TaskManager](/docs/CS/Framework/Flink/TaskManager.md)
- [Checkpoint](/docs/CS/Framework/Flink/Checkpoint.md)

## References

1. [Flink Docs - Dataflow Programming Model (2.3)](https://nightlies.apache.org/flink/flink-docs-release-2.3/docs/concepts/flink-architecture/)
2. [Flink Docs - Network Shuffle / Task Lifecycle (2.3)](https://nightlies.apache.org/flink/flink-docs-release-2.3/docs/internals/job_scheduling/)
3. [Flink Docs - Credit-based Flow Control (2.3)](https://nightlies.apache.org/flink/flink-docs-release-2.3/docs/ops/monitoring/back_pressure/)
4. [Flink 2.3.0 Source: JobGraph.java](https://github.com/apache/flink/blob/release-2.3.0/flink-runtime/src/main/java/org/apache/flink/runtime/jobgraph/JobGraph.java)
5. [Flink 2.3.0 Source: ExecutionGraph.java](https://github.com/apache/flink/blob/release-2.3.0/flink-runtime/src/main/java/org/apache/flink/runtime/executiongraph/ExecutionGraph.java)
6. [Flink 2.3.0 Source: AdaptiveScheduler.java](https://github.com/apache/flink/blob/release-2.3.0/flink-runtime/src/main/java/org/apache/flink/runtime/scheduler/adaptive/AdaptiveScheduler.java)
7. [Flink 2.3.0 Source: pom.xml](https://github.com/apache/flink/blob/release-2.3.0/pom.xml)
8. [FLIP-549: Support Application Management](https://cwiki.apache.org/confluence/spaces/FLINK/pages/386272238/FLIP-549+Support+Application+Management)
