## Introduction

U-Boot，全称 Universal Boot Loader，是遵循GPL条款的从FADSROM、8xxROM、PPCBOOT逐步发展演化而来的 开放源码项目。

U-boot，是一个主要用于嵌入式系统的引导加载程序，可以支持多种不同的计算机系统结构，其主要作用为：引导系统的启动
目前，U-Boot不仅支持Linux系统的引导，还支持NetBSD, VxWorks, QNX, RTEMS, ARTOS, LynxOS, android等多种嵌入式操作系统

U-boot主要特性及功能
开放：开放的源代码
多平台：支持多种嵌入式操作系统，如Linux、NetBSD、android等
生态：有丰富的设备驱动源码，如以太网、SDRAM、LCD等，同时也具有丰富的开发文档



U-Boot开发源码：

https://source.denx.de/u-boot/u-boot

如何编译Uboot 

```shell
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- distclean
make ARCH=arm CORSS_COMPILE=arm-linux-gnueabihf- colibri-imx6ull_defconfig
make V=1 ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- -j8
```


U-boot的工作模式有：启动加载模式和下载模式

启动加载模式：
启动加载模式，为Bootloader正常工作模式，一款开发板，正常上电后，Bootloader将嵌入式操作系统==从FLASH中加载到SDRAM中==运行。

下载模式：
下载模式，就是Bootloader通过通信，将内核镜像、根文件系统镜像从PC机直接下载到目标板的FLASH中

嵌入式系统，一般使用Flash来作为启动设备，Flash上存储着U-boot、环境变量、内核映像、文件系统等。U-boot存放于Flash的起始地址，所在扇区由Soc规



## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)