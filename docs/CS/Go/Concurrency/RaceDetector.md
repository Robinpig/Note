## Introduction

Go 的 **race detector** 是一个**动态**数据竞争检测工具：给 `go` 命令加上 `-race` 编译标志，编译器会在每次内存访问处插入记录代码，运行时库据此监视对共享变量的「未同步访问」，一旦发现就打印 `WARNING: DATA RACE`。它是 Go 官方保证并发正确性的头号工具——[Go 内存模型](/docs/CS/Go/Concurrency/MemoryModel.md) 明确指出「含数据竞争的程序行为未定义」，而 `-race` 正是验证你有没有遵守 happens-before 规则的手段。

## How to Enable

```shell
go test  -race ./...   # 跑测试时检测（最常用，CI 标配）
go run   -race main.go # 编译并运行
go build -race ./cmd   # 构建带检测的二进制
go install -race pkg
```

在测试里它是事实标准：`go test -race ./...` 应当进 CI；集成测试、压测最能触达并发路径。框架里并发代码难以触达时，也可在生产集群里放一个 race-enabled 实例来抓偶发竞争。

## What Algorithm It Uses

race detector 基于 C/C++ 的 **ThreadSanitizer（tsan）** 运行时库：编译器对每个内存读写插桩、记录「何时 / 如何访问」；运行时维护一份 **shadow memory**，追踪每个内存位置「上一次被哪个 goroutine、在哪个时钟（vector clock）读/写」，当两条访问之间**没有 happens-before 关系**、且至少一条是写时，判定为数据竞争。

## What is Data Race

数据竞争 = 两个 goroutine 访问**同一块内存**，其中**至少一个是写**，且二者之间**不存在同步（happens-before）**排序。典型形态：

```go
func main() {
    var x int
    go func() { x++ }() // 写
    go func() { x++ }() // 写，无同步
    time.Sleep(time.Second)
}
```

`-race` 会报 `WARNING: DATA RACE`，并分别列出两次冲突访问的「读/写类型 + goroutine + 调用栈」，以及上一次访问的位置，方便定位。

## Overhead and Boundaries

- **开销大**：带检测的二进制 CPU 与内存通常膨胀到 **10 倍**左右，因此不适合常驻全量开启；一般只在 `go test -race`、压测或单实例上启用。
- **只抓「跑到的」竞争**：它是**动态分析**，只能发现执行路径上真正并发发生的竞争——**不能证明没有竞争**。覆盖度完全取决于你的测试/负载是否真实触达并发路径。
- **平台**：需要在 **64 位架构**上编译运行（amd64、arm64 等），不支持 32 位平台。
- **基本无误报**：官方明确说明 race detector **不会产生误报**——看到 WARNING 就该认真对待，它几乎一定指向真实的同步缺陷（即便在某些人看来「良性」的共享也往往藏着真 bug，标准库历史上就靠它抓出过 42 例）。
- **GORACE 环境变量**：可调选项，如 `GORACE="halt_on_error=1"` 让首个竞争就退出，`log_path` 指定报告落盘路径等。

## Relationship with atomic / Synchronization Primitives

race detector 把 `sync/atomic` 的操作视为同步点（带 happens-before 语义），所以**用原子操作保护的共享变量不会被报竞争**——这正是「用 atomic 消除竞争」在工具层面的依据。反之，混用「原子读 + 普通写」同一变量仍会被抓。要理解哪些操作能提供 happens-before 保证，回到 [Go 内存模型](/docs/CS/Go/Concurrency/MemoryModel.md)。

## Links

- [Go Concurrency 总览](/docs/CS/Go/Concurrency/Concurrency.md)
- [Golang](/docs/CS/Go/Go.md)

## References

1. [Introducing the Go Race Detector](https://go.dev/blog/race-detector)
2. [Data Race Detector（官方文档）](https://go.dev/doc/articles/race_detector.html)
3. [ThreadSanitizer Algorithm](https://github.com/google/sanitizers/wiki/ThreadSanitizerAlgorithm)
