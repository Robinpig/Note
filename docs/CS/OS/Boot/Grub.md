## Introduction

**GRUB**（GRand Unified Bootloader）是 x86 PC 上事实上标准的**多操作系统引导程序**，GNU 项目的一部分，常见版本是 **GRUB 2**（配置 `grub.cfg`，区别于已被淘汰的 GRUB Legacy）。它处在固件（BIOS/UEFI）与操作系统内核之间：固件完成硬件初始化后加载 GRUB，GRUB 负责呈现菜单、读取文件系统里的内核映像与参数、装载初始内存盘（initramfs/initrd），最后跳入内核入口、交出控制权。

GRUB 在整条启动链中的位置：

```
上电 → BIOS/UEFI → (MBR/GPT) → GRUB → 内核 bzImage + initramfs → 内核启动 → systemd/init
```

前面固件与主引导记录的通用原理（0x7C00、MBR 的 446+64+2 字节布局、活动分区、卷引导记录）见 [BootLoader](/docs/CS/OS/BootLoader.md) 与 [BIOS/UEFI](/docs/CS/OS/BIOS.md)；本笔记聚焦 GRUB 自身。

## Why GRUB

相比"MBR 直接引导内核"，GRUB 解决了几个实际问题：

- **能读文件系统**：GRUB 内置 ext2/4、xfs、fat、btrfs 等文件系统驱动，内核以普通文件（如 `/boot/vmlinuz-…`）存放即可，不需要占用固定扇区；
- **菜单与多系统**：一份配置里可选不同内核版本、不同 OS（链式加载 chainload Windows 等），支持交互式编辑启动参数；
- **理解内核格式**：直接支持 **Multiboot / Multiboot2** 协议，也实现了 **Linux boot protocol**，能正确设置进入内核所需的寄存器与参数结构；
- **可携带初始内存盘**：把 initramfs 一并载入并告知内核位置；
- UEFI 时代 GRUB 作为一个 EFI 应用（`grubx64.efi`）由固件直接加载，不再依赖 MBR 那套 512 字节限制。

## Multiboot

**Multiboot** 是 GNU 定义的一套"引导器 ↔ 内核"之间的标准接口（Multiboot2 是其现代化版本，支持 UEFI、更灵活的数据结构），让任何兼容的引导器能加载任何兼容的内核，而不必为每个内核写专用加载逻辑。

内核侧约定：

- 内核映像头部放一个 **Multiboot header**（魔数 `0x1BADB002`，Multiboot2 为 `0xE85250D6`），声明对齐方式、是否需要 a.out 符号表、期望的视频模式等；
- 引导器加载内核到指定位置、进入 32 位保护模式、设置好段寄存器/栈；
- 跳转时 `EAX` 放魔数（让内核确认自己是被 Multiboot 引导器加载的），`EBX` 指向引导器填写的 **information structure**（物理内存布局、启动设备、命令行、模块列表、帧缓冲信息等）。

教学内核（包括简化的自研 OS、早期 [xv6 x86](/docs/CS/OS/xv6/xv6.md) 的实验思路、《30天自制操作系统》之外的大量课程内核）常用 Multiboot + GRUB，从而省去自己写磁盘读取与保护模式切换的繁琐引导代码。

## Boot Stages

在传统 BIOS + MBR 布局下，GRUB 2 的加载被拆成几个小阶段（受 MBR 体积限制，无法一次容纳完整程序）：

| 阶段 | 文件/位置 | 职责 |
| --- | --- | --- |
| **boot.img** | 写入 MBR（或分区引导扇区） | 只有 ~446 字节，唯一任务是定位并加载 core.img 的第一扇区，不含文件系统逻辑 |
| **diskboot.img** | core.img 的起始扇区（位于 MBR 与第一分区之间的空隙，或 BIOS Boot Partition） | 由 boot.img 加载，负责把整个 core.img 剩余部分读入 |
| **core.img** | 由 diskboot + 前缀模块（lzio、`normal`、`part_msdos/gpt`、目标文件系统模块等）动态拼成 | 最小化的 GRUB 内核：识别磁盘分区与 `/boot` 文件系统，加载配置和模块 |
| **normal.mod** | `/boot/grub/…` | 完整命令环境：解析 `grub.cfg`、显示菜单、提供 rescue shell |

进入 `normal` 后，GRUB 才能真正读懂 `/boot/grub/grub.cfg`、加载 `linux`/`initrd` 等模块并执行菜单项。UEFI 下不再需要这种多阶段接力：固件直接把 `grubx64.efi`（已含文件系统与模块加载能力）读进内存运行。

