## Introduction

容器化（Containerization）是把软件代码连同运行它所需的操作系统库和依赖一起打包，得到一个轻量、单一的可执行单元——容器——它在任何基础设施上都能一致地运行。相比虚拟机（VM），容器更便携、更省资源，已经成为现代云原生应用事实上的计算单元。

容器化让开发者可以更快、更安全地创建和部署应用。传统方式下，代码是在某个特定计算环境中开发的，迁移到新环境时常常冒出一堆 bug 和错误，比如把代码从桌面机迁到虚拟机，或从 Linux 迁到 Windows。容器化的解决办法是把应用代码与它运行所需的配置文件、库、依赖捆在一起。这个单一的软件包（即"容器"）从宿主机操作系统中抽象出来，因此它是自包含、可移植的——可以在任意平台或云上运行而不出问题。

容器与虚拟机的对比：

- **容器**<br/>
  容器是应用层的抽象，把代码和依赖打包在一起。多个容器可以跑在同一台机器上，共享同一个操作系统内核，各自以用户态隔离进程的形式运行。容器占用空间比虚拟机小得多（镜像通常只有几十 MB），能承载更多应用，需要的虚拟机和操作系统也更少。
- **虚拟机**<br/>
  虚拟机是对物理硬件的抽象，把一台服务器变成多台。Hypervisor 让多个虚拟机跑在同一台机器上。每个虚拟机都包含一份完整的操作系统、应用以及必要的二进制和库——占用几十 GB，启动也慢。

根据容器运行时的资源隔离和虚拟化方式，可以将目前的主流虚拟化 + 容器技术分为这么几类：

- 标准容器，符合 OCI （Open Container Initiative）规范，如 docker/containerd，容器运行时为 runc，这是目前 k8s workload 的主要形态
- 用户态内核容器，如 gVisor，也符合 OCI 规范，容器运行时为 runsc，有比较好的隔离性和安全性，但是性能比较差，适合比较轻量的 workload
- 微内核容器，使用了 hypervisor，如 Firecracker、Kata-Container，也符合 OCI 规范，容器运行时为 runc 或 runv，有比较好的安全性和隔离性，性能介于标准容器和用户态内核容器之间
- 纯虚拟机，如 [KVM](/docs/CS/OS/Linux/KVM.md)、Xen、VMWare，是主流云厂商服务器的底层虚拟化技术，一般作为 k8s 中的 Node 存在，比容器要更低一个层次



容器相比虚拟化的优势在于，可以再次提高服务器的资源利用率，重量更轻，体积更小，能够匹配微服务的需求，保持多环境运行的一致性，快速部署迁移，且容错率高。

其劣势在于安全性相对较差，多容器管理有一定的难度，稳定性较差，排错难度较大



容器技术的核心功能，就是通过约束和修改进程的动态表现，从而为其创造出一个“边界”

符合 OCI 规范的几款主流容器化技术做一下分析

- runc 是一个符合 OCI 标准的容器运行时，它是 Docker/Containerd 核心容器引擎的一部分。它使用 Linux 的 [Namespace](/docs/CS/OS/Linux/namespace.md) 和 [Cgroup](/docs/CS/OS/Linux/cgroup.md) 技术来实现容器的隔离
  在运行容器时，runc 使用命名空间隔离容器的进程、网络、文件系统和 IPC（进程间通信）。它还使用控制组来限制容器内进程的资源使用。这种隔离技术使得容器内的应用程序可以在一个相对独立的环境中运行，与宿主机和其他容器隔离开来。
  runc 的隔离技术虽然引入了一定开销，但是这种开销仅限于命名空间映射、限制检查和一些记账逻辑，理论上影响很小，而且当 syscall 是长耗时操作时，这种影响几乎可以忽略不计，一般情况下，基于 Namespace+Cgroup 的隔离技术对 CPU、内存、I/O 性能的影响较小
  容器运行时的完整调用链路（kubelet → CRI → containerd → containerd-shim → runc）见 [containerd 运行时](/docs/CS/Container/k8s/containerd.md)。
