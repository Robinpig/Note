## Introduction

容器化（Containerization）是把软件代码连同运行它所需的操作系统库和依赖一起打包，得到一个轻量、单一的可执行单元——容器。相比虚拟机（VM），容器更便携、更省资源，已经成为现代云原生应用事实上的计算单元。

容器解决的核心问题是**环境一致性**：传统方式下，代码在某一特定计算环境开发，迁移到新环境时常冒出 bug（如桌面机 → 虚拟机、Linux → Windows）。容器化的办法是把应用代码与配置文件、库、依赖捆成一个自包含、可移植的单元，从宿主机 OS 抽象出来，于是"在我的机器上能跑"不再依赖目标主机的预装环境。

容器与虚拟机的本质区别在于抽象的层次：

- **容器** 是应用层的抽象，把代码和依赖打包在一起。多个容器共享同一个 OS 内核，各自以用户态隔离进程的形式运行，镜像通常只有几十 MB。
- **虚拟机** 是对物理硬件的抽象，由 Hypervisor 让多个 VM 共享一台物理机。每个 VM 都包含一份完整 OS、应用及必要的二进制和库，占用几十 GB，启动慢。

容器相比虚拟化的优势：进一步提高服务器资源利用率，重量轻、体积小，契合微服务粒度，多环境一致，部署迁移快，容错率高。其代价是：共享内核带来更大的安全攻击面，多容器管理、稳定性与排错难度更高。

## Container Taxonomy

根据运行时对资源隔离与虚拟化的实现方式，主流"虚拟化 + 容器"技术可以分成四类。它们不是互相替代，而是同一张"隔离强度 ↔ 性能开销"光谱上的不同落点——越往右隔离越强、越接近 VM，但启动与 syscall 开销越大：

- **标准容器**：符合 OCI 规范，运行时为 runc（如 Docker/containerd），是当今 K8s workload 的主要形态，共享宿主内核，开销最低。
- **用户态内核容器**：仍符合 OCI 规范，运行时为 runsc（如 gVisor）。在用户态实现一套"沙箱内核"拦截 syscall，隔离性与安全性更好，但 syscall 需经过模拟，性能较差，适合轻量 workload。
- **微内核 / 微虚拟机容器**：借助轻量 hypervisor（如 Firecracker、Kata Containers），运行时为 runc 或 runv。每个容器跑在独立 microVM 里，拥有自己的来宾内核，安全性与隔离性介于标准容器和纯 VM 之间，性能损耗居中。
- **纯虚拟机**：如 [KVM](/docs/CS/OS/Linux/KVM.md)、Xen、VMWare，是云厂商服务器的底层虚拟化，通常作为 K8s 的 Node 存在，比容器低一个层次。

## OCI and the Container Ecosystem

容器化与进程隔离的概念其实已有几十年历史，但真正让它普及的是 2013 年开源的 [Docker Engine](/docs/CS/Container/Docker/Docker.md)：它用简洁的开发者工具和通用打包格式，把容器变成了工业标准。

容器关注度的快速增长催生了标准化的需求。2015 年 6 月，Docker 联合其他行业领导者发起开放容器倡议（OCI, Open Container Initiative），推动容器镜像格式与运行时接口的通用、最小化开放标准。今天，Docker 仍是最知名的容器引擎，但整个生态正在向 [containerd](/docs/CS/Container/k8s/containerd.md) 收敛；此外还有 CoreOS rkt、Mesos Containerizer、[LXC Linux Containers](/docs/CS/OS/Linux/LXC.md)、OpenVZ、cri-o 等替代实现。只要跟进 OCI 规范演进，就能保证方案厂商中立、跨 OS 可运行。

[Docker 枢纽](/docs/CS/Container/Docker/Docker.md) 进一步拆解了镜像、网络、存储、构建与安全的分册脉络。

## The Core Mechanism: Namespace and Cgroup

容器技术的核心，是通过**约束和修改进程的动态表现**，给进程创造出一个"边界"。内核里并没有"容器"这个对象——只有"进程 + namespace 成员身份 + cgroup 归属"。这条边界由两样 Linux 原语共同构成（详见 OS 层笔记）：

- [Namespace](/docs/CS/OS/Linux/namespace.md) 负责"看得见什么"：隔离 PID、网络、挂载点、IPC 等视图，让容器以为自己独占了这些资源。
- [Cgroup](/docs/CS/OS/Linux/cgroup.md) 负责"能用多少"：限制容器内进程可消耗的 CPU、内存、I/O 等资源。

