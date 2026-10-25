## Introduction

汇编的"编译"过程比高级语言短得多：汇编器只做符号解析与编码，没有类型检查、没有优化、没有语义分析。这条链的每一环都对应一个可见的中间产物，因此也特别适合**逐环节对照验证**——这是学汇编最有效的手段。

本页讲工具链本身：有哪些汇编器、源码怎么变成可执行文件、以及怎么把可执行文件变回可读的汇编。目标文件格式的完整结构见 [ELF](/docs/CS/Compiler/ELF.md)，语法方言见 [语法与伪指令](/docs/CS/assembly/Syntax_and_Directives.md)。

## The Pipeline

```text
foo.c ──gcc -S──▶ foo.s ──as──▶ foo.o ──ld──▶ a.out
        编译器       汇编器      目标文件    链接器
                     ▲
foo.asm ─────────────┘（手写汇编从 .s 这一步接入）
```

四个常用动作：

```bash
gcc -O2 -S foo.c                 # 只编译到汇编，看编译器生成了什么
gcc -O2 -S -fverbose-asm foo.c   # 附带源变量名注释，最有用的一种
as foo.s -o foo.o                # 汇编（现代用法通常直接 gcc）
gcc -c foo.s -o foo.o            # 走 gcc 驱动，自动处理架构与选项
ld -o prog foo.o                 # 链接（不带 libc）
```

看编译器输出的两个进阶开关：`-fno-asynchronous-unwind-tables` 能去掉 `.eh_frame` 噪音让输出清爽；`-masm=intel` 让 GCC 直接输出 Intel 语法（省去读 AT&T 的麻烦）。

> [!NOTE]
> 工具版本实测：NASM **3.02**（2026-06-29）、GNU binutils **2.47**（2026-07-26）、GCC **16.2**（2026-08-07）。binutils 官网首页当时仍标注 2.46，落后一个版本——以 `as --version` / `objdump --version` 的实际输出为准。

## Assemblers

| 汇编器 | 支持架构 | 输出格式 | 什么时候选它 |
|--------|---------|---------|-------------|
| **GAS**（`as`，binutils 2.47） | 几乎所有（x86/ARM/RISC-V/Power/MIPS…） | ELF、COFF、Mach-O 等 | GCC/Clang 的默认后端；多架构项目、内联汇编 |
| **NASM** 3.02 | x86 / x86-64（可交叉） | ELF32/64、COFF、Mach-O、Win32/64、裸 `bin` | 教学、bootloader（裸二进制输出方便）、需要干净 Intel 语法时 |
| **MASM**（`ml.exe` / `ml64.exe`） | x86 / x64 | COFF | Windows 平台，随 Visual Studio 分发；与 MSVC 工具链一体 |
| **FASM** | x86 / x86-64 | 多种，可自举 | 自汇编、追求轻量 |
| **Yasm** | x86 | 同 NASM | NASM 的重写分支，兼容 NASM 语法，也支持 GAS 语法 |
| **Go asm** | 多架构 | Go 自有 | Go 标准库与运行时；Plan 9 语法，且经 Go 的虚拟寄存器映射 |

选择标准其实只有两条：**跟着你的工具链**（用 GCC/Clang 就 GAS，用 MSVC 就 MASM），以及**是否需要非 ELF 输出**（写引导扇区要裸 `bin`，NASM 最省事）。

## Object Files and Relocations

汇编器输出的 `.o` 里没有"地址"，只有**符号引用 + 重定位条目**：`call printf` 在 `.o` 里是 `call 0x0` 加一条"在偏移 X 处填入 printf 的地址"的重定位记录，真正的填值在链接期完成。这就是为什么 `objdump -d foo.o` 里看到的调用目标全是 0。

section 的划分决定了链接后的布局与权限：

| section | 内容 | 权限 |
|---------|------|------|
| `.text` | 指令 | 可读可执行 |
| `.rodata` | 只读数据（字符串常量、`const` 数组） | 只读 |
| `.data` | 已初始化的可写全局变量 | 可读可写 |
| `.bss` | 未初始化全局变量（只记长度，不占文件空间） | 可读可写 |
| `.eh_frame` | 栈回溯 / 异常展开信息 | 只读 |

完整格式（ELF 头、程序头、节头、动态段）见 [ELF](/docs/CS/Compiler/ELF.md)。

