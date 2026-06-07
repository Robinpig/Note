## 简介

LXC 是 Linux 内核容器功能的用户空间接口。
通过强大的 API 和简单的工具，它让 Linux 用户可以轻松创建和管理系统或应用程序容器。

当前 LXC 使用以下内核功能来包含进程：

- 内核命名空间（ipc、uts、mount、pid、network 和 user）
- Apparmor 和 SELinux 配置文件
- Seccomp 策略
- Chroot（使用 pivot_root）
- 内核能力
- CGroups（控制组）

我们可以简化为创建一个容器：

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

## 链接

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [容器](/docs/CS/Container/Container.md)
