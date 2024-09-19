## Introduction

Go是一种新的语言，一种并发的、带垃圾回收的、快速编译的语言。它具有以下特点：

- 类型安全和内存安全
- 快速编译 Go为软件构造提供了一种模型，它使依赖分析更加容易，且避免了大部分C风格include文件与库的开头。
- Go是静态类型的语言，它的类型系统没有层级。因此用户不需要在定义类型之间的关系上花费时间，这样感觉起来比典型的面向对象语言更轻量级。
- Go完全是垃圾回收型的语言，并为并发执行与通信提供了基本的支持

代码规范
>[Google style go](https://google.github.io/styleguide/go)
>[Go Wiki: Go Code Review Comments - The Go Programming Language](https://go.dev/wiki/CodeReviewComments)

## 配置
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

两个重要的环境变量没有设置，它们分别是 GOPATH 和 GOBIN。
- GOPATH：代表 Go 语言项目的工作目录，在 Go Module 模式之前非常重要，现在基本上用来存放使用 go get 命令获取的项目。
- GOBIN：代表 Go 编译生成的程序的安装目录，比如通过 go install 命令，会把生成的 Go 程序安装到 GOBIN 目录下，以供你在终端使用。

export GOPATH=/Users/flysnow/go export GOBIN=$GOPATH/bin

Go 语言开发工具包的另一强大功能就是可以跨平台编译

Go 语言通过两个环境变量来控制跨平台编译，它们分别是 GOOS 和 GOARCH 。
- GOOS：代表要编译的目标操作系统，常见的有 Linux、Windows、Darwin 等。
- GOARCH：代表要编译的目标处理器架构，常见的有 386、AMD64、ARM64 等。
这样通过组合不同的 GOOS 和 GOARCH，就可以编译出不同的可执行程序。比如我现在的操作系统是 macOS AMD64 的，我想编译出 Linux AMD64 的可执行程序，只需要执行 go build 命令即可，如以下代码所示：

```shell
GOOS=linux GOARCH=amd64 go build ./ch01/main.go
```

dependency tool
- go get
- godep
- vender
- gb

Traits

- Garbage Collection



[compile](/docs/CS/Go/compile.md)


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
```
add path

[Delve]（https://www.github.com/go-delve/delve) is a debugger for the Go programming language.
使用如下命令install
`go install github.com/go-delve/delve/cmd/dlv@latest`

也可以在vscode中cmd+P Go:Install Update Tool安装工具链

## Basic

### Basic Type
任何一门语言都有对应的基础类型， Go 语言也有自己丰富的基础类型，常用的有：整型、浮点数、布尔型和字符串


在 Go 语言中，整型分为：
- 有符号整型：如 int、int8、int16、int32 和 int64。
- 无符号整型：如 uint、uint8、uint16、uint32 和 uint64。

除了有用位（bit）大小表示的整型外，还有 int 和 uint 这两个没有具体 bit 大小的整型，它们的大小可能是 32bit，也可能是 64bit，和硬件设备 CPU 有关
在整型中，如果能确定 int 的 bit 就选择比较明确的 int 类型，因为这会让你的程序具备很好的移植性。
在 Go 语言中，还有一种字节类型 byte，它其实等价于 uint8 类型，可以理解为 uint8 类型的别名，用于定义一个字节，所以字节 byte 类型也属于整型

浮点数
浮点数就代表现实中的小数。Go 语言提供了两种精度的浮点数，分别是 float32 和 float64。项目中最常用的是 float64，因为它的精度高，浮点计算的结果相比 float32 误差会更小

布尔型
一个布尔型的值只有两种：true 和 false Go 语言中的布尔型使用关键字 bool 定义

### strings


Go 语言中的字符串可以表示为任意的数据
在 Go 语言中，可以通过操作符 + 把字符串连接起来，得到一个新的字符串
字符串也可以通过 += 运算符操作

字符串 string 也是一个不可变的字节序列，所以可以直接转为字节切片 []byte

utf8.RuneCountInString 函数。运行下面的代码，可以看到打印结果是 9，也就是 9 个 unicode（utf8）字符，和我们看到的字符的个数一致。

fmt.Println(utf8.RuneCountInString(s))

而使用 for range 对字符串进行循环时，也恰好是按照 unicode 字符进行循环的，所以对于字符串 s 来说，循环了 9 次

在汇编语言中，无论是经典的 for 循环还是 for-range 循环都会使用 JMP 等命令跳回循环体的开始位置复用代码。
从不同循环具有相同的汇编代码可以猜到，使用 for-range 的控制结构最终也会被 Go 语言编译器转换成普通的 for 循环


字符串常量在词法解析阶段最终会被标记成StringLit类型的Token并被传递到编译的下一个阶段。在语法分析阶段，采取递归下降的方式读取Uft-8字符，单撇号或双引号是字符串的标识。分析的逻辑位于syntax/scanner.go文件中

果在代码中识别到单撇号，则调用rawString函数；如果识别到双引号，则调用stdString函数，两者的处理略有不同。
对于单撇号的处理比较简单：一直循环向后读取，直到寻找到配对的单撇号， 

双引号调用stdString函数，如果出现另一个双引号则直接退出；如果出现了\\，则对后面的字符进行转义

string（s.stopLit（））将解析到的字节转换为字符串，这种转换会在字符串左、右两边加上双引号，因此"hello"会被解析为""hello""。在抽象语法树阶段，无论是import语句中包的路径、结构体中的字段标签还是字符串常量，都会调用strconv.Unquote（s）去掉字符串两边的引号等干扰，还原其本来的面目

字符常量存储于静态存储区，其内容不可以被改变，声明时有单撇号和双引号两种方法。字符常量的拼接发生在编译时，而字符串变量的拼接发生在运行时

运行时字符串的拼接并不是简单地将一个字符串合并到另一个字符串中，而是找到一个更大的空间，并通过内存复制的形式将字符串复制到其中
无论使用concatstring{2，3，4，5}函数中的哪一个，最终都会调用runtime.concatstrings函数
concatstrings函数会先对传入的切片参数进行遍历，过滤空字符串并计算拼接后字符串的长度
拼接的过程位于rawstringtmp函数中，当拼接后的字符串小于32字节时，会有一个临时的缓存供其使用。当拼接后的字符串大于32字节时，堆区会开辟一个足够大的内存空间，并将多个字符串存入其中，期间会涉及内存的复制（copy）


### default value

零值其实就是一个变量的默认值，在 Go 语言中，如果我们声明了一个变量，但是没有对其进行初始化，那么 Go 语言会自动初始化其值为对应类型的零值。比如数字类的零值是 0，布尔型的零值是 false，字符串的零值是  空字符串等

### 指针
在 Go 语言中，指针对应的是变量在内存中的存储位置，也就说指针的值就是变量的内存地址。通过 & 可以获取一个变量的地址，也就是指针。
常量

常量的定义和变量类似，只不过它的关键字是 const。
在 Go 语言中，只允许布尔型、字符串、数字类型这些基础类型作为常量
iota
iota 是一个常量生成器，它可以用来初始化相似规则的常量，避免重复的初始化
iota 的初始值是 0，它的能力就是在每一个有常量声明的行后面 +1

### Reference Type

引用类型(reference type)特指slice、map、channel这三种预定义类型

类型转换

Go 语言是强类型的语言，也就是说不同类型的变量是无法相互使用和计算的，这也是为了保证Go 程序的健壮性，所以不同类型的变量在进行赋值或者计算前，需要先进行类型转换

通过包 strconv 的 Itoa 函数可以把一个 int 类型转为 string，Atoi 函数则用来把 string 转为 int。
同理对于浮点数、布尔型，Go 语言提供了 strconv.ParseFloat、strconv.ParseBool、strconv.FormatFloat 和 strconv.FormatBool 进行互转

对于数字类型之间，可以通过强制转换的方式
这种使用方式比简单，采用类型（要转换的变量）格式即可。采用强制转换的方式转换数字类型，可能会丢失一些精度，比如浮点型转为整型时，小数点部分会全部丢失




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





### struct
结构体定义
```go
type structName struct{
    fieldName typeName
    ....
    ....
}
```

### Interface

在接口的实现中，值类型接收者和指针类型接收者不一样 以指针类型接收者实现接口的时候，只有对应的指针类型才被认为实现了该接口
可以这样解读：
- 当值类型作为接收者时，person 类型和*person类型都实现了该接口。
- 当指针类型作为接收者时，只有*person类型实现了该接口。

在 Go 语言中没有继承的概念，所以结构、接口之间也没有父子关系，Go 语言提倡的是组合，利用组合达到代码复用的目的，这也更灵活

直接把结构体类型放进来，就是组合，不需要字段名。组合后，被组合的 address 称为内部类型，person 称为外部类型。修改了 person 结构体后，声明和使用也需要一起修改
类型组合后，外部类型不仅可以使用内部类型的字段，也可以使用内部类型的方法，就像使用自己的方法一样。如果外部类型定义了和内部类型同样的方法，那么外部类型的会覆盖内部类型，这就是方法的覆写
方法覆写不会影响内部类型的方法实现。

有了接口和实现接口的类型，就会有类型断言。类型断言用来判断一个接口的值是否是实现该接口的某个具体类型。


### error

在 error、panic 这两种错误机制中，Go 语言更提倡 error 这种轻量错误，而不是 panic

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




## Context

一个任务会有很多个协程协作完成，一次 HTTP 请求也会触发很多个协程的启动，而这些协程有可能会启动更多的子协程，并且无法预知有多少层协程、每一层有多少个协程
Context 就是用来简化解决这些问题的，并且是并发安全的。Context 是一个接口，它具备手动、定时、超时发出取消信号、传值等功能，主要用于控制多个协程之间的协作，尤其是取消操作。一旦取消指令下达，那么被 Context 跟踪的这些协程都会收到取消信号，就可以做清理和退出操作。
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


## References

1. [Go指南](https://tour.go-zh.org/welcome/1)
1. [Goproxy.cn](https://goproxy.cn/)
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