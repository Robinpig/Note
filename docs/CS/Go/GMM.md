## Introduction

> 本文档的 **GMM** 指 Go 运行时的 **GMP 调度模型**（Goroutine / Machine / Processor），**不是** Go Memory Model（内存模型）。内存可见性的 happens-before 规则见 [Go 内存模型](/docs/CS/Go/Concurrency/MemoryModel.md)（官方文档 [The Go Memory Model](https://go.dev/ref/mem)）。

Go 在语言层只暴露 goroutine 与 channel，但真正把成千上万个 goroutine 跑在少量 OS 线程上的，是 runtime 里的调度器。它要解决的核心问题是：**用多少个内核线程、以什么策略把就绪的 goroutine 交给它们执行，同时让阻塞（syscall、channel、网络 I/O、GC）尽量不拖垮 CPU 利用率。**

三要素的角色划分与结构体定义见 [Goroutine](/docs/CS/Go/Concurrency/Goroutine.md) 的 GMP 章节（g / m / p），本文聚焦调度的**算法与流程**。

## Responsibilities of the Three Elements

- **G（goroutine）**：用户态轻量执行流，初始栈 2KB、按需增长；状态机含 `_Grunnable / _Grunning / _Gwaiting / _Gdead` 等。一个程序可同时存在百万级 G。
- **M（machine）**：操作系统线程的抽象，真正在 CPU 上跑代码的实体；runtime 把 M 与内核线程绑定。一个 M 阻塞在 syscall 时，与它所绑定的 P 会被解绑、转交其他 M。M 数量默认上限 10000（`debug.SetMaxThreads` 可调）。
- **P（processor）**：逻辑处理器，是调度的"资源上下文"——持有本地运行队列 `runq`（容量 256）、mcache（内存分配缓存）、GC 标记本地状态等。P 的数量即并发执行 Go 代码的能力上限，默认等于 `GOMAXPROCS`（通常 = CPU 逻辑核数）。**任一时刻一个 P 只能绑定一个 M，但 P↔M 不是固定配对**，会随调度流动。

> 早期 Go（1.0 前）是 GM 模型：全局 runq + 全局锁，锁争用严重、缓存局部性差、频繁跨 M 切换。引入 P 后，调度的主要竞争从"全局锁"收敛为"每 P 的本地队列"，这是 GMP 相对 GM 的根本改进。

## Scheduling Loop

每个 M 在拿到 P 后进入 `schedule()` 自旋，生命周期是一条永不退出的环：

```
schedule → execute → gogo → 运行用户代码 → goexit → goexit1 → mcall → goexit0 → schedule
```

`goexit0` 把 G 复位为 `_Gdead`、归还到 P 的 gfree 缓存，再调 `schedule()` 取下一个 G，如此往复。新 goroutine 由 `go` 关键字编译为 `newproc → newproc1`，优先放入**当前 P 的本地 runq**（创建细节见 [Goroutine](/docs/CS/Go/Concurrency/Goroutine.md) 的 start 章节）。

## findRunnable: Where to Get the Next G

`schedule()` 的核心是 `findRunnable()`，它按既定优先级尝试获取一个可运行的 G，顺序直接决定调度的公平性与局部性（源码见 [Goroutine](/docs/CS/Go/Concurrency/Goroutine.md)）：

1. **本地队列优先**：`runqget(pp)` 从当前 P 的 `runq` 取 G（FIFO）。本地队列无锁、热缓存友好，是绝大多数情况下的命中路径。
2. **周期性看全局队列**：每 `schedtick % 61 == 0` 才 `globrunqget` 一次全局 runq，避免两个 G 互相 respawn 占满本地队列、饿死其他 P。
3. **netpoll 唤醒**：`netpoll(0)` 非阻塞地捞回被 [netpoller](/docs/CS/Go/netpoller.md) 挂起、现已就绪的网络 I/O goroutine，转为 `_Grunnable`。
4. **工作窃取（work-stealing）**：本地、全局、netpoll 都空时，`stealWork(now)` 从其他 P 的 runq 尾部"偷"一半 G 过来。为避免空转，runtime 限制"自旋 M"数量 ≤ 空闲 P 数的一半（`2*nmspinning < gomaxprocs - npidle`）。
5. **idle mark worker**：若处于 GC 标记期且本 P 有空闲标记任务，转去跑 GC 标记而非让出 P。

找不到任何工作时，M 进入休眠（`stopm`），P 回到 `pidle` 空闲池，直到被 `wakep` / netpoll / 新 goroutine 唤醒。

## Work Stealing and Spinning

工作窃取是 GMP 负载均衡的基石：当一个 P 的本地队列被掏空，它不会干等，而是从其他 P "借" G。配套的是 **spinning M** 机制——当一个 M 即将去偷活时先 `becomeSpinning()`，偷到后把偷来的 G 通过 `runnext` 优先执行（利用缓存局部性）；偷不到则退出自旋去休眠。对 spinning M 的数量设上限，避免了 `GOMAXPROCS` 很大但程序并行度很低时的 CPU 空耗。

## System Call Handoff

当 G 陷入**阻塞型 syscall**（如文件 read、部分 cgo），它所在的 M 会被内核挂起。若 P 一直绑在这个 M 上，P 的本地队列就停摆。解决方式是 **handoff**：

- 进入 syscall 时，M 通过 `entersyscall` 让 P 进入 `_Psyscall`，但 P 仍可被其他 M 取走；
- 若 syscall 耗时超过阈值，sysmon 的 `retake` 会把 `_Psyscall` 的 P 状态改为 `_Pidle` 并交给另一个空闲 M（`handoffp`），继续在该 P 上跑 Go 代码；
- 原 M 在 syscall 返回后若找不到 P，就把自己挂起（`exitsyscall` → `dropg` → `stopm`）。

注意：**非阻塞 I/O（网络）走的是 netpoller + G 挂起 `_Gwaiting`，M 不被阻塞**，所以不会触发 handoff——这是 Go 高并发网络性能的关键。

## sysmon and Preemption

runtime 启动时会创建一个**不绑定 P、运行在独立 M 上**的监控线程 sysmon，每约 10ms 跑一次 `retake`，负责三件事：

- **抢占运行过久的 G**：1.14 之前是协作式抢占——编译器在函数序言插入 `morestack` 检查，G 只能在函数调用边界让出；1.14 起改为**基于 `SIGURG` 信号的异步抢占**，向目标 M 发信号即可打断长时间运行（甚至死循环）的 G，避免个别 G 霸占 P。
- **回收陷入 syscall 的 P**：如上所述，把 `_Psyscall` 的 P 抢回空闲池。
- **触发 netpoll 与 GC 辅助**：在网络、GC 需要时被唤醒。

## GOMAXPROCS and the Number of Threads

| 实体 | 默认 | 上限 / 约束 |
| --- | --- | --- |
| P | `GOMAXPROCS`（= CPU 核数） | `runtime.GOMAXPROCS(n)` 动态调整 |
| M | — | 默认 10000（`debug.SetMaxThreads`） |
| G | — | 无硬上限，受内存限制（`runtime.NumGoroutine()` 查看） |

> IO 密集型服务可把 `GOMAXPROCS` 设得比核数大一些：虽然 M 被阻塞到切换有延迟，但更大的 P 数能让更多 G 在剩余 M 上跑，缓解 syscall 带来的 CPU 空窗。

## Links

- [Go 语言总览](/docs/CS/Go/Go.md)
- [Goroutine 与 GMP 结构体](/docs/CS/Go/Concurrency/Goroutine.md)

## References

1. [Go 调度器源码（runtime/proc.go）](https://github.com/golang/go/blob/master/src/runtime/proc.go)
2. [The Go scheduler · golang/go wiki](https://github.com/golang/go/wiki/GoScheduler)
3. [Go 语言设计与实现 · 调度器](https://draveness.me/golang/docs/scheduler/)
4. [Go 1.14 基于信号的异步抢占](https://go.dev/doc/go1.14)
5. [Go 官方文档 · 内存模型（happens-before）](https://go.dev/ref/mem)
