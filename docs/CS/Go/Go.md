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



[compile](/docs/CS/Go/compile.md)

除了 Go 语言实现的 gc 外，Go 官方还维护了一个基于 gcc 实现的 Go 编译器 gccgo。与 gc 相比，gccgo 编译速度较慢，但支持更强大的优化，
因此由 gccgo 构建的 CPU 密集型(CPU-bound)程序通常会运行得更快。此外 gccgo 比 gc 支持更多的操作系统，如果交叉编译gc不支持的操作系统，可以考虑使用gccgo

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



## Basic

### Data Type

#### Basic Type
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

#### strings

Go语言中字符串的底层结构中也包含了字符数组，该字符数组是完整的字符串内容，它不同于C语言，字符数组中没有标记字符串结束的标记
为了记录底层字符数组的大小，Go语言使用了额外的一个长度字段来记录该字符数组的大小，字符数组的大小也就是字符串的长度
其中关于string的描述位于src/builtin/builtin.go

- string是8比特字节的集合，通常但并不一定是UTF-8编码的文本。
- string可以为空（长度为0），但不会是nil；
- string对象不可以修改。

```go
// string is the set of all strings of 8-bit bytes, conventionally but not
// necessarily representing UTF-8-encoded text. A string may be empty, but
// not nil. Values of string type are immutable.
type string string
```


src/runtime/string.go:stringStruct定义了string的数据结构：

```go
type stringStruct struct {
    str unsafe.Pointer
    len int
}
```

string数据结构跟切片有些类似，只不过切片还有一个表示容量的成员，事实上string和切片，准确的说是byte切片经常发生转换

byte切片转换成string的场景很多，为了性能上的考虑，有时候只是临时需要字符串的场景下，byte切片转换成string时并不会拷贝内存，而是直接返回一个string，这个string的指针(string.str)指向切片的内存

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

string和[]byte都可以表示字符串，但因数据结构不同，其衍生出来的方法也不同，要跟据实际应用场景来选择。

string 擅长的场景：

- 需要字符串比较的场景；
- 不需要nil字符串的场景；

[]byte擅长的场景：

- 修改字符串的场景，尤其是修改粒度为1个字节；
- 函数返回值，需要用nil表示含义的场景；
- 需要切片操作的场景；

虽然看起来string适用的场景不如[]byte多，但因为string直观，在实际应用中还是大量存在，在偏底层的实现中[]byte使用更多


当我们编译时候开启了禁止内联，禁止优化时候，可以发现 len(str) == 0 和 str == "" 的实现是不同的，前者的执行效率是不如后者的
在默认情况下，Go编译器是开启了优化选项的，len(str) == 0 会优化成跟 str == "" 的实现一样




Go语言中数组、字符串和切片三者是密切相关的数据结构。

这三种数据类型，在底层原始数据有着相同的内存结构，在上层，因为语法的限制而有着不同的行为表现。

- 首先，Go语言的数组是一种值类型，虽然数组的元素可以被修改，但是数组本身的赋值和函数传参都是以整体复制的方式处理的。
- Go语言字符串底层数据也是对应的字节数组，但是字符串的只读属性禁止了在程序中对底层字节数组的元素的修改。字符串赋值只是复制了数据地址和对应的长度，而不会导致底层数据的复制。
- 切片的行为更为灵活，切片的结构和字符串结构类似，但是解除了只读限制。切片的底层数据虽然也是对应数据类型的数组，但是每个切片还有独立的长度和容量信息，切片赋值和函数传参数时也是将切片头信息部分按传值方式处理。因为切片头含有底层数据的指针，所以它的赋值也不会导致底层数据的复制。

> [!TIP]
>
>  其实Go语言的赋值和函数传参规则很简单，除了闭包函数以引用的方式对外部变量访问之外，其它赋值和函数传参数都是以传值的方式处理

#### default value

零值其实就是一个变量的默认值，在 Go 语言中，如果我们声明了一个变量，但是没有对其进行初始化，那么 Go 语言会自动初始化其值为对应类型的零值。比如数字类的零值是 0，布尔型的零值是 false，字符串的零值是  空字符串等

#### Reference Type

引用类型(reference type)特指slice、map、channel这三种预定义类型

类型转换

Go 语言是强类型的语言，也就是说不同类型的变量是无法相互使用和计算的，这也是为了保证Go 程序的健壮性，所以不同类型的变量在进行赋值或者计算前，需要先进行类型转换

通过包 strconv 的 Itoa 函数可以把一个 int 类型转为 string，Atoi 函数则用来把 string 转为 int。
同理对于浮点数、布尔型，Go 语言提供了 strconv.ParseFloat、strconv.ParseBool、strconv.FormatFloat 和 strconv.FormatBool 进行互转

对于数字类型之间，可以通过强制转换的方式
这种使用方式比简单，采用类型（要转换的变量）格式即可。采用强制转换的方式转换数字类型，可能会丢失一些精度，比如浮点型转为整型时，小数点部分会全部丢失



#### struct

结构体定义

```go
type structName struct{
    fieldName typeName
    ....
    ....
}
```

#### Interface

在接口的实现中，值类型接收者和指针类型接收者不一样 以指针类型接收者实现接口的时候，只有对应的指针类型才被认为实现了该接口
可以这样解读：

- 当值类型作为接收者时，person 类型和*person类型都实现了该接口。
- 当指针类型作为接收者时，只有*person类型实现了该接口。

在 Go 语言中没有继承的概念，所以结构、接口之间也没有父子关系，Go 语言提倡的是组合，利用组合达到代码复用的目的，这也更灵活

直接把结构体类型放进来，就是组合，不需要字段名。组合后，被组合的 address 称为内部类型，person 称为外部类型。修改了 person 结构体后，声明和使用也需要一起修改
类型组合后，外部类型不仅可以使用内部类型的字段，也可以使用内部类型的方法，就像使用自己的方法一样。如果外部类型定义了和内部类型同样的方法，那么外部类型的会覆盖内部类型，这就是方法的覆写
方法覆写不会影响内部类型的方法实现。

有了接口和实现接口的类型，就会有类型断言。类型断言用来判断一个接口的值是否是实现该接口的某个具体类型。



#### function



Go 的函数可以返回多个值



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