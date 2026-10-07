## Introduction

`golang.org/x/sync/semaphore` 提供 `Weighted`——一个**带权计数信号量**：调用方可以一次申请 n 个单位的资源，运行时在「总配额 - 已占用」足够且 ctx 未取消时放行。它是限制**并发度**的标准件，尤其适合「不同任务占用不同资源量」或「并发数受外部配额（数据库连接、下游 QPS）约束」的场景。

与用 channel 当信号量（`sem := make(chan struct{}, 10)`）相比，`Weighted` 的关键点是**加权**：一次可以 `Acquire(3)`，而不是固定 1 个单位；与 [errgroup.SetLimit(n)](/docs/CS/Go/Concurrency/errgroup.md) 相比，它是更底层的原语——errgroup 的并发上限背后正是借它实现的。

## Core API

```go
import "golang.org/x/sync/semaphore"

// NewWeighted：创建总配额为 n 的加权信号量；n 为负会 panic
sem := semaphore.NewWeighted(int64(10))

// Acquire：阻塞直到拿到 n 个单位，或 ctx 取消；取消时返回 ctx.Err() 且不占有任何单位
if err := sem.Acquire(ctx, 3); err != nil {
    return err
}
defer sem.Release(3)

// TryAcquire：非阻塞版本，拿不到立即返回 false（信号量不变）
if sem.TryAcquire(1) {
    defer sem.Release(1)
} else {
    // 直接走降级路径，不阻塞
}
```

- `NewWeighted(n int64) *Weighted`：总并发权重上限；`n < 0` 直接 panic。
- `(*Weighted).Acquire(ctx, n)`：申请 n 个单位。成功返回 nil；若 ctx 先 Done，返回 `ctx.Err()` 且**不占有**任何单位。
- `(*Weighted).TryAcquire(n) bool`：非阻塞，成功 true、失败 false，信号量均保持不变。
- `(*Weighted).Release(n)`：归还 n 个单位；**过量归还（归还量超过已持有）会 panic**。

## Typical Usage: Rate-limiting Concurrent Tasks

```go
func fetchAll(ctx context.Context, urls []string) error {
    sem := semaphore.NewWeighted(int64(10)) // 最多 10 个并发
    var wg sync.WaitGroup
    for _, u := range urls {
        u := u
        if err := sem.Acquire(ctx, 1); err != nil {
            break // ctx 取消
        }
        wg.Add(1)
        go func() {
            defer wg.Done()
            defer sem.Release(1)
            _ = fetch(ctx, u)
        }()
    }
    wg.Wait()
    return nil
}
```

申请与归还成对、用 `defer Release` 保证异常路径也归还；还想聚合错误就换 [errgroup.SetLimit](/docs/CS/Go/Concurrency/errgroup.md)，它内部正是用 `Weighted` 压并发。

## Trade-offs with channel / errgroup / worker pool

| 方案 | 能力 | 适合 |
| --- | --- | --- |
| `make(chan struct{}, n)` 当信号量 | 固定 1 单位/次，最简单 | 所有任务占用相同、且只需「最多 n 个在跑」 |
| `semaphore.Weighted` | 加权 Acquire/Release，可按任务粒度借资源 | 任务占用不均、或受外部配额约束 |
| `errgroup.SetLimit(n)` | 限并发 + 错误聚合 + 取消传播 | 一组 goroutine、要等齐并聚合错误 |
| worker pool（见 [并发模式](/docs/CS/Go/Concurrency/Patterns.md)） | 固定 worker 消费任务队列 | 同构任务的批量处理，控制更精细 |

经验法则：只要「并发度」是唯一约束、任务彼此独立 → channel 或 `Weighted` 即可；需要「错误聚合 / 失败取消其余」→ [errgroup](/docs/CS/Go/Concurrency/errgroup.md)；任务同构且想避免每个任务起一个 goroutine → 走 worker pool。

## Implementation Notes (FIFO Waiting)

`Weighted` 内部维护一个 FIFO 等待队列，每个等待者记录自己要申请的权重 n 和一个用于唤醒的 channel；同时保存已分配总量 `cur` 与上限 `size`：

- **Acquire 快路径**：若 `cur + n <= size` 且当前没有排队的等待者，直接 `cur += n` 返回，无需入队。
- **Acquire 慢路径**：否则把等待者入队，在 `select` 中同时等 `ctx.Done()` 与自己的唤醒 channel——ctx 先到则返回 `ctx.Err()` 并出队。
- **Release**：`cur -= n` 后，按入队顺序遍历等待者，凡是「剩余容量够其权重」的就唤醒、出队并扣减 `cur`，直到容量不足或队列空。FIFO 保证先到先得，避免饥饿。

> 注意：等待者只在 Release 时被重新评估，所以「大权重」请求如果前面一直有小请求在跑，可能要等队列清空才轮到——这是 FIFO 的代价，设计配额时要考虑到。

## Links

- [Go Concurrency 总览](/docs/CS/Go/Concurrency/Concurrency.md)
- [Golang](/docs/CS/Go/Go.md)

## References

1. [Package semaphore](https://pkg.go.dev/golang.org/x/sync/semaphore)
2. [golang.org/x/sync 源码（semaphore.go）](https://cs.opensource.google/go/x/sync/+/v0.23.0:semaphore/semaphore.go)
