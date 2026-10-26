## Introduction

xv6 的启动（boot）是理解整个内核的入口：它把"加电/复位后 CPU 处于什么状态"一步步带到"第一个用户进程 `init` 在跑 `sh`"。这段链路在 xv6 里被刻意做得极简——没有复杂的两级 Bootloader、不做硬件全面自检，目的就是让读者能盯住每一条指令。

xv6 有两个官方移植版，**启动路径差别很大**：

- **x86 版**（早期 6.828 用）：BIOS 把 512 字节 `bootblock` 载入 `0x7c00`，从 16 位实模式切到 32 位保护模式，再 `bootmain` 把内核 ELF 读进内存、打开分页，最后进 `main()`。
- **RISC-V 版**（6.S081 用）：QEMU 的 `-kernel` 直接把内核放到 `0x80000000`，`_entry` 给每个 hart 铺好栈后调 `start()`，在 **Machine 态**配置好特权寄存器、用 `mret` 降权到 **Supervisor 态**后才进 `main()`。

两条移植的收尾是同一套：内核 `main()` 初始化各子系统 → `userinit()` 造出第一个用户进程 → 该进程 `exec("/init")` → `init` 进程 `fork+exec` 出 `sh`。

下文先讲 x86，再讲 RISC-V，最后对比两者的特权模型。涉及分页/页表、trap 进入、进程调度的细节分别见 [memory](/docs/CS/OS/xv6/memory.md)、[Interrupt](/docs/CS/OS/xv6/Interrupt.md) 与 [proc](/docs/CS/OS/xv6/proc.md)。

## x86 启动流程

系统上电后 BIOS 把硬盘第一扇区（512 字节）载入物理地址 `0x7c00` 并以实模式开始执行。xv6 的这段代码由 `bootasm.S` 与 `bootmain.c` 组成，最终被 `objcopy` 抽出 `.text` 拼成 `bootblock`。整体分四步：

1. `bootasm.S`：关中断、清零段寄存器，把 x86 从 8088 的 **16 位实模式**切到 80386 之后的 **32 位保护模式**，并打开 A20 地址线突破 1 MB 寻址。
2. `bootmain()`（bootmain.c）：把内核 ELF 从磁盘读进内存，并跳到 ELF 记录的入口。
3. `entry.S`：建好页目录、打开分页，再跳到 `main.c` 的 `main()`。
4. `main()`：初始化内存/进程/中断/文件等各模块，最后造出第一个用户进程 `initcode`。

### 实模式 → 保护模式（bootasm.S）

`bootasm.S` 开头先关中断并清零 `DS/ES/SS`，避免后续搬移 GDT 时旧值捣乱：

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

**A20 地址线**：8086 只有 20 根地址线（A0–A19），超过 1 MB 的地址会回绕到 0。要访问全部内存必须打开 A20 gate。控制方法有三种（8042 键盘控制器法、Fast A20 法、BIOS 中断法），正确做法应三种都试并验证。xv6 为求简单只用了最古老也最慢的 **8042 键盘控制器法**（`seta20.1`/`seta20.2`），且不做成功校验；而 Linux 三种都实现并带验证。

```asm
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

进入保护模式前要先铺好 **GDT**（全局描述符表）。xv6 用 `SEG_ASM` 宏造三个描述符：空描述符、代码段、数据段；代码段在 GDT 中索引为 1，故选择子为 `SEG_KCODE<<3`。

```asm
# Bootstrap GDT
.p2align 2                                # force 4 byte alignment
gdt:
  SEG_NULLASM                             # null seg
  SEG_ASM(STA_X|STA_R, 0x0, 0xffffffff)   # code seg
  SEG_ASM(STA_W, 0x0, 0xffffffff)         # data seg

gdtdesc:
  .word   (gdtdesc - gdt - 1)             # sizeof(gdt) - 1
  .long   gdt                             # address gdt
```

把 GDT 位置装入 `GDTR`，再把 `CR0` 的 PE 位置 1 即开启保护模式：

```asm
  lgdt    gdtdesc

  movl    %cr0, %eax
  orl     $CR0_PE, %eax
  movl    %eax, %cr0
```

切到保护模式后，流水线上可能还残留 16 位指令，必须用一个**长跳**刷新流水线、同时把段选择子写进 `CS`：

```asm
#define SEG_KCODE 1
ljmp    $(SEG_KCODE<<3), $start32

