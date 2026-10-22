## Introduction

xv6 的教学价值很大程度来自"能跑、能改、能调试"。本笔记汇总在两个官方移植版（x86 的 `mit-pdos/xv6-public` 与 RISC-V 的 `mit-pdos/xv6-riscv`）上搭建 QEMU 运行环境、用 gdb 单步内核、以及编译运行自己的用户程序的方法。硬件虚拟化与 QEMU 本身见 [QEMU](/docs/CS/OS/Virtualization/qemu.md)。

> 选哪个版本：6.S081（RISC-V）是当前主流课程分支，工具链与社区资料更全；x86 版适合对照"实模式→保护模式"的教材式启动（见 [Boot](/docs/CS/OS/xv6/Boot.md)）。下面分别给命令，按本机系统挑一段即可。

## 搭建 x86 环境

### 获取源码

```shell
git clone http://github.com/mit-pdos/xv6-public.git
```

### Ubuntu

```shell
sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils virtinst virt-manager
```

若运行时一直停在 `Booting from Hard Disk...`，通常需改 `kernel.ld` 里调试信息段；x86 版某些提交下 `mp.o` 编译告警可把 Makefile 的 `-Werror` 改成 `-Wno-error` 后 `make clean` 再编。

### macOS（ARM 芯片）

ARM 架构 Mac 需要装 **x86 版** Homebrew 工具链：

```shell
# 安装binutils gcc
brew tap nativeos/i386-elf-toolchain
brew install nativeos/i386-elf-toolchain/i386-elf-binutils
brew install nativeos/i386-elf-toolchain/i386-elf-gcc
brew install i386-elf-gdb
brew install qemu
```

然后改 Makefile 打开交叉编译：

```makefile
TOOLPREFIX = i386-elf-
```

### Docker

```shell
docker pull linxi177229/mit6.s081:latest
docker run --name mit6.s081 -itd linxi177229/mit6.s081
```

## 搭建 RISC-V 环境

### 获取源码

```shell
git clone git://github.com/mit-pdos/xv6-riscv.git
```

### Ubuntu 编译工具链

先装依赖，再从镜像拉 `riscv-gnu-toolchain`（含 `riscv-isa-sim`/`riscv-pk`）：

```shell
sudo apt-get install autoconf automake autotools-dev curl python3 libmpc-dev libmpfr-dev libgmp-dev gawk build-essential bison flex texinfo gperf libtool patchutils bc zlib1g-dev libexpat-dev ninja-build

git clone https://gitee.com/mirrors/riscv-gnu-toolchain.git
cd riscv-gnu-toolchain
# 把 isa-sim / pk 作为子目录放好
git clone https://gitee.com/mirrors/riscv-isa-sim.git
rm -rf spike; mv riscv-isa-sim spike
git clone https://gitee.com/riscv/riscv-pk.git
rm -rf pk; mv riscv-pk pk

sudo mkdir /opt/riscv && sudo chmod 777 /opt/riscv
./configure --prefix=/opt/riscv --enable-multilib
sudo make linux -j4

riscv64-unknown-linux-gnu-gcc -v   # 验证
```

### macOS

```shell
brew tap riscv/riscv
brew install riscv-tools
export PATH=$PATH:/usr/local/opt/riscv-gnu-toolchain/bin
export PATH=$PATH:/opt/homebrew/bin/riscv64-elf-gcc/bin

riscv64-unknown-elf-gcc --version
qemu-system-riscv64 --version
```

## 调试内核

### 基本运行

- 用 `make qemu-nox` 不弹仿真窗口。
- 退出虚拟机：先按 `Ctrl+A`，再按 `X`。

### 用 gdb 单步

第一个终端：

```shell
# 第一次执行 gdb 需要把 .gdbinit 加入白名单
echo "add-auto-load-safe-path $(pwd)/.gdbinit" >> ~/.gdbinit
make CPUS=1 qemu-gdb
```

