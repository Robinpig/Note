## Introduction

Client 是 Flink 作业提交链路的起点，是一个独立的 JVM 进程（通常就是运行用户 `main()` 方法的地方）。
它本身**不参与作业的持续运行**，主要职责是：执行用户程序、把代码中的 DataStream API 调用翻译成逻辑执行图、优化成 JobGraph，然后提交给集群的 [JobManager](/docs/CS/Framework/Flink/JobManager.md)。提交完成后 Client 可以退出，作业仍在集群运行。

## Submission Flow

一次典型提交的时序（对应原笔记的几个关键词 Executor → execute → StreamGraph → submit JobGraph）：

1. 用户在 `main()` 里创建执行环境（如 `StreamExecutionEnvironment.getExecutionEnvironment()`），声明 source、一系列转换算子、sink。此时这些调用**并不会真正触发计算**，只是把每个转换登记到环境内部的 `List<Transformation<?>>` 中。
2. 调用 `env.execute(jobName)`（或 `executeAsync()`）才真正提交。Executor/PipelineExecutor 根据部署目标（Standalone / Yarn / Kubernetes / MiniCluster）选择具体实现。
3. Client 基于 Transformation 列表生成 **StreamGraph**（算子级 DAG，最贴近用户代码）。
4. 进一步优化生成 **JobGraph**：把可链化的算子合并成 JobVertex，确定中间数据集、序列化器、算子链策略等。JobGraph 是 **Client 与集群运行时之间约定的统一数据结构**，无论流批作业都以它提交。
5. Client 通过 **REST 接口**（新版）把 JobGraph 连同依赖 jar、配置提交给 Dispatcher，由 Dispatcher 拉起 JobMaster。底层早期用 Actor/RPC，现统一为 REST + BlobServer 分发大文件。

图的生成细节见 [Dataflow](/docs/CS/Framework/Flink/Dataflow.md)。

## Execution Environment

执行环境是 Client 侧的入口，不同环境决定作业最终跑在哪：

- `StreamExecutionEnvironment.getExecutionEnvironment()`：按 classpath/上下文自动选择本地或远程执行器。
- `createLocalEnvironment()`：本地 MiniCluster，用于开发调试（IDE 里直接跑 main）。
- `createRemoteEnvironment(host, port, jars...)`：显式提交到远程集群。
- SQL/Table 场景对应 `StreamTableEnvironment`。

命令行提交则由 `flink run` 这个 CLI Client 完成，它解析参数、上传用户 jar、调用同样的提交逻辑。

## Deploy Modes and Client Role

Client 是否在本地执行 `main()`、是否上传依赖，随部署模式而变（详见主笔记 [Flink](/docs/CS/Framework/Flink/Flink.md) 的三种模式对比）：

| 模式 | main() 在哪执行 | 依赖上传 | Client 负担 |
| ---- | ---- | ---- | ---- |
| Session | Client 本地生成 JobGraph | 每次提交上传 jar 到已存在集群 | 作业多时 Client 负载/带宽大 |
| Per-Job | Client 本地生成 JobGraph | 每作业独立建 JM/TM 并上传 | 同上，资源隔离好 |
| Application | **集群上**（JobManager 内）执行 main | 依赖预放 HDFS，无需 Client 上传 | Client 最轻，社区主推生产模式 |

Application 模式正是为了解决 Session/Per-Job 下“Client 既要本地构建 JobGraph 又要上传大量依赖”的瓶颈，把这部分工作搬进集群。

## What Client Does Not Do

- 不参与调度、不持有 Task、不负责 Checkpoint 协调——这些是 JobManager/JobMaster 的职责。
- 不执行真正的数据处理算子——那是 [TaskManager](/docs/CS/Framework/Flink/TaskManager.md) 上的 Task。
- 提交后即便 Client 断开，作业也不受影响；但作业结果获取（如 `execute().getJobClient()`、批作业的 collect）依赖 Client 在作业完成前保持连接。

## Links

- [Flink](/docs/CS/Framework/Flink/Flink.md)
- [Dataflow](/docs/CS/Framework/Flink/Dataflow.md)
- [JobManager](/docs/CS/Framework/Flink/JobManager.md)
- [TaskManager](/docs/CS/Framework/Flink/TaskManager.md)
- [Yarn](/docs/CS/Framework/Hadoop/Yarn.md)

## References

1. [Flink Docs - DataStream API Overview](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/overview/)
2. [Flink Docs - Deployment Modes](https://nightlies.apache.org/flink/flink-docs-stable/docs/deployment/overview/)
3. [Flink Architecture](https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/flink-architecture/)