start32:
  # Set up the protected-mode data segment registers
  movw    $(SEG_KDATA<<3), %ax    # Our data segment selector
  movw    %ax, %ds                # -> DS: Data Segment
  movw    %ax, %es                # -> ES: Extra Segment
  movw    %ax, %ss                # -> SS: Stack Segment
  movw    $0, %ax
  movw    %ax, %fs                # -> FS
  movw    %ax, %gs                # -> GS

  # Set up the stack pointer and call into C.
  movl    $start, %esp 						# set 0x7c00
  call    bootmain
```

### 内核加载（bootmain.c）

`bootmain()` 相当于 Bootloader：先把内核 ELF 的第一页（4096 字节）读进 `0x10000` 的临时区，校验 `ELF_MAGIC`，再按程序头（`proghdr`）逐个把段搬进物理内存，最后跳到 ELF 头的入口地址。

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

ELF 头的程序头（`elfhdr`/`proghdr`）定义见 [ELF](/docs/CS/OS/xv6/ELF.md)；`bootmain` 只认 `paddr`/`filesz`/`memsz`，不解释段的 flag。

### 打开分页、进入 main（entry.S）

`entry.S` 在内核被加载的地址上直接跑：先开 4 MB 页大小扩展（PSE），把内核页目录 `entrypgdir` 装入 `CR3`，再开 `CR0_PG`（分页）与 `CR0_WP`（写保护），最后设好内核栈、用**间接跳**进 `main()`（间接跳是为让汇编生成 PC 无关指令）。

```asm
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

  # Jump to main(), and switch to executing at high addresses.
  mov $main, %eax
  jmp *%eax
```

`entrypgdir` 只映射了内核需要的低级地址（含 `0–4 MB` 与高地址内核区），足以让 `main()` 跑起来；之后 `kvmalloc()` 会建一张完整的**内核页表**接管（见 [memory](/docs/CS/OS/xv6/memory.md)）。

### 多核启动与 main()

`BSP`（启动核）的 `main()` 依次初始化各模块，最后 `userinit()` 造出第一个用户进程、`mpmain()` 进入 `scheduler()`：

```c
// Bootstrap processor starts running C code here.
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

`mpinit()` 解析 MP 表、数出有多少颗 CPU 并填 `cpus[NCPU]` 数组；`startothers()` 把 `entryother.S` 镜像搬到 `0x7000`，给每个 AP 准备好栈、入口 `mpenter`、临时页表 `entrypgdir`，再用 `lapicstartap()` 发启动 IPI 唤醒。AP 醒来后走 `mpenter → mpmain`，`mpmain` 做 `idtinit()`、把 `cpu->started` 置 1（通知 `startothers` 启动下一颗）、最后 `scheduler()` 开始调度：

```c
// Other CPUs jump here from entryother.S.
static void
mpenter(void)
{
  switchkvm();
  seginit();
  lapicinit();
  mpmain();
}

static void
mpmain(void)
{
  cprintf("cpu%d: starting\n", cpunum());
  idtinit();       // load idt register
  xchg(&cpu->started, 1); // tell startothers() we’re up
  scheduler();     // start running processes
}
```

## RISC-V 启动流程

RISC-V 版没有 BIOS、也没有实模式，硬件模型更简单：QEMU 以 `-kernel $K/kernel` 把内核放到 `0x80000000`，并把 `pc` 初值设为 `0x1000`（ROM 里的复位向量，最终跳到 `0x80000000`）。启动特权级的转换是理解这条路径的关键——**Machine 态（M）** 配置好一切后，用 `mret` 降权到 **Supervisor 态（S）** 才跑 `main()`。

### 每核栈与 _entry（entry.S）

`_entry` 给每个 hart 在 `stack0` 上分配 4096 字节栈（偏移 `hartid*4096`），然后 `call start`：

```asm
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

`stack0` 在 `start.c` 里声明：`__attribute__ ((aligned (16))) char stack0[4096 * NCPU];`。

### Machine 态降权（start.c）

`start()` 全程运行在 M 态，做的事包括：把 `mstatus.MPP` 设成 Supervisor（这样 `mret` 会回到 S 态）、把 `mepc` 设成 `main`、关分页（`satp=0`）、通过 `medeleg/mideleg` 把**所有异常与中断都委托给 S 态**、用 PMP 把全部物理内存交给 S 态、开时钟中断、把 `hartid` 存进 `tp` 寄存器，最后 `asm("mret")` 降权到 `main()`：

```c
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

