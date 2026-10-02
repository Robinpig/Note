## Introduction

**BookOS** 是一个用于学习的 x86 32 位（i386）操作系统，基于作者自研的 **xbook2 内核**（[GitHub](https://github.com/hzcx998/BookOS)）。它可运行在 QEMU（默认）、[Bochs](/docs/CS/OS/Bochs.md)、VirtualBox、VMware 等虚拟机中，具备所需驱动时也可在物理机上运行。xbook2 相比第一版 xbook 的宏内核，第二版采用**混合内核（hybrid kernel）**思路：把多进程、虚拟内存、进程间通信、驱动留在核心，而把文件系统、网络协议栈、图形界面放到用户态。

它在教学内核谱系里属于"中文社区自研、目标更接近完整可用系统"的一类，可与 [xv6](/docs/CS/OS/xv6/xv6.md)（精炼 Unix 教材内核）、[rCore](/docs/CS/OS/rCore.md)（Rust/RISC-V）、[osask](/docs/CS/OS/osask.md)（30 天自制）、[Linux 0.11](/docs/CS/OS/Linux/0.11.md)（真实历史内核）对照学习。

## xbook2 Kernel

xbook2 的设计取舍：

| 部分 | 位置 | 说明 |
| --- | --- | --- |
| 多进程（task） | 内核态 | 进程/线程抽象、调度 |
| 虚拟内存（vmm） | 内核态 | 分页、地址空间隔离 |
| 进程间通信（ipc） | 内核态 | 用户态服务与内核/彼此通信的通道 |
| 驱动（drivers） | 内核态 | 支撑硬件访问的最小驱动集 |
| 文件系统（fs） | 用户态 | 通过 IPC 以服务形式提供 |
| 网络协议栈（net） | 用户态 | 套接字能力作为用户态服务 |
| 图形界面（gui） | 用户态 | 窗口/图形栈不占用内核信任域 |

把 fs/net/gui 移出内核，是典型的"**微内核/混合内核**"取向：缩小内核可信计算基（TCB），单个服务崩溃不至于直接 panic 整个系统，代价是服务间通信更频繁。这与 Linux 的宏内核（[ext4](/docs/CS/OS/Linux/fs/ext4.md)、网络栈都在内核）形成鲜明对比，可借此理解不同 OS 结构（宏内核/微内核/混合内核）的权衡，参见 [OS.md 的系统结构讨论](/docs/CS/OS/OS.md)。

## Source Tree

仓库的主要目录：

| 目录 | 内容 |
| --- | --- |
| `kernel/` | xbook2 内核的引导与可执行文件 |
| `libs/` | 用户态库：xlibc（C 库）、pthread、etsocket，以及 SDL2、freetype、zlib、jpeg 等移植库 |
| `bin/` | 命令行程序：bash/sh、ls、cat、cp、mkdir、ps、date 等 |
| `sbin/` | 系统使用的程序 |
| `app/` | 普通图形/应用程序（文本编辑器、小游戏等） |
| `develop/` | 开发用磁盘镜像、ROM 文件系统内容 |
| `scripts/`、`tools/` | xbuild 脚本与内核开发工具 |

这种 `kernel + libs + bin/sbin + app` 的目录划分，本身就在模仿真实 Unix 系统的用户态/内核态边界。

## Build and Run

工具链为 gcc（i386 交叉编译）、nasm、ld、dd、objdump、objcopy、truncate，虚拟机默认 QEMU，也支持 GRUB 引导。基本流程：

```shell
git clone https://github.com/hzcx998/BookOS.git
cd BookOS
make build     # 首次：构建环境/镜像
make run       # 编译并运行（默认 qemu）
make qemu      # 显式用 qemu
make clean     # 清理产物
```

macOS 上需自行准备 i386-elf 工具链（如 `i386-elf-gcc`）与 nasm/qemu；Linux 上安装 `gcc nasm qemu-system-x86` 即可，需要性能可启用 KVM。调试可改用 [Bochs](/docs/CS/OS/Bochs.md) 的内置指令级调试器观察引导与早期内核。

## Links

- [Operating Systems](/docs/CS/OS/OS.md)
- [xv6](/docs/CS/OS/xv6/xv6.md)
- [rCore](/docs/CS/OS/rCore.md)
- [osask](/docs/CS/OS/osask.md)
- [Linux 0.11](/docs/CS/OS/Linux/0.11.md)
- [Bochs](/docs/CS/OS/Bochs.md)
- [qemu](/docs/CS/OS/qemu.md)
- [GRUB](/docs/CS/OS/Boot/Grub.md)

## References

1. [BookOS GitHub (hzcx998/BookOS)](https://github.com/hzcx998/BookOS)
2. [xbook2 内核 GitHub](https://github.com/hzcx998/xbook2)
3. [BookOS / xbook2 官网](http://www.book-os.org/)
4. [xbook2 操作系统内核介绍](https://blog.csdn.net/qq_21066551/article/details/106751783)
