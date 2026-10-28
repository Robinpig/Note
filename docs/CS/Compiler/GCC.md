# GCC

## Introduction

GCC（GNU Compiler Collection）不是单一编译器，而是**驱动程序 + 语言前端 + 目标后端**的组合：一条 `gcc hello.c -o hello` 命令背后，驱动依次调用预处理、编译、汇编、链接四个程序。
理解这张流水线，是排查编译错误与调优构建的前提。

两种使用形态：

- **本地编译**（native）：生成代码跑在编译机上；
- **交叉编译**（cross compile）：生成代码跑在另一架构/系统上，常见于嵌入式与内核开发。

## Cross Compilation

交叉工具链的命名遵循固定模式，看到名字就知道目标：

```
[arch]-[vendor]-[os]-[abi]
aarch64-linux-gnu-gcc     # ARM64 + Linux + glibc ABI
arm-none-eabi-gcc         # 裸机 ARM，无操作系统
x86_64-w64-mingw32-gcc    # Windows 目标（MinGW）
riscv64-unknown-elf-gcc   # RISC-V 裸机
```

- 前缀即 `--target=`，`-print-sysroot` 打印目标系统的 sysroot 根；
- `--sysroot=<dir>` 指定目标系统的头文件与库所在位置，交叉编译时必须与工具链的 target 匹配；
- 架构相关的编译选项（`-march`、`-mfpu`、`-mabi`）决定生成指令集，内核与裸机开发对此极其敏感。

## Driver and Pipeline

`gcc` 驱动按输入文件类型决定调用哪些程序，四阶段可分别截停观察：

```shell
gcc -E hello.c -o hello.i    # 预处理：宏展开、头文件包含、条件编译
gcc -S hello.i -o hello.s    # 编译：C → 汇编
gcc -c hello.s -o hello.o    # 汇编：汇编 → 可重定位目标文件
gcc hello.o -o hello         # 链接：目标文件 + 库 → 可执行文件
```

| 阶段 | 程序 | 输入 → 输出 |
| :--- | :--- | :--- |
| 预处理 | `cpp` / `cc1 -E` | `.c` → `.i` |
| 编译 | `cc1`（语言专属） | `.i` → `.s` |
| 汇编 | `as` | `.s` → `.o` |
| 链接 | `collect2` → `ld` | `.o` + `.a/.so` → 可执行文件 |

- `-v` 打印驱动实际调用的每个子程序与参数，排查"到底链接了哪个库"的第一工具；
- `-###` 类似但不执行；
- 多文件编译时，每个 `.c` 独立走完前三阶段，最后统一链接——这是增量构建与 make 的基础。

## Common Options

| 选项 | 作用 |
| :--- | :--- |
| `-O0 / -O1 / -O2 / -O3 / -Os / -Og` | 优化级别，`-Os` 以大小为目标，`-Og` 保调试性 |
| `-std=c11 / gnu17` | 语言标准，`gnu` 前缀启用扩展 |
| `-Wall -Wextra -Werror` | 告警集合；`-Werror` 让告警失败 |
| `-g` | 生成调试信息，`-g3` 含宏 |
| `-fno-omit-frame-pointer` | 保留帧指针，profiling / 栈回溯必需 |
| `-march=native -mtune=native` | 按本机（或交叉目标）指令集生成 |
| `-flto` | 链接期优化，跨编译单元内联与优化 |
| `-fanalyzer` | 静态分析器（GCC 10+），检查空指针、双重释放、泄漏 |
| `-pthread` | 链接线程库并启用相关宏 |
| `-shared -fPIC` | 生成位置无关的共享库 |

优化选项的语义详见 [Optimization](/docs/CS/Compiler/Optimization.md)；诊断输出格式可用 `-fdiagnostics-color=always`、`-fmessage-length=0` 适配 CI 与编辑器解析。

## Builtins

`__builtin_*` 系列把常用操作直译成最优指令序列，跳过普通函数调用的 ABI 开销。
分支预测提示是其中对性能影响最大的一类：

```c
#define likely(x)   __builtin_expect(!!(x), 1)
#define unlikely(x) __builtin_expect(!!(x), 0)
```

`__builtin_expect(exp, c)` 告诉编译器 `exp == c` 是高频路径，影响基本块排布（热路径连续存放，冷路径外移），与 [Instruction-Level Parallelism](/docs/CS/Compiler/Instruction_Level_Parallelism.md) 中的分支预测配合。
其它常用内置：`__builtin_prefetch`（预取）、`__builtin_clz`（前导零计数，常映射到单条指令）、`__builtin_expect` 的内存序版本 `__atomic_*` / `__sync_*`。

## ELF

GCC 的编译产物默认是 [ELF](/docs/CS/Compiler/ELF.md) 目标文件（Linux）或 PE/COFF（Windows）；`-r` 生成部分链接的可重定位文件，`-static` 关闭动态链接。
验证产物：

```shell
file hello.o
readelf -h hello.o
```

## Issues

Ubuntu 等发行版同时安装多个 GCC 版本时的切换机制：

```shell
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-12 120
sudo update-alternatives --config gcc
```

常见坑：`cc`/`gcc` 符号链接与真实版本错位、`gcc` 是驱动而 `g++` 只是加链 `libstdc++` 的同族驱动、驱动版本与子程序（`cc1`）版本不匹配导致 `-print-prog-name=cc1` 找到错误副本。

## Links

- [Compiler](/docs/CS/Compiler/Compiler.md)
- [ELF](/docs/CS/Compiler/ELF.md)
- [Optimization](/docs/CS/Compiler/Optimization.md)
- [Assembler and Toolchain](/docs/CS/assembly/Assembler_and_Toolchain.md)
- [GNU](/docs/CS/GNU/GNU.md)

## References

1. [GCC Online Documentation](https://gcc.gnu.org/onlinedocs/)
2. [GNU Binutils](https://www.gnu.org/software/binutils/)
