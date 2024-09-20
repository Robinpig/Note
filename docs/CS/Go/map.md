## Introduction

A map is just a hash table. The data is arranged into an array of buckets. Each bucket contains up to 8 key/elem pairs. The low-order bits of the hash are used to select a bucket. Each bucket contains a few high-order bits of each hash to distinguish the entries within a single bucket.

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
nameAgeMap[”飞雪无情“] = 20

age,ok:=nameAgeMap[”飞雪无情1“]
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



If more than 8 keys hash to a bucket, we chain on extra buckets.



When the hashtable grows, we allocate a new array of buckets twice as big. Buckets are incrementally copied from the old bucket array to the new bucket array.



Map iterators walk through the array of buckets and return the keys in walk order (bucket #, then overflow chain order, then bucket index). 

To maintain iteration semantics, we never move keys within their bucket (if we did, keys might be returned 0 or 2 times). 

When growing the table, iterators remain iterating through the old table and must check the new table if the bucket they are iterating through has been moved ("evacuated") to the new table.




```go
// A header for a Go map.
type hmap struct {
    // Note: the format of the hmap is also encoded in cmd/compile/internal/reflectdata/reflect.go.
    // Make sure this stays in sync with the compiler's definition.
    count     int // # live cells == size of map.  Must be first (used by len() builtin)
    flags     uint8
    B         uint8  // log_2 of # of buckets (can hold up to loadFactor * 2^B items)
    noverflow uint16 // approximate number of overflow buckets; see incrnoverflow for details
    hash0     uint32 // hash seed

    buckets    unsafe.Pointer // array of 2^B Buckets. may be nil if count==0.
    oldbuckets unsafe.Pointer // previous bucket array of half the size, non-nil only when growing
    nevacuate  uintptr        // progress counter for evacuation (buckets less than this have been evacuated)

    extra *mapextra // optional fields
}

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



在Go语言中还有一个溢出桶的概念，在执行hash[key]=value赋值操作时，当指定桶中的数据超过8个时，并不会直接开辟一个新桶，而是将数据放置到溢出桶中，每个桶的最后都存储了overflow，即溢出桶的指针。在正常情况下，数据是很少会跑到溢出桶里面去的”

同理，我们可以知道，在map执行查找操作时，如果key的hash在指定桶的tophash数组中不存在，那么需要遍历溢出桶中的数据。
后面还会看到，如果一开始，初始化map的数量比较大，则map会提前创建好一些溢出桶存储在extra*mapextra字段”


这样当出现溢出现象时，可以用提前创建好的桶而不用申请额外的内存空间。只有预分配的溢出桶使用完了，才会新建溢出桶。
当发生以下两种情况之一时，map会进行重建：
- map超过了负载因子大小。
- 溢出桶的数量过多



```go
type bmap struct {
    tophash [abi.SwissMapBucketCount]uint8
}
```

`bmap` 结构体其实不止包含 `tophash` 字段，由于哈希表中可能存储不同类型的键值对并且 Go 语言也不支持泛型，所以键值对占据的内存空间大小只能在编译时进行推导，
这些字段在运行时也都是通过计算内存地址的方式直接访问的，所以它的定义中就没有包含这些字段，但是我们能根据编译期间的 [cmd/compile/internal/reflectdata/reflect.MapBucketType](https://github.com/golang/go/blob/go1.23.1/src/cmd/compile/internal/reflectdata/reflect.go) 函数对它的结构重建：
```go
type bmap struct {
    topbits  [8]uint8
    keys     [8]keytype
    values   [8]valuetype
    pad      uintptr
    overflow uintptr
}
```


make



```go
func makemap_small() *hmap {
    h := new(hmap)
    h.hash0 = uint32(rand())
    return h
}
```

