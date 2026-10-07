## Introduction

`defer` 让函数"退出前"执行一段清理逻辑，是 Go 资源管理的惯用法（关闭文件、解锁、恢复 panic）。表面上它像"析构 / RAII"，底层由 runtime 通过 `_defer` 记录与延迟调用机制实现。Go 1.14 起，`defer` 在多数简单场景下被**开放编码（open-coded）**优化，几乎零开销。

## _defer Records

每次执行 `defer f()`，runtime 会生成一条 `_defer` 记录，挂在当前 goroutine 的 `g._defer` 链表上（链表头即最近一次 defer，因此执行顺序是 **LIFO**）：

```go
// runtime/runtime2.go
type _defer struct {
    started   bool
    heap      bool     // 是否分配在堆上（开放编码为 false）
    openDefer bool     // 是否为开放编码 defer
    sp        uintptr  // 注册时的栈指针，用于匹配
    pc        uintptr
    fn        func()   // 延迟调用的函数
    _panic    *_panic  // 触发本 defer 的 panic（用于 recover 判断）
    link      *_defer   // 指向上一条 _defer
}
```

## Two Implementation Paths

| 路径 | 适用场景 | 机制 | 开销 |
|------|----------|------|------|
| 堆分配（heap） | defer 出现在循环中、或函数含大量 defer、或无法静态分析 | `deferproc` 在堆上分配 `_defer`，挂入 `g._defer`；函数返回时 `deferreturn` 弹出并 `jmpdefer` 调用 | 分配 + 链表 |
| 开放编码（open-coded） | 函数内 defer 数 ≤ 8 且不在循环 / 复杂控制流中 | 编译器直接把"保存参数 + 在 return 处插入调用"内联进函数体，不分配 `_defer` | 接近直接调用 |

- `deferreturn` 在每个 `ret` 指令前由编译器插入（开放编码路径），逐个执行；`jmpdefer` 用汇编 `jmp` 复用调用栈，避免每次 defer 多一层栈帧。
- 当开放编码不可用时（循环中的 defer、defer 数量过多等），自动回退到堆分配路径。

## Execution Order with return

`return X` 的完整过程（以命名返回值函数为例）：

1. 把 `X` 写入**命名返回值变量**（已零值初始化）；
2. 执行所有 `defer`（LIFO），defer 可读写命名返回值；
3. 真正返回命名返回值变量。

因此 **defer 能修改命名返回值**：

```go
func f() (n int) {
    defer func() { n++ }() // n: 0 -> 1
    return 5               // 写入 n=5，defer 再 +1 => 返回 6
}
```

匿名返回值的函数里，defer 看不到返回值变量，无法修改最终返回。

## Interaction with panic/recover

panic 触发时，runtime 沿 `g._defer` 链表逐个执行 defer（详见 panic/recover 机制）；若某 defer 中调用 `recover()` 成功，unwind 停止，函数象正常 return 一样退出。注意：**defer 中的函数会因本函数 panic 而被执行，但 `os.Exit` 等直接退出进程时 defer 不会执行**。

## Links

- [panic/recover 机制](/docs/CS/Go/Panic.md)
- [Go 语言总览（defer 语法）](/docs/CS/Go/Go.md?id=defer)
- [Issues：常见错误](/docs/CS/Go/Issues.md)

## References

1. [Go 1.14 Release Notes（open-coded defers）](https://go.dev/doc/go1.14)
1. [Go 语言设计与实现：defer](https://draveness.me/golang/docs/defer/)
1. [runtime/panic.go](https://github.com/golang/go/blob/master/src/runtime/panic.go)
