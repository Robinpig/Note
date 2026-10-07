## Introduction

interface 是 Go 多态的核心。表面上是"一组方法的集合"，底层在 runtime 里由两个结构体承载：非空接口 `iface`（声明了方法集）与空接口 `eface`（即 `interface{}` / `any`）。理解它们的内存布局与 `itab` 缓存，是看懂 Go 动态派发、类型断言开销，以及"nil interface ≠ nil pointer"陷阱的关键。

## iface 与 eface

非空接口（声明了方法）的运行时表示：

```go
// runtime/runtime2.go
type iface struct {
    tab  *itab
    data unsafe.Pointer
}
type eface struct {
    _type *_type
    data  unsafe.Pointer
}
```

- `eface` 只保存"底层具体类型"（`_type`）和"数据指针"（`data`），没有方法表——`interface{}` / `any` 用它承载任意值。
- `iface` 除了 `data`，还多一个 `tab *itab` 指针；`itab` 既指向接口类型，也指向具体类型的类型元数据，并缓存了该接口所要求的方法在**具体类型虚表**里的偏移（函数指针数组 `fun[1]`）。

## itab：接口与具体类型的契约缓存

```go
// runtime/runtime2.go
type itab struct {
    inter *interfacetype  // 接口类型（含方法集 mhdr）
    _type *_type          // 具体类型
    hash  uint32          // 类型哈希，用于快速判等
    _     [4]byte
    fun   [1]uintptr      // 变长：接口要求的方法地址（按接口方法集顺序）
}
```

- `interfacetype.mhdr` 是接口声明的方法集；`_type` 是具体类型的类型元数据。`itab.fun[k]` 保存"具体类型实现接口第 k 个方法"的函数指针。若具体类型没实现全部方法，则**无法构造 `itab`**（编译期即保证）。
- **动态派发**：调用 `iface.method()` 时，实际是 `fn = itab.fun[k]; call fn(data, args)`——先查 `itab` 里的函数指针再间接调用，这就是 Go 接口方法调用比直接调用慢、且通常无法被内联的原因。
- **itab 缓存**：`(接口类型, 具体类型)` 这对组合第一次相遇时，`runtime.getitab` 会做一次方法集匹配、构造 `itab` 并写入全局 `itabTable`（带锁的哈希表，读路径用 atomic）；之后同一对组合直接命中缓存，类型断言与转换几乎免费。

## 类型转换与装箱

- 把一个具体值赋给接口（如 `var e interface{} = 42`）会触发 `convT2E` / `convT2I`：若该值不是指针且会发生逃逸，runtime 会**在堆上拷贝一份**（"装箱"），`data` 指向这份拷贝；否则 `data` 直接指向原值。
- 这解释了为什么接口里存的是"值的拷贝"——修改原变量不影响接口内数据；要在接口里反映改动，应存指针（`interface{} = &x`）。

## 类型断言

- `v, ok := i.(T)` 走 `assertI2I` / `assertE2I`，基于 `itab` 匹配；失败时不 panic（带 `ok` 形式）或 panic（`i.(T)` 形式）。
- 断言到具体类型时直接复用 `itab`，断言到另一接口时做方法集子集检查。

## nil interface ≠ nil pointer（高频陷阱）

接口"为 nil"的充要条件是 **`tab/_type` 与 `data` 同时为 nil**。把一个**值为 nil 但类型非 nil** 的指针塞进接口，接口本身并不为 nil：

```go
func f() error { var p *MyErr = nil; return p } // 返回的是 *MyErr(nil)，不是 error(nil)
var e error = f()
e == nil // false！因为 e 的 _type=*MyErr, data=nil，类型非 nil
```

后果是 `if err != nil` 判定为 true，本应"无错误"的分支被跳过。详见 Issues（#45 返回 nil 接收器）。结论：**返回接口时永远显式返回 nil，不要返回 nil 指针**。

## 与泛型的关系

Go 1.18 泛型（`[T any]`）在编译期单态化（monomorphization），不走接口装箱与 `itab` 动态派发，性能等价于直接调用。对容器、算法等"只为多态而用 interface{}"的场景，用类型参数替代 `any` 可消除装箱开销与运行时类型检查。

## Links

- [struct 内部表示](/docs/CS/Go/struct/struct.md)
- [Go 语言总览](/docs/CS/Go/Go.md)
- [Issues：常见错误](/docs/CS/Go/Issues.md)

## References

1. [Go Data Structures: Interfaces](https://research.swtch.com/interface)
1. [Go 语言设计与实现：接口](https://draveness.me/golang/docs/interface/)
1. [runtime/runtime2.go](https://github.com/golang/go/blob/master/src/runtime/runtime2.go)