- Kata Containers 是一个使用虚拟机技术实现的容器运行时，它提供了更高的隔离性和安全性。Kata Containers 使用了 Intel 的 Clear Containers 技术，并结合了轻量级虚拟机监控器和容器运行时。
  Kata Containers 在每个容器内运行一个独立的虚拟机，每个虚拟机都有自己的内核和用户空间。这种虚拟化技术能够提供更严格的隔离，使得容器内的应用程序无法直接访问宿主机的资源。
  然而，由于引入了虚拟机的启动和管理开销，相对于传统的容器运行时，Kata Containers 在系统调用和 I/O 性能方面可能会有一些额外的开销
- gVisor 是一个使用用户态虚拟化技术实现的容器运行时，它提供了更高的隔离性和安全性。gVisor 使用了自己的内核实现，在容器内部运行
  gVisor 的内核实现，称为 “Sandboxed Kernel”，在容器内部提供对操作系统接口的模拟和管理。容器内的应用程序和进程与宿主内核隔离开来，无法直接访问或影响宿主内核的资源。这种隔离技术在提高安全性的同时，相对于传统的容器运行时，可能会引入一些额外的系统调用和 I/O 性能开销
- Firecracker 是一种针对无服务器计算和轻量级工作负载设计的虚拟化技术。它使用了微虚拟化技术，将每个容器作为一个独立的虚拟机运行。
  Firecracker 使用 KVM（Kernel-based Virtual Machine）技术作为底层虚拟化技术。每个容器都在自己的虚拟机中运行，拥有独立的内核和根文件系统，并使用独立的虚拟设备模拟器与宿主机通信。
  这种隔离技术提供了较高的安全性和隔离性，但相对于传统的容器运行时，Firecracker 可能会引入更大的系统调用和 I/O 性能开销


|             | Containerd-runc  | Kata-Container         | gVisor               | FireCracker-Containerd |
|-------------|------------------|------------------------|----------------------|------------------------|
| 隔离机制     | Namespace+Cgroup | 来宾内核（Guest Kernel） | 沙箱内核（Sandboxed Kernel） | 微虚拟机（microVM）  |
| OCI 运行时   | runc             | Clear Container + runv | runsc                | runc                   |
| 虚拟化方式   | Namespace        | Clear Container + runv | 规则化执行（Rule-Based Execution） | rust-VMM + KVM |
| vCPU        | Cgroup           | Cgroup                 | Cgroup               | Cgroup                 |
| 内存        | Cgroup           | Cgroup                 | Cgroup               | Cgroup                 |
| 系统调用     | 宿主内核          |                        |                      |                        |
| 磁盘 I/O    | 宿主内核          |                        |                      |                        |
| 网络 I/O    | 宿主内核 + veth   |                        |                      |                        |





容器化与进程隔离的概念其实已经有几十年历史，但真正让这项技术加速普及的，是 2013 年开源的 [Docker Engine](/docs/CS/Container/Docker/Docker.md)：它用简洁的开发者工具和通用的打包方式，成了容器的工业标准。

基于容器的方案在关注和落地上的快速增长，催生了对容器技术以及软件打包方式进行标准化的需求。2015 年 6 月，Docker 与其他行业领导者共同发起开放容器倡议（OCI, Open Container Initiative），推动容器技术通用、最小化的开放标准与规范。

今天，Docker 是最知名、使用最广泛的容器引擎技术，但它并不是唯一选择。整个生态正在向 containerd 收敛，此外还有 CoreOS rkt、Mesos Containerizer、[LXC Linux Containers](/docs/CS/OS/Linux/LXC.md)、OpenVZ、crio-d 等替代方案。各家实现的特性与默认值可能不同，但只要跟进 OCI 规范的演进，就能保证方案保持厂商中立、能在多个操作系统上运行、并适用于多种环境。



尽管你可以在容器里通过Mount Namespace单独挂载其他不同版本的操作系统文件，比如CentOS或者Ubuntu，但这并不能改变共享宿主机内核的事实。这意味着，如果你要在Windows宿主机上运行Linux容器，或者在低版本的Linux宿主机上运行高版本的Linux容器，都是行不通的
其次，在Linux内核中，有很多资源和对象是不能被Namespace化的，最典型的例子就是：时间。
这就意味着，如果你的容器中的程序使用settimeofday(2)系统调用修改了时间，整个宿主机的时间都会被随之修改，这显然不符合用户的预期
由于上述问题，尤其是共享宿主机内核的事实，容器给应用暴露出来的攻击面是相当大的，应用“越狱”的难度自然也比虚拟机低得多

