## Introduction

Go 的并发哲学是「share by communicating」——通过 channel 在 goroutine 之间传递数据的所有权，而非共享内存 + 锁。但 channel 不是银弹：临界区保护仍用 `sync.Mutex` / `atomic`，而**并发模式**解决的是「如何把 goroutine + channel + context 组合成可复用结构」。本文按使用频率列最常见的几种，每个都给最小可运行示例。

channel 与锁的判据（何时该用哪个）见 [Concurrency](/docs/CS/Go/Concurrency/Concurrency.md) 的 Share by Communicating 段：channel 表达「数据流动 / 事件」，锁表达「状态此刻互斥访问」。

## Worker Pool（工作者池）

固定一组 worker goroutine 从同一个 `jobs` channel 取任务、把结果写到 `results` channel，用 quit channel 或 context 做统一退出。比起「来一个请求起一个 goroutine」，worker pool 能平滑突增流量、限制资源占用。

```go
func worker(ctx context.Context, id int, jobs <-chan int, results chan<- int) {
    for {
        select {
        case <-ctx.Done():
            return
        case j, ok := <-jobs:
            if !ok {
                return // jobs 已被关闭
            }
            results <- j * j
        }
    }
}

func main() {
    ctx, cancel := context.WithCancel(context.Background())
    defer cancel()
    jobs, results := make(chan int), make(chan int)
    for i := 0; i < 3; i++ { // 启动 3 个 worker
        go worker(ctx, i, jobs, results)
    }
    // ... 投喂 jobs、收集 results、close(jobs) 收尾 ...
}
```

退出有两种等价方式：`close(done)` 广播（见 [Channel](/docs/CS/Go/Concurrency/Channel.md) 的 close 语义），或 `ctx` 取消（见 [Context](/docs/CS/Go/Concurrency/Context.md)）。要限制 worker 数量，直接控制启动的 goroutine 个数；要限制**并发任务数**而非 worker 数，用下方的限流模式。

## Pipeline（流水线）

把处理拆成多个阶段，每阶段是一个「接收上游 channel → 处理 → 写入下游 channel」的 goroutine，阶段间用 channel 串联。上游阶段负责 `close` 自己的输出 channel，下游用 `for range` 自然收尾（见 [Channel](/docs/CS/Go/Concurrency/Channel.md) 的 for-range 约定）。

```go
func gen(nums ...int) <-chan int { // stage 1：输出
    out := make(chan int)
    go func() { defer close(out); for _, n := range nums { out <- n } }()
    return out
}
func sq(in <-chan int) <-chan int { // stage 2：平方
    out := make(chan int)
    go func() { defer close(out); for n := range in { out <- n * n } }()
    return out
}
// 串联：out := sq(gen(2, 3, 4))
```

取消传播：任意阶段出错应让整条流水线退出——把每个阶段的 select 都监听同一个 `ctx.Done()`，错误上游 `cancel(ctx)`，下游在 Done 后 `return`，避免「孤儿 goroutine」泄漏（见 [Goroutine](/docs/CS/Go/Concurrency/Goroutine.md) 的泄漏章节）。

## Fan-in / Fan-out（扇入 / 扇出）

- **Fan-out**：一个 channel 被多个 worker 同时消费（分摊计算，天然负载均衡，因为 channel 每次只递交给一个接收者）。
- **Fan-in**：多个 worker 的结果汇入一个 channel，供下游统一消费。常用 `reflect.Select` 或单独起 goroutine 把每个输入 channel 转发到同一个输出（见 [select](/docs/CS/Go/Concurrency/select.md) 的反射式 select）。

```go
func fanIn(a, b <-chan int) <-chan int {
    out := make(chan int)
    var wg sync.WaitGroup
    wg.Add(2)
    for _, in := range []<-chan int{a, b} { // 两个转发 goroutine
        go func(c <-chan int) {
            defer wg.Done()
            for v := range c { out <- v }
        }(in)
    }
    go func() { wg.Wait(); close(out) }() // 全部转发完再关闭 out
    return out
}
```

## 限流（限制并发度）

三种层次，按需取用：

- **channel 当信号量**：`sem := make(chan struct{}, n)`，`sem <- struct{}{}` 获取、`<-sem` 释放，限制同时进行的 goroutine 数。最轻量。
- **errgroup.SetLimit**：`g, _ := errgroup.WithContext(ctx); g.SetLimit(n)`，每个 `g.Go` 受同一上限约束，且任一失败自动 cancel（见 [errgroup](/docs/CS/Go/Concurrency/errgroup.md)）。
- **semaphore.Weighted**：`golang.org/x/sync/semaphore` 的 `Acquire` / `Release`，支持「加权」获取（一次占多个配额），适合异构任务。

```go
sem := make(chan struct{}, 10) // 最多 10 个并发
var wg sync.WaitGroup
for _, task := range tasks {
    wg.Add(1)
    sem <- struct{}{}
    go func(t Task) {
        defer wg.Done()
        defer func() { <-sem }()
        process(t)
    }(task)
}
wg.Wait()
```

## 退出与取消传播

长期运行的服务里，子 goroutine 必须能被「优雅退出」，否则就是 [goroutine 泄漏](/docs/CS/Go/Concurrency/Goroutine.md)。两条等价广播路径：

- **done channel**：主 goroutine `close(done)`，所有 `<-done` 监听者同时收到零值退出。
- **context 取消**：`cancel()` 后 `ctx.Done()` 关闭，所有监听者退出；且能携带截止时间与值。

选择：纯内部、无截止时间需求用 done channel 更轻；需要超时 / 跨调用链传递 / 与 RPC·HTTP 框架对接用 context。二者广播语义一致，可混用（见 [Context](/docs/CS/Go/Concurrency/Context.md)）。

## for-range 退出约定

发送方 `close(ch)` 后，接收方的 `for v := range ch` 在缓冲耗尽后自动结束——**关闭是发送方的职责**，接收方不应 close 别人的 channel（会导致 [panic](/docs/CS/Go/Concurrency/Channel.md)）。这条约定是 pipeline / fan-in 收尾的基础，违反它会引发「close of closed channel」或「send on closed channel」。

## Links

- [Go 语言枢纽](/docs/CS/Go/Go.md)
