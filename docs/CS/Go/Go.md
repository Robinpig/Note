## Introduction

Go是一种新的语言，一种并发的、带垃圾回收的、快速编译的语言。它具有以下特点：

- 类型安全和内存安全
- 快速编译 Go为软件构造提供了一种模型，它使依赖分析更加容易，且避免了大部分C风格include文件与库的开头
- Go是静态类型的语言，它的类型系统没有层级。因此用户不需要在定义类型之间的关系上花费时间，这样感觉起来比典型的面向对象语言更轻量级
- Go完全是垃圾回收型的语言，并为并发执行与通信提供了基本的支持

代码规范
>[Google style go](https://google.github.io/styleguide/go)
>[Go Wiki: Go Code Review Comments - The Go Programming Language](https://go.dev/wiki/CodeReviewComments)

## Config

>  [Download and install Go](https://golang.google.cn/doc/install)

Go使用[常见错误](/docs/CS/Go/Issues.md)

Go mod是package和其dependencies的集合 是构建 版本控制和管理的单元
 package是同一路径导入文件的集合 通常package名和目录名相同

go.sum列出mod下全部的依赖项(直接和间接) 由工具链管理 不需要手动修改



go get set proxy


```shell
//go version >=1.13 
go env -w GO111MODULE=on
go env -w GOPROXY=https://goproxy.cn,direct

//get godoc
go get -v  golang.org/x/tools/cmd/godoc
godoc -http=:6060
```


要让一个 Go 语言程序成功运行起来，只需要 package main 和 main 函数这两个核心部分， package main 代表的是一个可运行的应用程序，而 main 函数则是这个应用程序的主入口



dependency tool

- go get
- godep
- vender
- gb

Traits

- Garbage Collection




goroutine

channel

duck type

composition


### Build

go1.4之后实现了自举 需要一个1.4之后的go版本来执行

从github clone的go 源码目录下没有VERSION文件 报错如下
```
go tool dist: FAILED: not a Git repo; must put a VERSION file in $GOROOT
```
解决方法: 从官网下载最新的golang源代码进行安装


```shell
git clone https://github.com/golang/go.git
cd go/src
# wait for ALL TESTS PASSED
./all.bash

# 修改源码后可使用make.bash编译
./make.bash
```




add path

[Delve](https://www.github.com/go-delve/delve) is a debugger for the Go programming language.
使用如下命令install
`go install github.com/go-delve/delve/cmd/dlv@latest`

也可以在vscode中cmd+P Go:Install Update Tool安装工具链



### Upgrade

 删除旧版本 安装新版本



## Compile

Go 语言是一门需要编译才能运行的编程语言，也就是说代码在运行之前需要通过编译器生成二进制机器码，包含二进制机器码的文件才能在目标机器上运行

[Go 语言编译过程](/docs/CS/Go/compile.md)



## Basic


Go 自带的数据结构

### range



```go
package main

import "fmt"

func main() {
  s := []string{"a", "b", "c"}

  // 只有一个返回值：则第一个参数是index
  for v := range s {
    fmt.Println(v)
  }

  // 两个返回值
  for i, v := range s {
    fmt.Println(i, v)
  }
}
```

遍历 `map` 为随机序输出，`slice` 为索引序输出



range v 是值拷贝，且只会声明初始化一次

```go
package main

import "fmt"

func main() {
  ParseStudent()
}

type student struct {
  Name string
  Age  int
}

func ParseStudent() {
  m := make(map[string]*student)
  stus := []student{
    {Name: "zhang", Age: 22},
    {Name: "li", Age: 23},
    {Name: "wang", Age: 24},
  }
  for _, stu := range stus {
    // 都指向了同一个stu的内存指针，为什么？
    // 因为 for range 中的 v 只会声明初始化一次
    // 不会每次循环都初始化，最后赋值会覆盖前面的

    fmt.Printf("%p\n", &stu)

    newStu := stu
    m[stu.Name] = &newStu
  }

  for i, v := range m {
    fmt.Println(i, v)
  }
}
```











### 指针
在 Go 语言中，指针对应的是变量在内存中的存储位置，也就说指针的值就是变量的内存地址。通过 & 可以获取一个变量的地址，也就是指针。
常量

常量的定义和变量类似，只不过它的关键字是 const。
在 Go 语言中，只允许布尔型、字符串、数字类型这些基础类型作为常量
#### iota
iota 是一个常量生成器，它可以用来初始化相似规则的常量，避免重复的初始化
iota 的初始值是 0，它的能力就是在每一个有常量声明的行后面 +1

iota代表了const声明块的行索引（下标从0开始）
除此之外，const声明还有个特点，即第一个常量必须指定一个表达式，后续的常量如果没有表达式，则继承上面的表达式

const块中每一行在GO中使用spec数据结构描述，spec声明如下：

```go
// A ValueSpec node represents a constant or variable declaration
// (ConstSpec or VarSpec production).
//
ValueSpec struct {
    Doc     *CommentGroup // associated documentation; or nil
    Names   []*Ident      // value names (len(Names) > 0)
    Type    Expr          // value type; or nil
    Values  []Expr        // initial values; or nil
    Comment *CommentGroup // line comments; or nil
}
```
ValueSpec.Names这个切片中保存了一行中定义的常量，如果一行定义N个常量，那么ValueSpec.Names切片长度即为N。
const块实际上是spec类型的切片，用于表示const中的多行。

译期间构造常量时的伪算法如下
```
for iota, spec := range ValueSpecs {
        for i, name := range spec.Names {
            obj := NewConst(name, iota...) //此处将iota传入，用于构造常量
            ...
        }
    }
```








### Flow Control

和其他编程语言不同，在 Go 语言的 if 语句中，可以有一个简单的表达式语句，并将该语句和条件语句使用分号 ; 分开
通过 if 简单语句声明的变量，只能在整个 if……else if……else 条件语句中使用

switch 语句同样也可以用一个简单的语句来做初始化，同样也是用分号 ; 分隔。每一个 case 就是一个分支，分支条件为 true 该分支才会执行，而且 case 分支后的条件表达式也不用小括号 () 包裹
Go 语言的 switch 在默认情况下，case 最后自带 break。
提供了 fallthrough 关键字允许执行下一个紧跟的 case
switch 后的表达式也没有太多限制，是一个合法的表达式即可，也不用一定要求是常量或者整数

在 Go 语言中没有 while 循环，但是可以通过 for 达到 while 的效果





### defer

延迟函数在绝大数情况下能被执行 除非显式调用Exit或者Fatal

延迟函数的调用执行顺序是LIFO
defer 有一个调用栈，越早定义越靠近栈的底部，越晚定义越靠近栈的顶部，在执行这些 defer 语句的时候，会先从栈顶弹出一个 defer 然后执行它

延迟函数造成的panic不会影响其它延迟函数的执行

延迟函数需要注意作用域

如下代码里time.Slice()并不在defer的作用域里

```go
func main() {

	now := time.Now

	defer fmt.Printf("duration : %s\n", time.Since(now()))

	fmt.Println("sleep for 50ms")

	time.Sleep(50 * time.Millisecond)
}
```


### init

init函数在main函数前的所有init函数 并按照其声明顺序执行

不同文件里的init函数按照加载文件顺序执行








### error

在 error、panic 这两种错误机制中，Go 语言更提倡 error 这种轻量错误，而不是 panic



panic 有三种诞生方式：

- 程序猿主动：调用 `panic()`函数；
- 编译器的隐藏代码：比如除零场景；
- 内核发送给进程信号：比如非法地址访问 ；

## Generic


## goroutine



Go不允许开发者控制goroutine的内存分配量和调度

Go使用工作共享和工作窃取来管理goroutine


Go 语言中没有线程的概念，只有协程，也称为 goroutine。相比线程来说，协程更加轻量，一个程序可以随意启动成千上万个 goroutine。
goroutine 被 Go runtime 所调度，这一点和线程不一样。也就是说，Go 语言的并发是由 Go 自己所调度的，自己决定同时执行多少个 goroutine，什么时候执行哪几个。这些对于我们开发者来说完全透明，只需要在编码的时候告诉 Go 语言要启动几个 goroutine，至于如何调度执行，我们不用关心

GMP模型

系统线程不会销毁
避免线程阻塞

锁同步操作阻塞
系统调用阻塞
网络调用阻塞
sleep主动阻塞

监控线程sysmon




```go
package main

import (
    "fmt"
    "time"
)

var sum = 0

func main() {

    //开启100个协程让sum+10
    for i := 0; i < 1000; i++ {
        go add(10)
    }

    //防止提前退出
    time.Sleep(2 * time.Second)
    fmt.Println("和为:", sum)
}

func add(i int) {
    sum += i
}
```

使用 go build、go run、go test 这些 Go 语言工具链提供的命令时，添加 -race 标识可以帮你检查 Go 语言代码是否存在资源竞争


mutex
var( sum int mutex sync.Mutex ) funcadd(i int) { mutex.Lock() sum += i mutex.Unlock() }
Mutex 的 Lock 和 Unlock 方法总是成对出现，而且要确保 Lock 获得锁后，一定执行 UnLock 释放锁，所以在函数或者方法中会采用 defer 语句释放锁

sync.Cond
在 Go 语言中，sync.WaitGroup 用于最终完成的场景，关键点在于一定要等待所有协程都执行完毕。
而 sync.Cond 可以用于发号施令，一声令下所有协程都可以开始执行，关键点在于协程开始的时候是等待的，要等待 sync.Cond 唤醒才能执行。
sync.Cond 从字面意思看是条件变量，它具有阻塞协程和唤醒协程的功能，所以可以在满足一定条件的情况下唤醒协程，但条件变量只是它的一种使用场景

sync.Cond 有三个方法，它们分别是：
1. Wait，阻塞当前协程，直到被其他协程调用 Broadcast 或者 Signal 方法唤醒，使用的时候需要加锁，使用 sync.Cond 中的锁即可，也就是 L 字段。
2. Signal，唤醒一个等待时间最长的协程。
3. Broadcast，唤醒所有等待的协程。
   注意：在调用 Signal 或者 Broadcast 之前，要确保目标协程处于 Wait 阻塞状态，不然会出现死锁问题。

sync.Cond 和 Java 的等待唤醒机制很像，它的三个方法 Wait、Signal、Broadcast 就分别对应 Java 中的 wait、notify、notifyAll




## Frameworks

ORM
- [gorm](/docs/CS/Framework/gorm.md)

## Links
- [C](/docs/CS/C/C.md)


## References

1. [Go指南](https://tour.go-zh.org/welcome/1)
1. [Goproxy.cn](https://goproxy.cn/)
1. [Go入门指南](https://geekdaxue.co/read/Go-Getting-Started-Guide/README.md)
1. [Golang 学习笔记](https://geekdaxue.co/books/lengyuezuixue@vdhg2e)
1. [Go语言圣经(中文版)](https://gopl-zh.github.io/)
1. [Go语言设计与实现](https://draveness.me/golang/)
1. [Go语言高级编程](http://docs.studygolang.com/advanced-go-programming-book/)
1. [Go专家编程](https://docs.kilvn.com/GoExpertProgramming/)
1. [Go Web编程](https://docs.kilvn.com/build-web-application-with-golang/zh/)
1. [深度探索Go语言](https://book-go-runtime.netlify.app/#/)
1. [Go程序设计](https://www.yuque.com/qyuhen/go)
1. [LeetCode Cookbook](https://books.halfrost.com/leetcode/)
1. [Mastering Go Second Edition](https://www.kancloud.cn/cloud001/golang/1601804)
1. [go语言核心36讲](https://jums.gitbook.io/36-lectures-on-golang)