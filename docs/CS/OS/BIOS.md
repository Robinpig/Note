## 简介

在计算机中，BIOS（基本输入/输出系统，也称为系统 BIOS、ROM BIOS、BIOS ROM 或 PC BIOS）
是固件，用于为操作系统和程序提供运行时服务，并在启动过程（上电启动）期间执行硬件初始化。

现代 PC 中的 BIOS 初始化并测试系统硬件组件（上电自检），
并从大容量存储设备加载引导加载程序，然后由引导加载程序初始化内核。
在 DOS 时代，BIOS 为键盘、显示器、存储和其他输入/输出（I/O）设备提供 BIOS 中断调用，标准化了应用程序和操作系统的接口。
较新的操作系统在启动后不再使用 BIOS 中断调用。

大多数 BIOS 实现是专门为与特定计算机或主板型号配合工作而设计的，通过与各种设备（尤其是系统芯片组）交互来实现。
最初，BIOS 固件存储在 PC 主板上的 ROM 芯片中。
在后来的计算机系统中，BIOS 内容存储在闪存中，因此可以在不将芯片从主板取下的情况下重写。
这允许终端用户轻松更新 BIOS 固件，从而可以添加新功能或修复错误，
但也使得计算机有可能被 BIOS rootkit 感染。此外，失败的 BIOS 升级可能导致主板变砖。

## Legacy BIOS




## EFI


EFI(Extensible Firmware Interface) 的实现使用了 C语言 

与传统的 BIOS 不同 EFI的设备驱动程序不是由汇编语言写的  而是由 EFI 的虚拟指令集编写成的



## UEFI

The [Unified Extensible Firmware Interface](https://uefi.org/) (UEFI, successor of the EFI) is an interface between operating systems and firmware.
It provides a standard environment for booting an operating system and running pre-boot applications.


It is distinct from the "MBR boot code" method that was used by legacy BIOS systems.




## Links

- [Operating System](/docs/CS/OS/OS.md)
- [Computer Organization](/docs/CS/CO/CO.md)