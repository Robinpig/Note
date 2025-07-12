## Introduction


proc文件系统也是一个基于内存的文件系统，方便用户空间访间内核数据结构、更改内核某些设置
它一般挂载到／proc上， 包含内存、进程的信息、终端和系统控制参数等多方面信息，可谓包罗万象。
最早用于提供进程运行时信息 后来很多系统级的内核信息也加入进来

proc定义了一个贯穿始终的结构体 proc_dir_entry


目录的proc_iops 为proc_dir_inode_operations, 只定义了lookup、getatt1 和 setattr 三个操作， 没有create 和mkdir, 所以proc 文件系统不支待用户空间直接创建文件
显然，proc 的文件都是内核各个模块创建的，proc 提供了创建文件的函数供各模块使用


/proc/cpuinfo

/proc/meminfo

/proc/kallsyms

/proc/interrupts

/proc/loadavg























## Links

- [fs](/docs/CS/OS/Linux/fs/fs.md)