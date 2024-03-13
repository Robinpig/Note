## Introduction

A bootloader is a program written to load a more complex kernel.

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
