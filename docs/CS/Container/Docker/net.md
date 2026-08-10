## Introduction

标准的Docker支持以下网络模式
- host：使用--net=host指定
- container：使用--net=container:NAME_or_ID 指定
- none：使用--net=none指定
- bridge：使用 --net=brige指定，默认设置


在 bridge模式下首次启动会创建一个虚拟网桥，默认名称 docker0，按照 RFC1918模型在私有网络命名空间给网桥分配一个子网。
对每一个创建的容器都会创建一个虚拟以太网设备（Veth设备对），其中一端关联到网桥上，另一端使用Linux的网络命名空间技术映射到容器的 eth0 设备，然后在网桥的地址段内给 eth0 接口分配一个IP地址。

这样做的结果是在同一台机器的容器之间可以互相通信，不同机器上的容器不能互相通信，即使它们可能在相同的网络地址范围（不同主机上的docker0地址段可能是一样的）。



若要实现

## Links

- [Docker](/docs/CS/Container/Docker/Docker.md)