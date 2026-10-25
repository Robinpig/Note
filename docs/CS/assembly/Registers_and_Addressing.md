## Introduction

寄存器是汇编语言里唯一有名字的存储。x86-64 只有 16 个通用寄存器，比 AArch64 和 RISC-V 都少——这个数字直接决定了 [调用约定](/docs/CS/assembly/Calling_Convention.md) 为什么要把寄存器切成"调用者保存"与"被调用者保存"两组，也决定了函数稍微复杂一点就得把值溢出（spill）到 [栈帧](/docs/CS/assembly/Stack_Frame.md)。

本页讲两件事：x86-64 的寄存器文件全景与子寄存器访问规则，以及"操作数可以放在哪里"——也就是寻址方式。指令语义见 [指令集与常用指令](/docs/CS/assembly/Instruction_Set.md)。

## General Purpose Registers

| 寄存器 | 64 位 | 低 32 位 | 低 16 位 | 低 8 位 | ABI 角色（SysV） |
|--------|-------|---------|---------|--------|-----------------|
| 累加器 | `rax` | `eax` | `ax` | `al` | 返回值；`syscall` 调用号；`mul`/`div` 隐式操作数 |
| 基址 | `rbx` | `ebx` | `bx` | `bl` | **被调用者保存** |
| 计数 | `rcx` | `ecx` | `cx` | `cl` | 第 4 个传参；`syscall` 会破坏它 |
| 数据 | `rdx` | `edx` | `dx` | `dl` | 第 3 个传参；返回值的第 2 个 64 位；`mul`/`div` 隐式操作数 |
| 源索引 | `rsi` | `esi` | `si` | `sil` | 第 2 个传参；串操作源地址 |
| 目标索引 | `rdi` | `edi` | `di` | `dil` | 第 1 个传参；串操作目标地址 |
| 基址指针 | `rbp` | `ebp` | `bp` | `bpl` | **被调用者保存**；传统帧指针（`-O` 下常被释放为普通寄存器） |
| 栈指针 | `rsp` | `esp` | `sp` | `spl` | 栈顶，不可随意改动 |
| r8~r15 | `r8`…`r15` | `r8d`… | `r8w`… | `r8b`… | r8/r9 是第 5/6 个传参；**r12~r15 被调用者保存** |

几个只有踩过才记得的细节：

- **`r8`~`r15` 是 x86-64 新增的**，靠 REX 前缀编码。它们的子寄存器命名也跟着改：`r8d`（32 位）、`r8w`（16 位）、`r8b`（8 位）——不是 `r8l`。
- **`sil`/`dil`/`bpl`/`spl` 需要 REX 前缀**：低 8 位访问在 32 位时代只有 `al/cl/dl/bl`，扩展到 `sil/dil/bpl/spl` 后必须带 REX，否则汇编器报错或解释成别的寄存器。
- **没有 `ah`/`bh`/`ch`/`dh` 的 r8~r15 对应物**：高 8 位寄存器只存在于 rax/rbx/rcx/rdx，而且**不能与 REX 前缀同时使用**——一旦指令里出现新寄存器（`r8` 之类），就不能用 `ah`。

## Sub-Register Write Semantics

这是 x86-64 最反直觉的一条规则：

```asm
mov eax, 1        ; 写 32 位 → rax 的高 32 位被自动清零
mov ax, 1         ; 写 16 位 → 只改低 16 位，高 48 位保持不变
mov al, 1         ; 写 8 位  → 只改低 8 位，高 56 位保持不变
```

**32 位写清零高半，8/16 位写不清零。** 这不是无关紧要的实现细节：

- 编译器大量利用这条规则。`mov eax, 1` 是"把 rax 置 1"的最短编码（5 字节），比 `mov rax, 1`（7 字节立即数）还短；C 里的 `(unsigned char)x` 在汇编里常常表现为一次 8 位写，高位残留是上层必须自己处理的事。
- 手写汇编里混用 8 位和 64 位访问同一个寄存器，会读到意料之外的残留高位，也可能触发部分寄存器停顿（partial register stall，现代微架构大多已用重命名消除，但依赖链仍然存在）。

## Special Registers

| 寄存器 | 用途 | 用户态可访问 |
|--------|------|-------------|
| `rip` | 指令指针。**不能当通用寄存器用**，只能通过 RIP 相对寻址读取"当前位置" | 读（相对寻址） |
| `rflags` | 状态标志（CF/ZF/SF/OF/PF/AF）+ 控制标志（DF、IF 内核态） | 部分（`pushf`/`lahf`） |
| `xmm0`~`xmm15` | SSE 向量寄存器，128 位；`ymm` 是低 256 位视图，`zmm` 是 512 位 | 是 |
| `mxcsr` | 浮点控制/状态（舍入模式、异常标志） | 是（`ldmxcsr`/`stmxcsr`） |
| `st0`~`st7` | x87 浮点栈，历史遗留，现代代码基本不用 | 是 |
| `fs` / `gs` | 段寄存器，被 OS 用来指向 TLS / CPU 局部数据；`fs` 在 Linux 上是 TLS 基址，`gs` 在内核里指 per-cpu | 是（经 OS 设定） |
| `cr0`/`cr3`/`cr4` | 控制寄存器（分页开关、页表基址） | **否**，Ring 0 |
| `msr` 系列 | 模型特定寄存器（`rdmsr`/`wrmsr`） | **否** |

