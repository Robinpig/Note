## Introduction

Go 工具链自带性能剖析（profiling）与执行追踪（tracing）能力，无需第三方 APM 就能定位 CPU、内存、锁竞争、调度延迟等问题。
两者面向不同问题：**pprof 回答「资源花在哪个函数上」，trace 回答「一个时间窗口内调度器和每个 goroutine 发生了什么」。**

## pprof

pprof 基于**采样**，每隔约 10ms 记录一次当前堆栈，统计各函数占用的资源比例，细节见 [pprof](/docs/CS/Go/pprof.md)。

- 标准库：`runtime/pprof`（工具型/离线任务）、`net/http/pprof`（服务型，导入后在 `/debug/pprof/` 暴露端点）；
- 常见 profile 类型：`cpu`、`heap`（内存分配）、`goroutine`、`block`（阻塞）、`mutex`（锁竞争）、`threadcreate`；
- 采集后用 `go tool pprof` 分析，可看 top、list（源码级）、web（火焰/调用图），也常用 `pprof -http=:8080` 开火焰图 UI；
- 与 Java 生态对照：JFR/async-profiler 采样 CPU/allocation lock 是同一类手段。

```shell
go tool pprof http://localhost:6060/debug/pprof/profile?seconds=30   # CPU 采样 30s
go tool pprof http://localhost:6060/debug/pprof/heap                  # 堆分配
```

## trace

`runtime/trace`（服务里经 `net/http/pprof` 的 `/debug/pprof/trace` 暴露）记录的是一段时间内的**执行事件流**而非采样：
goroutine 的创建/阻塞/唤醒、GC 的开始结束、系统调用、网络读写、P/M/G 调度切换等。

```shell
curl -o trace.out 'http://localhost:6060/debug/pprof/trace?seconds=5'
go tool trace trace.out        # 打开 Web UI：时间线、goroutine 分析、调度延迟分布
```

适用场景——这些是 pprof 看不出来的：

- STW、GC 抢占导致的尾延迟，GC 与用户代码在时间线上的重叠；
- goroutine 因 channel、锁、syscall、网络（[netpoller](/docs/CS/Go/netpoller.md)）阻塞造成的调度延迟（scheduling latency）；
- P 空闲、M 不够、GOMAXPROCS 设置不当导致的并行度不足；
- 排查「CPU 没满但请求慢」这类典型的调度/阻塞问题。

一句话区分：**CPU 飙高、内存涨，用 pprof 找函数；延迟高但 CPU 闲、怀疑阻塞或调度，用 trace 看时间线。**

## Other Toolchain Commands

| 命令 | 用途 |
| --- | --- |
| `go test -bench -benchmem -cpuprofile -memprofile` | 基准测试并直接产出 CPU/内存 profile |
| `go test -race` | 数据竞争检测（编译期插桩，定位并发读写同一变量） |
| `go vet` | 静态检查（copylocks、unreachable、printf 格式等） |
| `go build -gcflags="-m"` | 查看逃逸分析决定（对象分配在堆还是栈） |
| `GODEBUG=gctrace=1,schedtrace=1000` | 打印 GC/调度日志，轻量现场诊断 |
| `delve`（dlv） | 调试器，可下断点、看 goroutine 栈 |

## Links

- [Golang](/docs/CS/Go/Go.md)
- [pprof](/docs/CS/Go/pprof.md) — 采样原理与 profile 类型详解
- [runtime 与调度](/docs/CS/Go/runtime.md)
- [netpoller](/docs/CS/Go/netpoller.md)
- [GC](/docs/CS/Go/GC.md)

## References

1. [Profiling Go Programs](https://go.dev/blog/pprof)
2. [Go Execution Tracer](https://go.dev/blog/execution-traces-2024)
