## Introduction

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