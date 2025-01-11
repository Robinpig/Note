## Introduction



## build

```shell
 mvn clean install -DskipTests -Dfast
```



standalone的Flink会启动MiniCluster模拟分布式集群环境 和真正的分布式集群环境相比，MiniCluster省略了集群的一些主要组件，如Flink WebUI等

分布式集群本地调试环境需要启动 StandaloneSessionClusterEntrypoint TaskManagerRunner



## Architecture



Flink技术架构如图











Flink集群主要包含3部分：JobManager、TaskManager和客户端，三者均为独立的JVM进程。Flink集群启动后，会至少启动一个JobManager和多个TaskManager。客户端将任务提交到JobManager，JobManager再将任务拆分成Task并调度到各个TaskManager中执行，最后TaskManager将Task执行的情况汇报给JobManager





客户端会在内部运行提交的作业，然后基于作业的代码逻辑构建JobGraph结构，最终将JobGraph提交到运行时中运行。JobGraph是客户端和集群运行时之间约定的统一抽象数据结构，也就是说，不管是什么类型的作业，都会通过客户端将提交的应用程序构建成JobGraph结构，最后提交到集群上运行



obManager是整个集群的管理节点，负责接收和执行来自客户端提交的JobGraph。JobManager也会负责整个任务的Checkpoint协调工作，内部负责协调和调度提交的任务，并将JobGraph转换为ExecutionGraph结构，然后通过调度器调度并执行ExecutionGraph的节点。ExecutionGraph中的ExecutionVertex节点会以Task的形式在TaskManager中执行



除了对Job的调度和管理之外，JobManager会对整个集群的计算资源进行统一管理，所有TaskManager的计算资源都会注册到JobManager节点中，然后分配给不同的任务使用。当然，JobManager还具备非常多的功能，例如Checkpoint的触发和协调等





TaskManager作为整个集群的工作节点，主要作用是向集群提供计算资源，每个TaskManager都包含一定数量的内存、CPU等计算资源。这些计算资源会被封装成Slot资源卡槽，然后通过主节点中的ResourceManager组件进行统一协调和管理，而任务中并行的Task会被分配到Slot计算资源中。

根据底层集群资源管理器的不同，TaskManager的启动方式及资源管理形式也会有所不同 例如，在基于Standalone模式的集群中，所有的TaskManager都是按照固定数量启动的；而YARN、Kubernetes等资源管理器上创建的Flink集群则支持按需动态启动TaskManager节点





## DataStream

数据读取的API定义在StreamExecutionEnvironment 从这里构建数据读取API DataStream

内置的数据读取支持从内存、文件和网络读取 同时支持使用Flink连接器 自定义读取函数 读取外部存储数据

```java
public class StreamExecutionEnvironment implements AutoCloseable {
    @PublicEvolving
    public <OUT> DataStreamSource<OUT> createInput(
            InputFormat<OUT, ?> inputFormat, TypeInformation<OUT> typeInfo) {
        DataStreamSource<OUT> source;

        if (inputFormat instanceof FileInputFormat) {
            @SuppressWarnings("unchecked")
            FileInputFormat<OUT> format = (FileInputFormat<OUT>) inputFormat;

            source =
                    createFileInput(
                            format,
                            typeInfo,
                            "Custom File source",
                            FileProcessingMode.PROCESS_ONCE,
                            -1);
        } else {
            source = createInput(inputFormat, typeInfo, "Custom Source");
        }
        return source;
    }

    private <OUT> DataStreamSource<OUT> createInput(
            InputFormat<OUT, ?> inputFormat, TypeInformation<OUT> typeInfo, String sourceName) {

        InputFormatSourceFunction<OUT> function =
                new InputFormatSourceFunction<>(inputFormat, typeInfo);
        return addSource(function, sourceName, typeInfo);
    }

    private <OUT> DataStreamSource<OUT> addSource(
            final SourceFunction<OUT> function,
            final String sourceName,
            @Nullable final TypeInformation<OUT> typeInfo,
            final Boundedness boundedness) {
        checkNotNull(function);
        checkNotNull(sourceName);
        checkNotNull(boundedness);

        TypeInformation<OUT> resolvedTypeInfo =
                getTypeInfo(function, sourceName, SourceFunction.class, typeInfo);

        boolean isParallel = function instanceof ParallelSourceFunction;

        clean(function);

        final StreamSource<OUT, ?> sourceOperator = new StreamSource<>(function);
        return new DataStreamSource<>(
                this, resolvedTypeInfo, sourceOperator, isParallel, sourceName, boundedness);
    }
}
```



DataStream代表一系列同类型数据的集合，可以通过转换操作生成新的DataStream。DataStream用于表达业务转换逻辑，实际上并没有存储真实数据。

DataStream数据结构包含两个主要成员：StreamExecutionEnvironment和Transformation< T > transformation。其中transformation是当前DataStream对应的上一次的转换操作，换句话讲，就是通过transformation生成当前的DataStream

当用户通过DataStream API构建Flink作业时，StreamExecutionEnvironment会将DataStream之间的转换操作存储至StreamExecutionEnvironment的List<Transformation<?>> transformations集合，然后基于这些转换操作构建作业Pipeline拓扑，用于描述整个作业的计算逻辑。其中流式作业对应的Pipeline实现类为StreamGraph，批作业对应的Pipeline实现类为Plan

### Transformation



在Transformation的基础上又抽象出了PhysicalTransformation类。PhysicalTransformation中提供了setChainingStrategy()方法，可以将上下游算子按照指定的策略连接

ChainingStrategy支持如下四种策略

- ALWAYS
- NEVER
- HEAD
- HEAD_WITH_SOURCES



Transformation结构中最主要的组成部分就是StreamOperator



StreamOperator最终会通过StreamOperatorFactory封装在Transformation结构中，并存储在StreamGraph和JobGraph结构中，直到运行时执行StreamTask时，才会调用StreamOperatorFactory.createStreamOperator()方法在StreamOperatorFactory中定义StreamOperator实例



DataStream API中大部分转换操作都是通过SimpleOperatorFactory进行封装和创建的。SimpleStreamOperatorFactory根据算子类型的不同，拓展出了InputFormatOperatorFactory、UdfStreamOperatorFactory和OutputFormatOperatorFactory三种接口实现



## Function



Function作为Flink中最小的数据处理单元，在Flink中占据非常重要的地位。和Java提供的Function接口类似，Flink实现的Function接口专门用于处理接入的数据元素。StreamOperator负责对内部Function的调用和执行，当StreamOperator被Task调用和执行时，StreamOperator会将接入的数据元素传递给内部Function进行处理，然后将Function处理后的结果推送给下游的算子继续处理







## Links

- [Spark]()