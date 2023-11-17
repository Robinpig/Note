## Introduction

Containerization is the packaging of software code with just the operating system (OS) libraries and dependencies required to 
run the code to create a single lightweight executable—called a container—that runs consistently on any infrastructure.
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



The concept of containerization and process isolation is actually decades old, but the emergence in 2013 of the open source [Docker Engine](/docs/CS/Container/Docker.md)—an industry standard for containers 
with simple developer tools and a universal packaging approach—accelerated the adoption of this technology.


The rapid growth in interest and usage of container-based solutions has led to the need for standards around container technology and the approach to packaging software code. 
The Open Container Initiative (OCI), established in June 2015 by Docker and other industry leaders, is promoting common, minimal, open standards and specifications around container technology. 

Today, Docker is one of the most well-known and highly used container engine technologies, but it is not the only option available. 
The ecosystem is standardizing on containerd and other alternatives like CoreOS rkt, Mesos Containerizer, LXC Linux Containers, OpenVZ, and crio-d. Features and defaults may differ,
but adopting and leveraging OCI specifications as these evolve will ensure that solutions are vendor-neutral, certified to run on multiple operating systems and usable in multiple environments.


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

As well as various /proc files described below, the namespaces
API includes the following system calls:

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

## Links

