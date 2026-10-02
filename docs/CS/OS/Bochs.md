## Introduction

**Bochs** 是一个用 C++ 编写的 **x86（IA-32/x86-64）PC 模拟器**，由 Kevin Lawton 发起、现由社区维护。与 VMware、KVM 这类借助硬件虚拟化（VT-x/AMD-V）直接在 CPU 上跑客户机的方案不同，Bochs **逐条解释执行 x86 指令**，并完整模拟 PC 的芯片组、BIOS、中断控制器、定时器、VGA 显卡、磁盘与键盘等设备。正因为它模拟得足够"老实"、可在任意指令和 I/O 访问处中断观察，它长期是**操作系统开发与启动过程调试**的经典工具——Linux 0.11、《Orange'S》《30天自制操作系统》以及大量课程内核的实验环境都用 Bochs。

它在教学内核工具链中的角色：提供一台确定、可单步、可看寄存器/物理内存/页表的"虚拟 PC"，配合 [GRUB](/docs/CS/OS/Boot/Grub.md) 或软盘引导，把内核跑起来并调试。现代更主流的模拟器是 [QEMU](/docs/CS/OS/qemu.md)，二者取舍见下文。

## Emulation vs Virtualization

| 方式 | 代表 | 原理 | 速度 | 可调试性 |
| --- | --- | --- | --- | --- |
| **指令集模拟** | Bochs | 解释执行每条 x86 指令，软件模拟设备 | 慢（数量级下降） | 极强：任意指令/I/O/内存断点 |
| **硬件虚拟化** | KVM、VMware、Hyper-V、QEMU+KVM | CPU 进入 guest 模式直接执行，仅敏感操作陷入 | 接近原生 | 依赖 gdb stub/跟踪点 |
| **动态翻译（JIT/TCG）** | QEMU（无 KVM） | 把客户指令块翻译成主机指令缓存执行 | 较快 | 可配合 gdb stub 调试 |

Bochs 选择了最慢但最可控的全模拟：它不追求跑生产负载，而追求**行为精确、状态完全可见、跨平台可复现**，这恰好是研究启动流程、实模式→保护模式切换、分页开启、中断处理等早期内核代码最需要的。

## What Bochs Emulates

一台典型的 Bochs PC 包含：

- **CPU**：可配置 386/486/Pentium 到现代 x86-64，支持多核心模拟；
- **内存**：可配置大小，物理内存完全可查看/可下断；
- **芯片组与中断**：i440FX 等北桥、PIIX 南桥、8259 PIC、APIC、8253/8254 PIT 定时器、RTC；
- **BIOS/VGA**：含可模拟的 BIOS 与 VBE，能显示文本/图形；
- **存储**：IDE/ATA 硬盘（镜像文件）、软驱（软盘镜像 `.img`）、ATAPI 光驱；
- **其他**：键盘、鼠标、串口、并口、网卡（NE2000/E1000）。

对教学内核而言，软盘/IDE + 8259 + 8253 + VGA 文本模式这套"经典 PC 组合"正是早期引导代码面对的硬件。

## Configuration

Bochs 用一个文本配置文件（通常 `bochsrc`）描述机器。一个最小教学配置（软盘引导）：

```text
megs: 32
ata0-enabled: 1=1
floppya: 1_44=boot.img, status=inserted
boot: a
log: bochsout.txt
display_library: sdl2
```

硬盘引导并挂 CD 的常见项：

```text
ata0: enabled=1, ioaddr1=0x1f0, ioaddr2=0x3f0, irq=14
ata0-master: type=disk, path=hd.img, mode=flat
ata0-slave: type=cdrom, path=cd.iso, status=inserted
boot: disk
```

启动：`bochs -f bochsrc`（`-q` 跳过菜单直接运行）。磁盘镜像可用 `bximage` 工具创建。

## Debugger

Bochs 内置命令行调试器，这是它相对普通虚拟机的核心价值：