## Loading Linux

`grub.cfg` 的一个典型 Linux 菜单项：

```grub
menuentry 'Linux' {
    set root='hd0,gpt2'
    linux  /boot/vmlinuz-6.6 root=UUID=xxxx ro quiet splash
    initrd /boot/initramfs-6.6.img
}
```

GRUB 加载 Linux 内核（`linux`/`linux16`/`linuxefi` 命令）时实现了 **Linux boot protocol**，大致步骤：

1. **boot.S**：GRUB 最早期的汇编入口，建立最基本的执行环境；
2. **grub_main**：进入 C 语言环境，初始化设备、文件系统与模块；
3. 读取 `vmlinuz`（**bzImage**，即压缩内核 + 内嵌 setup 头），解析内核头部的 boot protocol 版本与参数；
4. **依靠 BIOS（或 EFI boot services）收集的硬件信息填充 boot protocol 结构**：如 E820 物理内存映射（e820 表）、显存信息、命令行（`root=… ro quiet`）、initrd 位置大小等，写进内核约定的参数区/`boot_params`；
5. 在高/低内存的规定位置摆放内核各段（bzImage 可放在 1MB 以上的大内存）；
6. **加载 initrd/initramfs 到内存**并在 boot params 里登记其地址与长度；
7. 按协议切到内核要求的模式（32/64 位、关中断），**跳入内核第一行代码**（压缩内核的解压入口 `startup_32/64`，解压缩后到 `start_kernel`），此后 GRUB 不再执行。

内核解压缩并完成架构相关初始化后，会挂载 initramfs 作为临时根文件系统、加载必要驱动（磁盘、文件系统模块），再 pivot 到真正的根设备并启动 init/systemd。早期 Linux 引导与 0.11 内核的启动背景可参考 [Linux 0.11](/docs/CS/OS/Linux/0.11.md)。

## Configuration and Rescue

```bash
# Debian/Ubuntu 风格：更新 /boot/grub/grub.cfg
update-grub              # 实际调用 grub-mkconfig -o /boot/grub/grub.cfg
# RHEL/Fedora 风格
grub2-mkconfig -o /boot/grub2/grub.cfg

# 默认启动项与超时（/etc/default/grub）
GRUB_DEFAULT=0
GRUB_TIMEOUT=5
GRUB_CMDLINE_LINUX="quiet splash"
```

- 开机按住 `Shift`/按 `Esc` 可唤出菜单；在菜单项按 `e` 可临时编辑启动参数（单用户/救援常加 `init=/bin/bash` 或 `single`），按 `c` 进入命令行。
- 当 core 找不到文件系统/配置时进入 **grub rescue>**，需手动 `set prefix=(hd0,gpt2)/boot/grub`、`insmod normal`、`normal` 救回。
- GRUB 里磁盘命名从 0 起、分区从 1 起：`(hd0,gpt2)` = 第一块盘的第二个 GPT 分区。

## GRUB vs systemd-boot / U-Boot

| 引导器 | 平台/场景 | 特点 |
| --- | --- | --- |
| **GRUB 2** | x86 PC（BIOS/UEFI） | 功能最全、文件系统/脚本/多系统支持强，也用于部分嵌入式 |
| **systemd-boot**（gummiboot） | UEFI PC | 轻量，只引导 EFI stub 内核 + initrd，配置简单 |
| **U-Boot** | ARM/RISC-V 嵌入式 | 通用 bootloader，加载内核到内存、传 ATAG/设备树（DTB），常与 GRUB 对 ARM 的角色不同 |
| 内核 EFI stub | UEFI | 内核自身就是合法 EFI 应用，可被固件/systemd-boot 直接加载，跳过传统引导器 |

## Links

- [BootLoader](/docs/CS/OS/BootLoader.md)
- [BIOS and UEFI](/docs/CS/OS/BIOS.md)
- [Linux 0.11](/docs/CS/OS/Linux/0.11.md)
- [xv6](/docs/CS/OS/xv6/xv6.md)
- [Operating Systems](/docs/CS/OS/OS.md)

## References

1. [GNU GRUB Manual](https://www.gnu.org/software/grub/manual/grub/grub.html)
2. [Multiboot2 Specification](https://www.gnu.org/software/grub/manual/multiboot2/multiboot.html)
3. [The Linux/x86 Boot Protocol (kernel docs)](https://docs.kernel.org/arch/x86/boot.html)
4. [systemd-boot](https://www.freedesktop.org/software/systemd/man/latest/systemd-boot.html)
