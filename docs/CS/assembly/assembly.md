## Introduction

**汇编语言**是机器指令的一对一符号表示：一条汇编语句基本对应一条机器指令，一个助记符（mnemonic）对应一个操作码。它没有变量作用域、没有类型系统、没有控制流抽象——只有寄存器、内存地址、标志位和跳转。也正因为"没有抽象"，它成为唯一能精确表达"硬件到底做了什么"的层次：[组成原理](/docs/CS/CO/CO.md)里的[指令集架构](/docs/CS/CO/isa.md)是软硬契约，汇编就是这份契约的书写形式；[编译器](/docs/CS/Compiler/Compiler.md)的输出、[C 语言](/docs/CS/C/C.md)的语义下限、调试器看到的现场，最终都落到这里。

处理器只认 0/1 的机器码，机器码对人类不可能手工维护——地址要重算、指令长度不定、分支偏移是字节数。汇编器（assembler）解决的正是这三件事：**助记符换操作码、符号地址换数值地址、跳转标签换偏移**，此外提供一批不产生指令的**伪指令**（directive）来切 section、对齐、定义数据。

> [!NOTE]
> 版本口径：本子树以 **x86-64（SysV 与 Win64 双 ABI）+ GNU 工具链**为主线，对比面覆盖 AArch64 与 RISC-V。工具版本实测：NASM **3.02**（2026-06-29）、GNU binutils **2.47**（2026-07-26）、GCC **16.2**（2026-08-07）。注意 binutils 官网首页仍写 2.46，落后一个版本——判断工具行为请以 `as --version` 为准，不要以官网为准。

## Why Assembly Still Matters

今天几乎没人用汇编写业务，但下面六件事离开汇编就做不了，或者做不好：

- **编译器表达不出来的指令**：上下文切换要保存/恢复全部寄存器、启动代码要在 C 运行时之前设好栈、`sgdt`/`wrmsr`/`swapgs` 这类系统指令没有 C 内建表达。这也是 [操作系统](/docs/CS/OS/OS.md)里从 [进程切换](/docs/CS/OS/process.md) 到 [xv6 的中断入口](/docs/CS/OS/xv6/Interrupt.md) 都留着一小段 `.S` 的原因。
- **验证编译器做了什么**：优化打开之后，"这段代码快不快"只能看生成的汇编。读得懂输出才知道 `-O2` 有没有向量化、有没有把除法换成乘法、有没有消除掉你的边界检查。
- **定性能下限**：SIMD 内联、加解密内核、memcpy/memcmp、CRC32、矩阵小核这些地方，编译器有时差一口气，intrinsic 兜不住时才上 [内联汇编](/docs/CS/assembly/Inline_Assembly.md)。
- **调试与逆向**：崩溃现场给的是寄存器和栈，coredump 里的调用栈要靠栈帧与 unwind 信息还原；漏洞分析、二进制补丁、符号缺失的第三方库，工作面就是反汇编。
- **ABI 与 FFI**：跨语言调用、回调、JNI、Wasm host 函数，出问题的地方几乎都是调用约定。Rust/Go/C++ 混编踩的坑，本质都在 [调用约定](/docs/CS/assembly/Calling_Convention.md) 那一页。
- **理解"为什么这么慢"**：缓存行、假共享、分支预测、store-forwarding stall 这些现象在 C 里只能猜，在汇编里能定位到指令。

## The Three Contracts

写汇编要同时遵守三份彼此独立的契约，混淆它们是新手最常见的错误来源：

| 契约 | 规定者 | 内容 | 违反后果 |
|------|--------|------|----------|
| **ISA**（指令集架构） | 芯片厂商文档 | 有哪些指令、寄存器、寻址方式、编码 | 非法指令 SIGILL |
| **汇编器语法** | 汇编器实现（GAS / NASM / MASM） | 操作数顺序、伪指令、注释、宏 | 汇编期报错，或悄无声息生成别的指令 |
| **ABI**（调用约定） | 操作系统/编译器约定 | 参数放哪、谁保存寄存器、栈怎么对齐 | 能跑能过编译，但和其他模块接不上、或者偶发崩溃 |

ISA 是硬件事实，语法是工具事实，ABI 是约定事实。同一份 x86-64 机器码，Intel 语法和 AT&T 语法写出来完全不像同一种语言；同一段能跑的汇编，参数放错寄存器就调不了 C 函数。这三层的分册分别是 [指令集与常用指令](/docs/CS/assembly/Instruction_Set.md)、[语法与伪指令](/docs/CS/assembly/Syntax_and_Directives.md)、[调用约定与 ABI](/docs/CS/assembly/Calling_Convention.md)。

## Syntax Dialects

x86 有两套语法：Intel（NASM、MASM、GDB 默认可选、Intel 手册）与 AT&T（GAS 默认、objdump 默认）。操作数顺序相反、寄存器与立即数的标记符号相反、内存寻址写法也不同——同一个 `mov` 在两边长得完全不一样。GAS 可以 `.intel_syntax noprefix` 切到 Intel 风格，但伪指令仍是 GAS 自己的一套。方言差异、伪指令清单、宏写法见 [语法与伪指令](/docs/CS/assembly/Syntax_and_Directives.md)。

## Registers and Data Movement

x86-64 有 16 个 64 位通用寄存器，其中一部分被 ABI 赋予了固定角色（栈指针、帧指针、传参顺序、调用者保存/被调用者保存的分界）。32 位写会清零高 32 位、8/16 位写不会——这个细节既影响性能也影响正确性。寻址方式上 x86 支持"基址 + 变址×比例 + 位移"这种复杂形式，一条指令完成数组元素定位；`lea` 因此常被当成算术指令用。寄存器文件全景与寻址谱系见 [寄存器与寻址方式](/docs/CS/assembly/Registers_and_Addressing.md)。

