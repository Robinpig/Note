## Introduction

C 语言是一种通用的、面向过程式的计算机程序设计语言。1972 年，为了移植与开发 UNIX 操作系统，丹尼斯·里奇（Dennis Ritchie）在贝尔实验室设计开发了 C 语言。它贴近硬件、零隐藏成本，是操作系统（如 Linux 内核）、嵌入式与高性能基础设施的基石，也是 C++、Go、Rust 等语言的共同源头。

## 知识体系

本目录下 C 相关的笔记可以按几条主线理解：

- **语言核心**：类型与表示、指针、结构体布局、数组与字符串、预处理——这些决定你写出的 C 是否正确、可移植。
- **内存管理**：手动 `malloc`/`free` 是 C 程序最容易出错、也最值得深入的部分。
- **编译与链接**：从翻译单元到可执行文件，是工程化的地基。
- **工具链**：`make` / `CMake` 构建系统与 `GDB` 调试器。
- **运行时与并发**：C 程序运行在 libc（本库以 glibc 为主）之上，线程靠 POSIX `pthread`、原子靠 C11 `<stdatomic.h>`。
- **标准库与标准**：libc 各模块总览，以及 C 标准的演进脉络。

## 类型与表示

[类型系统](/docs/CS/C/Types.md) 讲基础类型、`<stdint.h>` 定宽整数、整型提升与字节序——可移植代码的起点。

[预处理与宏](/docs/CS/C/Preprocessor.md) 是编译前的文本层：`#define` / `#include` / `#ifdef`、可变参数宏、`#` / `##` 运算符、X-Macros，以及宏的常见陷阱。

## 指针

指针保存的是内存地址。理解指针必须先建立「变量 / 地址 / 内存」三者的对应关系：取址 `&`、解引用 `*`、指针算术都与数组、`malloc` 返回的堆地址直接相关。指针用错（空指针、野指针、越界、悬垂）也是 C 内存问题的根源——它和「Memory」一节是同一件事的两面。

## 结构体与内存布局

[结构体](/docs/CS/C/Struct.md) 把字段打包进连续内存，但编译器会按对齐插入填充：`offsetof`、位域、联合体（union）做类型双关的合规路径都在这里。

## 数组与字符串

[数组与字符串](/docs/CS/C/Array_String.md) 讲清两件事：C 没有原生字符串类型（字符串是 `\0` 结尾的 `char` 数组），数组名在多数语境会退化成指针——这两点是大量 bug 的来源，并给出缓冲区溢出的防御。

## 未定义行为

[未定义行为](/docs/CS/C/UB.md) 汇总有符号溢出、严格别名、序列点、数据竞争等「标准不保证」的雷区。写出正确 C 的关键，就是知道哪些操作是 UB，以及如何用 `-Wall` / UBSan 防御。

## Memory

[glibc](/docs/CS/C/glibc.md) 是 Linux 上 C 程序的运行时基础，内存分配由其中的 ptmalloc 负责。

堆分配 `malloc`/`free` 不是系统调用，而是用户态 ptmalloc 对 `brk`/`mmap` 的封装：chunk、arena、bin 的完整链路见 [malloc](/docs/CS/C/malloc.md)。

- malloc()
  分配内存并返回其地址，但并不进行初始化，存储具体数据未指定类型。
- calloc()
  会对申请内存进行初始化。
- realloc()
  可动态调整申请内存大小。
- free()
  显式释放内存。

## 编译与链接

[编译与链接](/docs/CS/C/Compilation.md) 展开「翻译单元 → 预处理 → 编译 → 汇编 → 链接」四阶段、目标文件与符号、静态 / 动态链接，以及 `-I` / `-L` / `-l` / `-std` 等常用选项——这是看懂下面工具链三篇的前提。

## 工具链

构建与调试是 C 工程化的两条腿：

- [make](/docs/CS/C/make.md) / [CMake](/docs/CS/C/CMake.md)：Makefile 与跨平台构建系统。
- [GDB](/docs/CS/C/GDB.md)：基于 `ptrace` 的 GNU 调试器，单步、断点、观察崩溃现场。

## 运行时与并发

- [glibc](/docs/CS/C/glibc.md)：libc 与 ptmalloc 内存分配器（见上「Memory」）。
- [并发与原子](/docs/CS/C/Concurrency.md)：POSIX `pthread` 的 mutex / condvar / 读写锁，以及 C11 `_Atomic` 与内存序（acquire-release 同步）。
- [Thread](/docs/CS/C/Thread.md)：线程池的实现模式。

## 标准库与标准

- [标准库总览](/docs/CS/C/Stdlib.md)：libc 按头文件分模块，重点讲 errno 错误处理、setjmp/longjmp、`<stdarg.h>` 可变参数。
- [C 标准演进](/docs/CS/C/Standard.md)：C89→C99→C11→C17→C23 的特性线，以及 `-std` 与 `__STDC_VERSION__` 的实践。

## Links

- [C++](/docs/CS/C++/C++.md)
- [编程语言横向对比](/docs/CS/Languages.md)

## References

1. [C 语言标准（ISO/IEC 9899，WG14）](https://www.open-std.org/jtc1/sc22/wg14/)
2. [cppreference：C 文档](https://en.cppreference.com/w/c)
3. [The GNU C Library 手册](https://www.gnu.org/software/libc/manual/)
