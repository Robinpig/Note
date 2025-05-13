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