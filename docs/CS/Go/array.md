## Introduction













## array






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

