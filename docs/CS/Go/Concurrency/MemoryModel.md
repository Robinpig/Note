## Introduction

Go 的**内存模型（Memory Model）**规定了一组规则，用来判断"一个 goroutine 的写，另一个 goroutine 能否、以及何时能看到"。规则的核心概念是 **happens-before**：

- 若事件 `e1` **happens-before** `e2`，则 `e2` 一定能观察到 `e1` 的写及其之前的全部副作用（不会出现重排、撕裂、旧值）。
- 若 `e1` 与 `e2` 之间**不存在** happens-before 关系，则二者是**并发**的——编译器、CPU 可以自由重排与缓存，结果不可预测。

并发程序的正确性，本质就是**在需要顺序保证的地方，借助同步原语建立 happens-before**。

> 注意区分：本文档是 Go 的**内存模型（可见性规则）**；[GMM](/docs/CS/Go/GMM.md) 是 **GMP 调度模型**（Goroutine / Machine / Processor），二者完全不是一回事。

## 基础规则

- **程序顺序**：单 goroutine 内按代码顺序（program order）执行；编译器的重排不会破坏单线程语义（as-if-serial）。
- happens-before 是**传递**的：`e1 → e2 → e3` 蕴含 `e1 → e3`。
- 若 `e1` 不 happens-before `e2`、且 `e2` 不 happens-before `e1`，则二者**并发**。

## 同步操作提供的 happens-before 保证

### goroutine 的创建与退出

- `go` 语句中"启动 goroutine 之前的语句" **happens-before** "新 goroutine 的函数体开始执行"。
- goroutine 的**退出不**对任何事件建立 happens-before。因此"等子 goroutine 写完、主 goroutine 再读"不能只靠自然退出——必须通过 [channel](/docs/CS/Go/Concurrency/Channel.md) 或 [Sync](/docs/CS/Go/Concurrency/Sync.md) 的 WaitGroup 显式同步。

### channel

- 对 channel 的**发送** happens-before 对应的**接收完成**（无缓冲 channel 是"会合"语义，天然携带 happens-before，这也是 CSP 能替代锁的原因）。
- channel 的**关闭** happens-before "因关闭而接收到零值"。
- 带缓冲 channel（容量 C）：第 k 次**接收** happens-before 第 k+C 次**发送**完成——即缓冲写满时，发送要等前面有人接收腾出位置。

### Mutex / RWMutex

同一个锁上，`Unlock` happens-before 后续（任意 goroutine 的）`Lock` 返回。这是保护一段共享临界区的基础保证。更多见 [Lock](/docs/CS/Go/Concurrency/Lock.md)。

### atomic

`sync/atomic` 的 Load（acquire 语义）、Store（release 语义）、CompareAndSwap、Swap 提供同步保证：一次 release store 之前的所有写，对后续 acquire load 同一地址的读者可见。详见 [atomic](/docs/CS/Go/atomic.md)。

### Once

`Once.Do(f)` 中 `f` 的返回 happens-before **任何**后续 `Do` 调用返回——保证一次性初始化的结果对所有调用者都可见（零值/懒加载单例的安全基石）。

### init 与 main

- 每个包的 `init` 函数 happens-before 该包内任何其它代码；
- 被 `import` 包的 `init` 全部先于导入者运行；
- `main.main` 在所有 `init` 完成之后才开始。

## Data Race（数据竞争）

当满足以下三点，即发生 data race，结果**未定义**（可能看到撕裂值、重排后的旧值，甚至崩溃）：

1. 两个访问针对**同一内存地址**；
2. 至少**一个是写**；
3. 二者之间**没有** happens-before 关系。

`go build` / `go test` 加 **`-race`** 会在编译期插入读/写事件上报，运行期通过 happens-before 关系图检测竞争（会显著拖慢程序，仅用于测试与排查）。[atomic](/docs/CS/Go/atomic.md) 末尾的 Pitfalls 也强调"不要混用原子与非原子访问同一变量"。

## Links

- [Go Concurrency 总览](/docs/CS/Go/Concurrency/Concurrency.md)
- [GMM（GMP 调度模型）](/docs/CS/Go/GMM.md) — 调度，不是内存模型
- [atomic](/docs/CS/Go/atomic.md)
- [Channel](/docs/CS/Go/Concurrency/Channel.md)
- [Sync](/docs/CS/Go/Concurrency/Sync.md)

## References

1. [The Go Memory Model](https://go.dev/ref/mem)
