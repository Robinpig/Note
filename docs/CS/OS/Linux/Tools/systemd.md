## Introduction


systemd不是一个命令，而是一组命令的集合，提供了一个系统和服务管理器，运行为 PID 1 并负责启动其它程序
systemd功能包括：支持并行化任务；同时采用 socket 式与 D-Bus 总线式激活服务； 按需启动守护进程（daemon）；
利用 Linux 的 cgroups 监视进程；支持快照和系统恢复； 维护挂载点和自动挂载点；各服务间基于依赖关系进行精密控制
systemd 支持 SysV 和 LSB 初始脚本，可以替代 sysvinit。除此之外， 功能还包括日志进程、控制基础系统配置，维护登陆用户列表以及系统账户、运行时目录和设置，
可以运行容器和虚拟机，可以简单的管理网络配置、网络时间同步、日志转发和名称解析等

单元，单元文件是 ini 风格的纯文本文件，Systemd 可以管理所有系统资源，不同的资源统称为 Unit（单位）
其封装了12种对象的信息：服务(service)、套接字(socket)、设备(device)、挂载点(mount)、 
自动挂载点(automount)、 启动目标(target)、交换分区或交换文件(swap)、被监视的路径(path)、 任务计划(timer)、 资源控制组(slice)、一组外部创建的进程(scope)、快照(snapshot)



## Links

- [Tools](/docs/CS/OS/Linux/Tools/Tools.md)

## References

1. [探索Systemd](https://doc.embedfire.com/lubancat/build_and_deploy/zh/latest/building_image/using_systemd/using_systemd.html)


