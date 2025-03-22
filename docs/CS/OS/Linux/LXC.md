## Introduction

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




## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [Container](/docs/CS/Container/Container.md)
