## Introduction



在实模式地址中 CPU把内存从0开始的1KB作为一个中断向量表
表中每项占4个Byte 2Byte段基址+2Byte偏移量



Interrupt Descriptor Table(IDT)



xv6启动 在main() -> tvinit()中完成IDT的初始化

CPU不切换到内核的页表，不切换到内核的栈，不保存除`pc`外的其它寄存器。那些事需要由内核来做。在trap的过程中CPU做尽量少的工作，这是为了给软件提供尽可能高的灵活性

## x86



中断的公共入口代码alltraps和公共返回代码trapret都在trapasm.S中以汇编形式实现

Call trap(tf)

```assembly
#include "mmu.h"

  # vectors.S sends all traps here.
.globl alltraps
alltraps:
  # Build trap frame.
  pushl %ds
  pushl %es
  pushl %fs
  pushl %gs
  pushal
  
  # Set up data and per-cpu segments.
  movw $(SEG_KDATA<<3), %ax
  movw %ax, %ds
  movw %ax, %es
  movw $(SEG_KCPU<<3), %ax
  movw %ax, %fs
  movw %ax, %gs

  # Call trap(tf), where tf=%esp
  pushl %esp
  call trap
  addl $4, %esp

  # Return falls through to trapret...
.globl trapret
trapret:
  popal
  popl %gs
  popl %fs
  popl %es
  popl %ds
  addl $0x8, %esp  # trapno and errcode
  iret
```

trap.c 中定义了三个中断处理函数:

1. 其中trap())函数在前面已经提到过，它将根据中断事件编号作不同的处理。需要注意的是:对于前32个trapno编号没有相应的处理入又，也就是说xv6暂时没有处理异常的功能;
2. tvint()将利用中断向量表vectors[]数组，填写硬件使用的IDT表，其表项是一个“中断门”描述符，使用SETGATE宏创建，该函数在处理器核启动时由main()->tvinit()调用;
3. idtinit()用于将该表装入到IDTR从而生效，该操作在处理器核启动时由main()->mpmain()->idtinit()调用，也就是说在处理器准备好所有环境后才启动中断，开始正常运作

trap()函数(代码7-2的第37行)首先判断tf->trapno是否为系统调用T_SYSCALL如果是则转到syscall()
回顾前面trapframe生成结束后将esp压入堆栈，因此相当于是把trapframe起始地址作为trap()函数的参数(x86C语言函数的参数传递规范)。这就是为什么trap()函数可以用tf作为structtrapframe并访问到系统调用号的原因。

如果中断是硬件引起的，则调用相应的硬件中断处理函数。否则，xv6认为是发生了错误的操作(例如除以◎的操作)，此时如果是用户态代码引起的，则将当前进程cp->killed标志置位(将会被撤销)，否则是内核态代码引起的，只能执行panic()给出警告提示。

