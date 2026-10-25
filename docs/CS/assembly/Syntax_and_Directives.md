## Introduction

汇编语言没有标准化组织：ISA 由芯片厂商定，而**汇编语法由汇编器实现定**。同一条 x86-64 的 `mov rax, 1`，Intel 语法和 AT&T 语法写出来是两行几乎不相关的文本；同一段逻辑从 GAS 搬到 NASM，伪指令要整段重写。所以学汇编的第一步不是背指令，而是**先确认你在用哪个汇编器、哪种语法**。

本页讲三件事：语句的基本结构、x86 的两大语法流派与三大汇编器方言、以及不产生机器指令的**伪指令**（directive）。指令本身的语义见 [指令集与常用指令](/docs/CS/assembly/Instruction_Set.md)，寄存器命名规则见 [寄存器与寻址方式](/docs/CS/assembly/Registers_and_Addressing.md)。

## Statement Structure

一行汇编的典型结构是四个可选字段：

```asm
label:    mnemonic   operand1, operand2    ; comment
```

- **label**：符号名，汇编器把它解析成一个地址。跳转目标、数据符号都靠它。GAS 里以 `.L` 开头的 label 是局部符号，不会进目标文件符号表；NASM 里以 `.` 开头的是局部 label，归属于上一个全局 label。
- **mnemonic**：助记符，可以是指令（`mov`、`lea`、`syscall`）或伪指令（`section`、`dq`、`align`）。
- **operand**：0~3 个。立即数、寄存器、内存操作数都可以，但**不是任意组合都合法**——`mov` 的两个操作数不能同时是内存，这是 x86 的硬约束。
- **comment**：GAS 用 `#`（也支持 `//` 与 `/* */`），NASM 与 MASM 用 `;`。

## Intel versus AT&T

x86 有两套语法，差异是系统性的：

| 维度 | Intel（NASM / MASM / Intel 手册） | AT&T（GAS 默认 / objdump 默认） |
|------|----------------------------------|----------------------------------|
| 操作数顺序 | `mnemonic dst, src`（目标在前） | `mnemonic src, dst`（源在前） |
| 寄存器 | `rax` | `%rax` |
| 立即数 | `42` | `$42` |
| 内存引用 | `[rax + rbx*4 + 8]` | `8(%rax,%rbx,4)` |
| 取立即地址 | `mov rax, qword [msg]` | `movq $msg, %rax`（无括号即地址） |
| 宽度标记 | 靠寄存器名或 `qword/dword/byte` 前缀 | 靠指令后缀 `b/w/l/q`（`movq`、`movl`） |
| 跳转/调用 | `call rax`、`jmp 0x1234` | `call *%rax`、`jmp *0x1234`（间接跳转要 `*`） |
| 典型出处 | NASM、MASM、Intel/AMD 手册、IDA | GCC 内联汇编、GAS `.s`、`objdump` 默认输出 |

同一个"把 1 写进 rax"：

```asm
; Intel / NASM
mov rax, 1
```

```asm
# AT&T / GAS
movq $1, %rax
```

三个高频踩坑：

1. **操作数方向反了**。`mov %rax, %rbx` 在 AT&T 里是把 rax 送进 rbx，看起来像 Intel 的 `mov rbx, rax`；写反了不报错，只是结果错。
2. **忘记 `*`**。AT&T 下 `call *%rax` 才是间接调用，漏掉 `*` 会变成以 rax 值为偏移的直接跳转。
3. **`objdump` 默认是 AT&T**。看反汇编时要么加 `-M intel`，要么接受 AT&T 的读法，混着读一定会出错。

GAS 可以在文件里切语法：

```asm
.intel_syntax noprefix    # 之后用 Intel 语法，寄存器不加 %
    mov rax, 1
.att_syntax               # 切回 AT&T
```

注意 `.intel_syntax noprefix` 只改**指令语法**，伪指令仍然是 GAS 那一套（`.section` 而不是 `section`）。

## Assembler Dialects

| 汇编器 | 平台 / 输出格式 | 语法 | 定位与特点 |
|--------|----------------|------|-----------|
| **GAS**（`as`，binutils） | 跨架构；ELF / COFF / Mach-O | AT&T 默认，可切 Intel | GCC/Clang 的后端汇编器，多架构统一前端，伪指令以 `.` 开头 |
| **NASM** | x86；ELF / COFF / Mach-O / 裸 bin | Intel | 独立汇编器，语法干净，裸二进制输出方便写 bootloader；自带反汇编器 `ndisasm` |
| **MASM / ML64** | Windows；COFF | Intel | 微软官方，随 Visual Studio 分发；MASM 32 位用 `ml.exe`，x64 用 `ml64.exe`；宏与结构体能力强 |
| **FASM** | x86；自举 | Intel | 自汇编，语法偏简洁，宏能力强 |
| **Go asm** | Go 工具链 | Plan 9 风格 | 与上面都不同：寄存器名、操作数顺序、伪指令全是 Plan 9 血统，且要经过 Go 的虚拟寄存器映射 |

跨方言移植不是文本替换，是重写。以 `.text` 段的定义为例：

```asm
# GAS
.text
.globl  main
.type   main, @function
main:
    ret
```

```asm
; NASM
section .text
global main
main:
    ret
```

```asm
; MASM (ml64)
.code
main PROC
    ret
main ENDP
END
```

