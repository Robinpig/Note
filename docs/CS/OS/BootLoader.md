## Introduction

A bootloader is a program written to load a more complex kernel.

计算机启动是这样一个过程。

- 通电
- 读取ROM里面的BIOS，用来检查硬件
- 硬件检查通过
- BIOS根据指定的顺序，检查引导设备的第一个扇区（即主引导记录），加载在内存地址 0x7C00
- 主引导记录把操作权交给操作系统

> 0x7C00这个地址来自Intel的第一代个人电脑芯片8088，以后的CPU为了保持兼容，一直使用这个地址
> 为了把尽量多的连续内存留给操作系统，主引导记录就被放到了内存地址的尾部。由于一个扇区是512字节，主引导记录本身也会产生数据，需要另外留出512字节保存。
> 所以，它的预留位置就变成了： 0x7FFF - 512 - 512 + 1 = 0x7C00


0x7FFF - 512 - 512 + 1 = 0x7C00

主引导记录就是引导"操作系统"进入内存的一段小程序，大小不超过1个扇区（512字节）
如果这512个字节的最后两个字节是0x55和0xAA，表明这个设备可以用于启动；如果不是，表明设备不能用于启动，控制权于是被转交给"启动顺序"中的下一个设备

主引导记录由三个部分组成：

- 第1-446字节：调用操作系统的机器码。
- 第447-510字节：分区表（Partition table）。
- 第511-512字节：主引导记录签名（0x55和0xAA）。



硬盘分区有很多好处。考虑到每个区可以安装不同的操作系统，"主引导记录"因此必须知道将控制权转交给哪个区。

分区表的长度只有64个字节，里面又分成四项，每项16个字节。所以，一个硬盘最多只能分四个一级分区，又叫做"主分区"。

每个主分区的16个字节，由6个部分组成：

1. 第1个字节：如果为0x80，就表示该主分区是激活分区，控制权要转交给这个分区。四个主分区里面只能有一个是激活的。
2. 第2-4个字节：主分区第一个扇区的物理位置（柱面、磁头、扇区号等等）。
3. 第5个字节：主分区类型。
4. 第6-8个字节：主分区最后一个扇区的物理位置。
5. 第9-12字节：该主分区第一个扇区的逻辑地址。
6. 第13-16字节：主分区的扇区总数。

最后的四个字节（"主分区的扇区总数"），决定了这个主分区的长度。也就是说，一个主分区的扇区总数最多不超过2的32次方。

如果每个扇区为512个字节，就意味着单个分区最大不超过2TB。再考虑到扇区的逻辑地址也是32位，所以单个硬盘可利用的空间最大也不超过2TB。如果想使用更大的硬盘，只有2个方法：一是提高每个扇区的字节数，二是增加扇区总数

计算机的控制权就要转交给硬盘的某个分区了，这里又分成三种情况

##### **卷引导记录**

四个分区只有一个是激活的。计算机会读取激活分区的第一个扇区，叫做"卷引导记录"（Volume boot record，缩写为VBR）。

"卷引导记录"的主要作用是，告诉计算机，操作系统在这个分区里的位置。然后，计算机就会加载操作系统了


##### **扩展分区和逻辑分区**

随着硬盘越来越大，四个主分区已经不够了，需要更多的分区。但是，分区表只有四项，因此规定有且仅有一个区可以被定义成"扩展分区"（Extended partition）。

所谓"扩展分区"，就是指这个区里面又分成多个区。这种分区里面的分区，就叫做"逻辑分区"（logical partition）。

计算机先读取扩展分区的第一个扇区，叫做"扩展引导记录"（Extended boot record，缩写为EBR）。它里面也包含一张64字节的分区表，但是最多只有两项（也就是两个逻辑分区）。

计算机接着读取第二个逻辑分区的第一个扇区，再从里面的分区表中找到第三个逻辑分区的位置，以此类推，直到某个逻辑分区的分区表只包含它自身为止（即只有一个分区项）。因此，扩展分区可以包含无数个逻辑分区。

但是，似乎很少通过这种方式启动操作系统。如果操作系统确实安装在扩展分区，一般采用下一种方式启动。

