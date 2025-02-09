## Introduction



JobMaster会把JobGraph转换成ExecutionGraph JobMaster会向资源管理器（Resource Manager）发出请求，申请执行任务必要的资源。一旦它获取到了足够的资源，就会将执行图分发到真正运行它们的TaskManager上



在运行过程中，JobMaster会负责所有需要中央协调的操作，比如检查点（Checkpoints）的协调



ResourceManager主要负责资源的分配和管理。在Flink集群只有一个

Dispatcher主要负责提供一个REST接口，用来提交应用，并且负责为每一个新提交的作业启动一个新的JobMaster组件。Dispatcher也会启动一个WebUI，用来方便的展示和监控作业的执行信息





## Links

- [Flink](/docs/CS/Framework/Flink/Flink.md)