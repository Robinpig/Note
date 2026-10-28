## Introduction

不链接 libc 的纯汇编程序，能做的事只有一件：发**系统调用**。系统调用是用户态进入内核的唯一受控入口——一条 `syscall` 指令把 CPU 切到 Ring 0，按 `rax` 里的调用号去内核的系统调用表查函数，执行完再切回来。这也是 [操作系统](/docs/CS/OS/OS.md) 里"用户态/内核态"这条边界在指令层面的样子。

本页讲 x86-64 上的调用序列、调用号表、错误返回，以及 vDSO 这类"不必陷入内核"的旁路。调用号表是**按架构分表**的，换架构不只是换助记符。汇编语法见 [语法与伪指令](/docs/CS/assembly/Syntax_and_Directives.md)。

## The x86-64 Calling Sequence

```text
rax   调用号
rdi   参数 1
rsi   参数 2
rdx   参数 3
r10   参数 4     ← 不是 rcx！
r8    参数 5
r9    参数 6
────────────────
syscall
────────────────
rax   返回值（负数表示错误）
```

第四个参数是 `r10` 而不是用户态函数调用约定的 `rcx`，原因是 **`syscall` 指令本身要破坏 `rcx` 和 `r11`**：CPU 把返回地址存进 `rcx`、把 `rflags` 存进 `r11`（因为 `sysret` 需要这两个值来恢复现场）。内核入口的第一步就是把 `rcx`/`r11` 保存到 `pt_regs`，然后才按 `r10` 取第四个参数。

这意味着：**`syscall` 前后，`rcx` 与 `r11` 的值不可信**。手写汇编里把还需要的变量留在 `rcx` 里就发系统调用，是最常见的隐蔽 bug——它在 `strace` 下甚至可能"正常"，因为 `strace` 走的是 ptrace 的另一条路径。

返回值语义：成功时 `rax` ≥ 0；失败时 `rax` 是 **-4095 到 -1** 之间的负数，其绝对值就是 `errno`。所以正确的错误处理不是 `js error`（判负数），而是 `cmp rax, -4095; ja error`——因为合法的返回值本身也可能是负数（比如 `lseek` 返回负偏移在某些场景、`mmap` 返回地址虽不可能是小负数但语义上仍要按区间判断）。

## A Complete Example

不链接 libc 的 hello world（NASM + ld）：

```asm
; nasm -f elf64 hello.asm && ld -o hello hello.o
section .rodata
msg:    db  "hello, world", 10
len     equ $ - msg

section .text
global _start
_start:
    ; write(1, msg, len)
    mov rax, 1              ; SYS_write
    mov rdi, 1              ; fd = stdout
    mov rsi, msg            ; buf
    mov rdx, len            ; count
    syscall

    ; exit(0)
    mov rax, 60             ; SYS_exit
    xor rdi, rdi            ; status = 0
    syscall
```

注意入口是 `_start` 而不是 `main`：`main` 是 libc 的约定，`ld` 默认入口符号是 `_start`。要让 `main` 可用必须 `gcc hello.o -o hello`（拉入 crt1.o 等启动文件），此时退出要用 `exit_group`（231）或干脆 `ret`，因为 `main` 返回后 libc 会做 atexit 清理。

## Syscall Numbers Are Per-Architecture

调用号不统一，这是移植汇编时第二个大坑（第一个是语法）：

| 调用 | x86-64 | AArch64 / RISC-V（asm-generic） |
|------|--------|-------------------------------|
| `read` | 0 | 63 |
| `write` | 1 | 64 |
| `openat` | 257 | 56 |
| `close` | 3 | 57 |
| `mmap` | 9 | 222 |
| `brk` | 12 | 214 |
| `futex` | 202 | 98 |
| `clock_gettime` | 228 | 403 |
| `getpid` | 39 | 172 |
| `exit` | 60 | 93 |
| `exit_group` | 231 | 94 |

上表 x86-64 一列来自内核源码 `arch/x86/entry/syscalls/syscall_64.tbl`，asm-generic 一列来自 `include/uapi/asm-generic/unistd.h`（AArch64 与 RISC-V 都用它）。

几点值得记住：