`rip` 相对寻址是现代 x86 代码里最常见的访存形式，它也是位置无关代码的基础（见 [汇编器与工具链](/docs/CS/assembly/Assembler_and_Toolchain.md)）：

```asm
mov rax, [rel msg]     ; NASM：把 msg 处的 8 字节读进 rax
lea rdi, [rel msg]     ; 取 msg 的地址本身
```

## Addressing Modes

x86 一个内存操作数可以写成"基址 + 变址×比例 + 位移"，全部字段可选：

```asm
mov rax, [rbx]                 ; 寄存器间接
mov rax, [rbx + 8]             ; 基址 + 位移
mov rax, [rbx + rcx*4]         ; 基址 + 变址×4
mov rax, [rbx + rcx*8 + 0x10]  ; 基址 + 变址×8 + 位移
mov rax, [rel global_var]      ; RIP 相对
mov rax, [0x400000]            ; 绝对地址（32 位模式下常见，64 位下罕见）
```

比例只能是 1/2/4/8，位移是 32 位有符号。这套寻址让"数组元素访问"一条指令搞定：`[base + index*8]` 就是 `long[]` 的第 index 项——这是 [数据通路](/docs/CS/CO/datapath.md) 里 ModRM/SIB 字节解码出来的能力，也是 x86 相比 load/store 架构的最大语法便利。

对应到 AT&T 语法是 `disp(base, index, scale)`，即 `0x10(%rbx,%rcx,8)`。

**`lea` 不是访存指令**。`lea` 计算有效地址但**不访问内存**，因此被大量用作算术：

```asm
lea rax, [rdi + rdi*4]    ; rax = rdi * 5，一条指令，不碰内存、不影响标志位
lea rax, [rdi + rsi + 1]  ; 三操作数加法，比 add 少一次 mov
```

`lea` 不写标志位是它相对 `add` 的关键优势：在循环里做地址推进时不会破坏尚未消费的条件码。

## Cross-Architecture Register Files

| | x86-64 | AArch64 | RISC-V (RV64) |
|---|---|---|---|
| 通用寄存器 | 16 个 × 64 位 | 31 个 × 64 位（`x0`~`x30`） | 31 个 × XLEN（`x0`~`x31`） |
| 零寄存器 | 无 | `xzr`/`wzr`（读恒为 0） | `x0`（读恒为 0） |
| 栈指针 | `rsp`（普通寄存器，可参与寻址） | `sp`（有对齐与用途限制） | `x2`（`sp`，只是 ABI 约定） |
| 返回地址 | 由 `call` 压栈 | `x30`（`lr`，寄存器保存） | `x1`（`ra`，寄存器保存） |
| 程序计数器 | `rip`（不可直接读写） | `pc`（不可直接写） | `pc`（不可直接读写） |
| 传参 | `rdi,rsi,rdx,rcx,r8,r9` | `x0`~`x7` | `a0`~`a7`（即 `x10`~`x17`） |
| 返回 | `rax`（+`rdx`） | `x0`（+`x1`） | `a0`/`a1` |
| 访存 | 运算可直接读内存操作数 | **load/store 架构**，只有 `ldr`/`str` 碰内存 | **load/store 架构** |
| 寻址 | 基址+变址×比例+位移 | 基址+偏移、带扩展的寄存器偏移 | 只有基址+12 位偏移 |

差别最大的是两处：**RISC 侧有零寄存器**（`x0` 恒为 0，于是"取负""清零""取立即数"都能复用同一条指令），以及 **RISC 侧访存与运算分离**（`add rax, [rbx]` 在 x86 合法，在 RISC-V 必须先 `ld` 再 `add`）。这两点决定了 RISC 汇编看起来指令条数更多、但每条更简单，也决定了 [流水线](/docs/CS/CO/pipeline.md) 里访存级的位置。

## Links

- [汇编（枢纽）](/docs/CS/assembly/assembly.md)
- [指令集与常用指令](/docs/CS/assembly/Instruction_Set.md)
- [调用约定与 ABI](/docs/CS/assembly/Calling_Convention.md)
- [栈帧与函数调用](/docs/CS/assembly/Stack_Frame.md)
- [指令集架构（ISA）](/docs/CS/CO/isa.md)
- [RISC-V](/docs/CS/CO/RISC-V.md)

## References

1. [System V AMD64 psABI（版本 1.0）](https://gitlab.com/x86-psABIs/x86-64-ABI)
2. [x86-64 psABI 1.0 PDF](https://github.com/hjl-tools/x86-psABI/wiki/x86-64-psABI-1.0.pdf)
3. [Intel 64 and IA-32 Architectures Software Developer Manuals](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
4. [ARM — Procedure Call Standard for the Arm 64-bit Architecture (AAPCS64)](https://github.com/ARM-software/abi-aa)
5. [RISC-V ELF psABI](https://github.com/riscv-non-isa/riscv-elf-psabi-doc)
