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


## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [Container](/docs/CS/Container/Container.md)
