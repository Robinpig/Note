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

- runc 是一个符合 OCI 标准的容器运行时，它是 Docker/Containerd 核心容器引擎的一部分。它使用 Linux 的命名空间（Namespace）和控制组（Cgroup）技术来实现容器的隔离
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
The ecosystem is standardizing on containerd and other alternatives like CoreOS rkt, Mesos Containerizer, LXC Linux Containers, OpenVZ, and crio-d.
Features and defaults may differ, but adopting and leveraging OCI specifications as these evolve will ensure that solutions are vendor-neutral, 
certified to run on multiple operating systems and usable in multiple environments.






## LXC

LXC is a userspace interface for the Linux kernel containment features. 
Through a powerful API and simple tools, it lets Linux users easily create and manage system or application containers.

Current LXC uses the following kernel features to contain processes:

- Kernel namespaces (ipc, uts, mount, pid, network and user)
- Apparmor and SELinux profiles
- Seccomp policies
- Chroots (using pivot_root)
- Kernel capabilities
- CGroups (control groups)

We can simplify to create a container:

```c
pid = clone(fun, stack, flags, clone_arg);
(flags: CLONE_NEWPID  | CLONE_NEWNS  |
    CLONE_NEWUSER | CLONE_NEWNET |
    CLONE_NEWIPC  | CLONE_NEWUTS |
    ...)

echo $pid > /sys/fs/cgroup/cpu/tasks
echo $pid > /sys/fs/cgroup/cpuset/tasks
echo $pid > /sys/fs/cgroup/blkio/tasks
echo $pid > /sys/fs/cgroup/memory/tasks
echo $pid > /sys/fs/cgroup/devices/tasks
echo $pid > /sys/fs/cgroup/freezer/tasks

fun()
{
    ...
    pivot_root("path_of_rootfs/", path);
    ...
    exec("/bin/bash");
    ...
}
```





## cgroup

"cgroup" stands for "control group" and is never capitalized.
The singular form is used to designate the whole feature and also as a qualifier as in "cgroup controllers". 
When explicitly referring to multiple individual control groups, the plural form "cgroups" is used.

cgroup is a mechanism to organize processes hierarchically and distribute system resources along the hierarchy in a controlled and configurable manner.

cgroup is largely composed of two parts - the core and controllers. 
cgroup core is primarily responsible for hierarchically organizing processes. 
A cgroup controller is usually responsible for distributing a specific type of system resource along the hierarchy although there are utility controllers which serve purposes other than resource distribution.

cgroups form a tree structure and every process in the system belongs to one and only one cgroup.
All threads of a process belong to the same cgroup.
On creation, all processes are put in the cgroup that the parent process belongs to at the time.
A process can be migrated to another cgroup. Migration of a process doesn't affect already existing descendant processes.

Following certain structural constraints, controllers may be enabled or disabled selectively on a cgroup. 
All controller behaviors are hierarchical - if a controller is enabled on a cgroup, it affects all processes which belong to the cgroups consisting the inclusive sub-hierarchy of the cgroup. 
When a controller is enabled on a nested cgroup, it always restricts the resource distribution further.
The restrictions set closer to the root in the hierarchy can not be overridden from further away.

cgroups are, therefore, a facility built into the kernel that allow the administrator to set resource utilization limits on any process on the system. 
In general, cgroups control:

- The number of CPU shares per process.
- The limits on memory per process.
- Block Device I/O per process.
- Which network packets are identified as the same type so that another application can enforce network traffic rules.

```shell
cd /sys/fs/cgroup/cpu,cpuacct
mkdir test
cd test
echo 100000 > cpu.cfs_period_us // 100ms 
echo 100000 > cpu.cfs_quota_us //200ms 
echo {$pid} > cgroup.procs
```

All cgroup_subsys_state(such as cpu, cpuset and memory) are inherited from different ancestors.

| cgroup_subsys_state type | ancestor |
| --- | --- |
| cpu |  task_group |
| memory | mem_cgroup |
| dev | dev_cgroup |


