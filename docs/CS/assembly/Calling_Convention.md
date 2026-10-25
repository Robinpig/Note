## Introduction

**调用约定**（calling convention）是编译器之间、语言之间、甚至编译器与手写汇编之间的契约：参数放哪些寄存器、返回值放哪、栈怎么对齐、调用者和被调用者各自负责保存哪些寄存器。它**不属于硬件**——`call` 指令只管压返回地址，其余全是约定——但一旦违反，代码能编译、能跑，却会在某个优化级别或某个调用点莫名其妙地坏掉。这是手写汇编与 [内联汇编](/docs/CS/assembly/Inline_Assembly.md) 的头号事故源，也是跨语言 FFI 出问题的重灾区。

本页以 x86-64 的两套 ABI（System V 与 Win64）为主线，附 AArch64 与 RISC-V 对照。栈帧的构造细节见 [栈帧与函数调用](/docs/CS/assembly/Stack_Frame.md)，寄存器命名见 [寄存器与寻址方式](/docs/CS/assembly/Registers_and_Addressing.md)。

## x86-64 System V ABI

Linux、macOS、BSD、以及除 Windows 外的几乎所有类 Unix 都用这一套（规范是 **psABI 1.0**，内容在 GitLab 上滚动更新，"1.0" 是版本号而非冻结稿）。

**整型参数**按顺序进 `rdi, rsi, rdx, rcx, r8, r9`，**浮点参数**按序进 `xmm0`~`xmm7`；超过 6 个整型参数的部分走栈（从右往左压）。返回值在 `rax`（第二个 64 位在 `rdx`），浮点返回在 `xmm0`/`xmm1`，`long double` 走 x87 的 `st0`。

寄存器职责划分：

| 类别 | 寄存器 | 谁负责 |
|------|--------|--------|
| 调用者保存（caller-saved / volatile） | `rax, rcx, rdx, rsi, rdi, r8`~`r11`，全部 `xmm0`~`xmm15`，标志位 | 调用者要在 `call` 前自行备份还想用的值 |
| 被调用者保存（callee-saved / non-volatile） | `rbx, rbp, r12`~`r15`，`rsp` | 被调函数若要用，必须先 `push` 并在返回前 `pop` |
| 保留 | `rsp` | 返回时必须与进入时一致，否则 `ret` 拿到错的返回地址 |

> [!NOTE]
> SysV 下**没有任何 callee-saved 的向量寄存器**——所有 `xmm` 都是易失的。Win64 则保留了 `xmm6`~`xmm15`。这一条差异是移植汇编时最容易漏掉、后果最难查的：在 SysV 下写了汇编函数、把值留在 `xmm6` 里跨调用使用，调用者那边的值已经被冲掉了。

**栈对齐**：执行 `call` 指令的那一刻，`rsp` 必须 16 字节对齐。由于 `call` 会压入 8 字节返回地址，进入被调函数时 `rsp ≡ 8 (mod 16)`。所以函数入口若要用要求 16 字节对齐的 SSE 指令（`movaps`、`movdqa`），必须先再减一个 8 的奇数倍：`sub rsp, 8 + 16*N`。

**Red zone**：`rsp` 之下 128 字节（即 `[rsp-128, rsp)`）是**叶子函数**（不再调用其他函数的函数）的自由区域，可以直接用来放局部变量而**不需要 `sub rsp`**。规范同时要求信号处理器和中断处理器不得修改这块区域，所以它是安全的。

```asm
; SysV 叶子函数，直接用 red zone，不动 rsp
strlen:
    xor rax, rax
.loop:
    cmp byte [rdi + rax], 0
    je  .done
    inc rax
    jmp .loop
.done:
    ret                    ; 没有 prologue/epilogue
```

两个 red zone 的禁区：

- **内核代码不能用**。内核栈上随时可能来中断，中断入口会往栈上压 pt_regs，red zone 一定被踩。Linux 内核编译时因此带 `-mno-red-zone`。
- **被调用者是叶子函数这条要自己确认**。函数里只要有一条 `call`，它就不再是叶子函数，用 red zone 的数据会被被调函数的栈帧覆盖。

## Windows x64 ABI

Windows 自有一套（`rcx, rdx, r8, r9` 四个寄存器传参）：

| 维度 | System V | Windows x64 |
|------|----------|-------------|
| 整型传参 | `rdi, rsi, rdx, rcx, r8, r9` | `rcx, rdx, r8, r9` |
| 浮点传参 | `xmm0`~`xmm7` | `xmm0`~`xmm3` |
| 返回值 | `rax`（+`rdx`）、`xmm0` | `rax`、`xmm0` |
| 调用者保存 | `rax, rcx, rdx, rsi, rdi, r8`~`r11`，全部 xmm | `rax, rcx, rdx, r8`~`r11`，`xmm0`~`xmm5` |
| 被调用者保存 | `rbx, rbp, r12`~`r15` | `rbx, rbp, rsi, rdi, r12`~`r15`，`xmm6`~`xmm15` |
| Shadow space | 无 | **有**：调用者必须在栈上预留 32 字节 |
| Red zone | 128 字节 | **无** |
| 栈对齐 | `call` 时 16 字节 | `call` 时 16 字节 |
| 超过 4 个参数 | 走栈 | 走栈，前 4 个仍要留 shadow space |

**Shadow space（home space）**是 Win64 的特色：调用者在 `call` 之前必须留出 32 字节（4 个 8 字节槽），被调函数可以把前 4 个寄存器参数 spill 到这里——这让调试器和变参函数（如 `printf`）能统一处理参数。手写汇编调 Windows API 时忘了它，栈就错位了。

