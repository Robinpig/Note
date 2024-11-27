## Introduction

Linux is the kernel: the program in the system that allocates the machine's resources to the other programs that you run.
The kernel is an essential part of an operating system, but useless by itself; it can only function in the context of a complete operating system.
Linux is normally used in combination with the GNU operating system: the whole system is basically GNU with Linux added, or GNU/Linux.
All the so-called “Linux” distributions are really distributions of GNU/Linux.

On a purely technical level, the kernel is an intermediary layer between the hardware and the software.
Its purpose is to pass application requests to the hardware and to act as a low-level driver to address the devices and components of the system.

Linux系统诞生于1991年10月5日

常见Linux发行版

- Red Hat Linux
  - Red Hat Enterprise Linux
  - [Fedora](/docs/CS/OS/Linux/Distribution/Fedora.md)
  - [CentOS](/docs/CS/OS/Linux/Distribution/CentOS.md)
- Debian Linux
  - [Ubuntu](/docs/CS/OS/Linux/Distribution/Ubuntu.md)
- SuSE Linux
- Arch Linux

跨平台在其它OS下使用Linux

- Docker
- 虚拟机

Windows下使用Linux

- [WSL](/docs/CS/OS/Windows/WSL.md)

> [!TIP]
>
> 常见的一些[使用经验](/docs/CS/OS/Linux/Experience.md)

Linux在最初是宏内核架构 同时也逐渐融入了微内核的精华 如模块化设计 抢占式内核 动态加载内核模块等

模块是被编译的目标文件 可以在运行时的内核中动态加载和卸载 和微内核实现的模块化不同 它们不是作为独立模块执行的 而是和静态编译的内核函数一样 运行在内核态中 模块的引入带来了不少的有点

- 内核的功能和设备驱动可以编译成动态加载/卸载的模块 驱动开发者需要遵守API来访问内核核心 提高开发效率
- 内核模块可以设计成平台无关的
- 相比微内核 具有宏内核的性能优势

## Kernel

调试环境需要安装qemu+gdb

需要准备如下：

- 带调试信息的内核vmlinux
- 一个压缩的内核vmlinuz bzImage/Image
- 一份裁剪过的文件系统initrd/init

vmlinux 是生成的内核二进制文件它是一个没有压缩的镜像

**Image**是vmlinux经过OBJCOPY后生成的纯二进制映像文件

**zImage**是Image经过压缩后形成的一种映像压缩文件

**uImage**是在zImage基础上在前面64字节加上内核信息后的映像压缩文件，供uboot使用

fs可以通过不同的tools来构建

- buildroot

编译busybox时因为内存不足出现如下错误 可在Docker Desktop中看到内存占用很高, 创建较大内存的容器后重新make

> gcc: fatal error: Killed signal terminated program cc1

出现如下问题 需要 设置disable Applets->Shells->ash->job control

> can't access tty; job control turned off

### Build

#### Build examples

<!-- tabs:start -->

##### **Ubuntu**

```shell
 wget https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.10.3.tar.xz
 
 tar Jxf linux-6.10.3.tar.xz
```

> 异常: gelf.h: No such file or directory
>
> sudo apt install libelf-dev

```shell
sudo apt install libelf-dev


zcat /proc/config.gz > .config

```

> make[1]: *** No rule to make target 'debian/canonical-certs.pem', needed by 'certs/x509_certificate_list'.  Stop.
> make: *** [Makefile:1809: certs] Error 2
>
> scripts/config --disable SYSTEM_TRUSTED_KEYS

##### **ARM Ubuntu**

> 基于[奔跑吧 Linux内核 入门篇]()