```c
struct cgroup {
	/* Private pointers for each registered subsystem */
	struct cgroup_subsys_state __rcu *subsys[CGROUP_SUBSYS_COUNT];
};  
```


Let's see the task_struct.

```c
struct task_struct {
  #ifdef CONFIG_CGROUPS
	/* Control Group info protected by css_set_lock: */
	struct css_set __rcu		*cgroups;
	/* cg_list protected by css_set_lock and tsk->alloc_lock: */
	struct list_head		cg_list;
#endif
}
```

A css_set is a structure holding pointers to a set of cgroup_subsys_state objects.
This saves space in the task struct object and speeds up `fork()`/`exit()`, since a single inc/dec and a list_add()/del() can bump the reference count on the entire cgroup set for a task.

```c
struct css_set {
	/*
	 * Set of subsystem states, one for each subsystem. This array is
	 * immutable after creation apart from the init_css_set during
	 * subsystem registration (at boot time).
	 */
	struct cgroup_subsys_state *subsys[CGROUP_SUBSYS_COUNT];
}    
```





## Namespace

A namespace wraps a global system resource in an abstraction that makes it appear to the processes within the namespace that they have their own isolated instance of the global resource.
Changes to the global resource are visible to other processes that are members of the namespace, but are invisible to other processes.
One use of namespaces is to implement containers.

| Namespace | Flag |            Page                  | Isolates |
| --- | --- | --- | --- |
| Cgroup |    CLONE_NEWCGROUP | cgroup_namespaces(7)  | Cgroup root directory |
| IPC |       CLONE_NEWIPC |    ipc_namespaces(7)     | System V IPC, POSIX message queues |
| Network |   CLONE_NEWNET |    network_namespaces(7) | Network devices, stacks, ports, etc. |
| Mount |     CLONE_NEWNS |     mount_namespaces(7)   | Mount points |
| PID |       CLONE_NEWPID |    pid_namespaces(7)     | Process IDs |
| Time |      CLONE_NEWTIME |   time_namespaces(7)    | Boot and monotonic clocks |
| User |      CLONE_NEWUSER |   user_namespaces(7)    | User and group IDs |
| UTS |       CLONE_NEWUTS |    uts_namespaces(7)     | Hostname and NIS domain name |

The namespaces API

As well as various /proc files described below, the namespaces API includes the following system calls:

- clone(2)<br/>
  The clone(2) system call creates a new process.  
  If the flags argument of the call specifies one or more of the CLONE_NEW* flags listed above, 
  then new namespaces are created for each flag, and the child process is made a member of those namespaces. 
  (This system call also implements a number of features unrelated to namespaces.)
- setns(2)<br/>
  The setns(2) system call allows the calling process to join an existing namespace.  
  The namespace to join is specified via a file descriptor that refers to one of the `/proc/pid/ns` files described below.
- unshare(2)<br/>
  The unshare(2) system call moves the calling process to a new namespace. 
  If the flags argument of the call specifies one or more of the CLONE_NEW* flags listed above,
  then new namespaces are created for each flag, and the calling process is made a member of those namespaces.
  (This system call also implements a number of features unrelated to namespaces.)
- ioctl(2)<br/>
  Various ioctl(2) operations can be used to discover information about namespaces.  These operations are described in ioctl_ns(2).


pivot_root() changes the root mount in the mount namespace of the calling process.
More precisely, it moves the root mount to the directory put_old and makes new_root the new root mount.
The calling process must have the CAP_SYS_ADMIN capability in the user namespace that owns the caller's mount namespace.

pivot_root() changes the root directory and the current working directory of each process or thread in the same mount namespace to new_root if they point to the old root directory.
On the other hand, pivot_root() does not change the caller's current working directory (unless it is on the old root directory), and thus it should be followed by a chdir("/") call.





## Links



## References
1. [](https://www.infoq.cn/article/sh2tjyw1dki4zqpakujj)
