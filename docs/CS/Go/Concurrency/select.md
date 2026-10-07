## Introduction

Golang实现select时，定义了一个数据结构表示每个case语句(含defaut，default实际上是一种特殊的case)，select执行过程可以类比成一个函数，函数输入case数组，输出选中的case，然后程序流程转到选中的case块



源码包`src/runtime/select.go:scase`定义了表示case语句的数据结构：

```go
type scase struct {
	c    *hchan         // chan
	elem unsafe.Pointer // data element
}
```

scase.c为当前case语句所操作的channel指针，这也说明了一个case语句只能操作一个channel。
scase.kind表示该case的类型，分为读channel、写channel和default，三种类型分别由常量定义：

- caseRecv：case语句中尝试读取scase.c中的数据；
- caseSend：case语句中尝试向scase.c中写入数据；
- caseDefault： default语句

scase.elem表示缓冲区地址



源码包`src/runtime/select.go:selectgo()`定义了select选择case的函数：

```go
func selectgo(cas0 *scase, order0 *uint16, pc0 *uintptr, nsends, nrecvs int, block bool) (int, bool) 
	
```

- select语句中除default外，每个case操作一个channel，要么读要么写
- select语句中除default外，各case执行顺序是随机的
- select语句中如果没有default语句，则会阻塞等待任一case
- select语句中读操作要判断是否成功读取，关闭的channel也可以读取



## Usage (Common Patterns)

`select` 本身只负责「在多个通信操作间选一个就绪的」，但把它和 `time.After` / `context` / `done` channel 组合，就能表达超时、非阻塞、优雅退出等几乎所有并发控制套路。下面按场景列最常用写法。

### Timeout and Deadline

用 `time.After` 在 select 里塞一个「定时唤醒」的 case，避免长时间阻塞：

```go
select {
case v := <-ch:
    handle(v)
case <-time.After(2 * time.Second):
    // 2s 内没收到，走超时分支
}
```

更推荐 `context.WithTimeout`：超时事件能和上游取消信号统一成一个 `ctx.Done()`，且超时后 `ctx` 被 cancel、自动释放关联资源（见 [Context](/docs/CS/Go/Concurrency/Context.md)）：

```go
ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
defer cancel()
select {
case v := <-ch:
    handle(v)
case <-ctx.Done():
    // 超时或上游取消，统一处理
}
```

### Non-blocking Send/Receive (default Branch)

带 `default` 的 select 永不阻塞：若所有 case 都未就绪，立即执行 `default`。这是「尝试一次」语义，常用来实现轮询、健康探测、或避免慢接收方拖垮发送方：

```go
select {
case ch <- v:
    // 发送成功
default:
    // 缓冲区满或无人接收，立即放弃
}
```

注意：非阻塞与阻塞版本语义不同——阻塞版本会 `gopark` 等待对端（见 [Channel](/docs/CS/Go/Concurrency/Channel.md)），非阻塞版本必须显式处理 `default` 分支，否则「没发成」会被静默吞掉。

### Exit Notification (done channel)

长期运行的后台 goroutine 不能「硬杀」（Go 没有从外部终止 goroutine 的 API，见 [Goroutine](/docs/CS/Go/Concurrency/Goroutine.md) 的生命周期），只能靠「信号让它自己退出」。`done` channel 是经典做法：主 goroutine `close(done)` 广播，工作 goroutine 在 select 里持续监听：

```go
for {
    select {
    case <-done:
        return // 收到退出信号
    case job := <-jobs:
        process(job)
    }
}
```

`close(done)` 会让所有正在 `<-done` 的接收者**同时**收到零值——这是「一对多广播」最廉价的方式，不需要知道有多少监听者。更结构化的替代是用 `context` 取消（见 [Context](/docs/CS/Go/Concurrency/Context.md)），二者广播语义一致。

### Reflective select (Dynamic Number of Cases)

当 case 数量在编译期未知（如聚合任意多个 channel 的结果），用 `reflect.Select` 在运行时构造 case 列表：

```go
cases := make([]reflect.SelectCase, len(chans))
for i, ch := range chans {
    cases[i] = reflect.SelectCase{Dir: reflect.SelectRecv, Chan: reflect.ValueOf(ch)}
}
chosen, _, _ := reflect.Select(cases) // 返回就绪的 case 下标
```

代价是放弃编译期类型检查、性能也低于原生 `select`，只在「channel 数量动态」时才有必要。fan-in 聚合多个数据源是典型场景（见 [并发模式](/docs/CS/Go/Concurrency/Patterns.md)）。

### Two Often-Ignored Semantics

- **nil channel 在 select 中会被永久跳过**：把某个 case 的 channel 置为 `nil`，该分支就永远不被选中——这常被用来「动态禁用」某个分支（例如某路数据已处理完，把它置 nil 让 select 不再选中它）。
- **多 case 同时就绪时随机选**：Go 规范保证 `select` 在多个 case 就绪时**均匀随机**选择，而非按书写顺序优先级；这一随机性既是 `scase` 实现里的 `pollorder` 打乱（见上方 Introduction 的 runtime 细节），也是避免「某 case 饿死」的语义保证，不要依赖 case 的书写顺序。

## Links

- [Concurrency](/docs/CS/Go/Concurrency/Concurrency.md)
