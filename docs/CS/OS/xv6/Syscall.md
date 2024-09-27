## Introduction

文件user/usys.pl生成user/usys.S，usys.S就是用来完成从用户态到内核态的代码。从代码可见，它是通过ecall产生一个异常来进入内核态。只要把usys.S生成的二进制文件链接进用户程序里，就可以使用系统调用了

```c
// syscall.c
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



## Links

- [xv6](/docs/CS/OS/xv6/xv6.md)