## Disassembly and Inspection

```bash
objdump -d prog                  # 反汇编可执行段（默认 AT&T 语法）
objdump -d -M intel prog         # Intel 语法，推荐
objdump -S prog                  # 源码与汇编交错（编译时带 -g）
objdump -t prog                  # 符号表
objdump -R prog                  # 动态重定位
readelf -hS prog                 # ELF 头与 section 列表
nm -C prog                       # 符号（C++ 名字还原）
```

默认语法是 AT&T 这一条值得再强调一次：读反汇编时操作数方向搞反，会得出完全相反的结论。

GDB 里的指令级调试：

```text
(gdb) disassemble /m main        # 带源码行号反汇编
(gdb) layout asm                 # TUI 模式，跟着执行走
(gdb) stepi                      # 单步一条机器指令（si）
(gdb) nexti                      # 单步一条指令，跳过 call
(gdb) x/i $pc                    # 看当前指令
(gdb) info registers             # 全部寄存器
(gdb) x/16gx $rsp                # 看栈顶 16 个八字节
(gdb) print/x *(long*)$rax       # 按寄存器地址读内存
```

NASM 自带 `ndisasm`，用于反汇编**裸二进制**（比如引导扇区，没有 ELF 头可依）：

```bash
ndisasm -b 64 boot.bin | head
```

## Position-Independent Code

动态库要能加载到任意地址，所以它的代码不能含绝对地址。现代 x86-64 的默认方案（`-fPIE`，主流发行版已默认开启）依赖两件事：

- **RIP 相对寻址**访问本模块的数据：`mov rax, [rel my_var]` 的偏移在链接期就确定，加载时无需改写；
- **GOT / PLT** 访问外部符号：全局变量走 GOT（Global Offset Table，加载时由动态链接器填真实地址），函数调用走 PLT（Procedure Linkage Table，首次调用触发惰性绑定）。

```asm
; -fPIE 下访问全局变量：先从 GOT 取地址
mov rax, [rel my_var@GOTPCREL]   ; rax = &my_var
mov eax, [rax]                   ; 再取值
```

手写汇编在 PIE 环境里最常见的错误是直接写绝对地址（`mov rax, my_var`），链接器会报 "relocation R_X86_64_32S against ... can not be used when making a PIE object"。修法就是改成 RIP 相对 + GOT。ELF 侧的重定位类型与 GOT/PLT 结构见 [ELF](/docs/CS/Compiler/ELF.md)。

## Verification Workflow

写汇编（尤其是内联汇编或手写优化）时最可靠的验证顺序：

1. **看编译器怎么做**：把等价逻辑写成 C，`gcc -O2 -S -fverbose-asm` 看它生成什么。你的手写版本应该有明确理由比它更好。
2. **确认指令真的被生成**：`objdump -d -M intel` 检查目标文件，特别注意内联 asm 有没有被删除或外提。
3. **确认编码与预期一致**：`objdump` 输出的字节序列对照 Intel 手册的编码表（这一步在排查"为什么汇编器选了另一条指令"时很有用）。
4. **单步验证**：GDB 里 `stepi` 逐条走，边走边看 `info registers`。
5. **测并发与边界**：并发相关的要跑 `-O2` 且多线程反复验证，不能只看 `-O0`。

## Links

- [汇编（枢纽）](/docs/CS/assembly/assembly.md)
- [语法与伪指令](/docs/CS/assembly/Syntax_and_Directives.md)
- [ELF 与目标文件格式](/docs/CS/Compiler/ELF.md)
- [GCC](/docs/CS/Compiler/GCC.md)
- [GDB](/docs/CS/C/GDB.md)
- [惯用法与优化](/docs/CS/assembly/Optimization_and_Idioms.md)

## References

1. [NASM — The Netwide Assembler](https://nasm.us/)
2. [NASM Documentation](https://nasm.us/docs.html)
3. [GNU Binutils — Using as（GAS 手册）](https://sourceware.org/binutils/docs/as/)
4. [GNU Binutils — objdump 手册](https://sourceware.org/binutils/docs/binutils/objdump.html)
5. [GCC — 编译选项总览](https://gcc.gnu.org/onlinedocs/gcc/Option-Summary.html)
6. [Compiler Explorer（在线对照编译器汇编输出）](https://godbolt.org/)
