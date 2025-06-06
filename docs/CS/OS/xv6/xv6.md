## Introduction

xv6 是 MIT 开发的一个教学用的完整的类 Unix 操作系统, 是UNIX Version(v6)的简单实现，并且在 MIT 的操作系统课程 [6.828](http://pdos.csail.mit.edu/6.828/2012/xv6.html) 中使用
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



安装qemu
```shell
sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils virtinst virt-manager
```
>[MIT6.828 Fall2018 笔记 - Homework 3: xv6 system calls](https://www.cnblogs.com/zsmumu/p/12622898.html)

运行时一直在 Booting from Hard Disk... , 修改kernel.ld的内容
```shell
/* Include debugging information in kernel memory */
.stab : AT(LOADADDR(.rodata) + SIZEOF(.rodata)){
```

##### **Mac**



ARM架构Mac需要安装x86版本的Homebrew



> https://github.com/nativeos/homebrew-i386-elf-toolchain

```shell
# 安装binutils gcc
brew tap nativeos/i386-elf-toolchain
brew install nativeos/i386-elf-toolchain/i386-elf-binutils
brew install nativeos/i386-elf-toolchain/i386-elf-gcc

brew install i386-elf-gdb
brew install qemu
```

修改Makefile 配置 Cross-compiling

```makefile
TOOLPREFIX = i386-elf-
```



make时mp.o文件告警

修改Makefile -Wall或者 -Werror修改成 -Wno-error



由上面mp.o编译失败导致

> file not recognized: File format not recognized

使用make clean



##### **Docker**

```shell
docker pull linxi177229/mit6.s081:latest

docker run --name mit6.s081 -itd linxi177229/mit6.s081
```

gdb

```shell
# 第一个 terminal
cd xv6-labs-2020
# 第一次执行 gdb 需要 执行 下面条语句 
echo "add-auto-load-safe-path $(pwd)/.gdbinit " >> ~/.gdbinit # 第一次执行
make CPUS=1 qemu-gdb

# 第二个 terminal
cd xv6-labs-2020
gdb-multiarch
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







##### **Mac**

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

使用`make qemu-nox` 不弹出仿真窗口


退出虚拟机时，先按下control(ctrl)键和A键，然后按X键




proc.c sleeplock.c spinlock.c

ctrl p 获取进程信息是由内核函数procdump打印
```
$ 1 sleep  init 80103fb7 8010405f 80104a6d 80105b41 80105883
2 sleep  sh 80103f80 801002ea 80101030 80104d66 80104a6d 80105b41 80105883
```
进程后面的数字是调用栈关于函数调用的返回地址 可以使用addr2line -e kernel [] 查看对应代码 将调用栈所有地址逐个检查 可以还原出进程阻塞前的函数调用嵌套情况
> i386编译的binutils使用 i386-elf-addr2line

例如上面的sh进程是通过系统 调用进入到内核的，具体过程包括alltraps->trap->syscall->sys_read()->readi()->consoleread()->sleep()





使用gdb调试


```shell
brew install riscv64-elf-gdb
```

第一个窗口 make qemu-gdb , 第二个窗口riscv64-elf-gdb

'

如果 我们希望各个线程 都受gdb控制而执行，而不是现在只控制其中一个线程，那么我们设置set-scheduler-locking=on，反之设置力off
我们还可以控制调试命令施加到指定的线程上，例如用具体的ID列表，或者用all指代所有线程

## 代码总览

xv6源代码总量较小

### x86

```shell
ls *.S
bootasm.S  entry.S  entryother.S  initcode.S  swtch.S  trapasm.S  usys.S  vectors.S

ls *.h
asm.h  date.h  elf.h    file.h  kbd.h        mmu.h  param.h  sleeplock.h  stat.h     traps.h  user.h
buf.h  defs.h  fcntl.h  fs.h    memlayout.h  mp.h   proc.h   spinlock.h   syscall.h  types.h  x86.h

ls *.c
bio.c       exec.c      ide.c     kill.c   main.c    picirq.c  sh.c         syscall.c  ulib.c       zombie.c
bootmain.c  file.c      init.c    lapic.c  memide.c  pipe.c    sleeplock.c  sysfile.c  umalloc.c
cat.c       forktest.c  ioapic.c  ln.c     mkdir.c   printf.c  spinlock.c   sysproc.c  usertests.c
console.c   fs.c        kalloc.c  log.c    mkfs.c    proc.c    stressfs.c   trap.c     vm.c
echo.c      grep.c      kbd.c     ls.c     mp.c      rm.c      string.c     uart.c     wc.c
```

xv6二进制代码分成两个部分 一个是启动扇区的bootblock 另一个是内核代码kernel 两个都是ELF格式的文件






## Init

xv6二进制代码分成两部分 bootloader和kernel



### x86

在源代码中，XV6系统的启动运行轨迹如图。系统的启动分为以下几个步骤：

1. 首先，在`bootasm.S`中，系统必须初始化CPU的运行状态。具体地说，需要将x86 CPU从启动时默认的Intel 8088 16位实模式切换到80386之后的32位保护模式；然后设置初始的GDT(详细解释参见https://wiki.osdev.org/Global_Descriptor_Table)，将虚拟地址直接按值映射到物理地址；最后，调用`bootmain.c`中的`bootmain()`函数。
2. `bootmain()`函数的主要任务是将内核的ELF文件从硬盘中加载进内存，并将控制权转交给内核程序。具体地说，此函数首先将ELF文件的前4096个字节（也就是第一个内存页）从磁盘里加载进来，然后根据ELF文件头里记录的文件大小和不同的程序头信息，将完整的ELF文件加载到内存中。然后根据ELF文件里记录的入口点，将控制权转交给XV6系统。
3. `entry.S`的主要任务是设置页表，让分页硬件能够正常运行，然后跳转到`main.c`的`main()`函数处，开始整个操作系统的运行。
4. `main()`函数首先初始化了与内存管理、进程管理、中断控制、文件管理相关的各种模块，然后启动第一个叫做`initcode`的用户进程。至此，整个XV6系统启动完毕。

XV6的操作系统的加载与真实情况有一些区别。首先，XV6操作系统作为教学操作系统，它的启动过程是相对比较简单的
XV6并不会在启动时对主板上的硬件做全面的检查，而真实的Bootloader会对所有连接到计算机的所有硬件的状态进行检查。
此外，XV6的Boot loader足够精简，以至于能够bootblock能被压缩到512字节，从而能够直接加载进0x7c00的内存位置
真实的操作系统中，通常会有一个两步加载的过程。首先将一个加载Bootloader的程序加载在0x7c00处，然后加载进完整的功能复杂的Bootloader，再使用Bootloader加载内核



Start the first CPU: switch to 32-bit protected mode, jump into C.
The BIOS loads this code from the first sector of the hard disk into memory at physical address 0x7c00 and starts executing in real mode with %cs=0 %ip=7c00.

```asm
.code16                       # Assemble for 16-bit mode
.globl start
start:
  cli                         # BIOS enabled interrupts; disable

  # Zero data segment registers DS, ES, and SS.
  xorw    %ax,%ax             # Set %ax to zero
  movw    %ax,%ds             # -> Data Segment
  movw    %ax,%es             # -> Extra Segment
  movw    %ax,%ss             # -> Stack Segment
```

> The A20 Address Line is the physical representation of the 21st bit (number 20, counting from 0) of any memory access. When the IBM-AT (Intel 286) was introduced, it was able to access up to sixteen megabytes of memory (instead of the 1 MByte of the 8086). But to remain compatible with the 8086, a quirk in the 8086 architecture (memory wraparound) had to be duplicated in the AT. To achieve this, the A20 line on the address bus was disabled by default.
The wraparound was caused by the fact the 8086 could only access 1 megabyte of memory, but because of the segmented memory model it could effectively address up to 1 megabyte and 64 kilobytes (minus 16 bytes). Because there are 20 address lines on the 8086 (A0 through A19), any address above the 1 megabyte mark wraps around to zero. For some reason a few short-sighted programmers decided to write programs that actually used this wraparound (rather than directly addressing the memory at its normal location at the bottom of memory). Therefore in order to support these 8086-era programs on the new processors, this wraparound had to be emulated on the IBM AT and its compatibles; this was originally achieved by way of a latch that by default set the A20 line to zero. Later the 486 added the logic into the processor and introduced the A20M pin to control it.
> For an operating system developer (or Bootloader developer) this means the A20 line has to be enabled so that all memory can be accessed. This started off as a simple hack but as simpler methods were added to do it, it became harder to program code that would definitely enable it and even harder to program code that would definitely disable it.



在初始化好寄存器后，xv6 bootasm.S 接下来要做的事情就是打开 A20 gate 突破 1MB 内存寻址的限制。
控制 A20 gate 的方法有 3 种：
- 804x 键盘控制器法
- Fast A20 法
- BIOS 中断法

xv6 用了第一种 804x 键盘控制器法，这也是最古老且效率最慢的一种。当然因为硬件的不同，这三种方法可能不会被硬件都支持，正确的做法应该是这三种都尝试一下，每尝试一个就验证一下 A20 gate 是否被正确打开以保证兼容各种硬件。但是 xv6 作为一款教学用的操作系统就没必要做的这么复杂里。只用了一种最古老的方法（保证兼容大多数硬件）而且没有对打开成功与否做验证。像诸如 Linux 这样的操作系统就把三种方法的实现都做好里，并且加上了验证机制。

在开启A20线之前需要关闭中断以防止我们的内核陷入混乱。命令字节是通过端口0x64来发送的

我们具体来看 xv6 的实现代码
bootasm.S 用了两个方法 seta20.1 和 seta20.2 来实现通过 804x 键盘控制器打开 A20 gate

```
seta20.1:
  inb     $0x64,%al               # Wait for not busy
  testb   $0x2,%al
  jnz     seta20.1

  movb    $0xd1,%al               # 0xd1 -> port 0x64, prepare write to 0x60
  outb    %al,$0x64

seta20.2:
  inb     $0x64,%al               # Wait for not busy
  testb   $0x2,%al
  jnz     seta20.2

  movb    $0xdf,%al               # 0xdf -> port 0x60
  outb    %al,$0x60
```


在进入保护模式前需要将 GDT 准备好


根据 SEG_ASM宏构建了两个段描述符：代码段描述符和数据段描述符，因为代码段在 GDT 中的
索引设为 1，所以先构建的代码段描述符。 GDT第一个描述符是没用的，所以直接设置为 0。



```

# asm.h

#define SEG_NULLASM                                             \
        .word 0, 0;                                             \
        .byte 0, 0, 0, 0

// The 0xC0 means the limit is in 4096-byte units
// and (for executable segments) 32-bit mode.
#define SEG_ASM(type,base,lim)                                  \
        .word (((lim) >> 12) & 0xffff), ((base) & 0xffff);      \
        .byte (((base) >> 16) & 0xff), (0x90 | (type)),         \
                (0xC0 | (((lim) >> 28) & 0xf)), (((base) >> 24) & 0xff)



# Bootstrap GDT
.p2align 2                                # force 4 byte alignment
gdt:
  SEG_NULLASM                             # null seg
  SEG_ASM(STA_X|STA_R, 0x0, 0xffffffff)   # code seg
  SEG_ASM(STA_W, 0x0, 0xffffffff)         # data seg





```

构建 GDT位置信息
CPU需要知道构建的GDT在哪，所以需要将GDT的起始地址和界限这两样信息加载到GDTR寄存器
gdtdesc即为 需GDTR要的 48 位位置信息指针，它包括了GDT的起始位置和界限


```
gdtdesc:
  .word   (gdtdesc - gdt - 1)             # sizeof(gdt) - 1
  .long   gdt                             # address gdt

```
加载 有专门的指令

```
  lgdt    gdtdesc
```

将 寄存器的 PE 位置 1 开启保护模式

```

  movl    %cr0, %eax
  orl     $CR0_PE, %eax
  movl    %eax, %cr0
```

从此开始进入保护模式，16 位的 CPU 变成了 32 位的 CPU，此刻前后的指令格式也是不一样的，在
此之前使用的 16 位指令，在此之后使用的 32 位指令，这里所说的多少位的指令不是说这个指令的长
度，而是两种模式下指令的编码都不一样，也就是说同一条指令在两种模式下的机器码可能不一样。
但是我们应该都知道，为了加快 CPU 执行指令的效率，存在着一种机制：流水线，简单来说，就是把
多条指令加载到流水线上，同时运行不同指令不同部分。问题就出在这儿，进入保护模式后流水线上可
能还存在 16位的指令，所以进入保护模式后需要清空流水线，无条件跳转 指令可以用来清空流水线



这里就是使用了一个长跳指令来刷新流水线，顺便设置 和 寄存器，因为现在是保护模式
了，段寄存器的可见部分应存放的是段选择子，所以将 内核代码段选择子写进
，这里的 相当于选择子的 域，所以左移3位。左移操作右边添 0，这页
说明 位为 0 表示 ，位域为0，表特权级0，也就是内核态





```

#define SEG_KCODE 1

ljmp    $(SEG_KCODE<<3), $start32

```
上面那个长跳跳转到此



```
start32:
  # Set up the protected-mode data segment registers
  movw    $(SEG_KDATA<<3), %ax    # Our data segment selector
  movw    %ax, %ds                # -> DS: Data Segment
  movw    %ax, %es                # -> ES: Extra Segment
  movw    %ax, %ss                # -> SS: Stack Segment
  movw    $0, %ax                 # Zero segments not ready for use
  movw    %ax, %fs                # -> FS
  movw    %ax, %gs                # -> GS

  # Set up the stack pointer and call into C.
  movl    $start, %esp 						# set 0x7c00
  call    bootmain


```


#### bootmain


bootmain.c做的相当于bootloader的工作 加载kernel

运行 的时候是将 以下作为栈使用，根据内存低 1M 布局图可以看出，以下有大约 30K 的空闲空间



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



```assembly
# The xv6 kernel starts executing in this file. This file is linked with
# the kernel C code, so it can refer to kernel symbols such as main().
# The boot block (bootasm.S and bootmain.c) jumps to entry below.
        
# Multiboot header, for multiboot boot loaders like GNU Grub.
# http://www.gnu.org/software/grub/manual/multiboot/multiboot.html
#
# Using GRUB 2, you can boot xv6 from a file stored in a
# Linux file system by copying kernel or kernelmemfs to /boot
# and then adding this menu entry:
#
# menuentry "xv6" {
# 	insmod ext2
# 	set root='(hd0,msdos1)'
# 	set kernel='/boot/kernel'
# 	echo "Loading ${kernel}..."
# 	multiboot ${kernel} ${kernel}
# 	boot
# }

#include "asm.h"
#include "memlayout.h"
#include "mmu.h"
#include "param.h"

# Multiboot header.  Data to direct multiboot loader.
.p2align 2
.text
.globl multiboot_header
multiboot_header:
  #define magic 0x1badb002
  #define flags 0
  .long magic
  .long flags
  .long (-magic-flags)

# By convention, the _start symbol specifies the ELF entry point.
# Since we haven't set up virtual memory yet, our entry point is
# the physical address of 'entry'.
.globl _start
_start = V2P_WO(entry)

# Entering xv6 on boot processor, with paging off.
.globl entry
entry:
  # Turn on page size extension for 4Mbyte pages
  movl    %cr4, %eax
  orl     $(CR4_PSE), %eax
  movl    %eax, %cr4
  # Set page directory
  movl    $(V2P_WO(entrypgdir)), %eax
  movl    %eax, %cr3
  # Turn on paging.
  movl    %cr0, %eax
  orl     $(CR0_PG|CR0_WP), %eax
  movl    %eax, %cr0

  # Set up the stack pointer.
  movl $(stack + KSTACKSIZE), %esp

  # Jump to main(), and switch to executing at
  # high addresses. The indirect call is needed because
  # the assembler produces a PC-relative instruction
  # for a direct jump.
  mov $main, %eax
  jmp *%eax

.comm stack, KSTACKSIZE
```



#### xv6#main



```c

// Bootstrap processor starts running C code here.
// Allocate a real stack and switch to it, first
// doing some setup required for memory allocator to work.
int
main(void)
{
  kinit1(end, P2V(4*1024*1024)); // phys page allocator
  kvmalloc();      // kernel page table
  mpinit();        // detect other processors
  lapicinit();     // interrupt controller
  seginit();       // segment descriptors
  cprintf("\ncpu%d: starting xv6\n\n", cpunum());
  picinit();       // another interrupt controller
  ioapicinit();    // another interrupt controller
  consoleinit();   // console hardware
  uartinit();      // serial port
  pinit();         // process table
  tvinit();        // trap vectors
  binit();         // buffer cache
  fileinit();      // file table
  ideinit();       // disk
  if(!ismp)
    timerinit();   // uniprocessor timer
  startothers();   // start other processors
  kinit2(P2V(4*1024*1024), P2V(PHYSTOP)); // must come after startothers()
  userinit();      // first user process
  mpmain();        // finish this processor's setup
}
```

xv6定义了一个全局的CPU数据结构，mpinit函数就是探寻有多少个CPU然后初始化的 ，每个CPU都对应着一个 LAPIC， LAPIC的ID也就可以用来唯一标识




```c

struct cpu cpus[NCPU];
int ncpu;

```


##### mpinit


```c


void
mpinit(void)
{
  uchar *p, *e;
  struct mp *mp;
  struct mpconf *conf;
  struct mpproc *proc;
  struct mpioapic *ioapic;

  if((conf = mpconfig(&mp)) == 0)
    return;
  ismp = 1;
  lapic = (uint*)conf->lapicaddr;
  for(p=(uchar*)(conf+1), e=(uchar*)conf+conf->length; p<e; ){
    switch(*p){
    case MPPROC:
      proc = (struct mpproc*)p;
      if(ncpu < NCPU) {
        cpus[ncpu].apicid = proc->apicid;  // apicid may differ from ncpu
        ncpu++;
      }
      p += sizeof(struct mpproc);
      continue;
    case MPIOAPIC:
      ioapic = (struct mpioapic*)p;
      ioapicid = ioapic->apicno;
      p += sizeof(struct mpioapic);
      continue;
    case MPBUS:
    case MPIOINTR:
    case MPLINTR:
      p += 8;
      continue;
    default:
      ismp = 0;
      break;
    }
  }
  if(!ismp){
    // Didn’t like what we found; fall back to no MP.
    ncpu = 1;
    lapic = 0;
    ioapicid = 0;
    return;
  }

  if(mp->imcrp){
    // Bochs doesn’t support IMCR, so this doesn’t run on Bochs.
    // But it would on real hardware.
    outb(0x22, 0x70);   // Select IMCR
    outb(0x23, inb(0x23) | 1);  // Mask external interrupts.
  }
}
```

Start the non-boot (AP) processors

```c

static void
startothers(void)
{
  extern uchar _binary_entryother_start[], _binary_entryother_size[];
  uchar *code;
  struct cpu *c;
  char *stack;

  // Write entry code to unused memory at 0x7000.
  // The linker has placed the image of entryother.S in
  // _binary_entryother_start.
  code = P2V(0x7000);
  memmove(code, _binary_entryother_start, (uint)_binary_entryother_size);

  for(c = cpus; c < cpus+ncpu; c++){
    if(c == cpus+cpunum())  // We’ve started already.
      continue;

    // Tell entryother.S what stack to use, where to enter, and what
    // pgdir to use. We cannot use kpgdir yet, because the AP processor
    // is running in low  memory, so we use entrypgdir for the APs too.
    stack = kalloc();
    *(void**)(code-4) = stack + KSTACKSIZE;
    *(void**)(code-8) = mpenter;
    *(int**)(code-12) = (void *) V2P(entrypgdir);

    lapicstartap(c->apicid, V2P(code));

    // wait for cpu to finish mpmain()
    while(c->started == 0)
      ;
  }
}
```

AP会执行mpenter完成启动

```

// Other CPUs jump here from entryother.S.
static void
mpenter(void)
{
  switchkvm();
  seginit();
  lapicinit();
  mpmain();
}


```


##### mpmain


CPU这个结构体中的元素started置1表示这个CPU已经启动好了，这里就会通知startothers函数，可以启动下一个AP了。最后就是调用scheduler可以开始调度执行程序了。

```c
static void
mpmain(void)
{
  cprintf(“cpu%d: starting\n”, cpunum());
  idtinit();       // load idt register
  xchg(&cpu->started, 1); // tell startothers() we’re up
  scheduler();     // start running processes
}

```


执行完startothers ，所有的AP就启动好了，最后BSP本身再执行mpmain自身完成启动




### RISC-V



查看Makefile里qemu的配置 会用 `-kernel $K/kernel` 参数指定内核文件，`-file fs.img` 参数指定文件系统镜像

```makefile
QEMU = qemu-system-riscv64

QEMUOPTS = -machine virt -bios none -kernel $K/kernel -m 128M -smp $(CPUS) -nographic
QEMUOPTS += -global virtio-mmio.force-legacy=false
QEMUOPTS += -drive file=fs.img,if=none,format=raw,id=x0
QEMUOPTS += -device virtio-blk-device,drive=x0,bus=virtio-mmio-bus.0

qemu: $K/kernel fs.img
    $(QEMU) $(QEMUOPTS)

.gdbinit: .gdbinit.tmpl-riscv
    sed "s/:1234/:$(GDBPORT)/" < $^ > $@

qemu-gdb: $K/kernel .gdbinit fs.img
    @echo "*** Now run 'gdb' in another window." 1>&2
    $(QEMU) $(QEMUOPTS) -S $(QEMUGDB)
```



```makefile
K=kernel
U=user

OBJS = \
  $K/entry.o \
  $K/start.o \
  $K/console.o \
  $K/printf.o \
  $K/uart.o \
  $K/kalloc.o \
  $K/spinlock.o \
  $K/string.o \
  $K/main.o \
  $K/vm.o \
  $K/proc.o \
  $K/swtch.o \
  $K/trampoline.o \
  $K/trap.o \
  $K/syscall.o \
  $K/sysproc.o \
  $K/bio.o \
  $K/fs.o \
  $K/log.o \
  $K/sleeplock.o \
  $K/file.o \
  $K/pipe.o \
  $K/exec.o \
  $K/sysfile.o \
  $K/kernelvec.o \
  $K/plic.o \
  $K/virtio_disk.o

LD = $(TOOLPREFIX)ld
LDFLAGS = -z max-page-size=4096
  
$K/kernel: $(OBJS) $K/kernel.ld $U/initcode
	$(LD) $(LDFLAGS) -T $K/kernel.ld -o $K/kernel $(OBJS) 
	$(OBJDUMP) -S $K/kernel > $K/kernel.asm
	$(OBJDUMP) -t $K/kernel | sed '1,/SYMBOL TABLE/d; s/ .* / /; /^$$/d' > $K/kernel.sym
```





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

kernel.ld文件中可以得知kernel文件的入口为 `_entry` 函数

```assembly
UTPUT_ARCH( "riscv" )
ENTRY( _entry )

SECTIONS
{
  /*
   * ensure that entry.S / _entry is at 0x80000000,
   * where qemu's -kernel jumps.
   */
  . = 0x80000000;

  .text : {
    *(.text .text.*)
    . = ALIGN(0x1000);
    _trampoline = .;
    *(trampsec)
    . = ALIGN(0x1000);
    ASSERT(. - _trampoline == 0x1000, "error: trampoline larger than one page");
    PROVIDE(etext = .);
  }

  .rodata : {
    . = ALIGN(16);
    *(.srodata .srodata.*) /* do not need to distinguish this from .rodata */
    . = ALIGN(16);
    *(.rodata .rodata.*)
  }

  .data : {
    . = ALIGN(16);
    *(.sdata .sdata.*) /* do not need to distinguish this from .data */
    . = ALIGN(16);
    *(.data .data.*)
  }

  .bss : {
    . = ALIGN(16);
    *(.sbss .sbss.*) /* do not need to distinguish this from .bss */
    . = ALIGN(16);
    *(.bss .bss.*)
  }

  PROVIDE(end = .);
}

```

_entry函数主要用于开辟栈空间，以便后续运行C代码 每一个CPU都会有自己的栈，将栈指针指向stack0 + 4096 * CPU_ID 位置

```assembly
.section .text
.global _entry
_entry:
        # set up a stack for C.
        # stack0 is declared in start.c,
        # with a 4096-byte stack per CPU.
        # sp = stack0 + (hartid * 4096)
        la sp, stack0
        li a0, 1024*4
        csrr a1, mhartid
        addi a1, a1, 1
        mul a0, a0, a1
        add sp, sp, a0
        # jump to start() in start.c
        call start
spin:
        j spin
```

设置 MSTATUS 寄存器，下一步跳转到Supervisor Mode；设置EPC，控制下一步跳转到main；关闭分页机制；将所有的**中断**和**异常**都**委托**给Supervisor态；将所有物理内存的访问权限都分配给Supervisor态；启动时钟中断(`timerinit`, )；将当前的hard id都保存在tp寄存器（Thread Pointer）；之后使用`mret`指令跳转到Supervisor态 开始执行main函数



```c
// entry.S needs one stack per CPU.
__attribute__ ((aligned (16))) char stack0[4096 * NCPU];

// entry.S jumps here in machine mode on stack0.
void
start()
{
  // set M Previous Privilege mode to Supervisor, for mret.
  unsigned long x = r_mstatus();
  x &= ~MSTATUS_MPP_MASK;
  x |= MSTATUS_MPP_S;
  w_mstatus(x);

  // set M Exception Program Counter to main, for mret.
  // requires gcc -mcmodel=medany
  w_mepc((uint64)main);

  // disable paging for now.
  w_satp(0);

  // delegate all interrupts and exceptions to supervisor mode.
  w_medeleg(0xffff);
  w_mideleg(0xffff);
  w_sie(r_sie() | SIE_SEIE | SIE_STIE | SIE_SSIE);

  // configure Physical Memory Protection to give supervisor mode
  // access to all of physical memory.
  w_pmpaddr0(0x3fffffffffffffull);
  w_pmpcfg0(0xf);

  // ask for clock interrupts.
  timerinit();

  // keep each CPU's hartid in its tp register, for cpuid().
  int id = r_mhartid();
  w_tp(id);

  // switch to supervisor mode and jump to main().
  asm volatile("mret");
}
```



时钟中断

用户态发生时钟中断时，首先由M状态捕获，进入timervec，然后设置S态的software int中断，mret返回用户态；之后用户态检测到S态的software异常，跳转到S态，执行对应的中断处理程序，最后通过sret返回用户态

```c
// ask each hart to generate timer interrupts.
void
timerinit()
{
  // enable supervisor-mode timer interrupts.
  w_mie(r_mie() | MIE_STIE);
  
  // enable the sstc extension (i.e. stimecmp).
  w_menvcfg(r_menvcfg() | (1L << 63)); 
  
  // allow supervisor to use stimecmp and time.
  w_mcounteren(r_mcounteren() | 2);
  
  // ask for the very first timer interrupt.
  w_stimecmp(r_time() + 1000000);
}
```

`main` 函数初始化所有设备和子系统，初始化地址空间，创建内核页表，分配一个物理内存页给内核栈

main 函数调用 userinit 函数创建第一个用户进程



第一个用户进程执行的代码就是 `user/initcode.S` 中代码，其实际上就是调用 `exec("\init", 0)`, 执行init程序

init程序创建文件描述符0,1,2，并开启一个shell窗口 init程序子进程是一个shell，其本身在无限循环处理孤儿进程



entry.S start.c main.c

Qemu设置0x8000_0000 运行entry.S的 _entry函数
调用start函数
初始化机器态特权寄存器
启用时钟中断
cpu id放入tp寄存器

调用main函数



#### riscv#main



如果不是CPU0，则会循环等待CPU0进行系统初始化完成之后，才会进行下一步操作

`__sync_synchronize` 阻止编译器重排 搭配 `volatile` 确保 started 字段

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



#### userinit

`userinit`函数代码，首先会通过`allocproc` 函数为第一个用户进程分配进程结构体proc，然后将`initproc`变量指向这个第一个用户进程的进程结构体

通过`uvminit`函数给进程分配一个页，且将initcode放置到这个页中，设置当前进程所占内存大小为PGSIZE `uvminit`函数其实只服务于第一个进程的创建，主要是将initcode代码放到虚拟内存地址为 **0x0** 的位置上面



将进程名称设置为`initcode`，将进程所在目录设置为`/`，将进程状态设置为`RUNNABLE` 随后等待main函数执行调度函数

```c
// Set up first user process.
void
userinit(void)
{
  struct proc *p;

  p = allocproc();
  initproc = p;
  
  // allocate one user page and copy initcode's instructions
  // and data into it.
  uvmfirst(p->pagetable, initcode, sizeof(initcode));
  p->sz = PGSIZE;

  // prepare for the very first "return" from kernel to user.
  p->trapframe->epc = 0;      // user program counter
  p->trapframe->sp = PGSIZE;  // user stack pointer

  safestrcpy(p->name, "initcode", sizeof(p->name));
  p->cwd = namei("/");

  p->state = RUNNABLE;

  release(&p->lock);
}
```



```c
// a user program that calls exec("/init")
// assembled from ../user/initcode.S
// od -t xC ../user/initcode
uchar initcode[] = {
  0x17, 0x05, 0x00, 0x00, 0x13, 0x05, 0x45, 0x02,
  0x97, 0x05, 0x00, 0x00, 0x93, 0x85, 0x35, 0x02,
  0x93, 0x08, 0x70, 0x00, 0x73, 0x00, 0x00, 0x00,
  0x93, 0x08, 0x20, 0x00, 0x73, 0x00, 0x00, 0x00,
  0xef, 0xf0, 0x9f, 0xff, 0x2f, 0x69, 0x6e, 0x69,
  0x74, 0x00, 0x00, 0x24, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00
};
```

`user/initcode.S` 代码如下，start为其中第一个符号，编译后在二进制最前面。可以看出，start函数实际上执行的就是`exec("/init", 0)`，也就是运行/init程序

```assembly
# Initial process that execs /init.
# This code runs in user space.

#include "syscall.h"

# exec(init, argv)
.globl start
start:
        la a0, init
        la a1, argv
        li a7, SYS_exec
        ecall

# for(;;) exit();
exit:
        li a7, SYS_exit
        ecall
        jal exit

# char init[] = "/init\0";
init:
  .string "/init\0"

# char *argv[] = { init, 0 };
.p2align 2
argv:
  .quad init
  .quad 0
```



init.c`主要fork了一个子进程，然后打开shell窗口，方便用户进行交互操作。其主要做的就是`fork();exec("sh", 0);

```c
user/init.c
int
main(void)
{
  int pid, wpid;

  if(open("console", O_RDWR) < 0){
    mknod("console", CONSOLE, 0);
    open("console", O_RDWR);
  }
  dup(0);  // stdout
  dup(0);  // stderr

  for(;;){
    printf("init: starting sh\n");
    pid = fork();
    if(pid < 0){
      printf("init: fork failed\n");
      exit(1);
    }
    if(pid == 0){
      exec("sh", argv);
      printf("init: exec sh failed\n");
      exit(1);
    }

    for(;;){
      // this call to wait() returns if the shell exits,
      // or if a parentless process exits.
      wpid = wait((int *) 0);
      if(wpid == pid){
        // the shell exited; restart it.
        break;
      } else if(wpid < 0){
        printf("init: wait returned an error\n");
        exit(1);
      } else {
        // it was a parentless process; do nothing.
      }
    }
  }
}
```

shell就是不断地使用getcmd函数读取命令行的输入，然后使用`fork`来创建一个子进程。父进程调用`wait`来等待子进程执行命令。子进程调用`runcmd`来执行真正的命令

```c
int
main(void)
{
  static char buf[100];
  int fd;

  // Ensure that three file descriptors are open.
  while((fd = open("console", O_RDWR)) >= 0){
    if(fd >= 3){
      close(fd);
      break;
    }
  }

  // Read and run input commands.
  while(getcmd(buf, sizeof(buf)) >= 0){
    if(buf[0] == 'c' && buf[1] == 'd' && buf[2] == ' '){
      // Chdir must be called by the parent, not the child.
      buf[strlen(buf)-1] = 0;  // chop \n
      if(chdir(buf+3) < 0)
        fprintf(2, "cannot cd %s\n", buf+3);
      continue;
    }
    if(fork1() == 0)
      runcmd(parsecmd(buf));
    wait(0);
  }
  exit(0);
}
```





调用schedule函数 调度初始进程initcode
执行init程序


init进程
启动sh进程
循环调用wait回收僵尸进程




entry和start运行在机器态 main运行在内核态





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
4. [xv6操作系统启动过程(RISC-V)](https://juejin.cn/post/7308621051525120037)
5. [ 6.S081 All-In-One (dgs.zone)](https://xv6.dgs.zone/)
