## Introduction

GDB, the GNU Project debugger, allows you to see what is going on `inside' another program while it executes -- or what another program was doing at the moment it crashed.


like LLDB in MacOS


based on `ptrace`(Linux)

[see man7 ptrace](https://man7.org/linux/man-pages/man2/ptrace.2.html)



```c
#include <sys/ptrace.h>
long ptrace(enum __ptrace_request request, pid_t pid,
                   void *addr, void *data);
```



follow process when fork
```shell
(gdb) set follow-fork-mode child 
(gdb) set follow-fork-mode parent 
(gdb) set follow-fork-mode ask 
```


## gdbtui


```shell
gdb -tui
gdbtui
```




## cgroup




## References

1. [GDB: The GNU Project Debugg](http://www.sourceware.org/gdb/)

