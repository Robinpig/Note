## Introduction

**osask**（作者川合秀实的社区昵称，其自制 OS 名为 **Haribote OS / "纸娃娃操作系统"**）指的是入门书《**30天自制操作系统**》（川合秀实）从零构建的 x86 教学操作系统。这本书以 30 天为进度，每天增加一点功能，从一张可引导软盘的引导扇区开始，逐步做出画面显示、内存管理、中断、多任务、窗口、命令行、定时器乃至简单图形界面。它与偏理论的 [xv6](/docs/CS/OS/xv6/xv6.md)、用现代语言的 [rCore](/docs/CS/OS/rCore.md) 路线不同：强调"亲手做、看得见画面"，工具链以汇编 + C 为主，运行在 [Bochs](/docs/CS/OS/Bochs.md)/QEMU 这类模拟器上。

本笔记汇总该书涉及的核心知识点与工具链，作为教学内核主题的一条入门支线。

## Environment

书中原始环境是 Windows 作者自制工具链（用 `nask` 汇编、`make`、`bz` 打包软盘镜像），关键点：

- 需要下载作者提供的 [bz](https://vcraft.jp/soft/bz.html) 等工具把编译产物组织成软盘镜像；
- 引导载体是 **1.44MB 软盘镜像（.img）**，BIOS 从引导扇区（0x7C00，见 [BootLoader](/docs/CS/OS/BootLoader.md)）载入；
- 用 [Bochs](/docs/CS/OS/Bochs.md) 或 QEMU 从该软盘镜像启动并调试。

**软盘方式已不适用于现在大部分物理 PC**，但作为教学模型仍很清晰：它把"BIOS → 引导扇区 → 自举加载 → 内核"这条最朴素的启动链压缩到一张镜像里，便于理解。现代学习时通常改用 QEMU（`-fda haribote.img` 或转硬盘/ISO），或在 Linux/macOS 上用交叉工具链替代 nask。

## What It Builds

按天数推进的主要模块（对应操作系统的经典主题）：

| 阶段（天） | 内容 | 对应 OS 概念 |
| --- | --- | --- |
| 1–5 | 二进制编辑引导扇区、Hello 画面、汇编、寄存器与内存 | 实模式、引导、显存文本输出 |
| 6–10 | C 语言接入、GDT/段设定、中断处理、PIC、定时器 | 保护模式、GDT、[中断](/docs/CS/OS/interrupt.md)、IDT |
| 11–15 | 内存分层与容量检测、内存管理 | 物理内存、内存分配 |
| 16–20 | 多任务、任务切换、优先级 | 进程/线程、[调度](/docs/CS/OS/scheduling.md)、上下文切换 |
| 21–25 | 窗口、图层叠加、鼠标、定时器管理 | 图形、输入设备、事件 |
| 26–30 | 命令行窗口、应用程序、API、系统调用 | [系统调用](/docs/CS/OS/xv6/Syscall.md)、用户态、API |

## Key Technical Points

- **实模式 → 保护模式**：早期引导在 16 位实模式，随后设置 GDT 并切换到 32 位保护模式，是理解 x86 启动与分段的经典练习；可对照 [BIOS/UEFI](/docs/CS/OS/BIOS.md) 与 [GRUB](/docs/CS/OS/Boot/Grub.md)（后者用 Multiboot 帮你省去这些手工步骤）。
- **中断与 PIC**：通过 8259A 设置中断掩码、注册中断处理函数处理定时器与键盘，是理解中断驱动的入门；[xv6 中断](/docs/CS/OS/xv6/Interrupt.md)在 RISC-V 上给出更结构化的同类机制。
- **协作/抢占式多任务**：书中用任务状态段（TSS）与栈切换实现多任务，展示了保存/恢复寄存器的上下文切换本质，与 [xv6 进程](/docs/CS/OS/xv6/proc.md)、Linux 调度（[sche](/docs/CS/OS/Linux/proc/sche.md)）目标一致但实现更原始。
- **自制而非复用标准**：为教学清晰，很多东西（文件系统、库函数、字体）都手写简化版，因此不追求工程规范，重在"每个部件都自己造一遍"。

## osask vs xv6 / rCore / Linux 0.11

| 教学内核 | 语言/平台 | 风格与侧重 |
| --- | --- | --- |
| **osask（30天）** | 汇编+C / x86 实→保护模式、软盘 | 零基础、画面驱动、部件全手写，重趣味与直觉 |
| [xv6](/docs/CS/OS/xv6/xv6.md) | C / RISC-V·x86 | 现代 Unix 结构，配套教材，贴近真实 OS 设计 |
| [rCore](/docs/CS/OS/rCore.md) | Rust / RISC-V | 现代系统语言、`no_std`、内存安全、SBI 分层 |
| [Linux 0.11](/docs/CS/OS/Linux/0.11.md) | C + 少量汇编 / x86 | 真实历史内核，复杂度与代码量更大，用于"读真内核" |

入门路线建议：想快速建立"OS 是怎么一步步长出来"的直觉可用 osask；要系统学习 Unix 内核设计转 xv6；想用现代安全语言实践用 rCore；想看真实工业内核早期形态读 Linux 0.11。

## Links

- [Operating Systems](/docs/CS/OS/OS.md)
- [Bochs](/docs/CS/OS/Bochs.md)
- [qemu](/docs/CS/OS/qemu.md)
- [BootLoader](/docs/CS/OS/BootLoader.md)
- [GRUB](/docs/CS/OS/Boot/Grub.md)
- [xv6](/docs/CS/OS/xv6/xv6.md)
- [rCore](/docs/CS/OS/rCore.md)
- [Linux 0.11](/docs/CS/OS/Linux/0.11.md)

## References

1. [川合秀实《30天自制操作系统》](https://book.douban.com/subject/11530332/)
2. [作者站 Haribote OS / osask](http://hrb.osask.jp/)
3. [30天自制操作系统 相关工具 bz](https://vcraft.jp/soft/bz.html)
4. [OSDev Wiki](https://wiki.osdev.org/Main_Page)
