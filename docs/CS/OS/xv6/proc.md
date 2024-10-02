## Introduction

在xv6里没有多用户的概念。用Unix术语来说，所有xv6进程都是作为根用户来运行的



进程管理的数据结构被叫做进程控制块(Process Control Block, PCB)。一个进程的PCB必须存储以下两类信息：

1. 操作系统管理运行的进程所需要信息，比如优先级、进程ID、进程上下文等
2. 一个应用程序运行所需要的全部环境，比如虚拟内存的信息、打开的文件和IO设备的信息等。

与前述的两类信息的对应关系如下

1. 操作系统管理进程有关的信息：内核栈`kstack`，进程的状态`state`，进程的`pid`，进程的父进程`parent`，进程的中断帧`tf`，进程的上下文`context`，与`sleep`和`kill`有关的`chan`和`killed`变量。
2. 进程本身运行所需要的全部环境：虚拟内存信息`sz`和`pgdir`，打开的文件`ofile`和当前目录`cwd`。

额外地，`proc`中还有一条用于调试的进程名字`name`

```c

enum procstate { UNUSED, USED, SLEEPING, RUNNABLE, RUNNING, ZOMBIE };
```




<div style="text-align: center;">

![](./img/process-state.svg)

</div>

<p style="text-align: center;">Fig.1. xv6 process state</p>



## x86



在操作系统中，ptable.proc[NPR OC]数组用于记录所有 进程 的PCB;initproc是i n i t 进 程的 P C ，`ptable`的定义如下

```c
struct {
  struct spinlock lock;
  struct proc proc[NPROC];
} ptable;
```

由于各个处 理器共享一个全局进程表(ptable)，因此 xv6 的调度算法采用了极简单的时间片轮转算法。因为各处理器核上的调度器并发地共享 一 个就绪进程 队列, 所以需要用自旋锁进行互斥保护

定时器每 经过一个计时周期tick就会发出时钟中断，每次都会经时钟中断处理函数 进入到调度函数，从而引 发一 次调度。调度器则是简单地循环扫描pt abl e[]，找到下一个就绪 进程，并且切换过去 也就是说，xv6的时间片并不是指一个进程每 次能执 行一个时间片tick 对应 的时长， 而是不管该进程什么时候开始拥 有CPU的，只要到下一个 时钟tick就 必须再次调度。 每 一 遍 轮 转 过 程 中，各 个 进程 所 占 有 的 C P U 时 间 是 不 确 定 的 ，小 于 或 等 于 一 个 时 钟 t i c k 长度。例如某个进程A在执行了半个tick时间然后阻 塞睡眠，此时调度器执行另一个就 绪进程B，那么B 执行半个tick后就将面临下一次调度



除了被动的定时中断原因外，还可能因为进程发 出系统调用进入内核，出于某些原因 而需要 阻塞，从而主动要求切换到其他进程。例如发 出磁盘读写操作、或者直接进行 s l e e p 系 统 调 用 都 可 能 进 入 阻 塞 并切 换 到 其 他 进 程





CPU



```c
// Per-CPU state
struct cpu {
  uchar apicid;                // Local APIC ID
  struct context *scheduler;   // swtch() here to enter scheduler
  struct taskstate ts;         // Used by x86 to find stack for interrupt
  struct segdesc gdt[NSEGS];   // x86 global descriptor table
  volatile uint started;       // Has the CPU started?
  int ncli;                    // Depth of pushcli nesting.
  int intena;                  // Were interrupts enabled before pushcli?

  // Cpu-local storage variables; see below
  struct cpu *cpu;
  struct proc *proc;           // The currently-running process.
};

extern struct cpu cpus[NCPU];
extern int ncpu;

// Per-CPU variables, holding pointers to the
// current cpu and to the current process.
// The asm suffix tells gcc to use "%gs:0" to refer to cpu
// and "%gs:4" to refer to proc.  seginit sets up the
// %gs segment register so that %gs refers to the memory
// holding those two variables in the local cpu's struct cpu.
// This is similar to how thread-local variables are implemented
// in thread libraries such as Linux pthreads.
extern struct cpu *cpu asm("%gs:0");       // &cpus[cpunum()]
extern struct proc *proc asm("%gs:4");     // cpus[cpunum()].proc
```





## RISC-V






```c
struct proc {
  struct spinlock lock;

  // p->lock must be held when using these:
  enum procstate state;        // Process state
  void *chan;                  // If non-zero, sleeping on chan
  int killed;                  // If non-zero, have been killed
  int xstate;                  // Exit status to be returned to parent's wait
  int pid;                     // Process ID

  // wait_lock must be held when using this:
  struct proc *parent;         // Parent process

  // these are private to the process, so p->lock need not be held.
  uint64 kstack;               // Virtual address of kernel stack
  uint64 sz;                   // Size of process memory (bytes)
  pagetable_t pagetable;       // User page table
  struct trapframe *trapframe; // data page for trampoline.S
  struct context context;      // swtch() here to run process
  struct file *ofile[NOFILE];  // Open files
  struct inode *cwd;           // Current directory
  char name[16];               // Process name (debugging)
}
```

scheduler

```c
// Per-CPU process scheduler.
// Each CPU calls scheduler() after setting itself up.
// Scheduler never returns.  It loops, doing:
//  - choose a process to run.
//  - swtch to start running that process.
//  - eventually that process transfers control
//    via swtch back to the scheduler.
void
scheduler(void)
{
  struct proc *p;
  struct cpu *c = mycpu();

  c->proc = 0;
  for(;;){
    // The most recent process to run may have had interrupts
    // turned off; enable them to avoid a deadlock if all
    // processes are waiting.
    intr_on();

    int found = 0;
    for(p = proc; p < &proc[NPROC]; p++) {
      acquire(&p->lock);
      if(p->state == RUNNABLE) {
        // Switch to chosen process.  It is the process's job
        // to release its lock and then reacquire it
        // before jumping back to us.
        p->state = RUNNING;
        c->proc = p;
        swtch(&c->context, &p->context);

        // Process is done running for now.
        // It should have changed its p->state before coming back.
        c->proc = 0;
        found = 1;
      }
      release(&p->lock);
    }
    if(found == 0) {
      // nothing to run; stop running on this core until an interrupt.
      intr_on();
      asm volatile("wfi");
    }
  }
}
```



## Links

- [xv6](/docs/CS/OS/xv6/xv6.md)