## Instructions and Flags

指令按功能分成数据传送、算术、逻辑/移位、比较测试、控制流、栈操作、串与向量、系统指令几大类。真正需要记住的与其说是指令清单，不如说是 x86 的几条硬约束：**`mov` 不能内存到内存**、立即数宽度有限制、`mul`/`div` 用隐式操作数、除法前必须扩展符号。算术结果不只写目标寄存器，还写标志位（CF/ZF/SF/OF），后续的 `jcc`/`setcc`/`cmov` 都读这些位——这是 x86 与 RISC 在风格上最大的差别之一。指令语义与标志位见 [指令集与常用指令](/docs/CS/assembly/Instruction_Set.md)。

## Calling Convention and Stack

函数怎么接参数、怎么返回、栈怎么长，由 ABI 规定而不是硬件：x86-64 System V 用 `rdi/rsi/rdx/rcx/r8/r9` 传前六个整型参数，Windows x64 用 `rcx/rdx/r8/r9` 四个并额外要求调用者预留 32 字节 shadow space；两者在"哪些寄存器被调用者保存"上也不同。栈帧的构造（prologue/epilogue）、16 字节对齐要求、red zone、栈保护与栈回溯，是手写汇编最容易出事的地方，见 [调用约定与 ABI](/docs/CS/assembly/Calling_Convention.md) 与 [栈帧与函数调用](/docs/CS/assembly/Stack_Frame.md)。

## Talking to the Kernel

不链接 libc 的纯汇编程序要自己发系统调用：`syscall` 指令、调用号进 `rax`、参数进 `rdi/rsi/rdx/r10/r8/r9`（注意第四个是 `r10` 不是 `rcx`，因为 `syscall` 本身会破坏 `rcx` 和 `r11`）。调用号是**按架构分表**的：x86-64 上 `write=1`、`exit=60`，而 AArch64/RISC-V 走 asm-generic 表，`write=64`、`exit=93`——同一段逻辑换个架构不只是换助记符，调用号也得换。系统调用的完整调用序列、错误返回、vDSO 与内核侧入口见 [系统调用](/docs/CS/assembly/System_Calls.md)。

## Assembly in Host Languages

真正常见的不是 `.s` 文件，而是**嵌在高级语言里的汇编**：GCC/Clang 的扩展 `asm`（操作数约束、clobber 列表、volatile、asm goto）、Rust 的 `asm!`/`global_asm!`/`naked_asm!`、MSVC 的 intrinsic 路线（x64 下 MSVC 已不支持内联汇编）。内联汇编的危险之处在于编译器不知道你改了什么——漏一个 clobber 声明就能让代码在 `-O2` 下偶发算错。各语言写法与已知陷阱见 [内联汇编](/docs/CS/assembly/Inline_Assembly.md)。

## Toolchain and Verification

从源码到可执行文件：`gcc -S` 看编译器生成什么、`as` 汇编成 `.o`、`ld` 链接；反汇编用 `objdump -d -M intel`（默认 AT&T，容易看错操作数方向）、`readelf` 看 section 与重定位、`nm` 看符号、`gdb` 里 `disassemble`/`stepi`/`layout asm` 单步到指令级。位置无关代码（PIC/PIE）依赖 GOT/PLT 与 RIP 相对寻址，这是动态库能加载到任意地址的机制。工具链与反汇编实践见 [汇编器与工具链](/docs/CS/assembly/Assembler_and_Toolchain.md)。

## Reading Compiler Output

最后一层是"读得懂且读得快"：`xor eax, eax` 是清零、`lea` 是做算术、`test` 后跟 `je` 是判零、除法变成乘法加移位说明编译器做了倒数替换、出现 `call memset` 说明它识别出了惯用法。手写汇编想赢过编译器，前提是知道编译器通常会怎么做、在哪些地方它保守。惯用法清单、常见优化模式与微架构陷阱见 [惯用法与优化](/docs/CS/assembly/Optimization_and_Idioms.md)。

## Links

- [指令集架构（ISA）](/docs/CS/CO/isa.md)
- [Computer Organization（组成原理枢纽）](/docs/CS/CO/CO.md)
- [C](/docs/CS/C/C.md)
- [ELF 与目标文件格式](/docs/CS/Compiler/ELF.md)
- [数据表示（补码与 IEEE 754）](/docs/CS/CO/datarep.md)
- [编程语言横向对比](/docs/CS/Languages.md)

## References

1. [NASM — The Netwide Assembler](https://nasm.us/)
2. [NASM Documentation](https://nasm.us/docs.html)
3. [GNU Binutils — Using as（GAS 手册）](https://sourceware.org/binutils/docs/as/)
4. [System V AMD64 psABI（版本 1.0）](https://gitlab.com/x86-psABIs/x86-64-ABI)
5. [x86-64 psABI 1.0 PDF](https://github.com/hjl-tools/x86-psABI/wiki/x86-64-psABI-1.0.pdf)
6. [Intel 64 and IA-32 Architectures Software Developer Manuals](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
7. [AMD64 Architecture Programmer's Manual（Volume 1-5）](https://www.amd.com/en/search/site-search.html?k=AMD64%20Architecture%20Programmer%27s%20Manual)
8. [Linux x86-64 syscall table（内核源码）](https://github.com/torvalds/linux/blob/master/arch/x86/entry/syscalls/syscall_64.tbl)
9. [GCC — Using Assembly Language with C](https://gcc.gnu.org/onlinedocs/gcc/Using-Assembly-Language-with-C.html)
10. [Rust Reference — Inline Assembly](https://doc.rust-lang.org/reference/inline-assembly.html)
11. [Agner Fog — Software Optimization Resources](https://www.agner.org/optimize/)
