## Introduction

**栈**是"函数调用"这个概念在内存里的物理形态：它保存返回地址、参数、局部变量，也保存被调函数承诺要恢复的寄存器。因为栈是向下增长的、每次调用压一层，递归才有意义，异常才能逐层回溯，调试器才能打印调用栈。

栈帧（stack frame）是每一次函数调用在栈上占据的那一段。理解它的布局，才知道一段汇编在干什么、崩溃时 `rsp` 和 `rbp` 指向哪里、以及为什么"只改了一行 C"会让栈用量翻倍。调用约定见 [调用约定与 ABI](/docs/CS/assembly/Calling_Convention.md)，指令层面的 `push`/`pop`/`call`/`ret` 见 [指令集与常用指令](/docs/CS/assembly/Instruction_Set.md)。

## Layout

x86-64（System V）下一次调用后的栈从高地址往低地址看是这样：

```text
高地址
+-----------------------------+
| 调用者的栈帧                |
| 第 7、8... 个参数（栈传参） |
| 返回地址（call 压入）       |  ← 函数入口时 rsp 指向这里
+-----------------------------+
| 被调函数的栈帧              |
| 旧的 rbp（push rbp）        |  ← rbp 指向这里
| 被调用者保存的寄存器        |
| 局部变量 / spill slot       |
| 传给下一层调用的参数空间    |  ← rsp 指向这里（若已 sub rsp）
+-----------------------------+
低地址
                              ← rsp-128 以下是 red zone（仅叶子函数）
```

`call` 做两件事：把返回地址压栈（`rsp -= 8`）、跳到目标。`ret` 反向：弹出返回地址并跳回。所以**栈帧的起点是返回地址**，函数里第一件事通常是给自己划出空间。

## Prologue and Epilogue

经典的帧指针式 prologue 与 epilogue：

```asm
; prologue
push  rbp             ; 保存调用者的帧指针
mov   rbp, rsp        ; 建立本帧的帧指针
sub   rsp, 32         ; 给局部变量腾 32 字节

; ... 函数体，局部变量用 [rbp-8]、[rbp-16] 访问 ...

; epilogue（两种等价写法）
mov   rsp, rbp        ; 或 leave
pop   rbp
ret
```

`leave` 就是 `mov rsp, rbp; pop rbp` 的合成指令。

**帧指针不是必需的**。`rbp` 的价值是让每个局部变量有固定偏移、让回溯器能逐帧走（每帧的 `rbp` 指向上一个 `rbp`）。代价是占用一个通用寄存器，而 x86-64 只有 16 个。所以开启优化时 GCC/Clang 默认**省略帧指针**（-fomit-frame-pointer），把 `rbp` 当普通寄存器用，局部变量改用 `rsp` 相对寻址：

```asm
func:
    sub  rsp, 24
    mov  [rsp+8], rbx      ; 局部变量直接用 rsp 相对
    ...
    add  rsp, 24
    ret
```

代价是回溯必须依赖 unwind 信息（见下文）。反过来，性能剖析工具（`perf` 的调用图、火焰图）在省略帧指针时常常采集不全，所以也有发行版为此把默认改回 `-fno-omit-frame-pointer`。

## Stack Alignment

`rsp` 的 16 字节对齐是 ABI 硬要求（见 [调用约定与 ABI](/docs/CS/assembly/Calling_Convention.md)）。在 `rsp` 初值未知的场景（比如手写汇编入口、`main` 之外被系统调用进来的代码），标准做法是：

```asm
and   rsp, -16        ; 把 rsp 向下对齐到 16 字节
```

注意这是**向下**对齐（可能损失几个字节），且之后不能再指望恢复原来的 `rsp`——所以只有不需要返回的入口（如线程入口、进程入口）才这么写。

函数内部给局部变量腾空间时，习惯上一次性减到 16 的倍数：`sub rsp, 16*N + 8`（那个 8 是为了抵消入口时 `rsp ≡ 8 mod 16` 的偏移）。

## Locals, Spills, and Outgoing Arguments

- **局部变量**优先分配在寄存器；寄存器不够（或取了地址、或跨调用还要用）就"溢出"到栈上的 spill slot。
- **传给出站调用的参数**也在本帧里：超过 6 个整型参数的部分要写进 `[rsp+0]`、`[rsp+8]`…… 注意这必须在 `call` 之前写，且此时 `rsp` 已经 `sub` 过——编译器会预留"outgoing argument area"，手写汇编容易在这里算错偏移。
- **取地址迫使变量落栈**：`&local` 会让本来可以常驻寄存器的变量必须有内存表示，这是 C 里常见的"多一个取址操作，性能掉一截"的根源。

## Recursion, Limits, and Protection

递归就是"函数还没返回就再次 `call` 自己"，每层消耗一份栈帧。栈的大小是固定的（Linux 用户态默认 8 MB，可用 `ulimit -s` 查），所以：

- 深度递归、大局部数组（`char buf[1<<20]`）、变长数组（VLA）和 `alloca` 都可能直接把栈用光，表现为**栈溢出段错误**而不是"内存不足"；
- 编译器对已知深度的递归能做尾调用优化（`jmp` 替代 `call` + `ret`），把递归转循环，但只在 `-O2`/`-O3` 且函数结构合适时发生，不能依赖。

