## Introduction

Go是一种新的语言，一种并发的、带垃圾回收的、快速编译的语言。它具有以下特点：

- 它可以在一台计算机上用几秒钟的时间编译一个大型的Go程序。
- Go为软件构造提供了一种模型，它使依赖分析更加容易，且避免了大部分C风格include文件与库的开头。
- Go是静态类型的语言，它的类型系统没有层级。因此用户不需要在定义类型之间的关系上花费时间，这样感觉起来比典型的面向对象语言更轻量级。
- Go完全是垃圾回收型的语言，并为并发执行与通信提供了基本的支持

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



[compile](/docs/CS/Go/Basic/compile.md)


goroutine

channel

duck type

composition


### Build

go1.4之后实现了自举 需要一个1.4之后的go版本来执行
```shell
git clone https://github.com/golang/go.git
cd go/src
# wait for ALL TESTS PASSED
./all.bash
```
add path

## Basic

### Type
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

字符串
Go 语言中的字符串可以表示为任意的数据
在 Go 语言中，可以通过操作符 + 把字符串连接起来，得到一个新的字符串
字符串也可以通过 += 运算符操作

字符串 string 也是一个不可变的字节序列，所以可以直接转为字节切片 []byte

utf8.RuneCountInString 函数。运行下面的代码，可以看到打印结果是 9，也就是 9 个 unicode（utf8）字符，和我们看到的字符的个数一致。

fmt.Println(utf8.RuneCountInString(s))

而使用 for range 对字符串进行循环时，也恰好是按照 unicode 字符进行循环的，所以对于字符串 s 来说，循环了 9 次


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



类型转换

Go 语言是强类型的语言，也就是说不同类型的变量是无法相互使用和计算的，这也是为了保证Go 程序的健壮性，所以不同类型的变量在进行赋值或者计算前，需要先进行类型转换

通过包 strconv 的 Itoa 函数可以把一个 int 类型转为 string，Atoi 函数则用来把 string 转为 int。
同理对于浮点数、布尔型，Go 语言提供了 strconv.ParseFloat、strconv.ParseBool、strconv.FormatFloat 和 strconv.FormatBool 进行互转

对于数字类型之间，可以通过强制转换的方式
这种使用方式比简单，采用类型（要转换的变量）格式即可。采用强制转换的方式转换数字类型，可能会丢失一些精度，比如浮点型转为整型时，小数点部分会全部丢失


#### array

array

```go
var array[2] string
```

长度也是数组类型的一部分
所有元素都被初始化的数组定义时可以省略数组长度

编译期间的数组类型是由上述的 cmd/compile/internal/types.NewArray 函数生成的，类型 Array 包含两个字段，一个是元素类型 Elem，另一个是数组的大小 Bound，这两个字段共同构成了数组类型，而当前数组是否应该在堆栈中初始化也在编译期就确定了


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


> After long discussion it was decided that the typical use of maps did not require safe access from multiple goroutines, and in those cases where it did, the map was probably part of some larger data structure or computation that was already synchronized. Therefore requiring that all map operations grab a mutex would slow down most programs and add safety to few. This was not an easy decision, however, since it means uncontrolled map access can crash the program.

Go语言选择将key与value分开存储而不是以key/value/key/value的形式存储，是为了在字节对齐时压缩空间。
在进行hash[key]的map访问操作时，会首先找到桶的位置
找到桶的位置后遍历tophash数组，如图8-3所示，如果在数组中找到了相同的hash，那么可以接着通过指针的寻址操作找到对应的key与value。


在Go语言中还有一个溢出桶的概念，在执行hash[key]=value赋值操作时，当指定桶中的数据超过8个时，并不会直接开辟一个新桶，而是将数据放置到溢出桶中，每个桶的最后都存储了overflow，即溢出桶的指针。在正常情况下，数据是很少会跑到溢出桶里面去的”

同理，我们可以知道，在map执行查找操作时，如果key的hash在指定桶的tophash数组中不存在，那么需要遍历溢出桶中的数据。
后面还会看到，如果一开始，初始化map的数量比较大，则map会提前创建好一些溢出桶存储在extra*mapextra字段”
```go
type mapextra struct {
	// If both key and elem do not contain pointers and are inline, then we mark bucket
	// type as containing no pointers. This avoids scanning such maps.
	// However, bmap.overflow is a pointer. In order to keep overflow buckets
	// alive, we store pointers to all overflow buckets in hmap.extra.overflow and hmap.extra.oldoverflow.
	// overflow and oldoverflow are only used if key and elem do not contain pointers.
	// overflow contains overflow buckets for hmap.buckets.
	// oldoverflow contains overflow buckets for hmap.oldbuckets.
	// The indirection allows to store a pointer to the slice in hiter.
	overflow    *[]*bmap
	oldoverflow *[]*bmap

	// nextOverflow holds a pointer to a free overflow bucket.
	nextOverflow *bmap
}
```

这样当出现溢出现象时，可以用提前创建好的桶而不用申请额外的内存空间。只有预分配的溢出桶使用完了，才会新建溢出桶。
当发生以下两种情况之一时，map会进行重建：
- map超过了负载因子大小。
- 溢出桶的数量过多。 

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



### Function

```go
func funcName(params) result {
    body
}
```