```shell
wget https://github.com/runninglinuxkernel/runninglinuxkernel_5.0/archive/refs/heads/rlk_5.0.zip
unzip rlk_5.0.zip
mv runninglinuxkernel_5.0-rlk_5.0/ runninglinuxkernel_5.0

cd runninglinuxkernel_5.0/
sudo ./run_rlk_arm64.sh build_kernel
sudo ./run_rlk_arm64.sh build_rootfs
./run_rlk_arm64.sh run
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

##### **x86 Docker**

> 参考[Linux核心概念详解 - 1. 调试环境](https://s3.shizhz.me/s3e1)

需要一个能够编译 Linux Kernel 的 Docker 镜像 新建目录 $HOME/linux/docker:
在该目录下创建文件 build-kernel.sh 并写入如下内容：

```shell
Copy
#!/bin/bash

cd /workspace/linux-5.12.14
make O=../obj/linux/ -j$(nproc)
```

在该目录下创建文件 start-gdb.sh 并写入如下内容：

```shell
Copy
#!/bin/bash

echo 'add-auto-load-safe-path /workspace/linux-5.12.14/scripts/gdb/vmlinux-gdb.py' > /root/.gdbinit # 让 gdb 能够顺利加载内核的调试脚本，如果在下一节编译 Linux Kernel 时下载的是另一版本的 Linux Kernel 代码，请修改这里的版本号
cd /workspace/obj/linux/
gdb vmlinux -ex "target remote :1234" # 启动 gdb 远程调试内核
```

创建文件 Dockerfile 并写入如下内容：

```dockerfile
FROM --platform=linux/amd64 dockerproxy.cn/debian:10.8-slim

RUN apt-get update
RUN apt install -y apt-transport-https ca-certificates \
    && echo 'deb https://mirrors.tuna.tsinghua.edu.cn/debian/ buster main contrib non-free \n\
    deb https://mirrors.tuna.tsinghua.edu.cn/debian/ buster-updates main contrib non-free \n\
    deb https://mirrors.tuna.tsinghua.edu.cn/debian-security buster/updates main contrib non-free\n'\
    > /etc/apt/sources.list \
    && apt update && apt-get install -y \
    procps \
    vim \
    bc \
    bison \
    build-essential \
    cpio \
    flex \
    libelf-dev \
    libncurses-dev \
    libssl-dev \
    vim-tiny \
    qemu-kvm \
    gdb
