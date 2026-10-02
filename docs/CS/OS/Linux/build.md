## Introduction

本页收拢内核**从拿到源码到产出可引导镜像**的全过程，回答三个问题：源码从哪来、怎么读、怎么配和编。

这三步在实践中经常被跳过，但它们正是排查"为什么内核跑不出预期行为"的前提。两件最容易出错的事：**源码版本与运行版本不一致**——`uname -r` 给出的是运行版本，而 `/lib/modules/$(uname -r)/build` 指向的才是编译它所用的源码树，拿错树会让所有结论失效；**`.config` 不同**——同一份源码能编出行为完全不同的内核，抢占模型、调度器、页大小都由它决定。

下文按实际操作顺序组织：先获取源码，再用 ctags 或 bootlin 读懂它，最后配置并构建。构建产物的分工（`vmlinux` 与 `bzImage`）以及它如何被引导器接过去，见 [boot](/docs/CS/OS/Linux/boot/README.md)。

## Kernel

如何在机器上下载当前系统的源码

```
# Cent OS
sudo yum install -y kernel-devel

## Ubuntu
sudo apt install linux-source

# 目录
cd /usr/src

```



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

- [Init](/docs/CS/OS/Linux/boot/init.md)

内核中可供调用的函数通常需要EXPORT



### Build

> [!TIP]
>
> 最佳推荐环境是 Linux物理机 > Linux虚拟机 > Docker容器



[Linux 0.11](/docs/CS/OS/Linux/0.11.md)


调试环境需要安装qemu+gdb

需要准备如下：

- 带调试信息的内核vmlinux
- 一个压缩的内核vmlinuz bzImage/Image
- 一份裁剪过的文件系统initrd/initramfs

vmlinux 是生成的内核二进制文件它是一个没有压缩的镜像

- **Image**是vmlinux经过OBJCOPY后生成的纯二进制映像文件
- **zImage**是Image经过压缩后形成的一种映像压缩文件
- **uImage**是在zImage基础上在前面64字节加上内核信息后的映像压缩文件，供uboot使用

fs可以通过不同的tools来构建

- buildroot

编译busybox时因为内存不足出现如下错误 可在Docker Desktop中看到内存占用很高, 创建较大内存的容器后重新make

> gcc: fatal error: Killed signal terminated program cc1

出现如下问题 需要 设置disable Applets->Shells->ash->job control

> can't access tty; job control turned off

编译Linux主要分两部分

- kernel 下载[aliyun mirror](https://mirrors.aliyun.com/linux-kernel/v6.x/?spm=a2c6h.25603864.0.0.596f43c0uwxjrK)
- fs 通常使用的是busybox

#### Build Configuration

qemu启动只携带kernel会error `unable to mount root fs`



常见的根文件系统
buildroot 和 busybox 无包管理工具



<!-- tabs:start -->



##### **kernel**

依赖

```shell
sudo apt-get install -y  procps  vim  bc bison build-essential cpio  flex  libelf-dev  libncurses-dev gcc g++ make libssl-dev

```

Linux 内核的构建过程会查找 `.config` 文件。顾名思义，这是一个配置文件，用于指定 Linux 内核的所有可能的配置选项。这是必需的文件。

获取 Linux 内核的 `.config` 文件有两种方式

使用你的 Linux 发行版的配置作为基础（**推荐做法**）

```shell
### Debian 和 Fedora 及其衍生版：
$ cp /boot/config-"$(uname -r)" .config

### Arch Linux 及其衍生版：
$ zcat /proc/config.gz > .config
```

使用默认的，通用的配置


```shell
make defconfig
```



无论使用 Linux 发行版的配置并更新它，还是使用 `defconfig` 目标创建新的 `.config` 文件，你都可能希望熟悉如何修改这个配置文件 使用 `make menuconfig` 修改更方便


> Kernel hacking ---> Compile-time checks and compiler options 开启GDB Scripts


| 编译报错 | 解决方法 |
| --- | --- |
| No rule to make target 'debian/certs/debian-uefi-certs.pem | vim .config 文件 remove包含 debian 的key配置 |







##### **busybox**



> Busybox 配置时需要disable Applets->Shells->ash->job control
> 否则将在linux启动后报错 can't access tty,job control turned off


```shell

make

make install  CONFIG_PREFIX=../busybox
```


创建文件夹

```shell
mkdir -p {home,bin,sbin,etc,proc,sys,usr/{bin,sbin}}
```

制作临时的init

vim shell.c

```shell
#include<stdio.h>

int main()
{
	while(1)
	{
    printf("Hello World!");
    scanf("%d");	
	}
}
```



打包init文件
```shell
gcc main.c  -static -o init

echo "init" | cpio -H newc -o > init.cpio
qemu-system-x86_64 -kernel linux-6.13.5/arch/x86/boot/bzImage  -initrd init.cpio
```


配置用户文件
/etc/passwd 文件包含了所有系统用户账户列表以及每个用户的基本配置信息

```
# /etc/passwd
root:x:0:0:Linux User,,,:/root:/bin/sh

# /etc/group
tty:x:0:

# /etc/shadow
root::::::::
```

正式配置init

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



打包busybox
```shell
find . -print0 | cpio --null -ov --format=newc | gzip -9 > ../busybox.cpio.gz
```





<!-- tabs:end -->




```shell
qemu-system-x86_64  -kernel linux-6.13.5/arch/x86/boot/bzImage  -initrd busybox/busybox.cpio.gz  -nographic -append "console=ttyS0"
```




grub的配置





```shell
sudo grub-install --target=x86_64-efi --efi-directory=$(realpath mnt) --bootloader-id=GRUB  --removable --recheck
```







```shell

qemu-system-x86_64  -drive file=./linux.img -bios /usr/share/ovmf/OVMF.fd -m 1G -serial stdio
```





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
#!/bin/bash

cd /workspace/linux-5.12.14
make O=../obj/linux/ -j$(nproc)
```

在该目录下创建文件 start-gdb.sh 并写入如下内容：

```shell
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
```

通过如下命令构建镜像：

```shell
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
qemu-system-x86_64 -kernel /workspace/obj/linux/arch/x86_64/boot/bzImage -initrd /workspace/obj/initramfs-busybox.cpio.gz -nographic -append "console=ttyS0"
```

##### **ARM Docker**

ARM配置操作基本同x86 以下列出的是不同点

Dockerfile增加

```dockerfile

ENV PATH /path/to/qemu-aarch64-static:$PATH
ENV LD_LIBRARY_PATH /path/to/qemu-aarch64-static/usr/lib:$LD_LIBRARY_PATH
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

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [boot](/docs/CS/OS/Linux/boot/README.md)
- [Tools](/docs/CS/OS/Linux/Tools/README.md)
