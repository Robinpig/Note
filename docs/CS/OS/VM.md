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


## VMware

虚拟机挂载共享文件夹
```shell
vmhgfs-fuse .host:/ /mnt/hgfs -o rw,allow_other
```


## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)



## References