ADD ./start-gdb.sh /usr/local/bin
ADD ./build-kernel.sh /usr/local/bin
RUN chmod a+x /usr/local/bin/*.sh
WORKDIR /workspace


ENV PATH /path/to/qemu-aarch64-static:$PATH
ENV LD_LIBRARY_PATH /path/to/qemu-aarch64-static/usr/lib:$LD_LIBRARY_PATH
```

通过如下命令构建镜像：

```shell
Copy
docker build --platform=linux/amd64 -t linux-builder .
```

下载最新稳定版的内核代码：

```shell
cd $HOME/linux/
wget https://cdn.kernel.org/pub/linux/kernel/v5.x/linux-5.12.14.tar.xz
tar -xvJf linux-5.12.14.tar.xz
```

创建编译结果的输出目录：

```shell
mkdir -p $HOME/linux/obj
```

进入目录 $HOME/linux/ 并运行如下命令，进入容器编译内核：

```shell

docker run --platform=linux/amd64 -it --name linux-builder -v $HOME/linux:/workspace linux-builder
```

在容器内进入解压后内核源代码目录，并配置 Kernel 的编译选项：

```shell
cd /workspace/linux-5.12.14
make O=../obj/linux menuconfig
```

> Kernel hacking ---> Compile-time checks and compiler options 开启GDB Scripts

编译kernel

> Mac的APFS文件系统默认case insensitive, 导致make的xt_TCPMSS.o变成xt_tcpmss.o
> 需要修改Makefile里变成xt_tcpmss.o

```shell
bash build-kernel.sh
```

下载 busybox 到工作目录并解压:

```shell

cd $HOME/linux
wget https://busybox.net/downloads/busybox-1.33.1.tar.bz2
tar -vxjf busybox-1.33.1.tar.bz2
```

回到编译内核的容器 linux-builder 中，对 busybox 进行编译配置：

```shell

mkdir -p /workspace/obj/busybox # 创建 busybox 的编译输出目录
cd /workspace/busybox-1.33.1
make O=../obj/busybox menuconfig
```

最后一条命令会打开配置目录，选中 Settings ---> Build static binary (no shared libs)

然后通过如下命令编译并安装 busybox:

```shell
cd /workspace/obj/busybox/
make -j$(nproc)
make install
```

使用 busybox 构建一个极简的 initramfs, 能引导 Linux 启动并进入一个 shell 环境就足够。在容器中回到目录 /workspace 执行如下命令：

```shell
mkdir -p /workspace/initramfs/busybox
cd !$
mkdir -p {bin,sbin,etc,proc,sys,usr/{bin,sbin}}
cp -av /workspace/obj/busybox/_install/* .
```

此时我们已经将 busybox 生成的可执行文件全部拷贝到了对应目录，但还缺少一个 init 程序，可以简单写一个 shell 脚本来充当 init, 将如下内容写入文件 /workspace/initramfs/busybox/init 中：

```shell
#!/bin/sh

mount -t proc none /proc
mount -t sysfs none /sys

echo -e "\nBoot took $(cut -d' ' -f1 /proc/uptime) seconds\n"

exec /bin/sh
```

为文件添加可执行权限：

```shell
chmod a+x /workspace/initramfs/busybox/init
```

通过如下命令将所有内容打包：

```shell
cd /workspace/initramfs/busybox

find . -print0 \
| cpio --null -ov --format=newc \
| gzip -9 > /workspace/obj/initramfs-busybox.cpio.gz
```

文件 /workspace/obj/initramfs-busybox.cpio.gz 便是最终的 initramfs, 该文件会在启动内核时作为参数传递给 qemu.

运行

```shell
qemu-system-x86_64 -kernel /workspace/obj/linux/arch/x86/boot/bzImage -initrd /workspace/obj/initramfs-busybox.cpio.gz -nographic -append "console=ttyS0"
```

##### **ARM Docker**

ARM配置操作基本同x86 以下列出的是不同点

Dockerfile

> Busybox 配置时需要disable Applets->Shells->ash->job control
> 否则将在linux启动后报错 can't access tty,job control turned off

配置用户文件

```
# /etc/passwd
root:x:0:0:Linux User,,,:/root:/bin/sh

# /etc/group
tty:x:0:

# /etc/shadow
root::::::::
```

配置init

```shell
#!/bin/sh

mount -t proc none /proc
mount -t sysfs none /sys

echo -e "\nBoot took $(cut -d' ' -f1 /proc/uptime) seconds\n"

mkdir -p /home/admin

mount -n -t tmpfs none /dev

mknod -m 622 /dev/console c 5 1
mknod -m 666 /dev/null c 1 3
mknod -m 666 /dev/zero c 1 5
mknod -m 666 /dev/ptmx c 5 2
mknod -m 666 /dev/tty c 5 0 # <--
mknod -m 444 /dev/random c 1 8
mknod -m 444 /dev/urandom c 1 9
mknod -m 666 /dev/ttyAMA0 c 5 3

chown admin:tty /dev/console
chown admin:tty /dev/ptmx
chown admin:tty /dev/tty
chown admin:tty /dev/ttyAMA0 

exec /bin/sh
```

启动

```shell
qemu-system-aarch64 -s -S -name vm2 -M virt -cpu cortex-a57 -m 4096M -kernel /workspace/obj/linux/arch/arm64/boot/Image -initrd /workspace/obj/initramfs-busybox.cpio.gz -nographic -append nokaslr root="/dev/ram init=/init console=ttyAMA0"
```

<!-- tabs:end -->

#### config

Linux 内核的构建过程会查找 .config 文件。顾名思义，这是一个配置文件，用于指定 Linux 内核的所有可能的配置选项。这是必需的文件。
获取 Linux 内核的 .config 文件有两种方式：

- 使用你的 Linux 发行版的配置作为基础（推荐做法）
- 使用默认的，通用的配置

Linux 发行版的 Linux 内核配置文件会在以下两个位置之一：

- 大多数 Linux 发行版，如 Debian 和 Fedora 及其衍生版，将会把它存在 /boot/config-$(uname -r)。
- 一些 Linux 发行版，比如 Arch Linux 将它整合在了 Linux 内核中。所以，可以在 /proc/config.gz 找到。

```shell
cp /boot/config-${uname -r} .config
```

make 方式

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

#### makefile

install.sh脚本文件只是完成复制的功能 将bzImage文件复制到vmlinuz

```makefile
#linux/arch/x86/boot/Makefile
install:
        sh $(srctree)/$(src)/install.sh $(KERNELRELEASE) $(obj)/bzImage \
                System.map "$(INSTALL_PATH)"
```

生成bzImage文件需要三个依赖文件：setup.bin、vmlinux.bin，linux/arch/x86/boot/tools目录下的build

```makefile
#linux/arch/x86/boot/Makefile
$(obj)/bzImage: $(obj)/setup.bin $(obj)/vmlinux.bin $(obj)/tools/build FORCE
        $(call if_changed,image)
        @$(kecho) 'Kernel: $@ is ready' ' (#'`cat .version`')'
```

build只是一个HOSTOS下的应用程序，它的作用就是将setup.bin、vmlinux.bin两个文件拼接成一个bzImage文件

vmlinux.bin文件依赖于linux/arch/x86/boot/compressed/目录下的vmlinux目标

```makefile
#linux/arch/x86/boot/Makefile
OBJCOPYFLAGS_vmlinux.bin := -O binary -R .note -R .comment -S
$(obj)/vmlinux.bin: $(obj)/compressed/vmlinux FORCE
        $(call if_changed,objcopy)
```

linux/arch/x86/boot/compressed目录下的vmlinux是由该目录下的head_32.o或者head_64.o、cpuflags.o、error.o、kernel.o、misc.o、string.o 、cmdline.o 、early_serial_console.o等文件以及piggy.o链接而成的

setup.bin文件是由objcopy命令根据setup.elf生成的
setup.bin文件正是由/arch/x86/boot/目录下一系列对应的程序源代码文件编译链接产生

### Read

执行 ctags -R 生成索引文件 tags

- ctrl + ] 进入函数定义
- g, ctrl + ] 进入函数定义 可选择
- ctrl + o 返回

打开vim后 加载tags文件

```shell
:set tags=tags
```

> 在线阅读 [bootlin](https://elixir.bootlin.com/linux/v6.11/source)

#### Directory

目录结构


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

- [memory](/docs/CS/OS/Linux/mm/memory.md)
- [slab](/docs/CS/OS/Linux/mm/slab.md)
- [mmap](/docs/CS/OS/Linux/mm/mmap.md)

## fs

- [fs](/docs/CS/OS/Linux/fs/fs.md)

## IO

- [IO](/docs/CS/OS/Linux/IO/IO.md)
- [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)

## Network

- [network](/docs/CS/OS/Linux/net/network.md)
- [socket](/docs/CS/OS/Linux/net/socket.md)
- [IP](/docs/CS/OS/Linux/net/IP.md)
- [TCP](/docs/CS/OS/Linux/net/TCP/TCP.md)
- [UDP](/docs/CS/OS/Linux/net/UDP.md)

## Loadable kernel module

## Commands

可以通过man查看命令

> [Linux命令搜索](https://wangchujiang.com/linux-command/)

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
2. [Linux核心概念详解](https://s3.shizhz.me/)
3. [linux-insides](https://0xax.gitbooks.io/linux-insides/content/)
4. [Linux0.11源码解析](https://zhuanlan.zhihu.com/c_1094189343643652096)
5. [The Linux Kernel documentation](https://www.kernel.org/doc/)