第二个终端：

```shell
gdb-multiarch        # RISC-V
# 或 i386-elf-gdb     # x86
```

`gdb` 里可设 `set scheduler-locking on` 让所有线程都受控于 gdb（反之 `off`）；也能把命令施加到指定线程（ID 列表或 `all`）。

### 进程栈回溯（procdump）

内核里 `ctrl-p` 打印的进程信息由 `procdump()` 输出，后面跟着的是调用栈返回地址：

```
$ 1 sleep  init 80103fb7 8010405f 80104a6d 80105b41 80105883
2 sleep  sh 80103f80 801002ea 80101030 80104d66 80104a6d 80105b41 80105883
```

用 `addr2line -e kernel [地址]`（x86 用 `i386-elf-addr2line`）逐个还原代码位置，即可拼出进程阻塞前的函数嵌套。例如上例中 `sh` 是通过 `alltraps → trap → syscall → sys_read() → readi() → consoleread() → sleep()` 进入内核的。

## 编译运行用户程序

xv6 本身**不含编译器**，用户程序要随内核一起编译。以 RISC-V 版为例，在 `user/` 下新建 `helloworld.c`：

```c
#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"

int main() {
    printf("Hello World!\n");
    exit(0);
}
```

注意两点，否则会遇到运行期错误（如 `unexpected scause 0x000000000000000f`）：

1. 头文件固定三行：`kernel/types.h`、`kernel/stat.h`、`user/user.h`（约等于 `<stdio.h>/<stdlib.h>/<unistd.h>`）。
2. 用 `exit(0);` 而不是 `return 0;`，且只能用 xv6 自带 C 库，不能用 STL。

然后在 `Makefile` 的 `UPROGS` 里登记（保持格式）：

```makefile
UPROGS=\
$U/_cat\
$U/_echo\
...
$U/_helloworld\
```

### fork 示例

```c
#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"

int main() {
    int pid = fork();
    if(pid > 0) {
        printf("parent: child=%d\n", pid);
        pid = wait((int *) 0);
        printf("child %d is done\n", pid);
    } else if (pid == 0) {
        printf("child: exiting\n");
        exit(0);
    } else {
        printf("fork error\n");
    }
    exit(0);
}
```

> xv6 的 `printf` **线程不安全**，并发打印字符可能随机交错（真实 UNIX 下是安全的）。

### exec 示例

```c
#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"

int main() {
    char *argv[3];
    argv[0] = "echo";
    argv[1] = "hello";
    argv[2] = 0;
    exec("echo", argv);
    printf("exec error\n");   // exec 成功后不会回到这里
    exit(0);
}
```

`exec` 的装载细节（读 ELF、建地址空间、设参数字符串）见 [ELF](/docs/CS/OS/xv6/ELF.md) 与 [Syscall](/docs/CS/OS/xv6/Syscall.md)；`fork`/`wait` 的进程语义见 [proc](/docs/CS/OS/xv6/proc.md)。

## Links

- [xv6](/docs/CS/OS/xv6/xv6.md)
- [xv6 启动流程](/docs/CS/OS/xv6/Boot.md)
- [xv6 系统调用](/docs/CS/OS/xv6/Syscall.md)
- [xv6 进程](/docs/CS/OS/xv6/proc.md)
- [QEMU](/docs/CS/OS/Virtualization/qemu.md)
- [Bochs](/docs/CS/OS/Virtualization/Bochs.md)

## References

1. [MIT 6.S081/Fall 2020 搭建 risc-v 与 xv6 开发调试环境](https://yaoyao.io/posts/mit6.S081-basic-env-install)
2. [MIT6.828 Fall2018 笔记 - Homework 3: xv6 system calls](https://www.cnblogs.com/zsmumu/p/12622898.html)
3. [xv6-riscv 仓库](https://github.com/mit-pdos/xv6-riscv)
