## Introduction

GDB, the GNU Project debugger, allows you to see what is going on `inside' another program while it executes -- or what another program was doing at the moment it crashed.
GDB can do four main kinds of things (plus other things in support of these) to help you catch bugs in the act:

- Start your program, specifying anything that might affect its behavior.
- Make your program stop on specified conditions.
- Examine what has happened, when your program has stopped.
- Change things in your program, so you can experiment with correcting the effects of one bug and go on to learn about another.



GDB主要由三个子系统组成 分别是

- user interface
- symbol handling
- target system handling








like LLDB clang in MacOS


based on `ptrace`(Linux)

[see man7 ptrace](https://man7.org/linux/man-pages/man2/ptrace.2.html)



```c
#include <sys/ptrace.h>
long ptrace(enum __ptrace_request request, pid_t pid,
                   void *addr, void *data);
```



```c
gcc -
```





follow process when fork
```shell
(gdb) set follow-fork-mode child 
(gdb) set follow-fork-mode parent 
(gdb) set follow-fork-mode ask 
```


### gdbgui


gdbgui
```shell

apt install python3-pip
pip3 install gdbgui --upgrade
```


## gdbtui

```shell
gdb -tui
gdbtui
```







## Breakpoint

Breakpoint的实现分两种 硬件和软件



软件断点






## Links

- [GCC]()
- [LLDB](/docs/)

## References

1. [GDB: The GNU Project Debugg](http://www.sourceware.org/gdb/)