正是 Namespace+Cgroup 的组合，使得容器内应用能在相对独立的环境里运行，又几乎不引入内核态开销——隔离开销仅限于命名空间映射、限制检查和记账逻辑，对 CPU/内存/I/O 性能影响很小。完整的运行时调用链路（kubelet → CRI → containerd → containerd-shim → runc）见 [containerd 运行时](/docs/CS/Container/k8s/containerd.md)。

## Container Filesystem: Namespace and Layering

容器的"文件系统边界"由两层叠加而成，二者都在 OS 层有专门笔记，这里只串起关系、不展开细节：

- **视图隔离靠 Mount Namespace。** 它让容器拥有独立的挂载点视图——新容器默认继承宿主机挂载点，直到一次 `mount` 操作改写视图（见 [Namespace](/docs/CS/OS/Linux/namespace.md) 的 Mount Namespace 部分）。这解释了为什么容器里看到的根文件系统与宿主机不同，却仍共享同一个内核。
- **内容落地靠镜像分层 + 写时复制。** 容器的 rootfs 不是一份完整拷贝，而是镜像的多层只读层叠加一层可写层，再由 [overlayfs](/docs/CS/OS/Linux/fs/overlayfs.md) 以 union-mount 合并、对可写层做 CoW。分层与内容寻址、registry 交互、体积优化的细节见 [Docker 镜像](/docs/CS/Container/Docker/image.md)；volume / bind / tmpfs 与存储驱动（overlay2、containerd snapshotter）的落地见 [Docker 存储](/docs/CS/Container/Docker/storage.md)。

一句话：Mount Namespace 决定容器"看得见哪些挂载点"，overlayfs 决定这些挂载点背后"怎么合并多层、怎么写"。二者共同构成容器文件系统的实现原理，与 Namespace + Cgroup 的边界机制正交、互为补充。

## Runtime Landscape

在 OCI 规范的统一下，几款主流运行时各有取舍。下面按"隔离实现"而非"厂商"来对比，便于按 workload 选型：

- **runc**（Docker/Containerd 核心引擎）用 Namespace+Cgroup 实现隔离，开销最小，但共享宿主内核、隔离最弱。
- **Kata Containers** 在每个容器里跑一个独立 microVM（源自 Intel Clear Containers），拥有独立来宾内核，隔离性接近 VM；代价是 VM 启动与管理开销，syscall 与 I/O 有额外损耗。
- **gVisor** 用用户态"沙箱内核"拦截 syscall，容器内应用与宿主内核完全隔离，安全性好；但因 syscall 要经过模拟，性能开销明显，适合不可信或轻量 workload。
- **Firecracker** 面向无服务器 / 轻量负载的微虚拟化，每个容器是一个独立 microVM，基于 KVM，配独立虚拟设备模拟器；安全性与隔离性好，但 syscall 与 I/O 开销最大。

|                    | Containerd-runc        | Kata Containers              | gVisor                     | Firecracker-Containerd        |
|--------------------|------------------------|------------------------------|----------------------------|--------------------------------|
| 隔离机制            | Namespace+Cgroup       | 来宾内核（Guest Kernel）      | 沙箱内核（Sandboxed Kernel） | 微虚拟机（microVM）            |
| OCI 运行时          | runc                   | Clear Container + runv       | runsc                      | runc                           |
| 虚拟化方式          | Namespace              | Clear Container + runv       | 规则化执行（Rule-Based Execution） | rust-VMM + KVM          |
| vCPU               | Cgroup                 | Cgroup                       | Cgroup                     | Cgroup                         |
| 内存               | Cgroup                 | Cgroup                       | Cgroup                     | Cgroup                         |
| 系统调用            | 宿主内核               | 来宾内核                     | 沙箱内核                   | microVM 内核                   |
| 磁盘 I/O           | 宿主内核               | 来宾内核                     | 沙箱内核                   | microVM 内核                   |
| 网络 I/O           | 宿主内核 + veth        | 来宾内核 + 虚拟网卡           | 沙箱内核 + 虚拟网卡        | microVM 内核 + 虚拟网卡        |

> 运行时细节与"隔离四道防线"见 [Docker 运行时](/docs/CS/Container/Docker/runtime.md)。

## Limitations and Security

共享内核是容器的根本约束，由此带来一系列必须正视的局限：

**共享内核与安全攻击面。** 即便可以通过 Mount Namespace 单独挂载 CentOS / Ubuntu 的根文件系统，也无法改变共享宿主内核的事实——在 Windows 宿主机上跑 Linux 容器、或在低版本 Linux 上跑高版本 Linux 容器都不成立。Linux 内核里还有大量资源 / 对象无法被 Namespace 化，最典型的是**时间**：容器内用 `settimeofday(2)` 修改时间会直接改掉整个宿主机的时间，这显然不符合预期。共享内核意味着容器暴露给应用的攻击面相当大，"越狱"难度比 VM 低得多。