## Passing and Returning Aggregates

结构体怎么传，规则比"放寄存器"复杂。SysV 的做法是**分类**：把对象按 8 字节（eightbyte）切开，每块判定为 INTEGER / SSE / MEMORY 之一。

- 大小 ≤ 16 字节且每块都可归入寄存器类 → 用寄存器传（一个 eightbyte 一个寄存器，可能是 GPR 也可能是 XMM）；
- 含有非平凡构造/析构的 C++ 对象、大小 > 16 字节、或含未对齐字段 → 归为 **MEMORY**，在栈上传整个副本；
- 返回值 > 16 字节 → 调用者在栈上（或自己分配的内存里）准备空间，把地址作为**隐藏的第一个参数**放进 `rdi`（Win64 是 `rcx`），函数返回时 `rax` 带回这个指针。

这解释了为什么 C 里返回大结构体的开销被低估：它不是"返回"，而是"调用者分配 + 被调用者写入"，寄存器参数序号还整体后移了一位。

**可变参数函数**额外要求：调用者要把实际用到的向量寄存器个数放进 `al`（0~8）。手写汇编调 `printf` 家族时若 `al` 没设对，可变参数读取就会错位——这也是纯汇编里调用 `printf` 需要先 `xor eax, eax` 的原因（`xor eax, eax` 同时把 `al` 置 0）。

## Cross-Architecture Conventions

| | x86-64 SysV | AArch64 (AAPCS64) | RISC-V (RV64) |
|---|---|---|---|
| 整型传参 | `rdi,rsi,rdx,rcx,r8,r9` | `x0`~`x7` | `a0`~`a7`（`x10`~`x17`） |
| 浮点传参 | `xmm0`~`xmm7` | `v0`~`v7` | `fa0`~`fa7` |
| 返回值 | `rax`/`rdx`，`xmm0` | `x0`（+`x1`），`v0` | `a0`/`a1` |
| 大结构返回 | 隐藏指针进 `rdi`，`rax` 回传 | 隐藏指针进 `x8`（间接结果寄存器），`x0` 回传 | 隐藏指针进 `a0`（其余参数后移） |
| 被调用者保存 | `rbx,rbp,r12`~`r15` | `x19`~`x28`，`v8`~`v15`，`sp` | `s0`~`s11`（`x8,x9,x18`~`x27`），`sp` |
| 调用者保存 | 其余 + 全部 xmm | `x0`~`x18`，`v0`~`v7`，`x30`(lr) | `ra`，`t0`~`t6`，`a0`~`a7` |
| 返回地址 | 栈上（由 `call` 压入） | 寄存器 `x30`（lr） | 寄存器 `x1`（ra） |
| 栈对齐 | 16 字节 | 16 字节 | 16 字节 |
| Red zone | 128 字节 | 无 | 无 |
| 保留寄存器 | — | `x18`（platform reg） | `gp`（`x3`）、`tp`（`x4`） |

**返回地址保存在寄存器里**（AArch64 的 `x30`、RISC-V 的 `ra`）是 RISC 侧的显著差异：函数只要还要再调用别人，就必须自己把 `lr`/`ra` 压栈保存（即"非叶子函数"的 prologue 必然包含一次 `str x30, [sp, #-N]!`）。x86 把这个动作做进了 `call`/`ret` 硬件，代价是返回地址进了内存、成了栈溢出攻击的目标（现代缓解手段是 shadow stack 与 CET）。

## Common Bugs

手写汇编调 C、或者 C 调手写汇编时，下面几条占了绝大多数故障：

1. **忘记保存 callee-saved 寄存器**。汇编函数里用了 `rbx` 却没 `push/pop`，返回后调用者的 `rbx` 已变——症状是"某个无关变量莫名被改"，且只在开启优化时出现（不优化时调用者可能没把值留在 `rbx`）。
2. **栈没对齐就调 `movaps`/SSE 指令**，或 `call` 前 `rsp` 不是 16 的倍数。症状是偶发段错误，且只在特定调用路径出现。
3. **Win64 下忘留 shadow space**，或者 SysV 下误以为有 shadow space。
4. **把返回值写进错的寄存器**——`float` 返回要写 `xmm0` 而不是 `rax`。
5. **可变参数调用没设 `al`**。
6. **在内核/中断上下文用 red zone**。
7. **C++ 异常穿过手写汇编帧**：没有 unwind 信息（`.cfi_*` 或 `.eh_frame`）时，异常传播会直接终止进程。

## Links

- [汇编（枢纽）](/docs/CS/assembly/assembly.md)
- [栈帧与函数调用](/docs/CS/assembly/Stack_Frame.md)
- [寄存器与寻址方式](/docs/CS/assembly/Registers_and_Addressing.md)
- [内联汇编](/docs/CS/assembly/Inline_Assembly.md)
- [指令集架构（ISA）](/docs/CS/CO/isa.md)

## References

1. [System V AMD64 psABI（版本 1.0）](https://gitlab.com/x86-psABIs/x86-64-ABI)
2. [x86-64 psABI 1.0 PDF](https://github.com/hjl-tools/x86-psABI/wiki/x86-64-psABI-1.0.pdf)
3. [Microsoft — x64 calling convention](https://learn.microsoft.com/en-us/cpp/build/x64-calling-convention)
4. [ARM — Procedure Call Standard for the Arm 64-bit Architecture (AAPCS64)](https://github.com/ARM-software/abi-aa)
5. [RISC-V ELF psABI](https://github.com/riscv-non-isa/riscv-elf-psabi-doc)
6. [Agner Fog — Calling Conventions](https://www.agner.org/optimize/calling_conventions.pdf)