## Directives

伪指令不生成机器码，指挥汇编器怎么摆放数据、怎么声明符号、怎么对齐。按用途分成几类：

**段与符号**

| 用途 | GAS | NASM |
|------|-----|------|
| 切代码段 | `.text` | `section .text` |
| 切数据段 | `.data` / `.rodata` / `.bss` | `section .data` / `.rodata` / `.bss` |
| 导出符号 | `.globl name` | `global name` |
| 引用外部符号 | 无需声明（链接期解析） | `extern printf` |
| 符号类型 | `.type name, @function` / `@object` | 无（靠 target 格式） |
| 符号尺寸 | `.size name, .-name` | 无 |

**数据定义**

| 宽度 | GAS | NASM |
|------|-----|------|
| 1 字节 | `.byte 0x41` | `db 0x41` |
| 2 字节 | `.word 1` | `dw 1` |
| 4 字节 | `.long 1` / `.int` | `dd 1` |
| 8 字节 | `.quad 1` | `dq 1` |
| 字符串 | `.ascii "hi"` / `.asciz "hi"`（带 NUL） | `db "hi", 0` |
| 预留空间 | `.space 64` / `.zero 64` | `resb 64` |
| 常量 | `.equ N, 10` | `N equ 10` |

**对齐与填充**：GAS 用 `.align 16` 或 `.p2align 4`（`.p2align` 的参数是 2 的幂次，语义更明确，推荐用后者）；NASM 用 `align 16`。GAS 还有 `.balign`（按字节对齐）。对齐对性能与正确性都有影响：未对齐的 `movaps`（要求 16 字节对齐的 SSE 传送）会直接 `#GP` 崩。

**重复与填充**：NASM 的 `times` 很方便（`times 512 db 0`），GAS 用 `.rept ... .endr` 或 `.fill 512, 1, 0`。

**条件与宏**：NASM 有 `%macro`/`%endmacro`、`%if`/`%endif`、`%include`；GAS 有 `.macro`/`.endm`、`.irp`、`.include`；MASM 的 `MACRO`/`ENDM` 最完备。宏在手写汇编里的典型用途是把 prologue/epilogue 或系统调用序列参数化。

## Macros and Conditional Assembly

NASM 的宏写法：

```asm
%macro SYSCALL3 4      ; 宏名 参数个数，%1=调用号 %2..%4=三个参数
    mov rax, %1
    mov rdi, %2
    mov rsi, %3
    mov rdx, %4
    syscall
%endmacro

    SYSCALL3 1, 1, msg, len    ; write(1, msg, len)
```

GAS 的对应写法：

```asm
.macro SYSCALL3 num, a1, a2, a3
    mov $\num, %rax
    mov $\a1, %rdi
    mov $\a2, %rsi
    mov $\a3, %rdx
    syscall
.endm
```

宏展开是纯文本替换，**不做类型检查**。写宏时给参数加括号、`\macro` 参数引用加 `\` 前缀（GAS）是防止拼接错误的习惯。

## Common Pitfalls

- **NASM 要求显式的内存宽度**：`mov [rax], 1` 在 NASM 里报错（不确定是写 1 字节还是 8 字节），必须写 `mov qword [rax], 1`。GAS 在操作数能推断时宽容，但 `movl $1, (%rax)` 这种带后缀的写法更稳。
- **AT&T 的 `$` 是立即数，不是取地址**：`movq $msg, %rax` 取的是符号地址常量，`movq msg, %rax` 是从内存加载。少一个 `$` 语义完全变了。
- **`endbr64` 在 CET 环境下是必需的**：启用了 Intel CET（Control-flow Enforcement Technology）的函数入口必须是 `endbr64`（编码 `F3 0F 1E FA`），否则间接跳转会被终结。它在不支持 CET 的 CPU 上是无害的 `nop`，所以现代工具链默认在函数入口都插一条。手写一个要被函数指针调用的汇编函数，别忘了它。
- **局部 label 的作用域容易搞错**：NASM 的 `.loop` 属于上一个非局部 label，写两个同名 `.loop` 在不同全局 label 下是合法的；跨文件同名全局符号则会链接冲突。
- **`.` 在 GAS 里是"当前地址"**：`.size func, .-func` 就是靠它算出函数长度。在别处误用 `.` 会得到令人困惑的偏移。

## Links

- [汇编（枢纽）](/docs/CS/assembly/assembly.md)
- [指令集与常用指令](/docs/CS/assembly/Instruction_Set.md)
- [寄存器与寻址方式](/docs/CS/assembly/Registers_and_Addressing.md)
- [汇编器与工具链](/docs/CS/assembly/Assembler_and_Toolchain.md)
- [指令集架构（ISA）](/docs/CS/CO/isa.md)

## References

1. [NASM Documentation](https://nasm.us/docs.html)
2. [GNU Binutils — Using as（GAS 手册）](https://sourceware.org/binutils/docs/as/)
3. [Microsoft MASM Reference](https://learn.microsoft.com/en-us/cpp/assembler/masm/microsoft-macro-assembler-reference)
4. [Intel 64 and IA-32 Architectures Software Developer Manuals](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
5. [Intel CET — Control-flow Enforcement Technology](https://www.intel.com/content/www/us/en/developer/articles/technical/technical-look-control-flow-enforcement-technology.html)
