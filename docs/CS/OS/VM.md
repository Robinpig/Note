## Introduction

A virtual machine is a virtual representation of a physical computer.
We can call the virtual machine the guest machine, and the physical computer it runs on is the host machine.

<div style="text-align: center;">

![Fig.1. VM](./img/VM.png)

</div>

<p style="text-align: center;">
Fig.1. VM.
</p>

A single physical machine can run multiple virtual machines, each with their own operating system and applications.
These virtual machines are isolated from each other.


客户机(Guest, 或者叫作虚拟机）无疑运行在主机(Host) 上， 一个主机往往有运行多个虚拟机(Virtual Mcahine)的能力， 这就需要一个虚拟机管理程序， 被称作hyperviso（r 又名 Virtual Mcahine Monitor, VMM或者Virtualizer)

第一类，hypervis01运行在裸机（称作Native 或者Bare-Metal )上。它直接运行在实际的硬件上，管理客户机操作系统(Guest OS)。
第二类，hypervisot运行在操作系统上， 与其他应用程序没有差别。hypervis01本身作为一个进程运行在主机上，Guest OS由它在主机操作系统(Host OS)的基础上抽象而来。

这两类hypervis01的差别并不是绝对的


KVM 的全称是Kernel-Based Virtual Machines ,在Linux上它是内核的一部分， 可以实现CPU和内存虚拟化。但它本身并不是一个纯软件的方案， 需要硬件支持， 比如Intel-VT和AMD-V



QEMU 并不依赖KVM 来实现虚拟化，没有KVM 支持的情况下，QEMU 有 TCG (Tiny Code Generato1) 做指令翻译，将需要运行的指令翻译成当前CPU 可执行的指令。 
有KVM 的支持的情况下， 自然就不需要TCG 了，KVM 负责CPU 和内存的虚拟化，QEMU只需要负责IO、设备虚拟化


## Tools

[vmware虚拟机软件下载地址](https://softwareupdate.vmware.com/cds/vmw-desktop/)

[Ventoy](https://www.ventoy.net/cn/index.html) 是一个制作可启动U盘的开源工具 只需要把 ISO/WIM/IMG/VHD(x)/EFI 等类型的文件直接拷贝到U盘里面就可以启动了，无需其他操作

支持Windows、Linux、FreeBSD等系统的镜像文件



Linux新版本安装 VM Tools
```shell
sudo apt install -y open-vm-tools open-vm-tools-desktop
```



## VMware

虚拟机挂载共享文件夹(需要 VM Tools)

在设置里先挂载好目录



```shell
sudo mkdir /mnt/hgfs
sudo /usr/bin/vmhgfs-fuse .host:/ /mnt/hgfs -o allow_other -ouid=1000-ogid=1000-oumask=022
```

如果之前挂载过 先 unmount
```shell
sudo umount /mnt/hgfs
```


[QEMU](/docs/CS/OS/qemu.md) 和 
[Bochs](/docs/CS/OS/Bochs.md) 用纯软件的方式完全模拟x86 CPU 和外围设备 所以运行性能较差






## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)



## References

