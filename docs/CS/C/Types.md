## Introduction

C 的类型系统是它表达力的基础，也藏着整型提升、隐式转换这类「安静的坑」。理解它们，才能写出在 32/64 位、不同编译器间可移植的代码。

## 基础类型

- 整数：`char`（实现定义 signed/unsigned，x86 上通常是 signed）、`short`、`int`、`long`、`long long`。`int` 至少 16 位、`long` 至少 32 位——但具体宽度**依赖平台**：Linux/macOS 是 LP64（`long`=64 位），Windows 是 LLP64（`long`=32 位、`long long`=64 位）。
- 浮点：`float` / `double` / `long double`（宽度依 ABI）。
- `_Bool`（C99）；C23 起 `bool` 成为关键字（`stdbool.h` 的 `true`/`false` 也是）。
- `void`：无类型，用于「无返回值 / 泛型指针」。

## 定宽整数：`<stdint.h>`

为了可移植、尤其和协议 / 文件格式 / 序列化对齐，优先用定宽类型：

- `int8_t` `int16_t` `int32_t` `int64_t` 及对应 `uint*_t`。
- `intptr_t` / `uintptr_t`：能装下指针的整数（指针↔整数转型必备）。
- `intmax_t` / `uintmax_t`：最大宽度整数。
- 极限宏 `INT32_MAX`、`SIZE_MAX` 等在 `<stdint.h>` / `<limits.h>`。

注意 `int8_t` 等**不保证存在**（要求补码 8 位），但所有现代平台都有。

## 隐式转换与整型提升

- **整型提升**：小于 `int` 的整数类型（`char`、`short`）在多数表达式里先提升为 `int`（或 `unsigned int`）。这就是 `char c = getchar(); if (c == EOF)` 要把 `c` 声明成 `int` 的原因（`EOF` 是 `int`）。
- **寻常算术转换**：二元运算符两边类型不同时，按「秩（rank）」向宽 / 无符号方向统一；浮点与整数运算时整数先转浮点。
- **有符号 vs 无符号混合**：一边是 `unsigned` 时另一边也转 `unsigned`——常见陷阱：
  ```c
  size_t n = 5;
  if (n < -1) { /* 不执行：-1 转 size_t 成巨大正数 */ }
  ```

## 有符号 vs 无符号

无符号溢出良定义（模回绕）；有符号溢出是 [UB](/docs/CS/C/UB.md)。下标、计数、位运算用 `unsigned` 更安全；但别把 `unsigned` 和无符号字面量混进有符号比较里「悄悄」变号。

## 字节序（Endianness）

多字节整数在内存里的字节排列：

- **小端**（little-endian）：低字节在低地址（x86、ARM 通常小端）。
- **大端**（big-endian）：高字节在低地址（网络字节序）。
- 网络协议统一用大端，跨主机通信要转换：
  ```c
  #include <arpa/inet.h>
  uint32_t net  = htonl(host);   // 主机→网络
  uint32_t host = ntohl(net);     // 网络→主机
  ```
- 想看一个整数的字节，用 `union` 或 `memcpy` 逐字节读（类型双关见 [结构体](/docs/CS/C/Struct.md)）；GCC/Clang 提供 `__builtin_bswap32/64`。**不要**直接强转指针做类型双关（严格别名 UB）。

## 限定符

- `const`：只读（语义约束，非「常量」）。
- `volatile`：禁止编译器把对该对象的访问优化掉（硬件寄存器、信号处理、并发里防重排——但 `volatile` **不构成**线程同步，同步请看 [并发与原子](/docs/CS/C/Concurrency.md)）。
- `restrict`（C99）：承诺指针是唯一别名，给编译器优化自由（与 [UB](/docs/CS/C/UB.md) 严格别名相关）。
- `_Atomic`（C11）/ `_Alignas`：原子与对齐（见 [并发与原子](/docs/CS/C/Concurrency.md) / [结构体](/docs/CS/C/Struct.md)）。

## 枚举

`enum` 的底层类型是 `int`（C23 起可指定底层类型，如 `enum : unsigned char`）。枚举常量是 `int`，没有强类型——需要「类型安全的一组整数」时要注意。

## Links

- [C](/docs/CS/C/C.md)
- [结构体](/docs/CS/C/Struct.md)
- [未定义行为](/docs/CS/C/UB.md)
- [预处理与宏](/docs/CS/C/Preprocessor.md)
- [C 标准演进](/docs/CS/C/Standard.md)

## References

1. [cppreference：类型与转换](https://en.cppreference.com/w/c/language/types)
2. [cppreference：整数类型](https://en.cppreference.com/w/c/types/integer)
