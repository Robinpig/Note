## Introduction

Containerization is the packaging of software code with just the operating system (OS) libraries and dependencies required to run the code to create a single lightweight executable—called a container—that runs consistently on any infrastructure.
More portable and resource-efficient than virtual machines (VMs), containers have become the de facto compute units of modern cloud-native applications.

Containerization allows developers to create and deploy applications faster and more securely. 
With traditional methods, code is developed in a specific computing environment which, when transferred to a new location, often results in bugs and errors. 
For example, when a developer transfers code from a desktop computer to a VM or from a Linux to a Windows operating system. 
Containerization eliminates this problem by bundling the application code together with the related configuration files, libraries, and dependencies required for it to run. 
This single package of software or “container” is abstracted away from the host operating system, and hence, 
it stands alone and becomes portable—able to run across any platform or cloud, free of issues.

Container via Virtual Machine:

- **Container**<br/>
  Containers are an abstraction at the app layer that packages code and dependencies together. 
  Multiple containers can run on the same machine and share the OS kernel with other containers, each running as isolated processes in user space. 
  Containers take up less space than VMs (container images are typically tens of MBs in size), can handle more applications and require fewer VMs and Operating systems.
- **Virtual Machine**<br/>
  Virtual machines (VMs) are an abstraction of physical hardware turning one server into many servers.
  The hypervisor allows multiple VMs to run on a single machine.
  Each VM includes a full copy of an operating system, the application, necessary binaries and libraries – taking up tens of GBs. VMs can also be slow to boot.

根据容器运行时的资源隔离和虚拟化方式，可以将目前的主流虚拟化 + 容器技术分为这么几类：

- 标准容器，符合 OCI （Open Container Initiative）规范，如 docker/containerd，容器运行时为 runc，这是目前 k8s workload 的主要形态
- 用户态内核容器，如 gVisor，也符合 OCI 规范，容器运行时为 runsc，有比较好的隔离性和安全性，但是性能比较差，适合比较轻量的 workload
- 微内核容器，使用了 hypervisor，如 Firecracker、Kata-Container，也符合 OCI 规范，容器运行时为 runc 或 runv，有比较好的安全性和隔离性，性能介于标准容器和用户态内核容器之间
- 纯虚拟机，如 KVM、Xen、VMWare，是主流云厂商服务器的底层虚拟化技术，一般作为 k8s 中的 Node 存在，比容器要更低一个层次



容器相比虚拟化的优势在于，可以再次提高服务器的资源利用率，重量更轻，体积更小，能够匹配为服务的需求，保持多环境运行的 致性，快速部署迁移，且容错率高。

其劣势在于安全性相对较差，多容器管理有 定的难度，稳定性较差，排错难度较大





符合 OCI 规范的几款主流容器化技术做一下分析

- runc 是一个符合 OCI 标准的容器运行时，它是 Docker/Containerd 核心容器引擎的一部分。它使用 Linux 的 [Namespace](/docs/CS/OS/Linux/namespace.md) 和 [Cgroup](/docs/CS/OS/Linux/cgroup.md) 技术来实现容器的隔离
  在运行容器时，runc 使用命名空间隔离容器的进程、网络、文件系统和 IPC（进程间通信）。它还使用控制组来限制容器内进程的资源使用。这种隔离技术使得容器内的应用程序可以在一个相对独立的环境中运行，与宿主机和其他容器隔离开来。
  runc 的隔离技术虽然引入了一定开销，但是这种开销仅限于命名空间映射、限制检查和一些记账逻辑，理论上影响很小，而且当 syscall 是长耗时操作时，这种影响几乎可以忽略不计，一般情况下，基于 Namespace+Cgroup 的隔离技术对 CPU、内存、I/O 性能的影响较小
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
| Isolation   | Namespace+Cgroup | Guest Kernel           | Sandboxed Kernel     | microVM                |
| OCI Runtime | runc             | Clear Container + runv | runsc                | runc                   |
| Virtual     | Namespace        | Clear Container + runv | Rule-Based Execution | rust-VMM + KVM         |
| vCPU        | Cgroup           | Cgroup                 | Cgroup               | Cgroup                 |
| Memory      | Cgroup           | Cgroup                 | Cgroup               | Cgroup                 |
| Syscall     | Host             |                        |                      |                        |
| Disk I/O    | Host             |                        |                      |                        |
| Network I/O | Host+ veth       |                        |                      |                        |





The concept of containerization and process isolation is actually decades old, but the emergence in 2013 of the open source [Docker Engine](/docs/CS/Container/Docker.md)—an industry standard for containers 
with simple developer tools and a universal packaging approach—accelerated the adoption of this technology.


The rapid growth in interest and usage of container-based solutions has led to the need for standards around container technology and the approach to packaging software code. 
The Open Container Initiative (OCI), established in June 2015 by Docker and other industry leaders, is promoting common, minimal, open standards and specifications around container technology. 

Today, Docker is one of the most well-known and highly used container engine technologies, but it is not the only option available. 
The ecosystem is standardizing on containerd and other alternatives like CoreOS rkt, Mesos Containerizer, [LXC Linux Containers](/docs/CS/OS/Linux/LXC.md), OpenVZ, and crio-d.
Features and defaults may differ, but adopting and leveraging OCI specifications as these evolve will ensure that solutions are vendor-neutral, 
certified to run on multiple operating systems and usable in multiple environments.





## Links

- [Operating Systems](/docs/CS/OS/OS.md)


## References

1. [不敢把数据库运行在 K8s 上？容器化对数据库性能有影响吗？](https://www.infoq.cn/article/sh2tjyw1dki4zqpakujj)
