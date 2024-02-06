## Introduction

http://play.golang.org




go get set proxy


```shell
//go version >=1.13 
go env -w GO111MODULE=on
go env -w GOPROXY=https://goproxy.cn,direct

//get godoc
go get -v  golang.org/x/tools/cmd/godoc
godoc -http=:6060
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

8 Byte
array

```go
var array[2] string
```



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





map

```go
dict := make(map[string][]int)
dict2 := map[string][]int{}
```





struct

## References

1. [Goproxy.cn](https://goproxy.cn/)