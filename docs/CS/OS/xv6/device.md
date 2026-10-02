## Introduction

设备 I/O 是操作系统的重要职责：内核要把对硬件（串口、磁盘、时钟）的访问包装成统一的接口，让应用通过系统调用、而不是直接操作硬件寄存器来使用设备。xv6 用尽量少的代码演示了现代 OS 处理设备的几个核心概念：**内存映射 I/O、中断驱动收发、设备抽象表、DMA 描述符环、以及用缓冲区缓存吸收磁盘访问**。

本笔记对照 xv6 的两个移植版（x86 与 RISC-V）。主线以 RISC-V 版为主，硬件平台是 QEMU 提供的 virt 机器：16550 兼容 UART 与 virtio-blk 磁盘。整体启动与主循环见 [xv6](/docs/CS/OS/xv6/xv6.md)，中断进入机制见 [Interrupt](/docs/CS/OS/xv6/Interrupt.md)，页表与地址映射见 [memory](/docs/CS/OS/xv6/memory.md)。

## Memory-mapped I/O

RISC-V 版 xv6 不使用独立的 I/O 端口指令，设备寄存器被映射到固定的物理地址：

| 设备 | RISC-V 物理地址 | 用途 |
| --- | --- | --- |
| UART（16550） | `0x10000000`（UART0） | 控制台字符收发 |
| virtio-mmio 磁盘 | `0x10001000` | virtio-blk 块设备寄存器 |
| CLINT | `0x2000000` 起 | 核本地中断器、定时器 |
| PLIC | `0x0C000000` 起 | 平台级中断控制器，仲裁外部中断 |

所谓 MMIO，就是用普通的 load/store 指令访问这些"地址"：读某个地址等于读设备寄存器，写等于给设备下命令。`main.c` 里 `uartinit()`、`virtio_disk_init()` 本质都是对这些地址做读写。因为这些地址不是真正的内存，页表里要把它们映射为已映射、可直接访问（在内核页表建立时用 `PTE_R | PTE_W` 映射设备页，区别于普通 RAM 的缓存属性）。

x86 版则部分使用端口 I/O（`in`/`out` 指令，如 IDE 磁盘、老 UART），这是两种移植最直观的差别之一。

## UART Console

UART 是最简单的字符设备，演示了"发送可轮询、接收靠中断"的典型模式：

- **发送 `uartputc`**：把一个字符写进一个内核环形缓冲 `uart_tx_buf`；若缓冲空闲可直接发，否则当前进程睡眠等待。真正把字节送出的是 `uartstart()`，它在 UART 的发送保持寄存器空闲时逐字节写入。输出用轮询+缓冲，避免每个打印字符都陷入中断。
- **接收**：键盘输入/串口字符到达时触发 UART 中断，`uartintr()` 从 UART 数据寄存器读出每个字节，调用 `consoleintr()` 处理退格、行缓冲，攒成一行后唤醒等待输入的 `cat`/`sh` 等进程。
- 控制台把"设备"和"行规程（line discipline）"合在 `console.c`：读到的字符先进入行缓冲，`read` 系统调用通常在遇到换行后才返回一整行。

写寄存器前要检查 UART 的 LSR（line status register）位，判断是否可写/有数据可读，这是轮询型硬件握手的基本套路。

## Interrupt-driven I/O

设备就绪是异步事件，xv6 用中断而不是忙等来处理（除了上面发送路径的轻量轮询）。流程：

1. 设备完成某操作（一字节到达、磁盘读完成）后发出中断；
2. RISC-V 上中断经 **PLIC** 仲裁送到当前核，CPU 陷入 `trap`（见 [Interrupt](/docs/CS/OS/xv6/Interrupt.md)）；
3. `devinit`/PLIC 初始化时使能 UART、virtio 的中断号并设优先级；
4. 内核在 `devintr()` 里问 PLIC 是哪个设备（`UART0_IRQ` / `VIRTIO0_IRQ`），分发到 `uartintr()` 或 `virtio_disk_intr()`；
5. 处理函数唤醒等待该 I/O 的进程并 `yield` 回调度。

这样发起 I/O 的进程在等待时可以 `sleep` 让出 CPU，而不是空转——这就是**中断驱动 I/O 相对忙等轮询**的关键收益。在真实 Linux 上对应硬中断 + 下半部（软中断/NAPI），可对照 [network 收包路径](/docs/CS/OS/Linux/net/network.md)。

## virtio-blk Disk

xv6 RISC-V 的磁盘是 QEMU 的 **virtio-blk** 设备，用**virtqueue 描述符环 + DMA**工作，而非逐端口读写：