如果函数有多个返回值，返回值部分的类型定义需要使用小括号括起来
在函数体中，可以使用 return 返回多个值，返回的多个值通过逗号分隔即可，返回多个值的类型顺序要和函数声明的返回类型顺序一致
不止函数的参数可以有变量名称，函数的返回值也可以，也就是说你可以为每个返回值都起一个名字，这个名字可以像参数一样在函数体内使用
虽然 Go 语言支持函数返回值命名，但是并不是太常用，根据自己的需求情况，酌情选择是否对函数返回值命名

可变参数

定义可变参数，只要在参数类型前加三个点 … 即可
可变参数的类型其实就是切片
如果你定义的函数中既有普通参数，又有可变参数，那么可变参数一定要放在参数列表的最后一个

同一个包中的函数哪怕是私有的（函数名称首字母小写）也可以被调用。如果不同包的函数要被调用，那么函数的作用域必须是公有的，也就是函数名称的首字母要大写，比如 Println


Go 语言没有用 public、private 这样的修饰符来修饰函数是公有还是私有，而是通过函数名称的大小写来代表，这样省略了烦琐的修饰符，更简洁
1. 函数名称首字母小写代表私有函数，只有在同一个包中才可以被调用；
2. 函数名称首字母大写代表公有函数，不同的包也可以调用；
3. 任何一个函数都会从属于一个包。

#### Closure

匿名函数和闭包
顾名思义，匿名函数就是没有名字的函数，这是它和正常函数的主要区别

有了匿名函数，就可以在函数中再定义函数（函数嵌套），定义的这个匿名函数，也可以称为内部函数。更重要的是，在函数内定义的内部函数，可以使用外部函数的变量等，这种方式也称为闭包


```go
func main() {
    cl:=colsure()
    fmt.Println(cl())
    fmt.Println(cl())
    fmt.Println(cl())
}

func colsure() func() int {
    i:=0
    return func() int {
        i++
        return i
    }
}
```
运行这个代码，你会看到输出打印的结果是：1 2 3
这都得益于匿名函数闭包的能力，让我们自定义的 colsure 函数，可以返回一个匿名函数，并且持有外部函数 colsure 的变量 i。因而在 main 函数中，每调用一次 cl()，i 的值就会加 1。
小提示：在 Go 语言中，函数也是一种类型，它也可以被用来声明函数类型的变量、参数或者作为另一个函数的返回值类型。

#### Method

在 Go 语言中，方法和函数是两个概念，但又非常相似，不同点在于方法必须要有一个接收者，这个接收者是一个类型，这样方法就和这个类型绑定在一起，称为这个类型的方法。
虽然存在函数和方法两个概念，但是它们基本相同，不同的是所属的对象。函数属于一个包，方法属于一个类型，所以方法也可以简单地理解为和一个类型关联的函数。

接收者的定义和普通变量、函数参数等一样，前面是变量名，后面是接收者类型。
定义了接收者的方法后，就可以通过点操作符调用方法

接收者就是函数和方法的最大不同，此外，上面所讲到的函数具备的能力，方法也都具备。
方法的接收者除了可以是值类型，也可以是指针类型。
定义的方法的接收者类型是指针，所以我们对指针的修改是有效的，如果不是指针，修改就没有效果
在调用方法的时候，传递的接收者本质上都是副本，只不过一个是这个值副本，一是指向这个值指针的副本。指针具有指向原有值的特性，所以修改了指针指向的值，也就修改了原有的值。我们可以简单地理解为值接收者使用的是值的副本来调用方法，而指针接收者使用实际的值来调用方法

```go
func main()	{
age := Age(25)
	age.String()
	age.Modify()
	age.String()
}

func (age *Age) Modify() {
	*age = Age(30)
}

type Age uint

func (age Age) String() {
	fmt.Println("the age is", age)
}
```
示例中调用指针接收者方法的时候，使用的是一个值类型的变量，并不是一个指针类型，其实这里使用指针变量调用也是可以的，如下面的代码所示

```go
(&age).Modify()
```

这就是 Go 语言编译器帮我们自动做的事情：
- 如果使用一个值类型变量调用指针类型接收者的方法，Go 语言编译器会自动帮我们取指针调用，以满足指针接收者的要求。
- 同样的原理，如果使用一个指针类型变量调用值类型接收者的方法，Go 语言编译器会自动帮我们解引用调用，以满足值类型接收者的要求。

总之，方法的调用者，既可以是值也可以是指针，不用太关注这些，Go 语言会帮我们自动转义，大大提高开发效率，同时避免因不小心造成的 Bug。
不管是使用值类型接收者，还是指针类型接收者，要先确定你的需求：在对类型进行操作的时候是要改变当前接收者的值，还是要创建一个新值进行返回？这些就可以决定使用哪种接收者

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

1. [Goproxy.cn](https://goproxy.cn/)
1. [Go语言圣经(中文版)](https://gopl-zh.github.io/)
1. [Go语言设计与实现](https://draveness.me/golang/)
1. [Go语言高级编程](http://docs.studygolang.com/advanced-go-programming-book/)
1. [Go专家编程](https://docs.kilvn.com/GoExpertProgramming/)
1. [Go Web编程](https://docs.kilvn.com/build-web-application-with-golang/zh/)
1. [深度探索Go语言](https://book-go-runtime.netlify.app/#/)