```text
b 0x7c00            # 物理地址/线性地址断点（断在 MBR 被加载处）
vb 0x8:0x1000       # 虚地址（段:偏移）断点
info cpu            # 查看通用寄存器、段寄存器、eflags
info gdt / idt / tss
x /16xb 0x7c00      # 查看物理内存（十六进制字节）
x /16xw 0x100000
info tab            # 查看当前线性->物理页映射
s                   # step，执行一条指令
n                   # next（跳过函数调用）
c                   # continue
watch r 0x...       # 物理内存读/写监视点
print-stack
```

典型调试启动链：在 `0x7c00`（MBR，见 [BootLoader](/docs/CS/OS/BootLoader.md)）下断，单步看 BIOS 把引导扇区载入、跳入、设置 GDT、切保护模式、加载 [GRUB](/docs/CS/OS/Boot/Grub.md)、再到内核入口。对研究"上电后第一条指令如何一路走到 `start_kernel`/`main`"非常直观。

## Use in OS Education

- **Linux 0.11**：赵炯《Linux 内核完全注释》等学习材料常以 Bochs 跑 Linux 0.11 软盘/硬盘镜像，因为那个年代的内核假设的硬件正是 Bochs 精确模拟的经典 PC；参考 [Linux 0.11](/docs/CS/OS/Linux/0.11.md)。
- **《30天自制操作系统》（osask）**：书中工具链以 Bochs/QEMU 为运行环境（见 [osask](/docs/CS/OS/osask.md)）。
- **自研/课程内核**：在 [Multiboot](/docs/CS/OS/Boot/Grub.md) 普及前，常把 512 字节引导扇区写进软盘镜像用 Bochs 调试。

## Bochs vs QEMU

| 维度 | Bochs | [QEMU](/docs/CS/OS/qemu.md) |
| --- | --- | --- |
| 执行方式 | 纯解释模拟 | TCG 动态翻译；可配 KVM 硬件加速 |
| 速度 | 慢 | 快很多（+KVM 近原生） |
| 内置调试 | 自带强大的指令级调试器 | 默认无交互调试器，用 `-s -S` + gdb stub |
| 架构 | 主要 x86 PC | 多架构（x86/ARM/RISC-V…） |
| 典型用途 | 教学内核/启动过程精调 | 现代教学内核（[xv6-riscv](/docs/CS/OS/xv6/xv6.md)、[rCore](/docs/CS/OS/rCore.md)）、虚拟化、跨架构运行 |

经验选择：做 x86 实模式/早期引导、需要逐指令和 I/O 级观察用 Bochs；跑现代 RISC-V/ARM 教学内核或追求速度、用 gdb 远程调试，用 QEMU。两者都是"模拟器"而非容器——它们虚拟的是**整台机器**，与 [namespace/cgroup](/docs/CS/OS/Linux/namespace.md) 式隔离不是一类技术（虚拟化与容器的区别见 [VM](/docs/CS/OS/VM.md)）。

## Links

- [Operating Systems](/docs/CS/OS/OS.md)
- [qemu](/docs/CS/OS/qemu.md)
- [BootLoader](/docs/CS/OS/BootLoader.md)
- [GRUB](/docs/CS/OS/Boot/Grub.md)
- [BIOS and UEFI](/docs/CS/OS/BIOS.md)
- [Linux 0.11](/docs/CS/OS/Linux/0.11.md)
- [osask](/docs/CS/OS/osask.md)
- [Virtual Machines](/docs/CS/OS/VM.md)

## References

1. [Bochs Official Site and Documentation](https://bochs.sourceforge.io/)
2. [Bochs User Manual — Using the Bochs internal debugger](https://bochs.sourceforge.io/cgi-bin/topper.py?pr=documentation)
3. [Bochs x86 PC emulator (GitHub mirror)](https://github.com/bochs-emu/Bochs)
4. [x86 指令级调试与 Bochs（OSDev Wiki Bochs）](https://wiki.osdev.org/Bochs)