- 内存里准备好三个环：**descriptor table**（描述每个请求：命令、读写、缓冲区物理地址）、**available ring**（驱动放可用描述符给设备）、**used ring**（设备处理完回填）；
- 发起读写：把请求头（`virtio_blk_req`：类型+扇区号）与数据缓冲区的描述符挂到 available ring，然后写 virtio 的 queue-notify 寄存器**通知设备**；
- 设备通过 **DMA** 直接在这些物理缓冲区与磁盘之间搬运数据，完成后发中断；
- `virtio_disk_intr()` 检查 used ring，标记请求完成并 `wakeup` 等待者。

这是现代高性能设备的通用模式——**描述符环 + 共享内存 + 门铃通知 + DMA + 完成中断**，真实内核的 virtio、网卡多队列与此同构（可对照 [DPDK](/docs/CS/OS/Linux/IO/DPDK.md) 中 PMD 描述符环，区别是 DPDK 用轮询取代完成中断以追求线速）。

x86 版的磁盘则是经典 **IDE**：通过端口下发 LBA 扇区号和命令、轮询状态位等待、用中断通知完成，代码在老版本 `ide.c`，结构更简单但性能模型老旧。

## Device Switch Table

xv6 用一张设备分发表把"主设备号"映射到读写函数，体现 Unix "一切皆文件"的设备抽象：

```c
// kernel/file.h (示意)
struct devsw {
  int (*read)(int user_dst, uint64 dst, int n);
  int (*write)(int user_src, uint64 src, int n);
};
```

`consoleinit()` 注册 `console_read`/`console_write` 到设备表。设备在文件系统里以特殊 inode 表示（`type == T_DEVICE`，带主次设备号）。当 `read()`/`write()` 系统调用走到一个设备 inode 时，`fileread`/`filewrite` 不走常规文件路径，而是查 `devsw` 表调用对应设备函数。于是 shell 的 `echo hi > /dev/console` 与写普通文件走同一个 `write()` 入口——这就是统一设备抽象的目的。（Linux 上对应更复杂的字符设备/块设备层与 `file_operations`，可对照 [device model](/docs/CS/OS/Linux/dev/device.md)。）

## Buffer Cache

磁盘比内存慢几个数量级，xv6 对块设备再叠加一层**缓冲区缓存（buffer cache）**（`bio.c`）：

- 缓存以块（扇区）为单位，每个 `buf` 持有一份磁盘块的内存副本、有效/脏标志（`B_VALID`/`B_DIRTY`）和一把睡眠锁；
- 读：`bread()` 先查缓存，命中直接返回；未命中选一个空闲（或可回收）缓冲区，向 virtio 发起同步读；
- 写：改完标脏并 `bwrite()`，由块层发起 DMA 写；
- 缓存用哈希桶 + LRU 链表管理，并用每桶睡眠锁降低竞争（较新版本把单一大锁改为分桶锁），同时保证同一磁盘块在内存中只有一个 `buf`，天然串行化对该块的并发修改。

buffer cache 向上承接口志/文件系统（[file](/docs/CS/OS/xv6/file.md)），向下对接 virtio/IDE，是理解"文件系统如何不被磁盘速度拖垮"的关键一层；Linux 对应 page cache（[PageCache](/docs/CS/OS/Linux/mm/PageCache.md)）。

## Polling vs Interrupt

xv6 的取舍很好地展示了两种 I/O 同步方式：

- **轮询（poll）**：持续读状态寄存器直到就绪，实现简单、无切换延迟，但浪费 CPU；适合极频繁、要求确定低延迟或发送路径（xv6 UART 发送）；
- **中断**：设备就绪才打断 CPU，等待期间 CPU 可做别的事，适合稀疏、异步事件（UART 接收、磁盘完成）。

现代高吞吐网络（[DPDK](/docs/CS/OS/Linux/IO/DPDK.md) 的 PMD、Linux NAPI 在高负载时切轮询）会故意重新采用轮询，因为在百万 pps 下每包中断的开销反而是瓶颈——与 xv6 这个最小例子的权衡一脉相承。

## Links

- [xv6](/docs/CS/OS/xv6/xv6.md)
- [Interrupt](/docs/CS/OS/xv6/Interrupt.md)
- [memory](/docs/CS/OS/xv6/memory.md)
- [file](/docs/CS/OS/xv6/file.md)
- [Syscall](/docs/CS/OS/xv6/Syscall.md)
- [Operating Systems](/docs/CS/OS/OS.md)

## References

1. [xv6: a simple, Unix-like teaching operating system — Chapter 5 Interrupts and device drivers](https://pdos.csail.mit.edu/6.S081/2024/xv6/book-riscv-rev4.pdf)
2. [xv6-riscv source — kernel/uart.c, virtio_disk.c, console.c](https://github.com/mit-pdos/xv6-riscv)
3. [virtio Specification (blksz)](https://docs.oasis-open.org/virtio/virtio/v1.2/virtio-v1.2.html)
4. [6.S081 All-In-One](https://xv6.dgs.zone/)
