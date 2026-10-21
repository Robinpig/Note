## Introduction

xv6 是 MIT 为操作系统课程（6.828 / 6.S081）设计的**完整教学用类 Unix 内核**，是 Unix Version 6（v6）的重新实现：沿用 v6 的结构与风格，但用 ANSI C 写成，先后移植到 x86 多核与 RISC-V。代码量小、结构清晰，是学习"操作系统概念如何落到几千行 C+汇编"的绝佳起点——也是本知识库 [Linux](/docs/CS/OS/Linux/Linux.md) 等生产级内核的对照样本。

特点（也是它有意为之的简化）：

- 只支持多进程，**不支持**多线程
- 不支持内存换出（page replacement）
- 不支持信号系统（仅 `kill` 用于杀进程）
- 不支持 `mmap` 内存映射
- 用户页只读（写入触发异常）
- 系统调用规范不完全符合 POSIX
- 不支持动态链接
- 内核态无法动态分配内存（启动早期用 `kinit1` 受限区间，之后才 `kinit2` 全量）

两个官方移植：x86 版 [`mit-pdos/xv6-public`](https://github.com/mit-pdos/xv6-public)（教材式启动，实模式→保护模式）、RISC-V 版 [`mit-pdos/xv6-riscv`](https://github.com/mit-pdos/xv6-riscv)（当前课程主流，QEMU `virt` 机器）。

## 架构总览

```
        ┌──────────────────────── 用户态 ────────────────────────┐
        │  init → sh，以及 cat/echo/grep… 等用户程序              │
        │  通过 ecall / int $T_SYSCALL 进入内核                    │
        └───────────────────────────┬────────────────────────────┘
                                     │ 系统调用
        ┌──────────────────────── 内核态 ────────────────────────┐
        │  Syscall  分发（syscall.c + syscalls[] 表）              │
        │     ├─ Proc     进程/线程控制块、fork、调度（proc.c）      │
        │     ├─ File     文件描述符、inode、目录、管道（fs/file）   │
        │     ├─ Memory   物理页分配 + 进程私有地址空间（kalloc/vm） │
        │     ├─ Interrupt/trap 异常/中断/系统调用统一入口          │
        │     └─ Device   MMIO、UART、virtio-blk、缓冲区缓存        │
        │  Boot     从复位到 main()、第一个用户进程（bootasm/entry） │
        └───────────────────────────┬────────────────────────────┘
                                     │ 读写
        ┌─────────────────────── 硬件（QEMU）─────────────────────┐
        │  CPU（x86 多核 / RISC-V harts）、RAM、virtio-blk 磁盘、   │
        │  16550 UART、PLIC/CLINT、定时器                           │
        └────────────────────────────────────────────────────────┘
```

各子系统之间刻意保持单向依赖：上层（syscall/proc/file）调用下层（memory/interrupt/device），启动线（[Boot](/docs/CS/OS/xv6/Boot.md)）把最底层硬件初始化串起来。

## Map of This Section

xv6 内容按下述几条线组织，本枢纽只做导航，细节在各分册：

- **启动线**：[Boot](/docs/CS/OS/xv6/Boot.md) —— 从 BIOS/复位到 `main()`、再到第一个用户进程 `init` 的完整链路，x86 与 RISC-V 两条移植对照。
- **运行支撑线**：[memory](/docs/CS/OS/xv6/memory.md)（物理页分配 + 进程私有地址空间/页表）、[Interrupt](/docs/CS/OS/xv6/Interrupt.md)（trap / 中断 / 异常进入内核的统一入口）、[Syscall](/docs/CS/OS/xv6/Syscall.md)（系统调用分发与参数取回，x86 `eax` vs RISC-V `a7`）。
- **抽象线**：[proc](/docs/CS/OS/xv6/proc.md)（进程控制块、`fork`、时间片轮转调度）、[file](/docs/CS/OS/xv6/file.md)（fd、inode、目录、路径查找、管道、日志式写）、[device](/docs/CS/OS/xv6/device.md)（MMIO、UART、virtio-blk、缓冲区缓存）。
- **格式线**：[ELF](/docs/CS/OS/xv6/ELF.md)（可执行文件格式与 `exec` 装载）。
- **动手线**：[Env](/docs/CS/OS/xv6/Env.md)（搭建 QEMU 调试环境、gdb 单步、编译运行自己的用户程序）。

## Code Overview

xv6 源码按"一个 `.c` 管一个子系统"组织，关键文件与归属：

| 子系统 | 关键源文件（x86 / RISC-V） | 对应分册 |
| --- | --- | --- |
| 启动 | `bootasm.S`/`bootmain.c`/`entry.S`/`main.c`（x86）；`entry.S`/`start.c`/`main.c`（RISC-V） | [Boot](/docs/CS/OS/xv6/Boot.md) |
| 进程 | `proc.c`、`swtch.S`（上下文切换） | [proc](/docs/CS/OS/xv6/proc.md) |
| 内存 | `kalloc.c`（物理页）、`vm.c`（页表/地址空间） | [memory](/docs/CS/OS/xv6/memory.md) |
| 中断/异常 | `trap.c`/`trapasm.S`/`vectors.S`（x86）；`trap.c`/`kernelvec.S`/`trampoline.S`（RISC-V） | [Interrupt](/docs/CS/OS/xv6/Interrupt.md) |
| 系统调用 | `syscall.c`、`sysproc.c`、`usys.S`（用户态桩） | [Syscall](/docs/CS/OS/xv6/Syscall.md) |
| 文件系统 | `fs.c`/`file.c`/`bio.c`/`log.c`/`pipe.c`/`exec.c` | [file](/docs/CS/OS/xv6/file.md) / [ELF](/docs/CS/OS/xv6/ELF.md) |
| 设备 | `console.c`/`uart.c`（x86 UART）、`virtio_disk.c`/`plic.c`（RISC-V） | [device](/docs/CS/OS/xv6/device.md) |

> 二进制构成：x86 版入口 `bootblock`（512 字节，由 `bootasm.S`+`bootmain.c` 生成）负责把内核 ELF 载入内存并转移控制权，内核本身也是 ELF；细节见 [Boot](/docs/CS/OS/xv6/Boot.md)。

## 启动与主循环（摘要）

加电后，启动代码把内核装好、打开分页、初始化各子系统，最后 `userinit()` 造出第一个用户进程、`scheduler()` 开始调度；首进程 `exec("/init")` → `init` 进程 `fork+exec` 出 `sh`。完整步骤、寄存器级代码与 x86/RISC-V 差异见 [Boot](/docs/CS/OS/xv6/Boot.md)，环境搭建与运行示例见 [Env](/docs/CS/OS/xv6/Env.md)。

## Links

- [Operating Systems](/docs/CS/OS/OS.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)
- [xv6 启动流程](/docs/CS/OS/xv6/Boot.md)
- [xv6 环境搭建](/docs/CS/OS/xv6/Env.md)
- [xv6 进程](/docs/CS/OS/xv6/proc.md)
- [xv6 内存管理](/docs/CS/OS/xv6/memory.md)
- [xv6 中断与异常](/docs/CS/OS/xv6/Interrupt.md)
- [xv6 系统调用](/docs/CS/OS/xv6/Syscall.md)
- [xv6 文件系统](/docs/CS/OS/xv6/file.md)
- [xv6 设备管理](/docs/CS/OS/xv6/device.md)
- [xv6 ELF 与 exec](/docs/CS/OS/xv6/ELF.md)
- [QEMU](/docs/CS/OS/qemu.md)
- [Bochs](/docs/CS/OS/Bochs.md)
- [Unix](/docs/CS/OS/unix/Unix.md)

## References

1. [xv6 a simple, Unix-like teaching operating system](https://pdos.csail.mit.edu/6.828/2018/xv6/book-rev11.pdf)
2. [操作系统原型 - xv6分析与实验](https://book.douban.com/subject/35550326/)
3. [xv6 中文文档](https://th0ar.gitbooks.io/xv6-chinese/content/)
4. [xv6操作系统启动过程(RISC-V)](https://juejin.cn/post/7308621051525120037)
5. [6.S081 All-In-One (dgs.zone)](https://xv6.dgs.zone/)
