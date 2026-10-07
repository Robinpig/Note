## Introduction

`struct` 把多个字段打包进一段（通常）连续的内存。但「连续」不等于「紧凑」——编译器会按**对齐**要求插入**填充（padding）**，这既影响 `sizeof`，也影响你把结构体当二进制协议 / 内存映射看待时的正确性。

## Alignment

每个类型都有一个对齐要求：该类型的对象地址必须是某个值的整数倍。常见经验法则（具体由 **ABI** 规定，下以 System V AMD64 为例）：

- 基础类型对齐 = 其大小（上限通常为 16）：`char`=1、`short`=2、`int`=4、`long`/`double`=8、`long double`=16。
- 结构体的对齐 = 其**最大成员对齐**；结构体整体大小还要**向上取整到该对齐**。
- C11 用 `_Alignof` 查对齐，`_Alignas` 强制指定（C23 起 `alignof` / `alignas` 成为关键字）。

## Padding and Reordering

```c
struct ex { char a; int b; };   // sizeof = 8，不是 5：a 后填 3 字节
struct good { int b; char a; }; // sizeof = 8（尾随 3 字节仍对齐到 8）
struct better { int b; char a; char c; }; // 把字段按大小降序排，浪费更小
```

合理重排字段（大在下、小聚拢）能显著减小结构体体积——在百万级对象或网络协议里很关键。协议 / 文件格式里想要「无填充」时，要么手写 `#pragma pack`、要么用 `memcpy` 逐个字段序列化，绝不要直接 `memcpy` 整个带填充的结构体。

## offsetof and Container Macros

`<stddef.h>` 的 `offsetof(type, member)` 求某成员相对结构体开头的偏移。它是实现「侵入式数据结构」的基石，Linux 内核著名的 `container_of` 宏正是用它从成员指针反推外层结构体指针：

```c
#define container_of(ptr, type, member) \
    ((type *)((char *)(ptr) - offsetof(type, member)))
```

## Bit Fields (Bit-field)

```c
struct { unsigned int a : 3; unsigned int b : 5; } bf;
```

位域把多个小整数压进同一个机器字，节省空间。但：成员**不可取地址**；具体位布局（顺序、跨字行为）是**实现定义**的，跨平台 / 跨编译器不要假设一致——需要确定布局时用移位 + 掩码手写。

## Unions (union) and Type Punning

`union` 的所有成员共享同一段起始地址，大小为最大成员的大小：

```c
union { uint32_t u; float f; } x;
x.f = 3.14f;        // 用 float 视角写入
uint32_t bits = x.u; // 用 uint32_t 视角读出同一段位的位模式
```

这种「类型双关」在 **C 里是允许的**——C 标准明确允许通过 union  reinterpret 位模式（**C++ 不允许**，C++ 里要改用 `memcpy`）。注意它仍然受 [未定义行为](/docs/CS/C/UB.md) 里**严格别名规则**约束：直接写 `*(uint32_t*)&some_float` 是 UB，走 union 才是合规的例外路径。

## Alignment with Dynamic Memory

`malloc` 返回的地址保证适合**任何**基础类型对齐（即 `max_align_t` 对齐），所以直接 `malloc` 一个结构体是安全的。需要更大对齐（如 SIMD 的 32/64 字节）要用 `aligned_alloc`（C11）或平台接口。详见 [malloc](/docs/CS/C/malloc.md) 与 [glibc](/docs/CS/C/glibc.md)。

## Argument Passing and Return

结构体默认**按值**传递 / 返回（整段拷贝）。大结构体用指针传参更高效，也才能修改调用方的数据；返回大结构体时编译器通常暗中改为「调用方预留空间 + 指针返回」，无需手动优化。

## Links

- [C](/docs/CS/C/C.md)
- [malloc](/docs/CS/C/malloc.md)
- [未定义行为](/docs/CS/C/UB.md)
- [类型系统](/docs/CS/C/Types.md)

## References

1. [cppreference：struct](https://en.cppreference.com/w/c/language/struct)
2. [System V AMD64 ABI（对齐规则）](https://gitlab.com/x86-64-abi/abi/-/wikis/Home)
