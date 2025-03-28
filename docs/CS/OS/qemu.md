## Introduction

[QEMU](https://www.qemu.org/) is a generic and open source machine emulator and virtualizer.

QEMU can be used in several different ways.
The most common is for System Emulation, where it provides a virtual model of an entire machine (CPU, memory and emulated devices) to run a guest OS.
In this mode the CPU may be fully emulated, or it may work with a hypervisor such as KVM, Xen or Hypervisor.Framework to allow the guest to run directly on the host CPU.

The second supported way to use QEMU is User Mode Emulation, where QEMU can launch processes compiled for one CPU on another CPU.
In this mode the CPU is always emulated.


### Installing

<!-- tabs:start -->

##### **CentOS**

```shell
yum install qemu

# if no qemu
yum -y install epel-release
```

##### **Ubuntu**

```shell
apt-get install qemu-system
```

##### **MacOS**

```shell
brew install qemu
```


<!-- tabs:end -->


### Build
<!-- tabs:start -->
##### **Docker**



<!-- tabs:end -->



## arch

qemu-system-aarch64出现如下报错
> there is no default Use -machine help to list supported machines

使用`qemu-system-aarch64`需要 -M指定machine


qemu-system-aarch64 CPU 100%

添加`-nographic`参数解决如下问题
> Could not initialize SDL(No available video device) - exiting


```shell
p %eip
```





## Links

- [Operating System](/docs/CS/OS/OS.md)
- [Computer Organization](/docs/CS/CO/CO.md)
- [VM](/docs/CS/OS/VM.md)

## References

1. [Qemu 4.2.1 版本构建](https://runsisi.com/2024/06/23/qemu/)