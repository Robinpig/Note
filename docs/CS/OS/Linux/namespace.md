## Introduction

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




对于每一种 namespace，Linux在启动时都有一套默认值，定义在 kernel/nsproxy.c 中。


Linux启动有个 INIT_TASK 0号进程，也叫idle进程，固定使用这个默认的 init_nsproxy。






## 容器如何使用 namespace

容器 = 一组 namespace + 一个 rootfs + 一套 cgroup 限额。以 `docker run` 为例，runc 的启动路径正是教科书式的三步（伪代码见 [LXC](/docs/CS/OS/Linux/LXC.md)）：

1. **clone 创建容器主进程**：`CLONE_NEWPID|CLONE_NEWNS|CLONE_NEWUSER|CLONE_NEWNET|CLONE_NEWIPC|CLONE_NEWUTS` 一并指定，子进程一出生就活在全新的视图里（clone 的共享机制见 [pthread](/docs/CS/OS/Linux/proc/pthread.md)——同样的系统调用，flags 决定了是线程还是容器）；
2. **pivot_root 切换根文件系统**：把 overlayfs 挂载好的容器 rootfs 变成新的 `/`，配合 `chdir("/")`，进程从此"看不见"宿主机文件系统；
3. **exec 用户指定的入口程序**：映像替换后成为容器内的 PID 1。

各 namespace 在容器里的可观察现象：PID ns 让容器内 `ps` 只看到自己；NET ns 给容器独立的网卡与端口空间（veth pair 怎么接进来见 [Docker 网络](/docs/CS/Container/Docker/net.md)）；UTS ns 让每个容器有自己的 hostname。

### setns 加入已有 namespace

`docker exec` / `kubectl exec` / `nsenter` 的底层都是 setns(2)：打开目标进程的 `/proc/PID/ns/xxx` 拿到 namespace 句柄，再 setns 把当前线程"搬"进去。

这也是 [Pod 的 pause 容器](/docs/CS/Container/k8s/Pod.md?id=pause-容器)的实现机制：pause 先创建并持有 Network/IPC/UTS namespace，业务容器逐项 setns join 进来——因此业务容器崩溃重建不影响 Pod IP，只有 pause 重建才会。

观察：`ls -l /proc/$$/ns/`，两个进程某项 namespace 的链接数与 inode 号相同即共享之。

`setns` 需要一个宿主 PID 才能拿到 `/proc/PID/ns/*` 句柄，所以"先找到容器对应的进程"是 `nsenter` 的前置步骤；反过来从某个 PID 反查它属于哪个容器要靠 `/proc/PID/cgroup`，两侧的完整命令见 [容器定位](/docs/CS/Container/locate.md)。

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [Container](/docs/CS/Container/Container.md)
- [LXC](/docs/CS/OS/Linux/LXC.md) — clone + pivot_root 最小容器伪代码
- [Docker 网络](/docs/CS/Container/Docker/net.md) — NET namespace 与 veth pair
- [Pod](/docs/CS/Container/k8s/Pod.md) — pause 容器持有哪些 namespace
- [容器定位](/docs/CS/Container/locate.md) — PID ↔ 容器双向换算与 nsenter 实践
- [容器知识地图](/docs/CS/Container/README.md)
