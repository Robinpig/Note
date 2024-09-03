## Introduction


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
● GOPATH：代表 Go 语言项目的工作目录，在 Go Module 模式之前非常重要，现在基本上用来存放使用 go get 命令获取的项目。
● GOBIN：代表 Go 编译生成的程序的安装目录，比如通过 go install 命令，会把生成的 Go 程序安装到 GOBIN 目录下，以供你在终端使用。

export GOPATH=/Users/flysnow/go export GOBIN=$GOPATH/bin

Go 语言开发工具包的另一强大功能就是可以跨平台编译

Go 语言通过两个环境变量来控制跨平台编译，它们分别是 GOOS 和 GOARCH 。
● GOOS：代表要编译的目标操作系统，常见的有 Linux、Windows、Darwin 等。
● GOARCH：代表要编译的目标处理器架构，常见的有 386、AMD64、ARM64 等。
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



[compile](/docs/CS/Go/Basic/compile.md)


goroutine

channel

duck type

composition

## Basic

### Type
任何一门语言都有对应的基础类型， Go 语言也有自己丰富的基础类型，常用的有：整型、浮点数、布尔型和字符串


在 Go 语言中，整型分为：
● 有符号整型：如 int、int8、int16、int32 和 int64。
● 无符号整型：如 uint、uint8、uint16、uint32 和 uint64。

除了有用“位”（bit）大小表示的整型外，还有 int 和 uint 这两个没有具体 bit 大小的整型，它们的大小可能是 32bit，也可能是 64bit，和硬件设备 CPU 有关
在整型中，如果能确定 int 的 bit 就选择比较明确的 int 类型，因为这会让你的程序具备很好的移植性。
在 Go 语言中，还有一种字节类型 byte，它其实等价于 uint8 类型，可以理解为 uint8 类型的别名，用于定义一个字节，所以字节 byte 类型也属于整型

浮点数
浮点数就代表现实中的小数。Go 语言提供了两种精度的浮点数，分别是 float32 和 float64。项目中最常用的是 float64，因为它的精度高，浮点计算的结果相比 float32 误差会更小
布尔型
一个布尔型的值只有两种：true 和 false Go 语言中的布尔型使用关键字 bool 定义

字符串
Go 语言中的字符串可以表示为任意的数据
在 Go 语言中，可以通过操作符 + 把字符串连接起来，得到一个新的字符串
字符串也可以通过 += 运算符操作

字符串 string 也是一个不可变的字节序列，所以可以直接转为字节切片 []byte

utf8.RuneCountInString 函数。运行下面的代码，可以看到打印结果是 9，也就是 9 个 unicode（utf8）字符，和我们看到的字符的个数一致。

fmt.Println(utf8.RuneCountInString(s))

而使用 for range 对字符串进行循环时，也恰好是按照 unicode 字符进行循环的，所以对于字符串 s 来说，循环了 9 次

零值其实就是一个变量的默认值，在 Go 语言中，如果我们声明了一个变量，但是没有对其进行初始化，那么 Go 语言会自动初始化其值为对应类型的零值。比如数字类的零值是 0，布尔型的零值是 false，字符串的零值是 “” 空字符串等

指针
在 Go 语言中，指针对应的是变量在内存中的存储位置，也就说指针的值就是变量的内存地址。通过 & 可以获取一个变量的地址，也就是指针。
常量


常量的定义和变量类似，只不过它的关键字是 const。
在 Go 语言中，只允许布尔型、字符串、数字类型这些基础类型作为常量
iota
iota 是一个常量生成器，它可以用来初始化相似规则的常量，避免重复的初始化
iota 的初始值是 0，它的能力就是在每一个有常量声明的行后面 +1



类型转换

Go 语言是强类型的语言，也就是说不同类型的变量是无法相互使用和计算的，这也是为了保证Go 程序的健壮性，所以不同类型的变量在进行赋值或者计算前，需要先进行类型转换

通过包 strconv 的 Itoa 函数可以把一个 int 类型转为 string，Atoi 函数则用来把 string 转为 int。
同理对于浮点数、布尔型，Go 语言提供了 strconv.ParseFloat、strconv.ParseBool、strconv.FormatFloat 和 strconv.FormatBool 进行互转

