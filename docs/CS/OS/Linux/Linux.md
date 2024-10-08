## Introduction

Linux is the kernel: the program in the system that allocates the machine's resources to the other programs that you run.
The kernel is an essential part of an operating system, but useless by itself; it can only function in the context of a complete operating system.
Linux is normally used in combination with the GNU operating system: the whole system is basically GNU with Linux added, or GNU/Linux.
All the so-called “Linux” distributions are really distributions of GNU/Linux.

On a purely technical level, the kernel is an intermediary layer between the hardware and the software.
Its purpose is to pass application requests to the hardware and to act as a low-level driver to address the devices and components of the system.

常见Linux发行版

- Red Hat Enterprise Linux
- [Fedora](/docs/CS/OS/Linux/Distribution/Fedora.md)
- [Ubuntu](/docs/CS/OS/Linux/Distribution/Ubuntu.md)
- [CentOS](/docs/CS/OS/Linux/Distribution/CentOS.md)
- Debian
- Arch Linux

跨平台在其它OS下使用Linux

- Docker
- 虚拟机

Windows下使用Linux

- [WSL](/docs/CS/OS/Windows/WSL.md)

## Kernel

阅读

执行 ctags -R 生成索引文件 tags


ctrl + ] 进入函数定义
g, ctrl + ] 进入函数定义 可选择
ctrl + o 返回

在线阅读

