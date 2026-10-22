## Introduction

Apache Flink 是一个框架和分布式处理引擎，用于对无界和有界数据流进行**状态计算**。基本数据模型是**数据流与事件（Event）序列**；批（batch）被视为"有界的流"，与流共用同一个运行时。

**Flink应用场景**

- 电商和市场营销: 实时报表|广告投放|实时推荐
- 物流配送及服务: 订单状态跟踪|信息推送
- 物联网: 实时数据采集|实时报警
- 银行和金融业: 实时结算|风险检测

早期 Lambda架构（第二代）用两套系统，同时保证低延迟和结果准确；Flink 的路线是把两者统一到一个引擎里。

**Flink核心特点**

- 高吞吐、低延迟
- 结果的正确性 （时间语义 事件时间 ）
- 精确一次（exacly-once）的状态一致性保证
- 可以与众多常用存储系统链接
- 高可用、支持动态扩展

**与 Spark 的分工**

- Spark采用RDD模型。Spark Streaming的DStream实际上也就是一组组小批数据RDD的集合，适合处理批次数据
- Flink基本数据模型是数据流，以及事件（Event）序列

> [!NOTE]
> 本页是 Flink 子树的**枢纽页**，只保留全貌与导航，各机制的细节见下面各子页。最新稳定版为 2.3.0（2026-06 发布）；2.x 是继 1.0 之后九年来第一个大版本，升级风险见 [Deployment](/docs/CS/Framework/Flink/Deployment.md)。

## build

```shell
 mvn clean install -DskipTests -Dfast
```

standalone的Flink会启动MiniCluster模拟分布式集群环境 和真正的分布式集群环境相比，MiniCluster省略了集群的一些主要组件，如Flink WebUI等

分布式集群本地调试环境需要启动 StandaloneSessionClusterEntrypoint TaskManagerRunner

## Architecture

Flink集群主要包含3部分：JobManager、TaskManager和 Client，三者均为独立的JVM进程。Flink集群启动后，会至少启动一个JobManager和多个TaskManager。

- [Client](/docs/CS/Framework/Flink/Client.md)：本地执行 main() 解析 JobGraph 对象，将 JobGraph 提交到 JobManager；
- [JobManager](/docs/CS/Framework/Flink/JobManager.md)：将任务拆分成 Task 并调度到各个 TaskManager，负责 Checkpoint 协调；
- [TaskManager](/docs/CS/Framework/Flink/TaskManager.md)：提供计算资源（内存、CPU 被切成 Slot），执行 Task 并向 JobManager 汇报。

JobGraph是客户端和集群运行时之间约定的**统一抽象数据结构**，也就是说，不管是什么类型的作业，都会通过客户端将提交的应用程序构建成JobGraph结构，最后提交到集群上运行。

TaskManager作为整个集群的工作节点，主要作用是向集群提供计算资源。这些计算资源会被封装成Slot资源卡槽，然后通过主节点中的ResourceManager组件进行统一协调和管理，而任务中并行的Task会被分配到Slot计算资源中。

根据底层集群资源管理器的不同，TaskManager的启动方式及资源管理形式也会有所不同：在基于Standalone模式的集群中，所有的TaskManager都是按照固定数量启动的；而YARN、Kubernetes等资源管理器上创建的Flink集群则支持按需动态启动TaskManager节点。

图从 StreamGraph → JobGraph → ExecutionGraph → 物理执行 Task 的四层演进，以及算子链（operator chain）、数据交换与背压，统一在 [Dataflow](/docs/CS/Framework/Flink/Dataflow.md) 里展开。

### 部署模式与资源提供者

三种集群运行模式（session、per-job、application）与三种资源管理器（Standalone / YARN / Kubernetes）的完整对比、Slot 资源模型与高可用方案，见 [Deployment](/docs/CS/Framework/Flink/Deployment.md)。一句话结论：**生产推荐 Application 模式**，底层优先 Kubernetes（Operator）或 YARN。

## WordCount demo

流式写法（DataStream API）：

```java
public class StreamWordCount {
    public static void main(String[] args) throws Exception {
        StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();

        DataStreamSource<String> lineDataStreamSource = env.readTextFile(filePath);

        SingleOutputStreamOperator<Tuple2<String, Long>> wordAndOneTuple =
                lineDataStreamSource.flatMap((String line, Collector<Tuple2<String, Long>> out) -> {
                    for (String word : line.split(" ")) {
                        out.collect(Tuple2.of(word, 1L));
                    }
                }).returns(Types.TUPLE(Types.STRING, Types.LONG));

        wordAndOneTuple
                .keyBy(data -> data.f0)
                .sum(1)
                .print();

        env.execute();   // 流式作业必须显式触发执行
    }
}
```

批式写法在 2.x 里不再使用独立的 DataSet API，而是**同一套 DataStream API + 批执行模式**：

```java
ExecutionEnvironment env = ExecutionEnvironment.getExecutionEnvironment();   // 1.x DataSet API，2.x 已移除
// 2.x 等价做法：StreamExecutionEnvironment + execution.runtime-mode = BATCH
```

> [!WARNING]
> Flink 2.x 已移除 DataSet API。批作业应统一使用 DataStream API 的 BATCH 运行时模式（或 Table API / SQL），不要再用 `ExecutionEnvironment`。

## DataStream

数据读取的API定义在StreamExecutionEnvironment 从这里构建数据读取API DataStream

内置的数据读取支持从内存、文件和网络读取 同时支持使用Flink连接器 自定义读取函数 读取外部存储数据

Flink 支持的数据源连接器通过 addSource 函数添加，之后通过 addSink 添加到转换流程中；2.x 起推荐 `env.fromSource()` + `stream.sinkTo()`（见 [Connector](/docs/CS/Framework/Flink/Connector.md)）。

