## Introduction

`sync.Mutex` 是 Go 最常用的互斥原语。它的 API 极简（`Lock`/`Unlock`/`TryLock`），但运行时实现经历了明显演进，
核心思想是**公平与性能的折中**：无竞争时一条原子指令即可拿锁；有竞争时先短暂自旋，再进入信号量挂起等待，避免大量 goroutine 空转烧 CPU。
用法与注意事项见 [Sync](/docs/CS/Go/Concurrency/Sync.md)，本篇聚焦其内部实现。

## State

`sync.Mutex` 只有两个字段：

```go
type Mutex struct {
    state int32   // 状态位：mutexLocked / mutexWoken / mutexStarving + waiter 计数
    sema  uint32  // 信号量，等待者在它上面 park / 被 wake
}
```

`state` 低位是三个标志：`mutexLocked`（已加锁）、`mutexWoken`（有人在正常路径被唤醒，避免解锁时无谓唤醒）、
`mutexStarving`（进入饥饿模式）；高位存放等待者数量（waiter count）。等待/唤醒最终走 runtime 的信号量
（`runtime_SemacquireMutex` / `runtime_Semrelease`），由调度器把 goroutine park 到等待队列，而不是忙等。

## Fast Path and Slow Path

- **正常路径（fast path）**：无竞争时 `Lock` 就是一次 CAS 把 `mutexLocked` 置位，成功立即返回，无系统级开销。
- **慢速路径（slow path）`lockSlow`**：CAS 失败后进入，先在满足条件时**自旋（spinning）**几次，期望持锁者很快释放（临界区很短时，自旋比挂起/唤醒便宜）；
  自旋期间会设置 `mutexWoken`。仍拿不到则把 waiter 计数 +1，调用信号量把自己挂起。

这与 Linux 内核 [futex](/docs/CS/OS/Linux/Lock/futex.md)「用户态先原子试、失败再陷入内核等待」的两段式设计是同一个套路。

## Normal and Starvation Modes

Go 1.9 引入饥饿模式，解决极端竞争下新来的 goroutine（正在 CPU 上运行）反复插队、导致被挂起的等待者长期拿不到锁的问题：

- **正常模式（Normal）**：解锁时唤醒一个等待者，但被唤醒者要和新到达的 goroutine **竞争**锁。新到者正占着 CPU，胜率更高，吞吐更好；可一旦某个等待者超过 `1ms`（starvationThresholdNs）仍未抢到，切到饥饿模式。
- **饥饿模式（Starving）**：解锁直接把锁**移交给队首等待者**，新来者不再尝试抢锁、直接排队。等队首拿到锁后，若它是最后一个等待者或等待时间已低于阈值，切回正常模式。

正常模式追求吞吐，饥饿模式保证尾延迟与无饥饿，二者自动切换。

## RWMutex

`sync.RWMutex` 在 Mutex 之上构建「多读单写」语义，内部用一个 Mutex 保护写者，再加 reader 计数信号量：

- 读锁 `RLock`：原子递增 readerCount，为负（有写者在等待）时在信号量上排队，否则直接进入；
- 写锁 `Lock`：先拿内部 Mutex，再把 readerCount 减去 `rwmutexMaxReaders` 变成负值「拦住后续新读者」，并等待在途读者归零；
- 因此 **RWMutex 适合读远多于写、且临界区较长**的场景。极短临界区下，原子操作与写者插队的开销可能让它还不如一把 Mutex。

## Pitfalls

- `Unlock` 未加锁的 Mutex 会 panic；务必 `defer mu.Unlock()` 紧挨 `Lock` 之后写。
- Mutex 不可重入：Go 不维护持有者/加锁次数，对同一把锁二次 Lock 会自锁（与 Java [ReentrantLock](/docs/CS/Java/JDK/Concurrency/ReentrantLock.md) 不同）。
- Mutex 复制即出错：拷贝会连状态位一起复制，两把「锁」互不影响，应通过指针共享，`go vet` 的 copylocks 检查会报警。
- 不要用 channel 或 sleep 去「实现」互斥，保护共享状态用 Mutex/[atomic](/docs/CS/Go/atomic.md) 最直接。

## Links

- [Sync](/docs/CS/Go/Concurrency/Sync.md) — Mutex/RWMutex/WaitGroup/Once 的用法
- [Goroutine](/docs/CS/Go/Concurrency/Goroutine.md)
- [Go Concurrency 总览](/docs/CS/Go/Concurrency/Concurrency.md)
- [runtime 与调度](/docs/CS/Go/runtime.md)
- [Java AQS](/docs/CS/Java/JDK/Concurrency/AQS.md) — 对照：CLH 队列 + 状态位的另一套锁实现
- [futex](/docs/CS/OS/Linux/Lock/futex.md)

## References

1. [sync package - sync.Mutex](https://pkg.go.dev/sync#Mutex)
2. [Go 语言设计与实现 - Mutex](https://draveness.me/golang/docs/part3-runtime/ch06-concurrency/golang-sync-primitives/)
