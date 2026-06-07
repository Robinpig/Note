## Introduction


在 [Go 内存模型] 的术语中，对于任何 n < m，第 n 次对 [Mutex.Unlock] 的调用“synchronizes before”第 m 次对 [Mutex.Lock] 的调用。
对 [Mutex.TryLock] 的成功调用等效于对 Lock 的调用。
失败的 TryLock 调用根本不建立任何“synchronizes before”关系。


## Links

- [Golang](/docs/CS/Go/Go.md)