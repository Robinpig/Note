## Introduction

1.7版本加入

Go 语言中的 Context 的主要作用还是在多个 Goroutine 或者模块之间同步取消信号或者截止日期，用于减少对资源的消耗和长时间占用，避免资源浪费，虽然传值也是它的功能之一，但是这个功能我们还是很少用到。
在真正使用传值的功能时我们也应该非常谨慎，不能将请求的所有参数都使用 Context 进行传递，这是一种非常差的设计，比较常见的使用场景是传递请求对应用户的认证令牌以及用于进行分布式追踪的请求 ID




一个任务会有很多个协程协作完成，一次 HTTP 请求也会触发很多个协程的启动，而这些协程有可能会启动更多的子协程，并且无法预知有多少层协程、每一层有多少个协程
Context 就是用来简化解决这些问题的，并且是并发安全的。Context 是一个接口，它具备手动、定时、超时发出取消信号、传值等功能，
主要用于控制多个协程之间的协作，尤其是取消操作。一旦取消指令下达，那么被 Context 跟踪的这些协程都会收到取消信号，就可以做清理和退出操作。

Context 接口只有四个方法
```go
type Context interface {
   Deadline() (deadline time.Time, ok bool)
   Done() <-chan struct{}
   Err() error
   Value(key interface{}) interface{}
}
```
1. Deadline 方法可以获取设置的截止时间，第一个返回值 deadline 是截止时间，到了这个时间点，Context 会自动发起取消请求，第二个返回值 ok 代表是否设置了截止时间。
2. Done 方法返回一个只读的 channel，类型为 struct{}。在协程中，如果该方法返回的 chan 可以读取，则意味着 Context 已经发起了取消信号。通过 Done 方法收到这个信号后，就可以做清理操作，然后退出协程，释放资源。
3. Err 方法返回取消的错误原因，即因为什么原因 Context 被取消。
4. Value 方法获取该 Context 上绑定的值，是一个键值对，所以要通过一个 key 才可以获取对应的值。

Context 接口的四个方法中最常用的就是 Done 方法，它返回一个只读的 channel，用于接收取消信号。当 Context 取消的时候，会关闭这个只读 channel，也就等于发出了取消信号

我们不需要自己实现 Context 接口，Go 语言提供了函数可以帮助我们生成不同的 Context，通过这些函数可以生成一颗 Context 树，这样 Context 才可以关联起来
父 Context 发出取消信号的时候，子 Context 也会发出，这样就可以控制不同层级的协程退出。
从使用功能上分，有四种实现好的 Context。
1. 空 Context：不可取消，没有截止时间，主要用于 Context 树的根节点。
2. 可取消的 Context：用于发出取消信号，当取消的时候，它的子 Context 也会取消。
3. 可定时取消的 Context：多了一个定时的功能。
4. 值 Context：用于存储一个 key-value 键值对。

从下图 Context 的衍生树可以看到，最顶部的是空 Context，它作为整棵 Context 树的根节点，在 Go 语言中，可以通过 context.Background() 获取一个根节点 Context。
有了根节点 Context 后，这颗 Context 树要怎么生成呢？需要使用 Go 语言提供的四个函数。
1. WithCancel(parent Context)：生成一个可取消的 Context。
2. WithDeadline(parent Context, d time.Time)：生成一个可定时取消的 Context，参数 d 为定时取消的具体时间。
3. WithTimeout(parent Context, timeout time.Duration)：生成一个可超时取消的 Context，参数 timeout 用于设置多久后取消

以上四个生成 Context 的函数中，前三个都属于可取消的 Context，它们是一类函数，最后一个是值 Context，用于存储一个 key-value 键值对。

Context 不仅可以取消，还可以传值，通过这个能力，可以把 Context 存储的值供其他协程使用

Context 是一种非常好的工具，使用它可以很方便地控制取消多个协程。在 Go 语言标准库中也使用了它们，比如 net/http 中使用 Context 取消网络的请求。
要更好地使用 Context，有一些使用原则需要尽可能地遵守。
1. Context 不要放在结构体中，要以参数的方式传递。
2. Context 作为函数的参数时，要放在第一位，也就是第一个参数。
3. 要使用 context.Background 函数生成根节点的 Context，也就是最顶层的 Context。
4. Context 传值要传递必须的值，而且要尽可能地少，不要什么都传。
5. Context 多协程安全，可以在多个协程中放心使用。


以上原则是规范类的，Go 语言的编译器并不会做这些检查，要靠自己遵守

要想跟踪一个用户的请求，必须有一个唯一的 ID 来标识这次请求调用了哪些函数、执行了哪些代码，然后通过这个唯一的 ID 把日志信息串联起来。这样就形成了一个日志轨迹，也就实现了用户的跟踪，于是思路就有了。
1. 在用户请求的入口点生成 TraceID。
2. 通过 context.WithValue 保存 TraceID。
3. 然后这个保存着 TraceID 的 Context 就可以作为参数在各个协程或者函数间传递。
4. 在需要记录日志的地方，通过 Context 的 Value 方法获取保存的 TraceID，然后把它和其他日志信息记录下来。
5. 这样具备同样 TraceID 的日志就可以被串联起来，达到日志跟踪的目的


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

- []()
