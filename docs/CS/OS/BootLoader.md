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


CS: 0xffff
IP: 0

Linux

- bootsect.S
- sctup.S
- video.S

head.S

## BIOS

MBR

## UEFI

EFI

## Links

- [Operating Systems](/docs/CS/OS/OS.md)
