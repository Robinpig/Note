## Introduction

`errgroup` 是 `golang.org/x/sync/errgroup` 提供的**子任务组**工具：让你启动一组 goroutine、等待它们全部完成，并**聚合第一个返回的错误**；配合 `errgroup.WithContext` 还能在任一子任务失败时，**自动取消其余子任务**。它是 `sync.WaitGroup` 的增强版——WaitGroup 只负责"等大家都结束"，`errgroup` 额外负责"错误聚合 + 取消传播"。

典型场景：一个请求需要并发调用多个下游服务，任何一个失败就整体失败，并让还在跑的调用及时退出，避免浪费资源。

## 核心 API

```go
// 基础用法：无 context，只聚合错误
g := new(errgroup.Group)
for _, url := range urls {
    url := url
    g.Go(func() error { return fetch(url) })
}
if err := g.Wait(); err != nil { // 返回第一个非 nil 错误
    log.Fatal(err)
}

// 带 context：任一 Go 返回错误，ctx 被 cancel
g, ctx := errgroup.WithContext(context.Background())
for _, url := range urls {
    url := url
    g.Go(func() error {
        // 子任务应监听 ctx.Done()，被取消时及时退出
        return fetchWithCtx(ctx, url)
    })
}
if err := g.Wait(); err != nil {
    log.Fatal(err)
}
```

- `(*Group).Go(f func() error)`：启动一个 goroutine 执行 `f`；`f` 返回的错误会被记录（只保留第一个）。
- `(*Group).Wait() error`：阻塞直到所有 `Go` 启动的任务完成，返回第一个非 nil 错误（无错误返回 nil）。
- `WithContext(parent) (*Group, ctx)`：返回一个 Group 和派生的 `ctx`；**一旦任意一个 `Go` 返回非 nil 错误，`ctx` 立即被取消**，其余监听该 `ctx` 的子任务可据此退出。

## 与 WaitGroup 的对比

| 维度 | sync.WaitGroup | errgroup.Group |
| --- | --- | --- |
| 等待全部完成 | ✅ `Wait` | ✅ `Wait` |
| 错误聚合 | ❌ 需自己收集 | ✅ 取第一个错误 |
| 失败取消其余任务 | ❌ | ✅ `WithContext` 自动 cancel |
| 返回错误信息 | 无 | 第一个 error |

经验法则：**只要子任务会返回 error、或需要"一个失败全撤"，就用 `errgroup`**；纯"等一组无错任务"才用 WaitGroup。注意 `errgroup` 不像 `WaitGroup` 那样对 `f` 里的 panic 做 recover——`Go` 的 `f` 若 panic，会沿 goroutine 上抛（由进程级的 panic 处理决定），不会在 `Wait` 里被静默吞掉，所以 `f` 内部该 recover 还是要自己 recover。

## 限制并发度（配合 semaphore）

`errgroup.Group` 本身**不限并发度**——`Go` 会立刻起一个新 goroutine。需要限制同时运行的子任务数时，用 `g.SetLimit(n)`（Go 1.20+，来自 `golang.org/x/sync/errgroup` 的 `limit.go`），底层借助 `golang.org/x/sync/semaphore` 把并发压到 n：

```go
g, ctx := errgroup.WithContext(context.Background())
g.SetLimit(10) // 最多 10 个并发
for _, item := range items {
    item := item
    g.Go(func() error { return process(ctx, item) })
}
_ = g.Wait()
```

## 与 context 的协作边界

`WithContext` 派生的 `ctx` 只在**出错时**取消。它**不提供超时**——若需要超时，应当用 `context.WithTimeout` 作为 `parent` 传入：`g, ctx := errgroup.WithContext(context.WithTimeout(context.Background(), 5*time.Second))`。

## Links

- [Go Concurrency 总览](/docs/CS/Go/Concurrency/Concurrency.md)
- [Context](/docs/CS/Go/Concurrency/Context.md) — 取消信号的来源
- [Goroutine](/docs/CS/Go/Concurrency/Goroutine.md)
- [Sync](/docs/CS/Go/Concurrency/Sync.md) — WaitGroup 的对比参照
- [singleflight](/docs/CS/Go/Concurrency/singleflight.md) — 另一类"合并请求"的同步件

## References

1. [Package errgroup](https://pkg.go.dev/golang.org/x/sync/errgroup)
2. [Go 语言设计与实现 - 多线程同步](https://draveness.me/golang/docs/part3-runtime/ch06-concurrency/golang-sync-primitives/)
