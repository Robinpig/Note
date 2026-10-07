## Introduction

`error` 是 Go 内建的接口类型，而非异常。它承载"可预期的失败"，与 panic 的"不可恢复错误"分工明确。Go 1.13 引入 `%w` 包装与 `errors.Is` / `errors.As`，让错误链上的判定与类型提取变得可组合。

## error Interface and Sentinel

```go
type error interface { Error() string }
```

- `errors.New("msg")` 返回 `*errors.errorString`；`fmt.Errorf("msg")` 返回 `*fmt.wrapError`（无包装）。
- **sentinel error**（哨兵错误）是包级导出的预定义错误值，用 `==` 比较：`io.EOF`、`sql.ErrNoRows`，以及 Go 1.20 加入的 `errors.ErrUnsupported`。
- 注意：sentinel 只适用于"调用方需要按值区分"的场景；不要为每一种失败都造一个 sentinel。

## Error Wrapping and Chain

Go 1.13 起，`fmt.Errorf("read %s: %w", name, err)` 用 `%w` 把 `err` 包进新错误，新错误实现 `Unwrap() error` 从而可被"解开"：

| 操作 | 作用 | 典型用途 |
|------|------|----------|
| `errors.Unwrap(err)` | 取被 `%w` 包装的内层错误 | 手动向下钻 |
| `errors.Is(err, target)` | 沿 `Unwrap` 链逐层比较，命中即 true（若某层实现 `Is(error) bool` 方法则以它为准） | 判断是否"某种 sentinel"（即使被多层包装） |
| `errors.As(err, &target)` | 沿链做类型断言，找到第一个能赋给 `target` 的类型 | 取出具体错误类型读字段 |

- 关键坑：包装后的错误用 `==` 比较**永远不相等**，必须用 `errors.Is`。参见 Issues（#50 / #51 错误类型与对象比较）。
- `%v` 只格式化、不包装；只有 `%w` 才建立链。

## errors.Join（Go 1.20）

`errors.Join(errs...)` 把多个错误合并为一个，其 `Unwrap()` 返回所有子错误切片，便于在一次操作中收集多处失败（如并行任务的部分失败）。

## Custom Error Types

```go
type MyError struct {
    Op  string
    Err error
}
func (e *MyError) Error() string { return e.Op + ": " + e.Err.Error() }
func (e *MyError) Unwrap() error { return e.Err }   // 支持 errors.Is/As 向下钻
func (e *MyError) Is(target error) bool { ... }     // 自定义 Is 判定
```

约定：仅当调用方需要按类型 / 字段区分时才定义自定义类型；自定义类型应实现 `Unwrap` 以保持链可穿透。

## Error vs panic (Reemphasis)

error 用于寻常错误流，每层 `if err != nil` 处理或上抛；panic 仅用于不可恢复的程序级 bug（详见 panic/recover 机制）。不要把 error 当 exception 用、到处 `panic`。

## Links

- [panic/recover 机制](/docs/CS/Go/Panic.md)
- [Go 语言总览](/docs/CS/Go/Go.md)
- [Issues：常见错误](/docs/CS/Go/Issues.md)
- [Exceptions](/docs/CS/Python/Exceptions.md)

## References

1. [Go 1.13 Release Notes（error wrapping）](https://go.dev/doc/go1.13#error_wrapping)
1. [Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors)
1. [pkg.go.dev/errors](https://pkg.go.dev/errors)