DataStream代表一系列同类型数据的集合，可以通过转换操作生成新的DataStream。DataStream用于表达业务转换逻辑，实际上并没有存储真实数据。

DataStream数据结构包含两个主要成员：StreamExecutionEnvironment和Transformation<T> transformation。其中transformation是当前DataStream对应的上一次的转换操作，换句话讲，就是通过transformation生成当前的DataStream。

当用户通过DataStream API构建Flink作业时，StreamExecutionEnvironment会将DataStream之间的转换操作存储至List<Transformation<?>> transformations集合，然后基于这些转换操作构建作业Pipeline拓扑，用于描述整个作业的计算逻辑。其中流式作业对应的Pipeline实现类为StreamGraph，批作业对应的Pipeline实现类为Plan。

转换操作

- 单数据：map、filter、flatmap
- window（见 [Window](/docs/CS/Framework/Flink/Window.md)）：timeWindowAll、countWindow
- 多流合并：join、connect、coGroup、union、interval join
- 单流切分：split、sideOutput

### Transformation

在Transformation的基础上又抽象出了PhysicalTransformation类。PhysicalTransformation中提供了setChainingStrategy()方法，可以将上下游算子按照指定的策略连接

ChainingStrategy支持如下四种策略：ALWAYS、NEVER、HEAD、HEAD_WITH_SOURCES

Transformation结构中最主要的组成部分就是StreamOperator。StreamOperator最终会通过StreamOperatorFactory封装在Transformation结构中，并存储在StreamGraph和JobGraph结构中，直到运行时执行StreamTask时，才会调用StreamOperatorFactory.createStreamOperator()方法在StreamOperatorFactory中定义StreamOperator实例

DataStream API中大部分转换操作都是通过SimpleOperatorFactory进行封装和创建的。SimpleStreamOperatorFactory根据算子类型的不同，拓展出了InputFormatOperatorFactory、UdfStreamOperatorFactory和OutputFormatOperatorFactory三种接口实现

## Function

Function作为Flink中最小的数据处理单元，在Flink中占据非常重要的地位。和Java提供的Function接口类似，Flink实现的Function接口专门用于处理接入的数据元素。StreamOperator负责对内部Function的调用和执行，当StreamOperator被Task调用和执行时，StreamOperator会将接入的数据元素传递给内部Function进行处理，然后将Function处理后的结果推送给下游的算子继续处理

## Runtime

运行时两块核心是资源与执行环境：

- **Resource Manager**：JobManager 侧组件，管理 TaskManager 注册上来的 Slot，不足时向底层平台申请新节点（见 [JobManager](/docs/CS/Framework/Flink/JobManager.md)）
- **Execution Environment**：Client 侧执行环境，把用户代码编译成图结构并提交执行（见 [Client](/docs/CS/Framework/Flink/Client.md)）

运行时的另外两根支柱是**状态**与**容错**：[State](/docs/CS/Framework/Flink/State.md) 负责算子记住什么，[Checkpoint](/docs/CS/Framework/Flink/Checkpoint.md) 负责失败后回到哪里。

## SQL

SQL / Table API 是 Flink 的声明式接口：用**动态表 + 连续查询**表达流计算，优化器生成计划后仍落到同一套运行时。窗口 TVF、各类 join、changelog 模式、物化表与 Streaming Lakehouse 见 [Table_SQL](/docs/CS/Framework/Flink/Table_SQL.md)。

## Metrics

生产可观测性主要看四组指标：

| 类别 | 关注点 | 典型指标 |
| ---- | ---- | ---- |
| 吞吐 / 延迟 | 算子是否跟得上 | numRecordsIn/Out、Watermark 推进速度 |
| 背压 | 瓶颈算子定位 | 各 Task 背压比例（见 [Dataflow](/docs/CS/Framework/Flink/Dataflow.md) 的 credit-based 流控） |
| Checkpoint | 容错健康度 | Duration、对齐时长、持久化大小、失败次数（见 [Checkpoint](/docs/CS/Framework/Flink/Checkpoint.md)） |
| 资源 | 是否资源瓶颈 | JVM 堆/堆外、GC、网络缓冲、Slot 利用率（见 [TaskManager](/docs/CS/Framework/Flink/TaskManager.md)） |

用户侧可用 MetricGroup（Counter / Gauge / Meter / Histogram）上报业务指标，通过 Reporter 推送到 Prometheus 等系统。

## Links

- [Dataflow](/docs/CS/Framework/Flink/Dataflow.md)
- [Time](/docs/CS/Framework/Flink/Time.md)
- [Window](/docs/CS/Framework/Flink/Window.md)
- [State](/docs/CS/Framework/Flink/State.md)
- [Checkpoint](/docs/CS/Framework/Flink/Checkpoint.md)
- [Connector](/docs/CS/Framework/Flink/Connector.md)
- [Table_SQL](/docs/CS/Framework/Flink/Table_SQL.md)
- [Deployment](/docs/CS/Framework/Flink/Deployment.md)
- [Client](/docs/CS/Framework/Flink/Client.md)
- [JobManager](/docs/CS/Framework/Flink/JobManager.md)
- [TaskManager](/docs/CS/Framework/Flink/TaskManager.md)
- [Storm](/docs/CS/Framework/Flink/Storm.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Yarn](/docs/CS/Framework/Hadoop/Yarn.md)
- [Hadoop](/docs/CS/Framework/Hadoop/Hadoop.md)

## References

1. [Apache Flink Documentation](https://nightlies.apache.org/flink/flink-docs-stable/)
2. [Flink Concepts - Architecture](https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/flink-architecture/)
3. [Apache Flink 官方中文文档](https://flink.apache.org/zh/)