##### 启动管理器

在这种情况下，计算机读取"主引导记录"前面446字节的机器码之后，不再把控制权转交给某一个分区，而是运行事先安装的"启动管理器"（boot loader），由用户选择启动哪一个操作系统



#### 操作系统

控制权转交给操作系统后，操作系统的内核首先被载入内存。

以Linux系统为例，先载入/boot目录下面的kernel。内核加载成功后，第一个运行的程序是/sbin/init。它根据配置文件（Debian系统是/etc/initab）产生init进程。这是Linux启动后的第一个进程，pid进程编号为1，其他进程都是它的后代。

然后，init线程加载系统的各个模块，比如窗口程序和网络程序，直至执行/bin/login程序，跳出登录界面，等待用户输入用户名和密码。

至此，全部启动过程完成

The boot loader ultimately has to:

- Bring the kernel (and all the kernel needs to bootstrap) into memory
- Provide the kernel with the information it needs to work correctly
- Switch to an environment that the kernel will like
- Transfer control to the kernel



The following table lists the most important bootloaders:


| Name of the bootloader          | Description                                                                     |
| ------------------------------- | ------------------------------------------------------------------------------- |
| Bootmgr                         | boot program for Microsoft systems since Windows Vista and Windows Server 2008  |
| NT loader (NTLDR)               | boot program for Microsoft systems until Windows XP and Windows Server 2003     |
| barebox                         | bootloader for embedded systems in printers, cameras, cars, airplanes, and more |
| boot.efi                        | EFI bootloader that has been used in Mac devices since 2006                     |
| BootX                           | former bootloader for Mac operating systems                                     |
| Grand Unified Bootloader (GRUB) | free boot program for Unix-like operating systems such as Linux                 |
| ARM Core Bootloader             | bootloader for microcontrollers (used in iPhones among others)                  |
| OpenBIOS                        | free, portable boot manager under a GNU-GPL license                             |


A boot loader is a piece of software started by the firmware (BIOS or UEFI). 
It is responsible for loading the kernel with the wanted kernel parameters and any external initramfs images.
In the case of UEFI, the kernel itself can be directly launched by the UEFI using the EFI boot stub. 
A separate boot loader or boot manager can still be used for the purpose of editing kernel parameters before booting.


CS: 0xffff
IP: 0

Linux

- bootsect.S
- sctup.S
- video.S

head.S

## BIOS

In computing, BIOS (`Basic Input/Output System`, also known as the System BIOS, ROM BIOS, BIOS ROM or PC BIOS) 
is firmware used to provide runtime services for operating systems and programs and to perform hardware initialization during the booting process (power-on startup).


The BIOS in modern PCs initializes and tests the system hardware components (Power-on self-test), 
and loads a boot loader from a mass storage device which then initializes a kernel. 
In the era of DOS, the BIOS provided BIOS interrupt calls for the keyboard, display, storage, 
and other input/output (I/O) devices that standardized an interface to application programs and the operating system. 
More recent operating systems do not use the BIOS interrupt calls after startup.


Most BIOS implementations are specifically designed to work with a particular computer or motherboard model, by interfacing with various devices especially system chipset.
Originally, BIOS firmware was stored in a ROM chip on the PC motherboard. 
In later computer systems, the BIOS contents are stored on flash memory so it can be rewritten without removing the chip from the motherboard.
This allows easy, end-user updates to the BIOS firmware so new features can be added or bugs can be fixed, 
but it also creates a possibility for the computer to become infected with BIOS rootkits. Furthermore, a BIOS upgrade that fails could brick the motherboard.

MBR

## UEFI

The [Unified Extensible Firmware Interface](https://uefi.org/) (UEFI, successor of the EFI) is an interface between operating systems and firmware. 
It provides a standard environment for booting an operating system and running pre-boot applications.


It is distinct from the "MBR boot code" method that was used by legacy BIOS systems.



## Links

- [Operating Systems](/docs/CS/OS/OS.md)


## References

1. [计算机是如何启动的？](https://www.ruanyifeng.com/blog/2013/02/booting.html)