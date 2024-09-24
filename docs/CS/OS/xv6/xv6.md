## Introduction

xv6 是 MIT 开发的一个教学用的完整的类 Unix 操作系统，并且在 MIT 的操作系统课程 [6.828](http://pdos.csail.mit.edu/6.828/2012/xv6.html) 中使用

xv6 是 Dennis Ritchie 和 Ken Thompson 合著的 Unix Version 6（v6）操作系统的重新实现。xv6 在一定程度上遵守 v6 的结构和风格，但它是用 ANSI C 实现的，并且是基于 x86 多核处理器的。

2019年移植到RISC-V上后设置了6.S081课程


特点

- 只支持多进程 不支持多线程
- 不支持内存替换
- 不支持信号系统
- 不支持内存映射mmap
- 只读用户页
- 系统调用规范不完全符合POSIX标准
- 不支持动态链接
- 内核态无法动态内存分配



## Tutorial


### Build



Fist of all, [Install QEMU](/docs/CS/OS/qemu.md)



#### x86

Download


```shell
git clone http://github.com/mit-pdos/xv6-public.git
```

<!-- tabs:start -->

##### **Ubuntu**




```shell
apt install
```

##### **Intel Mac**

```shell
brew install
```







<!-- tabs:end -->

#### Riscv




Download

```shell
git clone git://github.com/mit-pdos/xv6-riscv.git
```

<!-- tabs:start -->

##### **Ubuntu**

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







##### **ARM Mac**

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

<!-- tabs:end -->



### Debug


退出虚拟机时，先按下control(ctrl)键和A键，然后按X键



使用gdb调试


```shell
brew install riscv64-elf-gdb
```

第一个窗口 make qemu-gdb , 第二个窗口riscv64-elf-gdb



## Init



### x86

在源代码中，XV6系统的启动运行轨迹如图。系统的启动分为以下几个步骤：

1. 首先，在`bootasm.S`中，系统必须初始化CPU的运行状态。具体地说，需要将x86 CPU从启动时默认的Intel 8088 16位实模式切换到80386之后的32位保护模式；然后设置初始的GDT(详细解释参见https://wiki.osdev.org/Global_Descriptor_Table)，将虚拟地址直接按值映射到物理地址；最后，调用`bootmain.c`中的`bootmain()`函数。
2. `bootmain()`函数的主要任务是将内核的ELF文件从硬盘中加载进内存，并将控制权转交给内核程序。具体地说，此函数首先将ELF文件的前4096个字节（也就是第一个内存页）从磁盘里加载进来，然后根据ELF文件头里记录的文件大小和不同的程序头信息，将完整的ELF文件加载到内存中。然后根据ELF文件里记录的入口点，将控制权转交给XV6系统。
3. `entry.S`的主要任务是设置页表，让分页硬件能够正常运行，然后跳转到`main.c`的`main()`函数处，开始整个操作系统的运行。
4. `main()`函数首先初始化了与内存管理、进程管理、中断控制、文件管理相关的各种模块，然后启动第一个叫做`initcode`的用户进程。至此，整个XV6系统启动完毕。

XV6的操作系统的加载与真实情况有一些区别。首先，XV6操作系统作为教学操作系统，它的启动过程是相对比较简单的。XV6并不会在启动时对主板上的硬件做全面的检查，而真实的Bootloader会对所有连接到计算机的所有硬件的状态进行检查。此外，XV6的Boot loader足够精简，以至于能够被压缩到小于512字节，从而能够直接将Bootloader加载进0x7c00的内存位置。真实的操作系统中，通常会有一个两步加载的过程。首先将一个加载Bootloader的程序加载在0x7c00处，然后加载进完整的功能复杂的Bootloader，再使用Bootloader加载内核



```c
void
bootmain(void)
{
  struct elfhdr *elf;
  struct proghdr *ph, *eph;
  void (*entry)(void);
  uchar* pa;

  elf = (struct elfhdr*)0x10000;  // scratch space

  // Read 1st page off disk
  readseg((uchar*)elf, 4096, 0);

  // Is this an ELF executable?
  if(elf->magic != ELF_MAGIC)
    return;  // let bootasm.S handle error

  // Load each program segment (ignores ph flags).
  ph = (struct proghdr*)((uchar*)elf + elf->phoff);
  eph = ph + elf->phnum;
  for(; ph < eph; ph++){
    pa = (uchar*)ph->paddr;
    readseg(pa, ph->filesz, ph->off);
    if(ph->memsz > ph->filesz)
      stosb(pa + ph->filesz, 0, ph->memsz - ph->filesz);
  }

  // Call the entry point from the ELF header.
  // Does not return!
  entry = (void(*)(void))(elf->entry);
  entry();
}

```



`bootmain.c`中的`bootmain()`函数是XV6系统启动的核心代码。

- `bootmain()`函数首先从磁盘中读取第一个内存页；然后判断读取到的内存页是否是ELF文件的开头；
- 如果是的话，根据ELF文件头内保存的每个程序头和其长度信息，依次将程序读入内存
- 最后，从ELF文件头内找到程序的入口点，跳转到那里执行

通过`readelf`命令可以得到ELF文件中程序头的详细信息。总而言之，boot loader在XV6系统的启动中主要用来将内核的ELF文件从硬盘中加载进内存，并将控制权转交给内核程序。

通过获取`struct elfhdr`中`struct proghdr`的位置和大小信息，就能得知XV6内核程序段(Program Header)的位置和数量，在加载硬盘扇区的过程中，逐步向前移动`ph`指针，一个个加载对应的程序段。对于一个程序段，通过`ph->filesz`和`ph->off`获得程序段的大小和位置，使用`readseg()`函数来加载程序段，逐步向前移动`pa`指针，直到加载进的磁盘扇区使得加载进的扇区大小超过程序文件的结尾`epa`，从而完成单个程序段的加载。对于单个内核程序段，代码确保它会填满最后一个内存页

### RISC-V

riscv在启动时，pc被默认设置为`0X1000`，之后经过以下几条指令，跳转到`0x80000000`

- 在第一个shell，打开xv6 gdb模式`make qemu-gdb`
- 打开第二个shell，进行调试`riscv64-elf-gdb`
- 可以看到启动时，qemu就在`0X1000`地址





同时，xv6在编译时，会把引导程序放在`0x80000000`位置


```shell
riscv64-unknown-elf-objdump -d kernel/kernel
```

查看xv6中的`kernel/kernel.ld`，可以看到`. = 0x80000000;`，这一行会将初始程序`_entry`函数放置到`0x80000000`地址


```shell
kernel/kernel:     file format elf64-littleriscv

Disassembly of section .text:

0000000080000000 <_entry>:
    80000000:	00008117          	auipc	sp,0x8
    80000004:	91010113          	add	sp,sp,-1776 # 80007910 <stack0>
    80000008:	6505                	lui	a0,0x1
    8000000a:	f14025f3          	csrr	a1,mhartid
    8000000e:	0585                	add	a1,a1,1
    80000010:	02b50533          	mul	a0,a0,a1
    80000014:	912a                	add	sp,sp,a0
    80000016:	04a000ef          	jal	80000060 <start>
```





entry.S start.c main.c

Qemu设置0x8000_0000 运行entry.S的 _entry函数
调用start函数
初始化机器态特权寄存器
启用时钟中断
cpu id放入tp寄存器


调用main函数
调用schedule函数 调度初始进程initcode
执行init程序


init进程
启动sh进程
循环调用wait回收僵尸进程




entry和start运行在机器态 main运行在内核态



## Process


proc.c sleeplock.c spinlock.c


ctrl p 获取进程信息
addr2line -e kernel 调用占 查看执行停顿处

## Memory 


vm.c kalloc.c



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

xv6启动扇区代码bootblock负责bootloader的角色 将内核代码kernel装载到内存并转移控制权 

启动扇区是通过bootasm.S和bootmain.c生成bootblock.o目标文件后 通过objcopy将其中的.text抽取出来到bootblock文件中产生的

readelf -l bootblock.o



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
