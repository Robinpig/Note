## Introduction

本目录收拢 Linux **从加电到用户态 1 号进程**的完整链路。它是 `Linux/` 下唯一一条**时间轴单向**的链路——没有并发分支、没有回退，每一段只把控制权交给下一段，直到 `execve("/sbin/init")` 把用户态接管过来。

这条链在源码里横跨三种完全不同的执行环境：**固件提供的实模式下 BIOS 调用**、**内核自举期只有汇编和临时页表的原始状态**、**`start_kernel()` 之后的完整内核环境**。越靠前的阶段能用的东西越少——早期连堆都没有、不能调用任何依赖 slab 的函数，这也解释了内核为什么必须准备 `early_param`、`memblock`、`fixmap` 这一整套"还没准备好时的替代品"。

看这条链有个额外好处：它把前面几条纵向链路（[进程](/docs/CS/OS/Linux/proc/README.md)、[内存](/docs/CS/OS/Linux/mm/README.md)、[网络](/docs/CS/OS/Linux/net/README.md)）的**初始化顺序**交代清楚了——为什么某些子系统必须早于另一些，答案就在这里的 initcall 分级里。

## 全景：五段接力

**① 固件**。上电自检后，BIOS/UEFI 按启动顺序找到可引导设备，把引导扇区读进内存并交出控制权。这个阶段系统还处于实模式，只能寻址 1 MiB。

**② 引导器**。它的任务是把内核镜像送进内存、整理好内核需要的参数，然后跳转。PC 上是 GRUB 这类通用引导器；嵌入式场景则是 [U-Boot](/docs/CS/OS/Linux/boot/U-Boot.md) 这类专注特定硬件的实现——它同时要负责初始化 SDRAM、串口等内核还没能力碰的外设。参数形式因架构而异：x86 是 `boot_params` 结构（传统上叫 zeropage），ARM64 则是通过 `x0` 寄存器传进来的 FDT。

**③ 内核自举**。进入内核自己的入口代码，此时 MMU 还没开。x86 从 `arch/x86/kernel/head_64.S` 进入，要先处理 A20 地址线、建立临时页表、切到长模式；ARM64 从 `arch/arm64/kernel/head.S` 的 `__HEAD` 开始，在关闭 MMU 的情况下跑完基础初始化（打开 MMU、建部分页表、准备运行堆栈），并把 bootloader 传来的 FDT 存到 `__fdt_pointer`。[Start](/docs/CS/OS/Linux/boot/Start.md) 记录了这段汇编的具体动作，以及链接脚本 `vmlinux.lds.S` 如何把成千上万个 `.o` 合并成一个 `vmlinux`。

**④ `start_kernel()`**。汇编跑完后的第一个 C 函数。它内部依次完成早期参数解析、内存探测、`setup_arch()`、以及各类子系统的早期初始化，最终走到 `rest_init()`。[init](/docs/CS/OS/Linux/boot/init.md) 顺着 `arch/x86/boot/main.c` → `i386_start_kernel()` → `start_kernel()` → `rest_init()` → `kernel_init()` 往下读，把这段"内核自己把自己装配起来"的过程逐层展开。

**⑤ `rest_init()` 与 1 号进程**。`rest_init()` 做三件事：把当前上下文交给 idle 线程、创建 `kthreadd`（2 号，负责后续所有内核线程的派生）、创建 `kernel_init`（1 号）。`kernel_init` 里跑完 `do_initcalls()` 后，就 `execve` 掉自己变成用户态第一个进程——至此内核初始化结束，后续的挂载硬盘、加载模块都改用系统调用完成了。

## initcall：初始化顺序为什么是硬约束

上面第 ⑤ 步里 `do_initcalls()` 是整条链最耗时的一段，也是理解"内核为什么能有序启动"的关键。所有用 `xxx_initcall` 注册的函数被分成若干 **level**，按 level 从低到高依次调用；`module_init` 编进内核后对应的其实是 `device_initcall`，处于较后的 level。

[arm](/docs/CS/OS/Linux/boot/arm.md) 用 ARM64 的启动过程把这件事讲得最透：`of_platform_default_populate_init` 处在 `arch_initcall_sync`（3s level），它扫描 `setup_arch()` 建好的 `device_node` 树、为匹配 `of_default_bus_match_table` 的节点创建 `platform_device`；而 I2C/SPI 这类总线控制器本身是 `platform_device`，用 level 4 初始化，正好卡在"设备已创建、client driver 未 probe"之间——**这个位置不是随意的，选错 level 就会在自己的依赖还没初始化时被调用**。

同一篇里还有一个容易被忽略的差异：level 后缀带 `s` 的（sync）比不带 `s` 的后执行；`rootfs_initcall` 则插在 level 5 和 6 之间，专门用来起一个线程**异步**解压 initramfs，缩短启动时间。

## 镜像：vmlinux 与 bzImage 的分工

引导器加载的 `bzImage` 由两个独立编译的产物拼成，理解这一点对排查启动初期问题很关键：

- **`setup.bin`**——由 `arch/x86/boot/` 下的 `main.c`、`a20.c`、`video*.c` 等编译链接而来（`setup.elf` 经 `objcopy -O binary` 得到）。它跑在**实模式**，负责探测内存、设置显示模式这些还离不开 BIOS 的事。
- **`vmlinux.bin`**——由 `compressed/vmlinux` 经 objcopy 得到，是**压缩后的保护模式内核**，前面还带一小段自解压 stub。

v7.2.7 里两者的拼接已经很朴素（`arch/x86/boot/Makefile:61`）：

```makefile
quiet_cmd_image = BUILD   $@
      cmd_image = (dd if=$< bs=4k conv=sync status=none; cat $(filter-out $<,$(real-prereqs))) >$@
```

`dd` 先把 `setup.bin` 补齐到 4 KiB 边界，`cat` 再接上压缩内核——**不再需要专门的拼接程序**。两段之间靠 `zoffset.h` 通信：构建时用 `nm` 从 `compressed/vmlinux` 里抽出 `startup_32`、`_text`、`_end`、`z_*` 等符号地址，生成宏给 `header.o` 用，这样实模式代码才能知道压缩内核的入口在哪、有多大。

> 顺带说明：[Start](/docs/CS/OS/Linux/boot/Start.md) 里提到的 `arch/x86/boot/tools/build` 在当前内核上已不存在，该目录连同这个 C 拼接程序都被移除了。如果你照着旧资料去找它，会扑空。

从源码到 `bzImage` 的完整过程——`.config` 怎么选、`make` 各目标的关系、各架构的差异——见 [内核构建](/docs/CS/OS/Linux/build.md)。

调试启动崩溃时要注意区分：**`vmlinux` 是带完整符号表的 ELF**，`bzImage` 是给引导器用的压缩镜像。`gdb`、`addr2line` 这类工具只能吃前者。

## 观测启动过程

启动阶段的问题最难查，因为此时磁盘、网络、日志系统都还不可用。两个内核参数直接可用（均见 `Documentation/admin-guide/kernel-parameters.txt`）：

- `initcall_debug` —— 逐个打印 initcall 的耗时与执行顺序，做启动时间优化或定位 initcall 崩溃时首选；
- `earlycon=` —— 在真正的 console 驱动就位之前就建立输出通道，卡在 `start_kernel()` 早期时这是唯一能看到日志的途径。

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [BootLoader](/docs/CS/OS/BootLoader.md)
- [BIOS](/docs/CS/OS/BIOS.md)