更为棘手的是，尽管在实践中我们确实可以使用Seccomp等技术，对容器内部发起的所有系统调用进行过滤和甄别来进行安全加固，但这种方法因为多了一层对系统调用的过滤，必然会拖累容器的性能。何况，默认情况下，谁也不知道到底该开启哪些系统调用，禁止哪些系统调用。
所以，在生产环境中，没有人敢把运行在物理机上的Linux容器直接暴露到公网上



跟Namespace的情况类似，Cgroups对资源的限制能力也有很多不完善的地方，被提及最多的自然是/proc文件系统的问题

在容器里执行top指令，就会发现，它显示的信息居然是宿主机的CPU和内存数据，而不是当前容器的数据。
造成这个问题的原因就是，/proc文件系统并不知道用户通过Cgroups给这个容器做了什么样的资源限制，即：/proc文件系统不了解Cgroups限制的存在（详见 [cgroup v1 与 v2](/docs/CS/OS/Linux/cgroup.md?id=cgroup-v1-与-v2)，生产环境常用 lxcfs 修正）

Mount Namespace修改的，是容器进程对文件系统“挂载点”的认知
跟其他Namespace的使用略有不同的地方：它对容器进程视图的改变，一定是伴随着挂载操作（mount）才能生效 在此之前，新创建的容器会直接继承宿主机的各个挂载点


## 容器定位：容器 ↔ 宿主机进程

容器不是一个内核认得的对象，内核里只有"进程 + namespace 成员身份 + cgroup 归属"。因此排障时真正的动作，是在**容器 ID ↔ 宿主机 PID ↔ namespace / cgroup** 之间做双向换算：容器里的 PID 1 在宿主机上往往是个普通 PID（`NSpid` 一行就能读出两套编号），反过来从 `top` 里冒出来的异常进程要靠 `/proc/PID/cgroup` 认祖归宗。

```
容器 ID ──► docker inspect / crictl inspect ──► 宿主机 PID ──► /proc/PID/{status,cgroup,ns,root,fd}
宿主机 PID ──► /proc/PID/cgroup ──► 容器 ID / Pod UID ──► 容器名
```

两条路都会失效的典型场景是镜像里没有 shell（`exec` 用不了）和 daemon 自己挂了，这时只有绕到 `/proc` 才拿得到答案。完整命令清单、K8s 侧链路（kubectl → 节点 → crictl → nsenter）与常见例外见 [容器定位](/docs/CS/Container/locate.md)。


## 容器编排

> 容器本身没有价值，有价值的是“容器编排”

正因为如此，容器技术生态才爆发了一场关于"容器编排"的"战争"。而这次战争，最终以 [Kubernetes](/docs/CS/Container/k8s/K8s.md) 项目和 CNCF 社区的胜利而告终
最具代表性的容器编排工具，当属Docker公司的Compose+Swarm组合，以及Google与RedHat公司共同主导的Kubernetes项目

编排层的内部结构——四条主链路如何串行分布式组件的读写、为什么"唯一的写入口 + 自治控制回路"这个模型能让组件互不相识却最终收敛——见 [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)。




## Links

- [Operating Systems](/docs/CS/OS/OS.md)
- [Namespace](/docs/CS/OS/Linux/namespace.md)
- [Cgroup](/docs/CS/OS/Linux/cgroup.md)
- [Docker](/docs/CS/Container/Docker/Docker.md)
- [Kubernetes](/docs/CS/Container/k8s/K8s.md)
- [容器知识地图](/docs/CS/Container/README.md)
- [容器定位](/docs/CS/Container/locate.md)


## References

1. [不敢把数据库运行在 K8s 上？容器化对数据库性能有影响吗？](https://www.infoq.cn/article/sh2tjyw1dki4zqpakujj)
