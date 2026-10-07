## Introduction

`singleflight` 来自 `golang.org/x/sync/singleflight`，解决的问题是：**把对同一个 key 的并发重复调用，合并成一次真实执行，让所有调用方共享这一次的结果**。最经典的场景是**缓存击穿防护**——热点 key 失效瞬间，成千上万个请求同时打到 `Get(key)`，若不加约束都会回源数据库；`singleflight` 保证同一 key 只回源一次，其余请求直接拿到同一份结果。

它与 [errgroup](/docs/CS/Go/Concurrency/errgroup.md) 常被混淆：errgroup 是"等待**一组不同**任务并聚合错误"，singleflight 是"合并**同一 key 的多个相同**请求"。

## Core API

```go
var g singleflight.Group

// Do：阻塞直到 fn 执行完毕，返回结果与是否共享
v, err, shared := g.Do("user:123", func() (interface{}, error) {
    return loadFromDB(123) // 只有一个调用真的执行它
})

// DoChan：非阻塞版本，通过 channel 拿结果
ch := g.DoChan("user:123", func() (interface{}, error) {
    return loadFromDB(123)
})
res := <-ch // res.Val / res.Err / res.Shared

// Forget：忘记这个 key，让下一次 Do 重新执行 fn（不共享上一次）
g.Forget("user:123")
```

- `Do(key, fn)`：若已有相同 key 的调用在进行，`caller` 不会执行自己的 `fn`，而是**加入等待**，等进行中的 `fn` 返回后共享其 `v/err`；`shared == true` 表示结果是共享来的（自己没有真正执行 `fn`）。
- `DoChan(key, fn)`：同上，但不阻塞当前 goroutine，返回一个 `chan Result`。
- `Forget(key)`：把 key 从"进行中"集合移除。此后对同一 key 的新 `Do` 会另起一次 `fn` 执行。

## Implementation Principle (inFlight Merging)

内部维护一个 `call` 结构表示"正在进行一次 key 的调用"，以及一个 `inFlight map[string]*call`：

```go
type call struct {
    wg  sync.WaitGroup // 第一个执行者完成前，其余 join 者在此等待
    val interface{}
    err error
    dups  int            // 共享者数量
    chans []chan Result  // DoChan 的等待者
}
```

- `Do` 进来先看 `inFlight[key]`：已存在则 `dups++`、注册自己（追加到 `chans` 或直接等 `wg`），**不执行 `fn`**；
- 不存在则新建 `call`、`inFlight[key] = c`、执行 `fn`，结束后 `wg.Done()` 唤醒所有等待者，并从 `inFlight` 删除该 key；
- `fn` 返回 `err` 时，所有等待者都拿到同一个 `err`，**且该 key 不会自动 Forget**（下一次同 key 调用会重新执行 `fn`）——除非显式 `Forget`。

## Example: Preventing Cache Breakdown

```go
func (c *Cache) Get(key string) (string, error) {
    if v, ok := c.local.Get(key); ok {
        return v, nil // 命中，直接返回
    }
    v, err, _ := c.g.Do(key, func() (interface{}, error) {
        return c.db.Load(key) // 同一 key 并发只回源一次
    })
    if err == nil {
        c.local.Set(key, v)
    }
    return v.(string), err
}
```

## Pitfalls

- `shared == true` 时结果是"借用"的，不要对返回值做可变原地修改（可能污染其它共享者）。
- `fn` 返回错误时该 key 不会被 Forget，下一次调用会重新执行——这是正确行为，避免一次失败把 key 永久"钉死"在错误结果上。
- `singleflight` **不限制** key 的数量与并发执行数，只是对"同 key"去重；不同的 key 仍会各自执行。
- 不要把它当限流器用——限制并发度应交给 semaphore（golang.org/x/sync/semaphore）或 `errgroup.SetLimit`（见 [errgroup](/docs/CS/Go/Concurrency/errgroup.md)）。

## Links

- [Go Concurrency 总览](/docs/CS/Go/Concurrency/Concurrency.md)
- [errgroup](/docs/CS/Go/Concurrency/errgroup.md) — 对比：合并同 key vs 等待一组不同
- [Context](/docs/CS/Go/Concurrency/Context.md)

## References

1. [Package singleflight](https://pkg.go.dev/golang.org/x/sync/singleflight)
2. [groupcache/singleflight 源码](https://github.com/golang/groupcache/blob/master/singleflight/singleflight.go)
