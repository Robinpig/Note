## Introduction

用于运行 ForkJoinTasks 的 ExecutorService。
ForkJoinPool 提供了非 ForkJoinTask 客户端的提交入口点，以及管理和监控操作。

ForkJoinPool 与其他类型的 ExecutorService 的主要区别在于采用了工作窃取：
池中的所有线程都尝试查找并执行提交给池的任务和/或由其他活跃任务创建的任务（如果没有工作，最终会阻塞等待）。
这使得当大多数任务生成其他子任务（如大多数 ForkJoinTasks 所做的那样），以及当许多小任务从外部客户端提交到池时，能够实现高效处理。
特别是在构造方法中将 asyncMode 设置为 true 时，ForkJoinPools 也可能适用于使用从不 join 的事件风格任务。所有工作线程都初始化为 Thread.isDaemon 为 true。

静态 commonPool() 可用于大多数应用程序。公共池由任何未显式提交到指定池的 ForkJoinTask 使用。
使用公共池通常会减少资源使用（其线程在非使用期间缓慢回收，并在后续使用中恢复）。

对于需要单独或自定义池的应用程序，可以使用给定的目标并行度级别构造 ForkJoinPool；默认情况下，等于可用处理器的数量。
池通过动态添加、挂起或恢复内部工作线程来尝试维持足够的活跃（或可用）线程，即使某些任务因等待 join 其他任务而停滞。
然而，在面对阻塞 I/O 或其他非托管同步时，不保证此类调整。

嵌套的 ForkJoinPool.ManagedBlocker 接口允许扩展所容纳的同步种类。
可以使用带有与 ThreadPoolExecutor 类中记录的参数对应的构造方法来覆盖默认策略。
除了执行和生命周期控制方法外，此类还提供了状态检查方法（例如 getStealCount），旨在帮助开发、调优和监控 fork/join 应用程序。

```java
ForkJoinPool commonPool = ForkJoinPool.commonPool();
```

### 工作窃取

工作窃取算法允许空闲线程从其他繁忙线程的队列尾部"窃取"任务。
这有助于保持所有线程忙碌，提高整体吞吐量。

### commonPool

公共池是 ForkJoinPool 的共享实例，默认并行度等于 Runtime.getRuntime().availableProcessors() - 1。

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
