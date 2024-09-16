## Introduction

1.7版本加入

Go 语言中的 Context 的主要作用还是在多个 Goroutine 或者模块之间同步取消信号或者截止日期，用于减少对资源的消耗和长时间占用，避免资源浪费，虽然传值也是它的功能之一，但是这个功能我们还是很少用到。
在真正使用传值的功能时我们也应该非常谨慎，不能将请求的所有参数都使用 Context 进行传递，这是一种非常差的设计，比较常见的使用场景是传递请求对应用户的认证令牌以及用于进行分布式追踪的请求 ID

在 context 包中，最常使用其实还是 context.Background 和 context.TODO 两个方法，这两个方法最终都会返回一个预先初始化好的私有变量 background 和 todo：

```go
func Background() Context {
    return background
}

func TODO() Context {
    return todo
}
```




这两个变量是在包初始化时就被创建好的，它们都是通过 new(emptyCtx) 表达式初始化的指向私有结构体 emptyCtx 的指针，这是包中最简单也是最常用的类型

```go
type emptyCtx int

func (*emptyCtx) Deadline() (deadline time.Time, ok bool) {
    return
}
```
emptyCtx对 Context 接口方法的实现也都非常简单，无论何时调用都会返回 nil 或者空值，并没有任何特殊的功能，Background 和 TODO 方法在某种层面上看其实也只是互为别名，两者没有太大的差别，不过 context.Background() 是上下文中最顶层的默认值，所有其他的上下文都应该从 context.Background() 演化出来





## Links


