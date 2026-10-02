## Introduction

**rCore** 是一个用 **Rust** 编写、面向 **RISC-V** 平台的类 Unix 教学操作系统，源自清华大学的 rCore 与后续的 [rCore-Tutorial-v3](https://rcore-os.cn/rCore-Tutorial-Book-v3/index.html)。它和 MIT 的 [xv6](/docs/CS/OS/xv6/xv6.md) 一样属于"读完就能看懂全貌"的教学内核，但定位有鲜明差异：xv6 用 C、贴近传统 Unix 实现来讲解 OS 概念；rCore 用 Rust 的所有权/类型系统，在语言层面就规避空指针、数据竞争、缓冲区溢出等内存错误，并展示如何在没有标准库（`no_std`）的裸机环境里一步步搭出内核。

rCore-Tutorial 用增量实验的方式组织：从一个"能在 QEMU 上打印字符串"的最小裸机程序开始，每一章增加一个 OS 子系统，最终得到一个支持虚拟内存、任务调度、系统调用、文件系统、进程间通信的多任务内核。

## Rust on Bare Metal

在用户态，Rust 靠标准库（std）获得线程、文件、堆分配等能力；而内核运行在没有 OS 的裸机上，因此：

- `#![no_std]`：去掉标准库，只保留 **core**（语言核心：迭代器、Option/Result、原子操作等）与可选的 **alloc**（需自行提供全局堆分配器后才能用 `Vec/Box`）；
- 需要自己实现入口（`_start`）、panic 处理（`#[panic_handler]`），没有现成的 `main`；
- 用 `unsafe` 显式圈出直接操作硬件/裸内存的部分，其余安全代码借助所有权与借用检查在编译期保证内存安全与线程安全；
- 通过 **SBI（Supervisor Binary Interface）** 调用 M 模式提供的服务（关机、时钟、字符 I/O、核间中断），而不是自己直接操作最底层硬件。

这种"安全 Rust 为主、unsafe 集中封装硬件抽象"的结构，是 rCore 与 C 教学内核最大的工程区别。

## Privilege Levels and SBI

RISC-V 有三个特权级：

| 级别 | 名称 | rCore 中的角色 |
| --- | --- | --- |
| U | User | 用户程序运行于此，权限最低 |
| S | Supervisor | **内核运行于此**，管理页表/中断/系统调用 |
| M | Machine | OpenSBI 固件运行于此，为 S 模式提供底层服务 |

分层调用：U 态程序通过 `ecall` 陷入 S 态内核；S 态内核需要更底层操作（如关机、设置时钟、串口输出）时再通过 SBI 调用 M 态的 OpenSBI。这与真实系统里"内核 vs 固件/hypervisor"的分层一致。

## Lab Roadmap

rCore-Tutorial-v3 各章大致对应一个 OS 子系统（也是阅读主线）：

1. **应用程序与基本执行环境**：`no_std` 裸机程序、SBI 调用、`println!`、函数调用栈（与 QEMU 用法，见 [qemu](/docs/CS/OS/qemu.md)）。
2. **批处理操作系统**：多个应用一次性载入内存、顺序运行；特权级切换、S/U 态、`ecall` 系统调用的雏形。
3. **多道程序与协作式调度**：应用主动 `yield` 时切换任务，引入任务控制块与任务切换汇编。
4. **地址空间**：SV39 页表、内核/应用地址空间隔离、按需分配；对照 [xv6 memory](/docs/CS/OS/xv6/memory.md) 与 Linux 的 [vm](/docs/CS/OS/Linux/mm/vm.md)。
5. **进程与调度**：抢占式（时钟中断驱动切换）、任务状态机、进程抽象。
6. **文件系统与 I/O 重定向**：类 Unix 的 `open/read/write/close`、文件描述符表、管道、标准输入输出。
7. **进程间通信与并发**：管道、信号量/互斥等同步机制，对照内核[同步原语](/docs/CS/OS/Linux/Lock/README.md)。
8. **线程与并发安全**：内核里用 Rust 类型安全地管理共享状态。

## Trap and Syscall

rCore 的陷入处理是理解 RISC-V 内核的关键：

- 用户程序执行 `ecall`（系统调用）、遇到异常或外部/时钟中断时，硬件保存关键寄存器（sepc、scause、stval、sstatus）并跳到 S 态的 `trap entry`；
- 汇编入口保存通用寄存器到**内核栈上的 trap 上下文（TrapContext）**，再进入 Rust 的 `trap_handler`；
- `trap_handler` 根据 `scause` 分发：系统调用号在 `a7`、参数在 `a0–a5`，处理完把返回值写回 `a0`；时钟中断触发调度；
- 返回时恢复 TrapContext、`sret` 回到 U 态（sepc 指向被中断的指令）。

这套"汇编薄壳保存现场 + Rust 安全逻辑分发"的分层，与 [xv6 的 trap](/docs/CS/OS/xv6/Interrupt.md) 在概念上一一对应，只是寄存器与语言不同。系统调用入口语义见 [Syscall](/docs/CS/OS/xv6/Syscall.md)。

## Memory and Process

- **SV39 分页**：39 位虚拟地址、三级页表，页表项含 R/W/X/U/G 等标志位；rCore 用 Rust 结构体把物理页、页表项、地址区间（MapArea）封装成带生命周期的类型，借助所有权确保映射与释放成对出现。
- **任务控制块（TaskControlBlock）**：持有用户态 TrapContext（或内核栈位置）、内存地址空间（MemorySet）、进程号、fd 表、状态，等价于 Linux 的精简版 `task_struct`（对照 [Linux 进程](/docs/CS/OS/Linux/proc/process.md)）。
- **调度**：早期是协作式 yield，加入时钟中断后变为抢占式时间片轮转；任务切换只在内核态保存被调者的 callee-saved 寄存器，等价于一次协程式上下文切换。

## rCore vs xv6

| 维度 | rCore | [xv6](/docs/CS/OS/xv6/xv6.md) |
| --- | --- | --- |
| 语言 | Rust（`no_std`，安全/unsafe 分层） | C |
| 平台 | RISC-V（QEMU virt） | RISC-V / x86 双版 |
| 特权模型 | U/S/M，经 SBI/OpenSBI 调底层 | RISC-V 经 M 模式 SBI；x86 直接端口/中断 |
| 内存安全 | 语言层保证，unsafe 收敛到硬件抽象 | 靠程序员纪律 |
| 组织方式 | 逐章增量实验（Tutorial-v3） | 一本配套教材 + 完整内核 |
| 适合 | 想用现代系统语言学 OS、理解 no_std | 阅读经典 Unix 内核实现 |

二者互补：xv6 代码更贴近真实 Linux 的 C 风格与历史脉络，rCore 则展示现代类型系统如何让内核更安全、更易重构。

## Build and Run

用官方仓库在 QEMU 上运行（参考仓库 README 的环境依赖）：

```shell
git clone https://github.com/rcore-os/rCore-Tutorial-v3.git
cd rCore-Tutorial-v3
# 方式一：使用提供的 Docker 环境
make build_docker
make docker
# 方式二：本机安装 rust-src、qemu-system-riscv64、make 后
cd os && make run
```

`make run` 会编译内核与用户程序、启动 `qemu-system-riscv64`（通过 OpenSBI 加载内核），在终端看到各用户测试程序依次/并发执行。

## Links

- [Operating Systems](/docs/CS/OS/OS.md)
- [xv6](/docs/CS/OS/xv6/xv6.md)
- [xv6 Interrupt](/docs/CS/OS/xv6/Interrupt.md)
- [xv6 memory](/docs/CS/OS/xv6/memory.md)
- [qemu](/docs/CS/OS/qemu.md)
- [Linux vm](/docs/CS/OS/Linux/mm/vm.md)
- [Kernel Locking](/docs/CS/OS/Linux/Lock/README.md)

## References

1. [rCore-Tutorial-Book 第三版（官方中文教程）](https://rcore-os.cn/rCore-Tutorial-Book-v3/index.html)
2. [rCore-Tutorial-v3 GitHub](https://github.com/rcore-os/rCore-Tutorial-v3)
3. [RISC-V Privileged Architectures Specification](https://riscv.org/technical/specifications/)
4. [Rust Embedded Book / no_std overview](https://docs.rust-embedded.org/embedonomicon/)
