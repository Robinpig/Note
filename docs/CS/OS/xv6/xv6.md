## Introduction

xv6 是 MIT 开发的一个教学用的完整的类 Unix 操作系统，并且在 MIT 的操作系统课程 [6.828](http://pdos.csail.mit.edu/6.828/2012/xv6.html) 中使用

xv6 是 Dennis Ritchie 和 Ken Thompson 合著的 Unix Version 6（v6）操作系统的重新实现。xv6 在一定程度上遵守 v6 的结构和风格，但它是用 ANSI C 实现的，并且是基于 x86 多核处理器的。



## Build



Fist of all, [Install QEMU](/docs/CS/OS/qemu.md)



### x86

<!-- tabs:start -->

Download

```shell
git clone http://github.com/mit-pdos/xv6-public.git
```

##### **Ubuntu**

```shell
```







<!-- tabs:end -->

### Riscv

<!-- tabs:start -->





##### Ubuntu

Make riscv-gnu-toolchain

```shell
sudo apt-get install autoconf automake autotools-dev curl python3 libmpc-dev libmpfr-dev libgmp-dev gawk build-essential bison flex texinfo gperf libtool patchutils bc zlib1g-dev libexpat-dev ninja-build
```
prepare
```shell
git clone https://gitee.com/mirrors/riscv-gnu-toolchain.git
cd riscv-gnu-toolchain
cat .gitmodules

git clone https://gitee.com/mirrors/riscv-isa-sim.git
rm -rf spike
mv riscv-isa-sim spike

git clone https://gitee.com/riscv/riscv-pk.git
rm -rf pk
mv riscv-pk pk
```




make
```shell
sudo mkdir /opt/riscv
sudo chmod 777 /opt/riscv
# zsh
sudo vim ~/.zshrc
source ~/.zshrc

./configure --prefix=/opt/riscv --enable-multilib
sudo make linux -j4
```

Check version

```shell
riscv64-unknown-linux-gnu-gcc -v
```







##### **m1 mac**

参考

> [MIT 6.S081/Fall 2020 搭建 risc-v 与 xv6 开发调试环境](https://yaoyao.io/posts/mit6.S081-basic-env-install)

Install riscv-gnu-toolchain

```shell

brew tap riscv/riscv
brew install riscv-tools
export PATH=$PATH:/usr/local/opt/riscv-gnu-toolchain/bin
export PATH=$PATH:/opt/homebrew/bin/riscv64-elf-gcc/bin
```



测试安装 确保gcc正常安装

```shell
riscv64-unknown-elf-gcc --version
qemu-system-riscv64 --version
```

下载代码

```shell

git clone git://github.com/mit-pdos/xv6-riscv.git

cd /path/to/xv6-riscv
make qemu
```

会输出一大堆编译信息，最后：

```
xv6 kernel is booting
init: starting sh
```

退出虚拟机时，先按下control键和A键，然后按X键



使用gdb调试

```shell
brew install riscv64-elf-gdb
```

第一个窗口 make qemu-gdb , 第二个窗口riscv64-elf-gdb



<!-- tabs:end -->



## 小测

编写程序

在 xv6-riscv/user/ 里新建一个 helloworld.c 文件，编写代码：

```c
#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"

int main() {
printf("Hello World!\n");
exit(0);
}
```

注意到，这个和平时我们在真实系统中写的代码有少许区别：

1. 导库：kernel/types.h, kernel/stat.h, user/user.h。你可以看到 xv6-riscv/user/*.c 头三行基本都是这么写的，咱们有样学样就可。（这三行大概就是 include <stdio.h>，<stdlib.h>，<unistd.h> ）
2. 不要 return 0;，要 exit(0);（否则你会得到一个运行时的  unexpected scause 0x000000000000000f）。这一点同样可以参考其他系统随附的程序得出。
   只要注意这两点，还有注意你只能用 Xv6 提供的 C 库，不能用真实系统中的 STL。其他的和平时写 C 程序没有多大区别。
3. 修改 Makefile
   Xv6 系统本身并没有编译器的实现，所以我们需要把程序在编译系统时一并编译。修改 xv6-riscv/Makefile：

vim Makefile

找到 UPROGS (大概第118行左右)，保持格式，在后面添加注册新程序：

```makefile
UPROGS=\
$U/_cat\
$U/_echo\
...
$U/_helloworld\
```

编译运行 Xv6

在 Xv6 中 ls，可以看到我们的 helloworld 程序

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

在 Xv6 里提供的 printf 线程不安全，运行程序打印出的字符可能随机混合在一起

在UNIX下 printf是线程安全的

```c
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main() {
	int pid = fork();
	if(pid > 0) {
		printf("parent: child=%d\n", pid);
		pid = wait((int *) 0);
		printf("child %d is done\n", pid);
	} else if (pid == 0) {
		printf("child: exiting\n");
		// sleep(2);
		exit(0);
	} else {
		printf("fork error\n");
	}

	return 0;
}
```

Xv6 系统下的 `useexec.c`：

注意 include 库与真实世界中的不同

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
	// exec 成功了会替换程序，下面的就执行不到了:
	printf("exec error\n");

	exit(0);
}
```

macOS 下的 `useexec.c`:

```c
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main() {
	char *argv[3];

	argv[0] = "echo";
	argv[1] = "hello";
	argv[2] = 0;

	execv("/bin/echo", argv);
	// execv("/bin/echooooo", argv);  // an error one
	printf("exec error\n");
}
```





## main



x86

二进制代码分成两部分 启动扇区bootblock 和内核代码kernel 可以直接使用binutils工具查看分析





Riscv

```shell
#include "types.h"
#include "param.h"
#include "memlayout.h"
#include "riscv.h"
#include "defs.h"

volatile static int started = 0;

// start() jumps here in supervisor mode on all CPUs.
void
main()
{
  if(cpuid() == 0){
    consoleinit();
    printfinit();
    printf("\n");
    printf("xv6 kernel is booting\n");
    printf("\n");
    kinit();         // physical page allocator
    kvminit();       // create kernel page table
    kvminithart();   // turn on paging
    procinit();      // process table
    trapinit();      // trap vectors
    trapinithart();  // install kernel trap vector
    plicinit();      // set up interrupt controller
    plicinithart();  // ask PLIC for device interrupts
    binit();         // buffer cache
    iinit();         // inode table
    fileinit();      // file table
    virtio_disk_init(); // emulated hard disk
    userinit();      // first user process
    __sync_synchronize();
    started = 1;
  } else {
    while(started == 0)
      ;
    __sync_synchronize();
    printf("hart %d starting\n", cpuid());
    kvminithart();    // turn on paging
    trapinithart();   // install kernel trap vector
    plicinithart();   // ask PLIC for device interrupts
  }

  scheduler();        
}
```









## Process



处理器共享一个全局进程表 

xv6进程只保存父子关系



### schedule

保存现场



调度算法

简单时间片轮转调度



负载均衡

每个CPU都是独立进行时间片轮转 一定程度上实现了负载均衡

暂时未实现优先级调度





## Memory



## File System



## Device







## Links

- [Operating Systems](/docs/CS/OS/OS.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [xv6 a simple, Unix-like teaching operating system](https://pdos.csail.mit.edu/6.828/2018/xv6/book-rev11.pdf)
2. [操作系统原型 - xv6分析与实验](https://book.douban.com/subject/35550326/)
3. [xv6 中文文档](https://th0ar.gitbooks.io/xv6-chinese/content/)
