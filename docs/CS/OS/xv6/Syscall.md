## Introduction

系统调用是用户程序请求内核服务的唯一正规入口：开文件、建进程、收发数据都经由此机制。xv6 用"一条陷入指令 + 一张分发表"把用户态的函数调用翻译成内核函数调用，是全系统最简单的 syscall 实现之一，也是理解 [Interrupt](/docs/CS/OS/xv6/Interrupt.md)「trap 进入内核」最好的实例。

整条链路分三段：**用户态包装**（把调用号和参数放进寄存器，执行陷入指令）→ **内核 trap 入口**（保存现场、识别是系统调用、调用 `syscall()`）→ **分发与参数取回**（`syscall()` 查表、用 `argint/argaddr/argstr` 取参数、把返回值写回 `trapframe`）。

## 用户态包装（usys.S）

`user/usys.pl` 是个 Perl 脚本，为每个系统调用生成一小段汇编（即 `user/usys.S`）。它做的事只有两件：把调用号塞进指定寄存器，再执行陷入指令。

x86 版用 `int $T_SYSCALL`、调用号放 `eax`：

```perl
# x86: usys.pl 生成的片段
#define SYSCALL(name) \
  .globl name; \
  name: \
    movl $SYS_ ## name, %eax; \
    int $T_SYSCALL; \
    ret

SYSCALL(fork)
SYSCALL(exit)
# ... 其余同理
```

RISC-V 版用 `ecall`、调用号放 `a7`：

```perl
# RISC-V: usys.pl 生成的片段
#define SYSCALL(name) \
  .globl name; \
  name: \
    li a7, SYS_ ## name; \
    ecall; \
    ret

SYSCALL(fork)
SYSCALL(exit)
# ... 其余同理
```

`ecall`（RISC-V）/`int $T_SYSCALL`（x86）会触发一次**异常/trap**，CPU 切换到内核态并跳到内核 trap 向量（见 [Interrupt](/docs/CS/OS/xv6/Interrupt.md)）。trap 处理识别出这是系统调用后，把控制权交给 `syscall()`。

## 内核分发（syscall.c）

`syscall()` 从当前进程的 `trapframe` 读出**调用号**，用它对 `syscalls[]` 表做索引得到处理函数；返回值写回 `trapframe` 里存放**函数返回值**的槽位（RISC-V 的 `a0` / x86 的 `eax`）。

x86 取号在 `tf->eax`，返回值也回写 `eax`：

```c
// syscall.c (x86)
void
syscall(void)
{
  int num;

  num = proc->tf->eax;
  if(num > 0 && num < NELEM(syscalls) && syscalls[num]) {
    proc->tf->eax = syscalls[num]();
  } else {
    cprintf("%d %s: unknown sys call %d\n",
            proc->pid, proc->name, num);
    proc->tf->eax = -1;
  }
}
```

RISC-V 取号在 `trapframe->a7`，返回值回写 `trapframe->a0`：

```c
// syscall.c (RISC-V)
void
syscall(void)
{
  int num;
  struct proc *p = myproc();

  num = p->trapframe->a7;
  if(num > 0 && num < NELEM(syscalls) && syscalls[num]) {
    p->trapframe->a0 = syscalls[num]();
  } else {
    printf("%d %s: unknown sys call %d\n",
            p->pid, p->name, num);
    p->trapframe->a0 = -1;
  }
}
```

`syscalls[]` 是一张「调用号 → 处理函数」的表，编译期由 `SYS_xxx` 常量下标填充，例如 `[SYS_fork] sys_fork`、`[SYS_exec] sys_exec`。

## 参数取回（argint / argaddr / argstr）

陷入时，用户传进来的参数就躺在 `trapframe` 的寄存器槽里。内核不直接读用户栈，而是用一组 helper 从 `trapframe` 取第 `n` 个参数。RISC-V 版先经 `argraw` 按序号挑寄存器 `a0–a5`：

```c
// syscall.c (RISC-V)
static int
argraw(int n, uint64 *ip)
{
  struct proc *p = myproc();
  switch(n){
  case 0: *ip = p->trapframe->a0; break;
  case 1: *ip = p->trapframe->a1; break;
  case 2: *ip = p->trapframe->a2; break;
  case 3: *ip = p->trapframe->a3; break;
  case 4: *ip = p->trapframe->a4; break;
  case 5: *ip = p->trapframe->a5; break;
  default: return -1;
  }
  return 0;
}

int argint(int n, int *ip) {
  uint64 val;
  if(argraw(n, &val) < 0) return -1;
  *ip = (int)val;
  return 0;
}

int argaddr(int n, uint64 *ip) {
  uint64 val;
  if(argraw(n, &val) < 0) return -1;
  *ip = val;
  return 0;
}

int argstr(int n, char *buf, int max) {
  uint64 addr;
  int maxlen;
  if(argaddr(n, &addr) < 0 || argint(n+1, &maxlen) < 0)
    return -1;
  return fetchstr(addr, buf, max);   // 从用户空间拷贝字符串
}
```

