## Introduction



[Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)

[Hackintosh](/docs/CS/OS/mac/Hackintosh.md)

从Mac OS X 10.5开始，Apple引入了地址空间配置随机加载(ASLR)机制。在每次程序执行的过程中，程序在内存中的开始地址，堆、栈、库的地址都会随机化，这样可以更好地保护不受攻击者攻击



```c
//test.c
#include <stdlib.h>
#include <stdio.h>

int main()
{
    int a = 0;
    printf("The address in the stack is:\t0x%x\n", &a);
    return 0;
}
```
我们在终端下用clang对其编译
```shell
clang test.c -o test
```



我们可以发现，每次运行时， a 的逻辑地址都不同。似乎是一个随机值加上一个固定的偏移量。这就是ASLR的作用


在ASLR中我们可以看到，大部分变量在每次运行时的逻辑地址都不一样。那么，我们在汇编层面访问这些变量时，就不能直接访问一个固定的逻辑地址。
因此，我们在汇编语言中有许多技巧可以生成位置无关代码(Position Independent Code, PIC).
这些代码中没有一处会直接访问固定的逻辑地址。由位置无关代码编译生成的可执行文件称为位置无关可执行文件(Position Independent Executable, PIE).


mac使用 launchctl 管理app
```shell
launchctl list
launchctl stop
launchctl start

```

查看端口占用
```shell
#命令格式：lsof -i :端口
lsof -i:8080
```

## Issues

MBP长期没关机 突然跨设备Handoff失效 需要把mac重启

## Links