`timerinit()` 负责请时钟中断（开 S 态 timer、`stimecmp` 设首个到期点）。CPU0 与各 AP 在 M 态醒来后都调 `start()`，但后续 `main()` 里靠 `cpuid()` 区分谁做全局初始化。

### 内核初始化与调度（main.c）

RISC-V 的 `main()` 只在 `cpu0` 上做全局初始化，其他 hart 自旋等 `started` 置 1 后再各自打开分页/陷阱向量/PLIC：

```c
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

注意 RISC-V 版用 `kvminit()/kvminithart()`（页表在 [memory](/docs/CS/OS/xv6/memory.md)）、`plicinit/plicinithart`（中断控制器在 [Interrupt](/docs/CS/OS/xv6/Interrupt.md)），与 x86 的 `kvmalloc()/picinit/ioapicinit` 对应但硬件不同。所有核最终都进入 `scheduler()` 开始调度（见 [proc](/docs/CS/OS/xv6/proc.md)）。

### 第一个用户进程（userinit）

`userinit()` 调 `allocproc()` 拿到第一个 `proc`，用 `uvmfirst()` 把 `initcode` 放进虚拟地址 `0x0` 的那一页，设置 `trapframe` 的 `epc=0`/`sp=PGSIZE`，命名为 `initcode`、当前目录 `/`、状态 `RUNNABLE`：

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

`initcode` 是 `user/initcode.S` 编出的二进制，它在用户态做的事就是 `exec("/init", 0)`：

```asm
# Initial process that execs /init.
# This code runs in user space.
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
```

`/init`（`user/init.c`）打开 console、用 `dup` 把 0/1/2 都指向它，然后 `fork()` 出子进程 `exec("sh", ...)`，父进程在循环里 `wait()` 回收孤儿进程；`sh`（`user/sh.c`）读命令行、对每条命令 `fork()+exec()`、父进程 `wait()`。至此 xv6 启动完成，用户看到 shell。

## x86 与 RISC-V 启动对比

| 维度 | x86 版 | RISC-V 版 |
| --- | --- | --- |
| 入口来源 | BIOS 载 512B `bootblock` 到 `0x7c00` | QEMU `-kernel` 放内核到 `0x80000000` |
| 模式切换 | 实模式 → 保护模式（A20/GDT/PE） | 无实模式，M 态直接起 |
| 分页开启 | `entry.S` 设 `entrypgdir`+`CR0_PG` | `start()` 设 `satp=0`，`main()` 内 `kvminithart()` 开 |
| 特权级 | 全程 ring 0（无用户/内核特权区分的硬件层） | M 态配置后 `mret` 降权到 S 态 |
| 中断控制器 | PIC + IOAPIC + LAPIC | PLIC + CLINT（核本地） |
| 多核唤醒 | `startothers()` + `lapicstartap()` | 各 hart 同跑 `start()`，自旋等 `started` |

两条移植在 C 层（`main → userinit → scheduler`）完全收敛，区别只在最底层的硬件初始化代码。理解启动能串起后续所有子系统：分页靠 [memory](/docs/CS/OS/xv6/memory.md)、trap 进入靠 [Interrupt](/docs/CS/OS/xv6/Interrupt.md)、`allocproc`/`scheduler` 靠 [proc](/docs/CS/OS/xv6/proc.md)、`exec` 装载靠 [ELF](/docs/CS/OS/xv6/ELF.md)。

## Links

- [xv6](/docs/CS/OS/xv6/xv6.md)
- [xv6 内存管理](/docs/CS/OS/xv6/memory.md)
- [xv6 中断与异常](/docs/CS/OS/xv6/Interrupt.md)
- [xv6 进程](/docs/CS/OS/xv6/proc.md)
- [xv6 系统调用](/docs/CS/OS/xv6/Syscall.md)
- [xv6 ELF 与 exec](/docs/CS/OS/xv6/ELF.md)

## References

1. [xv6 a simple, Unix-like teaching operating system](https://pdos.csail.mit.edu/6.828/2018/xv6/book-rev11.pdf)
2. [xv6操作系统启动过程(RISC-V)](https://juejin.cn/post/7308621051525120037)
3. [The Global Descriptor Table (osdev)](https://wiki.osdev.org/Global_Descriptor_Table)
4. [RISC-V Privileged Specification](https://riscv.org/specifications/privileged-isa/)
