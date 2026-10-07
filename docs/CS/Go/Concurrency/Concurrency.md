## Introduction

Go 的并发哲学是 CSP（Communicating Sequential Processes）风格：**不要通过共享内存通信，而要通过通信共享内存**。
语言层面用 [goroutine](/docs/CS/Go/Concurrency/Goroutine.md) 表达并发执行体，用 [channel](/docs/CS/Go/Concurrency/Channel.md)
在它们之间传递数据；但传统的共享内存同步原语（[sync](/docs/CS/Go/Concurrency/Sync.md) 包、[atomic](/docs/CS/Go/atomic.md)）
同样是一等公民，该用锁的场景仍应用锁。

与 [Java 并发](/docs/CS/Java/JDK/Concurrency/Concurrency.md)相比，Go 没有把线程池、Future、synchronized 暴露给用户，
而是由 [runtime](/docs/CS/Go/runtime.md) 把大量 goroutine 复用到少量 OS 线程上（GMP 调度），用户写的是同步风格的直线代码。

## Building Blocks

- [Goroutine](/docs/CS/Go/Concurrency/Goroutine.md)：用户态轻量线程，初始栈仅 2KB 且可增长，由 Go runtime 调度到 OS 线程（M）上，创建/切换成本远低于内核线程。
- [Channel](/docs/CS/Go/Concurrency/Channel.md)：类型化的通信管道。无缓冲 channel 是「会合（rendezvous）」语义——发送与接收同时就绪才完成交接，天然携带 happens-before；带缓冲 channel 退化为容量受限的信号量/队列。
- [select](/docs/CS/Go/Concurrency/select.md)：多路复用 channel 操作，`default` 分支可做非阻塞尝试，常配合 `time.After`/`context.Done` 实现超时与取消。
- [Context](/docs/CS/Go/Concurrency/Context.md)：在调用链上传播取消信号、超时与请求作用域的值，是 Go 服务端控制 goroutine 生命周期的标准手段。
- [Sync](/docs/CS/Go/Concurrency/Sync.md)：`Mutex`/`RWMutex`/`WaitGroup`/`Cond`/`Once`/`Pool`；其运行时实现见 [Lock](/docs/CS/Go/Concurrency/Lock.md)。
- [atomic](/docs/CS/Go/atomic.md)：无锁原子操作，实现 lock-free 结构时使用。
- [errgroup](/docs/CS/Go/Concurrency/errgroup.md)：子任务组取消与错误聚合（golang.org/x/sync）。
- [singleflight](/docs/CS/Go/Concurrency/singleflight.md)：合并并发重复调用，防缓存击穿（golang.org/x/sync）。
- [semaphore](/docs/CS/Go/Concurrency/semaphore.md)：加权计数信号量（golang.org/x/sync），限制并发度，Acquire/Release 可按权重借还资源。

## Patterns

Go 并发里最常被复用的几种结构——工作者池、流水线、扇入/扇出、限流、退出与取消传播、for-range 退出约定——都展开在 [并发模式](/docs/CS/Go/Concurrency/Patterns.md)：每个模式配最小可运行示例，并说明与 channel / context / errgroup 的组合方式。要点速记：fan-in 把多路结果汇入一个 channel、fan-out 是一个 channel 被多 worker 分摊；`close(ch)` 后 `for range` 自动收尾（关闭是发送方职责）；`sync.WaitGroup` 只等待不取消，要取消与错误聚合用 [errgroup](/docs/CS/Go/Concurrency/errgroup.md)；channel 当信号量（`sem <- struct{}{}` / `<-sem`）即可限流，说明 channel 与锁并非对立。

## Share by Communicating

channel 适合「转移数据所有权 / 编排工作流」，但并非所有同步都该用 channel：

- 保护一段临界区（map、计数器、结构体字段）→ `sync.Mutex`/`atomic` 更直接，强行用 channel 反而绕远；
- 向多个 worker 派发独立任务并回收结果、随生命周期取消、限流 → channel + context 更自然。

判据：channel 表达的是「发生了某件事 / 一份数据在执行体之间流动」；锁表达的是「这块状态此刻互斥访问」。
内存可见性的正式保证见 [Go Memory Model](https://go.dev/ref/mem)（happens-before 规则）。


## Memory Model (happens-before)

并发可见性的正式保证见 [Go 内存模型](/docs/CS/Go/Concurrency/MemoryModel.md)：它逐条定义了 goroutine 创建/退出、channel、Mutex、atomic、Once、init 各自提供的 happens-before 保证，以及 data race 的判定。atomic 的 Load/Store 自带 acquire/release 语义、channel 收发天然携带 happens-before，正是「通过通信共享内存」在可见性层面成立的根基——不要凭直觉假设并发读写安全，需要顺序保证就靠这些同步原语。

想验证写出来的并发代码确实没有数据竞争，用 `go test -race` 跑测试——检测器的原理与边界见 [竞争检测](/docs/CS/Go/Concurrency/RaceDetector.md)。
## Links

- [Go](/docs/CS/Go/Go.md)
- [Goroutine](/docs/CS/Go/Concurrency/Goroutine.md)
- [Channel](/docs/CS/Go/Concurrency/Channel.md)
- [select](/docs/CS/Go/Concurrency/select.md)
- [Context](/docs/CS/Go/Concurrency/Context.md)
- [Sync](/docs/CS/Go/Concurrency/Sync.md)
- [Lock](/docs/CS/Go/Concurrency/Lock.md)
- [atomic](/docs/CS/Go/atomic.md)
- [runtime 与 GMP](/docs/CS/Go/runtime.md)

## References

1. [Effective Go - Concurrency](https://go.dev/doc/effective_go#concurrency)
2. [The Go Memory Model](https://go.dev/ref/mem)
3. [Share Memory By Communicating](https://go.dev/blog/codelab-share)