- `argint`：取第 `n` 个**32 位整数**参数（如文件描述符、长度）。
- `argaddr`：取第 `n` 个**指针/地址**参数（如缓冲区地址、字符串指针）。
- `argstr`：取第 `n` 个**字符串指针**并顺带把第 `n+1` 个当作长度上限，从用户空间安全拷到内核（`fetchstr` 防止越界读）。

x86 版逻辑完全相同，只是 `argraw` 改从 `tf->ebx/ecx/edx/esi/edi/ebp` 取值、调用号在 `tf->eax`。所有 sys_* 处理函数开头都先 `argint/argaddr` 把参数搬到内核栈，再执行真正逻辑；返回值由 `syscall()` 统一写回 `trapframe`。

## x86 与 RISC-V 差异

| 维度 | x86 | RISC-V |
| --- | --- | --- |
| 陷入指令 | `int $T_SYSCALL` | `ecall` |
| 调用号寄存器 | `eax`（`tf->eax`） | `a7`（`trapframe->a7`） |
| 返回值寄存器 | `eax` | `a0` |
| 参数寄存器 | `ebx, ecx, edx, esi, edi, ebp` | `a0–a5` |

差异只在寄存器与指令层面，分发表 `syscalls[]` 和各 `sys_*` 处理函数的 C 代码在两个移植里是同一份。

## 系统调用清单

xv6（book-rev11）暴露约 21 个系统调用，定义在 `syscall.h` 的 `SYS_*`：

| 调用 | 处理函数 | 作用 |
| --- | --- | --- |
| `fork` | `sys_fork` | 复制当前进程 |
| `exit` | `sys_exit` | 结束当前进程 |
| `wait` | `sys_wait` | 等待子进程结束 |
| `pipe` | `sys_pipe` | 建匿名管道 |
| `read` | `sys_read` | 从 fd 读 |
| `kill` | `sys_kill` | 向进程发信号（xv6 仅用于杀进程） |
| `exec` | `sys_exec` | 装载并运行新程序（见 [ELF](/docs/CS/OS/xv6/ELF.md)） |
| `fstat` | `sys_fstat` | 取文件元信息 |
| `chdir` | `sys_chdir` | 切换当前目录 |
| `dup` | `sys_dup` | 复制 fd |
| `getpid` | `sys_getpid` | 取进程号 |
| `sbrk` | `sys_sbrk` | 调整进程内存大小（见 [memory](/docs/CS/OS/xv6/memory.md)） |
| `sleep` | `sys_sleep` | 休眠若干时钟滴答 |
| `uptime` | `sys_uptime` | 取系统启动后的滴答数 |
| `open` | `sys_open` | 打开文件 |
| `write` | `sys_write` | 向 fd 写 |
| `mknod` | `sys_mknod` | 建设备节点 |
| `unlink` | `sys_unlink` | 删文件/目录项 |
| `link` | `sys_link` | 建硬链接 |
| `mkdir` | `sys_mkdir` | 建目录 |
| `close` | `sys_close` | 关闭 fd |

`open/read/write/close` 与文件系统的关系见 [file](/docs/CS/OS/xv6/file.md)；`fork/exec/wait` 与进程生命周期见 [proc](/docs/CS/OS/xv6/proc.md)。

## Links

- [xv6](/docs/CS/OS/xv6/xv6.md)
- [xv6 中断与异常](/docs/CS/OS/xv6/Interrupt.md)
- [xv6 进程](/docs/CS/OS/xv6/proc.md)
- [xv6 文件系统](/docs/CS/OS/xv6/file.md)
- [xv6 ELF 与 exec](/docs/CS/OS/xv6/ELF.md)
- [xv6 内存管理](/docs/CS/OS/xv6/memory.md)

## References

1. [xv6 a simple, Unix-like teaching operating system](https://pdos.csail.mit.edu/6.828/2018/xv6/book-rev11.pdf)
2. [xv6 中文文档](https://th0ar.gitbooks.io/xv6-chinese/content/)
