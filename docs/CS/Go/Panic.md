## Introduction

`panic` 与 `recover` 是 Go 仅有的"控制流中断 / 恢复"原语，用于表达**不可恢复的程序员错误**（区别于 `error` 的寻常错误流）。理解 `gopanic` 的 unwind 过程与 `recover` 的生效边界，能避免"以为 recover 了其实没生效"的常见误用。

## 三种 panic 来源

- **主动**：代码调用 `panic(v)`；
- **编译器插入**：除零、nil 指针解引用、数组 / 切片越界、向已关闭 channel 发送等——编译期生成的隐式 `panic` 调用；
- **运行时信号**：非法地址访问等硬件 / 信号被 runtime 捕获后转为 panic。

## gopanic 与 _panic 链

`panic(v)` 进入 `runtime.gopanic`，构造一个 `_panic` 压入 `g._panic` 链，然后沿 `g._defer` 链表从新到旧执行每个 defer：

```go
// runtime/runtime2.go
type _panic struct {
    argp      unsafe.Pointer // 指向 defer 的参数帧
    arg       any
    link      *_panic
    pc        uintptr
    recovered bool
    aborted   bool
    goexit    bool
}
```

- 执行 defer 时若其调用了 `recover()`，实际调用 `gorecover`，会把当前 `_panic.recovered` 置 true；该 defer 执行完后，runtime 检测到 recovered，停止 unwind，视作函数正常返回（defer 之后的代码**不会**执行）。
- 若所有 defer 执行完仍无人 `recover`，runtime 打印完整 goroutine 栈（`panic: ...` + `goroutine X [running]`），随后进程以状态码 2 退出。

## recover 的生效边界

`recover()` 只在**直接位于 defer 函数体中**时有效；放到普通函数、或 defer 调用的嵌套函数里都返回 nil、不恢复：

```go
defer func() {
    recover()          // 有效：直接位于 defer 体
}()
defer func() {
    f := func() { recover() } // 无效：藏在嵌套函数里
    f()
}()
```

recover 之后当前 panic 被"消费"；若 defer 内又 panic，会再压入新 `_panic`，`recover` 只处理最新的一条。

## panic(nil) 与 PanicNilError

Go 1.21 起，`panic(nil)` 会被转换为 `*runtime.PanicNilError`（"panic called with nil error"），从而 `recover()` 拿到的不再是 nil——防止"用 nil 恢复、却误以为成功抑制了 panic"的静默 bug。

## Goexit：与 panic 不同

`runtime.Goexit()` 会执行完当前 goroutine 的全部 defer 后**直接终止该 goroutine**，它**不是 panic**，因此 `recover()` 无法拦截；常用于测试或要"干净退出 goroutine"的场景。`os.Exit` 则连 defer 都不执行。

## error 还是 panic

| 维度 | error | panic |
|------|-------|-------|
| 适用 | 预期内的错误流（文件不存在、网络超时） | 不可恢复 / 程序级 bug（断言失败、初始化强依赖缺失） |
| 处理 | 每层 `if err != nil` 上抛或处理 | 顶层 recover 兜底，或进程退出 |
| 性能 | 零开销 | 昂贵（栈展开） |

详见错误处理标准库与 Issues（#48 panicking）。

## Links

- [defer 实现机制](/docs/CS/Go/Defer.md)
- [错误处理标准库](/docs/CS/Go/Errors.md)
- [Go 语言总览](/docs/CS/Go/Go.md)

## References

1. [The Go Programming Language Specification: Handling panics](https://go.dev/ref/spec#Handling_panics)
1. [Go 1.21 Release Notes（panic(nil)）](https://go.dev/doc/go1.21)
1. [runtime/panic.go](https://github.com/golang/go/blob/master/src/runtime/panic.go)
