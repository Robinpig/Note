## Introduction

kube-scheduler组件是Kubernetes系统的核心组件之一，主要负责整个集群Pod资源对象的调度，根据内置或扩展的调度算法（预选与优选调度算法），将未调度的Pod资源对象调度到最优的工作节点上，从而更加合理、更加充分地利用集群的资源。

kube-scheduler是Kubernetes的默认调度器，其架构设计本身并不复杂，但Kubernetes系统在后期引入了优先级和抢占机制及亲和性调度等功能。







启动流程大致步骤如下： 
 （1）内置调度算法的注册。 
 （2）Cobra命令行参数解析。 
 （3）实例化Scheduler对象。 
 （4）运行EventBroadcaster事件管理器。 
 （5）运行HTTP或HTTPS服务。 
 （6）运行Informer同步资源。 
 （7）领导者选举实例化。 
 （8）运行sched.Run调度器









入口函数是位于`cmd/kube-scheduler/scheduler.go`中的main()方法,调用的是app.NewSchedulerCommand()方法





kube-scheduler组件的主要逻辑在于，如何在Kubernetes集群中为一个Pod资源对象找到合适的节点。调度器每次只调度一个Pod资源对象，为每一个Pod资源对象寻找合适节点的过程就是一个调度周期。”



kube-scheduler调度器在为Pod资源对象选择合适节点时，有如下两种最优解。 

- 全局最优解：是指每个调度周期都会遍历Kubernetes集群中的所有节点，以便找出全局最优的节点。 
- 局部最优解：是指每个调度周期只会遍历部分Kubernetes集群中的节点，找出局部最优的节点。 

全局最优解和局部最优解可以解决调度器在小型和大型Kubernetes集群规模上的性能问题。目前kube-scheduler调度器对两种最优解都支持。当集群中只有几百台主机时，例如100台主机，kube-scheduler使用全局最优解。当集群规模较大时，例如其中包含5000多台主机，kube-scheduler使用局部最优解。





kube-scheduler 目前包含两部分调度算法 predicates 和 priorities，首先执行 predicates 算法过滤部分 node 然后执行 priorities 算法为所有 node 打分，最后从所有 node 中选出分数最高的最为最佳的 node






## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)
