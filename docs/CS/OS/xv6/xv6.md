## Introduction

1. [Install QEMU](/docs/CS/OS/qemu.md)
2. git clone git://github.com/mit-pdos/xv6-public.git 

m1 mac

```shell

brew tap riscv/riscv
brew install riscv-tools
export PATH=$PATH:/usr/local/opt/riscv-gnu-toolchain/bin
```

```shell

brew install qemu
```

测试安装

```shell
riscv64-unknown-elf-gcc --version
#riscv64-unknown-elf-gcc (GCC) 10.2.0

qemu-system-riscv64 --version
#QEMU emulator version 5.2.0
```

下载代码
```shell

git clone git://github.com/mit-pdos/xv6-riscv.git

cd /path/to/xv6-riscv
make qemu
```
会输出一大堆编译信息，最后：
```
xv6 kernel is booting
init: starting sh
```


退出虚拟机时，按 c-A X（先按下 control 键不放开，接着按 A 键，送开两个键，然后按 X 键）。


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
2. 修改 Makefile
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
 





## Links

- [Operating Systems](/docs/CS/OS/OS.md)


## References

1. [xv6 a simple, Unix-like teaching operating system](https://pdos.csail.mit.edu/6.828/2018/xv6/book-rev11.pdf)