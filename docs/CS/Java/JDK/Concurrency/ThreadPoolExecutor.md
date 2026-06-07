## Introduction

Executor 是一个用于定义自定义线程类子系统的简单标准化接口，包括线程池、异步 I/O 和轻量级任务框架。
根据使用的具体 Executor 类，任务可以在新创建的线程、现有任务执行线程或调用 execute 的线程中执行，并且可以顺序或并发执行。

ExecutorService 提供了更完整的异步任务执行框架。ExecutorService 管理任务的排队和调度，并允许受控关闭。
ScheduledExecutorService 子接口和相关接口增加了对延迟和周期性任务执行的支持。
ExecutorServices 提供了以 Callable（Runnable 的结果承载对应物）形式表达的任何函数的异步执行方法。
Future 返回函数的结果，允许确定执行是否已完成，并提供取消执行的方法。
RunnableFuture 是一个具有 run 方法的 Future，执行时其结果被设置。

### Implementation

ThreadPoolExecutor 和 ScheduledThreadPoolExecutor 类提供可调优的灵活线程池。
Executors 类为最常见类型和配置的 Executors 提供了工厂方法，以及一些使用它们的实用方法。
其他基于 Executors 的实用程序包括具体类 FutureTask（提供可扩展的 Futures 通用实现）和 ExecutorCompletionService，
它协助协调异步任务组的处理。
ForkJoinPool 类提供了一个 Executor，主要设计用于处理 ForkJoinTask 及其子类的实例。
这些类采用工作窃取调度器，对于通常适用于计算密集型并行处理的受限制任务，可实现高吞吐量。

### 无限制创建线程的缺点

- 线程生命周期开销
  线程的创建和销毁并非免费。实际开销因平台而异，但
  线程创建需要时间，给请求处理引入延迟，并且需要 JVM 和操作系统的一些处理活动。
- 资源消耗
  活跃线程消耗系统资源，特别是内存。
  当可运行线程数多于可用处理器时，线程处于空闲状态。
- 稳定性
  可创建线程数存在限制。该限制因平台而异，并受多个因素影响，包括 JVM 启动参数、Thread 构造方法中请求的栈大小以及底层操作系统对线程的限制。

### 核心参数

- corePoolSize：核心线程数
- maximumPoolSize：最大线程数
- keepAliveTime：线程空闲存活时间
- workQueue：工作队列
- threadFactory：线程工厂
- RejectedExecutionHandler：拒绝策略

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
