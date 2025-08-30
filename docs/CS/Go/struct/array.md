## Introduction







## array


数组是Go语言中常见的数据结构，相比切片，数组我们使用的比较少
只有数组大小和数组元素类型一样的数组才能够进行比较
Go语言中数组是一个值类型变量，将一个数组作为函数参数传递是拷贝原数组形成一个新数组传递，在函数里面对数组做任何更改都不会影响原数组



```go
var array [2]string
```

长度也是数组类型的一部分
所有元素都被初始化的数组定义时可以省略数组长度

编译期间的数组类型是由上述的 cmd/compile/internal/types.NewArray 函数生成的，类型 Array 包含两个字段，一个是元素类型 Elem，另一个是数组的大小 Bound，这两个字段共同构成了数组类型，而当前数组是否应该在堆栈中初始化也在编译期就确定了


使用传统的 for 循环遍历数组，输出对应的索引和对应的值，这种方式很烦琐，一般不使用，大部分情况下，我们使用的是 for range 这种 Go 语言的新型循环

for i,v:=range array{

    fmt.Printf(”数组索引:%d,对应值:%s\n“, i, v)

}


数组固定length
define type and length
shallow copy 
pointer array



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
   相比传统的 for 循环，for range 要更简洁，如果返回的值用不到，可以使用 _丢弃




### access


如何实现随机访问数组的全部元素
第一种方法用在Go调度器部分。G-M-P调度模型中，当M关联的P的本地队列中没有可以执行的G时候，M会从其他P的本地可运行G队列中偷取G，所有P存储一个全局切片中，为了随机性选择P来偷取，这就需要随机的访问数组。该算法具体叫什么，未找到相关文档。由于该算法实现上使用到素数和取模运算，姑且称之素数取模随机法。

第二种方法使用算法Fisher–Yates shuffle，Go语言用它来随机性处理通道选择器select中case语句
素数取模随机法 #
该算法实现逻辑是：对于一个数组[n]T，随机的从小于n的素数集合中，选择一个素数，假定是p，接着从数组0到n-1位置中随机选择一个位置开始，假定是m，那么此时(m + p)%n = i位置处的数组元素就是我们要访问的第一个元素。第二次要访问的元素是(上一次位置+p)%n处元素，这里面就是(i+p)%n，以此类推，访问n次就可以访问完全部数组元素

来自 `runtime/proc.go`


```go



// randomOrder/randomEnum are helper types for randomized work stealing.
// They allow to enumerate all Ps in different pseudo-random orders without repetitions.
// The algorithm is based on the fact that if we have X such that X and GOMAXPROCS
// are coprime, then a sequences of (i + X) % GOMAXPROCS gives the required enumeration.
type randomOrder struct {
	count    uint32
	coprimes []uint32
}

type randomEnum struct {
	i     uint32
	count uint32
	pos   uint32
	inc   uint32
}


func (ord *randomOrder) reset(count uint32) {
	ord.count = count
	ord.coprimes = ord.coprimes[:0]
	for i := uint32(1); i <= count; i++ {
		if gcd(i, count) == 1 {
			ord.coprimes = append(ord.coprimes, i)
		}
	}
}

func (ord *randomOrder) start(i uint32) randomEnum {
	return randomEnum{
		count: ord.count,
		pos:   i % ord.count,
		inc:   ord.coprimes[i/ord.count%uint32(len(ord.coprimes))],
	}
}

func (enum *randomEnum) done() bool {
	return enum.i == enum.count
}

func (enum *randomEnum) next() {
	enum.i++
	enum.pos = (enum.pos + enum.inc) % enum.count
}

func (enum *randomEnum) position() uint32 {
	return enum.pos
}

func gcd(a, b uint32) uint32 {
	for b != 0 {
		a, b = b, a%b
	}
	return a
}

func main() {
	arr := [8]int{1, 2, 3, 4, 5, 6, 7, 8}
	var order randomOrder
	order.reset(uint32(len(arr)))

	fmt.Println("====第一次随机遍历====")
	for enum := order.start(rand.Uint32()); !enum.done(); enum.next() {
		fmt.Println(arr[enum.position()])
	}

	fmt.Println("====第二次随机遍历====")
	for enum := order.start(rand.Uint32()); !enum.done(); enum.next() {
		fmt.Println(arr[enum.position()])
	}
}
```




## slice

Slice又称动态数组, 依托数组实现，底层数组对用户屏蔽，在底层数组容量不足时可以实现自动重分配并生成新的Slice

- 创建切片时可根据实际需要预分配容量，尽量避免追加过程中扩容操作，有利于提升性能；
- 切片拷贝时需要判断实际拷贝的元素个数
- 谨慎使用多个切片操作同一个数组，以防读写冲突





源码包中`src/runtime/slice.go:slice`定义了Slice的数据结构：

```go
type slice struct {
	array unsafe.Pointer
	len   int
	cap   int
}
```

切片有两个基本概念: 长度和容量

### makeslice

切片有多种声明方式，如下所示，在只声明不赋初始值的情况下，切片slice1的值为预置的nil，切片的初始化需要使用内置的make函数


通过内置的 append 函数对一个切片追加元素，返回新切片
在创建新切片的时候，最好要让新切片的长度和容量一样，这样在追加操作的时候就会生成新的底层数组，从而和原有数组分离，就不会因为共用底层数组导致修改内容的时候影响多个切片

数组或切片的零值是元素类型的零值



### append

使用append()向Slice添加一个元素的实现步骤如下：

- 假如Slice容量够用，则将新元素追加进去，Slice.len++，返回原Slice
- 原Slice容量不够，则将Slice先扩容，扩容后得到新Slice
- 将新元素追加进新Slice，Slice.len++，返回新的Slice

扩容操作只关心容量，扩容容量的选择遵循以下规则：

如果原Slice容量小于1024，则新Slice容量将扩大为原来的2倍；
如果原Slice容量大于等于1024，则新Slice容量将扩大为原来的1.25倍


### copy



使用copy()内置函数拷贝两个切片时，会将源切片的数据逐个拷贝到目的切片指向的数组中，拷贝数量取两个切片长度的最小值。

例如长度为10的切片拷贝到长度为5的切片时，将会拷贝5个元素。

也就是说，copy过程中不会发生扩容

## Links

