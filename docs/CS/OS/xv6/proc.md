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



在操作系统中，所有的进程信息`struct proc`都存储在`ptable`中，`ptable`的定义如下

```c
struct {
  struct spinlock lock;
  struct proc proc[NPROC];
} ptable;
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