对于每个外设的中断，在调用相应的处理函数(例如磁盘的ideintr()之后，还需要执行lapiceoi()向lapic芯片通知中断处理已经完成

```c
#include "types.h"
#include "defs.h"
#include "param.h"
#include "memlayout.h"
#include "mmu.h"
#include "proc.h"
#include "x86.h"
#include "traps.h"
#include "spinlock.h"

// Interrupt descriptor table (shared by all CPUs).
struct gatedesc idt[256];
extern uint vectors[];  // in vectors.S: array of 256 entry pointers
struct spinlock tickslock;
uint ticks;

void
tvinit(void)
{
  int i;

  for(i = 0; i < 256; i++)
    SETGATE(idt[i], 0, SEG_KCODE<<3, vectors[i], 0);
  SETGATE(idt[T_SYSCALL], 1, SEG_KCODE<<3, vectors[T_SYSCALL], DPL_USER);

  initlock(&tickslock, "time");
}

void
idtinit(void)
{
  lidt(idt, sizeof(idt));
}

//PAGEBREAK: 41
void
trap(struct trapframe *tf)
{
  if(tf->trapno == T_SYSCALL){
    if(proc->killed)
      exit();
    proc->tf = tf;
    syscall();
    if(proc->killed)
      exit();
    return;
  }

  switch(tf->trapno){
  case T_IRQ0 + IRQ_TIMER:
    if(cpunum() == 0){
      acquire(&tickslock);
      ticks++;
      wakeup(&ticks);
      release(&tickslock);
    }
    lapiceoi();
    break;
  case T_IRQ0 + IRQ_IDE:
    ideintr();
    lapiceoi();
    break;
  case T_IRQ0 + IRQ_IDE+1:
    // Bochs generates spurious IDE1 interrupts.
    break;
  case T_IRQ0 + IRQ_KBD:
    kbdintr();
    lapiceoi();
    break;
  case T_IRQ0 + IRQ_COM1:
    uartintr();
    lapiceoi();
    break;
  case T_IRQ0 + 7:
  case T_IRQ0 + IRQ_SPURIOUS:
    cprintf("cpu%d: spurious interrupt at %x:%x\n",
            cpunum(), tf->cs, tf->eip);
    lapiceoi();
    break;

  //PAGEBREAK: 13
  default:
    if(proc == 0 || (tf->cs&3) == 0){
      // In kernel, it must be our mistake.
      cprintf("unexpected trap %d from cpu %d eip %x (cr2=0x%x)\n",
              tf->trapno, cpunum(), tf->eip, rcr2());
      panic("trap");
    }
    // In user space, assume process misbehaved.
    cprintf("pid %d %s: trap %d err %d on cpu %d "
            "eip 0x%x addr 0x%x--kill proc\n",
            proc->pid, proc->name, tf->trapno, tf->err, cpunum(), tf->eip,
            rcr2());
    proc->killed = 1;
  }

  // Force process exit if it has been killed and is in user space.
  // (If it is still executing in the kernel, let it keep running
  // until it gets to the regular system call return.)
  if(proc && proc->killed && (tf->cs&3) == DPL_USER)
    exit();

  // Force process to give up CPU on clock tick.
  // If interrupts were on while locks held, would need to check nlock.
  if(proc && proc->state == RUNNING && tf->trapno == T_IRQ0+IRQ_TIMER)
    yield();

  // Check if the process has been killed since we yielded
  if(proc && proc->killed && (tf->cs&3) == DPL_USER)
    exit();
}
```



```c
// mmu.h
struct gatedesc {
  uint off_15_0 : 16;   // low 16 bits of offset in segment
  uint cs : 16;         // code segment selector
  uint args : 5;        // # args, 0 for interrupt/trap gates
  uint rsv1 : 3;        // reserved(should be zero I guess)
  uint type : 4;        // type(STS_{TG,IG32,TG32})
  uint s : 1;           // must be 0 (system)
  uint dpl : 2;         // descriptor(meaning new) privilege level
  uint p : 1;           // Present
  uint off_31_16 : 16;  // high bits of offset in segment
};
```



`main` 函数初始化所有设备和子系统，初始化地址空间，创建内核页表，分配一个物理内存页给内核栈

main 函数调用 userinit 函数创建第一个用户进程



第一个用户进程执行的代码就是 `user/initcode.S` 中代码，其实际上就是调用 `exec("\init", 0)`, 执行init程序

init程序创建文件描述符0,1,2，并开启一个shell窗口 init程序子进程是一个shell，其本身在无限循环处理孤儿进程



x86处理器利用IDT 表，将“外部事件或异常事件”和相应的处理代码联系起来。 IDT表共有256项，一部分是与确定事件(除0、非法指令等异常)相关联，它们 占据了0~ 31 项，剩余的表项可以自由使用。xv6 将32~63项共32 个表项与32 个硬件外设中断相关联, 其中第 6 4 项与系统调用的INT指令相关联

xv6用到的中断/异常编号见trap.h

- 前面32个是x86处理器硬件规定的专用编号
- 外设I/O中断使用T_IRQ0 = 32 之后的向量号

```c
// Processor-defined:
#define T_DIVIDE         0      // divide error
#define T_DEBUG          1      // debug exception
#define T_NMI            2      // non-maskable interrupt
#define T_BRKPT          3      // breakpoint
#define T_OFLOW          4      // overflow
#define T_BOUND          5      // bounds check
#define T_ILLOP          6      // illegal opcode
#define T_DEVICE         7      // device not available
#define T_DBLFLT         8      // double fault
// #define T_COPROC      9      // reserved (not used since 486)
#define T_TSS           10      // invalid task switch segment
#define T_SEGNP         11      // segment not present
#define T_STACK         12      // stack exception
#define T_GPFLT         13      // general protection fault
#define T_PGFLT         14      // page fault
// #define T_RES        15      // reserved
#define T_FPERR         16      // floating point error
#define T_ALIGN         17      // aligment check
#define T_MCHK          18      // machine check
#define T_SIMDERR       19      // SIMD floating point error

// These are arbitrarily chosen, but with care not to overlap
// processor defined exceptions or interrupt vectors.
#define T_SYSCALL       64      // system call
#define T_DEFAULT      500      // catchall

#define T_IRQ0          32      // IRQ 0 corresponds to int T_IRQ

#define IRQ_TIMER        0
#define IRQ_KBD          1
#define IRQ_COM1         4
#define IRQ_IDE         14
#define IRQ_ERROR       19
#define IRQ_SPURIOUS    31
```

IDT表中的每一项都指向相关联的处理代码入口，这些入口处理代码只是简 单地往 内 核 栈中 压 入 中 断 事 件 编 号 ，转 入 公 共 处 理 代 码 的 入 又 处， 然后 再 根 据 事 件 编 号 进 行 区 别 处理。IDT表的内容依据中断向量表vectors[]数 组而填写，其关系 如图7-2 所示。所谓 中断向量，就是相应的处理代码的入又地址。I DT表可以简单认为是人又地址表，但 其 还 有 更 复 杂 的 控 制 功 能 ，例 如 运行 级 别 等 等

## RISC-V

发生中断后 若确定是系统调用





## Links

- [xv6](/docs/CS/OS/xv6/xv6.md)