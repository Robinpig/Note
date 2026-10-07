## Introduction

C 是**编译型**语言：源码经预处理器、编译器、汇编器、链接器四步，最终变成可直接执行的机器码，没有解释器参与。理解这条「翻译单元 → 目标文件 → 可执行文件」的链路，是看懂 `make` / `CMake` / `GDB` 三篇的前提——它们都默认你已经知道「编译」和「链接」到底在干什么。

## Translation Unit

一个 `.c` 文件经过预处理（展开 `#include`、替换宏）之后得到的文本，称为一个**翻译单元**。每个翻译单元被**独立编译**成目标文件（`.o` / `.obj`），彼此不共享任何中间状态。这种「分单元编译 + 最后链接」的模型带来两个直接后果：

- 改一个 `.c` 只需重编它自己，不用重编整个项目（`make` 正是基于这个增量）。
- 跨文件的名字（函数、全局变量）要到**链接**阶段才拼到一起，所以*声明*（告诉编译器「这个符号存在、长什么样」）和*定义*（真正分配空间 / 生成指令）必须分开看。

## gcc's Four Stages

`gcc` 其实是一串工具的前端。对 `hello.c` 来说，一条 `gcc hello.c` 背后是四步：

```text
hello.c
  │ ① 预处理  cpp  (-E)   展开 #include / 宏 → hello.i
  ▼
hello.i
  │ ② 编译    cc1  (-S)   生成汇编 → hello.s
  ▼
hello.s
  │ ③ 汇编    as   (-c)   生成机器码 + 重定位 → hello.o
  ▼
hello.o  (+ 其它 .o / 库)
  │ ④ 链接    ld          解析符号、拼装 → a.out
  ▼
a.out
```

对应常用开关：`-E` 只预处理、`-S` 到汇编、`-c` 到目标文件（不链接）。调试时 `gcc -E hello.c | less` 能直接看到宏展开后的大量代码。

## Header Files and Declarations

`#include` 本质是「把头文件文本原样贴进来」。两种写法含义不同：

- `#include <stdio.h>`：去**系统**头路径找（编译器内置 + `-I` 追加）。
- `#include "my.h"`：先在当前目录找，找不到再走系统路径。

头文件里通常只放**声明**（`extern int g;`、`int foo(int);`、宏、类型定义），真正的**定义**留在某个 `.c` 里，保证整个程序里只有一份。为避免「同一定义被多个翻译单元包含 → 链接报多重定义」，头文件要加**包含守卫**：

```c
#ifndef MY_H
#define MY_H
/* ... 声明 ... */
#endif
```

`#pragma once` 是等价但非标准的写法，主流编译器都支持（细节见 [预处理与宏](/docs/CS/C/Preprocessor.md)）。

## Declaration vs Definition, External Linkage

- **声明**：引入名字，不分配存储。`extern int g;` 只是声明。
- **定义**：分配存储或生成函数体。`int g;` 是定义（C 里未初始化的全局叫「暂定定义」，同一 TU 内多个会合并为一个）。
- 具有**外部链接**的名字（默认全局函数 / 变量）在**整个程序**中只能有**一个定义**，否则链接器报 `multiple definition`。想要多文件共享，就「一个 `.c` 里定义、其它 `.c` 里 `extern` 声明」。

## Object Files and Symbols

`.o` 不是纯机器码，它至少含：代码 / 数据节、一张**符号表**（哪些名字已定义、哪些还待解析）、重定位信息。链接器靠符号表把各 `.o` 拼起来：

```shell
nm hello.o          # 看符号：T=代码  U=未定义  D=已初始化数据
readelf -h hello.o  # ELF 头（Linux）
```

`U` 标记的符号要在链接阶段从别的 `.o` 或库里找到，找不到就 `undefined reference`。

## Static Linking vs Dynamic Linking

链接到库有两种方式：

- **静态**（`.a`，`gcc ... -static`）：把库的目标代码**拷进**你的可执行文件。优点：自包含、部署简单；缺点：体积大、库升级要重编。
- **动态**（`.so` / macOS `.dylib`，默认）：可执行文件只记录「我需要 libxxx」，运行前由**动态链接器**加载、各进程共享同一份库代码（通过 PLT/GOT 重定位）。优点：省内存 / 磁盘、库可单独升级（如 glibc 安全补丁）；缺点：依赖目标机器有对应版本的库（「缺少 libxxx.so」）。

常用链接选项：`-I<dir>` 加头搜索路径、`-L<dir>` 加库搜索路径、`-lxxx` 链 `libxxx.so`（注意顺序：被依赖的库放后面）。

## Common Compilation Options

```shell
gcc -std=c11 -Wall -Wextra -O2 -g -Iinclude -Llib -lm main.c util.c -o app
```

- `-std=c11`：指定语言标准（见 [C 标准演进](/docs/CS/C/Standard.md)）。
- `-Wall -Wextra`：开常用警告——很多 UB 和笔误能被它抓出来。
- `-O2`：优化；注意优化会放大 UB 的后果（见 [未定义行为](/docs/CS/C/UB.md)）。
- `-g`：保留调试信息，配合 [GDB](/docs/CS/C/GDB.md)。
- `-fsanitize=address,undefined`：接 ASan / UBSan，运行期抓内存与 UB 错误。

## Links

- [C](/docs/CS/C/C.md)
- [预处理与宏](/docs/CS/C/Preprocessor.md)
- [make](/docs/CS/C/make.md)
- [CMake](/docs/CS/C/CMake.md)
- [GDB](/docs/CS/C/GDB.md)

## References

1. [GCC 官方手册](https://gcc.gnu.org/onlinedocs/gcc/)
2. [cppreference：C 文档](https://en.cppreference.com/w/c)
