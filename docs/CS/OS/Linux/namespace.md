## 简介

命名空间将全局系统资源包装在抽象中，使命名空间内的进程看起来拥有自己的隔离的全局资源实例。
对全局资源的更改对命名空间的其他成员进程可见，但对其他进程不可见。
命名空间的一个用途是实现容器。

| 命名空间 | 标志 | 手册页 | 隔离内容 |
| --- | --- | --- | --- |
| Cgroup | CLONE_NEWCGROUP | cgroup_namespaces(7) | Cgroup 根目录 |
| IPC | CLONE_NEWIPC | ipc_namespaces(7) | System V IPC, POSIX 消息队列 |
| Network | CLONE_NEWNET | network_namespaces(7) | 网络设备、协议栈、端口等 |
| Mount | CLONE_NEWNS | mount_namespaces(7) | 挂载点 |
| PID | CLONE_NEWPID | pid_namespaces(7) | 进程 ID |
| Time | CLONE_NEWTIME | time_namespaces(7) | 启动和单调时钟 |
| User | CLONE_NEWUSER | user_namespaces(7) | 用户和组 ID |
| UTS | CLONE_NEWUTS | uts_namespaces(7) | 主机名和 NIS 域名 |

命名空间 API

除了下面描述的各种 /proc 文件外，命名空间 API 包括以下系统调用：

- clone(2)<br/>
  clone(2) 系统调用创建一个新进程。
  如果调用的 flags 参数指定了上述一个或多个 CLONE_NEW* 标志，
  则会为每个标志创建新的命名空间，并且子进程成为这些命名空间的成员。
  （此系统调用还实现了许多与命名空间无关的功能。）
- setns(2)<br/>
  setns(2) 系统调用允许调用进程加入现有命名空间。
  要加入的命名空间通过引用下面描述的 `/proc/pid/ns` 文件之一的文件描述符指定。
- unshare(2)<br/>
  unshare(2) 系统调用将调用进程移动到一个新的命名空间。
  如果调用的 flags 参数指定了上述一个或多个 CLONE_NEW* 标志，
  则会为每个标志创建新的命名空间，并且调用进程成为这些命名空间的成员。
  （此系统调用还实现了许多与命名空间无关的功能。）
- ioctl(2)<br/>
  各种 ioctl(2) 操作可用于发现关于命名空间的信息。这些操作在 ioctl_ns(2) 中描述。

pivot_root() 更改调用进程的挂载命名空间中的根挂载点。
更准确地说，它将根挂载点移动到目录 put_old，并使 new_root 成为新的根挂载点。
调用进程必须在拥有调用者挂载命名空间的用户命名空间中具有 CAP_SYS_ADMIN 能力。

如果同一挂载命名空间中的每个进程或线程的根目录和当前工作目录指向旧根目录，pivot_root() 会将其更改为 new_root。
另一方面，pivot_root() 不会更改调用者的当前工作目录（除非它在旧根目录上），因此其后应跟 chdir("/") 调用。

## 链接

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [容器](/docs/CS/Container/Container.md)