[bootlin](https://elixir.bootlin.com/linux/v6.11/source)

### Build

编译Kernel

下载解压缩 kernel

```shell
 wget https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.10.3.tar.xz
 
 tar Jxf linux-6.10.3.tar.xz
```



Linux 内核的构建过程会查找 .config 文件。顾名思义，这是一个配置文件，用于指定 Linux 内核的所有可能的配置选项。这是必需的文件。
获取 Linux 内核的 .config 文件有两种方式：

- 使用你的 Linux 发行版的配置作为基础（推荐做法）
- 使用默认的，通用的配置


Linux 发行版的 Linux 内核配置文件会在以下两个位置之一：

- 大多数 Linux 发行版，如 Debian 和 Fedora 及其衍生版，将会把它存在 /boot/config-$(uname -r)。
- 一些 Linux 发行版，比如 Arch Linux 将它整合在了 Linux 内核中。所以，可以在 /proc/config.gz 找到。


```shell
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-

make allnoconfig
make menuconfig
```




过程中遇到问题需要关闭功能 例如CONFIG_DEBUG_INFO_BIF=N时需要重新设置.config
- 运行脚本关闭: scripts/config --disable CONFIG_DEBUG_INFO_BIF
- 在menuconfig上设置

menuconfig是Linux平台用于管理代码工程、模块及功能的实用工具
menuconfig 其实只能算是一个“前端”，用于支撑它、决定它拥有什么配置项的“后端”则被称为 Kconfig

Kconfig参考文档位于 ./Document/kbuild/kconfig-language.rst

Kconfig常用的几个知识点有以下五个：

1. config模块
2. menuconfig模块
3. menu模块
4. choice模块
5. if 与 depends on 模块

```
General setup  --->   
  [*] Initial RAM filesystem and RAM disk (initramfs/initrd) support  
  [*] Configure standard kernel features (expert users)  ---> 

Executable file formats  --->
  [*] Kernel support for ELF binaries 
  [*] Kernel support for scripts starting with #! 

Device Drivers  --->  
  Generic Driver Options  --->
    [*] Maintain a devtmpfs filesystem to mount at /dev
    [*]   Automount devtmpfs at /dev, after the kernel mounted the rootfs 

Device Drivers  ---> 
  Character devices  ---> 
    Serial drivers  ---> 
      [*] ARM AMBA PL010 serial port support 
        [*]   Support for console on AMBA serial port
      [*] ARM AMBA PL011 serial port support  
        [*]   Support for console on AMBA serial port   

File systems  --->  
  [*] Second extended fs support
  [*] The Extended 4 (ext4) filesystem 

Device Drivers  ---> 
  [*] Block devices  ---> 
    [*]   RAM block device support
```

<!-- tabs:start -->

##### **Ubuntu**

> 异常: gelf.h: No such file or directory
> 
> sudo apt install libelf-dev

```shell
sudo apt install libelf-dev


zcat /proc/config.gz > .config

```

##### **ARM Mac**

```shell
brew install make
brew install aarch64-elf-gcc
brew install openssl@1.1
```
内核源码同级新建include目录，拷贝[elf.h](https://raw.githubusercontent.com/bminor/glibc/master/elf/elf.h)文件到其中

> 由于macOS环境已经定义了uuid_t从而引发了重复定义的错误
>
> error: member reference base type 'typeof (((struct tee_client_device_id )0)->uuid)' (aka 'unsigned char [16]') is not a structure or union uuid.b[15])

scripts/mod/file2alias.c文件中

```
typedef struct {
        __u8 b[16];
 } uuid_le;

#ifdef __APPLE__
#define uuid_t compat_uuid_t
#endif

 typedef struct {
        __u8 b[16];
 } uuid_t;
```



```shell
/opt/homebrew/opt/make/libexec/gnubin/make ARCH=arm64 CROSS_COMPILE=aarch64-elf- HOSTCFLAGS="-I../include -I/opt/homebrew/opt/openssl@1.1/include/" HOSTLDFLAGS="-L/opt/homebrew/opt/openssl@1.1/lib/" -j8

# 去掉CONFIG_KVM选项避免不必要的报错
# [ ] Virtualization  ----
/opt/homebrew/opt/make/libexec/gnubin/make ARCH=arm64 CROSS_COMPILE=aarch64-elf- menuconfig
```

> https://ixx.life/notes/cross-compile-linux-on-macos/

查看vmlinux文件

```shell
file vmlinux
```



##### **x86 Mac**

```shell

```

<!-- tabs:end -->





```shell
make -j8
```

```shell
cat /proc/version
```

### Directory


| Directory |                                                                                                                                                                                                                |  |
| --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | - |
| kernel    | The kernel directory contains the code for the components at the heart of the kernel.                                                                                                                          |  |
| arch      | arch/ holds all architecture-specific files, both include files and C and Assembler sources.<br />There is a separate subdirectory for each processor architecture supported by the kernel.                    |  |
| crypto    | crypto/ contains the files of the crypto layer (which is not discussed in this book).<br />It includesimplementations of various ciphers that are needed primarily to support IPSec (encrypted IP connection). |  |
| mm        | High-level memory management resides in mm/.                                                                                                                                                                   |  |
| fs        | fs/ holds the source code for all filesystem implementations.                                                                                                                                                  |  |
| include   | include/ contains all header files with publicly exported functions.                                                                                                                                           |  |
| init      | The code needed to initialize the kernel is held in init/.                                                                                                                                                     |  |
| ipc       | The implementation of the System V IPC mechanism resides in ipc/.                                                                                                                                              |  |
| lib       | lib/ contains generic library routines that can be employed by all parts of the kernel,<br />including data structures to implement various trees and data compression routines.                               |  |
| net       | net/ contains the network implementation, which is split into a core section and a section to implement the individual protocols                                                                               |  |
| security  | The security/ directory is used for security frameworks and key management for cryptography.                                                                                                                   |  |
| scripts   | scripts/ contains all scripts and utilities needed to compile the kernel or to perform other useful tasks.                                                                                                     |  |
| drivers   | drivers/ occupies the lion’s share of the space devoted to the sources.                                                                                                                                       |  |
|           |                                                                                                                                                                                                                |  |
| firmware  |                                                                                                                                                                                                                |  |
| virt      |                                                                                                                                                                                                                |  |
| usr       |                                                                                                                                                                                                                |  |
| tools     |                                                                                                                                                                                                                |  |
| block     | block device                                                                                                                                                                                                   |  |

```shell
usr/src/kernels/
```

内核源码根目录下的Makefile Kconfig Kbuild是与内核配置、编译相关的文件



- 
- [Init](/docs/CS/OS/Linux/init.md)



内核中可供调用的函数通常需要EXPORT

## Processes

Applications, servers, and other programs running under Unix are traditionally referred to as [processes](/docs/CS/OS/Linux/process.md).
Each process is assigned address space in the virtual memory of the CPU.
The address spaces of the individual processes are totally independent so that the processes are unaware of each other — as far as each process is concerned, it has the impression of being the only process in the system.
If processes want to communicate to exchange data, for example, then special kernel mechanisms must be used.

Because Linux is a multitasking system, it supports what appears to be concurrent execution of several processes.
Since only as many processes as there are CPUs in the system can really run at the same time, the kernel switches (unnoticed by users) between the processes at short intervals to give them the impression of simultaneous processing.
Here, there are two problem areas:

1. The kernel, with the help of the CPU, is responsible for the technical details of task switching. Each individual process must be given the illusion that the CPU is always available.
   This is achieved by saving all state-dependent elements of the process before CPU resources are withdrawn and the process is placed in an idle state.
   When the process is reactivated, the exact saved state is restored. Switching between processes is known as task switching.
2. The kernel must also decide how CPU time is shared between the existing processes. Important processes are given a larger share of CPU time, less important processes a smaller share.
   The decision as to which process runs for how long is known as [scheduling](/docs/CS/OS/Linux/sche.md).

### Spurious wakeup

A spurious wakeup happens when a thread wakes up from waiting on a condition variable that's been signaled, only to discover that the condition it was waiting for isn't satisfied.

It's called spurious because the thread has seemingly been awakened for no reason. But spurious wakeups don't happen for no reason:

- they usually happen because, in between the time when the condition variable was signaled and when the waiting thread finally ran, another thread ran and changed the condition.
  There was a race condition between the threads, with the typical result that sometimes, the thread waking up on the condition variable runs first, winning the race, and sometimes it runs second, losing the race.
- On many systems, especially multiprocessor systems, the problem of spurious wakeups is exacerbated because if there are several threads waiting on the condition variable when it's signaled,
  the system may decide to wake them all up, treating every signal() to wake one thread as a broadcast( ) to wake all of them, thus breaking any possibly expected 1:1 relationship between signals and wakeups.
  If there are ten threads waiting, only one will win and the other nine will experience spurious wakeups.
- To allow for implementation flexibility in dealing with error conditions and races inside the operating system, condition variables may also be allowed to return from a wait even if not signaled, though it is not clear how many implementations actually do that.
  In the Solaris implementation of condition variables, a spurious wakeup may occur without the condition being signaled if the process is signaled; the wait system call aborts and returns EINTR.
  **The Linux pthread implementation of condition variables guarantees it will not do that.**

Much more compelling reason for introducing concept of spurious wakeups is provided in [this answer at SO](https://stackoverflow.com/a/1051816/839601) that is based on additional details provided in an (older version) of that very article:

> The Wikipedia article on spurious wakeups has this tidbit:
>
> The function in Linux is implemented using the system call.
> Each blocking system call on Linux returns abruptly with when the process receives a signal.
> ... can't restart the waiting because it may miss a real wakeup in the little time it was outside the system call
> ...pthread_cond_wait() futex EINTR pthread_cond_wait() futex

Just think of it... like any code, thread scheduler may experience temporary blackout due to something abnormal happening in underlying hardware / software.
Of course, care should be taken for this to happen as rare as possible,
but since there's no such thing as 100% robust software it is reasonable to assume this can happen and take care on the graceful recovery in case if scheduler detects this (eg by observing missing heartbeats).

Now, how could scheduler recover, taking into account that during blackout it could miss some signals intended to notify waiting threads?
If scheduler does nothing, mentioned "unlucky" threads will just hang, waiting forever - to avoid this, scheduler would simply send a signal to all the waiting threads.

This makes it necessary to establish a "contract" that waiting thread can be notified without a reason.
To be precise, there would be a reason - scheduler blackout - but since thread is designed (for a good reason) to be oblivious to scheduler internal implementation details, this reason is likely better to present as "spurious".

From thread perspective, this somewhat resembles a Postel's law (aka robustness principle),

> be conservative in what you do, be liberal in what you accept from others

Assumption of spurious wakeups forces thread to be conservative in what it does: set condition when notifying other threads, and liberal in what it accepts:
check the condition upon any return from wait and repeat wait if it's not there yet.

Because spurious wakeups can happen whenever there's a race and possibly even in the absence of a race or a signal, when a thread wakes on a condition variable, it should always check that the condition it sought is satisfied.
If it's not, it should go back to sleeping on the condition variable, waiting for another opportunity.

### thundering herd

[thundering herd](/docs/CS/OS/Linux/thundering_herd.md)

## Interrupt

- [Interrupt](/docs/CS/OS/Linux/Interrupt.md)
- [System calls](/docs/CS/OS/Linux/Calls.md)

## memory

- [memory](/docs/CS/OS/Linux/memory.md)
- [slab](/docs/CS/OS/Linux/slab.md)

## fs

- [fs](/docs/CS/OS/Linux/fs.md)

## IO

- [IO](/docs/CS/OS/Linux/IO/IO.md)
- [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)
- [mmap](/docs/CS/OS/Linux/IO/mmap.md)

## Network

- [network](/docs/CS/OS/Linux/network.md)
- [socket](/docs/CS/OS/Linux/socket.md)
- [IP](/docs/CS/OS/Linux/IP.md)
- [TCP](/docs/CS/OS/Linux/TCP.md)
- [UDP](/docs/CS/OS/Linux/UDP.md)

## Loadable kernel module

## Links

- [Operating Systems](/docs/CS/OS/OS.md)

## 参考书籍


| 书名                                    | col2 | col3 |
| --------------------------------------- | ---- | ---- |
| Linux Performance and Tuning Guidelines |      |      |
| Linux内核源码剖析 - TCP/IP实现          |      |      |
| Linux内核源代码情景分析                 |      |      |
| Linux内核设计与实现                     |      |      |
| 深入理解计算机系统                      |      |      |
| UNIX网络编程                            |      |      |
| 图解TCP/IP                              |      |      |
| 网络是怎样连接的                        |      |      |
|                                         |      |      |
|                                         |      |      |
|                                         |      |      |
|                                         |      |      |

## References

1. [Experience with Processes and Monitors in Mesa](https://people.eecs.berkeley.edu/~brewer/cs262/Mesa.pdf)