**Seccomp 加固的代价。** 实践中可用 Seccomp 过滤容器内部发起的所有 syscall 来加固，但这层过滤必然拖累性能；而且默认情况下，没人能说清该放行哪些、禁止哪些 syscall。性能与可维护性的代价，使得生产环境很少把裸 Linux 容器直接暴露到公网——相关默认与最佳实践见 [Docker 安全](/docs/CS/Container/Docker/security.md)。

**Cgroup 与 /proc 的错位。** Cgroup 对资源的限制也不完善，最常被提到的是 `/proc` 文件系统问题：在容器里执行 `top`，显示的是宿主机的 CPU / 内存而非当前容器的数据，因为 `/proc` 不知道 Cgroup 的限制存在（详见 [cgroup v1 与 v2](/docs/CS/OS/Linux/cgroup.md?id=cgroup-v1-vs-v2)，生产环境常用 lxcfs 修正）。

**Mount Namespace 的生效方式。** Mount Namespace 改变的是容器进程对文件系统"挂载点"的认知，且对视图的改变必须伴随一次 `mount` 操作才生效；在此之前，新容器会直接继承宿主机的各挂载点。

## Container Locating: Container <-> Host Process

容器不是一个内核认得的对象，内核里只有"进程 + namespace 成员身份 + cgroup 归属"。因此排障时真正的动作，是在**容器 ID ↔ 宿主机 PID ↔ namespace / cgroup** 之间做双向换算：容器里的 PID 1 在宿主机上往往是个普通 PID（`NSpid` 一行就能读出两套编号），反过来从 `top` 里冒出来的异常进程要靠 `/proc/PID/cgroup` 认祖归宗。

```
容器 ID ──► docker inspect / crictl inspect ──► 宿主机 PID ──► /proc/PID/{status,cgroup,ns,root,fd}
宿主机 PID ──► /proc/PID/cgroup ──► 容器 ID / Pod UID ──► 容器名
```

两条路都会失效的典型场景是镜像里没有 shell（`exec` 用不了）和 daemon 自己挂了，这时只有绕到 `/proc` 才拿得到答案。完整命令清单、K8s 侧链路（kubectl → 节点 → crictl → nsenter）与常见例外见 [容器定位](/docs/CS/Container/locate.md)。

## Container Orchestration

> 容器本身没有价值，有价值的是"容器编排"

正因为如此，容器技术生态才爆发了一场关于"容器编排"的"战争"，最终以 [Kubernetes](/docs/CS/Container/k8s/K8s.md) 项目和 CNCF 社区的胜利而告终。最具代表性的编排工具，是 Docker 公司的 Compose+Swarm 组合，以及 Google 与 RedHat 共同主导的 Kubernetes 项目。

编排层的内部结构——四条主链路如何串行分布式组件的读写、为什么"唯一的写入口 + 自治控制回路"这个模型能让组件互不相识却最终收敛——见 [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)。

编排之上还有四层云原生能力，它们回答的是不同问题：**怎么跑**（[工作负载控制器](/docs/CS/Container/k8s/Workloads.md)：Deployment / StatefulSet / DaemonSet / Job / CronJob 对 Pod 身份与顺序的不同假设）、**怎么扩展**（[扩展机制](/docs/CS/Container/k8s/Extension.md)：CRD、Operator、聚合 API、准入 Webhook）、**怎么观测**（[可观测性](/docs/CS/Container/k8s/Observability.md)：kubelet 指标端点、metrics API、容器日志与 OTLP 链路）、**怎么交付**（[GitOps](/docs/CS/Container/k8s/GitOps.md)：以 Git 为唯一期望状态、由集群内 agent 持续拉取）。四者都不改变"声明期望、控制器收敛"这条主线，只是把这条主线分别用在对象模型、API 表面、运行时可观测性和发布流程上。

## Links

- [Namespace](/docs/CS/OS/Linux/namespace.md)
- [Cgroup](/docs/CS/OS/Linux/cgroup.md)
- [Docker](/docs/CS/Container/Docker/Docker.md)
- [Kubernetes](/docs/CS/Container/k8s/K8s.md)
- [容器定位](/docs/CS/Container/locate.md)
- [容器知识地图](/docs/CS/Container/README.md)

## References

1. [不敢把数据库运行在 K8s 上？容器化对数据库性能有影响吗？](https://www.infoq.cn/article/sh2tjyw1dki4zqpakujj)
