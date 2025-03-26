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

[vmware虚拟机软件下载地址](https://softwareupdate.vmware.com/cds/vmw-desktop/)

[Ventoy](https://www.ventoy.net/cn/index.html) 是一个制作可启动U盘的开源工具 只需要把 ISO/WIM/IMG/VHD(x)/EFI 等类型的文件直接拷贝到U盘里面就可以启动了，无需其他操作

支持Windows、Linux、FreeBSD等系统的镜像文件



Linux新版本安装 VM Tools
```shell
sudo apt install -y open-vm-tools open-vm-tools-desktop
```



## VMware

虚拟机挂载共享文件夹
```shell
vmhgfs-fuse .host:/ /mnt/hgfs -o rw,allow_other
```



[QEMU](/docs/CS/OS/qemu.md) 和 
[Bochs](/docs/CS/OS/Bochs.md) 用纯软件的方式完全模拟x86 CPU 和外围设备 所以运行性能较差






## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)



## References