- **x86-64 保留了 `open`/`stat`/`fork` 这些老调用号（2/4/2…），现代 libc 用的是 `openat`（257）/ `newfstatat`（262）**。手写汇编照着老教程写 `open=2` 能跑，但在容器/seccomp 过滤、no_new_privs 等场景下更容易撞上策略限制。
- **退出线程用 `exit`（60），退出进程用 `exit_group`（231）**。多线程程序里只调 `exit` 会留下僵尸兄弟线程——glibc 的 `exit()` 走的是 `exit_group`。
- **32 位 x86 用 `int 0x80`，是另一张表**（`write=4`），且慢得多。在 x86-64 上跑 32 位兼容代码时它也可用，但不要在新代码里用。
- 权威清单始终在内核源码里，**不要背**：`arch/<arch>/entry/syscalls/` 下的 `.tbl` 与 `include/uapi/asm-generic/unistd.h` 才是唯一真值来源。

## Entry Mechanisms Compared

| 机制 | 平台 | 现状 |
|------|------|------|
| `int 0x80` | x86（32 位与兼容模式） | 慢（走中断门，要查 IDT），仅兼容用 |
| `sysenter` / `sysexit` | 32 位 x86（Intel 引入） | 被 64 位路径取代 |
| `syscall` / `sysret` | x86-64（AMD 引入） | **当前标准路径** |
| `svc #0` | AArch64 | 标准路径 |
| `ecall` | RISC-V | 标准路径 |
| **vDSO** | 各架构 | 部分调用**不陷入内核**，见下 |
| vsyscall | x86-64 | **已废弃**，仅剩的页为兼容旧二进制保留 |

**vDSO**（virtual dynamic shared object）是内核映射到每个进程地址空间的一小段代码，`gettimeofday`、`clock_gettime`、`getcpu`、`getpid` 这些"只读内核数据"的调用可以通过它直接在用户态完成，省掉一次陷入（几百个周期）。glibc 的 `gettimeofday()` 实际优先走 vDSO，这也解释了为什么有些函数"看起来是系统调用但 `strace` 抓不到"。

## Kernel Side

`syscall` 之后 CPU 做的事（x86-64）：切到 Ring 0、`swapgs` 把 `gs` 换成内核的 per-cpu 基址、把用户 `rsp` 换成内核栈、按 MSR `STAR`/`LSTAR` 给出的入口跳到 `entry_SYSCALL_64`，在那里把全部寄存器压成 `pt_regs` 结构，再按 `rax` 查 `sys_call_table` 分发。返回时反向恢复，`sysret` 回到用户态。

这条路径上有一批安全相关的细节：Spectre 缓解需要的 `retpoline` 或 IBRS 序列、入口必须 `swapgs` 的严格顺序、以及内核栈上**不要碰 red zone**（中断随时会来）——内核因此整体编译在 `-mno-red-zone` 下，见 [调用约定与 ABI](/docs/CS/assembly/Calling_Convention.md)。

## Practical Checklist

写纯汇编发系统调用时按这个顺序检查：

1. 参数寄存器对不对（第四个是 `r10`）；
2. `rcx`/`r11` 里有没有还需要的活值（有就挪走）；
3. 调用号是不是**这个架构**的号；
4. 错误判断用区间（`rax > -4096` 视为错误）而不是判符号；
5. 退出路径用 `exit_group`（231）还是 `exit`（60）要想清楚；
6. 栈是 16 字节对齐的（若有函数调用）；
7. 频繁调用的 `clock_gettime`/`getpid` 考虑 vDSO。

## Links

- [汇编（枢纽）](/docs/CS/assembly/assembly.md)
- [调用约定与 ABI](/docs/CS/assembly/Calling_Convention.md)
- [栈帧与函数调用](/docs/CS/assembly/Stack_Frame.md)
- [进程（用户态与内核态边界）](/docs/CS/OS/process.md)
- [系统调用（Linux 视角）](/docs/CS/OS/Linux/Calls.md)

## References

1. [Linux x86-64 syscall table（内核源码）](https://github.com/torvalds/linux/blob/master/arch/x86/entry/syscalls/syscall_64.tbl)
2. [Linux asm-generic unistd.h（AArch64 / RISC-V 调用号）](https://github.com/torvalds/linux/blob/master/include/uapi/asm-generic/unistd.h)
3. [Linux man-pages — syscalls(2)](https://man7.org/linux/man-pages/man2/syscalls.2.html)
4. [Linux 内核文档 — vDSO](https://man7.org/linux/man-pages/man7/vdso.7.html)
5. [Linux 内核 syscall entry 源码（entry_SYSCALL_64）](https://github.com/torvalds/linux/blob/master/arch/x86/entry/entry_64.S)