栈溢出保护（`-fstack-protector-strong`，主流发行版默认开启）在 prologue 里放一个"金丝雀"（canary），epilogue 检查它是否被改写：

```asm
mov   rax, qword fs:[0x28]    ; 从 TLS 取随机 canary
mov   [rbp-8], rax            ; 放进栈帧底部（局部变量之下）
...
mov   rax, [rbp-8]
xor   rax, qword fs:[0x28]    ; 与 TLS 里的原值比对
je    .ok
call  __stack_chk_fail        ; 被改写 → 立即终止
.ok:
```

这就是缓冲区溢出通常表现为 `*** stack smashing detected ***` 而不是"跑飞"的原因。手写汇编函数**没有** canary，因此也不受这层保护——它是被攻破的常见入口。

## Unwinding and Backtraces

线程崩了怎么还原调用栈？三种机制并存：

| 机制 | 原理 | 代价 | 使用者 |
|------|------|------|--------|
| 帧指针链 | 每帧的 `rbp` 指向上一帧的 `rbp`，顺着链走 | 占用一个寄存器，但回溯 O(1) 每帧 | `-fno-omit-frame-pointer` 的构建；内核也常用 |
| **DWARF CFI**（`.eh_frame` / `.cfi_*` 伪指令） | 一张按 PC 查的表格，记录每个地址上 `rsp` 相对 CFA 的偏移、哪些寄存器存在哪里 | 数据量大，需要解析 | 默认构建、C++ 异常传播、`perf` |
| **SFrame** | 精简的栈回溯格式，专为内核与高频剖析设计，按 PC 查、格式小巧 | 只描述栈回溯，不做异常语义 | 内核与工具链推进中；binutils 2.46 起支持 SFrame v3 |

Linux 内核另有一条路：4.14 起引入 **ORC unwinder**（Oops Rewind Capability）替代内核里的 DWARF 展开表，因为 DWARF 在内核场景下太大且需要解释执行。这也说明一件事：**手写汇编必须自己提供 unwind 信息**，否则异常穿过它时会直接 `std::terminate`，或者回溯器在它这里断链。GAS 的写法是：

```asm
    .cfi_startproc
    push rbp
    .cfi_def_cfa_offset 16
    .cfi_offset 6, -16
    ...
    .cfi_endproc
```

## Kernel versus User Stacks

- **用户栈**在进程地址空间里，可增长（到 `RLIMIT_STACK` 为止），缺页时由内核按需映射。
- **内核栈**每个线程一份，小得多（x86-64 上常见 8 KB 或 16 KB 配置），**不能增长也不能换出**，因此内核代码禁用大局部数组、限制递归、且必须 `-mno-red-zone`（见 [调用约定与 ABI](/docs/CS/assembly/Calling_Convention.md)）。
- **中断/异常**可能打在任意时刻：x86 上如果发生在用户态，CPU 会自动切到内核栈（`tr` 指向的 TSS 提供栈指针）；内核态嵌套中断则使用独立的中断栈（IST）。这些切换动作全是硬件加汇编完成的——[操作系统的进程切换](/docs/CS/OS/process.md)里那句"C 语言表达不出来"说的正是这里。

## Pitfalls in Hand-Written Assembly

1. **`push` 与 `pop` 不配对**，`ret` 拿到的"返回地址"是局部变量的值 → 跳到随机地址。
2. **忘了 `sub rsp` 就往 `[rsp-8]` 写** → 那块内存属于 red zone 或下一层调用，值随时被覆盖。
3. **在循环里 `push` 不 `pop`** → 栈缓慢泄漏，深度循环后溢出。
4. **改动 `rsp` 后用了 `rbp` 相对寻址**（或反之）→ 偏移全错。
5. **忘了对齐**又调了要求对齐的 SSE 指令 → `#GP`。
6. **没有 `.cfi_*`** → C++ 异常或 `perf` 回溯在此断链。

## Links

- [汇编（枢纽）](/docs/CS/assembly/assembly.md)
- [调用约定与 ABI](/docs/CS/assembly/Calling_Convention.md)
- [指令集与常用指令](/docs/CS/assembly/Instruction_Set.md)
- [系统调用](/docs/CS/assembly/System_Calls.md)
- [进程（上下文切换的汇编边界）](/docs/CS/OS/process.md)

## References

1. [System V AMD64 psABI（版本 1.0）](https://gitlab.com/x86-psABIs/x86-64-ABI)
2. [DWARF Debugging Standard](https://dwarfstd.org/)
3. [GNU Binutils 2.46 release notes（SFrame v3 支持）](https://sourceware.org/pipermail/binutils/2026-February/148149.html)
4. [Linux 内核 objtool（ORC unwinder 生成器）](https://github.com/torvalds/linux/tree/master/tools/objtool)
5. [arch/x86/include/asm/orc_types.h（ORC 数据结构）](https://github.com/torvalds/linux/blob/master/arch/x86/include/asm/orc_types.h)
6. [GCC — Stack Protector 选项](https://gcc.gnu.org/onlinedocs/gcc/Instrumentation-Options.html)
