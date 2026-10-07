## Introduction

`sync/atomic` 提供基于 CPU 原子指令（[CAS](/docs/CS/Java/JDK/Basic/unsafe.md?id=cas) 等）的底层原语，用于在**不加锁**的情况下对单个变量做线程安全的读写。
它是实现 lock-free 数据结构的积木，也是 [Mutex](/docs/CS/Go/Concurrency/Lock.md) 内部 fast path 的底层依赖——Mutex 无竞争时拿锁就是一次原子 CAS。

```go
import "sync/atomic"

var counter int64
atomic.AddInt64(&counter, 1)          // 原子自增
v := atomic.LoadInt64(&counter)       // 原子读
old := atomic.SwapInt64(&counter, 0)  // 原子交换并返回旧值
// CAS：仅当 counter == old 时才写入 new，返回是否成功
swapped := atomic.CompareAndSwapInt64(&counter, old, new)
```

## Operations

- **Add**：原子加减（`AddInt64`/`AddUint64` 等），自增计数、信号量风格的配额都用它。
- **Load / Store**：保证读到/写入一个完整、不撕裂的值，并附带 happens-before 的可见性语义（对齐到 [Go 内存模型](/docs/CS/Go/Concurrency/MemoryModel.md)）。
- **Swap / CompareAndSwap**：Swap 无条件换；CAS 条件换，是无锁算法的核心——「读旧值 → 计算新值 → CAS 提交」，失败则重试（retry loop）。
- **Pointer / Value**：`atomic.Pointer[T]`（泛型，Go 1.19+）与 `atomic.Value` 支持原子地整体替换一个接口/指针，常用于**无锁配置热更新、单例切换**：Store 一个新配置，所有读方 Load 到的总是某个完整版本，不会看到半更新状态。

## Generic Atomic Types (Go 1.19+)

Go 1.19 起，`sync/atomic` 提供一组**类型安全的原子值类型**，把「传 `&x` + 函数式 API」升级成「方法式 API」，且对指针类型做到编译期类型检查。它们底层用的还是同一套原子指令，只是接口更友好、更不容易写错（不必反复手写 `&x`、不必担心对齐/地址传错）。

类型清单：`atomic.Bool`、`atomic.Int32`、`atomic.Int64`、`atomic.Uint32`、`atomic.Uint64`、`atomic.Uintptr`、`atomic.Pointer[T]`（泛型），后续版本又补齐了 `Int8/Uint8/Int16/Uint16` 等窄整型变体。

- 数值类型方法：`Load() T`、`Store(v T)`、`Add(delta T) T`（返回新值）、`Swap(v T) T`、`CompareAndSwap(old, new T) bool`；
- `atomic.Bool` 对应 `Load/Store/Swap/CompareAndSwap`（参数与返回值均为 `bool`）；
- `atomic.Pointer[T]`：泛型参数 `T` 是**指向的类型**，方法读写的是 `*T`——`Load() *T`、`Store(*T)`、`Swap(*T) *T`、`CompareAndSwap(old, new *T) bool`，**取代** `atomic.Value` 承载指针的场景，省去 `interface{}` + 类型断言、把类型错误从运行期提前到编译期。

```go
var counter atomic.Int64
counter.Add(1)
n := counter.Load()

var stopped atomic.Bool
if stopped.CompareAndSwap(false, true) { /* 只跑一次，无需 Mutex */ }

type Config struct{ /* ... */ }
var config atomic.Pointer[Config]
config.Store(&newCfg)
cfg := config.Load() // *Config，类型安全，无需断言
```

选型：新代码优先用类型化原子；函数式 `atomic.AddInt64` 等仍保留，适用于手头只有普通 `*int64` 或需要与旧代码互操作的场景。当要原子替换的不是一个指针、而是一个任意值（如某个 struct 整体），仍可用非泛型的 `atomic.Value`。注意 `atomic.Pointer[T]` 的 `T` 是所指向的类型（方法操作 `*T`），不能把值类型直接放进去。

## CAS Loop (Lock-Free Mode)

```go
for {
    old := atomic.LoadInt64(&v)
    next := compute(old)
    if atomic.CompareAndSwapInt64(&v, old, next) {
        break // 提交成功；若期间被别人改过，CAS 失败，重新读再试
    }
}
```

高竞争下 CAS 会反复失败重试（活锁/浪费 CPU），此时一把 [Mutex](/docs/CS/Go/Concurrency/Sync.md) 往往吞吐更稳。原子操作只适合**单个独立变量**或极短的临界区，多变量需要保持一致时必须用锁。

## Atomic vs Mutex vs Channel

| 方式 | 适合 | 代价/注意 |
| --- | --- | --- |
| atomic | 单个计数、标志位、指针整体替换、lock-free 结构 | 只保护单变量；复合更新要 CAS 重试；易错 |
| Mutex/RWMutex | 临界区、多字段一致、map 等复合状态 | 有挂起/唤醒开销，但竞争下稳定 |
| channel | 在 goroutine 间传递数据所有权、编排工作流 | 表达「事件/数据流」，不适合保护一个计数器 |

经验法则：**计数器、配置指针、停止标志用 atomic；保护一段共享状态用 Mutex；流转数据用 [channel](/docs/CS/Go/Concurrency/Channel.md)**。
另外 `sync.Map`、`WaitGroup` 等内部也用 atomic，但业务代码不要用 atomic 去手工拼一个并发 map。

## Pitfalls

- 原子操作只作用于传入的**地址**，被操作变量必须按机器字对齐，且不能被复制（应通过指针共享）；64 位原子在 32 位平台要求 8 字节对齐（用结构体首位分配或池化保证）。
- `atomic.AddUint64(&x, ^uint64(delta-1))` 这类「无符号数实现减法」的写法可读性差，优先用有符号类型。
- 不要混用原子与非原子访问同一变量——一半 LoadInt64 一半普通读会产生数据竞争，`go test -race` 能抓出来。
- `int64` 自增不是语言层面的原子操作，普通 `i++` 在并发下不安全。

## Links

- [Golang](/docs/CS/Go/Go.md)
- [Lock（Mutex 实现）](/docs/CS/Go/Concurrency/Lock.md)
- [Sync](/docs/CS/Go/Concurrency/Sync.md)
- [Go Memory Model](/docs/CS/Go/Concurrency/MemoryModel.md)
- [Go Concurrency 总览](/docs/CS/Go/Concurrency/Concurrency.md)

## References

1. [Package sync/atomic](https://pkg.go.dev/sync/atomic)