对于数字类型之间，可以通过强制转换的方式
这种使用方式比简单，采用“类型（要转换的变量）”格式即可。采用强制转换的方式转换数字类型，可能会丢失一些精度，比如浮点型转为整型时，小数点部分会全部丢失


#### array

array

```go
var array[2] string
```

长度也是数组类型的一部分
所有元素都被初始化的数组定义时可以省略数组长度

使用传统的 for 循环遍历数组，输出对应的索引和对应的值，这种方式很烦琐，一般不使用，大部分情况下，我们使用的是 for range 这种 Go 语言的新型循环

for i,v:=range array{

    fmt.Printf("数组索引:%d,对应值:%s\n", i, v)

}


数组固定length slice可以扩容
define type and length
shallow copy 
pointer array

slice 24Byte

dynamic array

Length <= Capacity

|         |        |          |
| ------- | ------ | -------- |
| Pointer | Length | Capacity |

```go
slice := make ( []int,3,5)
//length = j-i = 1 capacity = k-i = 2
newSlice := slice[2:3:4]

// capacity<=1000 100% >1000 25%
append()
```

这种方式和传统 for 循环的结果是一样的。对于数组，range 表达式返回两个结果：
1. 第一个是数组的索引；
2. 第二个是数组的值。
   相比传统的 for 循环，for range 要更简洁，如果返回的值用不到，可以使用 _ 下划线丢弃

切片和数组类似，可以把它理解为动态数组。切片是基于数组实现的，它的底层就是一个数组
基于数组的切片，使用的底层数组还是原来的数组，一旦修改切片的元素值，那么底层数组对应的值也会被修改。

除了可以从一个数组得到切片外，还可以声明切片，比较简单的是使用 make 函数

通过内置的 append 函数对一个切片追加元素，返回新切片
在创建新切片的时候，最好要让新切片的长度和容量一样，这样在追加操作的时候就会生成新的底层数组，从而和原有数组分离，就不会因为共用底层数组导致修改内容的时候影响多个切片

数组或切片的零值是元素类型的零值




#### map
在 Go 语言中，map 是一个无序的 K-V 键值对集合，结构为 map[K]V。其中 K 对应 Key，V 对应 Value。map 中所有的 Key 必须具有相同的类型，Value 也同样，但 Key 和 Value 的类型可以不同。此外，Key 的类型必须支持 == 比较运算符，这样才可以判断它是否存在，并保证 Key 的唯一。
map 的操作和切片、数组差不多，都是通过 [] 操作符，只不过数组切片的 [] 中是索引，而 map 的 [] 中是 Key，
```go
dict := make(map[string][]int)
dict2 := map[string][]int{}
```


Go 语言的 map 可以获取不存在的 K-V 键值对，如果 Key 不存在，返回的 Value 是该类型的零值，比如 int 的零值就是 0。所以很多时候，我们需要先判断 map 中的 Key 是否存在。
map 的 [] 操作符可以返回两个值：
1. 第一个值是对应的 Value；
2. 第二个值标记该 Key 是否存在，如果存在，它的值为 true
```go
nameAgeMap:=make(map[string]int)
nameAgeMap["飞雪无情"] = 20

age,ok:=nameAgeMap["飞雪无情1"]
if ok {
    fmt.Println(age)
}    
```
map 的遍历是无序的，也就是说你每次遍历，键值对的顺序可能会不一样。如果想按顺序遍历，可以先获取所有的 Key，并对 Key 排序，然后根据排序好的 Key 获取对应的 Value
和数组切片不一样，map 是没有容量的，它只有长度，也就是 map 的大小（键值对的个数）。要获取 map 的大小，使用内置的 len 函数即可

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

struct


### init

init函数在main函数前的所有init函数 并按照其声明顺序执行

不同文件里的init函数按照加载文件顺序执行


## Generic


## goroutine

Go不允许开发者控制goroutine的内存分配量和调度

Go使用工作共享和工作窃取来管理goroutine


## Context


## References

1. [Goproxy.cn](https://goproxy.cn/)